/* Test engine for SAMPLE_ACCURATE (wrapper/vst2_wrap.c, tools/host_test.c "SAMPLE_PROBE"): a note-on switches a constant
 * level on from the very next rendered frame, a note-off switches it off, so the first non-zero output frame is where the
 * wrapper applied the event. render() records whether it was ever called with a frame count outside 1..128. */
#include <stdlib.h>
#include <string.h>
#include "../../wrapper/engine.h"

int sampleprobe_bad;   /* render() calls with frames < 1 or > 128 */

typedef struct { int16_t level; } state_t;

static void *create(const char *data_dir) { (void)data_dir; return calloc(1, sizeof(state_t)); }
static void destroy(void *inst) { free(inst); }
static void midi(void *inst, const uint8_t *msg, int len) {
    state_t *s = inst;
    if (len < 3) return;
    if ((msg[0] & 0xf0) == 0x90 && msg[2]) s->level = 8192;
    else if ((msg[0] & 0xf0) == 0x80 || (msg[0] & 0xf0) == 0x90) s->level = 0;
}
static void set_param(void *inst, const char *key, const char *val) { (void)inst; (void)key; (void)val; }
static int get_param(void *inst, const char *key, char *buf, int buf_len) { (void)inst; (void)key; (void)buf; (void)buf_len; return 0; }
static void render(void *inst, int16_t *out_lr, int frames) {
    state_t *s = inst;
    if (frames < 1 || frames > 128) { sampleprobe_bad++; return; }
    for (int i = 0; i < frames; i++) out_lr[2 * i] = out_lr[2 * i + 1] = s->level;
}

static const mpc_engine_t ENGINE = { create, destroy, midi, set_param, get_param, render, NULL };
const mpc_engine_t *mpc_engine(void) { return &ENGINE; }
