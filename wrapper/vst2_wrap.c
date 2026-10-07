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
#include <pthread.h>
#include "params.h"
#ifndef HAS_LFO_BPM
#define HAS_LFO_BPM 0 /* 1: pass the host tempo to the DSP as "lfo_bpm" */
#endif
#ifndef HAS_DISPLAY_REV
#define HAS_DISPLAY_REV 0 /* 1: the DSP changes values by itself (a worker thread, a state machine): on the readout poll
                            * (every 100 ms, see housekeeping) read its "display_rev" and, when it changed, report every
                            * value that moved and ask for an UpdateDisplay (status text, when= panels, meters) */
#endif
#ifndef PARAM_TEXT_MAX
#define PARAM_TEXT_MAX 24 /* value text length handed to the host, NUL included. The VST2 spec says 8, JUCE's buffer is
                           * bigger; ports that show sentences (status lines) raise it via vst.json "defines" */
#endif
#ifndef SAMPLE_ACCURATE
#define SAMPLE_ACCURATE 0 /* 1 (instruments only): start each MIDI event at its VstMidiEvent.deltaFrames instead of at the
                            * block start. The wrapper then renders exactly the frames the host asks for, in pieces of at
                            * most 128 between events, so the engine's render() must accept any 1..128 frames (engine.h) */
#endif
#if SAMPLE_ACCURATE && defined(PLUG_EFFECT)
#error "SAMPLE_ACCURATE is for instruments: an effect has no notes to place"
#endif
#ifdef WRAP_TRACE   /* poc/inputprobe: the port provides wrap_trace() and logs every raw host call (kind 0 = setParameter, 1 = getParameter) */
void wrap_trace(int kind, int idx, float value);
#define TRACE(kind, idx, value) wrap_trace(kind, idx, value)
#else
#define TRACE(kind, idx, value) ((void)0)
#endif
#ifndef HAS_TRANSPORT
#define HAS_TRANSPORT 0 /* 1: tell the DSP when the host transport plays/stops as "transport" = "1"/"0"; a jump back
                          * in song position while playing (a loop, a locate) is sent as "1" again */
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
#define WRAP_EVQ 256   /* SAMPLE_ACCURATE: events queued per block; more are applied at once */

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
    effSetChunk = 24, effSetProgram = 2, effGetProgram = 3, effGetProgramName = 5,
    effGetProgramNameIndexed = 29, effProcessEvents = 25, effCanBeAutomated = 26, effGetPlugCategory = 35,
    effGetEffectName = 45, effGetVendorString = 47, effGetProductString = 48,
    effGetVendorVersion = 49, effCanDo = 51, effGetVstVersion = 58,
};
enum { audioMasterAutomate = 0, audioMasterGetTime = 7, audioMasterUpdateDisplay = 42, kVstTempoValid = 1 << 10 };
enum { kVstTransportPlaying = 1 << 1, kVstPpqPosValid = 1 << 9 };
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
    volatile char changed[NPARAMS];  /* params the plugin changed itself (step_of on an option), to report */
    float last_pos[NPARAMS]; /* stepped params: the last position the host asked for, in steps (-1 = none yet) */
    float qacc[NPARAMS];     /* qlink_ticks: turn events counted toward the next step (see setParameter) */
    signed char last_on[NPARAMS];  /* last "<key>_on" value told to the host, +1 (0 = unknown, -1 = the engine has no such key) */
    unsigned last_text[NPARAMS];   /* hash of a text readout's last value (see housekeeping) */
    int on_poll, text_poll;        /* frames until the next "<key>_on" poll / readout poll (see housekeeping) */
    int playing;             /* HAS_TRANSPORT: last transport state sent */
    double ppq;              /* HAS_TRANSPORT: song position at the last block, to spot a jump back */
    volatile char need_update_display;  /* deferred audioMasterUpdateDisplay -- see setParameter() */
    char last_rev[16];       /* HAS_DISPLAY_REV: the "display_rev" last seen */
    float last_norm[NPARAMS];   /* HAS_DISPLAY_REV: value last reported per param (-1 = never) */
    float open[NPARAMS];     /* popup "open" flags (popup.h): kept here, never sent to the DSP or saved */
    char chunk[8192];
    pthread_mutex_t lock;    /* one engine call at a time: see eng_set() */
    int nrpn;                /* HAS_NRPN: the parameter CC 99/98 selected (-1: none), its coarse value from CC 6 */
    int nrpn_msb;
    volatile char cc_changed[NPARAMS];   /* set from MIDI CC/NRPN, reported to the host at most every 1024 frames */
    int cc_report;           /* frames until CC-driven changes are reported again */
    int program;             /* NPRESETS: the preset last picked (not in the engine's state; 0 after a reload) */
