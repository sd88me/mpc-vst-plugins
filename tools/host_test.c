/* Offline x86 host test for a port built on wrapper/vst2_wrap.c: link it with the wrapper, the engine
 * (and its adapter) and the port's generated params.h -- tools/test_port.sh does all that -- and run
 * under ASan. Checks two independent instances, names/display for every param, a set/get round
 * trip, option selection, popup open/close, note -> audio, chunk save/restore, step_of on an option list and, with
 * HAS_TRANSPORT, play/stop/jump-back (poc/steptest). Exit 1 on failure. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>
#include "params.h"
typedef struct AEffect AEffect;
typedef intptr_t (*cb)(AEffect*,int32_t,int32_t,intptr_t,void*,float);
struct AEffect { int32_t magic; intptr_t (*d)(AEffect*,int32_t,int32_t,intptr_t,void*,float);
 void*p; void (*setP)(AEffect*,int32_t,float); float (*getP)(AEffect*,int32_t);
 int32_t np,npar,ni,no,flags; intptr_t r1,r2; int32_t a,b,c; float io; void*obj,*user; int32_t uid,ver;
 void (*pr)(AEffect*,float**,float**,int32_t); void*pdr; char f[56]; };
typedef struct { int32_t type,byteSize,deltaFrames,flags,noteLength,noteOffset; unsigned char m[4]; char x[4]; } ME;
typedef struct { int32_t n; intptr_t r; void* ev[2]; } EV;
extern AEffect* VSTPluginMain(cb);

static int automated[NPARAMS > 0 ? NPARAMS : 1], fails;
static double ti[16];                    /* VstTimeInfo: [3] ppqPos, [4] tempo, flags = ((int32_t *)&ti[8])[5] */
static int32_t ti_flags = 1 << 10;       /* tempo valid; transport_tests() adds playing (1 << 1) and ppq valid (1 << 9) */
static intptr_t host(AEffect*e,int32_t op,int32_t i,intptr_t v,void*p,float o){
    if (op == 0 && i >= 0 && i < NPARAMS) automated[i]++;
    if (op == 7) { ti[4] = 120.0; ((int32_t*)&ti[8])[5] = ti_flags; return (intptr_t)ti; }
    return 0;
}
#define CHECK(c, ...) do { printf("%s ", (c) ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!(c)) fails++; } while (0)
/* Effects (numInputs == 2) read in[0]/in[1], so they need real input buffers; instruments take NULL in. */
static void run(AEffect *a, int blocks) {
    float L[128], R[128], I0[128] = {0}, I1[128] = {0}, *o[2] = {L, R}, *in[2] = {I0, I1};
    float **ip = a->ni >= 2 ? in : 0;
    for (int k = 0; k < blocks; k++) a->pr(a, ip, o, 128);
}

/* How MPC nudges a stepped param (an option list, a "display": "int" range), measured on a Force (docs/NOTES.md "Input probe")
 * and an MPC One: the data wheel and a Q-Link send the read-back value plus a small delta (0.01 / 1/128 of the range); a drag or
 * sweep keeps sending positions from where it started. Each wheel click or Q-Link event must move one step, a sweep must not
 * flicker, and a reversal must go the other way. span = steps from the minimum to the maximum. */
static void step_tests(AEffect *a, int i, const char *kind, int span) {
    const char *key = PARAMS[i].key;
    float mn = span;
    a->setP(a, i, 0);
    int ok = 1;
    for (int k = 1; k <= 6; k++) {   /* data wheel: +0.01 from the read-back value */
        a->setP(a, i, a->getP(a, i) + 0.01f);
        if (fabsf(a->getP(a, i) * span - (k < span ? k : span)) > 0.05f) ok = 0;
    }
    CHECK(ok, "%s %s: six data wheel clicks step six (%.2f)", kind, key, a->getP(a, i) * span);
    if (span <= 64) {   /* a Q-Link event is 1/128 of the range: still one step each (opt-in counting is qlink_ticks) */
        a->setP(a, i, 0); ok = 1;
        for (int k = 1; k <= 6; k++) {
            a->setP(a, i, a->getP(a, i) + 1.0f / 128);
            if (fabsf(a->getP(a, i) * span - (k < span ? k : span)) > 0.05f) ok = 0;
        }
        CHECK(ok, "%s %s: six Q-Link events step six (%.2f)", kind, key, a->getP(a, i) * span);
    }
    a->setP(a, i, 0); ok = 1;
    float prev = 0, last = 0;
    for (int k = 1; 0.3f * k <= span; k++) {   /* a sweep up from where it started: 0.3 step per event */
        a->setP(a, i, 0.3f * k / span);
        float v = a->getP(a, i) * span;
        if (v < prev - 0.05f) ok = 0;
        prev = v; last = 0.3f * k;
    }
    CHECK(ok && fabsf(prev - ceilf(last - 0.001f)) < 0.05f, "%s %s: a sweep up goes steadily, no flicker (ends at %.2f)", kind, key, prev);
    ok = 1;
    for (int k = 1; last - 0.3f * k >= 0; k++) {   /* and back down */
        a->setP(a, i, (last - 0.3f * k) / span);
        float v = a->getP(a, i) * span;
        if (v > prev + 0.05f) ok = 0;
        prev = v;
    }
    CHECK(ok && prev < mn, "%s %s: a sweep back down goes steadily, no flicker (ends at %.2f)", kind, key, prev);
    a->setP(a, i, 0);
}

