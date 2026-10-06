/* Blueberry-PE: a four-voice instrument modelled on the DSI Poly Evolver's voice (manual v1.4 and the DSP 3.5 firmware tables).
 * The program is the instrument's own 192 bytes (128 parameters + 4 x 16 sequencer steps), so its SysEx dumps load as they are.
 *
 * One voice = two analog-style channels (Osc 1 + Osc 3 left, Osc 2 + Osc 4 right) into a 2/4-pole lowpass and a VCA per channel,
 * then the DSP side: output pan, tuned feedback, 4-pole highpass, distortion with noise gate, a three-tap delay and the output hack.
 * Modulation (3 envelopes, 4 LFOs, 4 mod slots, fixed controller routes, 4 x 16 sequencer) is computed every CTL samples. */
#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include "engine.h"
#include "patch_tab.h"
#include "curves.h"
#include "syx.h"
#include "waves.h"
#include "presets.h"

#define FS 44100.0f
#define MAXV 8
#define CTL 8
#define DT (CTL / FS)
#define DLEN 65536           /* delay memory per voice: > 1 s at 44.1 kHz */
#define FBLEN 4096           /* tuned feedback line per channel: C0 = 2697 samples */
#define MAXBANKS 48
#define PATHLEN 512

static const char *const DEST_NAMES[76] = {"Off", "Osc1 Freq", "Osc2 Freq", "Osc3 Freq", "Osc4 Freq", "OscAll Freq", "Osc1 Level",
    "Osc2 Level", "Osc3 Level", "Osc4 Level", "OscAll Lev", "Noise Level", "ExtIn Level", "Osc1 PW", "Osc2 PW", "OscAll PW",
    "FM 4>3", "FM 3>4", "RM 4>3", "RM 3>4", "Lowpass", "LP Split", "Resonance", "Highpass", "VCA Level", "Output Pan",
    "FBack Freq", "FBack Amt", "Delay1 Time", "Delay2 Time", "Delay3 Time", "DlyAll Time", "Delay1 Amt", "Delay2 Amt",
    "Delay3 Amt", "DlyAll Amt", "Delay FB1", "Delay FB2", "LFO1 Freq", "LFO2 Freq", "LFO3 Freq", "LFO4 Freq", "LFOAll Freq",
    "LFO1 Amt", "LFO2 Amt", "LFO3 Amt", "LFO4 Amt", "LFOAll Amt", "Env1 Amt", "Env2 Amt", "Env3 Amt", "EnvAll Amt",
    "Env1 Attack", "Env2 Attack", "Env3 Attack", "EnvAll Att", "Env1 Decay", "Env2 Decay", "Env3 Decay", "EnvAll Dec",
    "Env1 Rel", "Env2 Rel", "Env3 Rel", "EnvAll Rel", "Left LP", "Right LP", "Left Res", "Right Res", "Distortion",
    "Seq Clock", "MIDI Note", "MIDI Vel", "MIDI ModWh", "MIDI Press", "MIDI Breath", "MIDI Foot"};
static const char *const SRC_NAMES[25] = {"Off", "Seq 1", "Seq 2", "Seq 3", "Seq 4", "LFO 1", "LFO 2", "LFO 3", "LFO 4",
    "Filter Env", "VCA Env", "Env 3", "ExtIn Peak", "ExtIn EnvF", "Pitch Bend", "Mod Wheel", "Pressure", "Breath", "Foot",
    "Velocity", "Key Number", "Expression", "Noise", "Osc 3", "Osc 4"};
static const char *const SYNC_NAMES[16] = {"32 Steps", "16 Steps", "8 Steps", "4 Steps", "2 Steps", "1 Step", "1/2 Step",
    "1/4 Step", "1/8 Step", "1/16 Step", "6 Steps", "3 Steps", "1.5 Steps", "2/3 Step", "1/3 Step", "1/6 Step"};
static const float SYNC_STEPS[16] = {32, 16, 8, 4, 2, 1, 0.5f, 0.25f, 0.125f, 0.0625f, 6, 3, 1.5f, 2.0f / 3, 1.0f / 3, 1.0f / 6};
/* Steps per beat for each clock divide, and the swing (fraction of a step the odd steps are delayed by). */
static const float DIV_MULT[13] = {0.5f, 1, 2, 2, 2, 3, 4, 4, 4, 6, 8, 12, 24};
static const float DIV_SWING[13] = {0, 0, 0, 1.0f / 6, 1.0f / 3, 0, 0, 1.0f / 6, 1.0f / 3, 0, 0, 0, 0};
/* Modulation depth: destination units reached by a full-scale source at amount 99 (or 100 for LFOs). */
static const float DR[69] = {0, 60, 60, 60, 60, 60, 100, 100, 100, 100, 100, 100, 100, 99, 99, 99, 100, 100, 100, 100,
    164, 100, 100, 99, 100, 6, 48, 100, 150, 150, 150, 150, 100, 100, 100, 100, 100, 100, 150, 150, 150, 150, 150,
    100, 100, 100, 100, 100, 99, 99, 99, 99, 110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 110, 164, 164, 100, 100, 99};

enum { ST_IDLE, ST_DELAY, ST_ATT, ST_DEC, ST_SUS, ST_REL };
typedef struct { int st; float lvl, t; } env_t;
typedef struct { float ph, out, hold; } lfo_t;
typedef struct { int pos[4], running, gate, once, steps_done; float phase, gate_t, cur[4]; } seq_t;

typedef struct {
    int note, vel, gated, sounding;
    unsigned age;
    float key[4], tgt;            /* per oscillator key pitch (glides), the note it glides to */
    float ph[4], o3, o4, nz;      /* oscillator phases, last digital outputs, noise sample */
    float slop[4], slopv[4];
    env_t env[3];
    lfo_t lfo[4];
    seq_t seq;
    float d[69], dprev[69];       /* modulation sums this tick, last tick */
    float src[25];
    /* control results */
    float inc[4], lvl[4], duty[2], fm43, fm34, rm43, rm34, noise;
    float cut[2], cut_prev[2], res[2], vca, vca_prev, panl[2], panr[2], fblen, fblvl, fb2, fb1;
    int shape[2], wave[2], hpv, distv, hack;
    float dlen[3], damt[3];
    /* audio state */
    float lad[2][4], fbuf[2][FBLEN], fbo[2], hpz[2][2][2], hpc[2][5], gate_env, gain_gate, dfb;
    int fpos, dpos, hp_cur;
    float *dly;
    uint32_t rng;
} voice_t;

typedef struct { char name[40]; char path[PATHLEN]; int bank; } bankref_t;

typedef struct {
    uint8_t patch[NPATCH];
    char name[17];
    voice_t v[MAXV];
    int nv;
    unsigned age;
    struct { int note, vel; } held[16];
    int nheld, pedal, deferred[128];
    int last_note, rr;
    float bend, wheel, press, breath, foot, expr, cc_vol, bright;      /* smoothed controllers */
    float t_wheel, t_press, t_breath, t_foot, t_expr, t_bright;
    float host_bpm;
    int seq_run, clock_src, transport;
    float waves[PE_NWAVES][PE_WLEN];
    int user_waves;
    bankref_t banks[MAXBANKS];
    int nbanks, cur_bank, cur_prog;
    uint8_t bankdata[128][NPATCH];
    char banknames[128][17];
    char dir[PATHLEN];
    int display_rev;
    uint32_t rng;
} pe_t;

static float G_TAB[4096];        /* ladder G = g/(1+g), g = tan(pi f / fs), at 1/16 semitone from C0 - 48 semitones */
static float ENV_S[441];         /* envelope seconds at quarter steps of 0..110 */
static float LFO_HZ[151];

/* ---------------- helpers ---------------- */
static float clampf(float x, float a, float b) { return x < a ? a : x > b ? b : x; }
static int clampi(int x, int a, int b) { return x < a ? a : x > b ? b : x; }
static float ftanh(float x) { x = clampf(x, -3, 3); return x * (27 + x * x) / (27 + 9 * x * x); }
static float rnd(uint32_t *s) { *s = *s * 1664525u + 1013904223u; return (float)(int32_t)*s * (1.0f / 2147483648.0f); }
static int P(const pe_t *s, int i) { return s->patch[i]; }
static float s99(const pe_t *s, int i) { return (float)s->patch[i] - 99; }

