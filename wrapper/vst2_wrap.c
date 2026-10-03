/* =============================================================================
 * vst2_wrap.c — expose an engine (wrapper/engine.h) as a Linux VST2 plugin so
 * the built-in plugin host (JUCE) of MPC OS standalone devices can load it as a native track
 * instrument. Generic: the engine is linked in, and the generated params.h
 * (gen_vst.py, from the port's parameters) supplies the parameter table and identity.
 *
 * Host contract (MPC OS standalone): 44100 Hz, 128-frame blocks, the engine's own
 * block size. Audio is rendered in 128-frame chunks through a
 * small FIFO, so any host block size works; with 128-frame host blocks each
 * process() call renders exactly one DSP block and MIDI lands at its start.
 * ========================================================================== */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE   /* must precede every include */
#endif
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <ctype.h>
#include "params.h"
#ifndef HAS_LFO_BPM
#define HAS_LFO_BPM 0 /* 1: pass the host tempo to the DSP as "lfo_bpm" */
#endif
#ifdef WRAP_TRACE   /* poc/inputprobe: the port provides wrap_trace() and logs every raw host call (kind 0 = setParameter, 1 = getParameter) */
void wrap_trace(int kind, int idx, float value);
#define TRACE(kind, idx, value) wrap_trace(kind, idx, value)
#else
#define TRACE(kind, idx, value) ((void)0)
#endif
#ifndef MODULE_DIR
#define MODULE_DIR NULL /* set via vst.json "defines" for a DSP that reads its own files
                          * (ROMs, etc.) from "<module_dir>/..." (see jv880's create_instance) */
#endif
#ifdef MODULE_SUBDIR /* vst.json "defines": {"MODULE_SUBDIR": "\"engine\""}: data dir = <dir of the .so>/engine, found at runtime */
#include "plugin_dir.h"
#endif

#include "engine.h"
#include "popup.h"

#define DSP_BLOCK 128

/* ---- VST2 ABI (hand-written; no Steinberg SDK) -------------------------- */
typedef struct AEffect AEffect;
typedef intptr_t (*audioMasterCallback)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
struct AEffect {
    int32_t magic;
    intptr_t (*dispatcher)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
    void (*process)(AEffect *, float **, float **, int32_t);
    void (*setParameter)(AEffect *, int32_t, float);
    float (*getParameter)(AEffect *, int32_t);
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t resvd1, resvd2;
    int32_t initialDelay, realQualities, offQualities;
    float ioRatio;
    void *object, *user;
    int32_t uniqueID, version;
    void (*processReplacing)(AEffect *, float **, float **, int32_t);
    void (*processDoubleReplacing)(AEffect *, double **, double **, int32_t);
    char future[56];
};
typedef struct { int32_t type, byteSize, deltaFrames, flags; char data[16]; } VstEvent;
typedef struct {
    int32_t type, byteSize, deltaFrames, flags, noteLength, noteOffset;
    unsigned char midiData[4];
    char detune, noteOffVelocity, reserved1, reserved2;
} VstMidiEvent;
typedef struct { int32_t numEvents; intptr_t reserved; VstEvent *events[2]; } VstEvents;
typedef struct {
    double samplePos, sampleRate, nanoSeconds, ppqPos, tempo, barStartPos, cycleStartPos, cycleEndPos;
    int32_t timeSigNumerator, timeSigDenominator, smpteOffset, smpteFrameRate, samplesToNextClock, flags;
} VstTimeInfo;

enum {
    effOpen = 0, effClose = 1, effGetParamLabel = 6, effGetParamDisplay = 7, effGetParamName = 8,
    effSetSampleRate = 10, effSetBlockSize = 11, effMainsChanged = 12, effGetChunk = 23,
    effSetChunk = 24, effProcessEvents = 25, effCanBeAutomated = 26, effGetPlugCategory = 35,
    effGetEffectName = 45, effGetVendorString = 47, effGetProductString = 48,
    effGetVendorVersion = 49, effCanDo = 51, effGetVstVersion = 58,
};
enum { audioMasterAutomate = 0, audioMasterGetTime = 7, audioMasterUpdateDisplay = 42, kVstTempoValid = 1 << 10 };
enum { effFlagsCanReplacing = 1 << 4, effFlagsProgramChunks = 1 << 5, effFlagsIsSynth = 1 << 8 };

/* ---- per-instance state ------------------------------------------------- */
typedef struct {
    AEffect fx;
    audioMasterCallback master;
    void *dsp;
    int16_t block[DSP_BLOCK * 2];
    int pos;                 /* read position in block; DSP_BLOCK = empty */
    int16_t inb[DSP_BLOCK * 2];   /* effect: the host audio being collected for the engine */
    int inpos;
    double bpm;
    volatile int holdFrames[NPARAMS];  /* momentary params: frames left before reporting back to 0 (hold_ms) */
    float shadow[NPARAMS];   /* unrounded position last set on an integer param; <0 = none */
    signed char last_on[NPARAMS];  /* last "<key>_on" value told to the host, +1 (0 = unknown) */
    volatile char need_update_display;  /* deferred audioMasterUpdateDisplay -- see setParameter() */
    int last_refresh;        /* last value of the engine's "_refresh" counter, see housekeeping() */
    float open[NPARAMS];     /* popup "open" flags (popup.h): kept here, never sent to the DSP or saved */
    char chunk[8192];
} wrap_t;

static const mpc_engine_t *g_api;

static float clamp01(float v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

/* normalized 0..1 -> DSP display value string */
static void norm_to_str(const param_t *p, float n, char *buf, int len) {
    if (p->nopts) snprintf(buf, len, "%d", (int)lroundf(clamp01(n) * (p->nopts - 1)));
    else if (p->int_display) snprintf(buf, len, "%ld", lroundf(p->min + (p->max - p->min) * clamp01(n)));   /* round: a bare %g + atoi() truncates, so a sub-step Q-Link nudge never advances */
    else snprintf(buf, len, "%g", p->min + (p->max - p->min) * clamp01(n));
}

/* DSP display value string (number or enum label) -> normalized 0..1 */
static float str_to_norm(const param_t *p, const char *s) {
    if (p->nopts) {
        int idx = -1;
        if (isdigit((unsigned char)s[0])) idx = atoi(s);
        else
            for (int i = 0; i < p->nopts; i++)
                if (!strcasecmp(s, p->opts[i])) idx = i;
        if (idx < 0) idx = 0;
        return p->nopts > 1 ? (float)idx / (p->nopts - 1) : 0;
    }
    return p->max > p->min ? clamp01((float)((atof(s) - p->min) / (p->max - p->min))) : 0;
}

static float get_norm(wrap_t *w, int i) {
    char buf[64];
    if (i < 0 || i >= NPARAMS) return 0;
    if (popup_is(i)) return w->open[i];
    if (PARAMS[i].string_display) {
        /* a text param's value is not its text: a DSP may expose "<key>_on" (list-tile selection) */
        char k2[96];
        snprintf(k2, sizeof k2, "%s_on", PARAMS[i].key);
        if (g_api->get_param(w->dsp, k2, buf, sizeof buf) > 0) return atoi(buf) ? 1.0f : 0.0f;
    }
    if (g_api->get_param(w->dsp, PARAMS[i].key, buf, sizeof buf) <= 0) return PARAMS[i].def;
    float v = str_to_norm(&PARAMS[i], buf);
    /* An integer param is rounded on its way to the DSP, so a Q-Link nudge under one step would read back
     * as the old value and never accumulate. Hand the host its unrounded position while the DSP still
     * holds the value that position rounds to; if something else changed it, drop the shadow. */
    if (PARAMS[i].int_display && !PARAMS[i].nopts && PARAMS[i].max > PARAMS[i].min && w->shadow[i] >= 0) {
        float half = 0.5f / (PARAMS[i].max - PARAMS[i].min) + 1e-4f;
        if (fabsf(v - w->shadow[i]) <= half) return w->shadow[i];
        w->shadow[i] = -1;
    }
    return v;
}

static void setParameter(AEffect *e, int32_t i, float n) {
    wrap_t *w = e->object;
    TRACE(0, i, n);
    char buf[64];
    if (i < 0 || i >= NPARAMS) return;
    const param_t *p = &PARAMS[i];
    int nudge = 0;
    if (popup_set(w->open, i, n)) return;
    if (p->step_target >= 0) {
        /* A momentary nudge of ANOTHER param (see gen_vst.py's step_of/step_delta comment). Reads
         * the target's CURRENT value straight from the DSP, not our own cached norm, so it's
         * correct even if the DSP changed it independently (e.g. loading a bank shifts the patch).
         * This trigger's own key is never sent to the DSP at all. */
        if (n > 0.5f) {
            const param_t *tp = &PARAMS[p->step_target];
            if (g_api->get_param(w->dsp, tp->key, buf, sizeof buf) > 0) {
                float cur = (float)atof(buf) + p->step_delta;
                if (cur < tp->min) cur = tp->min;
                if (cur > tp->max) cur = tp->max;
                snprintf(buf, sizeof buf, "%g", cur);
                g_api->set_param(w->dsp, tp->key, buf);
            }
            w->holdFrames[i] = 1;
        }
        /* A string-display readout (e.g. patch_name/bank_name) bound elsewhere via get= has a
         * degenerate min==max range (its OWN reported normalized value never changes), so MPC has
         * no value-change signal telling it to re-poll THAT param's displayed text just because
         * THIS one changed it indirectly. audioMasterUpdateDisplay is the documented escape hatch
         * (docs/NOTES.md: MPC re-polls a Label "Name" on it; readouts stayed stuck on their
         * initial paint here without it -- confirmed on a real device, both via a stepper arrow
         * tap and a direct Q-Link turn on the underlying param). Deferred to processReplacing(),
         * same as w->holdFrames[] -- the host must not be re-entered from inside its own call to us. */
        w->need_update_display = 1;
        return;
    }
    if (p->nopts > 1) {
        /* A value on an option (button press, preset, automation) selects it. A value
         * between options is a Q-Link/encoder nudge from the current one: step one
         * option that way, else small nudges round back and never change state. */
        float pos = clamp01(n) * (p->nopts - 1);
        if (fabsf(pos - roundf(pos)) > 0.001f) {
            nudge = 1;
            float cur = get_norm(w, i) * (p->nopts - 1);
            int idx = (int)lroundf(cur) + (pos > cur ? 1 : -1);
            if (idx < 0) idx = 0;
            if (idx > p->nopts - 1) idx = p->nopts - 1;
            n = (float)idx / (p->nopts - 1);
        }
    }
    norm_to_str(p, n, buf, sizeof buf);
    g_api->set_param(w->dsp, PARAMS[i].key, buf);
    w->shadow[i] = (p->int_display && !p->nopts) ? clamp01(n) : -1;
    if (PARAMS[i].momentary && n > 0.5f) w->holdFrames[i] = PARAMS[i].hold_ms > 0 ? (int)(PARAMS[i].hold_ms * 44.1f) : 1;
    if (!nudge) popup_picked(w->open, w->holdFrames, i);   /* a list pick closes it; a Q-Link nudge doesn't */
    w->need_update_display = 1;   /* deferred to processReplacing(), see the step_target branch above */
}

static float getParameter(AEffect *e, int32_t i) {
    float v = get_norm(e->object, i);
    TRACE(1, i, v);
    return v;
}

static void update_tempo(wrap_t *w) {
    VstTimeInfo *ti = (VstTimeInfo *)w->master(&w->fx, audioMasterGetTime, 0, kVstTempoValid, 0, 0);
    if (!ti || !(ti->flags & kVstTempoValid) || ti->tempo <= 0) return;
    if (fabs(ti->tempo - w->bpm) > 0.01) {
        char buf[32];
        w->bpm = ti->tempo;
        snprintf(buf, sizeof buf, "%.2f", w->bpm);
        g_api->set_param(w->dsp, "lfo_bpm", buf);
    }
}

/* accumulate=1 is VST2's legacy process(), which must ADD to the output buffers; hosts here call
 * processReplacing, but a NULL e->process would crash any host that tried the old call. */
static void render_frames(wrap_t *w, float **out, int32_t n, int accumulate) {
    for (int32_t i = 0; i < n; i++) {
        if (w->pos >= DSP_BLOCK) {
            g_api->render(w->dsp, w->block, DSP_BLOCK);
            w->pos = 0;
        }
        float l = w->block[w->pos * 2] * (1.0f / 32768.0f), r = w->block[w->pos * 2 + 1] * (1.0f / 32768.0f);
        if (accumulate) { out[0][i] += l; out[1][i] += r; }
        else { out[0][i] = l; out[1][i] = r; }
        w->pos++;
    }
}

static void housekeeping(AEffect *e, int32_t n) {
    wrap_t *w = e->object;
    if (HAS_LFO_BPM) update_tempo(w);
    /* A trigger param (e.g. Generate) fired: tell the host it is back to 0 so
     * buttons bound to it drop their highlight. Done here, not inside
     * setParameter, so the host is not re-entered from its own call. */
    for (int i = 0; i < NPARAMS; i++)
        if (w->holdFrames[i] > 0 && (w->holdFrames[i] -= n) <= 0) { w->holdFrames[i] = 0; w->master(&w->fx, audioMasterAutomate, i, 0, 0, 0.0f); }
    /* An engine whose on-screen text changes by itself (a scan finishing, a pad hit moving the selection) has no
     * setParameter to piggy-back on. It may expose a "_refresh" counter: when the value changes, ask the host to
     * re-read the display text. Engines without the key answer 0 (get_param <= 0) and cost one cheap call. The call must
     * not block: this runs on the audio thread. */
    {
        char rb[16];
        if (g_api->get_param(w->dsp, "_refresh", rb, sizeof rb) > 0) {
            int r = atoi(rb);
            if (r != w->last_refresh) { w->last_refresh = r; w->need_update_display = 1; }
        }
    }
    if (w->need_update_display) {
        w->need_update_display = 0;
        w->master(&w->fx, audioMasterUpdateDisplay, 0, 0, 0, 0.0f);
        /* list-tile selection: the host doesn't re-read a button's value on UpdateDisplay, so push changes */
        for (int i = 0; i < NPARAMS; i++) {
            if (!PARAMS[i].string_display) continue;
            char k2[96], b2[16];
            snprintf(k2, sizeof k2, "%s_on", PARAMS[i].key);
            if (g_api->get_param(w->dsp, k2, b2, sizeof b2) <= 0) continue;
            int on = atoi(b2) ? 1 : 0;
            if (w->last_on[i] != on + 1) {
                w->last_on[i] = (signed char)(on + 1);
                w->master(&w->fx, audioMasterAutomate, i, 0, 0, (float)on);
            }
        }
    }
}

#ifdef PLUG_EFFECT
static int16_t f2s(float f) { f *= 32768.0f; return f >= 32767.0f ? 32767 : f <= -32768.0f ? -32768 : (int16_t)lrintf(f); }

/* An effect: whole 128-frame host blocks go straight through the engine (MPC's period is 128, so no added latency);
 * any other block size is collected and processed one block late. */
static void run_block(AEffect *e, float **in, float **out, int32_t n, int accumulate) {
    wrap_t *w = e->object;
    housekeeping(e, n);
    /* A conforming host passes real input to an effect, but a plugin scanner (and the device's own load
     * probe) may call processReplacing with in == NULL; treat a missing input channel as silence. */
    int have_in = in && in[0] && in[1];
    int32_t i = 0;
    while (i < n) {
        int aligned = w->inpos == 0 && w->pos >= DSP_BLOCK && n - i >= DSP_BLOCK;
        if (aligned) {
            for (int j = 0; j < DSP_BLOCK; j++) { w->inb[2 * j] = have_in ? f2s(in[0][i + j]) : 0; w->inb[2 * j + 1] = have_in ? f2s(in[1][i + j]) : 0; }
            g_api->process(w->dsp, w->inb, w->block, DSP_BLOCK);
            for (int j = 0; j < DSP_BLOCK; j++) {
                float l = w->block[2 * j] * (1.0f / 32768.0f), r = w->block[2 * j + 1] * (1.0f / 32768.0f);
                if (accumulate) { out[0][i + j] += l; out[1][i + j] += r; } else { out[0][i + j] = l; out[1][i + j] = r; }
            }
            i += DSP_BLOCK;
            continue;
        }
        float l = 0, r = 0;
        if (w->pos < DSP_BLOCK) { l = w->block[w->pos * 2] * (1.0f / 32768.0f); r = w->block[w->pos * 2 + 1] * (1.0f / 32768.0f); w->pos++; }
        if (accumulate) { out[0][i] += l; out[1][i] += r; } else { out[0][i] = l; out[1][i] = r; }
        w->inb[2 * w->inpos] = have_in ? f2s(in[0][i]) : 0; w->inb[2 * w->inpos + 1] = have_in ? f2s(in[1][i]) : 0;
        if (++w->inpos == DSP_BLOCK) { g_api->process(w->dsp, w->inb, w->block, DSP_BLOCK); w->pos = 0; w->inpos = 0; }
        i++;
    }
}
static void processReplacing(AEffect *e, float **in, float **out, int32_t n) { run_block(e, in, out, n, 0); }
static void process(AEffect *e, float **in, float **out, int32_t n) { run_block(e, in, out, n, 1); }
#else
static void run_block(AEffect *e, float **out, int32_t n, int accumulate) {
    wrap_t *w = e->object;
    housekeeping(e, n);
    render_frames(w, out, n, accumulate);
}

static void processReplacing(AEffect *e, float **in, float **out, int32_t n) { (void)in; run_block(e, out, n, 0); }
static void process(AEffect *e, float **in, float **out, int32_t n) { (void)in; run_block(e, out, n, 1); }
#endif

static void copy_str(void *dst, const char *src, size_t max) {
    strncpy(dst, src, max - 1);
    ((char *)dst)[max - 1] = 0;
}

static intptr_t dispatcher(AEffect *e, int32_t op, int32_t idx, intptr_t v, void *p, float o) {
    wrap_t *w = e->object;
    (void)o;
    switch (op) {
    case effOpen: return 1;
    case effClose:
        g_api->destroy(w->dsp);
        free(w);
        return 1;
#ifdef PLUG_EFFECT
    case effGetPlugCategory: return 1; /* kPlugCategEffect */
#else
    case effGetPlugCategory: return 2; /* kPlugCategSynth */
#endif
    case effGetEffectName:
    case effGetProductString: copy_str(p, PLUG_NAME, 32); return 1;
    case effGetVendorString: copy_str(p, PLUG_VENDOR, 32); return 1;
    case effGetVendorVersion: return PLUG_VERSION;
    case effGetVstVersion: return 2400;
    case effCanBeAutomated: return idx >= 0 && idx < NPARAMS;
    case effGetParamName:
        if (idx >= 0 && idx < NPARAMS) {
            char buf[64], k2[96];
            /* "dynamic_name" params: the DSP may rename them (e.g. a drum machine's per-machine knob
             * labels); MPC re-reads names on audioMasterUpdateDisplay (docs/NOTES.md). */
            snprintf(k2, sizeof k2, "%s_name", PARAMS[idx].key);
            if (PARAMS[idx].dynamic_name && g_api->get_param(w->dsp, k2, buf, sizeof buf) > 0) copy_str(p, buf, 32);
            else copy_str(p, PARAMS[idx].name, 32);
        }
        return 1;
    case effGetParamLabel:
        if (idx >= 0 && idx < NPARAMS) copy_str(p, PARAMS[idx].unit, 8);
        return 1;
    case effGetParamDisplay: {
        char buf[64];
        if (idx < 0 || idx >= NPARAMS) return 0;
        const param_t *pp = &PARAMS[idx];
        char k2[96];
        snprintf(k2, sizeof k2, "%s_display", pp->key);
        if (pp->dynamic_display && g_api->get_param(w->dsp, k2, buf, sizeof buf) > 0) {
            copy_str(p, buf, 24);   /* text the DSP composes (e.g. a destination's own name) */
        } else if (pp->nopts) {
            int k = (int)lroundf(get_norm(w, idx) * (pp->nopts - 1));
            copy_str(p, pp->opts[k], 24);
        } else if (g_api->get_param(w->dsp, pp->key, buf, sizeof buf) > 0) {
            if (pp->string_display) copy_str(p, buf, 24);   /* real text (a name, a status), not a number */
            else snprintf(p, 24, "%.*f", (pp->int_display || fabs(pp->max - pp->min) > 20) ? 0 : 1, atof(buf));
        }
        return 1;
    }
    case effSetSampleRate: case effSetBlockSize: case effMainsChanged: return 1;
    case effProcessEvents: {
        VstEvents *ev = p;
        for (int i = 0; i < ev->numEvents; i++)
            if (ev->events[i]->type == 1) {
                VstMidiEvent *m = (VstMidiEvent *)ev->events[i];
                g_api->midi(w->dsp, m->midiData, 3);
            }
        return 1;
    }
    case effCanDo:
        return (!strcmp(p, "receiveVstEvents") || !strcmp(p, "receiveVstMidiEvent") ||
                !strcmp(p, "receiveVstTimeInfo")) ? 1 : -1;
    case effGetChunk: {
        int len = g_api->get_param(w->dsp, "state", w->chunk, sizeof w->chunk);
        if (len <= 0) return 0;
        *(void **)p = w->chunk;
        return (intptr_t)strlen(w->chunk) + 1;
    }
    case effSetChunk: {
        if (v <= 0 || (size_t)v > sizeof w->chunk) return 0;
        memcpy(w->chunk, p, v);
        w->chunk[v - 1] = 0;
        g_api->set_param(w->dsp, "state", w->chunk);
        return 1;
    }
    default: return 0;
    }
}

__attribute__((visibility("default"))) AEffect *VSTPluginMain(audioMasterCallback master) {
    if (!g_api) g_api = mpc_engine();
    if (!g_api) return NULL;
#ifdef PLUG_EFFECT
    if (!g_api->process) return NULL;   /* an effect port must provide process() */
#endif
    wrap_t *w = calloc(1, sizeof *w);
    if (!w) return NULL;
    for (int i = 0; i < NPARAMS; i++) w->shadow[i] = -1;
#ifdef MODULE_SUBDIR
    char data_dir[600], here[512];
    const char *module_dir = MODULE_DIR;   /* an absolute MODULE_DIR is still the fallback */
    if (mpc_plugin_dir(here, sizeof here) && snprintf(data_dir, sizeof data_dir, "%s/%s", here, MODULE_SUBDIR) < (int)sizeof data_dir)
        module_dir = data_dir;
    w->dsp = g_api->create(module_dir);
#else
    w->dsp = g_api->create(MODULE_DIR);
#endif
    if (!w->dsp) { free(w); return NULL; }
    w->master = master;
    w->pos = DSP_BLOCK;
    AEffect *e = &w->fx;
    e->magic = 0x56737450; /* 'VstP' */
    e->dispatcher = dispatcher;
    e->process = process;
    e->setParameter = setParameter;
    e->getParameter = getParameter;
    e->processReplacing = processReplacing;
    e->numParams = NPARAMS;
#ifdef PLUG_EFFECT
    e->numInputs = 2;
    e->numOutputs = 2;
    e->flags = effFlagsCanReplacing | effFlagsProgramChunks;
#else
    e->numInputs = 0;
    e->numOutputs = 2;
    e->flags = effFlagsCanReplacing | effFlagsIsSynth | effFlagsProgramChunks;
#endif
    e->uniqueID = PLUG_UID;
    e->version = PLUG_VERSION;
    e->object = w;
    return e;
}