#ifdef SAMPLE_PROBE   /* poc/sampleprobe: a note-on switches a constant level on from the next frame it renders */
extern int sampleprobe_bad;
static int first_nonzero(const float *L, int n) { for (int i = 0; i < n; i++) if (L[i] != 0) return i; return -1; }
static int last_nonzero(const float *L, int n) { for (int i = n - 1; i >= 0; i--) if (L[i] != 0) return i; return -1; }
static void send(AEffect *c, int d1, int s1, int d2, int s2, int two) {   /* up to two events, in the order given */
    ME m1 = {1, sizeof(ME), d1, 0, 0, 0, {(unsigned char)s1, 60, 100, 0}}, m2 = {1, sizeof(ME), d2, 0, 0, 0, {(unsigned char)s2, 60, 100, 0}};
    EV ev = {two ? 2 : 1, 0, {&m1, &m2}};
    c->d(c, 25, 0, 0, &ev, 0);
}
static void send3(AEffect *c, const int *d, const int *st, int n) {   /* n (<= 3) events, in the order given */
    ME m[3]; struct { int32_t n; intptr_t r; void *ev[3]; } ev = {n, 0, {0}};
    for (int i = 0; i < n; i++) { ME t = {1, sizeof(ME), d[i], 0, 0, 0, {(unsigned char)st[i], 60, 100, 0}}; m[i] = t; ev.ev[i] = &m[i]; }
    c->d(c, 25, 0, 0, &ev, 0);
}
static void sample_accurate_tests(void) {
    AEffect *c = VSTPluginMain(host);
    float L[256], R[256], *o[2] = {L, R};
    static const int ds[] = {0, 1, 17, 64, 100, 127};
    for (unsigned k = 0; k < sizeof ds / sizeof ds[0]; k++) {
        send(c, ds[k], 0x90, 0, 0, 0); c->pr(c, 0, o, 128);
        CHECK(first_nonzero(L, 128) == ds[k], "SAMPLE_ACCURATE: note-on at deltaFrames %d starts at frame %d", ds[k], first_nonzero(L, 128));
        send(c, 0, 0x80, 0, 0, 0); c->pr(c, 0, o, 128);
    }
    send(c, 50, 0x80, 10, 0x90, 1); c->pr(c, 0, o, 128);   /* out of order: sorted by frame */
    CHECK(first_nonzero(L, 128) == 10 && last_nonzero(L, 128) == 49, "events out of order: on at 10, off at 50 -> frames %d..%d", first_nonzero(L, 128), last_nonzero(L, 128));
    {   /* events on one frame keep their order, whatever else is queued: an off then an on at 7 (a retrigger) must not end silent */
        const int d[3] = {2, 7, 7}, st[3] = {0x90, 0x80, 0x90};
        send(c, 0, 0x90, 0, 0, 0); c->pr(c, 0, o, 128);   /* sounding */
        send3(c, d, st, 3); c->pr(c, 0, o, 128);
        CHECK(first_nonzero(L, 128) == 0 && L[7] != 0 && last_nonzero(L, 128) == 127, "same-frame off then on at 7 stays in order (retrigger sounds: frames 0..%d)", last_nonzero(L, 128));
        send(c, 0, 0x80, 0, 0, 0); c->pr(c, 0, o, 128);
    }
    send(c, 40, 0x90, 0, 0, 0); c->pr(c, 0, o, 100);   /* a host block that is not 128 frames */
    CHECK(first_nonzero(L, 100) == 40, "100-frame block: note-on at 40 starts at frame %d", first_nonzero(L, 100));
    send(c, 0, 0x80, 0, 0, 0); c->pr(c, 0, o, 128);
    send(c, 200, 0x90, 0, 0, 0); c->pr(c, 0, o, 128);   /* past the end: at the start of the next block */
    int silent = first_nonzero(L, 128) < 0; c->pr(c, 0, o, 128);
    CHECK(silent && first_nonzero(L, 128) == 0, "deltaFrames 200 in a 128-frame block: silent, then frame 0 of the next");
    send(c, 0, 0x80, 0, 0, 0); c->pr(c, 0, o, 128);
    send(c, -5, 0x90, 0, 0, 0); c->pr(c, 0, o, 128);   /* negative: treated as 0 */
    CHECK(first_nonzero(L, 128) == 0, "negative deltaFrames starts at frame 0");
    CHECK(sampleprobe_bad == 0, "render() always got 1..128 frames (%d bad calls)", sampleprobe_bad);
    c->d(c, 1, 0, 0, 0, 0);
}
#endif