static void init_tables(void) {
    static int done;
    if (done) return;
    for (int i = 0; i < 4096; i++) {
        float f = pe_lpf_hz(i / 16.0f - 48);
        if (f > 0.45f * FS) f = 0.45f * FS;
        float g = tanf(3.14159265f * f / FS);
        G_TAB[i] = g / (1 + g);
    }
    for (int i = 0; i <= 440; i++) ENV_S[i] = pe_env_seconds(i * 0.25f);
    for (int i = 0; i <= 150; i++) LFO_HZ[i] = pe_lfo_hz(i);
    done = 1;
}
static float lpf_G(float semis) {
    float x = (semis + 48) * 16;
    if (x <= 0) return G_TAB[0];
    if (x >= 4094) return G_TAB[4094];
    int i = (int)x;
    return G_TAB[i] + (x - i) * (G_TAB[i + 1] - G_TAB[i]);
}

static float env_s(float v) { return ENV_S[clampi((int)(v * 4 + 0.5f), 0, 440)]; }

static float steps_per_sec(const pe_t *s) {
    float bpm = (s->clock_src && s->host_bpm > 0) ? s->host_bpm : (float)P(s, P_TEMPO);
    return clampf(bpm, 30, 250) / 60.0f * DIV_MULT[clampi(P(s, P_CLOCK_DIV), 0, 12)];
}

/* ---------------- program handling ---------------- */
static void patch_init(uint8_t *p, char *name) {
    for (int i = 0; i < NPATCH; i++) p[i] = (uint8_t)PTAB[i].def;
    if (name) strcpy(name, "Basic Program");
}
static void patch_clamp(uint8_t *p) {
    for (int i = 0; i < NPATCH; i++) if (p[i] > PTAB[i].max) p[i] = (uint8_t)PTAB[i].max;
    if (p[P_TEMPO] < 30) p[P_TEMPO] = 30;
}

/* ---------------- banks: the built-in presets plus programs found in .syx files ---------------- */
typedef struct { uint8_t (*data)[NPATCH]; char (*names)[17]; int want_bank, found, any_bank[4]; } loadctx_t;
static void load_cb(void *c, int cmd, const uint8_t *b, int n) {
    loadctx_t *x = c;
    if (cmd == SYX_PROGRAM && n >= 2 + 200) {
        int bank = b[0] & 3, num = b[1] & 0x7F;
        x->any_bank[bank] = 1;
        if (bank != x->want_bank || !x->data) return;
        uint8_t tmp[NPATCH];
        if (syx_unpack(b + 2, n - 2, tmp, NPATCH) < NPATCH) return;
        memcpy(x->data[num], tmp, NPATCH);
        patch_clamp(x->data[num]);
        x->found++;
    } else if (cmd == SYX_EDIT && n >= 200) {
        x->any_bank[0] = 1;
        if (x->want_bank != 0 || !x->data) return;
        uint8_t tmp[NPATCH];
        if (syx_unpack(b, n, tmp, NPATCH) < NPATCH) return;
        for (int k = 0; k < 128; k++)
            if (!x->names[k][0] || !strcmp(x->names[k], "-")) { memcpy(x->data[k], tmp, NPATCH); patch_clamp(x->data[k]); strcpy(x->names[k], "Edit Buffer"); x->found++; break; }
    } else if (cmd == SYX_NAME && n >= 18) {
        int bank = b[0] & 3, num = b[1] & 0x7F;
        if (bank != x->want_bank || !x->names) return;
        for (int i = 0; i < 16; i++) x->names[num][i] = (char)((b[2 + i] >= 32 && b[2 + i] < 127) ? b[2 + i] : ' ');
        x->names[num][16] = 0;
        for (int i = 15; i >= 0 && x->names[num][i] == ' '; i--) x->names[num][i] = 0;
    }
}
static uint8_t *read_file(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || n > (8 << 20)) { fclose(f); return NULL; }
    uint8_t *b = malloc((size_t)n);
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); b = NULL; }
    fclose(f);
    *len = (size_t)n;
    return b;
}
typedef struct { pe_t *s; } wavectx_t;
static void wave_cb(void *c, int cmd, const uint8_t *b, int n) {
    pe_t *s = ((wavectx_t *)c)->s;
    float w[PE_WLEN];
    if (cmd != SYX_WAVE) return;
    int slot = waves_from_dump(b, n, w);
    if (slot >= 0) { memcpy(s->waves[slot], w, sizeof w); s->user_waves++; }
}
static int cmpstr(const void *a, const void *b) { return strcasecmp(*(char *const *)a, *(char *const *)b); }
static void scan_dir(pe_t *s, const char *dir) {
    DIR *d = opendir(dir);
    if (!d) return;
    char *names[256];
    int n = 0;
    struct dirent *e;
    while ((e = readdir(d)) && n < 256) {
        size_t l = strlen(e->d_name);
        if (l > 4 && !strcasecmp(e->d_name + l - 4, ".syx")) names[n++] = strdup(e->d_name);
    }
    closedir(d);
    qsort(names, (size_t)n, sizeof names[0], cmpstr);
    for (int i = 0; i < n; i++) {
        char path[PATHLEN];
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        size_t len;
        uint8_t *buf = read_file(path, &len);
        if (buf) {
            wavectx_t wc = {s};
            syx_each(buf, len, wave_cb, &wc);
            loadctx_t lc = {0};
            lc.want_bank = -1;
            syx_each(buf, len, load_cb, &lc);
            int nb = lc.any_bank[0] + lc.any_bank[1] + lc.any_bank[2] + lc.any_bank[3];
            for (int b = 0; b < 4 && s->nbanks < MAXBANKS; b++) {
                if (!lc.any_bank[b]) continue;
                bankref_t *r = &s->banks[s->nbanks++];
                char base[40];
                snprintf(base, sizeof base, "%s", names[i]);
                char *dot = strrchr(base, '.');
                if (dot) *dot = 0;
                if (nb > 1) snprintf(r->name, sizeof r->name, "%.30s B%c", base, (char)('1' + b));
                else snprintf(r->name, sizeof r->name, "%.38s", base);
                snprintf(r->path, sizeof r->path, "%s", path);
                r->bank = b;
            }
            free(buf);
        }
        free(names[i]);
    }
}
static void load_bank(pe_t *s, int bi) {
    bi = clampi(bi, 0, s->nbanks - 1);
    for (int k = 0; k < 128; k++) { patch_init(s->bankdata[k], NULL); strcpy(s->banknames[k], "-"); }
    if (bi == 0) {
        for (int k = 0; k < presets_count() && k < 128; k++) {
            patch_init(s->bankdata[k], NULL);
            presets_apply(k, s->bankdata[k], s->banknames[k]);
        }
    } else {
        size_t len;
        uint8_t *buf = read_file(s->banks[bi].path, &len);
        if (buf) {
            for (int k = 0; k < 128; k++) s->banknames[k][0] = 0;
            loadctx_t lc = {s->bankdata, s->banknames, s->banks[bi].bank, 0, {0}};
            syx_each(buf, len, load_cb, &lc);
            for (int k = 0; k < 128; k++) if (!s->banknames[k][0]) snprintf(s->banknames[k], 17, "Prog %d", k + 1);
            free(buf);
        }
    }
    s->cur_bank = bi;
}
static void select_program(pe_t *s, int p) {
    s->cur_prog = clampi(p, 0, 127);
    memcpy(s->patch, s->bankdata[s->cur_prog], NPATCH);
    snprintf(s->name, sizeof s->name, "%s", s->banknames[s->cur_prog]);
    s->display_rev++;
}

