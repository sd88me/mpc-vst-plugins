/* bench: CPU stress test for a VST2 .so, run on the MPC device itself (or on a PC for a relative number).
 *
 *   bench <plugin.so> [-s seconds-per-stage] [-v "1,4,8,16"] [-p] [-j]
 *
 * Plays the plugin like MPC does (44100 Hz, 128-frame blocks, host transport running) through stages:
 * idle, then held chords of N voices re-struck every half second, then a parameter sweep (Q-Link turns), then the
 * release tail. Each block is timed with the thread's own CPU clock, so time lost to MPC preempting us doesn't
 * count. The plugin's background threads are reported separately (process CPU minus this thread).
 * Output: per stage mean / p99 / max as a % of one block (2902 us), and a verdict (see docs/BENCH.md).
 *   -p  also sweep every parameter (setParameter storm)   -j  print one JSON line at the end
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct AEffect AEffect;
typedef intptr_t (*hostcb)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
struct AEffect {
    int32_t magic;
    intptr_t (*dispatcher)(AEffect *, int32_t, int32_t, intptr_t, void *, float);
    void *process;
    void (*setParameter)(AEffect *, int32_t, float);
    float (*getParameter)(AEffect *, int32_t);
    int32_t numPrograms, numParams, numInputs, numOutputs, flags;
    intptr_t r1, r2;
    int32_t initialDelay, rOld1, rOld2;
    float ioRatio;
    void *object, *user;
    int32_t uniqueID, version;
    void (*processReplacing)(AEffect *, float **, float **, int32_t);
    void *processDoubleReplacing;
    char future[56];
};
typedef struct {
    int32_t type, byteSize, deltaFrames, flags, noteLength, noteOffset;
    unsigned char midi[4];
    char detune, offVel, r1, r2;
} MidiEv;
typedef struct {
    int32_t num;
    intptr_t reserved;
    void *ev[64];
} Events;
typedef struct {
    double samplePos, sampleRate, nanoSeconds, ppqPos, tempo, barStartPos, cycleStart, cycleEnd;
    int32_t tsNum, tsDen, smpte, smpteRate, toNextClock, flags;
} TimeInfo;

enum { SR = 44100, BLOCK = 128 };
enum { effOpen = 0, effClose = 1, effSetSampleRate = 10, effSetBlockSize = 11, effMainsChanged = 12,
       effProcessEvents = 25, effStartProcess = 71, effStopProcess = 72 };
#define BUDGET_US (1e6 * BLOCK / SR)

static TimeInfo ti;
static intptr_t host(AEffect *e, int32_t op, int32_t i, intptr_t v, void *p, float o) {
    (void)e; (void)i; (void)v; (void)p; (void)o;
    switch (op) {
    case 1: return 2400;               /* audioMasterVersion */
    case 7: return (intptr_t)&ti;      /* audioMasterGetTime */
    case 16: return SR;                /* audioMasterGetSampleRate */
    case 17: return BLOCK;             /* audioMasterGetBlockSize */
    default: return 0;
    }
}

static double now_us(clockid_t c) {
    struct timespec t;
    clock_gettime(c, &t);
    return t.tv_sec * 1e6 + t.tv_nsec / 1e3;
}
static int cmpd(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return x < y ? -1 : x > y;
}

static AEffect *fx;
static float inL[BLOCK], inR[BLOCK], outL[BLOCK], outR[BLOCK];
static float *ins[2] = {inL, inR}, *outs[2] = {outL, outR};
static MidiEv mev[64];
static Events evs;
static int synth, sweep_all;
#define TRIGGER_WARN_PCT 90.0   /* a trigger tap that eats this much of a block is worth a WARN */
/* Parameters split by kind, once the plugin answers the framework's EFF_MPC_IS_MOMENTARY opcode: the
 * sweep only turns continuous controls, one-shot triggers get their own stage (2026-10-26). */
static int *sw_idx, sw_n, *tr_idx, tr_n, pending_release = -1;
static unsigned rng = 12345;
static float frand(void) { rng = rng * 1664525u + 1013904223u; return (rng >> 8) / 16777216.0f; }

static void send_notes(int on, int n, int base) {
    evs.num = 0;
    for (int k = 0; k < n && k < 64; k++) {
        MidiEv *m = &mev[k];
        memset(m, 0, sizeof *m);
        m->type = 1; m->byteSize = sizeof *m;
        m->midi[0] = on ? 0x90 : 0x80;
        m->midi[1] = (unsigned char)(base + (k * 7) % 36); /* spread over three octaves */
        m->midi[2] = on ? 100 : 0;
        evs.ev[evs.num++] = m;
    }
    fx->dispatcher(fx, effProcessEvents, 0, 0, &evs, 0);
}

typedef struct { const char *name; double mean, p99, max, bg; float peak; } Stage;