static int find_param(const char *key) {
    for (int i = 0; i < NPARAMS; i++) if (!strcmp(PARAMS[i].key, key)) return i;
    return -1;
}

#if defined(HAS_TRANSPORT) && HAS_TRANSPORT
/* poc/steptest: the engine logs every "transport" value it gets in its "transport_log" readout. Play sends "1", stop "0",
 * a jump back in song position while playing (a loop, a locate) "1" again; moving forward sends nothing. */
static void transport_tests(void) {
    int lg = find_param("transport_log");
    if (lg < 0) { printf("warn HAS_TRANSPORT without a transport_log readout: not tested\n"); return; }
    AEffect *c = VSTPluginMain(host);
    char d[64];
    run(c, 2);                                           /* stopped: nothing */
    ti_flags = 1 << 10 | 1 << 9 | 1 << 1; ti[3] = 0; run(c, 1);   /* play */
    ti[3] = 1.0; run(c, 1); ti[3] = 2.0; run(c, 1);      /* forward */
    ti[3] = 0.5; run(c, 1);                              /* jump back */
    ti[3] = 0.6; run(c, 1);
    ti_flags = 1 << 10 | 1 << 9; run(c, 2);              /* stop */
    ti_flags = 1 << 10; ti[3] = 0;
    d[0] = 0; c->d(c, 7, lg, 0, d, 0);
    CHECK(!strcmp(d, "110"), "transport: play, jump back, stop -> \"%s\" (want \"110\")", d);
    c->d(c, 1, 0, 0, 0, 0);
}
#endif

/* A step_of button pair on an option list (e.g. a synth model picked with prev/next): steps by index, wraps both ways, and
 * tells the host the new value (audioMasterAutomate) on the next block. */
static void step_of_option_tests(AEffect *a) {
    int prev = -1, next = -1;
    for (int i = 0; i < NPARAMS; i++)
        if (PARAMS[i].step_target >= 0 && PARAMS[PARAMS[i].step_target].nopts > 1) {
            if (PARAMS[i].step_delta < 0 && prev < 0) prev = i;
            if (PARAMS[i].step_delta > 0 && next < 0) next = i;
        }
    if (prev < 0 || next < 0 || PARAMS[prev].step_target != PARAMS[next].step_target) return;
    int t = PARAMS[next].step_target, n = PARAMS[t].nopts;
    a->setP(a, t, 1.0f); run(a, 1);
    automated[t] = 0;
    a->setP(a, next, 1.0f); run(a, 1); a->setP(a, next, 0.0f);
    CHECK(a->getP(a, t) < 1e-3f && automated[t] == 1, "step_of %s on %s: last -> first (%.3f), reported %d time(s)",
          PARAMS[next].key, PARAMS[t].key, a->getP(a, t), automated[t]);
    a->setP(a, prev, 1.0f); run(a, 1); a->setP(a, prev, 0.0f);
    CHECK(fabsf(a->getP(a, t) - 1.0f) < 1e-3f && automated[t] == 2, "step_of %s on %s: first -> last (%.3f)",
          PARAMS[prev].key, PARAMS[t].key, a->getP(a, t));
    a->setP(a, prev, 1.0f); run(a, 1); a->setP(a, prev, 0.0f);
    CHECK(fabsf(a->getP(a, t) - (float)(n - 2) / (n - 1)) < 1e-3f, "step_of %s on %s: steps one option (%.3f)",
          PARAMS[prev].key, PARAMS[t].key, a->getP(a, t));
}