/* ---------------- envelopes and LFOs ---------------- */
/* 1 - exp(-x), cheap: exact enough for the small per-tick steps of these envelopes */
static float one_minus_exp(float x) { return x < 0.05f ? x * (1 - 0.5f * x) : 1 - expf(-x); }
static void env_gate(env_t *e, int on, float delay_s) {
    if (on) { e->st = delay_s > 0 ? ST_DELAY : ST_ATT; e->t = 0; }
    else if (e->st != ST_IDLE) e->st = ST_REL;
}
static float env_tick(env_t *e, float a, float d, float sus, float r, int lin, float delay_s) {
    switch (e->st) {
    case ST_DELAY:
        e->t += DT;
        if (e->t >= delay_s) e->st = ST_ATT;
        break;
    case ST_ATT:
        if (lin) e->lvl += DT / fmaxf(a, 1e-4f);
        else e->lvl += (1.3f - e->lvl) * one_minus_exp(DT * 1.466f / fmaxf(a, 1e-4f));
        if (e->lvl >= 1) { e->lvl = 1; e->st = ST_DEC; }
        break;
    case ST_DEC:
        if (lin) { e->lvl -= DT / fmaxf(d, 1e-4f); if (e->lvl <= sus) { e->lvl = sus; e->st = ST_SUS; } }
        else { e->lvl += (sus - e->lvl) * one_minus_exp(DT * 4.6f / fmaxf(d, 1e-4f)); if (fabsf(e->lvl - sus) < 1e-4f) e->st = ST_SUS; }
        break;
    case ST_SUS: e->lvl = sus; break;
    case ST_REL:
        if (lin) e->lvl -= DT / fmaxf(r, 1e-4f);
        else e->lvl -= e->lvl * one_minus_exp(DT * 4.6f / fmaxf(r, 1e-4f));
        if (e->lvl <= 1e-4f) { e->lvl = 0; e->st = ST_IDLE; }
        break;
    default: e->lvl = 0;
    }
    return e->lvl;
}
static float lfo_tick(lfo_t *l, float hz, int shape, uint32_t *rng) {
    l->ph += hz * DT;
    if (l->ph >= 1) { l->ph -= floorf(l->ph); l->hold = rnd(rng); }
    float p = l->ph;
    switch (shape) {
    case 0: l->out = p < 0.5f ? 4 * p - 1 : 3 - 4 * p; break;
    case 1: l->out = 1 - 2 * p; break;
    case 2: l->out = 2 * p - 1; break;
    case 3: l->out = p < 0.5f ? 1 : -1; break;
    default: l->out = l->hold;
    }
    return l->out;
}

/* ---------------- sequencer ---------------- */
static int trig_auto(int t) { return t == 4 || t == 5 || t == 8 || t == 9 || (t >= 10 && t <= 13); }
static int trig_seq_env(int t) { return t == 0 || t == 1 || trig_auto(t); }
static void seq_reset(seq_t *q) { for (int k = 0; k < 4; k++) q->pos[k] = 0; q->phase = 0; q->steps_done = 0; }
static void seq_load(pe_t *s, voice_t *v) {
    seq_t *q = &v->seq;
    for (int k = 0; k < 4; k++) {
        int val = s->patch[NPROG + k * 16 + q->pos[k]];
        if (val <= 100) q->cur[k] = (float)val;
    }
}
/* Advance one step: every track moves on, wrapping at 16 or at a Reset step. Returns 1 if the new step triggers (not a rest). */
static int seq_advance(pe_t *s, voice_t *v) {
    seq_t *q = &v->seq;
    for (int k = 0; k < 4; k++) {
        int p = q->pos[k] + 1;
        if (p >= 16 || s->patch[NPROG + k * 16 + p] == 101) p = 0;
        q->pos[k] = p;
    }
    q->steps_done++;
    seq_load(s, v);
    return s->patch[NPROG + q->pos[0]] != 102;
}
static void voice_trigger(pe_t *s, voice_t *v, int on);
/* Runs this voice's sequencer for one control tick; handles the trigger modes that let it fire the envelopes. */
static void seq_tick(pe_t *s, voice_t *v, float sps, float clockmul) {
    seq_t *q = &v->seq;
    if (!q->running) return;
    int trig = P(s, P_TRIGGER);
    float swing = DIV_SWING[clampi(P(s, P_CLOCK_DIV), 0, 12)];
    float len = 1 + ((q->steps_done & 1) ? -swing : swing);
    q->phase += sps * DT / clockmul / len;
    if (q->gate && (q->gate_t -= DT) <= 0) { q->gate = 0; if (trig_seq_env(trig)) voice_trigger(s, v, 0); }
    if (q->phase < 1) return;
    q->phase -= floorf(q->phase);
    if ((trig == 10 || trig == 11) && q->steps_done >= 15) {   /* play once: stop after the 16th step or a reset of sequence 1 */
        q->running = 0;
        if (q->gate) { q->gate = 0; voice_trigger(s, v, 0); }
        return;
    }
    int fire = seq_advance(s, v);
    if ((trig == 10 || trig == 11) && q->pos[0] == 0) { q->running = 0; if (q->gate) { q->gate = 0; voice_trigger(s, v, 0); } return; }
    if (fire && trig_seq_env(trig)) {
        q->gate = 1;
        q->gate_t = 0.5f / (sps / clockmul);
        voice_trigger(s, v, 1);
    }
}

/* ---------------- voices ---------------- */
static float glide_rate(const pe_t *s, int osc, int legato) {
    static const int gi[4] = {P_OSC1_GLIDE, P_OSC2_GLIDE, P_OSC3_GLIDE, P_OSC4_GLIDE};
    int g = P(s, gi[osc]);
    if (g == 0 || g == 200) return 0;
    if (g > 100) { if (!legato) return 0; g -= 99; }
    return 12.0f / pe_glide_seconds(g);    /* semitones per second */
}
static void voice_trigger(pe_t *s, voice_t *v, int on) {
    float d3 = env_s(P(s, P_ENV3_DELAY));
    for (int e = 0; e < 3; e++) env_gate(&v->env[e], on, e == 2 ? d3 : 0);
    if (on) {
        v->sounding = 1;
        static const int la[4] = {P_LFO1_AMT, P_LFO2_AMT, P_LFO3_AMT, P_LFO4_AMT};
        for (int l = 0; l < 4; l++) if (P(s, la[l]) > 100) { v->lfo[l].ph = 0; v->lfo[l].hold = rnd(&v->rng); }
    }
}
static void voice_note(pe_t *s, voice_t *v, int note, int vel, int legato, int retrig) {
    v->note = note;
    v->vel = vel;
    v->tgt = (float)note;
    for (int o = 0; o < 4; o++) if (!legato && glide_rate(s, o, 0) == 0) v->key[o] = (float)note;
    if (!v->sounding || !legato) for (int o = 0; o < 4; o++) if (glide_rate(s, o, legato) == 0) v->key[o] = (float)note;
    if (!v->sounding) for (int o = 0; o < 4; o++) v->key[o] = (float)note;
    v->gated = 1;
    v->age = ++s->age;
    int trig = P(s, P_TRIGGER);
    seq_t *q = &v->seq;
    if (trig == 3 || trig == 5 || trig == 7 || trig == 9 || trig == 11) { seq_reset(q); seq_load(s, v); }
    if (trig == 4 || trig == 5 || trig == 8 || trig == 9) {
        if (!q->running || trig == 5 || trig == 9) { seq_reset(q); seq_load(s, v); }
        q->running = 1;
    }
    if (trig == 10 || trig == 11) {
        if (!q->running || trig == 11) { seq_reset(q); seq_load(s, v); q->running = 1; q->gate = 1; q->gate_t = 0.5f / steps_per_sec(s); voice_trigger(s, v, 1); }
        return;
    }
    if (trig == 12 || trig == 13) {     /* each key plays one step */
        if (q->steps_done || q->gate) seq_advance(s, v); else seq_load(s, v);
        q->steps_done++;
        q->running = 0;
        voice_trigger(s, v, 1);
        return;
    }
    if (trig == 4 || trig == 5 || trig == 8 || trig == 9) { q->phase = 0; q->gate = 1; q->gate_t = 0.5f / steps_per_sec(s); voice_trigger(s, v, 1); return; }
    if (trig == 1) return;              /* sequencer only */
    if (!legato || retrig || v->env[1].st == ST_IDLE || v->env[1].st == ST_REL) voice_trigger(s, v, 1);
}
static void voice_release(pe_t *s, voice_t *v) {
    v->gated = 0;
    int trig = P(s, P_TRIGGER);
    if (trig == 4 || trig == 5 || trig == 8 || trig == 9) { v->seq.running = 0; v->seq.gate = 0; }
    if (trig == 10 || trig == 11) return;  /* the sequence plays to its end */
    voice_trigger(s, v, 0);
}

