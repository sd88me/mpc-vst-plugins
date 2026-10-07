/* vitOTTx for MPC: the mpc_engine() glue (wrapper/engine.h) around Vital's multiband OTT compressor,
 * as vendored from vitOTTx (src/VENDORED.md). An insert effect: process() filters 128-frame int16 blocks.
 *
 * Parameters follow vitOTTx's PluginProcessor::updParams(): depth/upward/downward scale the per-band ratios,
 * time drives both attack and release, band thresholds and ratios keep vitOTTx's defaults (not exposed).
 * Meters: per band, the input and output level (vitOTTx's mean-squared outputs, in dB) as a step index
 * 0..METER_STEPS-1 over METER_MIN_DB..METER_MAX_DB, plus the output level as text; "display_rev" changes
 * whenever one of them moves, so the wrapper (HAS_DISPLAY_REV) tells MPC to redraw. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <new>
extern "C" {
#include "engine.h"
}
#include "vital_dsp/compressor.h"
#include "vital_dsp/utilities/smooth_value.h"

namespace {

const int METER_STEPS = 24;
const float METER_MIN_DB = -60.0f, METER_MAX_DB = 0.0f;
const int NVALS = vital::MultibandCompressor::kNumInputs - 1;

enum { P_DEPTH, P_TIME, P_IN, P_OUT, P_UP, P_DOWN, P_HGAIN, P_MGAIN, P_LGAIN, P_MIX, P_LXO, P_HXO, NP };
const char *const KEYS[NP] = {"depth", "time", "in_gain", "out_gain", "upward", "downward",
                              "h_gain", "m_gain", "l_gain", "mix", "low_xover", "high_xover"};
const float DEFAULTS[NP] = {100, 100, 0, 0, 100, 100, 16.3f, 11.7f, 16.3f, 100, 120, 2500};

/* meters in band order H, M, L (as drawn); vitOTTx band index 0 = low, 1 = mid, 2 = high */
const char *const BAND[3] = {"h", "m", "l"};

struct Ott {
    vital::MultibandCompressor comp;
    vital::Output sig_in;
    vital::SmoothValue *vals[NVALS];
    volatile float p[NP];
    float in_db[3], out_db[3];      /* by drawn band (H, M, L) */
    volatile int in_step[3], out_step[3];
    volatile unsigned rev;
    int meter_div;
};

void upd(Ott *o) {
    typedef vital::MultibandCompressor M;
    float depth = o->p[P_DEPTH] / 100.0f, up = o->p[P_UP] / 100.0f, down = o->p[P_DOWN] / 100.0f;
    float t = o->p[P_TIME] / 200.0f;                 /* 100 % = vitOTTx's default 0.5 */
    float lx = o->p[P_LXO], hx = o->p[P_HXO];
    if (lx > hx) lx = hx;
    struct { int in; float v; } s[] = {
        {M::kLowLowerThreshold, -35.0f}, {M::kLowUpperThreshold, -28.0f},
        {M::kBandLowerThreshold, -36.0f}, {M::kBandUpperThreshold, -25.0f},
        {M::kHighLowerThreshold, -35.0f}, {M::kHighUpperThreshold, -30.0f},
        {M::kLowLowerRatio, 0.8f * depth * up}, {M::kLowUpperRatio, 0.9f * depth * down},
        {M::kBandLowerRatio, 0.8f * depth * up}, {M::kBandUpperRatio, 0.857f * depth * down},
        {M::kHighLowerRatio, 0.8f * depth * up}, {M::kHighUpperRatio, 1.0f * depth * down},
        {M::kAttack, t}, {M::kRelease, t},
        {M::kLowOutputGain, o->p[P_LGAIN]}, {M::kBandOutputGain, o->p[P_MGAIN]}, {M::kHighOutputGain, o->p[P_HGAIN]},
        {M::kLMFrequency, lx}, {M::kMHFrequency, hx}, {M::kMix, o->p[P_MIX] / 100.0f},
    };
    for (auto &e : s) o->vals[e.in - 1]->set(e.v);
    bool lc = lx <= 21.0f, hc = hx >= 17500.0f;      /* vitOTTx: drop a band whose crossover is at the end */
    int mode = lc && hc ? M::kSingleBand : lc ? M::kHighBand : hc ? M::kLowBand : M::kMultiband;
    o->vals[M::kEnabledBands - 1]->set(mode);
}

int step_of(float db) {
    int s = (int)floorf((db - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB) * (METER_STEPS - 1) + 0.5f);
    return s < 0 ? 0 : s >= METER_STEPS ? METER_STEPS - 1 : s;
}

float ms_db(float ms) { return 10.0f * log10f(ms > 1e-9f ? ms : 1e-9f); }

void meters(Ott *o) {
    typedef vital::MultibandCompressor M;
    const int in_out[3] = {M::kHighInputMeanSquared, M::kBandInputMeanSquared, M::kLowInputMeanSquared};
    const int out_out[3] = {M::kHighOutputMeanSquared, M::kBandOutputMeanSquared, M::kLowOutputMeanSquared};
    bool moved = false;
    for (int b = 0; b < 3; b++) {
        vital::poly_float mi = o->comp.output(in_out[b])->buffer[0], mo = o->comp.output(out_out[b])->buffer[0];
        float di = ms_db(fmaxf(mi[0], mi[1])), dout = ms_db(fmaxf(mo[0], mo[1]));
        o->in_db[b] = di;
        o->out_db[b] = dout;
        int si = step_of(di), so = step_of(dout);
        if (si != o->in_step[b] || so != o->out_step[b]) moved = true;
        o->in_step[b] = si;
        o->out_step[b] = so;
    }
    if (moved) o->rev++;
}

