/* =============================================================================
 * vst3_wrap.c — expose an engine (wrapper/engine.h) as a VST3 plugin for desktop DAWs (Linux x86_64), from the same
 * generated params.h as vst2_wrap.c. For local use beside the MPC build: MPC OS itself loads only VST2 (docs/NOTES.md).
 * tools/build_vst3.sh builds the bundle.
 *
 * One object is the component, the audio processor and the edit controller (a "single component" plugin: getControllerClassId
 * says there is no separate controller, so the host asks the component for IEditController), so the controller reads the
 * engine directly and no messages pass between halves.
 *
 * Host contract differences from MPC, handled here so engines stay unchanged:
 * - Any sample rate: the engine still runs at 44100 Hz; wrapper/resample.h converts on the way in and out.
 * - Any block size, float buffers: audio goes through the engine in 128-frame blocks via FIFOs. An effect reports a fixed
 *   latency (getLatencySamples) the host compensates; an instrument renders ahead on demand and adds none.
 * - Host parameter changes arrive in process() (inputParameterChanges) and are applied there, on the audio thread, at the
 *   block start; setParamNormalized() (the host's own copy for the controller) does not touch the engine, or every change
 *   would land twice. Values the engine changes by itself go back to the host through outputParameterChanges.
 * - MIDI: VST3 delivers notes as events but CCs, pitch bend and channel pressure only as parameters (IMidiMapping). Hidden
 *   parameters, one per controller per channel, turn them back into MIDI bytes for the engine's midi().
 * - Presets (vst.json "presets") are a program-change parameter. PROG_PARAM ports keep their own preset parameter.
 * - A bypass parameter: an effect then outputs its input, delayed by the same latency; an instrument goes silent. The
 *   engine keeps running either way, so switching back is seamless.
 * - State: the engine's "state" text when it has one, else every parameter as key=value lines.
 * - Editor: with -DVST3_EDITOR, vst3_editor.c draws the port's MPC skin in the plugin window; without it, hosts show their
 *   generic parameter view.
 *
 * The VST3 ABI is hand-written (wrapper/vst3_abi.h); no Steinberg SDK in this repository.
 * ========================================================================== */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE   /* must precede every include */
#endif
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdio.h>
#include <math.h>
#include <ctype.h>
#include <pthread.h>
#include "params.h"
#ifndef HAS_LFO_BPM
#define HAS_LFO_BPM 0
#endif
#ifndef HAS_DISPLAY_REV
#define HAS_DISPLAY_REV 0
#endif
#ifndef SAMPLE_ACCURATE
#define SAMPLE_ACCURATE 0
#endif
#ifndef HAS_TRANSPORT
#define HAS_TRANSPORT 0
#endif
#ifndef HAS_SONG_POS
#define HAS_SONG_POS 0
#endif
#ifndef MODULE_DIR
#define MODULE_DIR NULL
#endif
#ifdef MODULE_SUBDIR
#include "plugin_dir.h"
#endif

#include "engine.h"
#include "popup.h"
#include "resample.h"

#define DSP_BLOCK 128
#define ENGINE_RATE 44100.0
#define MAX_EVENTS 512       /* MIDI messages per host block (notes and controller parameters); more are dropped */
#define STATE_MAX 65536
#define PROG_ID 0x7FFF0000u  /* NPRESETS: the program-change parameter */
#define BYPASS_ID 0x7FFF0001u
#define MIDI_ID 0x40000000u  /* + channel * 130 + controller (0-127 CC, 128 channel pressure, 129 pitch bend) */
#define MIDI_CTRLS 130
#define MIDI_PARAMS (16 * MIDI_CTRLS)
#define CHUNK 4096           /* host frames per pass through the FIFOs: a bigger host block is processed in pieces */

#include "vst3_abi.h"

/* ---- per-instance state ------------------------------------------------- */
typedef struct { int32_t frame; uint8_t msg[3]; } midi_ev_t;
#define UIQ 256

typedef struct {
    const ComponentVtbl *comp;        /* each interface's pointer is the address of its vtable member */
    const ProcessorVtbl *proc;
    const ControllerVtbl *ctrl;
    const MidiMappingVtbl *midimap;
    const CtxReqVtbl *ctxreq;
    uint32_t refs;
    void *dsp;
    pthread_mutex_t lock;             /* one engine call at a time (vst2_wrap.c eng_set) */
    IComponentHandler *handler;
    double rate;                      /* host sample rate */
    int active;
    uint32_t latency;                 /* effect: host frames of delay through the FIFOs and converters */
    rs_t *rs_in, *rs_out;             /* host -> engine (effect input), engine -> host */
    int16_t inb[DSP_BLOCK * 2], outb[DSP_BLOCK * 2];
    int inpos;                        /* effect: engine-rate input frames collected in inb */
    float fl[DSP_BLOCK], fr[DSP_BLOCK];
    float *ofifo[2];                  /* effect: host-rate output waiting to go out (latency-padded) */
    int olen, ocap;
    int prog;                         /* NPRESETS: the program last picked (-1: none yet, so picking 0 loads it) */
    int bypass;                       /* the host's bypass: an effect passes its input through, delayed like its output */
    float *dry[2];                    /* effect: the input, delayed by the latency (a ring of `latency` frames) */
    int drypos;
    double bpm, ppq;
    int playing;
    double hostval[NPARAMS > 0 ? NPARAMS : 1];   /* the host's copy (setParamNormalized), for a param the engine can't read back */
    double reported[NPARAMS > 0 ? NPARAMS : 1];  /* the value last sent to the host through outputParameterChanges */
    int hold[NPARAMS > 0 ? NPARAMS : 1];         /* momentary params: engine frames until the host hears they're back at 0 */
    char changed[NPARAMS > 0 ? NPARAMS : 1];     /* to report through outputParameterChanges */
    char last_rev[16];
    int rev_poll;
    midi_ev_t ev[MAX_EVENTS];
    int nev;
    int nrpn;                         /* HAS_NRPN: the parameter CC 99/98 selected (-1: none) */
    char state[STATE_MAX];
#ifdef VST3_EDITOR
    double open[NPARAMS > 0 ? NPARAMS : 1];      /* the editor's popup flags (screen-only, never the host's) */
    struct { int p; double v; } uiq[UIQ];        /* editor edits the host can't make, for process() to apply */
    unsigned uiq_head, uiq_tail;
#endif
} v3_t;

static const mpc_engine_t *g_api;

#define FROM(ptr, member) ((v3_t *)((char *)(ptr) - offsetof(v3_t, member)))

static void eng_set(v3_t *w, const char *k, const char *v) {
    pthread_mutex_lock(&w->lock); g_api->set_param(w->dsp, k, v); pthread_mutex_unlock(&w->lock);
}
static int eng_get(v3_t *w, const char *k, char *buf, int n) {
    pthread_mutex_lock(&w->lock); int r = g_api->get_param(w->dsp, k, buf, n); pthread_mutex_unlock(&w->lock); return r;
}
static void eng_midi(v3_t *w, const uint8_t *m, int n) {
    pthread_mutex_lock(&w->lock); g_api->midi(w->dsp, m, n); pthread_mutex_unlock(&w->lock);
}

