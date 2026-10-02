/* Engine for the UI probe (poc/uiprobe, layout.conf says what each part tests). Everything moves on its own from the
 * audio thread's sample count: the phase every 2 s, the meter every block, the rows every 1.5 s and the 40 dense values
 * every 0.5 s. "display_rev" changes with every tick so the wrapper (HAS_DISPLAY_REV) refreshes text and reports the
 * changed values. Silent. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../wrapper/engine.h"

typedef struct {
    long samples, ticks;
    int running, taps;
    unsigned rev;
} st_t;

static const char *PHASES[] = {"idle", "preparing", "ready", "error"};
static const char *NAMES[] = {"Acid", "Crate Digger", "Dexed (DX7)", "JV-880", "Maze Voice", "MPC Plaits", "NAM"};

static void *create(const char *d) { (void)d; st_t *s = calloc(1, sizeof *s); if (s) s->running = 1; return s; }
static void destroy(void *i) { free(i); }
static void midi(void *i, const uint8_t *m, int n) { (void)i, (void)m, (void)n; }

static void set_param(void *inst, const char *key, const char *val) {
    st_t *s = inst;
    if (!strcmp(key, "run")) { s->running = atoi(val) != 0; s->rev++; }
    else if (!strcmp(key, "tap") && atof(val) > 0.5) { s->taps++; s->rev++; }
}

static int get_param(void *inst, const char *key, char *b, int n) {
    st_t *s = inst;
    long t = s->ticks;   /* one tick = 0.5 s */
    if (!strcmp(key, "display_rev")) return snprintf(b, n, "%u", s->rev);
    if (!strcmp(key, "long_ruler"))
        return snprintf(b, n, "....5...10...15...20...25...30...35...40...45...50...55...60...65...70...75...80");
    if (!strcmp(key, "long_sentence"))
        return snprintf(b, n, "Crate Digger: download failed after 3 retries. Nothing changed. tick %ld, taps %d", t, s->taps);
    if (!strcmp(key, "phase")) return snprintf(b, n, "%ld", (t / 4) % 4);
    if (!strcmp(key, "phase_text")) return snprintf(b, n, "phase %s (tick %ld)", PHASES[(t / 4) % 4], t);
    if (!strcmp(key, "progress")) return snprintf(b, n, "%.4f", (double)(s->samples % 88200) / 88200.0);
    if (!strcmp(key, "run")) return snprintf(b, n, "%d", s->running);
    if (!strcmp(key, "tap")) return snprintf(b, n, "0");
    if (key[0] == 'r' && key[1] >= '1' && key[1] <= '3' && key[2] == '_') {
        int r = key[1] - '1';
        long k = t / 3 + r * 2;   /* rows change every 1.5 s, out of step with each other */
        const char *f = key + 3;
        if (!strcmp(f, "state")) return snprintf(b, n, "%ld", k % 6);
        if (!strcmp(f, "tested")) return snprintf(b, n, "%ld", k % 2);
        if (!strcmp(f, "cpu")) return snprintf(b, n, "%ld", (k / 2) % 2);
        if (!strcmp(f, "name")) return snprintf(b, n, "%s", NAMES[k % 7]);
        if (!strcmp(f, "meta")) return snprintf(b, n, "v1.0.%ld  ·  synth  ·  eurorack  ·  sha %06lx", k % 10, (k * 2654435761u) & 0xffffff);
    }
    if (key[0] == 'd' && key[1] >= '0' && key[1] <= '9') return snprintf(b, n, "%ld", (t + atoi(key + 1)) % 3);
    return 0;
}

static void render(void *inst, int16_t *out, int frames) {
    st_t *s = inst;
    memset(out, 0, sizeof(int16_t) * 2 * frames);
    if (!s->running) return;
    s->samples += frames;
    long t = s->samples / 22050;
    s->ticks = t;
    s->rev++;   /* every block: the meter moves continuously; the wrapper polls at most every 0.1 s */
}

static const mpc_engine_t ENGINE = {create, destroy, midi, set_param, get_param, render, NULL};
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
