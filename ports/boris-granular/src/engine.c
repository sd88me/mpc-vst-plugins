/* Boris Granular (Schwung audio_fx_api_v2, src/dsp/granular.c) -> mpc_engine_t (wrapper/engine.h).
 * Same contract as Schwung (44.1 kHz, interleaved int16 stereo, 128-frame blocks); the DSP filters in place,
 * so process() copies the host's input into the output block first. Host tempo arrives as "lfo_bpm"
 * (HAS_LFO_BPM in vst.json) and drives Sync in place of MIDI clock (BORIS_VST patch, src/VENDORED.md). */
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "engine.h"

typedef struct {
    uint32_t api_version;
    void *(*create_instance)(const char *module_dir, const char *config_json);
    void (*destroy_instance)(void *instance);
    void (*process_block)(void *instance, int16_t *audio_inout, int frames);
    void (*set_param)(void *instance, const char *key, const char *val);
    int (*get_param)(void *instance, const char *key, char *buf, int buf_len);
    void (*on_midi)(void *instance, const uint8_t *msg, int len, int source);
} audio_fx_api_v2_t;
extern audio_fx_api_v2_t *move_audio_fx_init_v2(const void *host);

static audio_fx_api_v2_t *api;

static void *create(const char *dir) { return api->create_instance(dir ? dir : "", NULL); }
static void destroy(void *i) { api->destroy_instance(i); }
static void midi(void *i, const uint8_t *m, int n) { if (api->on_midi) api->on_midi(i, m, n, 2); }
static void set_param(void *i, const char *k, const char *v) { api->set_param(i, k, v); }
/* Division labels ("1/16".."4/1") start with a digit, which the wrapper reads as an option index: report the index. */
static const char *const divisions[] = { "1/16", "1/8", "1/4", "1/2", "1/1", "2/1", "4/1" };
static int get_param(void *i, const char *k, char *b, int n) {
    int r = api->get_param(i, k, b, n);
    if (r > 0 && !strcmp(k, "division"))
        for (int d = 0; d < (int)(sizeof divisions / sizeof *divisions); d++)
            if (!strcmp(b, divisions[d])) return snprintf(b, n, "%d", d);
    return r;
}
static void render(void *i, int16_t *out, int frames) { memset(out, 0, sizeof(int16_t) * 2 * frames); }
static void process(void *i, const int16_t *in, int16_t *out, int frames) {
    memcpy(out, in, sizeof(int16_t) * 2 * frames);
    api->process_block(i, out, frames);
}

static const mpc_engine_t engine = { create, destroy, midi, set_param, get_param, render, process };

const mpc_engine_t *mpc_engine(void) {
    if (!api) api = move_audio_fx_init_v2(NULL);
    return api ? &engine : NULL;
}
