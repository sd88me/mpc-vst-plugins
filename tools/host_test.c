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
    void *ch = 0; intptr_t n = a->d(a, 23, 0, 0, &ch, 0);
    if (n > 0) {
        b->d(b, 24, 0, n, ch, 0);
        if (cont >= 0) CHECK(fabsf(b->getP(b, cont) - a->getP(a, cont)) <= 1.0f / (PARAMS[cont].max - PARAMS[cont].min) + 1e-3f, "chunk (%ld bytes) restores %s on instance b", (long)n, PARAMS[cont].key);
        if (pop >= 0) CHECK(!strstr((char *)ch, PARAMS[pop].key), "popup flag not saved in the chunk");
    } else printf("warn no chunk (engine has no \"state\" param)\n");

    a->d(a, 1, 0, 0, 0, 0); b->d(b, 1, 0, 0, 0, 0);
    printf("%s\n", fails ? "FAILED" : "PASSED");
    return fails ? 1 : 0;
}
