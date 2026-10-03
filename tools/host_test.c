/* Offline x86 host test for a port built on wrapper/vst2_wrap.c: link it with the wrapper, the engine
 * (and its adapter) and the port's generated params.h -- tools/test_port.sh does all that -- and run
 * under ASan. Checks two independent instances, names/display for every param, a set/get round
 * trip, option selection, popup open/close, note -> audio, and chunk save/restore. Exit 1 on failure. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
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
static intptr_t host(AEffect*e,int32_t op,int32_t i,intptr_t v,void*p,float o){
    static double ti[16];
    if (op == 0 && i >= 0 && i < NPARAMS) automated[i]++;
    if (op == 7) { ti[4] = 120.0; ((int32_t*)&ti[8])[5] = 1 << 10; return (intptr_t)ti; }
    return 0;
}
#define CHECK(c, ...) do { printf("%s ", (c) ? "ok  " : "FAIL"); printf(__VA_ARGS__); printf("\n"); if (!(c)) fails++; } while (0)
static void run(AEffect *a, int blocks) { float L[128], R[128], *o[2] = {L, R}; for (int k = 0; k < blocks; k++) a->pr(a, 0, o, 128); }

#ifdef SAMPLE_PROBE   /* poc/sampleprobe: a note-on switches a constant level on from the next frame it renders */
extern int sampleprobe_bad;
static int first_nonzero(const float *L, int n) { for (int i = 0; i < n; i++) if (L[i] != 0) return i; return -1; }
static int last_nonzero(const float *L, int n) { for (int i = n - 1; i >= 0; i--) if (L[i] != 0) return i; return -1; }
static void send(AEffect *c, int d1, int s1, int d2, int s2, int two) {   /* up to two events, in the order given */
    ME m1 = {1, sizeof(ME), d1, 0, 0, 0, {(unsigned char)s1, 60, 100, 0}}, m2 = {1, sizeof(ME), d2, 0, 0, 0, {(unsigned char)s2, 60, 100, 0}};
    EV ev = {two ? 2 : 1, 0, {&m1, &m2}};
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
        a->setP(a, en, (n - 1.5f) / (n - 1));   /* a Q-Link nudge down from the last option: one step */
        CHECK(fabsf(a->getP(a, en) - (float)(n - 2) / (n - 1)) < 1e-3f, "nudge steps one option (%.3f)", a->getP(a, en));
    }
    if (pop >= 0) {
        int t = PARAMS[pop].popup_of, n = PARAMS[t].nopts;
        a->setP(a, pop, 1); CHECK(a->getP(a, pop) > 0.5f, "popup %s opens", PARAMS[pop].key);
        a->setP(a, t, 0.5f / (n - 1)); run(a, 1);
        CHECK(a->getP(a, pop) > 0.5f && !automated[pop], "Q-Link nudge leaves it open");
        a->setP(a, t, 1.0f); run(a, 1);
        CHECK(a->getP(a, pop) < 0.5f && automated[pop] == 1, "a pick closes it and tells the host once");
    }

    ME m = {1, sizeof(ME), 0, 0, 0, 0, {0x90, 60, 100, 0}}; EV ev = {1, 0, {&m, 0}};
    a->d(a, 25, 0, 0, &ev, 0);
    float L[128], R[128], *o[2] = {L, R}; double e = 0;
    for (int k = 0; k < 40; k++) { a->pr(a, 0, o, 128); for (int i = 0; i < 128; i++) e += L[i] * L[i] + R[i] * R[i]; }
    double rms = sqrt(e / (40 * 256));
    printf("%s note 60 -> rms %.4f\n", rms > 1e-5 ? "ok  " : "warn", rms);   /* an effect or a silent patch may be legitimately 0 */

    {   /* instance b never got a note: the legacy process() must add silence, leaving 1.0 */
        float L1[128], R1[128], *o1[2] = {L1, R1}; int kept = 1;
        for (int i = 0; i < 128; i++) L1[i] = R1[i] = 1.0f;
        ((void (*)(AEffect *, float **, float **, int32_t))b->p)(b, 0, o1, 128);
        for (int i = 0; i < 128; i++) kept &= fabsf(L1[i] - 1.0f) < 0.01f && fabsf(R1[i] - 1.0f) < 0.01f;
        CHECK(kept, "process() accumulates into the output instead of overwriting it");
    }
#ifdef SAMPLE_PROBE
    sample_accurate_tests();
#endif
    void *ch = 0; intptr_t n = a->d(a, 23, 0, 0, &ch, 0);
    if (n > 0) {
        b->d(b, 24, 0, n, ch, 0);
        // int params: a keeps the unrounded knob position, b restores the rounded value, so allow half a step
        float ctol = cont >= 0 && PARAMS[cont].int_display ? 0.5f / (PARAMS[cont].max - PARAMS[cont].min) + 1e-3f : 1e-3f;
        if (cont >= 0) CHECK(fabsf(b->getP(b, cont) - a->getP(a, cont)) <= ctol, "chunk (%ld bytes) restores %s on instance b", (long)n, PARAMS[cont].key);
        if (pop >= 0) CHECK(!strstr((char *)ch, PARAMS[pop].key), "popup flag not saved in the chunk");
    } else printf("warn no chunk (engine has no \"state\" param)\n");

    a->d(a, 1, 0, 0, 0, 0); b->d(b, 1, 0, 0, 0, 0);
    printf("%s\n", fails ? "FAILED" : "PASSED");
    return fails ? 1 : 0;
}
