/* Poll test engine for tools/host_test.c (POLL_PROBE): 40 text readouts t01-t40 whose get_param() calls are counted per param,
 * t02 also answers t02_on (a list tile's lit flag), the others do not. The layout shows t01-t30 only. */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "../../wrapper/engine.h"

volatile long polltest_hits[41];     /* get_param("tNN") calls */
volatile long polltest_on_gets;      /* get_param("t02_on") calls */
volatile int polltest_gen[41];       /* bump one to change that readout's text */
volatile int polltest_on;            /* t02_on */

static void *create(const char *d) { (void)d; return calloc(1, 1); }
static void destroy(void *i) { free(i); }
static void midi(void *i, const uint8_t *m, int n) { (void)i; (void)m; (void)n; }
static void set_param(void *i, const char *k, const char *v) { (void)i; (void)k; (void)v; }
static int get_param(void *i, const char *k, char *b, int n) {
    (void)i;
    int t;
    if (!strcmp(k, "t02_on")) { polltest_on_gets++; return snprintf(b, n, "%d", polltest_on); }
    if (sscanf(k, "t%d", &t) == 1 && !strchr(k, '_') && t >= 1 && t <= 40) { polltest_hits[t]++; return snprintf(b, n, "v%d", polltest_gen[t]); }
    return 0;
}
static void render(void *i, int16_t *o, int f) { (void)i; memset(o, 0, (size_t)f * 4); }

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