void *create(const char *) {
    Ott *o = new (std::nothrow) Ott();
    if (!o) return nullptr;
    for (int i = 0; i < NP; i++) o->p[i] = DEFAULTS[i];
    for (int b = 0; b < 3; b++) { o->in_db[b] = o->out_db[b] = -200.0f; o->in_step[b] = o->out_step[b] = 0; }
    o->comp.plug(&o->sig_in, vital::MultibandCompressor::kAudio);
    for (int i = 0; i < NVALS; i++) {
        o->vals[i] = new vital::SmoothValue(0);
        o->comp.plug(o->vals[i], i + 1);
    }
    upd(o);
    for (int i = 0; i < NVALS; i++) o->vals[i]->setHard(o->vals[i]->value());
    o->comp.setSampleRate(44100);
    o->comp.reset(vital::constants::kFullMask);
    return o;
}

void destroy(void *inst) {
    Ott *o = (Ott *)inst;
    for (int i = 0; i < NVALS; i++) delete o->vals[i];
    delete o;
}

void midi(void *, const uint8_t *, int) {}

void set_param(void *inst, const char *key, const char *val) {
    Ott *o = (Ott *)inst;
    for (int i = 0; i < NP; i++)
        if (!strcmp(key, KEYS[i])) { o->p[i] = (float)atof(val); return; }
    /* meters are display only, but a host set (a loaded project, a test) shows until the next meter update */
    for (int b = 0; b < 3; b++) {
        char k[16];
        int v = atoi(val);
        v = v < 0 ? 0 : v >= METER_STEPS ? METER_STEPS - 1 : v;
        snprintf(k, sizeof k, "%s_in", BAND[b]);
        if (!strcmp(key, k)) { o->in_step[b] = v; return; }
        snprintf(k, sizeof k, "%s_out", BAND[b]);
        if (!strcmp(key, k)) { o->out_step[b] = v; return; }
    }
}

int get_param(void *inst, const char *key, char *buf, int n) {
    Ott *o = (Ott *)inst;
    for (int i = 0; i < NP; i++)
        if (!strcmp(key, KEYS[i])) return snprintf(buf, n, "%.3f", (double)o->p[i]);
    if (!strcmp(key, "display_rev")) return snprintf(buf, n, "%u", o->rev);
    for (int b = 0; b < 3; b++) {
        char k[16];
        snprintf(k, sizeof k, "%s_in", BAND[b]);
        if (!strcmp(key, k)) return snprintf(buf, n, "%d", o->in_step[b]);
        snprintf(k, sizeof k, "%s_out", BAND[b]);
        if (!strcmp(key, k)) return snprintf(buf, n, "%d", o->out_step[b]);
        snprintf(k, sizeof k, "%s_level", BAND[b]);
        if (!strcmp(key, k)) {
            float d = o->out_db[b];
            return d <= -99.5f ? snprintf(buf, n, "-inf") : snprintf(buf, n, "%.0f", (double)d);
        }
    }
    return 0;
}

void process(void *inst, const int16_t *in, int16_t *out, int frames) {
    Ott *o = (Ott *)inst;
    upd(o);
    float gi = powf(10.0f, o->p[P_IN] / 20.0f) / 32768.0f, go = powf(10.0f, o->p[P_OUT] / 20.0f) * 32767.0f;
    for (int off = 0; off < frames;) {
        int ns = frames - off < vital::kMaxBufferSize ? frames - off : vital::kMaxBufferSize;
        for (int i = 0; i < NVALS; i++) o->vals[i]->process(ns);
        vital::mono_float *buf = (vital::mono_float *)o->sig_in.buffer;
        for (int i = 0; i < ns; i++) {
            vital::poly_float &v = o->sig_in.buffer[i];
            v = 0.0f;
            buf[vital::poly_float::kSize * i + 0] = in[2 * (off + i)] * gi;
            buf[vital::poly_float::kSize * i + 1] = in[2 * (off + i) + 1] * gi;
        }
        o->comp.process(ns);
        const vital::mono_float *ob = (const vital::mono_float *)o->comp.output(vital::MultibandCompressor::kAudioOut)->buffer;
        for (int i = 0; i < ns; i++)
            for (int c = 0; c < 2; c++) {
                float s = ob[vital::poly_float::kSize * i + c] * go;
                if (!(s == s)) s = 0.0f;   /* NaN guard */
                out[2 * (off + i) + c] = (int16_t)(s > 32767.0f ? 32767 : s < -32768.0f ? -32768 : lrintf(s));
            }
        off += ns;
    }
    if (++o->meter_div >= 4) {   /* ~12 ms: plenty for a 100 ms display poll */
        o->meter_div = 0;
        meters(o);
    }
}

void render(void *, int16_t *out, int frames) { memset(out, 0, (size_t)frames * 4); }

const mpc_engine_t ENGINE = {create, destroy, midi, set_param, get_param, render, process};

}  // namespace

extern "C" const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