static int voices_mode(const pe_t *s) { return P(s, P_KEY_MODE) / 6; }   /* 0 poly 1 mono 2 unison1 3 unison2 */
static int key_pick(const pe_t *s) {
    int pri = (P(s, P_KEY_MODE) % 6) / 2, best = -1;
    for (int i = 0; i < s->nheld; i++) {
        if (best < 0) { best = i; continue; }
        if (pri == 0 && s->held[i].note < s->held[best].note) best = i;
        if (pri == 1 && s->held[i].note > s->held[best].note) best = i;
        if (pri == 2) best = i;
    }
    return best;
}
static void mono_update(pe_t *s, int was_held) {
    int mode = voices_mode(s), n = mode == 1 ? 1 : s->nv, retrig = P(s, P_KEY_MODE) & 1;
    int k = key_pick(s);
    for (int i = 0; i < n; i++) {
        voice_t *v = &s->v[i];
        if (k < 0) { if (v->gated) voice_release(s, v); continue; }
        int note = s->held[k].note;
        if (v->gated && v->note == note) continue;
        voice_note(s, v, note, s->held[k].vel, was_held && v->gated, retrig);
    }
}
static void note_on(pe_t *s, int note, int vel) {
    if (P(s, P_KEY_XPOSE) == 0) return;    /* keyboard off */
    s->last_note = note;
    s->deferred[note & 127] = 0;
    int was = s->nheld;
    for (int i = 0; i < s->nheld; i++) if (s->held[i].note == note) { memmove(&s->held[i], &s->held[i + 1], sizeof s->held[0] * (size_t)(--s->nheld - i)); break; }
    if (s->nheld < 16) { s->held[s->nheld].note = note; s->held[s->nheld].vel = vel; s->nheld++; }
    if (voices_mode(s) != 0) { mono_update(s, was > 0); return; }
    voice_t *best = NULL;
    for (int i = 0; i < s->nv; i++) {             /* circular: the next voice not playing, else the oldest */
        voice_t *v = &s->v[(s->rr + i) % s->nv];
        if (!v->gated && v->env[1].st == ST_IDLE) { best = v; s->rr = (int)(v - s->v) + 1; break; }
    }
    if (!best) for (int i = 0; i < s->nv; i++) { voice_t *v = &s->v[(s->rr + i) % s->nv]; if (!v->gated) { best = v; s->rr = (int)(v - s->v) + 1; break; } }
    if (!best) { best = &s->v[0]; for (int i = 1; i < s->nv; i++) if (s->v[i].age < best->age) best = &s->v[i]; }
    voice_note(s, best, note, vel, 0, 1);
}
static void note_off(pe_t *s, int note) {
    if (s->pedal) { s->deferred[note & 127] = 1; return; }
    for (int i = 0; i < s->nheld; i++) if (s->held[i].note == note) { memmove(&s->held[i], &s->held[i + 1], sizeof s->held[0] * (size_t)(--s->nheld - i)); break; }
    if (voices_mode(s) != 0) { mono_update(s, 1); return; }
    for (int i = 0; i < s->nv; i++) if (s->v[i].gated && s->v[i].note == note) voice_release(s, &s->v[i]);
}
static void all_off(pe_t *s) {
    s->nheld = 0;
    memset(s->deferred, 0, sizeof s->deferred);
    for (int i = 0; i < s->nv; i++) if (s->v[i].gated) voice_release(s, &s->v[i]);
}

/* Biquad highpass, two sections (Butterworth 4-pole: Q 0.541 and 1.307), as the firmware's coefficient sets are built. */
static void hpf_design(voice_t *v, int val) {
    float fc = clampf(pe_hpf_hz((float)val), 10, 0.45f * FS);
    static const float Q[2] = {0.5412f, 1.3066f};
    for (int k = 0; k < 2; k++) {
        float w = 6.2831853f * fc / FS, c = cosf(w), al = sinf(w) / (2 * Q[k]), a0 = 1 + al;
        v->hpc[k][0] = (1 + c) / 2 / a0; v->hpc[k][1] = -(1 + c) / a0; v->hpc[k][2] = (1 + c) / 2 / a0;
        v->hpc[k][3] = 2 * c / a0; v->hpc[k][4] = -(1 - al) / a0;
    }
    v->hp_cur = val;
}