#if SAMPLE_ACCURATE
    struct { int32_t frame; uint8_t msg[3]; } evq[WRAP_EVQ];   /* this block's MIDI, sorted by frame (see queue_midi) */
    int nev;
#endif
} wrap_t;

static const mpc_engine_t *g_api;

/* One engine call at a time per instance. A JUCE host (MPC's) sets and reads parameters, chunks and displays on its
 * message thread while audio runs on another, and most engines assume a single caller (a voice-count change emptied a
 * list the audio thread was using and aborted MPC in another fork; docs/NOTES.md 2026-10-07). The lock is recursive
 * (an engine calling back into the wrapper can't deadlock) and priority-inheriting (audio waiting on a short screen-side
 * call lifts that thread). The host is never called with it held. Uncontended it costs an atomic operation. */
static void eng_set(wrap_t *w, const char *k, const char *v) {
    pthread_mutex_lock(&w->lock); g_api->set_param(w->dsp, k, v); pthread_mutex_unlock(&w->lock);
}
static int eng_get(wrap_t *w, const char *k, char *buf, int n) {
    pthread_mutex_lock(&w->lock); int r = g_api->get_param(w->dsp, k, buf, n); pthread_mutex_unlock(&w->lock); return r;
}
static void eng_midi(wrap_t *w, const uint8_t *m, int n) {
    pthread_mutex_lock(&w->lock); g_api->midi(w->dsp, m, n); pthread_mutex_unlock(&w->lock);
}
static void eng_render(wrap_t *w, int16_t *out, int n) {
    pthread_mutex_lock(&w->lock); g_api->render(w->dsp, out, n); pthread_mutex_unlock(&w->lock);
}
#ifdef PLUG_EFFECT
static void eng_process(wrap_t *w, const int16_t *in, int16_t *out, int n) {
    pthread_mutex_lock(&w->lock); g_api->process(w->dsp, in, out, n); pthread_mutex_unlock(&w->lock);
}
#endif

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
        if (eng_get(w, k2, buf, sizeof buf) > 0) return atoi(buf) ? 1.0f : 0.0f;
    }
    if (eng_get(w, PARAMS[i].key, buf, sizeof buf) <= 0) return PARAMS[i].def;
    return str_to_norm(&PARAMS[i], buf);
}

/* Where a param that moves in whole steps (an option list, a whole-number value) lands, in steps from its minimum.
 * The host nudges it two ways: the data wheel sends the current value plus a fraction of a step, while a drag or a
 * Q-Link sweep keeps sending positions from where it started, which just after a step still round back to the old
 * value (the knob then flickers between two values). So round toward the way it's moving: from the host's last
 * position while it moves continuously, else from the current value. A turn smaller than one step still moves one
 * step, and a sweep moves steadily. */
