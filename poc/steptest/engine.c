/* Test engine for the stepped-param checks in tools/host_test.c (settle() in wrapper/vst2_wrap.c): it keeps the five params the host sets,
 * and logs each "transport" value it is sent (HAS_TRANSPORT) as the "transport_log" readout. */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "../../wrapper/engine.h"

typedef struct { char mode[32], num[32], chan[32], cont[32], longl[32], tlog[32]; int push, push_raw; } st_t;

static void *create(const char *d) {
    (void)d;
    st_t *s = calloc(1, sizeof *s);
    strcpy(s->mode, "A"); strcpy(s->num, "1"); strcpy(s->chan, "1"); strcpy(s->cont, "0.0"); strcpy(s->longl, "0");
    return s;
}
static void destroy(void *i) { free(i); }
static void midi(void *i, const uint8_t *m, int n) { (void)i; (void)m; (void)n; }
static char *slot(st_t *s, const char *k) {
    return !strcmp(k, "mode") ? s->mode : !strcmp(k, "num") ? s->num : !strcmp(k, "chan") ? s->chan : !strcmp(k, "cont") ? s->cont : !strcmp(k, "long") ? s->longl : NULL;
}
static void set_param(void *i, const char *k, const char *v) {
    st_t *s = i;
    size_t l = strlen(s->tlog);
    if (!strcmp(k, "push") && v[0] != '0') { s->push++; return; }          /* presses that reached the engine: the wrapper's debounce_ms test */
    if (!strcmp(k, "push_raw") && v[0] != '0') { s->push_raw++; return; }
    if (!strcmp(k, "transport")) { if (l < sizeof s->tlog - 1) { s->tlog[l] = v[0]; s->tlog[l + 1] = 0; } return; }
    char *p = slot(i, k);
    if (p) snprintf(p, 32, "%s", v);
}
static int get_param(void *i, const char *k, char *b, int n) {
    if (!strcmp(k, "push_count")) return snprintf(b, n, "%d %d", ((st_t *)i)->push, ((st_t *)i)->push_raw);
    if (!strcmp(k, "transport_log")) return snprintf(b, n, "%s", ((st_t *)i)->tlog[0] ? ((st_t *)i)->tlog : "-");
    char *p = slot(i, k);
    return p ? snprintf(b, n, "%s", p) : 0;
}
static void render(void *i, int16_t *o, int f) { (void)i; memset(o, 0, (size_t)f * 4); }

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