/* The control tick: modulation sums, then everything the audio loop needs. */
static void voice_control(pe_t *s, voice_t *v, int vi, float sps) {
    int trig = P(s, P_TRIGGER), auto_seq = trig_auto(trig);
    int has_seq = auto_seq ? 1 : (vi == 0 && v->seq.running);
    float *d = v->d;
    memcpy(v->dprev, d, sizeof v->dprev);
    memset(d, 0, sizeof v->d);
    const float *dp = v->dprev;
    float vel = v->vel / 127.0f;

    /* sequencer: its clock multiplier is a sequencer-only destination */
    float clockmul = 1;
    for (int k = 0; k < 4; k++) if (has_seq && P(s, P_SEQ1_DEST + k) == 69 && v->seq.cur[k] > 0) clockmul = v->seq.cur[k] / 40.0f;
    if (auto_seq || vi == 0) seq_tick(s, v, sps, clockmul);

    /* envelopes */
    static const int ep[3][4] = {{P_FENV_A, P_FENV_D, P_FENV_S, P_FENV_R}, {P_AENV_A, P_AENV_D, P_AENV_S, P_AENV_R}, {P_ENV3_A, P_ENV3_D, P_ENV3_S, P_ENV3_R}};
    int lin = P(s, P_ENV_SHAPE);
    for (int e = 0; e < 3; e++) {
        float a = env_s(P(s, ep[e][0]) + dp[52 + e] + dp[55]);
        float dd = env_s(P(s, ep[e][1]) + dp[56 + e] + dp[59]);
        float r = env_s(P(s, ep[e][3]) + dp[60 + e] + dp[63]);
        env_tick(&v->env[e], a, dd, P(s, ep[e][2]) / 100.0f, r, lin, env_s(P(s, P_ENV3_DELAY)));
    }
    float velf = 1 - P(s, P_LPF_VEL) / 100.0f * (1 - vel), vela = 1 - P(s, P_VCA_VEL) / 100.0f * (1 - vel), vel3 = 1 - P(s, P_ENV3_VEL) / 100.0f * (1 - vel);
    float fenv = v->env[0].lvl * velf, aenv = v->env[1].lvl * vela, env3 = v->env[2].lvl * vel3;

    /* LFOs */
    static const int lp[4][4] = {{P_LFO1_FREQ, P_LFO1_SHAPE, P_LFO1_AMT, P_LFO1_DEST}, {P_LFO2_FREQ, P_LFO2_SHAPE, P_LFO2_AMT, P_LFO2_DEST},
        {P_LFO3_FREQ, P_LFO3_SHAPE, P_LFO3_AMT, P_LFO3_DEST}, {P_LFO4_FREQ, P_LFO4_SHAPE, P_LFO4_AMT, P_LFO4_DEST}};
    float lfo_raw[4];
    for (int l = 0; l < 4; l++) {
        int fv = P(s, lp[l][0]);
        float hz = fv > 150 ? sps / SYNC_STEPS[fv - 151] : LFO_HZ[(int)clampf(fv + dp[38 + l] + dp[42], 0, 150)];
        lfo_raw[l] = lfo_tick(&v->lfo[l], hz, P(s, lp[l][1]), &v->rng);
        int amt = P(s, lp[l][2]);
        if (amt > 100) amt -= 100;
        float a = clampf(amt + dp[43 + l] + dp[47], 0, 100) / 100.0f;
        int dst = P(s, lp[l][3]);
        if (dst > 0 && dst < 69) d[dst] += lfo_raw[l] * a * DR[dst];
    }

    /* sources */
    float *sr = v->src;
    for (int k = 0; k < 4; k++) sr[1 + k] = has_seq ? v->seq.cur[k] / 100.0f : 0;
    for (int l = 0; l < 4; l++) sr[5 + l] = lfo_raw[l];
    sr[9] = fenv; sr[10] = aenv; sr[11] = env3; sr[12] = 0; sr[13] = 0;
    sr[14] = s->bend; sr[15] = s->wheel; sr[16] = s->press; sr[17] = s->breath; sr[18] = s->foot;
    sr[19] = vel; sr[20] = v->note / 127.0f; sr[21] = s->expr; sr[22] = rnd(&v->rng); sr[23] = v->o3; sr[24] = v->o4;

    /* routes with an amount (-99..+99) */
    static const int route[][2] = {{P_MOD1_SRC, 0}, {P_MOD2_SRC, 0}, {P_MOD3_SRC, 0}, {P_MOD4_SRC, 0}};
    (void)route;
    static const int mods[4][3] = {{P_MOD1_SRC, P_MOD1_AMT, P_MOD1_DEST}, {P_MOD2_SRC, P_MOD2_AMT, P_MOD2_DEST},
        {P_MOD3_SRC, P_MOD3_AMT, P_MOD3_DEST}, {P_MOD4_SRC, P_MOD4_AMT, P_MOD4_DEST}};
    for (int m = 0; m < 4; m++) {
        int src = P(s, mods[m][0]), dst = P(s, mods[m][2]);
        if (!src || !dst || dst > 68) continue;
        float amt = s99(s, mods[m][1]) / 99.0f, x = sr[src];
        int pitchlike = (dst >= 1 && dst <= 5) || dst == 20 || dst == 26 || dst == 64 || dst == 65;
        if (src == 20 && pitchlike) d[dst] += (v->note - 60) * amt;   /* key number tracks in semitones */
        else d[dst] += x * amt * DR[dst];
    }
    static const int fixed[7][3] = {{12, P_PEAK_AMT, P_PEAK_DEST}, {13, P_ENVF_AMT, P_ENVF_DEST}, {19, P_VEL_AMT, P_VEL_DEST},
        {15, P_WHEEL_AMT, P_WHEEL_DEST}, {16, P_PRESS_AMT, P_PRESS_DEST}, {17, P_BREATH_AMT, P_BREATH_DEST}, {18, P_FOOT_AMT, P_FOOT_DEST}};
    for (int m = 0; m < 7; m++) {
        int dst = P(s, fixed[m][2]);
        if (dst > 0 && dst < 69) d[dst] += sr[fixed[m][0]] * s99(s, fixed[m][1]) / 99.0f * DR[dst];
    }
    { int dst = P(s, P_ENV3_DEST); if (dst > 0 && dst < 69) d[dst] += env3 * clampf(s99(s, P_ENV3_AMT) + dp[50] + dp[51], -99, 99) / 99.0f * DR[dst]; }
    if (has_seq)
        for (int k = 0; k < 4; k++) {
            int dst = P(s, P_SEQ1_DEST + k);
            if (dst <= 0 || dst > 68) continue;
            d[dst] += (dst <= 5) ? v->seq.cur[k] * 0.5f : v->seq.cur[k] / 100.0f * DR[dst];
        }

    /* pitch: osc value + key (with glide) + transpose + bend + modulation + slop + unison spread */
    int mode = voices_mode(s), legato = s->nheld > 1;
    float spread = 0;
    if (mode >= 2 && s->nv > 1) spread = (vi - (s->nv - 1) * 0.5f) / (s->nv - 1) * (mode == 2 ? 0.12f : 0.30f);
    static const int of[4][3] = {{P_OSC1_FREQ, P_OSC1_FINE, P_OSC1_GLIDE}, {P_OSC2_FREQ, P_OSC2_FINE, P_OSC2_GLIDE},
        {P_OSC3_FREQ, P_OSC3_FINE, P_OSC3_GLIDE}, {P_OSC4_FREQ, P_OSC4_FINE, P_OSC4_GLIDE}};
    float xpose = (float)P(s, P_KEY_XPOSE) - 37, slop = P(s, P_SLOP) * 0.03f;
    for (int o = 0; o < 4; o++) {
        float rate = glide_rate(s, o, legato || mode == 0);
        if (rate > 0) {
            float dk = v->tgt - v->key[o], st = rate * DT;
            v->key[o] += dk > st ? st : dk < -st ? -st : dk;
        } else v->key[o] = v->tgt;
        if ((v->rng & 0xff) < 3) v->slopv[o] = rnd(&v->rng) * slop;
        v->slop[o] += (v->slopv[o] - v->slop[o]) * 0.002f;
        float key = P(s, of[o][2]) == 200 ? 0 : v->key[o] + xpose;
        float semis = P(s, of[o][0]) + (P(s, of[o][1]) - 50) / 100.0f + key + s->bend * P(s, P_BEND_RANGE) + d[1 + o] + d[5] + v->slop[o] + spread;
        v->inc[o] = fminf(pe_note_hz(semis) / FS, 0.49f);
    }
    for (int o = 0; o < 4; o++) v->lvl[o] = clampf(P(s, P_OSC1_LEVEL + 4 * o) + d[6 + o] + d[10], 0, 100) / 100.0f;
    for (int c = 0; c < 2; c++) {
        int sh = P(s, c ? P_OSC2_SHAPE : P_OSC1_SHAPE);
        v->shape[c] = sh < 3 ? sh : 3;
        float pw = clampf(sh - 3 + d[13 + c] + d[15], 0, 99);
        v->duty[c] = sh < 3 ? 0.5f : pw / 99.0f;
    }
    for (int c = 0; c < 2; c++) {
        int ss = P(s, c ? P_SHAPESEQ4 : P_SHAPESEQ3);
        int w = P(s, c ? P_OSC4_SHAPE : P_OSC3_SHAPE);
        if (ss && has_seq) w = clampi((int)v->seq.cur[ss - 1] - 1, 0, 127);
        v->wave[c] = w;
    }
    v->fm43 = clampf(P(s, P_FM_43) + d[16], 0, 100) / 100.0f; v->fm34 = clampf(P(s, P_FM_34) + d[17], 0, 100) / 100.0f;
    v->rm43 = clampf(P(s, P_RM_43) + d[18], 0, 100) / 100.0f; v->rm34 = clampf(P(s, P_RM_34) + d[19], 0, 100) / 100.0f;
    v->noise = clampf(P(s, P_NOISE_LEVEL) + d[11], 0, 100) / 100.0f;

    /* lowpass: base + envelope + key tracking (72 = one semitone per note) + split + controllers */
    float envamt = clampf(s99(s, P_LPF_ENV) + dp[48] + dp[51], -99, 99);
    float cut = P(s, P_LPF_FREQ) + fenv * envamt / 99.0f * 164 + v->key[0] * P(s, P_LPF_KEY) / 72.0f + d[20] + s->bright * 40;
    float split = clampf(P(s, P_LPF_SPLIT) + d[21], 0, 100) * 0.25f;
    for (int c = 0; c < 2; c++) {
        v->cut_prev[c] = v->cut[c];
        v->cut[c] = clampf(cut + (c ? -split : split) + d[64 + c], -40, 200);
        float r = clampf(P(s, P_LPF_RES) + d[22] + d[66 + c], 0, 100) / 100.0f;
        v->res[c] = P(s, P_POLES) ? r * 4.15f : r * 12.0f;
    }

    /* VCA: base level plus envelope (full base level makes the envelope irrelevant) */
    float vamt = clampf(P(s, P_VCA_ENV) + dp[49] + dp[51], 0, 100) / 100.0f;
    v->vca_prev = v->vca;
    v->vca = clampf(P(s, P_VCA_LEVEL) / 100.0f + aenv * vamt + d[24] / 100.0f, 0, 1);

    /* output pan: where the left channel sits (0 = hard left); the right channel mirrors it */
    float pos = clampf(P(s, P_PAN) + d[25], 0, 6) / 6.0f;
    v->panl[0] = cosf(pos * 1.5707963f); v->panl[1] = sinf(pos * 1.5707963f);
    v->panr[0] = v->panl[1]; v->panr[1] = v->panl[0];

    /* tuned feedback, highpass, distortion, delay */
    v->fblen = clampf(FS / pe_note_hz(24 + clampf(P(s, P_FB_FREQ) + d[26], 0, 48)), 2, FBLEN - 2);
    v->fblvl = clampf(P(s, P_FB_LEVEL) + d[27], 0, 100) / 100.0f;
    int hpf = P(s, P_HPF);
    v->hpv = (hpf > 0 && hpf < 100) ? clampi(hpf + (int)d[23], 1, 99) : 0;
    if (v->hpv && v->hpv != v->hp_cur) hpf_design(v, v->hpv);
    int dist = P(s, P_DIST);
    v->distv = (dist > 0 && dist < 100) ? clampi(dist + (dist > 1 ? (int)d[68] : 0), 1, 99) : 0;
    static const int dt[3] = {P_DLY1_TIME, P_DLY2_TIME, P_DLY3_TIME}, da[3] = {P_DLY1_LEVEL, P_DLY2_LEVEL, P_DLY3_LEVEL};
    for (int k = 0; k < 3; k++) {
        int tv = P(s, dt[k]);
        float sec;
        if (tv > 150) {
            sec = SYNC_STEPS[clampi(tv - 151, 0, 15)] / sps;
            while (sec > 1.0f) sec *= 0.5f;    /* too long for one second of memory: halve until it fits (manual) */
        } else sec = pe_delay_seconds((int)clampf(tv + d[28 + k] + d[31], 0, 150));
        v->dlen[k] = clampf(sec * FS, 1, DLEN - 4);
        v->damt[k] = clampf(P(s, da[k]) + d[32 + k] + d[35], 0, 100) / 100.0f;
    }
    v->fb1 = clampf(P(s, P_DLY_FB1) + d[36], 0, 100) / 100.0f;
    v->fb2 = clampf(P(s, P_DLY_FB2) + d[37], 0, 100) / 100.0f;
    v->hack = P(s, P_OUT_HACK);
}