static double clamp01(double v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
static int iid_eq(const void *a, const void *b) { return !memcmp(a, b, 16); }

static void to_utf16(char16 *dst, const char *src, int max) {
    int i = 0;
    for (; src && src[i] && i < max - 1; i++) dst[i] = (unsigned char)src[i];
    dst[i] = 0;
}
static void from_utf16(char *dst, const char16 *src, int max) {
    int i = 0;
    for (; src && src[i] && i < max - 1; i++) dst[i] = src[i] < 128 ? (char)src[i] : '?';
    dst[i] = 0;
}

/* ---- parameters ---------------------------------------------------------- */
/* The host sees PARAMS by index (the same numbering as the VST2 build), minus the popup flags (screen-only), then the program
 * parameter, then the hidden MIDI controller parameters. */
static int g_nvis;                           /* visible PARAMS */
static int g_vis[NPARAMS > 0 ? NPARAMS : 1]; /* host list position -> PARAMS index */

static int has_programs(void) {
#ifdef NPRESETS
    return NPRESETS > 0;
#else
    return 0;
#endif
}
static int param_count(void) { return g_nvis + 1 + has_programs() + MIDI_PARAMS; }

static int is_param(uint32_t id) { return id < (uint32_t)NPARAMS && !popup_is((int)id); }

static int step_count(const param_t *p) {
    if (p->momentary || p->step_target >= 0) return 1;
    if (p->nopts > 1) return p->nopts - 1;
    if (p->int_display && p->max > p->min) return (int)lroundf(p->max - p->min);
    return 0;
}

static void norm_to_str(const param_t *p, double n, char *buf, int len) {
    if (p->nopts) snprintf(buf, len, "%ld", lround(clamp01(n) * (p->nopts - 1)));
    else if (p->int_display) snprintf(buf, len, "%ld", lround(p->min + (p->max - p->min) * clamp01(n)));
    else snprintf(buf, len, "%g", p->min + (p->max - p->min) * clamp01(n));
}

/* A value as the engine reports it (an option's index, or a number; as vst2_wrap.c reads it), or with text = 1 as a person
 * types it into the host (an option's name first: "30 s" is an option, not 30, and an option named "0" is not index 0). */
static double str_to_norm(const param_t *p, const char *s, int text) {
    if (p->nopts) {
        int idx = -1;
        for (int i = 0; text && i < p->nopts && idx < 0; i++)
            if (!strcasecmp(s, p->opts[i])) idx = i;
        if (idx < 0 && isdigit((unsigned char)s[0])) idx = atoi(s);
        for (int i = 0; !text && idx < 0 && i < p->nopts; i++)
            if (!strcasecmp(s, p->opts[i])) idx = i;
        if (idx < 0 || idx >= p->nopts) idx = 0;
        return p->nopts > 1 ? (double)idx / (p->nopts - 1) : 0;
    }
    return p->max > p->min ? clamp01((atof(s) - p->min) / (p->max - p->min)) : 0;
}

static double get_norm(v3_t *w, int i) {
    char buf[64];
    const param_t *p = &PARAMS[i];
    if (p->momentary || p->step_target >= 0) return w->hostval[i];
    if (p->string_display) {
        char k2[96];
        snprintf(k2, sizeof k2, "%s_on", p->key);
        if (eng_get(w, k2, buf, sizeof buf) > 0) return atoi(buf) ? 1.0 : 0.0;
        return w->hostval[i];
    }
    if (eng_get(w, p->key, buf, sizeof buf) <= 0) return p->def;
    return str_to_norm(p, buf, 0);
}

/* ---- programs ------------------------------------------------------------- */
#ifdef NPRESETS
static void set_program(v3_t *w, int idx) {
    if (idx < 0 || idx >= NPRESETS) return;
    for (int i = 0; i < PRESETS[idx].n; i++) {
        eng_set(w, PARAMS[PRESETS[idx].values[i].param].key, PRESETS[idx].values[i].value);
        w->changed[PRESETS[idx].values[i].param] = 1;
    }
    w->prog = idx;
}
#endif

/* ---- applying host values ------------------------------------------------ */
static void apply_param(v3_t *w, int i, double n) {
    const param_t *p = &PARAMS[i];
    char buf[64];
    double was = w->hostval[i];
    w->hostval[i] = n;
    if (p->step_target >= 0) {
        /* a momentary nudge of another param (gen_vst.py step_of): steps the target on the press */
        if (n > 0.5 && was <= 0.5) {
            const param_t *tp = &PARAMS[p->step_target];
            if (tp->nopts > 1 && eng_get(w, tp->key, buf, sizeof buf) > 0) {
                int idx = (int)lround(str_to_norm(tp, buf, 0) * (tp->nopts - 1)) + (int)lroundf(p->step_delta);
                idx = ((idx % tp->nopts) + tp->nopts) % tp->nopts;
                snprintf(buf, sizeof buf, "%d", idx);
                eng_set(w, tp->key, buf);
            } else if (eng_get(w, tp->key, buf, sizeof buf) > 0) {
                double cur = atof(buf) + p->step_delta;
                cur = cur < tp->min ? tp->min : cur > tp->max ? tp->max : cur;
                snprintf(buf, sizeof buf, "%g", cur);
                eng_set(w, tp->key, buf);
            }
            w->changed[p->step_target] = 1;
            w->hold[i] = 1;
        }
        return;
    }
    if (p->momentary) {
        if (n > 0.5 && was > 0.5) return;   /* still held */
        norm_to_str(p, n > 0.5 ? 1 : 0, buf, sizeof buf);
        eng_set(w, p->key, buf);
        if (n > 0.5) w->hold[i] = p->hold_ms > 0 ? (int)(p->hold_ms * 44.1f) : 1;
        return;
    }
    norm_to_str(p, n, buf, sizeof buf);
    eng_set(w, p->key, buf);
}

/* A controller parameter (hidden, IMidiMapping) moved: the MIDI bytes it stands for. A repeated value is sent too: it is a
 * message of its own (NRPN data entry sends CC 6 = 64 for two parameters in a row). */
static int controller_msg(uint32_t id, double v, uint8_t *msg) {
    int k = (int)(id - MIDI_ID), ch = k / MIDI_CTRLS, c = k % MIDI_CTRLS;
    if (c == 129) {
        int b = (int)lround(clamp01(v) * 16383);
        msg[0] = 0xE0 | ch; msg[1] = b & 127; msg[2] = b >> 7;
        return 3;
    }
    int val = (int)lround(clamp01(v) * 127);
    if (c == 128) { msg[0] = 0xD0 | ch; msg[1] = (uint8_t)val; msg[2] = 0; return 2; }
    msg[0] = 0xB0 | ch; msg[1] = (uint8_t)c; msg[2] = (uint8_t)val;
    return 3;
}

/* vst2_wrap.c's CC 20-35 and NRPN control, for the same MIDI here: 1 when the message was a parameter set. */
static int midi_control(v3_t *w, const uint8_t *m) {
    if ((m[0] & 0xF0) != 0xB0) return 0;
    int cc = m[1] & 127, v = m[2] & 127;
#ifdef HAS_CC_MAP
    if (cc >= 20 && cc <= 35 && PLUG_CC[cc - 20] >= 0) {
        int i = PLUG_CC[cc - 20];
        apply_param(w, i, v / 127.0);
        w->changed[i] = 1;
        return 1;
    }
#endif
#ifdef HAS_NRPN
    int *nrpn = &w->nrpn;
    if (cc == 99) { *nrpn = (v << 7) | (*nrpn >= 0 ? *nrpn & 127 : 0); return 1; }
    if (cc == 98) { *nrpn = (*nrpn >= 0 ? *nrpn & ~127 : 0) | v; return 1; }
    if (cc == 101 || cc == 100) { *nrpn = -1; return 0; }
    if (*nrpn >= 0 && *nrpn < NPARAMS && cc == 6 && !popup_is(*nrpn)) { apply_param(w, *nrpn, v / 127.0); w->changed[*nrpn] = 1; return 1; }
#endif
    (void)w; (void)cc; (void)v;
    return 0;
}

static void queue_midi(v3_t *w, int32_t frame, const uint8_t *msg) {
    if (w->nev == MAX_EVENTS) return;
    int k = w->nev++;
    while (k > 0 && w->ev[k - 1].frame > frame) { w->ev[k] = w->ev[k - 1]; k--; }   /* stable: after equal frames */
    w->ev[k].frame = frame;
    memcpy(w->ev[k].msg, msg, 3);
}

static void send_midi(v3_t *w, const uint8_t *msg) {
    if (midi_control(w, msg)) return;
    int len = (msg[0] & 0xF0) == 0xD0 || (msg[0] & 0xF0) == 0xC0 ? 2 : 3;
    eng_midi(w, msg, len);
}

/* ---- transport ------------------------------------------------------------ */
static void update_context(v3_t *w, const ProcessContext *c, int frames) {
    if (!c) return;
    double eng_frames = frames * ENGINE_RATE / w->rate;
    int tempo_ok = (c->state & kTempoValid) && c->tempo > 0, ppq_ok = (c->state & kProjectTimeMusicValid) != 0;
    int playing = (c->state & kPlaying) != 0;
    if (HAS_TRANSPORT) {
        int restart = playing && w->playing && ppq_ok && c->projectTimeMusic < w->ppq - 0.01;
        if (playing != w->playing || restart) eng_set(w, "transport", playing ? "1" : "0");
    }
    if (HAS_SONG_POS && g_api->song_pos) {
        pthread_mutex_lock(&w->lock);
        g_api->song_pos(w->dsp, ppq_ok && tempo_ok ? c->projectTimeMusic : -1.0, tempo_ok ? c->tempo : 0.0, playing,
                        (int)lround(eng_frames));
        pthread_mutex_unlock(&w->lock);
    }
    w->playing = playing;
    if (ppq_ok) w->ppq = c->projectTimeMusic;
    if (HAS_LFO_BPM && tempo_ok && fabs(c->tempo - w->bpm) > 0.01) {
        char buf[32];
        w->bpm = c->tempo;
        snprintf(buf, sizeof buf, "%.2f", w->bpm);
        eng_set(w, "lfo_bpm", buf);
    }
}

/* ---- audio ---------------------------------------------------------------- */
#ifdef PLUG_EFFECT
static int16_t f2s(float f) { f *= 32768.0f; return f >= 32767.0f ? 32767 : f <= -32768.0f ? -32768 : (int16_t)lrintf(f); }
#endif

static void free_audio(v3_t *w) {
    if (w->rs_in) { rs_free(w->rs_in); free(w->rs_in); w->rs_in = NULL; }
    if (w->rs_out) { rs_free(w->rs_out); free(w->rs_out); w->rs_out = NULL; }
    free(w->ofifo[0]); free(w->ofifo[1]);
    free(w->dry[0]); free(w->dry[1]);
    w->ofifo[0] = w->ofifo[1] = w->dry[0] = w->dry[1] = NULL;
}

/* Set up converters and FIFOs for the host rate (setupProcessing / setActive: never on the audio thread). The FIFOs hold a
 * CHUNK of host frames plus the latency and a margin over one engine block at the host rate (1115 frames at 384 kHz). */
static int init_audio_bufs(v3_t *w) {
    w->rs_out = malloc(sizeof *w->rs_out);
    if (!w->rs_out || !rs_init(w->rs_out, ENGINE_RATE, w->rate)) return 0;
    w->inpos = 0;
    w->latency = 0;
#ifdef PLUG_EFFECT
    w->rs_in = malloc(sizeof *w->rs_in);
    if (!w->rs_in || !rs_init(w->rs_in, w->rate, ENGINE_RATE)) return 0;
    /* Output frame m needs engine output up to time m * 44100 / rate + rs_out.half, which needs the input up to there plus a
     * whole engine block (collected before it is processed) plus rs_in.half host frames (converted before it is collected).
     * Padding the output by that much keeps the FIFO from running dry, and is the delay the host compensates. */
    double r = w->rate / ENGINE_RATE;
    w->latency = (uint32_t)ceil((DSP_BLOCK + w->rs_out->half) * r + w->rs_in->half + 2);
    if (!w->rs_in->half && !w->rs_out->half) w->latency = DSP_BLOCK;   /* equal rates: exactly one engine block */
    w->ocap = (int)w->latency + 8192 + DSP_BLOCK * 8;
    w->dry[0] = calloc(w->latency, sizeof(float));
    w->dry[1] = calloc(w->latency, sizeof(float));
    w->drypos = 0;
    if (!w->dry[0] || !w->dry[1]) return 0;
#else
    w->ocap = 8192 + DSP_BLOCK * 8;
#endif
    w->ofifo[0] = calloc(w->ocap, sizeof(float));
    w->ofifo[1] = calloc(w->ocap, sizeof(float));
    if (!w->ofifo[0] || !w->ofifo[1]) return 0;
    w->olen = (int)w->latency;   /* silence first */
    return 1;
}
static int init_audio(v3_t *w) {   /* all or nothing: a failure leaves no buffer behind (process() checks rs_out) */
    free_audio(w);
    if (init_audio_bufs(w)) return 1;
    free_audio(w);
    return 0;
}

/* engine output (int16 block) -> output converter -> output FIFO */
static void push_out(v3_t *w, int frames) {
    float l[DSP_BLOCK], r[DSP_BLOCK];
    for (int j = 0; j < frames; j++) { l[j] = w->outb[2 * j] * (1.0f / 32768.0f); r[j] = w->outb[2 * j + 1] * (1.0f / 32768.0f); }
    rs_push(w->rs_out, l, r, frames);
    int room = w->ocap - w->olen;
    if (room > 0) w->olen += rs_pull(w->rs_out, w->ofifo[0] + w->olen, w->ofifo[1] + w->olen, room);
}

static void pop_out(v3_t *w, float *l, float *r, int n) {
    int m = n < w->olen ? n : w->olen;
    if (l) memcpy(l, w->ofifo[0], sizeof(float) * m);
    if (r) memcpy(r, w->ofifo[1], sizeof(float) * m);
    for (int j = m; j < n; j++) { if (l) l[j] = 0; if (r) r[j] = 0; }   /* never with the padding right */
    memmove(w->ofifo[0], w->ofifo[0] + m, sizeof(float) * (w->olen - m));
    memmove(w->ofifo[1], w->ofifo[1] + m, sizeof(float) * (w->olen - m));
    w->olen -= m;
}

/* A pressed momentary param goes back to 0 after its hold time: the engine hears the release (on MPC the host's echo of the
 * wrapper's report does that) and the host hears it through outputParameterChanges. */
static void count_holds(v3_t *w, int eng_frames) {
    for (int i = 0; i < NPARAMS; i++)
        if (w->hold[i] > 0 && (w->hold[i] -= eng_frames) <= 0) {
            w->hold[i] = 0;
            w->hostval[i] = 0;
            w->changed[i] = 1;
            if (PARAMS[i].step_target < 0) {
                char buf[16];
                norm_to_str(&PARAMS[i], 0, buf, sizeof buf);
                eng_set(w, PARAMS[i].key, buf);
            }
        }
}

#ifdef PLUG_EFFECT
/* host-rate input [from, to) of this block -> engine, MIDI due before each piece first */
static void run_effect(v3_t *w, const float *il, const float *ir, int from, int to, int *evk) {
    while (from < to) {
        int n = to - from, room = rs_room(w->rs_in);
        if (n > room) n = room;
        rs_push(w->rs_in, il ? il + from : NULL, ir ? ir + from : NULL, n);
        from += n;
        for (;;) {
            int m = rs_pull(w->rs_in, w->fl + w->inpos, w->fr + w->inpos, DSP_BLOCK - w->inpos);
            for (int j = 0; j < m; j++) { w->inb[2 * (w->inpos + j)] = f2s(w->fl[w->inpos + j]); w->inb[2 * (w->inpos + j) + 1] = f2s(w->fr[w->inpos + j]); }
            w->inpos += m;
            if (w->inpos < DSP_BLOCK) break;
            while (*evk < w->nev && w->ev[*evk].frame < from) send_midi(w, w->ev[(*evk)++].msg);
            pthread_mutex_lock(&w->lock);
            g_api->process(w->dsp, w->inb, w->outb, DSP_BLOCK);
            pthread_mutex_unlock(&w->lock);
            w->inpos = 0;
            count_holds(w, DSP_BLOCK);
            push_out(w, DSP_BLOCK);
        }
    }
}
#else
/* render engine audio until the output FIFO holds `need` host frames; SAMPLE_ACCURATE engines render only what is needed */
static void fill_out(v3_t *w, int need) {
    while (w->olen < need) {
        int eng = rs_need(w->rs_out, need - w->olen);
        if (eng <= 0) eng = 1;
        if (!SAMPLE_ACCURATE || eng > DSP_BLOCK) eng = DSP_BLOCK;
        pthread_mutex_lock(&w->lock);
        g_api->render(w->dsp, w->outb, eng);
        pthread_mutex_unlock(&w->lock);
        count_holds(w, eng);
        push_out(w, eng);
    }
}
#endif

/* ---- reporting engine-side changes ---------------------------------------- */
static void report(v3_t *w, ProcessData *d) {
    if (HAS_DISPLAY_REV && (w->rev_poll -= d->numSamples) <= 0) {
        char rev[16];
        w->rev_poll = (int)(w->rate / 10);
        if (eng_get(w, "display_rev", rev, sizeof rev) > 0 && strcmp(rev, w->last_rev)) {
            snprintf(w->last_rev, sizeof w->last_rev, "%s", rev);
            for (int i = 0; i < NPARAMS; i++)
                if (is_param(i) && !PARAMS[i].momentary && !PARAMS[i].string_display) w->changed[i] = 1;
        }
    }
    if (mpc_engine_changed) {
        char key[64];
        pthread_mutex_lock(&w->lock);
        for (int k = 0; k < NPARAMS && mpc_engine_changed(w->dsp, key, sizeof key) > 0; k++)
            for (int i = 0; i < NPARAMS; i++)
                if (!strcmp(PARAMS[i].key, key)) { w->changed[i] = 1; break; }
        pthread_mutex_unlock(&w->lock);
    }
    IParameterChanges *out = d->outputParameterChanges;
    if (!out) return;   /* no list this call: the changes wait for one */
    for (int i = 0; i < NPARAMS; i++) {
        if (!w->changed[i]) continue;
        w->changed[i] = 0;
        if (!is_param(i)) continue;
        double v = get_norm(w, i);
        if (fabs(v - w->reported[i]) < 1e-9) continue;
        w->reported[i] = v;
        w->hostval[i] = v;
        uint32_t id = (uint32_t)i;
        int32_t qi = 0, pi = 0;
        IParamValueQueue *q = out->v->addParameterData(out, &id, &qi);
        if (q) q->v->addPoint(q, 0, v, &pi);
    }
}

/* ---- state ------------------------------------------------------------------ */
static int stream_write(IBStream *s, const void *buf, int n) {
    int32_t done = 0;
    return s->v->write(s, (void *)buf, n, &done) == kResultOk && done == n;
}

static int is_live(int i) {   /* vst.json "live": a value the engine changes by itself (a status, a meter), not a setting */
#ifdef PLUG_LIVE_COUNT
    for (int k = 0; k < PLUG_LIVE_COUNT; k++) if (PLUG_LIVE[k] == i) return 1;
#endif
    (void)i;
    return 0;
}

static tresult save_state(v3_t *w, IBStream *s) {
    int len = eng_get(w, "state", w->state, sizeof w->state);
    if (len > 0) {
        w->state[sizeof w->state - 1] = 0;
        if (!stream_write(s, "mpc-vst3 state\n", 15) || !stream_write(s, w->state, (int)strlen(w->state))) return kResultFalse;
    } else {
        if (!stream_write(s, "mpc-vst3 params\n", 16)) return kResultFalse;
        for (int i = 0; i < NPARAMS; i++) {
            char line[200], buf[96];
            const param_t *p = &PARAMS[i];
            if (popup_is(i) || p->momentary || p->step_target >= 0 || p->string_display || is_live(i)) continue;
            if (eng_get(w, p->key, buf, sizeof buf) <= 0) continue;
            int n = snprintf(line, sizeof line, "%s=%s\n", p->key, buf);
            if (n > 0 && n < (int)sizeof line && !stream_write(s, line, n)) return kResultFalse;
        }
    }
    /* the wrapper's own settings, after a \x01 the engine's text never holds */
    char line[64];
    int n = snprintf(line, sizeof line, "\n\x01program=%d\nbypass=%d\n", w->prog, w->bypass);
    return stream_write(s, line, n) ? kResultOk : kResultFalse;
}

static tresult load_state(v3_t *w, IBStream *s) {
    int len = 0;
    for (;;) {
        int32_t got = 0;
        if (len >= (int)sizeof w->state - 1) break;
        if (s->v->read(s, w->state + len, (int32_t)(sizeof w->state - 1 - len), &got) != kResultOk || got <= 0) break;
        len += got;
    }
    w->state[len] = 0;
    char *own = NULL;
    for (int i = 0; i + 1 < len; i++)
        if (w->state[i] == '\x01') { own = w->state + i + 1; w->state[i > 0 ? i - 1 : i] = 0; break; }
    if (!strncmp(w->state, "mpc-vst3 state\n", 15)) {
        eng_set(w, "state", w->state + 15);
    } else if (!strncmp(w->state, "mpc-vst3 params\n", 16)) {
        for (char *line = w->state + 16, *next; line && *line; line = next) {
            next = strchr(line, '\n');
            if (next) *next++ = 0;
            char *eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0;
            for (int i = 0; i < NPARAMS; i++)
                if (!strcmp(PARAMS[i].key, line)) { eng_set(w, line, eq + 1); break; }
        }
    } else {
        return kResultFalse;
    }
    for (char *l = own; l && *l; l = strchr(l, '\n') ? strchr(l, '\n') + 1 : NULL) {
        if (!strncmp(l, "program=", 8)) w->prog = atoi(l + 8);
        if (!strncmp(l, "bypass=", 7)) w->bypass = atoi(l + 7) != 0;
    }
    for (int i = 0; i < NPARAMS; i++) { w->changed[i] = 1; w->reported[i] = -1; }
    return kResultOk;
}

/* ---- identity ----------------------------------------------------------------- */
/* Class ID: "MPC3", the port's four-character uid, then 8 bytes of FNV-1a over vendor and name, so two ports that share a uid
 * by mistake still differ. Stable across builds: a saved project finds the plugin again. */
static TUID g_cid;
static void make_cid(void) {
    uint64_t h = 1469598103934665603ull;
    const char *parts[2] = { PLUG_VENDOR, PLUG_NAME };
    for (int k = 0; k < 2; k++)
        for (const char *c = parts[k]; *c; c++) h = (h ^ (unsigned char)*c) * 1099511628211ull;
    memcpy(g_cid, "MPC3", 4);
    for (int i = 0; i < 4; i++) g_cid[4 + i] = (uint8_t)((uint32_t)PLUG_UID >> (24 - 8 * i));
    for (int i = 0; i < 8; i++) g_cid[8 + i] = (uint8_t)(h >> (56 - 8 * i));
}

/* ---- FUnknown, shared by every interface of the instance ------------------------ */
static void destroy(v3_t *w);
static tresult query(v3_t *w, const TUID iid, void **obj) {
    void *p = NULL;
    if (iid_eq(iid, iid_FUnknown) || iid_eq(iid, iid_IPluginBase) || iid_eq(iid, iid_IComponent)) p = &w->comp;
    else if (iid_eq(iid, iid_IAudioProcessor)) p = &w->proc;
    else if (iid_eq(iid, iid_IEditController)) p = &w->ctrl;
    else if (iid_eq(iid, iid_IMidiMapping)) p = &w->midimap;
    else if (iid_eq(iid, iid_IProcessContextRequirements)) p = &w->ctxreq;
    if (!p) { *obj = NULL; return kNoInterface; }
    __atomic_add_fetch(&w->refs, 1, __ATOMIC_ACQ_REL);
    *obj = p;
    return kResultOk;
}
static uint32_t add_ref(v3_t *w) { return __atomic_add_fetch(&w->refs, 1, __ATOMIC_ACQ_REL); }
static uint32_t release(v3_t *w) {
    uint32_t r = __atomic_sub_fetch(&w->refs, 1, __ATOMIC_ACQ_REL);
    if (!r) destroy(w);
    return r;
}
#define UNKNOWN_FUNCS(pre, member) \
    static tresult pre##_query(void *s, const TUID iid, void **o) { return query(FROM(s, member), iid, o); } \
    static uint32_t pre##_addref(void *s) { return add_ref(FROM(s, member)); } \
    static uint32_t pre##_release(void *s) { return release(FROM(s, member)); }
UNKNOWN_FUNCS(comp, comp)
UNKNOWN_FUNCS(proc, proc)
UNKNOWN_FUNCS(ctrl, ctrl)
UNKNOWN_FUNCS(mm, midimap)
UNKNOWN_FUNCS(cr, ctxreq)

static tresult base_initialize(void *s, FUnknown *ctx) { (void)s; (void)ctx; return kResultOk; }
static tresult base_terminate(void *s) { (void)s; return kResultOk; }

/* ---- IComponent ------------------------------------------------------------------ */
static tresult comp_controller_cid(void *s, TUID cid) { (void)s; memset(cid, 0, 16); return kResultFalse; }
static tresult comp_set_io_mode(void *s, int32_t m) { (void)s; (void)m; return kNotImplemented; }
static int32_t comp_bus_count(void *s, int32_t type, int32_t dir) {
    (void)s;
    if (type == kAudio) {
#ifdef PLUG_EFFECT
        return 1;
#else
        return dir == kOutput;
#endif
    }
    return type == kEvent && dir == kInput;
}
static tresult comp_bus_info(void *s, int32_t type, int32_t dir, int32_t index, BusInfo *b) {
    (void)s;
    if (index != 0 || index >= comp_bus_count(s, type, dir)) return kInvalidArgument;
    memset(b, 0, sizeof *b);
    b->mediaType = type;
    b->direction = dir;
    b->busType = kMain;
    b->flags = kDefaultActive;
    b->channelCount = type == kAudio ? 2 : 16;
    to_utf16(b->name, type == kEvent ? "MIDI In" : dir == kInput ? "Input" : "Output", 128);
    return kResultOk;
}
static tresult comp_routing(void *s, RoutingInfo *i, RoutingInfo *o) { (void)s; (void)i; (void)o; return kNotImplemented; }
static tresult comp_activate_bus(void *s, int32_t t, int32_t d, int32_t i, uint8_t st) { (void)s; (void)t; (void)d; (void)i; (void)st; return kResultOk; }
static tresult comp_set_active(void *s, uint8_t state) {
    v3_t *w = FROM(s, comp);
    if (state && !w->active) {
        if (w->rate <= 0) w->rate = ENGINE_RATE;
        if (!init_audio(w)) return kResultFalse;
    }
    w->active = state;
    return kResultOk;
}
static tresult comp_set_state(void *s, IBStream *st) { return st ? load_state(FROM(s, comp), st) : kInvalidArgument; }
static tresult comp_get_state(void *s, IBStream *st) { return st ? save_state(FROM(s, comp), st) : kInvalidArgument; }

static const ComponentVtbl comp_vtbl = {
    comp_query, comp_addref, comp_release, base_initialize, base_terminate,
    comp_controller_cid, comp_set_io_mode, comp_bus_count, comp_bus_info, comp_routing, comp_activate_bus,
    comp_set_active, comp_set_state, comp_get_state,
};

/* ---- IAudioProcessor ---------------------------------------------------------------- */
#define STEREO 3ull
static tresult proc_set_arr(void *s, uint64_t *in, int32_t nin, uint64_t *out, int32_t nout) {
    (void)s;
#ifdef PLUG_EFFECT
    if (nin != 1 || nout != 1) return kResultFalse;
    return in[0] == STEREO && out[0] == STEREO ? kResultOk : kResultFalse;
#else
    (void)in;
    if (nin != 0 || nout != 1) return kResultFalse;
    return out[0] == STEREO ? kResultOk : kResultFalse;
#endif
}
static tresult proc_get_arr(void *s, int32_t dir, int32_t index, uint64_t *arr) {
    if (index != 0 || index >= comp_bus_count(s, kAudio, dir)) return kInvalidArgument;
    *arr = STEREO;
    return kResultOk;
}
static tresult proc_can_size(void *s, int32_t size) { (void)s; return size == 0 ? kResultOk : kResultFalse; }
static uint32_t proc_latency(void *s) { return FROM(s, proc)->latency; }
static tresult proc_setup(void *s, ProcessSetup *setup) {
    v3_t *w = FROM(s, proc);
    if (setup->symbolicSampleSize != 0) return kResultFalse;
    w->rate = setup->sampleRate > 0 ? setup->sampleRate : ENGINE_RATE;
    return init_audio(w) ? kResultOk : kResultFalse;   /* latency known from here on: hosts read it after setupProcessing */
}
static tresult proc_set_processing(void *s, uint8_t st) { (void)s; (void)st; return kResultOk; }

static tresult proc_process(void *s, ProcessData *d) {
    v3_t *w = FROM(s, proc);
    if (!w->rs_out) return kResultFalse;   /* not set up */
    int n = d->numSamples;
    w->nev = 0;
    /* parameters, applied in order at the block start; controller parameters become timed MIDI */
    IParameterChanges *pc = d->inputParameterChanges;
    int npc = pc ? pc->v->getParameterCount(pc) : 0;
    for (int k = 0; k < npc; k++) {
        IParamValueQueue *q = pc->v->getParameterData(pc, k);
        if (!q) continue;
        uint32_t id = q->v->getParameterId(q);
        int np = q->v->getPointCount(q);
        for (int j = 0; j < np; j++) {
            int32_t off = 0;
            double v = 0;
            if (q->v->getPoint(q, j, &off, &v) != kResultOk) continue;
            if (id >= MIDI_ID && id < MIDI_ID + MIDI_PARAMS) {
                uint8_t msg[3] = {0, 0, 0};
                if (controller_msg(id, v, msg)) queue_midi(w, off, msg);
            } else if (id == BYPASS_ID) {
                w->bypass = v > 0.5;
            } else if (id == PROG_ID && has_programs()) {
#ifdef NPRESETS
                int idx = (int)lround(clamp01(v) * (NPRESETS > 1 ? NPRESETS - 1 : 0));
                if (idx != w->prog) set_program(w, idx);   /* a re-pick of the current one keeps any edits (vst2_wrap.c) */
#endif
            } else if (is_param(id)) {
                apply_param(w, (int)id, clamp01(v));
                w->reported[id] = clamp01(v);
            }
        }
    }
#ifdef VST3_EDITOR
    for (unsigned t = w->uiq_tail; t != __atomic_load_n(&w->uiq_head, __ATOMIC_ACQUIRE); t++) {
        int p = w->uiq[t % UIQ].p;
        apply_param(w, p, w->uiq[t % UIQ].v);
        w->changed[p] = 1;   /* the host hears it through outputParameterChanges */
        __atomic_store_n(&w->uiq_tail, t + 1, __ATOMIC_RELEASE);
    }
#endif
    IEventList *el = d->inputEvents;
    int ne = el ? el->v->getEventCount(el) : 0;
    for (int k = 0; k < ne; k++) {
        Event e;
        if (el->v->getEvent(el, k, &e) != kResultOk) continue;
        uint8_t msg[3];
        if (e.type == kNoteOnEvent) {
            int vel = (int)lroundf(e.noteOn.velocity * 127);
            msg[0] = 0x90 | (e.noteOn.channel & 15); msg[1] = e.noteOn.pitch & 127; msg[2] = vel < 1 ? 1 : vel > 127 ? 127 : vel;
        } else if (e.type == kNoteOffEvent) {
            msg[0] = 0x80 | (e.noteOff.channel & 15); msg[1] = e.noteOff.pitch & 127; msg[2] = (uint8_t)lroundf(clamp01(e.noteOff.velocity) * 127);
        } else if (e.type == kPolyPressureEvent) {
            msg[0] = 0xA0 | (e.polyPressure.channel & 15); msg[1] = e.polyPressure.pitch & 127; msg[2] = (uint8_t)lroundf(clamp01(e.polyPressure.pressure) * 127);
        } else continue;
        queue_midi(w, e.sampleOffset, msg);
    }
    update_context(w, d->processContext, n);

    int evk = 0;
    float **out = d->numOutputs > 0 && d->outputs[0].numChannels >= 2 ? d->outputs[0].channelBuffers32 : NULL;
#ifdef PLUG_EFFECT
    float **in = d->numInputs > 0 && d->inputs[0].numChannels >= 1 ? d->inputs[0].channelBuffers32 : NULL;
    const float *il = in ? in[0] : NULL, *ir = in ? (d->inputs[0].numChannels >= 2 ? in[1] : in[0]) : NULL;
    if (n > 0) {
        /* MIDI for an effect applies before the engine block that holds its frame (one block's precision) */
        for (int from = 0; from < n; from += CHUNK) {
            int to = n - from > CHUNK ? from + CHUNK : n;
            run_effect(w, il, ir, from, to, &evk);
            pop_out(w, out ? out[0] + from : NULL, out ? out[1] + from : NULL, to - from);
        }
        while (evk < w->nev) send_midi(w, w->ev[evk++].msg);
        for (int j = 0; j < n; j++) {   /* the dry signal, delayed as the output is: what bypass plays */
            float dl = w->dry[0][w->drypos], dr = w->dry[1][w->drypos];
            w->dry[0][w->drypos] = il ? il[j] : 0;
            w->dry[1][w->drypos] = ir ? ir[j] : 0;
            w->drypos = (w->drypos + 1) % (int)w->latency;
            if (w->bypass && out) { out[0][j] = dl; out[1][j] = dr; }
        }
    } else {
        while (evk < w->nev) send_midi(w, w->ev[evk++].msg);
    }
#else
    /* An instrument renders on demand: each MIDI event goes in right before the output frame it is due at (to within the
     * converter's look-ahead, and a whole engine block unless SAMPLE_ACCURATE). */
    int pos = 0;
    while (pos < n) {
        while (evk < w->nev && w->ev[evk].frame <= pos) send_midi(w, w->ev[evk++].msg);
        int end = evk < w->nev && w->ev[evk].frame < n ? w->ev[evk].frame : n;
        if (end - pos > CHUNK) end = pos + CHUNK;
        fill_out(w, end - pos);
        pop_out(w, out ? out[0] + pos : NULL, out ? out[1] + pos : NULL, end - pos);
        pos = end;
    }
    while (evk < w->nev) send_midi(w, w->ev[evk++].msg);   /* past the block (or a parameter-only call): now */
    if (w->bypass && out) { memset(out[0], 0, sizeof(float) * n); memset(out[1], 0, sizeof(float) * n); }
#endif
    if (out) d->outputs[0].silenceFlags = 0;
    if (n > 0) report(w, d);
    return kResultOk;
}
static uint32_t proc_tail(void *s) {
    (void)s;
#ifdef PLUG_EFFECT
    return 0xFFFFFFFFu;   /* kInfiniteTail: delays and reverbs ring on after the input stops */
#else
    return 0;
#endif
}

static const ProcessorVtbl proc_vtbl = {
    proc_query, proc_addref, proc_release,
    proc_set_arr, proc_get_arr, proc_can_size, proc_latency, proc_setup, proc_set_processing, proc_process, proc_tail,
};

/* ---- IEditController ----------------------------------------------------------------- */
static tresult ctrl_initialize(void *s, FUnknown *ctx) { (void)s; (void)ctx; return kResultOk; }
static tresult ctrl_terminate(void *s) {
    v3_t *w = FROM(s, ctrl);
    if (w->handler) { w->handler->v->release(w->handler); w->handler = NULL; }
    return kResultOk;
}
static tresult ctrl_set_comp_state(void *s, IBStream *st) { (void)s; (void)st; return kResultOk; }   /* values come from the engine */
static tresult ctrl_set_state(void *s, IBStream *st) { (void)s; (void)st; return kResultOk; }
static tresult ctrl_get_state(void *s, IBStream *st) { (void)s; (void)st; return kResultOk; }
static int32_t ctrl_param_count(void *s) { (void)s; return param_count(); }

static uint32_t id_at(int index) {
    if (index < g_nvis) return (uint32_t)g_vis[index];
    index -= g_nvis;
    if (index == 0) return BYPASS_ID;
    index--;
    if (has_programs()) { if (index == 0) return PROG_ID; index--; }
    return MIDI_ID + (uint32_t)index;
}

static tresult ctrl_param_info(void *s, int32_t index, ParameterInfo *pi) {
    (void)s;
    if (index < 0 || index >= param_count()) return kInvalidArgument;
    memset(pi, 0, sizeof *pi);
    pi->id = id_at(index);
    if (pi->id == BYPASS_ID) {
        to_utf16(pi->title, "Bypass", 128);
        to_utf16(pi->shortTitle, "Bypass", 128);
        pi->stepCount = 1;
        pi->flags = kCanAutomate | kIsBypass;
        return kResultOk;
    }
    if (pi->id == PROG_ID) {
#ifdef NPRESETS
        to_utf16(pi->title, "Program", 128);
        to_utf16(pi->shortTitle, "Program", 128);
        pi->stepCount = NPRESETS > 1 ? NPRESETS - 1 : 1;
        pi->flags = kCanAutomate | kIsList | kIsProgramChange;
#endif
        return kResultOk;
    }
    if (pi->id >= MIDI_ID) {
        char name[32];
        int k = (int)(pi->id - MIDI_ID), ch = k / MIDI_CTRLS, c = k % MIDI_CTRLS;
        if (c == 128) snprintf(name, sizeof name, "Ch %d Pressure", ch + 1);
        else if (c == 129) snprintf(name, sizeof name, "Ch %d Pitch Bend", ch + 1);
        else snprintf(name, sizeof name, "Ch %d CC %d", ch + 1, c);
        to_utf16(pi->title, name, 128);
        to_utf16(pi->shortTitle, name, 128);
        pi->stepCount = c == 129 ? 0 : 127;
        pi->defaultNormalizedValue = c == 129 ? 0.5 : 0;
        pi->flags = kIsHidden | kIsReadOnly;
        return kResultOk;
    }
    const param_t *p = &PARAMS[pi->id];
    to_utf16(pi->title, p->name, 128);
    to_utf16(pi->shortTitle, p->name, 128);
    to_utf16(pi->units, p->unit, 128);
    pi->stepCount = step_count(p);
    pi->defaultNormalizedValue = clamp01(p->def);
    pi->flags = p->string_display ? kIsReadOnly : kCanAutomate;   /* a readout: text the engine writes */
    if (p->nopts > 1) pi->flags |= kIsList;
    return kResultOk;
}

static void value_text(v3_t *w, uint32_t id, double v, char *buf, size_t len) {
    buf[0] = 0;
    if (id == BYPASS_ID) { snprintf(buf, len, "%s", v > 0.5 ? "On" : "Off"); return; }
    if (id == PROG_ID) {
#ifdef NPRESETS
        int idx = (int)lround(clamp01(v) * (NPRESETS > 1 ? NPRESETS - 1 : 0));
        snprintf(buf, len, "%s", PRESETS[idx].name);
#endif
        return;
    }
    if (id >= MIDI_ID) {
        if ((id - MIDI_ID) % MIDI_CTRLS == 129) snprintf(buf, len, "%ld", lround(clamp01(v) * 16383) - 8192);
        else snprintf(buf, len, "%ld", lround(clamp01(v) * 127));
        return;
    }
    const param_t *p = &PARAMS[id];
    char k2[96], tmp[128];
    snprintf(k2, sizeof k2, "%s_display", p->key);
    if (p->string_display || (p->dynamic_display && fabs(v - get_norm(w, (int)id)) < 1e-6)) {
        /* engine text: only for the current value (a readout, or a value the engine names itself) */
        if (eng_get(w, p->dynamic_display ? k2 : p->key, tmp, sizeof tmp) > 0) { snprintf(buf, len, "%s", tmp); return; }
    }
    if (p->nopts) { snprintf(buf, len, "%s", p->opts[lround(clamp01(v) * (p->nopts - 1))]); return; }
    if (p->momentary || p->step_target >= 0) { snprintf(buf, len, "%s", v > 0.5 ? "On" : "Off"); return; }
    double x = p->min + (p->max - p->min) * clamp01(v);
    snprintf(buf, len, "%.*f", (p->int_display || fabs(p->max - p->min) > 20) ? 0 : (fabs(p->max - p->min) > 2 ? 1 : 2), x);
}

static tresult ctrl_string_by_value(void *s, uint32_t id, double v, char16 *out) {
    v3_t *w = FROM(s, ctrl);
    if (!(is_param(id) || id == PROG_ID || id == BYPASS_ID || (id >= MIDI_ID && id < MIDI_ID + MIDI_PARAMS))) return kInvalidArgument;
    char buf[128];
    value_text(w, id, v, buf, sizeof buf);
    to_utf16(out, buf, 128);
    return kResultOk;
}
static tresult ctrl_value_by_string(void *s, uint32_t id, char16 *str, double *v) {
    char buf[128];
    from_utf16(buf, str, sizeof buf);
    if (id == BYPASS_ID) { *v = !strcasecmp(buf, "On") || atoi(buf) ? 1 : 0; return kResultOk; }
#ifdef NPRESETS
    if (id == PROG_ID) {
        for (int i = 0; i < NPRESETS; i++)
            if (!strcasecmp(buf, PRESETS[i].name)) { *v = NPRESETS > 1 ? (double)i / (NPRESETS - 1) : 0; return kResultOk; }
        return kResultFalse;
    }
#endif
    if (id >= MIDI_ID && id < MIDI_ID + MIDI_PARAMS) {
        if ((id - MIDI_ID) % MIDI_CTRLS == 129) *v = clamp01((atof(buf) + 8192) / 16383);
        else *v = clamp01(atof(buf) / 127);
        return kResultOk;
    }
    if (!is_param(id)) return kInvalidArgument;
    const param_t *p = &PARAMS[id];
    if (p->string_display) { *v = get_norm(FROM(s, ctrl), (int)id); return kResultOk; }   /* a readout's text is its current value */
    *v = str_to_norm(p, buf, 1);
    return kResultOk;
}
static double ctrl_to_plain(void *s, uint32_t id, double v) {
    (void)s;
    if (!is_param(id)) return v;
    const param_t *p = &PARAMS[id];
    if (p->nopts > 1) return lround(clamp01(v) * (p->nopts - 1));
    return p->min + (p->max - p->min) * clamp01(v);
}
static double ctrl_to_norm(void *s, uint32_t id, double plain) {
    (void)s;
    if (!is_param(id)) return plain;
    const param_t *p = &PARAMS[id];
    if (p->nopts > 1) return clamp01(plain / (p->nopts - 1));
    return p->max > p->min ? clamp01((plain - p->min) / (p->max - p->min)) : 0;
}
static double ctrl_get_norm(void *s, uint32_t id) {
    v3_t *w = FROM(s, ctrl);
    if (is_param(id)) return get_norm(w, (int)id);
    if (id == BYPASS_ID) return w->bypass;
#ifdef NPRESETS
    if (id == PROG_ID) return NPRESETS > 1 && w->prog > 0 ? (double)w->prog / (NPRESETS - 1) : 0;
#endif
    if (id >= MIDI_ID && id < MIDI_ID + MIDI_PARAMS) return (id - MIDI_ID) % MIDI_CTRLS == 129 ? 0.5 : 0;
    return 0;
}
static tresult ctrl_set_norm(void *s, uint32_t id, double v) {
    v3_t *w = FROM(s, ctrl);
    if (is_param(id) && (PARAMS[id].momentary || PARAMS[id].step_target >= 0)) return kResultOk;   /* process() owns their state */
    if (is_param(id)) w->hostval[id] = clamp01(v);
    if (id == BYPASS_ID) w->bypass = v > 0.5;
    return kResultOk;
}
static tresult ctrl_set_handler(void *s, IComponentHandler *h) {
    v3_t *w = FROM(s, ctrl);
    if (h == w->handler) return kResultOk;
    if (w->handler) w->handler->v->release(w->handler);
    w->handler = h;
    if (h) h->v->addRef(h);
    return kResultOk;
}
#ifdef VST3_EDITOR
static void *editor_create(v3_t *w, const char *name);   /* vst3_editor.c */
static void *ctrl_create_view(void *s, const char *name) { return editor_create(FROM(s, ctrl), name); }
#else
static void *ctrl_create_view(void *s, const char *name) { (void)s; (void)name; return NULL; }
#endif

static const ControllerVtbl ctrl_vtbl = {
    ctrl_query, ctrl_addref, ctrl_release, ctrl_initialize, ctrl_terminate,
    ctrl_set_comp_state, ctrl_set_state, ctrl_get_state, ctrl_param_count, ctrl_param_info,
    ctrl_string_by_value, ctrl_value_by_string, ctrl_to_plain, ctrl_to_norm, ctrl_get_norm, ctrl_set_norm,
    ctrl_set_handler, ctrl_create_view,
};

/* ---- IMidiMapping, IProcessContextRequirements ----------------------------------------- */
static tresult mm_assign(void *s, int32_t bus, int16_t ch, int16_t ctrl, uint32_t *id) {
    (void)s;
    if (bus != 0 || ch < 0 || ch > 15 || ctrl < 0 || ctrl >= MIDI_CTRLS) return kResultFalse;
    *id = MIDI_ID + (uint32_t)(ch * MIDI_CTRLS + ctrl);
    return kResultOk;
}
static const MidiMappingVtbl mm_vtbl = { mm_query, mm_addref, mm_release, mm_assign };

static uint32_t cr_requirements(void *s) { (void)s; return (1 << 2) | (1 << 6) | (1 << 10); }   /* project time, tempo, transport */
static const CtxReqVtbl cr_vtbl = { cr_query, cr_addref, cr_release, cr_requirements };

/* ---- instance lifetime ------------------------------------------------------------------- */
static void destroy(v3_t *w) {
    if (w->handler) w->handler->v->release(w->handler);
    if (w->dsp) g_api->destroy(w->dsp);
    free_audio(w);
    pthread_mutex_destroy(&w->lock);
    free(w);
}

static v3_t *create(void) {
    if (!g_api) g_api = mpc_engine();
    if (!g_api) return NULL;
#ifdef PLUG_EFFECT
    if (!g_api->process) return NULL;
#endif
    v3_t *w = calloc(1, sizeof *w);
    if (!w) return NULL;
    pthread_mutexattr_t ma;
    pthread_mutexattr_init(&ma);
    pthread_mutexattr_settype(&ma, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&w->lock, &ma);
    pthread_mutexattr_destroy(&ma);
#ifdef MODULE_SUBDIR
    char data_dir[600], here[512];
    const char *module_dir = MODULE_DIR;
    if (mpc_plugin_dir(here, sizeof here) && snprintf(data_dir, sizeof data_dir, "%s/%s", here, MODULE_SUBDIR) < (int)sizeof data_dir)
        module_dir = data_dir;
    w->dsp = g_api->create(module_dir);
#else
    w->dsp = g_api->create(MODULE_DIR);
#endif
    if (!w->dsp) { pthread_mutex_destroy(&w->lock); free(w); return NULL; }
    w->comp = &comp_vtbl;
    w->proc = &proc_vtbl;
    w->ctrl = &ctrl_vtbl;
    w->midimap = &mm_vtbl;
    w->ctxreq = &cr_vtbl;
    w->refs = 1;
    w->rate = ENGINE_RATE;
    w->nrpn = -1;
    w->prog = -1;
    for (int i = 0; i < NPARAMS; i++) { w->hostval[i] = PARAMS[i].momentary ? 0 : clamp01(PARAMS[i].def); w->reported[i] = -1; }
    return w;
}

/* ---- factory ------------------------------------------------------------------------------ */
static tresult f_query(void *s, const TUID iid, void **obj) {
    if (iid_eq(iid, iid_FUnknown) || iid_eq(iid, iid_IPluginFactory) || iid_eq(iid, iid_IPluginFactory2)) { *obj = s; return kResultOk; }
    *obj = NULL;
    return kNoInterface;
}
static uint32_t f_ref(void *s) { (void)s; return 1; }   /* a static object */
static tresult f_info(void *s, PFactoryInfo *fi) {
    (void)s;
    memset(fi, 0, sizeof *fi);
    snprintf(fi->vendor, sizeof fi->vendor, "%s", PLUG_VENDOR);
    return kResultOk;
}
static int32_t f_count(void *s) { (void)s; return 1; }
static void version_string(char *buf, int len) {   /* vst.json "version" 1203 -> "1.2.0.3" */
    int v = PLUG_VERSION;
    snprintf(buf, len, "%d.%d.%d.%d", v / 1000 % 10, v / 100 % 10, v / 10 % 10, v % 10);
}
static tresult f_class(void *s, int32_t i, PClassInfo *ci) {
    (void)s;
    if (i != 0) return kInvalidArgument;
    memset(ci, 0, sizeof *ci);
    memcpy(ci->cid, g_cid, 16);
    ci->cardinality = 0x7FFFFFFF;
    snprintf(ci->category, sizeof ci->category, "Audio Module Class");
    snprintf(ci->name, sizeof ci->name, "%s", PLUG_NAME);
    return kResultOk;
}
static tresult f_class2(void *s, int32_t i, PClassInfo2 *ci) {
    (void)s;
    if (i != 0) return kInvalidArgument;
    memset(ci, 0, sizeof *ci);
    memcpy(ci->cid, g_cid, 16);
    ci->cardinality = 0x7FFFFFFF;
    snprintf(ci->category, sizeof ci->category, "Audio Module Class");
    snprintf(ci->name, sizeof ci->name, "%s", PLUG_NAME);
#ifdef PLUG_EFFECT
    snprintf(ci->subCategories, sizeof ci->subCategories, "Fx");
#else
    snprintf(ci->subCategories, sizeof ci->subCategories, "Instrument|Synth");
#endif
    snprintf(ci->vendor, sizeof ci->vendor, "%s", PLUG_VENDOR);
    version_string(ci->version, sizeof ci->version);
    snprintf(ci->sdkVersion, sizeof ci->sdkVersion, "VST 3.7.0");
    return kResultOk;
}
static tresult f_create(void *s, const char *cid, const char *iid, void **obj) {
    (void)s;
    *obj = NULL;
    if (!iid_eq(cid, g_cid)) return kNoInterface;
    v3_t *w = create();
    if (!w) return kResultFalse;
    tresult r = query(w, (const uint8_t *)iid, obj);
    release(w);   /* query holds the reference now, or the instance goes */
    return r;
}
static const FactoryVtbl factory_vtbl = {
    f_query, f_ref, f_ref, f_info, f_count, f_class, f_create, f_class2,
};
static const FactoryVtbl *factory = &factory_vtbl;

static void init_tables(void) {
    g_nvis = 0;
    for (int i = 0; i < NPARAMS; i++)
        if (!popup_is(i)) g_vis[g_nvis++] = i;
    make_cid();
}

#ifdef _WIN32
#define VST3_EXPORT __declspec(dllexport)
#else
#define VST3_EXPORT __attribute__((visibility("default")))
#endif
VST3_EXPORT void *GetPluginFactory(void) {
    init_tables();
    return (void *)&factory;
}
#ifdef _WIN32
/* Windows hosts call InitDll/ExitDll where Linux ones call ModuleEntry/ModuleExit. */
VST3_EXPORT int InitDll(void) { init_tables(); return 1; }
VST3_EXPORT int ExitDll(void) { return 1; }
#else
VST3_EXPORT int ModuleEntry(void *handle) { (void)handle; init_tables(); return 1; }
VST3_EXPORT int ModuleExit(void) { return 1; }
#endif

#ifdef VST3_EDITOR
#include "vst3_editor.c"
#endif