/* MIDI control (gen_vst.py cc_lines()): CC 20 moves the first Q-Link's parameter, NRPN n sets parameter n, and the
 * host hears about it (throttled to every 1024 frames). */
static void cc(AEffect *a, int num, int val) {
    ME m = {1, sizeof(ME), 0, 0, 0, 0, {0xB0, (unsigned char)num, (unsigned char)val, 0}}; EV ev = {1, 0, {&m, 0}};
    a->d(a, 25, 0, 0, &ev, 0);
}
/* whether a direct set of parameter i to v sticks (engine-driven displays, e.g. a meter level, don't keep a value) */
static int keeps(AEffect *a, int i, float v) {
    a->setP(a, i, v);
    return fabsf(a->getP(a, i) - v) < 0.01f;
}
static void cc_tests(AEffect *a) {
#ifdef HAS_CC_MAP
    int q = PLUG_CC[0];
    if (q >= 0 && keeps(a, q, 1.0f) && keeps(a, q, 0.0f)) {
        memset(automated, 0, sizeof automated);
        cc(a, 20, 0); cc(a, 20, 127);
        run(a, 9);
        CHECK(a->getP(a, q) > 0.99f, "CC 20 = 127 moves %s to the top (%g)", PARAMS[q].key, a->getP(a, q));
        CHECK(automated[q] > 0, "CC 20's change of %s reported to the host", PARAMS[q].key);
    }
#endif
#ifdef HAS_NRPN
    for (int i = 0; i < NPARAMS; i++) {
        if (PARAMS[i].nopts || PARAMS[i].momentary || PARAMS[i].string_display || PARAMS[i].step_target >= 0 ||
            PARAMS[i].popup_of >= 0 || PARAMS[i].int_display || PARAMS[i].max <= PARAMS[i].min) continue;
        if (!keeps(a, i, 0.5f) || !keeps(a, i, 0.0f)) continue;
        cc(a, 99, i >> 7); cc(a, 98, i & 127); cc(a, 6, 64); cc(a, 38, 0);
        CHECK(fabsf(a->getP(a, i) - 8192.0f / 16383.0f) < 0.01f, "NRPN %d sets %s to the middle (%g)", i, PARAMS[i].key, a->getP(a, i));
        break;
    }
#endif
}

/* Two threads, as a JUCE host drives a plugin: parameter sets/reads and display text on one, audio on the other. The
 * wrapper runs one engine call at a time (vst2_wrap.c eng_set()); an engine that is unsafe without that crashes here. */
static AEffect *g_two;
static volatile int g_two_done;
static void *screen_thread(void *arg) {
    char txt[256];
    unsigned r = 1;
    (void)arg;
    for (int k = 0; k < 3000 && !g_two_done; k++) {
        int i = (int)((r = r * 1103515245u + 12345u) >> 8) % (NPARAMS > 0 ? NPARAMS : 1);
        if (PARAMS[i].momentary || PARAMS[i].step_target >= 0) continue;
        g_two->setP(g_two, i, (float)((r >> 4) % 1000) / 999.0f);
        g_two->getP(g_two, i);
        g_two->d(g_two, 7, i, 0, txt, 0);   /* effGetParamDisplay */
    }
    return 0;
}
static void two_thread_tests(AEffect *a) {
    pthread_t t;
    g_two = a; g_two_done = 0;
    pthread_create(&t, 0, screen_thread, 0);
    run(a, 300);
    g_two_done = 1;
    pthread_join(t, 0);
    CHECK(1, "two threads: 3000 screen-side sets/reads while rendering");
}

/* VST programs (vst.json "presets" / "programs"): every program has a name, picking one moves the engine there, the
 * plugin reports the new current program, and the parameters it set are reported back to the host (housekeeping). */