static float polyblep(float t, float dt) {
    if (t < dt) { t /= dt; return t + t - t * t - 1; }
    if (t > 1 - dt) { t = (t - 1) / dt; return t * t + t + t + 1; }
    return 0;
}
static float analog_osc(int shape, float ph, float inc, float duty) {
    float saw = 2 * ph - 1 - polyblep(ph, inc);
    float tri = ph < 0.5f ? 4 * ph - 1 : 3 - 4 * ph;
    switch (shape) {
    case 0: return saw;
    case 1: return tri;
    case 2: return 0.5f * (saw + tri);
    default: {
        if (duty <= 0.0f || duty >= 1.0f) return 0;    /* the pulse turns off at both extremes */
        float x = ph < duty ? 1.0f : -1.0f;
        x += polyblep(ph, inc);
        float t2 = ph - duty + (ph < duty ? 1 : 0);
        x -= polyblep(t2, inc);
        return x - (2 * duty - 1);
    }
    }
}
static float wave_read(const float *w, float ph) {
    float x = ph * PE_WLEN;
    int i = (int)x;
    float f = x - i;
    i &= PE_WLEN - 1;
    return w[i] + f * (w[(i + 1) & (PE_WLEN - 1)] - w[i]);
}

/* One voice, CTL samples, added into out[] (stereo float). */
static void voice_audio(pe_t *s, voice_t *v, float *out, int n) {
    float am = P(s, P_LPF_AUDIOMOD) * 0.48f;         /* audio mod: semitones of cutoff per unit of oscillator */
    int four = P(s, P_POLES), grunge = P(s, P_GRUNGE), sync = P(s, P_SYNC);
    float vol = P(s, P_VOLUME) / 100.0f;
    const float *w3 = s->waves[v->wave[0]], *w4 = s->waves[v->wave[1]];
    for (int i = 0; i < n; i++) {
        float t = (i + 1) / (float)n;
        /* oscillators */
        float o2 = analog_osc(v->shape[1], v->ph[1], v->inc[1], v->duty[1]);
        v->ph[1] += v->inc[1];
        int wrap2 = v->ph[1] >= 1;
        if (wrap2) v->ph[1] -= 1;
        float o1 = analog_osc(v->shape[0], v->ph[0], v->inc[0], v->duty[0]);
        v->ph[0] += v->inc[0];
        if (v->ph[0] >= 1) v->ph[0] -= 1;
        if (sync && wrap2) v->ph[0] = v->ph[1] * v->inc[0] / v->inc[1];
        float r3 = wave_read(w3, v->ph[2]), r4 = wave_read(w4, v->ph[3]);
        v->ph[2] += v->inc[2] * (1 + v->fm43 * 4 * v->o4);
        v->ph[3] += v->inc[3] * (1 + v->fm34 * 4 * v->o3);
        v->ph[2] -= floorf(v->ph[2]);
        v->ph[3] -= floorf(v->ph[3]);
        v->o3 = r3; v->o4 = r4;
        float o3 = r3 * v->lvl[2] + v->rm43 * r3 * r4, o4 = r4 * v->lvl[3] + v->rm34 * r3 * r4;
        v->nz = rnd(&v->rng);
        float nz = v->nz * v->noise;
        /* mixer into the two lowpass channels, plus both feedback paths */
        float in[2] = {o1 * v->lvl[0] + o3 + nz, o2 * v->lvl[1] + o4 + nz};
        float fbg = v->fblvl * 1.02f;
        for (int c = 0; c < 2; c++) {
            float fb = v->fbo[c] * fbg;
            if (grunge && v->fblvl > 0.5f) fb = (fb > 0.25f ? fb - 0.5f : fb < -0.25f ? fb + 0.5f : fb) * 2;   /* folds: nasty at high levels */
            in[c] = in[c] * 0.5f + fb + v->dfb * v->fb2;
        }
        /* lowpass ladders (zero-delay feedback; tanh on the input) */
        float y[2];
        float osc_am[2] = {o1, o2};
        for (int c = 0; c < 2; c++) {
            float semis = v->cut_prev[c] + (v->cut[c] - v->cut_prev[c]) * t + am * osc_am[c];
            float G = lpf_G(semis), *st = v->lad[c], k = v->res[c];
            float g1 = 1 - G;
            float out4;
            if (four) {
                float S = G * G * G * g1 * st[0] + G * G * g1 * st[1] + G * g1 * st[2] + g1 * st[3];
                float u = ftanh((in[c] * (1 + 0.35f * k) - k * S) / (1 + k * G * G * G * G));
                float x = u;
                for (int j = 0; j < 4; j++) { float vv = (x - st[j]) * G; float yy = vv + st[j]; st[j] = yy + vv; x = yy; }
                out4 = x;
            } else {
                float S = G * g1 * st[0] + g1 * st[1];
                float u = ftanh((in[c] * (1 + 0.1f * k) - k * S) / (1 + k * G * G));
                float x = u;
                for (int j = 0; j < 2; j++) { float vv = (x - st[j]) * G; float yy = vv + st[j]; st[j] = yy + vv; x = yy; }
                st[2] = st[3] = 0;
                out4 = x;
            }
            y[c] = out4;
        }
        /* VCA, then output pan (it feeds the feedback, so one channel can feed back into the other) */
        float g = v->vca_prev + (v->vca - v->vca_prev) * t;
        float a = y[0] * g, b = y[1] * g;
        float L = a * v->panl[0] + b * v->panr[0], R = a * v->panl[1] + b * v->panr[1];
        /* tuned feedback lines */
        v->fbuf[0][v->fpos] = L; v->fbuf[1][v->fpos] = R;
        float rp = v->fpos - v->fblen;
        if (rp < 0) rp += FBLEN;
        int ri = (int)rp;
        float rf = rp - ri;
        for (int c = 0; c < 2; c++) v->fbo[c] = v->fbuf[c][ri] + rf * (v->fbuf[c][(ri + 1) & (FBLEN - 1)] - v->fbuf[c][ri]);
        v->fpos = (v->fpos + 1) & (FBLEN - 1);
        /* highpass (post), distortion (post) with the noise gate keyed from the left channel */
        if (v->hpv) {
            float io[2] = {L, R};
            for (int c = 0; c < 2; c++)
                for (int k = 0; k < 2; k++) {
                    float *z = v->hpz[c][k], *q = v->hpc[k];
                    float yv = q[0] * io[c] + z[0];
                    z[0] = q[1] * io[c] + q[3] * yv + z[1];
                    z[1] = q[2] * io[c] + q[4] * yv;
                    io[c] = yv;
                }
            L = io[0]; R = io[1];
        }
        if (v->distv) {
            float lv = fabsf(L);
            v->gate_env += (lv > v->gate_env ? 0.01f : 0.0005f) * (lv - v->gate_env);
            float gt = v->gate_env > 0.002f ? 1.0f : 0.0f;
            v->gain_gate += (gt - v->gain_gate) * 0.002f;
            float drive = 1 + v->distv * 0.35f;
            L = ftanh(L * drive) / sqrtf(drive) * v->gain_gate;
            R = ftanh(R * drive) / sqrtf(drive) * v->gain_gate;
        }
        /* three-tap delay on the summed channels; FB1 back into the delay, FB2 back into the filters */
        float din = 0.5f * (L + R), dsum = 0;
        for (int k = 0; k < 3; k++) {
            if (v->damt[k] <= 0) continue;
            float p = v->dpos - v->dlen[k];
            if (p < 0) p += DLEN;
            int pi = (int)p;
            float pf = p - pi;
            float x0 = v->dly[pi], x1 = v->dly[(pi + 1) & (DLEN - 1)];
            dsum += (x0 + pf * (x1 - x0)) * v->damt[k];
        }
        v->dly[v->dpos] = din + ftanh(dsum * v->fb1);
        v->dpos = (v->dpos + 1) & (DLEN - 1);
        v->dfb = dsum;
        L += dsum; R += dsum;
        /* output hack: drops bits, quite rudely */
        if (v->hack) {
            float q = (float)(1 << (15 - v->hack));
            L = floorf(L * q) / q; R = floorf(R * q) / q;
        }
        out[2 * i] += L * vol;
        out[2 * i + 1] += R * vol;
    }
}