static float settle(float pos, float cur, float last) {
    if (fabsf(pos - roundf(pos)) <= 0.001f) return roundf(pos);   /* on a step: a click, a preset, automation */
    float dir = (last >= 0 && fabsf(pos - last) < 0.5f) ? pos - last : pos - cur;
    if (dir == 0) return roundf(cur);
    return dir > 0 ? ceilf(pos - 0.001f) : floorf(pos + 0.001f);
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
            if (tp->nopts > 1 && eng_get(w, tp->key, buf, sizeof buf) > 0) {
                /* An option target (e.g. a synth model picked with two buttons): step by index, wrapping like
                 * a hardware selector button, and report the new value so the host redraws what shows it. */
                int idx = (int)lroundf(str_to_norm(tp, buf) * (tp->nopts - 1)) + (int)lroundf(p->step_delta);
                idx = ((idx % tp->nopts) + tp->nopts) % tp->nopts;
                norm_to_str(tp, (float)idx / (tp->nopts - 1), buf, sizeof buf);
                eng_set(w, tp->key, buf);
                w->changed[p->step_target] = 1;
            } else if (eng_get(w, tp->key, buf, sizeof buf) > 0) {
                float cur = (float)atof(buf) + p->step_delta;
                if (cur < tp->min) cur = tp->min;
                if (cur > tp->max) cur = tp->max;
                snprintf(buf, sizeof buf, "%g", cur);
                eng_set(w, tp->key, buf);
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
    if (p->nudge_gain > 1 && p->nopts <= 1 && p->max > p->min) {
        /* "nudge_gain": a small move (data wheel click, Q-Link event) is multiplied; a bigger one is a drag or a jump */
        const float cur = get_norm(w, i), d = n - cur;
        if (d != 0 && fabsf(d) < 0.02f) n = clamp01(cur + d * p->nudge_gain);
    }
    if (p->nopts > 1) {
        /* A value on an option (button press, preset, automation) selects it; one between options is a
         * Q-Link / data wheel / drag move, settled as above. A param with "qlink_ticks" > 1 instead counts small
         * moves and steps one option per qlink_ticks of them in the same direction, like a detented knob (a slow
         * Q-Link turn otherwise runs through a short list); turning back starts over. MPC sends Q-Link and data
         * wheel moves alike (a small delta from the value it read back; docs/NOTES.md "Input probe"), so the
         * wheel then takes qlink_ticks clicks per option too: opt in only where that is wanted. */
        float pos = clamp01(n) * (p->nopts - 1), cur = get_norm(w, i) * (p->nopts - 1), idx;
        nudge = fabsf(pos - roundf(pos)) > 0.001f;
        if (p->qlink_ticks > 1 && nudge && fabsf(pos - cur) < 0.5f) {
            float d = pos - cur;
            w->last_pos[i] = pos;
            if (d * w->qacc[i] < 0) w->qacc[i] = 0;
            w->qacc[i] += d > 0 ? 1 : -1;
            if (fabsf(w->qacc[i]) < p->qlink_ticks) return;   /* the host reads the same option back */
            w->qacc[i] = 0;
            idx = roundf(cur) + (d > 0 ? 1 : -1);
        } else {
            w->qacc[i] = 0;                  /* picked or jumped outright: nothing banked */
            idx = settle(pos, cur, w->last_pos[i]);
            w->last_pos[i] = pos;
        }
        n = clamp01(idx / (p->nopts - 1));
    }
    else if (p->int_display && p->max > p->min) {
        /* whole numbers: settled like options, or counted with "qlink_ticks" > 1 (a short range such as a MIDI
         * channel). A move of half a step or more is a direct set (automation, a drag), not a tick, unless the param
         * has "nudge_pct": a long list (a bank list of up to 998) a Q-Link event or wheel click would cross eight to ten
         * entries of at a time (1/128 and 1/100 of the range), so any move up to that percent of the range counts as one
         * tick, one step in its direction (one per qlink_ticks of them with both). MPC clamps the value it sends, so a
         * move that lands on the minimum or maximum from within that distance is a tick too, not a jump to the end. */
        float span = p->max - p->min, pos = clamp01(n) * span, cur = get_norm(w, i) * span, steps;
        float tickmax = p->nudge_pct > 0 ? fmaxf(0.5f, span * p->nudge_pct / 100.0f) : 0.5f;
        int edge = (pos < 0.001f || pos > span - 0.001f) && fabsf(pos - cur) >= 0.5f;
        if ((p->qlink_ticks > 1 || p->nudge_pct > 0) && (fabsf(pos - roundf(pos)) > 0.001f || edge) && fabsf(pos - cur) < tickmax) {
            float d = pos - cur;
            w->last_pos[i] = pos;
            if (p->qlink_ticks > 1) {
                if (d * w->qacc[i] < 0) w->qacc[i] = 0;
                w->qacc[i] += d > 0 ? 1 : -1;
                if (fabsf(w->qacc[i]) < p->qlink_ticks) return;   /* the host reads the same value back */
                w->qacc[i] = 0;
            }
            steps = roundf(cur) + (d > 0 ? 1 : -1);
        } else {
            w->qacc[i] = 0;
            steps = settle(pos, cur, w->last_pos[i]);
            w->last_pos[i] = pos;
        }
        n = clamp01(steps / span);
    }
    norm_to_str(p, n, buf, sizeof buf);
    eng_set(w, PARAMS[i].key, buf);
    if (PARAMS[i].momentary && n > 0.5f) w->holdFrames[i] = PARAMS[i].hold_ms > 0 ? (int)(PARAMS[i].hold_ms * 44.1f) : 1;
    if (!nudge) popup_picked(w->open, w->holdFrames, i);   /* a list pick closes it; a Q-Link nudge doesn't */
    w->need_update_display = 1;   /* deferred to processReplacing(), see the step_target branch above */
}

static float getParameter(AEffect *e, int32_t i) {
    float v = get_norm(e->object, i);
    TRACE(1, i, v);
    return v;
}

static void update_transport(wrap_t *w, const VstTimeInfo *ti) {
    int playing = (ti->flags & kVstTransportPlaying) != 0, ppq_ok = (ti->flags & kVstPpqPosValid) != 0;
    int restart = playing && w->playing && ppq_ok && ti->ppqPos < w->ppq - 0.01;
    if (playing != w->playing || restart) eng_set(w, "transport", playing ? "1" : "0");
    w->playing = playing;
    if (ppq_ok) w->ppq = ti->ppqPos;
}

static void update_tempo(wrap_t *w) {
    VstTimeInfo *ti = (VstTimeInfo *)w->master(&w->fx, audioMasterGetTime, 0,
                                              kVstTempoValid | (HAS_TRANSPORT ? kVstPpqPosValid : 0), 0, 0);
    if (!ti) return;
    if (HAS_TRANSPORT) update_transport(w, ti);
    if (!HAS_LFO_BPM || !(ti->flags & kVstTempoValid) || ti->tempo <= 0) return;
    if (fabs(ti->tempo - w->bpm) > 0.01) {
        char buf[32];
        w->bpm = ti->tempo;
        snprintf(buf, sizeof buf, "%.2f", w->bpm);
        eng_set(w, "lfo_bpm", buf);
    }
}

/* accumulate=1 is VST2's legacy process(), which must ADD to the output buffers; hosts here call
 * processReplacing, but a NULL e->process would crash any host that tried the old call. */
#if !SAMPLE_ACCURATE
static void render_frames(wrap_t *w, float **out, int32_t n, int accumulate) {
    for (int32_t i = 0; i < n; i++) {
        if (w->pos >= DSP_BLOCK) {
            eng_render(w, w->block, DSP_BLOCK);
            w->pos = 0;
        }
        float l = w->block[w->pos * 2] * (1.0f / 32768.0f), r = w->block[w->pos * 2 + 1] * (1.0f / 32768.0f);
        if (accumulate) { out[0][i] += l; out[1][i] += r; }
        else { out[0][i] = l; out[1][i] = r; }
        w->pos++;
    }
}
#endif

#if SAMPLE_ACCURATE
/* Instruments with SAMPLE_ACCURATE: no 128-frame buffering. The engine renders exactly the frames the host asked for
 * (at most DSP_BLOCK per call), and each queued MIDI event goes in right before its own frame. An event past the end
 * of the block (deltaFrames >= n) goes in after the last frame, i.e. at the start of the next block. */
static void queue_midi(wrap_t *w, const uint8_t *msg, int32_t frame) {
    if (w->nev == WRAP_EVQ) { eng_midi(w, msg, 3); return; }   /* full: apply now, as without SAMPLE_ACCURATE */
    if (frame < 0) frame = 0;
    int k = w->nev++;
    while (k > 0 && w->evq[k - 1].frame > frame) { w->evq[k] = w->evq[k - 1]; k--; }   /* stable: after equal frames */
    w->evq[k].frame = frame;
    memcpy(w->evq[k].msg, msg, 3);
}

static void drain_midi(wrap_t *w) {
    for (int k = 0; k < w->nev; k++) eng_midi(w, w->evq[k].msg, 3);
    w->nev = 0;
}

static void render_events(wrap_t *w, float **out, int32_t n, int accumulate) {
    int32_t i = 0;
    int k = 0;
    while (i < n) {
        while (k < w->nev && w->evq[k].frame <= i) eng_midi(w, w->evq[k++].msg, 3);
        int32_t end = (k < w->nev && w->evq[k].frame < n) ? w->evq[k].frame : n;
        while (i < end) {
            int len = end - i > DSP_BLOCK ? DSP_BLOCK : (int)(end - i);
            eng_render(w, w->block, len);
            for (int j = 0; j < len; j++) {
                float l = w->block[j * 2] * (1.0f / 32768.0f), r = w->block[j * 2 + 1] * (1.0f / 32768.0f);
                if (accumulate) { out[0][i + j] += l; out[1][i + j] += r; }
                else { out[0][i + j] = l; out[1][i + j] = r; }
            }
            i += len;
        }
    }
    for (; k < w->nev; k++) eng_midi(w, w->evq[k].msg, 3);
    w->nev = 0;
}
#endif

static void housekeeping(AEffect *e, int32_t n) {
    wrap_t *w = e->object;
    if (HAS_LFO_BPM || HAS_TRANSPORT) update_tempo(w);
    /* A trigger param (e.g. Generate) fired: tell the host it is back to 0 so
     * buttons bound to it drop their highlight. Done here, not inside
     * setParameter, so the host is not re-entered from its own call. */
    for (int i = 0; i < NPARAMS; i++)
        if (w->holdFrames[i] > 0 && (w->holdFrames[i] -= n) <= 0) { w->holdFrames[i] = 0; w->master(&w->fx, audioMasterAutomate, i, 0, 0, 0.0f); }
    for (int i = 0; i < NPARAMS; i++)
        if (w->changed[i]) { w->changed[i] = 0; w->master(&w->fx, audioMasterAutomate, i, 0, 0, get_norm(w, i)); }
    /* Text params are polled, not only read after a screen tap, because MIDI alone can change them (a pad plays
     * a chord, nothing on screen touched):
     * - list-tile selection ("<key>_on"), every 10 ms: the host doesn't re-read a button's value on UpdateDisplay,
     *   so push a change with audioMasterAutomate (a tile lights while the pad is held);
     * - a readout's text, every 100 ms: the host only re-reads it on UpdateDisplay, so ask for one when the text
     *   changed (a chord name on a page without tiles stayed stale until something else was tapped).
     * Only "display":"string" params without "poll":false are polled. A "<key>_on" the engine does not answer is
     * asked once, then skipped. The two countdowns run independently of the block size; a readout that changes
     * constantly (a clock) asks for at most 10 UpdateDisplays a second. Costs about one get_param per polled param per poll on the
     * audio thread; docs/BENCH.md measures it (Chordsmith, 10 polled params: idle p99 under 4% of a block). */
    int poll_on = (w->on_poll -= n) <= 0, poll_text = (w->text_poll -= n) <= 0;
    if (poll_on && (w->on_poll += 441) <= 0) w->on_poll = 441;        /* keep the remainder, so the rate holds */
    if (poll_text && (w->text_poll += 4410) <= 0) w->text_poll = 4410;   /* for any block size */
    for (int i = 0; (poll_on || poll_text) && i < NPARAMS; i++) {
        if (!PARAMS[i].string_display || PARAMS[i].no_poll) continue;
        char k2[96], b2[64];   /* 64: the hash sees the first 63 characters, enough for a 47-character readout */
        if (poll_on && w->last_on[i] >= 0) {
            snprintf(k2, sizeof k2, "%s_on", PARAMS[i].key);
            if (eng_get(w, k2, b2, sizeof b2) > 0) {
                int on = atoi(b2) ? 1 : 0;
                if (w->last_on[i] != on + 1) {
                    w->last_on[i] = (signed char)(on + 1);
                    w->master(&w->fx, audioMasterAutomate, i, 0, 0, (float)on);
                    w->need_update_display = 1;
                }
            } else
                w->last_on[i] = -1;
        }
        if (poll_text && eng_get(w, PARAMS[i].key, b2, sizeof b2) > 0) {
            unsigned h = 2166136261u;   /* FNV-1a */
            for (const char *s = b2; *s; s++) h = (h ^ (unsigned char)*s) * 16777619u;
            if (h != w->last_text[i]) {
                w->last_text[i] = h;
                w->need_update_display = 1;
            }
        }
    }
    if (HAS_DISPLAY_REV && poll_text) {
        char rev[16];
        if (eng_get(w, "display_rev", rev, sizeof rev) > 0 && strcmp(rev, w->last_rev)) {
            snprintf(w->last_rev, sizeof w->last_rev, "%s", rev);
            w->need_update_display = 1;
            /* report what the engine changed by itself, so the host moves controls and re-evaluates
             * IndexedEnabling (when= panels), not only text */
            for (int i = 0; i < NPARAMS; i++) {
                if (PARAMS[i].momentary || popup_is(i) || PARAMS[i].string_display) continue;
                float v = get_norm(w, i);
                if (fabsf(v - w->last_norm[i]) > 1e-4f) { w->last_norm[i] = v; w->master(&w->fx, audioMasterAutomate, i, 0, 0, v); }
            }
        }
    }
    if ((w->cc_report -= n) <= 0) {
        w->cc_report = 1024;
        for (int i = 0; i < NPARAMS; i++)
            if (w->cc_changed[i]) { w->cc_changed[i] = 0; w->master(&w->fx, audioMasterAutomate, i, 0, 0, get_norm(w, i)); }
    }
    if (w->need_update_display) {
        w->need_update_display = 0;
        w->master(&w->fx, audioMasterUpdateDisplay, 0, 0, 0, 0.0f);
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
            eng_process(w, w->inb, w->block, DSP_BLOCK);
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
        if (++w->inpos == DSP_BLOCK) { eng_process(w, w->inb, w->block, DSP_BLOCK); w->pos = 0; w->inpos = 0; }
        i++;
    }
}
static void processReplacing(AEffect *e, float **in, float **out, int32_t n) { run_block(e, in, out, n, 0); }
static void process(AEffect *e, float **in, float **out, int32_t n) { run_block(e, in, out, n, 1); }
#else
static void run_block(AEffect *e, float **out, int32_t n, int accumulate) {
    wrap_t *w = e->object;
    housekeeping(e, n);
#if SAMPLE_ACCURATE
    render_events(w, out, n, accumulate);
#else
    render_frames(w, out, n, accumulate);
#endif
}

static void processReplacing(AEffect *e, float **in, float **out, int32_t n) { (void)in; run_block(e, out, n, 0); }
static void process(AEffect *e, float **in, float **out, int32_t n) { (void)in; run_block(e, out, n, 1); }
#endif

/* MIDI control from a sequencer or controller on the track's MIDI input (gen_vst.py cc_lines()): CC 20-35 move the
 * first page's Q-Links, NRPN n sets parameter n. Set as a touch would (an option list rounds to the nearest option);
 * the host hears about it from housekeeping(), at most every 1024 frames per control, so the screen follows without a
 * flood. Returns 1 when the message was used here (it then doesn't go to the engine). */
static void cc_set(wrap_t *w, int i, float n) {
    if (i < 0 || i >= NPARAMS || popup_is(i)) return;
    const param_t *p = &PARAMS[i];
    if (p->nopts > 1) n = roundf(clamp01(n) * (p->nopts - 1)) / (p->nopts - 1);
    else if (p->int_display && p->max > p->min) n = roundf(clamp01(n) * (p->max - p->min)) / (p->max - p->min);
    setParameter(&w->fx, i, n);
    w->cc_changed[i] = 1;
}

static int midi_control(wrap_t *w, const uint8_t *m) {
    if ((m[0] & 0xF0) != 0xB0) return 0;
    int cc = m[1] & 127, v = m[2] & 127;
#ifdef HAS_CC_MAP
    if (cc >= 20 && cc <= 35 && PLUG_CC[cc - 20] >= 0) { cc_set(w, PLUG_CC[cc - 20], v / 127.0f); return 1; }
#endif
#ifdef HAS_NRPN
    if (cc == 99) { w->nrpn = (v << 7) | (w->nrpn >= 0 ? w->nrpn & 127 : 0); return 1; }
    if (cc == 98) { w->nrpn = (w->nrpn >= 0 ? w->nrpn & ~127 : 0) | v; return 1; }
    if (cc == 101 || cc == 100) { w->nrpn = -1; return 0; }   /* an RPN (bend range ...): the engine's */
    if (w->nrpn >= 0 && w->nrpn < NPARAMS && cc == 6) { w->nrpn_msb = v; cc_set(w, w->nrpn, v / 127.0f); return 1; }
    if (w->nrpn >= 0 && w->nrpn < NPARAMS && cc == 38) { cc_set(w, w->nrpn, (w->nrpn_msb * 128 + v) / 16383.0f); return 1; }
#endif
    (void)w; (void)cc; (void)v;
    return 0;
}

static void copy_str(void *dst, const char *src, size_t max) {
    strncpy(dst, src, max - 1);
    ((char *)dst)[max - 1] = 0;
}

/* ---- VST programs: MPC's PRESET menu lists them by name and loads one with effSetProgram (docs/NOTES.md) ----
 * NPRESETS: the port's presets.json, compiled into params.h by gen_vst.py; picking one sets each listed parameter in
 * file order, as a touch would, and has the host redraw them. PROG_PARAM: the engine's own preset parameter; a
 * program is one of its options (or whole numbers), so the current one is whatever the engine reports. */
#if defined(NPRESETS)
#define NUM_PROGRAMS NPRESETS
#elif defined(PROG_PARAM)
#define NUM_PROGRAMS NPROGRAMS
#else
#define NUM_PROGRAMS 0
#endif

static int get_program(wrap_t *w) {
#if defined(PROG_PARAM)
    const param_t *pp = &PARAMS[PROG_PARAM];
    float span = pp->nopts > 1 ? pp->nopts - 1 : pp->max - pp->min;
    return (int)lroundf(get_norm(w, PROG_PARAM) * span);
#else
    return w->program;
#endif
}

static void set_program(wrap_t *w, int idx) {
    if (idx < 0 || idx >= NUM_PROGRAMS || idx == get_program(w)) return;   /* a host re-selecting the current one
                                                                              * (JUCE does at load) keeps any edits */
#if defined(NPRESETS)
    for (int i = 0; i < PRESETS[idx].n; i++) {
        eng_set(w, PARAMS[PRESETS[idx].values[i].param].key, PRESETS[idx].values[i].value);
        w->changed[PRESETS[idx].values[i].param] = 1;   /* reported to the host from housekeeping() */
    }
    w->program = idx;
#elif defined(PROG_PARAM)
    char buf[32];
    const param_t *pp = &PARAMS[PROG_PARAM];
    snprintf(buf, sizeof buf, "%d", pp->nopts > 1 ? idx : (int)lroundf(pp->min) + idx);
    eng_set(w, pp->key, buf);
    for (int i = 0; i < NPARAMS; i++) w->changed[i] = !popup_is(i);   /* a preset may change anything */
#endif
    w->need_update_display = 1;
}

static void program_name(wrap_t *w, int idx, char *out) {
    out[0] = 0;
    if (idx < 0 || idx >= NUM_PROGRAMS) return;
#if defined(NPRESETS)
    (void)w;
    copy_str(out, PRESETS[idx].name, 24);
#elif defined(PROG_PARAM)
    char k2[96], buf[64];
    const param_t *pp = &PARAMS[PROG_PARAM];
    if (pp->nopts > 1) { copy_str(out, pp->opts[idx], 24); return; }
    snprintf(k2, sizeof k2, "%s:%d", pp->key, (int)lroundf(pp->min) + idx);   /* the engine names it without loading it */
    if (eng_get(w, k2, buf, sizeof buf) > 0) copy_str(out, buf, 24);
    else snprintf(out, 24, "%s %d", pp->name, (int)lroundf(pp->min) + idx);
#else
    (void)w;
#endif
}

static intptr_t dispatcher(AEffect *e, int32_t op, int32_t idx, intptr_t v, void *p, float o) {
    wrap_t *w = e->object;
    (void)o;
    switch (op) {
    case effOpen: return 1;
    case effClose:
        g_api->destroy(w->dsp);
        pthread_mutex_destroy(&w->lock);
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
            if (PARAMS[idx].dynamic_name && eng_get(w, k2, buf, sizeof buf) > 0) copy_str(p, buf, 32);
            else copy_str(p, PARAMS[idx].name, 32);
        }
        return 1;
    case effGetParamLabel:
        if (idx >= 0 && idx < NPARAMS) copy_str(p, PARAMS[idx].unit, 8);
        return 1;
    case effGetParamDisplay: {
        char buf[PARAM_TEXT_MAX > 64 ? PARAM_TEXT_MAX : 64];
        if (idx < 0 || idx >= NPARAMS) return 0;
        const param_t *pp = &PARAMS[idx];
        char k2[96];
        snprintf(k2, sizeof k2, "%s_display", pp->key);
        if (pp->dynamic_display && eng_get(w, k2, buf, sizeof buf) > 0) {
            copy_str(p, buf, PARAM_TEXT_MAX);   /* text the DSP composes (e.g. a destination's own name) */
        } else if (pp->nopts) {
            int k = (int)lroundf(get_norm(w, idx) * (pp->nopts - 1));
            copy_str(p, pp->opts[k], PARAM_TEXT_MAX);
        } else if (eng_get(w, pp->key, buf, sizeof buf) > 0) {
            if (pp->string_display) copy_str(p, buf, PARAM_TEXT_MAX);   /* real text (a name, a status), not a number */
            else snprintf(p, 24, "%.*f", (pp->int_display || fabs(pp->max - pp->min) > 20) ? 0 : 1, atof(buf));
        }
        return 1;
    }
    case effSetSampleRate: case effSetBlockSize: case effMainsChanged: return 1;
    case effProcessEvents: {
        VstEvents *ev = p;
#if SAMPLE_ACCURATE
        drain_midi(w);   /* left over if the host never processed the last block: late beats lost */
#endif
        for (int i = 0; i < ev->numEvents; i++)
            if (ev->events[i]->type == 1) {
                VstMidiEvent *m = (VstMidiEvent *)ev->events[i];
                if (midi_control(w, (const uint8_t *)m->midiData)) continue;
#if SAMPLE_ACCURATE
                queue_midi(w, (const uint8_t *)m->midiData, m->deltaFrames);
#else
                eng_midi(w, (const uint8_t *)m->midiData, 3);
#endif
            }
        return 1;
    }
    case effSetProgram: set_program(w, (int)v); return 1;
    case effGetProgram: return NUM_PROGRAMS ? get_program(w) : 0;
    case effGetProgramName: program_name(w, NUM_PROGRAMS ? get_program(w) : -1, p); return 1;
    case effGetProgramNameIndexed: program_name(w, idx, p); return idx >= 0 && idx < NUM_PROGRAMS;
    case effCanDo:
        return (!strcmp(p, "receiveVstEvents") || !strcmp(p, "receiveVstMidiEvent") ||
                !strcmp(p, "receiveVstTimeInfo")) ? 1 : -1;
    case effGetChunk: {
        int len = eng_get(w, "state", w->chunk, sizeof w->chunk);
        if (len <= 0) return 0;
        *(void **)p = w->chunk;
        return (intptr_t)strlen(w->chunk) + 1;
    }
    case effSetChunk: {
        if (v <= 0 || (size_t)v > sizeof w->chunk) return 0;
        memcpy(w->chunk, p, v);
        w->chunk[v - 1] = 0;
        eng_set(w, "state", w->chunk);
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
    pthread_mutexattr_t ma;
    pthread_mutexattr_init(&ma);
    pthread_mutexattr_settype(&ma, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutexattr_setprotocol(&ma, PTHREAD_PRIO_INHERIT);
    pthread_mutex_init(&w->lock, &ma);
    pthread_mutexattr_destroy(&ma);
#ifdef MODULE_SUBDIR
    char data_dir[600], here[512];
    const char *module_dir = MODULE_DIR;   /* an absolute MODULE_DIR is still the fallback */
    if (mpc_plugin_dir(here, sizeof here) && snprintf(data_dir, sizeof data_dir, "%s/%s", here, MODULE_SUBDIR) < (int)sizeof data_dir)
        module_dir = data_dir;
    w->dsp = g_api->create(module_dir);
#else
    w->dsp = g_api->create(MODULE_DIR);
#endif
    if (!w->dsp) { pthread_mutex_destroy(&w->lock); free(w); return NULL; }
    w->master = master;
    w->pos = DSP_BLOCK;
    for (int i = 0; i < NPARAMS; i++) w->last_pos[i] = w->last_norm[i] = -1;
    w->nrpn = -1;
    AEffect *e = &w->fx;
    e->magic = 0x56737450; /* 'VstP' */
    e->dispatcher = dispatcher;
    e->process = process;
    e->setParameter = setParameter;
    e->getParameter = getParameter;
    e->processReplacing = processReplacing;
    e->numParams = NPARAMS;
    e->numPrograms = NUM_PROGRAMS;
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
