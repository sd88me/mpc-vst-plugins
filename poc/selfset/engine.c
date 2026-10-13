/* Test engine for mpc_engine_changed (wrapper/engine.h, checked by tools/host_test.c): MIDI it is sent moves its own
 * params, as an engine reading an ALSA port of its own would: CC 1 sets "level" (0-127 -> 0-100), CC 2 "shape" (by
 * thirds), and each change is reported once through mpc_engine_changed(). It never sets "plain" itself. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../../wrapper/engine.h"

static const char *SHAPES[] = {"Sine", "Saw", "Square"};
typedef struct { char level[32], shape[32], plain[32]; unsigned changed; } ss_t;   /* changed: bit 0 level, bit 1 shape */

static void *create(const char *d) {
    (void)d;
    ss_t *s = calloc(1, sizeof *s);
    strcpy(s->level, "0.0"); strcpy(s->shape, "Sine"); strcpy(s->plain, "0.0");
    return s;
}
static void destroy(void *i) { free(i); }
static void midi(void *i, const uint8_t *m, int n) {
    ss_t *s = i;
    if (n < 3 || (m[0] & 0xF0) != 0xB0) return;
    if (m[1] == 1) { snprintf(s->level, sizeof s->level, "%.2f", m[2] * 100.0f / 127.0f); s->changed |= 1; }
    if (m[1] == 2) { snprintf(s->shape, sizeof s->shape, "%s", SHAPES[m[2] * 3 / 128]); s->changed |= 2; }
}
static char *slot(ss_t *s, const char *k) {
    return !strcmp(k, "level") ? s->level : !strcmp(k, "shape") ? s->shape : !strcmp(k, "plain") ? s->plain : NULL;
}
static void set_param(void *i, const char *k, const char *v) {
    char *p = slot(i, k);
    if (p) snprintf(p, 32, "%s", v);
}
static int get_param(void *i, const char *k, char *b, int n) {
    char *p = slot(i, k);
    return p ? snprintf(b, n, "%s", p) : 0;
}
static void render(void *i, int16_t *o, int f) { (void)i; memset(o, 0, (size_t)f * 4); }

int mpc_engine_changed(void *inst, char *key, int len) {
    ss_t *s = inst;
    if (!s->changed) return 0;
    int b = s->changed & 1 ? 0 : 1;
    s->changed &= ~(1u << b);
    snprintf(key, len, "%s", b ? "shape" : "level");
    return 1;
}

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