/* ---------------- engine API ---------------- */
static void *pe_create(const char *dir) {
    init_tables();
    pe_t *s = calloc(1, sizeof *s);
    if (!s) return NULL;
    s->nv = 4;
    s->cc_vol = 1;
    s->last_note = 60;
    s->clock_src = 1;
    s->rng = 0x13579BDFu;
    for (int i = 0; i < MAXV; i++) {
        s->v[i].dly = calloc(DLEN, sizeof(float));
        s->v[i].rng = 0x2468ACE1u + 7919u * (uint32_t)i;
        s->v[i].note = 60;
        for (int o = 0; o < 4; o++) { s->v[i].key[o] = 60; s->v[i].ph[o] = (float)((i * 37 + o * 11) % 100) / 100.0f; }
        s->v[i].tgt = 60;
        if (!s->v[i].dly) { for (int j = 0; j <= i; j++) free(s->v[j].dly); free(s); return NULL; }
    }
    waves_open(s->waves);
    strcpy(s->banks[0].name, "Blueberry");
    s->nbanks = 1;
    if (dir && *dir) {
        snprintf(s->dir, sizeof s->dir, "%s", dir);
        char sub[PATHLEN];
        snprintf(sub, sizeof sub, "%s/SYSEX", dir);
        mkdir(sub, 0755);
        scan_dir(s, dir);
        scan_dir(s, sub);
    }
    load_bank(s, 0);
    select_program(s, 0);
    return s;
}
static void pe_destroy(void *h) {
    pe_t *s = h;
    if (!s) return;
    for (int i = 0; i < MAXV; i++) free(s->v[i].dly);
    free(s);
}

static void set_patch_value(pe_t *s, int idx, int val) {
    if (idx < 0 || idx >= NPATCH) return;
    s->patch[idx] = (uint8_t)clampi(val, PTAB[idx].min, PTAB[idx].max);
}

/* Received controllers that edit the program directly (manual p. 50-51), scaled from 0..127 to the parameter's range. */
static const struct { uint8_t cc, param; } CCMAP[] = {{20, P_OSC1_FREQ}, {21, P_OSC2_FREQ}, {22, P_OSC3_FREQ}, {23, P_OSC4_FREQ},
    {24, P_OSC1_LEVEL}, {25, P_OSC2_LEVEL}, {26, P_OSC3_LEVEL}, {27, P_OSC4_LEVEL}, {28, P_OSC1_SHAPE}, {29, P_OSC2_SHAPE},
    {30, P_OSC3_SHAPE}, {31, P_OSC4_SHAPE}, {40, P_FM_43}, {41, P_FM_34}, {42, P_RM_43}, {43, P_RM_34}, {62, P_NOISE_LEVEL},
    {52, P_LPF_FREQ}, {53, P_LPF_RES}, {54, P_LPF_ENV}, {55, P_FENV_A}, {56, P_FENV_D}, {57, P_FENV_S}, {58, P_FENV_R},
    {59, P_LPF_AUDIOMOD}, {60, P_LPF_SPLIT}, {61, P_LPF_KEY}, {75, P_AENV_A}, {76, P_AENV_D}, {77, P_AENV_S}, {78, P_AENV_R},
    {85, P_FB_FREQ}, {86, P_FB_LEVEL}, {12, P_DIST}, {102, P_DLY1_TIME}, {103, P_DLY2_TIME}, {104, P_DLY3_TIME},
    {105, P_DLY1_LEVEL}, {106, P_DLY2_LEVEL}, {107, P_DLY3_LEVEL}, {108, P_DLY_FB1}, {109, P_DLY_FB2}};

static void pe_midi(void *h, const uint8_t *m, int len) {
    pe_t *s = h;
    if (len < 1) return;
    int st = m[0] & 0xF0;
    if (m[0] == 0xF0) {   /* program / sequencer parameter messages, if the host ever forwards SysEx */
        if (len >= 9 && m[1] == 0x01 && m[2] == 0x20 && m[3] == 0x01) {
            int v = (m[6] & 15) | ((m[7] & 15) << 4);
            if (m[4] == SYX_PARAM) set_patch_value(s, m[5] & 127, v);
            else if (m[4] == SYX_SEQ) set_patch_value(s, NPROG + (m[5] & 63), v);
            s->display_rev++;
        }
        return;
    }
    if (m[0] == 0xFA) { for (int i = 0; i < s->nv; i++) seq_reset(&s->v[i].seq); return; }
    if (len < 2) return;
    int d1 = m[1] & 127, d2 = len > 2 ? m[2] & 127 : 0;
    switch (st) {
    case 0x90: if (d2) { note_on(s, d1, d2); break; } /* fall through */
    case 0x80: note_off(s, d1); break;
    case 0xA0: s->t_press = d2 / 127.0f; break;
    case 0xD0: s->t_press = d1 / 127.0f; break;
    case 0xE0: s->bend = ((d1 | (d2 << 7)) - 8192) / 8192.0f; break;
    case 0xC0: select_program(s, d1); break;
    case 0xB0:
        switch (d1) {
        case 1: s->t_wheel = d2 / 127.0f; break;
        case 2: s->t_breath = d2 / 127.0f; break;
        case 4: s->t_foot = d2 / 127.0f; break;
        case 7: s->cc_vol = d2 / 127.0f; break;
        case 11: s->t_expr = d2 / 127.0f; break;
        case 74: s->t_bright = d2 / 127.0f; break;
        case 32: if (d2 < s->nbanks) { load_bank(s, d2); s->display_rev++; } break;
        case 64:
            s->pedal = d2 >= 64;
            if (!s->pedal) for (int n = 0; n < 128; n++) if (s->deferred[n]) { s->deferred[n] = 0; note_off(s, n); }
            break;
        case 120: case 123: case 125: all_off(s); if (d1 == 123) { s->t_wheel = s->t_breath = s->t_foot = s->t_press = 0; s->bend = 0; s->cc_vol = 1; } break;
        default:
            for (size_t i = 0; i < sizeof CCMAP / sizeof CCMAP[0]; i++)
                if (CCMAP[i].cc == d1) { set_patch_value(s, CCMAP[i].param, (d2 * PTAB[CCMAP[i].param].max + 63) / 127); s->display_rev++; }
        }
        break;
    }
}

static void pe_render(void *h, int16_t *out, int frames) {
    pe_t *s = h;
    float buf[2 * CTL];
    float sps = steps_per_sec(s);
    int running = s->seq_run == 1 || (s->seq_run == 2 && s->transport);
    voice_t *v0 = &s->v[0];
    if (!trig_auto(P(s, P_TRIGGER))) {
        if (running && !v0->seq.running) { seq_reset(&v0->seq); seq_load(s, v0); v0->seq.running = 1; v0->seq.phase = 1; }
        if (!running && v0->seq.running) { v0->seq.running = 0; if (v0->seq.gate) { v0->seq.gate = 0; voice_trigger(s, v0, 0); } }
    }
    for (int f = 0; f < frames; f += CTL) {
        int n = frames - f < CTL ? frames - f : CTL;
        const float k = 0.05f;   /* fixed controller routes are smoothed (manual p. 33) */
        s->wheel += (s->t_wheel - s->wheel) * k; s->press += (s->t_press - s->press) * k;
        s->breath += (s->t_breath - s->breath) * k; s->foot += (s->t_foot - s->foot) * k;
        s->expr += (s->t_expr - s->expr) * k; s->bright += (s->t_bright - s->bright) * k;
        memset(buf, 0, sizeof buf);
        for (int i = 0; i < s->nv; i++) {
            voice_t *v = &s->v[i];
            voice_control(s, v, i, sps);
            if (!v->sounding && !(i == 0 && v->seq.running)) continue;
            voice_audio(s, v, buf, n);
            if (!v->gated && v->env[1].st == ST_IDLE && v->env[0].st == ST_IDLE && !v->seq.running && P(s, P_VCA_LEVEL) == 0 &&
                P(s, P_FB_LEVEL) == 0 && v->damt[0] + v->damt[1] + v->damt[2] == 0)
                v->sounding = 0;
        }
        float g = 0.35f * s->cc_vol;
        for (int i = 0; i < 2 * n; i++) {
            float x = buf[i] * g;
            x = x > 1 ? 1 : x < -1 ? -1 : x;
            out[2 * f + i] = (int16_t)lrintf(x * 32767);
        }
    }
}