static void program_tests(AEffect *a) {
#if defined(NPRESETS) || defined(PROG_PARAM)
    char name[64];
    CHECK(a->np >= 1, "%d programs", a->np);
    for (int k = 0; k < a->np; k++) {
        name[0] = 0;
        CHECK(a->d(a, 29, k, 0, name, 0) == 1 && name[0], "program %d is named \"%s\"", k, name);
    }
    int pick = a->np - 1;
    if (pick == a->d(a, 3, 0, 0, 0, 0)) { printf("warn one program, already current: picking it changes nothing\n"); return; }
    memset(automated, 0, sizeof automated);
    a->d(a, 2, 0, pick, 0, 0);
    run(a, 1);
    CHECK(a->d(a, 3, 0, 0, 0, 0) == pick, "program %d is current after picking it", pick);
#if defined(NPRESETS)
    for (int i = 0; i < PRESETS[pick].n; i++) {
        const param_t *p = &PARAMS[PRESETS[pick].values[i].param];
        float want = p->nopts > 1 ? atof(PRESETS[pick].values[i].value) / (p->nopts - 1)
                                  : (atof(PRESETS[pick].values[i].value) - p->min) / (p->max - p->min);
        float got = a->getP(a, PRESETS[pick].values[i].param);
        CHECK(fabsf(got - want) < 1e-3f, "preset \"%s\" sets %s (%g, want %g)", PRESETS[pick].name, p->key, got, want);
        CHECK(automated[PRESETS[pick].values[i].param] > 0, "preset change of %s reported to the host", p->key);
    }
#endif
#else
    CHECK(a->np == 0, "no programs without vst.json presets/programs");
#endif
}

/* MPC's plugin host (JUCE) sets parameter 0 to the far end of its range and straight back whenever it gets ready to play
 * (on insert and on every STOP, for plugins without an editor; Live II trace 2026-10-10). That must leave the plugin as
 * it was: with a preset as parameter 0 it loaded the preset twice and every knob moved since went back to it. The
 * wrapper holds a host set of parameter 0 until the next block and drops a pair that ends where it started. */
static int toggle_skip(int i) {
    const param_t *p = &PARAMS[i];
    if (p->momentary || p->step_target >= 0 || p->popup_of >= 0 || p->string_display) return 1;
#ifdef PLUG_LIVE_COUNT
    for (int k = 0; k < PLUG_LIVE_COUNT; k++) if (PLUG_LIVE[k] == i) return 1;
#endif
    return 0;
}
#if defined(PARAM_TEXT_MAX) && PARAM_TEXT_MAX > 64   /* a port that shows longer text (vst.json "defines") */
#define TOGGLE_TEXT PARAM_TEXT_MAX
#else
#define TOGGLE_TEXT 64
#endif
static void param0_toggle_check(void) {
    if (NPARAMS < 2) return;
    AEffect *c = VSTPluginMain(host);
    static char before[NPARAMS][TOGGLE_TEXT];
    char d[TOGGLE_TEXT];
    int moved = 0;
    for (int i = 1; i < NPARAMS; i++) {   /* every knob moved, so a preset loaded under them shows */
        const param_t *p = &PARAMS[i];
        if (toggle_skip(i) || p->nopts || p->max <= p->min) continue;
        c->setP(c, i, c->getP(c, i) < 0.5f ? 0.73f : 0.21f);
        moved++;
    }
    run(c, 2);
    for (int i = 0; i < NPARAMS; i++) { before[i][0] = 0; c->d(c, 7, i, 0, before[i], 0); }
    float old = c->getP(c, 0);
    c->setP(c, 0, old < 0.5f ? 1.0f : 0.0f);   /* what JUCE's prepareToPlay does */
    c->setP(c, 0, old);
    run(c, 2);
    int changed = 0;
    for (int i = 0; i < NPARAMS; i++) {
        if (toggle_skip(i)) continue;
        d[0] = 0; c->d(c, 7, i, 0, d, 0);
        if (strcmp(d, before[i]) && changed++ < 5) printf("     %s: \"%s\" -> \"%s\"\n", PARAMS[i].key, before[i], d);
    }
    CHECK(!changed, "MPC's STOP toggle of parameter 0 (%s to the far end and back) changes nothing, %d knobs moved (%d changed)",
          PARAMS[0].key, moved, changed);
    c->d(c, 1, 0, 0, 0, 0);
}