/* mode: 0 idle, 1 chords of `voices`, 2 param sweep while holding 8 voices, 3 release tail */
static Stage run(const char *name, int mode, int voices, double seconds) {
    int nblocks = (int)(seconds * SR / BLOCK);
    double *t = malloc(sizeof(double) * nblocks);
    int restrike = SR / 2 / BLOCK, held = 0;
    float peak = 0;
    double p0 = now_us(CLOCK_PROCESS_CPUTIME_ID), th0 = now_us(CLOCK_THREAD_CPUTIME_ID);
    for (int b = 0; b < nblocks; b++) {
        for (int i = 0; i < BLOCK; i++) { inL[i] = frand() * 0.5f - 0.25f; inR[i] = frand() * 0.5f - 0.25f; }
        double t0 = now_us(CLOCK_THREAD_CPUTIME_ID);
        if (synth && (mode == 1 || mode == 2) && b % restrike == 0) {
            if (held) send_notes(0, held, 36);
            held = mode == 1 ? voices : 8;
            send_notes(1, held, 36);
        }
        if (synth && mode == 3 && b == 0) send_notes(0, 16, 36);
        if (mode == 2 && sw_n > 0) {
            int n = sweep_all ? sw_n : 4;
            for (int k = 0; k < n && k < sw_n; k++) {
                int slot = sweep_all ? k : (int)(frand() * sw_n) % sw_n;
                fx->setParameter(fx, sw_idx[slot], frand());
            }
        }
        if (mode == 4) {
            /* one trigger every 8 blocks, released on the next one: a tap, not a drag */
            if (pending_release >= 0) { fx->setParameter(fx, pending_release, 0.0f); pending_release = -1; }
            else if (tr_n > 0 && b % 8 == 0) {
                int slot = (int)(b / 8) % tr_n;
                fx->setParameter(fx, tr_idx[slot], 1.0f);
                pending_release = tr_idx[slot];
            }
        }
        fx->processReplacing(fx, ins, outs, BLOCK);
        t[b] = now_us(CLOCK_THREAD_CPUTIME_ID) - t0;
        for (int i = 0; i < BLOCK; i++) {
            float a = fabsf(outL[i]) > fabsf(outR[i]) ? fabsf(outL[i]) : fabsf(outR[i]);
            if (a > peak) peak = a;
        }
        ti.samplePos += BLOCK;
        ti.ppqPos += BLOCK * ti.tempo / 60.0 / SR;
    }
    if (synth && held && mode != 3) send_notes(0, held, 36);
    double proc = now_us(CLOCK_PROCESS_CPUTIME_ID) - p0, self = now_us(CLOCK_THREAD_CPUTIME_ID) - th0;
    qsort(t, nblocks, sizeof(double), cmpd);
    double sum = 0;
    for (int b = 0; b < nblocks; b++) sum += t[b];
    Stage s = {name, sum / nblocks, t[(int)(nblocks * 0.99)], t[nblocks - 1],
               (proc - self) / (nblocks * BUDGET_US) * 100, peak};
    free(t);
    return s;
}