/* ---------------- parameters ---------------- */
static int find_key(const char *k) {
    for (int i = 0; i < NPATCH; i++) if (!strcmp(PTAB[i].key, k)) return i;
    return -1;
}
static void note_name(int v, char *b, int n) {
    static const char *nm[12] = {"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"};
    snprintf(b, (size_t)n, "%s%d", nm[v % 12], v / 12 - 2);
}
static int format_value(const pe_t *s, int i, char *b, int n) {
    int v = s->patch[i];
    const char *f = PTAB[i].fmt;
    if (!strcmp(f, "note")) note_name(v, b, n);
    else if (!strcmp(f, "fbnote")) note_name(v + 24, b, n);
    else if (!strcmp(f, "cents")) snprintf(b, (size_t)n, "%+d", v - 50);
    else if (!strcmp(f, "ashape")) snprintf(b, (size_t)n, "%s", v == 0 ? "Sawtooth" : v == 1 ? "Triangle" : v == 2 ? "Saw-Tri" : "");
    else if (!strcmp(f, "wave")) snprintf(b, (size_t)n, "%d", v + 1);
    else if (!strcmp(f, "s99")) snprintf(b, (size_t)n, "%+d", v - 99);
    else if (!strcmp(f, "lfof")) {
        if (v > 150) snprintf(b, (size_t)n, "%s", SYNC_NAMES[v - 151]);
        else { float hz = pe_lfo_hz(v); snprintf(b, (size_t)n, hz < 10 ? "%.2f Hz" : "%.1f Hz", hz); }
    } else if (!strcmp(f, "lfoamt")) snprintf(b, (size_t)n, v > 100 ? "%d Sync" : "%d", v > 100 ? v - 100 : v);
    else if (!strcmp(f, "dest")) snprintf(b, (size_t)n, "%s", DEST_NAMES[clampi(v, 0, 68)]);
    else if (!strcmp(f, "sdest")) snprintf(b, (size_t)n, "%s", DEST_NAMES[clampi(v, 0, 75)]);
    else if (!strcmp(f, "src")) snprintf(b, (size_t)n, "%s", SRC_NAMES[clampi(v, 0, 24)]);
    else if (!strcmp(f, "dtime")) {
        if (v > 150) snprintf(b, (size_t)n, "%s", SYNC_NAMES[v - 151]);
        else snprintf(b, (size_t)n, "%.1f ms", pe_delay_seconds(v) * 1000);
    } else if (!strcmp(f, "glide")) {
        if (v == 0) snprintf(b, (size_t)n, "Off");
        else if (v == 200) snprintf(b, (size_t)n, "Key Off");
        else if (v > 100) snprintf(b, (size_t)n, "Finger %d", v - 99);
        else snprintf(b, (size_t)n, "%d", v);
    } else if (!strcmp(f, "xpose")) { if (!v) snprintf(b, (size_t)n, "Key Off"); else snprintf(b, (size_t)n, "%+d", v - 37); }
    else if (!strcmp(f, "hpf") || !strcmp(f, "dist")) {
        if (v == 0 || v == 100) snprintf(b, (size_t)n, "Off");
        else snprintf(b, (size_t)n, "%s %d", v < 100 ? "Out" : "In", v % 100);
    } else if (!strcmp(f, "tempo")) snprintf(b, (size_t)n, "%d BPM", v);
    else if (!strcmp(f, "onoff")) snprintf(b, (size_t)n, v ? "On" : "Off");
    else if (!strncmp(f, "step", 4)) {
        if (v == 101) snprintf(b, (size_t)n, "Reset");
        else if (v == 102) snprintf(b, (size_t)n, "Rest");
        else snprintf(b, (size_t)n, "%d", v);
    } else snprintf(b, (size_t)n, "%d", v);
    if (!strcmp(f, "ashape") && v >= 3) snprintf(b, (size_t)n, "Pulse %d", v - 3);
    return (int)strlen(b) + 1;
}

static void pe_set_param(void *h, const char *k, const char *val) {
    pe_t *s = h;
    if (!strcmp(k, "state")) {
        /* "PE1 <bank> <prog> <384 hex digits> <name>" */
        int b = 0, p = 0, pos = 0;
        if (sscanf(val, "PE1 %d %d %n", &b, &p, &pos) < 2 || pos <= 0) return;
        const char *hx = val + pos;
        uint8_t tmp[NPATCH];
        for (int i = 0; i < NPATCH; i++) {
            unsigned x;
            if (sscanf(hx + 2 * i, "%2x", &x) != 1) return;
            tmp[i] = (uint8_t)x;
        }
        memcpy(s->patch, tmp, NPATCH);
        patch_clamp(s->patch);
        const char *nm = hx + 2 * NPATCH;
        if (*nm == ' ') nm++;
        snprintf(s->name, sizeof s->name, "%s", nm);
        if (b >= 0 && b < s->nbanks && b != s->cur_bank) load_bank(s, b);
        s->cur_prog = clampi(p, 0, 127);
        s->display_rev++;
        return;
    }
    int i = find_key(k);
    if (i >= 0) { set_patch_value(s, i, atoi(val)); return; }
    int x = atoi(val);
    if (!strcmp(k, "bank")) { if (x != s->cur_bank && x < s->nbanks) { load_bank(s, x); select_program(s, 0); } }
    else if (!strcmp(k, "program")) { if (x != s->cur_prog) select_program(s, x); }
    else if (!strcmp(k, "seq_run")) s->seq_run = clampi(x, 0, 2);
    else if (!strcmp(k, "clock_src")) s->clock_src = clampi(x, 0, 1);
    else if (!strcmp(k, "seq_reset")) { if (x) for (int v = 0; v < s->nv; v++) seq_reset(&s->v[v].seq); }
    else if (!strcmp(k, "voices")) { int n = clampi(x, 1, MAXV); if (n != s->nv) { all_off(s); s->nv = n; } }
    else if (!strcmp(k, "lfo_bpm")) s->host_bpm = (float)atof(val);
    else if (!strcmp(k, "transport")) s->transport = x;
}

static int pe_get_param(void *h, const char *k, char *b, int n) {
    pe_t *s = h;
    if (!strcmp(k, "state")) {
        int o = snprintf(b, (size_t)n, "PE1 %d %d ", s->cur_bank, s->cur_prog);
        for (int i = 0; i < NPATCH && o + 3 < n; i++) o += snprintf(b + o, (size_t)(n - o), "%02x", s->patch[i]);
        if (o < n) o += snprintf(b + o, (size_t)(n - o), " %s", s->name);
        return o + 1;
    }
    if (!strcmp(k, "display_rev")) return snprintf(b, (size_t)n, "%d", s->display_rev) + 1;
    size_t kl = strlen(k);
    if (kl > 8 && !strcmp(k + kl - 8, "_display")) {
        char base[64];
        snprintf(base, sizeof base, "%.*s", (int)(kl - 8), k);
        int i = find_key(base);
        if (i >= 0) return format_value(s, i, b, n);
        if (!strcmp(base, "bank")) return snprintf(b, (size_t)n, "%d %s", s->cur_bank + 1, s->banks[s->cur_bank].name) + 1;
        if (!strcmp(base, "program")) return snprintf(b, (size_t)n, "%03d %s", s->cur_prog + 1, s->banknames[s->cur_prog]) + 1;
        return 0;
    }
    int i = find_key(k);
    if (i >= 0) return snprintf(b, (size_t)n, "%d", s->patch[i]) + 1;
    if (!strcmp(k, "bank")) return snprintf(b, (size_t)n, "%d", s->cur_bank) + 1;
    if (!strcmp(k, "program")) return snprintf(b, (size_t)n, "%d", s->cur_prog) + 1;
    if (!strcmp(k, "patch_name")) return snprintf(b, (size_t)n, "%s", s->name) + 1;
    if (!strcmp(k, "bank_name")) return snprintf(b, (size_t)n, "%s", s->banks[s->cur_bank].name) + 1;
    if (!strcmp(k, "seq_run")) return snprintf(b, (size_t)n, "%d", s->seq_run) + 1;
    if (!strcmp(k, "clock_src")) return snprintf(b, (size_t)n, "%d", s->clock_src) + 1;
    if (!strcmp(k, "seq_reset")) return snprintf(b, (size_t)n, "0") + 1;
    if (!strcmp(k, "voices")) return snprintf(b, (size_t)n, "%d", s->nv) + 1;
    if (!strcmp(k, "status"))
        return snprintf(b, (size_t)n, "%d banks, %s", s->nbanks, s->user_waves ? "user waves" : "open waves") + 1;
    return 0;
}

static const mpc_engine_t ENGINE = {pe_create, pe_destroy, pe_midi, pe_set_param, pe_get_param, pe_render, NULL};
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