int main(void) {
    AEffect *a = VSTPluginMain(host), *b = VSTPluginMain(host);
    CHECK(a && b && a != b, "two instances");
    if (!a || !b) return 1;
    CHECK(a->magic == 0x56737450 && a->npar == NPARAMS, "magic 'VstP', %d params, uid %08x", a->npar, a->uid);
    CHECK(a->p && a->pr, "process and processReplacing both set");
    char s[256], d[256];
    int named = 0;
    for (int i = 0; i < a->npar; i++) {
        s[0] = d[0] = 0; a->d(a, 8, i, 0, s, 0); a->d(a, 7, i, 0, d, 0);
        named += s[0] != 0;
    }
    CHECK(named == a->npar, "every param has a name (%d/%d)", named, a->npar);

    int cont = -1, en = -1, pop = -1;
    for (int i = 0; i < NPARAMS; i++) {
        const param_t *p = &PARAMS[i];
        if (cont < 0 && !p->nopts && !p->momentary && !p->string_display && p->step_target < 0 && p->max > p->min) cont = i;
        if (en < 0 && p->nopts > 2 && !p->momentary && p->popup_of < 0) en = i;
        if (pop < 0 && p->popup_of >= 0) pop = i;
    }
    if (cont >= 0) {
        float tol = 1.0f / (PARAMS[cont].max - PARAMS[cont].min) + 0.01f;
        a->setP(a, cont, 0.25f); a->d(a, 7, cont, 0, d, 0);
        CHECK(fabsf(a->getP(a, cont) - 0.25f) <= tol, "set %s 0.25 -> get %.3f (\"%s\")", PARAMS[cont].key, a->getP(a, cont), d);
        CHECK(fabsf(b->getP(b, cont) - 0.25f) > 1e-4f || PARAMS[cont].def == 0.25f, "instance b unaffected");
    }
    if (en >= 0) {
        int n = PARAMS[en].nopts;
        a->setP(a, en, 1.0f); a->d(a, 7, en, 0, d, 0);
        CHECK(!strcmp(d, PARAMS[en].opts[n - 1]), "option %s -> \"%s\" (want \"%s\")", PARAMS[en].key, d, PARAMS[en].opts[n - 1]);
        a->setP(a, en, (n - 1.5f) / (n - 1));   /* half an option down from the last: one option down (settle() rounds toward the move) */
        CHECK(fabsf(a->getP(a, en) - (float)(n - 2) / (n - 1)) < 1e-3f, "nudge steps one option (%.3f)", a->getP(a, en));
        if (PARAMS[en].qlink_ticks <= 1) step_tests(a, en, "option", n - 1);   /* counted params: below */
        /* Q-Link ticks, as MPC sends them (a small delta from the current option): without qlink_ticks each one
         * steps an option; with it, one option per qlink_ticks events the same way, and a turn back starts over */
        int ticks = PARAMS[en].qlink_ticks > 1 ? PARAMS[en].qlink_ticks : 1;
        float tick = 0.1f / (n - 1);
        a->setP(a, en, 0);
        for (int k = 0; k < ticks - 1; k++) a->setP(a, en, a->getP(a, en) + tick);
        CHECK(a->getP(a, en) < 1e-3f, "%d ticks stay put (%.3f)", ticks - 1, a->getP(a, en));
        a->setP(a, en, a->getP(a, en) + tick);
        CHECK(fabsf(a->getP(a, en) - 1.0f / (n - 1)) < 1e-3f, "tick %d steps one option (%.3f)", ticks, a->getP(a, en));
        a->setP(a, en, 0);                      /* picked outright: clears what was counted */
        if (ticks > 1) {
            for (int k = 0; k < ticks - 1; k++) a->setP(a, en, a->getP(a, en) + tick);
            a->setP(a, en, a->getP(a, en) - tick);
            for (int k = 0; k < ticks - 1; k++) a->setP(a, en, a->getP(a, en) + tick);
            CHECK(a->getP(a, en) < 1e-3f, "a turn back starts the count over (%.3f)", a->getP(a, en));
        }
        if (n >= 3) {   /* a jump of half an option or more (automation, a drag) settles toward the move (settle()) */
            a->setP(a, en, 0);
            a->setP(a, en, (n - 1 - 0.3f) / (n - 1));
            CHECK(fabsf(a->getP(a, en) - 1.0f) < 1e-3f, "a large jump up lands on the option above (%.3f)", a->getP(a, en));
            a->setP(a, en, 0.6f / (n - 1));
            CHECK(a->getP(a, en) < 1e-3f, "a large jump down lands on the option below (%.3f)", a->getP(a, en));
            a->setP(a, en, 0);
        }
    }
    for (int i = 0; i < NPARAMS; i++) {   /* an integer with its own Q-Link rate: qlink_ticks events per step */
        const param_t *p = &PARAMS[i];
        if (p->nopts || !p->int_display || p->qlink_ticks <= 1 || p->max - p->min < 2) continue;
        float range = p->max - p->min, tick = 0.1f / range;
        char d0[256]; a->setP(a, i, 0); a->d(a, 7, i, 0, d0, 0);
        for (int k = 0; k < p->qlink_ticks - 1; k++) a->setP(a, i, a->getP(a, i) + tick);
        a->d(a, 7, i, 0, d, 0);
        CHECK(!strcmp(d, d0), "%s: %d ticks stay on \"%s\" (\"%s\")", p->key, p->qlink_ticks - 1, d0, d);
        a->setP(a, i, a->getP(a, i) + tick);
        CHECK(fabsf(a->getP(a, i) * range - 1) < 0.05f, "%s: tick %d reaches the next step (%.3f)", p->key, p->qlink_ticks, a->getP(a, i) * range);
        a->setP(a, i, 0.5f);
        CHECK(fabsf(a->getP(a, i) - 0.5f) <= 0.5f / range + 1e-3f, "%s: a direct set lands (%.3f)", p->key, a->getP(a, i));
        a->setP(a, i, PARAMS[i].def);
        break;
    }
    for (int i = 0; i < NPARAMS; i++) {   /* a long whole-number list (a bank list): nudge_pct makes each Q-Link event and wheel click one step */
        const param_t *p = &PARAMS[i];
        if (p->nopts || !p->int_display || p->nudge_pct <= 0 || p->max - p->min < 2) continue;
        float range = p->max - p->min, rate[2] = {1.0f / 128, 0.01f};   /* a Q-Link event and a data wheel click, of the whole range */
        const char *who[2] = {"Q-Link events", "data wheel clicks"};
        for (int r = 0; r < 2; r++) {
            a->setP(a, i, 0); int ok = 1;
            for (int k = 1; k <= 6; k++) {
                a->setP(a, i, a->getP(a, i) + rate[r]);
                if (fabsf(a->getP(a, i) * range - k) > 0.05f) ok = 0;
            }
            CHECK(ok, "%s: six %s step six, not %.0f at a time (%.2f)", p->key, who[r], range * rate[r], a->getP(a, i) * range);
            ok = 1;
            for (int k = 5; k >= 0; k--) {   /* and back down to the minimum, MPC clamping what it sends at 0 */
                float v = a->getP(a, i) - rate[r];
                a->setP(a, i, v < 0 ? 0 : v);
                if (fabsf(a->getP(a, i) * range - k) > 0.05f) ok = 0;
            }
            CHECK(ok, "%s: six %s step back down to the minimum (%.2f)", p->key, who[r], a->getP(a, i) * range);
        }
        a->setP(a, i, 0.5f);
        CHECK(fabsf(a->getP(a, i) - 0.5f) <= 0.5f / range + 1e-3f, "%s: a jump past the nudge range lands outright (%.3f)", p->key, a->getP(a, i));
        a->setP(a, i, 1.0f - 1.0f / 128);
        float below = roundf(a->getP(a, i) * range);
        a->setP(a, i, 1.0f);   /* clamped at the maximum from within the nudge range: one step up, not a jump to the end */
        CHECK(fabsf(a->getP(a, i) * range - (below + 1)) < 0.05f, "%s: at the top a clamped move is one step (%.2f from %.0f)", p->key, a->getP(a, i) * range, below);
        a->setP(a, i, p->def);
        break;
    }
    for (int i = 0; i < NPARAMS; i++)   /* the first whole-number param */
        if (!PARAMS[i].nopts && PARAMS[i].int_display && PARAMS[i].qlink_ticks <= 1 && PARAMS[i].max - PARAMS[i].min >= 2) { step_tests(a, i, "int", (int)(PARAMS[i].max - PARAMS[i].min)); break; }
    if (pop >= 0) {
        int t = PARAMS[pop].popup_of, n = PARAMS[t].nopts;
        a->setP(a, pop, 1); CHECK(a->getP(a, pop) > 0.5f, "popup %s opens", PARAMS[pop].key);
        a->setP(a, t, 0.5f / (n - 1)); run(a, 1);
        CHECK(a->getP(a, pop) > 0.5f && !automated[pop], "Q-Link nudge leaves it open");
        a->setP(a, t, 1.0f); run(a, 1);
        CHECK(a->getP(a, pop) < 0.5f && automated[pop] == 1, "a pick closes it and tells the host once");
        int pop2 = -1;
        for (int i = pop + 1; i < NPARAMS && pop2 < 0; i++) if (PARAMS[i].popup_of >= 0) pop2 = i;
        if (pop2 >= 0) {
            a->setP(a, pop, 1); a->setP(a, pop2, 1); run(a, 1);
            CHECK(a->getP(a, pop2) > 0.5f && a->getP(a, pop) < 0.5f, "opening a second popup closes the first (%s, %s)", PARAMS[pop].key, PARAMS[pop2].key);
            a->setP(a, pop2, 0); run(a, 1);
        }
    }

    ME m = {1, sizeof(ME), 0, 0, 0, 0, {0x90, 60, 100, 0}}; EV ev = {1, 0, {&m, 0}};
    a->d(a, 25, 0, 0, &ev, 0);
    int fx = a->ni >= 2;   /* effect: feed a 440 Hz sine and check it passes through; instrument: play note 60 */
    float L[128], R[128], I0[128], I1[128], *o[2] = {L, R}, *in[2] = {I0, I1}; double e = 0;
    for (int k = 0; k < 40; k++) {
        if (fx) for (int i = 0; i < 128; i++) I0[i] = I1[i] = 0.25f * sinf(2.0f * 3.14159265f * 440.0f * (k * 128 + i) / 44100.0f);
        a->pr(a, fx ? in : 0, o, 128);
        for (int i = 0; i < 128; i++) e += L[i] * L[i] + R[i] * R[i];
    }
    double rms = sqrt(e / (40 * 256));
    printf("%s %s -> rms %.4f\n", rms > 1e-5 ? "ok  " : "warn", fx ? "audio in" : "note 60", rms);   /* a silent patch may be legitimately 0 */

    if (a->ni >= 2) {   /* an effect called with no input buffers (a plugin scanner's probe) must not crash: the input is silence */
        float L0[128], R0[128], *o0[2] = {L0, R0};
        a->pr(a, 0, o0, 128); a->pr(a, 0, o0, 100);
        CHECK(1, "effect survives processReplacing with a NULL input");
    }
    {   /* instance b never got a note (nor audio): process() must add silence, leaving 1.0 */
        float L1[128], R1[128], Z0[128] = {0}, Z1[128] = {0}, *o1[2] = {L1, R1}, *zin[2] = {Z0, Z1}; int kept = 1;
        for (int i = 0; i < 128; i++) L1[i] = R1[i] = 1.0f;
        ((void (*)(AEffect *, float **, float **, int32_t))b->p)(b, b->ni >= 2 ? zin : 0, o1, 128);
        for (int i = 0; i < 128; i++) kept &= fabsf(L1[i] - 1.0f) < 0.01f && fabsf(R1[i] - 1.0f) < 0.01f;
        CHECK(kept, "process() accumulates into the output instead of overwriting it");
    }
#ifdef SAMPLE_PROBE
    sample_accurate_tests();
#endif
#if defined(HAS_TRANSPORT) && HAS_TRANSPORT
    transport_tests();
#endif
    param0_toggle_check();
    step_of_option_tests(a);
    void *ch = 0; intptr_t n = a->d(a, 23, 0, 0, &ch, 0);
    if (n > 0) {
        b->d(b, 24, 0, n, ch, 0);
        // int params: a keeps the unrounded knob position, b restores the rounded value, so allow half a step
        float ctol = cont >= 0 && PARAMS[cont].int_display ? 0.5f / (PARAMS[cont].max - PARAMS[cont].min) + 1e-3f : 1e-3f;
        if (cont >= 0) CHECK(fabsf(b->getP(b, cont) - a->getP(a, cont)) <= ctol, "chunk (%ld bytes) restores %s on instance b", (long)n, PARAMS[cont].key);
        if (pop >= 0) CHECK(!strstr((char *)ch, PARAMS[pop].key), "popup flag not saved in the chunk");
    } else printf("warn no chunk (engine has no \"state\" param)\n");

    program_tests(a);
    cc_tests(a);
    two_thread_tests(a);
    a->d(a, 1, 0, 0, 0, 0); b->d(b, 1, 0, 0, 0, 0);
    printf("%s\n", fails ? "FAILED" : "PASSED");
    return fails ? 1 : 0;
}