int main(int argc, char **argv) {
    const char *path = 0, *vlist = "1,4,8,16";
    double secs = 5;
    int json = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-s") && i + 1 < argc) secs = atof(argv[++i]);
        else if (!strcmp(argv[i], "-v") && i + 1 < argc) vlist = argv[++i];
        else if (!strcmp(argv[i], "-p")) sweep_all = 1;
        else if (!strcmp(argv[i], "-j")) json = 1;
        else path = argv[i];
    }
    if (!path) { fprintf(stderr, "usage: bench <plugin.so> [-s secs] [-v 1,4,8,16] [-p] [-j]\n"); return 2; }
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    AEffect *(*entry)(hostcb) = (AEffect * (*)(hostcb)) dlsym(h, "VSTPluginMain");
    if (!entry) entry = (AEffect * (*)(hostcb)) dlsym(h, "main");
    if (!entry) { fprintf(stderr, "no VSTPluginMain\n"); return 1; }

    ti.sampleRate = SR; ti.tempo = 120; ti.tsNum = 4; ti.tsDen = 4;
    ti.flags = 2 | 1 << 9 | 1 << 10 | 1 << 13; /* playing, ppq, tempo, time signature valid */
    double o0 = now_us(CLOCK_MONOTONIC);
    fx = entry(host);
    if (!fx || fx->magic != 0x56737450) { fprintf(stderr, "bad AEffect\n"); return 1; }
    fx->dispatcher(fx, effOpen, 0, 0, 0, 0);
    fx->dispatcher(fx, effSetSampleRate, 0, 0, 0, SR);
    fx->dispatcher(fx, effSetBlockSize, 0, BLOCK, 0, 0);
    fx->dispatcher(fx, effMainsChanged, 0, 1, 0, 0);
    fx->dispatcher(fx, effStartProcess, 0, 0, 0, 0);
    double open_ms = (now_us(CLOCK_MONOTONIC) - o0) / 1e3;
    synth = (fx->flags & (1 << 8)) != 0;

    /* Ask which parameters are one-shot triggers; a plugin built before the opcode answers 0 for every
     * index, and the sweep then covers all parameters as it always did. */
    {
        int np = fx->numParams > 0 ? fx->numParams : 1;
        sw_idx = calloc((size_t)np, sizeof *sw_idx);
        tr_idx = calloc((size_t)np, sizeof *tr_idx);
        for (int i = 0; i < fx->numParams; i++) {
            if (fx->dispatcher(fx, 0x7F01, i, 0, 0, 0) == 1) tr_idx[tr_n++] = i;
            else sw_idx[sw_n++] = i;
        }
    }

    printf("plugin %s: %s, %d params, open %.1f ms; block %d @ %d Hz = %.0f us budget\n", path,
           synth ? "instrument" : "effect", fx->numParams, open_ms, BLOCK, SR, BUDGET_US);
    Stage st[16];
    int ns = 0;
    st[ns++] = run("idle", 0, 0, secs);
    if (synth) {
        char buf[64], *save = 0;
        strncpy(buf, vlist, sizeof buf - 1);
        for (char *v = strtok_r(buf, ",", &save); v && ns < 12; v = strtok_r(0, ",", &save)) {
            static char names[12][24];
            snprintf(names[ns], sizeof names[ns], "%s voices", v);
            st[ns] = run(names[ns], 1, atoi(v), secs);
            ns++;
        }
    } else {
        st[ns++] = run("audio in", 1, 0, secs);
    }
    if (tr_n > 0) printf("  %d one-shot trigger(s) excluded from the sweep, fired in their own stage\n", tr_n);
    st[ns++] = run(sweep_all ? "all-param sweep" : "q-link sweep", 2, 0, secs);
    st[ns++] = run("release tail", 3, 0, secs);
    const int ncont = ns;   /* stages above decide the verdict; triggers are reported, not scored */
    if (tr_n > 0) st[ns++] = run("trigger fire", 4, 0, secs);

    printf("%-16s %8s %8s %8s %9s %7s\n", "stage", "mean%", "p99%", "max%", "threads%", "peak");
    double worst99 = 0, worstmax = 0, bg = 0;
    for (int i = 0; i < ns; i++) {
        Stage *s = &st[i];
        printf("%-16s %8.1f %8.1f %8.1f %9.1f %7.2f\n", s->name, s->mean / BUDGET_US * 100, s->p99 / BUDGET_US * 100,
               s->max / BUDGET_US * 100, s->bg, s->peak);
        if (i < ncont && s->p99 > worst99) worst99 = s->p99;
        if (i < ncont && s->max > worstmax) worstmax = s->max;
        if (s->bg > bg) bg = s->bg;
    }
    double w99 = worst99 / BUDGET_US * 100, wmax = worstmax / BUDGET_US * 100;
    /* thresholds: see docs/BENCH.md */
    const char *verdict = w99 <= 15 && wmax <= 50 ? "PASS" : w99 <= 35 && wmax <= 80 ? "WARN" : "FAIL";
    /* A one-shot trigger is not a drag, so it does not decide the verdict like one (see docs/BENCH.md). It is
     * still real audio-thread work: a tap that eats most of a block glitches the next one, so PASS turns into
     * WARN above TRIGGER_WARN_PCT. */
    const double trmax = tr_n > 0 ? st[ncont].max / BUDGET_US * 100 : 0.0;
    if (tr_n > 0 && trmax >= TRIGGER_WARN_PCT && strcmp(verdict, "FAIL") != 0) verdict = "WARN";
    printf("worst p99 %.1f%%, worst block %.1f%%, background threads up to %.1f%% of a core", w99, wmax, bg);
    if (tr_n > 0) printf(", trigger max %.1f%% of a block", trmax);
    printf(" -> %s\n", verdict);
    if (json) {
        printf("{\"plugin\":\"%s\",\"instrument\":%d,\"open_ms\":%.1f,\"p99_pct\":%.1f,\"max_pct\":%.1f,"
               "\"threads_pct\":%.1f,\"verdict\":\"%s\"",
               path, synth, open_ms, w99, wmax, bg, verdict);
        if (tr_n > 0) printf(",\"triggers\":%d,\"trigger_max_pct\":%.1f", tr_n, st[ns - 1].max / BUDGET_US * 100);
        printf("}\n");
    }
    fx->dispatcher(fx, effStopProcess, 0, 0, 0, 0);
    fx->dispatcher(fx, effMainsChanged, 0, 0, 0, 0);
    fx->dispatcher(fx, effClose, 0, 0, 0, 0);
    free(sw_idx);
    free(tr_idx);
    return verdict[0] == 'F';
}
