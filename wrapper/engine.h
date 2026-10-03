/* The engine interface vst2_wrap.c drives: any synth/effect core that provides mpc_engine().
 * Contract: 44100 Hz, interleaved int16 stereo, rendered in 128-frame blocks. Parameters are
 * string key/value pairs; the keys and their ranges come from the port's generated params.h.
 * An engine written for another host plugs in through a small adapter (see adapters/). */
#pragma once
#include <stdint.h>

typedef struct {
    void *(*create)(const char *data_dir);    /* data_dir: MODULE_DIR define, or NULL */
    void (*destroy)(void *inst);
    void (*midi)(void *inst, const uint8_t *msg, int len);
    void (*set_param)(void *inst, const char *key, const char *val);
    int (*get_param)(void *inst, const char *key, char *buf, int buf_len);   /* > 0 on success */
    void (*render)(void *inst, int16_t *out_lr, int frames);
    /* Effects only (a port built with "effect": true in vst.json): filter one block of the host's audio, same format as
     * render (interleaved int16 stereo, 128 frames); in_lr may not alias out_lr. NULL for synths (add it last: engines
     * initialise this struct positionally).
 * A port that sets "defines": {"SAMPLE_ACCURATE": 1} in vst.json (instruments only) has render() called with any
 * frame count from 1 to 128, so MIDI can start at its in-block position: the engine must not assume 128. */
    void (*process)(void *inst, const int16_t *in_lr, int16_t *out_lr, int frames);
} mpc_engine_t;

const mpc_engine_t *mpc_engine(void);
