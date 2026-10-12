/* Test engine for HAS_SONG_POS (wrapper/engine.h song_pos, checked by tools/host_test.c): it keeps the last song_pos() call
 * and the number of calls, and reports them as the "pos_log" readout "ppq|bpm|playing|frames|calls". */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../wrapper/engine.h"

typedef struct { double ppq, bpm; int playing, frames, calls; } sp_t;

static void *create(const char *d) { (void)d; return calloc(1, sizeof(sp_t)); }
static void destroy(void *i) { free(i); }
static void midi(void *i, const uint8_t *m, int n) { (void)i; (void)m; (void)n; }
static void set_param(void *i, const char *k, const char *v) { (void)i; (void)k; (void)v; }
static int get_param(void *i, const char *k, char *b, int n) {
    sp_t *s = i;
    if (strcmp(k, "pos_log")) return 0;
    return snprintf(b, n, "%.3f|%.1f|%d|%d|%d", s->ppq, s->bpm, s->playing, s->frames, s->calls);
}
static void render(void *i, int16_t *o, int f) { (void)i; memset(o, 0, (size_t)f * 4); }
static void song_pos(void *i, double ppq, double bpm, int playing, int frames) {
    sp_t *s = i; s->ppq = ppq; s->bpm = bpm; s->playing = playing; s->frames = frames; s->calls++;
}

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL, song_pos };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
