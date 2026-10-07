/*
 * Boris Granular - Real-time granular audio FX
 *
 * Ported from Boris Granular Station (RNBO/JUCE/C++) to Move audio_fx_api_v2.
 * Captures live audio into a circular buffer, spawns overlapping grains with
 * per-grain randomization of position, pitch, direction, volume, and panning.
 *
 * V2 API only - instance-based for multi-instance support.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>

#include "audio_fx_api_v1.h"

/* ============================================================================
 * CONSTANTS
 * ============================================================================ */

#define SAMPLE_RATE     44100
#define BUFFER_SECONDS  10
#define BUFFER_SIZE     (SAMPLE_RATE * BUFFER_SECONDS)  /* 441000 mono samples */
#define MAX_VOICES      24
#define ENV_TABLE_SIZE  1024
#define RAMP_SAMPLES    2205   /* ~50ms smoothing */
#define CLOCKS_PER_QUARTER 24  /* MIDI standard: 24 PPQN */

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ============================================================================
 * SMOOTHED VALUE - Click-free parameter changes
 * ============================================================================ */

typedef struct {
    float current;
    float target;
    float step;
    int remaining;
} SmoothedValue;

static void sv_init(SmoothedValue *sv, float val) {
    sv->current = val;
    sv->target = val;
    sv->step = 0.0f;
    sv->remaining = 0;
}

static void sv_set(SmoothedValue *sv, float target, int ramp) {
    sv->target = target;
    if (ramp > 0) {
        sv->step = (target - sv->current) / (float)ramp;
        sv->remaining = ramp;
    } else {
        sv->current = target;
        sv->step = 0.0f;
        sv->remaining = 0;
    }
}

static inline float sv_next(SmoothedValue *sv) {
    if (sv->remaining > 0) {
        sv->current += sv->step;
        sv->remaining--;
        if (sv->remaining == 0)
            sv->current = sv->target;
    }
    return sv->current;
}

/* ============================================================================
 * PSEUDO-RANDOM NUMBER GENERATOR (xorshift32)
 * ============================================================================ */

static inline uint32_t xorshift32(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

/* Returns 0.0 - 1.0 */
static inline float rand01(uint32_t *state) {
    return (float)(xorshift32(state) & 0x7FFFFFFF) / (float)0x7FFFFFFF;
}

/* ============================================================================
 * GRAIN VOICE
 * ============================================================================ */

typedef struct {
    int active;
    float env_phase;          /* 0-1 progress through envelope */
    float play_pos;           /* fractional read position in buffer */
    float play_inc;           /* per-sample increment (speed * direction) */
    float grain_len_samps;    /* grain duration in samples (at original speed) */
    float total_samps;        /* actual playback samples = len / |pitch| */
    float volume;             /* per-grain volume */
    float pan;                /* per-grain pan (0=L, 1=R) */
    int samples_played;
} grain_voice_t;

/* ============================================================================
 * TEMPO SYNC - Musical divisions
 * ============================================================================ */

enum {
    DIV_1_16 = 0,
    DIV_1_8,
    DIV_1_4,
    DIV_1_2,
    DIV_1_1,
    DIV_2_1,
    DIV_4_1,
    DIV_COUNT
};

static const char *division_names[] = {
    "1/16", "1/8", "1/4", "1/2", "1/1", "2/1", "4/1"
};

/* Quarter notes per division */
static const float division_quarters[] = {
    0.25f,   /* 1/16 */
    0.5f,    /* 1/8  */
    1.0f,    /* 1/4  */
    2.0f,    /* 1/2  */
    4.0f,    /* 1/1  */
    8.0f,    /* 2/1  */
    16.0f    /* 4/1  */
};

static const char *rhythm_names[] = { "normal", "dotted", "triplet" };
static const char *envelope_names[] = { "hann", "triangle", "trapezoid" };

static float parse_envelope_float(const char *val) {
    if (strcmp(val, "hann") == 0) return 0.0f;
    if (strcmp(val, "triangle") == 0) return 0.5f;
    if (strcmp(val, "trapezoid") == 0) return 1.0f;
    char *endptr;
    float v = (float)strtod(val, &endptr);
    if (endptr != val) {
        if (v < 0.0f) v = 0.0f;
        if (v > 1.0f) v = 1.0f;
        return v;
    }
    return 0.0f;
}

static int parse_division(const char *val) {
    for (int i = 0; i < DIV_COUNT; i++) {
        if (strcmp(val, division_names[i]) == 0) return i;
    }
    char *endptr;
    long idx = strtol(val, &endptr, 10);
    if (endptr != val && *endptr == '\0') {
        if (idx < 0) idx = 0;
        if (idx >= DIV_COUNT) idx = DIV_COUNT - 1;
        return (int)idx;
    }
    return DIV_1_4;
}

static int parse_rhythm(const char *val) {
    for (int i = 0; i < 3; i++) {
        if (strcmp(val, rhythm_names[i]) == 0) return i;
    }
    char *endptr;
    long idx = strtol(val, &endptr, 10);
    if (endptr != val && *endptr == '\0') {
        if (idx < 0) idx = 0;
        if (idx > 2) idx = 2;
        return (int)idx;
    }
    return 0;
}

/* Compute trigger frequency in Hz from BPM, division, and rhythm */
static float compute_sync_freq(int bpm, int division, int rhythm) {
    if (division < 0 || division >= DIV_COUNT) return 0.0f;
    float quarters = division_quarters[division];

    /* Apply rhythm modifier */
    switch (rhythm) {
    case 1: quarters *= 1.5f;      break;  /* dotted */
    case 2: quarters *= (2.0f/3.0f); break;  /* triplet */
    default: break;
    }

    float beat_sec = 60.0f / (float)bpm;
    float period = quarters * beat_sec;
    return (period > 0.0f) ? 1.0f / period : 0.0f;
}

/* ============================================================================
 * INSTANCE
 * ============================================================================ */

typedef struct {
    /* Circular recording buffer (mono) */
    float *buffer;
    int write_pos;

    /* Grain voices */
    grain_voice_t voices[MAX_VOICES];

    /* Envelope tables (pre-computed) */
    float env_hann[ENV_TABLE_SIZE];
    float env_triangle[ENV_TABLE_SIZE];
    float env_trapezoid[ENV_TABLE_SIZE];

    /* Trigger state */
    float trigger_phase;       /* Free-running phasor 0-1 */
    float sync_phase;          /* For tempo-synced edge detection */

    /* Feedback state */
    float fb_l, fb_r;

    /* DC blocker state (stereo) */
    float dc_xm1_l, dc_ym1_l;
    float dc_xm1_r, dc_ym1_r;

    /* PRNG state */
    uint32_t rng_state;

    /* MIDI clock (from space-delay pattern) */
    int clock_sample_counter;
    int clock_tick_count;
    int clock_running;
    int detected_bpm;

    /* Smoothed values for key params */
    SmoothedValue sm_grain_size;
    SmoothedValue sm_position;
    SmoothedValue sm_pitch;
    SmoothedValue sm_density;
    SmoothedValue sm_drift;
    SmoothedValue sm_feedback;
    SmoothedValue sm_mix;
    SmoothedValue sm_gain;
    SmoothedValue sm_envelope;

    /* === Parameters === */
    float grain_size;     /* ms (20-2000) */
    float position;       /* 0-1 */
    float pitch;          /* ratio (0.25-4.0) */
    float density;        /* 0.04-1.0 */
    float drift;          /* 0-1 */
    float feedback;       /* 0-90 (percent) */
    float mix;            /* 0-100 (dry/wet percent) */
    float gain;           /* 0-1.5 */
    float chance;         /* 0-100 (percent) */
    float reverse_prob;   /* 0-100 (percent) */
    float pan_width;      /* 0-100 (percent) */
    float random_vol;     /* 0-100 (percent) */
    float random_pitch;   /* 0-100 (percent) */
    float random_length;  /* 0-100 (percent) */
    float random_delay;   /* 0-100 (percent) */
    float envelope;       /* 0.0=Hann, 0.5=Triangle, 1.0=Trapezoid (continuous morph) */
    int freeze;           /* 0/1 */
    int mute;             /* 0/1 */
    int sync;             /* 0/1 */
    int division;         /* 0-6 */
    int rhythm;           /* 0=normal, 1=dotted, 2=triplet */
    int voice_count;      /* 1-24 */
    int current_page;     /* 0=Granular, 1=Randomize, 2=Sync, 3=Advanced */
} granular_instance_t;

/* ============================================================================
 * KNOB DISPLAY - Maps knob positions to param keys and display names per page
 * ============================================================================ */

typedef struct {
    const char *key;
    const char *label;
} knob_map_entry_t;

/* Knobs per page (up to 8 knobs per page) */
static const knob_map_entry_t page_knobs[4][8] = {
    /* Page 0: Granular */
    {
        {"density",    "Density"},
        {"grain_size", "Size"},
        {"position",   "Position"},
        {"pitch",      "Pitch Shift"},
        {"feedback",   "Feedback"},
        {"pan_width",  "Pan Width"},
        {"freeze",     "Freeze"},
        {"mix",        "Dry/Wet"}
    },
    /* Page 1: Randomize */
    {
        {"random_length", "Rdm Size"},
        {"random_delay",  "Rdm Delay"},
        {"random_pitch",  "Rdm Shift"},
        {"reverse_prob",  "Reverse"},
        {"random_vol",    "Rdm Vol"},
        {"chance",        "Chance"},
        {NULL, NULL},
        {NULL, NULL}
    },
    /* Page 2: Sync */
    {
        {"sync",     "Sync"},
        {"division", "Division"},
        {"rhythm",   "Rhythm"},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL}
    },
    /* Page 3: Advanced */
    {
        {"gain",        "Input"},
        {"mute",        "Mute"},
        {"voice_count", "Voices"},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL},
        {NULL, NULL}
    }
};

static const int page_knob_count[4] = {8, 6, 3, 3};

/* ============================================================================
 * SHARED STATE
 * ============================================================================ */

static const host_api_v1_t *g_host = NULL;

static void plugin_log(const char *msg) {
    if (g_host && g_host->log) {
        char buf[256];
        snprintf(buf, sizeof(buf), "[granular] %s", msg);
        g_host->log(buf);
    }
}

/* ============================================================================
 * ENVELOPE TABLE GENERATION
 * ============================================================================ */

static void build_envelope_tables(granular_instance_t *inst) {
    for (int i = 0; i < ENV_TABLE_SIZE; i++) {
        float t = (float)i / (float)(ENV_TABLE_SIZE - 1);

        /* Hann window */
        inst->env_hann[i] = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * t));

        /* Triangle */
        inst->env_triangle[i] = (t < 0.5f) ? (2.0f * t) : (2.0f * (1.0f - t));

        /* Trapezoid (10% attack, 80% sustain, 10% release) */
        if (t < 0.1f)
            inst->env_trapezoid[i] = t / 0.1f;
        else if (t > 0.9f)
            inst->env_trapezoid[i] = (1.0f - t) / 0.1f;
        else
            inst->env_trapezoid[i] = 1.0f;
    }
}

/* ============================================================================
 * GRAIN MANAGEMENT
 * ============================================================================ */

/* Read from circular buffer with linear interpolation */
static inline float buffer_read_lerp(const float *buf, float pos) {
    /* Wrap to buffer range */
    while (pos < 0.0f) pos += (float)BUFFER_SIZE;
    while (pos >= (float)BUFFER_SIZE) pos -= (float)BUFFER_SIZE;

    int idx0 = (int)pos;
    int idx1 = (idx0 + 1) % BUFFER_SIZE;
    float frac = pos - (float)idx0;

    return buf[idx0] + frac * (buf[idx1] - buf[idx0]);
}

/* Look up envelope value with linear interpolation */
static inline float env_lookup(const float *table, float phase) {
    if (phase < 0.0f) phase = 0.0f;
    if (phase > 1.0f) phase = 1.0f;

    float idx_f = phase * (float)(ENV_TABLE_SIZE - 1);
    int idx0 = (int)idx_f;
    int idx1 = idx0 + 1;
    if (idx1 >= ENV_TABLE_SIZE) idx1 = ENV_TABLE_SIZE - 1;
    float frac = idx_f - (float)idx0;

    return table[idx0] + frac * (table[idx1] - table[idx0]);
}

/* Morphed envelope: blend between Hann (0.0), Triangle (0.5), Trapezoid (1.0) */
static inline float env_morphed(granular_instance_t *inst, float phase, float envelope) {
    if (envelope <= 0.0f) {
        return env_lookup(inst->env_hann, phase);
    } else if (envelope >= 1.0f) {
        return env_lookup(inst->env_trapezoid, phase);
    } else if (envelope <= 0.5f) {
        float t = envelope * 2.0f;
        float a = env_lookup(inst->env_hann, phase);
        float b = env_lookup(inst->env_triangle, phase);
        return a + t * (b - a);
    } else {
        float t = (envelope - 0.5f) * 2.0f;
        float a = env_lookup(inst->env_triangle, phase);
        float b = env_lookup(inst->env_trapezoid, phase);
        return a + t * (b - a);
    }
}

/* Find a free voice, returns index or -1 */
static int pick_voice(granular_instance_t *inst) {
    /* First pass: find an inactive voice */
    for (int i = 0; i < inst->voice_count; i++) {
        if (!inst->voices[i].active)
            return i;
    }
    /* Second pass: steal the voice closest to finishing */
    int best = -1;
    float best_phase = -1.0f;
    for (int i = 0; i < inst->voice_count; i++) {
        if (inst->voices[i].env_phase > best_phase) {
            best_phase = inst->voices[i].env_phase;
            best = i;
        }
    }
    return best;
}

/* Spawn a new grain */
static void spawn_grain(granular_instance_t *inst, float grain_size_ms,
                         float position, float pitch, float drift,
                         float reverse_prob, float pan_width,
                         float random_vol, float random_pitch,
                         float random_length) {
    int vi = pick_voice(inst);
    if (vi < 0) return;

    grain_voice_t *v = &inst->voices[vi];

    /* Randomize grain length */
    float rle = random_length * 0.01f;  /* normalize to 0-1 */
    float len_ms = grain_size_ms * (1.0f - rand01(&inst->rng_state) * rle);
    if (len_ms < 1.0f) len_ms = 1.0f;

    float len_samps = len_ms * (float)SAMPLE_RATE / 1000.0f;

    /* Randomize pitch */
    float rpt = random_pitch * 0.01f;
    float grain_pitch = pitch * powf(2.0f, rand01(&inst->rng_state) * rpt);
    if (grain_pitch < 0.25f) grain_pitch = 0.25f;
    if (grain_pitch > 4.0f) grain_pitch = 4.0f;

    /* Determine direction */
    float frp = reverse_prob * 0.01f;
    float direction = 1.0f;
    if (frp > 0.0f && rand01(&inst->rng_state) < frp)
        direction = -1.0f;

    /* Calculate playback increment */
    float inc = grain_pitch * direction;

    /* Total playback samples = grain_len_samps / |pitch| */
    float total = len_samps / grain_pitch;
    if (total < 1.0f) total = 1.0f;

    /* Calculate read position in buffer */
    float drf = drift * drift;  /* quadratic drift scaling (like Boris) */
    float pos_in_buf = position * (float)BUFFER_SIZE;
    float drift_samps = drf * (float)BUFFER_SIZE;
    pos_in_buf += rand01(&inst->rng_state) * drift_samps;

    /* Offset from write head: position 0 = closest to write head */
    float read_pos = (float)inst->write_pos - pos_in_buf;
    if (!inst->freeze) {
        /* When not frozen, offset by grain length to avoid reading
         * the region currently being written */
        read_pos -= len_samps;
    }

    /* Wrap to buffer */
    while (read_pos < 0.0f) read_pos += (float)BUFFER_SIZE;
    while (read_pos >= (float)BUFFER_SIZE) read_pos -= (float)BUFFER_SIZE;

    /* If reversed, start at end of grain region */
    if (direction < 0.0f)
        read_pos += len_samps;

    /* Randomize volume */
    float rvo = random_vol * 0.01f;
    float vol = 1.0f - rand01(&inst->rng_state) * rvo;

    /* Randomize pan */
    float pwi = pan_width * 0.01f;
    float pan = 0.5f + (rand01(&inst->rng_state) - 0.5f) * pwi;
    if (pan < 0.0f) pan = 0.0f;
    if (pan > 1.0f) pan = 1.0f;

    /* Set voice state */
    v->active = 1;
    v->env_phase = 0.0f;
    v->play_pos = read_pos;
    v->play_inc = inc;
    v->grain_len_samps = len_samps;
    v->total_samps = total;
    v->volume = vol;
    v->pan = pan;
    v->samples_played = 0;
}

/* ============================================================================
 * TRIGGER GENERATION
 * ============================================================================ */

/* Boris trigger frequency formula (from Granulator.cpp:1672) */
static inline float boris_trigger_freq(float len_ms, float density) {
    return (-0.60651f + 41.4268f * expf(-0.001f * len_ms)) * density;
}

/* ============================================================================
 * AUDIO PROCESSING
 * ============================================================================ */

/* DC blocker: y[n] = x[n] - x[n-1] + 0.9997 * y[n-1] */
static inline float dc_block(float x, float *xm1, float *ym1) {
    float y = x - *xm1 + 0.9997f * (*ym1);
    *xm1 = x;
    *ym1 = y;
    return y;
}

/* Soft clip (tanh-like, cheap) */
static inline float soft_clip(float x) {
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return x;
}

static void v2_process_block(void *instance, int16_t *audio_inout, int frames) {
    granular_instance_t *inst = (granular_instance_t *)instance;
    if (!inst || !inst->buffer) return;

    /* Track samples for MIDI clock BPM detection */
    inst->clock_sample_counter += frames;

    float inv_sr = 1.0f / (float)SAMPLE_RATE;

    for (int i = 0; i < frames; i++) {
        /* Get smoothed parameter values */
        float grain_size_ms = sv_next(&inst->sm_grain_size);
        float position      = sv_next(&inst->sm_position);
        float pitch          = sv_next(&inst->sm_pitch);
        float density        = sv_next(&inst->sm_density);
        float drift_val      = sv_next(&inst->sm_drift);
        float feedback       = sv_next(&inst->sm_feedback) * 0.01f;  /* 0-90 -> 0-0.9 */
        float mix_pct        = sv_next(&inst->sm_mix);
        float wet            = mix_pct * 0.01f;  /* 0-1 */
        float dry            = 1.0f - wet;       /* 1-0 */
        float gain           = sv_next(&inst->sm_gain);
        float envelope_val   = sv_next(&inst->sm_envelope);

        /* Convert input to float */
        float in_l = audio_inout[i * 2]     / 32768.0f;
        float in_r = audio_inout[i * 2 + 1] / 32768.0f;

        /* Sum to mono, apply input gain */
        float mono_in = (in_l + in_r) * 0.5f * gain;

        /* Mix with feedback */
        float fb_mono = (inst->fb_l + inst->fb_r) * 0.5f;
        float record_signal = mono_in + fb_mono * feedback;

        /* Write to circular buffer (unless frozen) */
        if (!inst->freeze) {
            inst->buffer[inst->write_pos] = record_signal;
            inst->write_pos = (inst->write_pos + 1) % BUFFER_SIZE;
        }

        /* === Trigger generation === */
        if (!inst->mute) {
            float freq;

            if (!inst->sync) {
                /* Free-running mode: Boris formula */
                freq = boris_trigger_freq(grain_size_ms, density);
            } else {
                /* Tempo-synced mode */
                if (inst->clock_running && inst->detected_bpm > 0) {
                    freq = compute_sync_freq(inst->detected_bpm, inst->division, inst->rhythm);
                } else {
                    freq = boris_trigger_freq(grain_size_ms, density);
                }
            }

            if (freq > 0.0f) {
                inst->trigger_phase += freq * inv_sr;

                if (inst->trigger_phase >= 1.0f) {
                    inst->trigger_phase -= 1.0f;

                    /* Chance check */
                    float cha = inst->chance * 0.01f;
                    if (rand01(&inst->rng_state) <= cha) {
                        /* Random delay: defer trigger by up to (rdl / freq) samples
                         * For simplicity we spawn immediately (delay within
                         * a 128-sample block is negligible) */
                        spawn_grain(inst, grain_size_ms, position, pitch,
                                    drift_val, inst->reverse_prob, inst->pan_width,
                                    inst->random_vol, inst->random_pitch,
                                    inst->random_length);
                    }
                }
            }
        }

        /* === Process active grains === */
        float wet_l = 0.0f, wet_r = 0.0f;

        for (int vi = 0; vi < inst->voice_count; vi++) {
            grain_voice_t *v = &inst->voices[vi];
            if (!v->active) continue;

            /* Read from buffer with interpolation */
            float sample = buffer_read_lerp(inst->buffer, v->play_pos);

            /* Envelope (morphed blend between shapes) */
            float env = env_morphed(inst, v->env_phase, envelope_val);

            /* Apply volume and envelope */
            float out = sample * env * v->volume;

            /* Pan to stereo (equal-power approximation) */
            float pan_r = v->pan;
            float pan_l = 1.0f - pan_r;
            wet_l += out * pan_l;
            wet_r += out * pan_r;

            /* Advance playback position */
            v->play_pos += v->play_inc;
            /* Wrap */
            if (v->play_pos < 0.0f) v->play_pos += (float)BUFFER_SIZE;
            if (v->play_pos >= (float)BUFFER_SIZE) v->play_pos -= (float)BUFFER_SIZE;

            /* Advance envelope */
            v->samples_played++;
            v->env_phase = (float)v->samples_played / v->total_samps;

            /* Check if grain is done */
            if (v->env_phase >= 1.0f) {
                v->active = 0;
            }
        }

        /* DC block the wet signal */
        wet_l = dc_block(wet_l, &inst->dc_xm1_l, &inst->dc_ym1_l);
        wet_r = dc_block(wet_r, &inst->dc_xm1_r, &inst->dc_ym1_r);

        /* Store feedback samples */
        inst->fb_l = wet_l;
        inst->fb_r = wet_r;

        /* Mix dry + wet */
        float out_l = in_l * dry + wet_l * wet;
        float out_r = in_r * dry + wet_r * wet;

        /* Soft clip */
        out_l = soft_clip(out_l);
        out_r = soft_clip(out_r);

        /* Convert back to int16 */
        audio_inout[i * 2]     = (int16_t)(out_l * 32767.0f);
        audio_inout[i * 2 + 1] = (int16_t)(out_r * 32767.0f);
    }
}

/* ============================================================================
 * MIDI CLOCK - BPM detection from 0xF8 timing messages
 * (Same pattern as space-delay spacecho.c)
 * ============================================================================ */

static void granular_on_midi(void *instance, const uint8_t *msg, int len, int source) {
    granular_instance_t *inst = (granular_instance_t *)instance;
    if (!inst || len < 1) return;
    (void)source;

    uint8_t status = msg[0];

    if (status == 0xF8) {
        /* Timing clock tick - 24 per quarter note */
        inst->clock_tick_count++;

        if (inst->clock_tick_count >= CLOCKS_PER_QUARTER) {
            int total_samples = inst->clock_sample_counter;
            float bpm = ((float)SAMPLE_RATE * 60.0f) / (float)total_samples;
            int bpm_int = (int)(bpm + 0.5f);
            if (bpm_int < 40) bpm_int = 40;
            if (bpm_int > 300) bpm_int = 300;

            /* Only update if BPM changed significantly (>=3 BPM) */
            if (!inst->clock_running || abs(bpm_int - inst->detected_bpm) >= 3) {
                inst->detected_bpm = bpm_int;
                inst->clock_running = 1;
            }

            inst->clock_tick_count = 0;
            inst->clock_sample_counter = 0;
        }
    }
    else if (status == 0xFA) {
        /* Start */
        inst->clock_tick_count = 0;
        inst->clock_sample_counter = 0;
        inst->clock_running = 1;
    }
    else if (status == 0xFC) {
        /* Stop */
        inst->clock_running = 0;
    }
    else if (status == 0xFB) {
        /* Continue */
        inst->clock_running = 1;
    }
}

/* ============================================================================
 * JSON HELPERS
 * ============================================================================ */

static int json_get_float(const char *json, const char *key, float *out) {
    char search[64];
    snprintf(search, sizeof(search), "\"%s\":", key);
    const char *pos = strstr(json, search);
    if (!pos) return -1;
    pos += strlen(search);
    while (*pos == ' ' || *pos == '\t' || *pos == '\r' || *pos == '\n') pos++;
    *out = (float)atof(pos);
    return 0;
}

static int json_get_int(const char *json, const char *key, int *out) {
    float v;
    if (json_get_float(json, key, &v) != 0) return -1;
    *out = (int)v;
    return 0;
}

static int json_get_string(const char *json, const char *key, char *out, int out_len) {
    char search[64];
    /* Match a fully-quoted key so "rhythm" never matches inside another key,
     * then tolerate any whitespace/newlines the host inserts when it
     * re-emits the state pretty-printed (`"key": "value"`). */
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *pos = strstr(json, search);
    if (!pos) return -1;
    pos += strlen(search);
    while (*pos == ':' || *pos == ' ' || *pos == '\t' ||
           *pos == '\r' || *pos == '\n') pos++;
    if (*pos != '"') return -1;
    pos++;
    int i = 0;
    while (*pos && *pos != '"' && i < out_len - 1) {
        out[i++] = *pos++;
    }
    out[i] = '\0';
    return 0;
}

/* ============================================================================
 * PARAMETER SET/GET
 * ============================================================================ */

static float clampf(float v, float lo, float hi) {
    return (v < lo) ? lo : (v > hi) ? hi : v;
}

static int clampi(int v, int lo, int hi) {
    return (v < lo) ? lo : (v > hi) ? hi : v;
}

static void apply_param_float(granular_instance_t *inst, const char *key, float v) {
    if (strcmp(key, "grain_size") == 0) {
        inst->grain_size = clampf(v, 20.0f, 2000.0f);
        sv_set(&inst->sm_grain_size, inst->grain_size, RAMP_SAMPLES);
    }
    else if (strcmp(key, "position") == 0) {
        inst->position = clampf(v, 0.0f, 1.0f);
        sv_set(&inst->sm_position, inst->position, RAMP_SAMPLES);
    }
    else if (strcmp(key, "pitch") == 0) {
        inst->pitch = clampf(v, 0.25f, 4.0f);
        sv_set(&inst->sm_pitch, inst->pitch, RAMP_SAMPLES);
    }
    else if (strcmp(key, "density") == 0) {
        inst->density = clampf(v, 0.04f, 1.0f);
        sv_set(&inst->sm_density, inst->density, RAMP_SAMPLES);
    }
    else if (strcmp(key, "drift") == 0) {
        inst->drift = clampf(v, 0.0f, 1.0f);
        sv_set(&inst->sm_drift, inst->drift, RAMP_SAMPLES);
    }
    else if (strcmp(key, "feedback") == 0) {
        inst->feedback = clampf(v, 0.0f, 90.0f);
        sv_set(&inst->sm_feedback, inst->feedback, RAMP_SAMPLES);
    }
    else if (strcmp(key, "mix") == 0) {
        inst->mix = clampf(v, 0.0f, 100.0f);
        sv_set(&inst->sm_mix, inst->mix, RAMP_SAMPLES);
    }
    else if (strcmp(key, "gain") == 0) {
        inst->gain = clampf(v, 0.0f, 1.5f);
        sv_set(&inst->sm_gain, inst->gain, RAMP_SAMPLES);
    }
    else if (strcmp(key, "chance") == 0) {
        inst->chance = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "reverse_prob") == 0) {
        inst->reverse_prob = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "pan_width") == 0) {
        inst->pan_width = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "random_vol") == 0) {
        inst->random_vol = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "random_pitch") == 0) {
        inst->random_pitch = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "random_length") == 0) {
        inst->random_length = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "random_delay") == 0) {
        inst->random_delay = clampf(v, 0.0f, 100.0f);
    }
    else if (strcmp(key, "voice_count") == 0) {
        inst->voice_count = clampi((int)v, 1, MAX_VOICES);
    }
}

static void apply_param_enum(granular_instance_t *inst, const char *key, const char *val) {
    if (strcmp(key, "envelope") == 0) {
        inst->envelope = parse_envelope_float(val);
        sv_set(&inst->sm_envelope, inst->envelope, RAMP_SAMPLES);
        return;
    }
    else if (strcmp(key, "freeze") == 0) {
        if (strcmp(val, "on") == 0 || strcmp(val, "1") == 0)
            inst->freeze = 1;
        else
            inst->freeze = 0;
    }
    else if (strcmp(key, "mute") == 0) {
        if (strcmp(val, "on") == 0 || strcmp(val, "1") == 0)
            inst->mute = 1;
        else
            inst->mute = 0;
    }
    else if (strcmp(key, "sync") == 0) {
        if (strcmp(val, "on") == 0 || strcmp(val, "1") == 0)
            inst->sync = 1;
        else
            inst->sync = 0;
    }
    else if (strcmp(key, "division") == 0) {
        inst->division = parse_division(val);
    }
    else if (strcmp(key, "rhythm") == 0) {
        inst->rhythm = parse_rhythm(val);
    }
}

static void v2_set_param(void *instance, const char *key, const char *val) {
    granular_instance_t *inst = (granular_instance_t *)instance;
    if (!inst) return;

    /* Page navigation from UI */
    if (strcmp(key, "_level") == 0 || strcmp(key, "level") == 0) {
        if (strcmp(val, "Granular") == 0 || strcmp(val, "root") == 0)
            inst->current_page = 0;
        else if (strcmp(val, "Randomize") == 0)
            inst->current_page = 1;
        else if (strcmp(val, "Sync") == 0)
            inst->current_page = 2;
        else if (strcmp(val, "Advanced") == 0)
            inst->current_page = 3;
        return;
    }

    /* State restore from patch save */
    if (strcmp(key, "state") == 0) {
        float fv;
        int iv;
        char sv[32];

        if (json_get_float(val, "grain_size", &fv) == 0)
            apply_param_float(inst, "grain_size", fv);
        if (json_get_float(val, "position", &fv) == 0)
            apply_param_float(inst, "position", fv);
        if (json_get_float(val, "pitch", &fv) == 0)
            apply_param_float(inst, "pitch", fv);
        if (json_get_float(val, "density", &fv) == 0)
            apply_param_float(inst, "density", fv);
        if (json_get_float(val, "drift", &fv) == 0)
            apply_param_float(inst, "drift", fv);
        if (json_get_float(val, "feedback", &fv) == 0)
            apply_param_float(inst, "feedback", fv);
        if (json_get_float(val, "mix", &fv) == 0)
            apply_param_float(inst, "mix", fv);
        if (json_get_float(val, "gain", &fv) == 0)
            apply_param_float(inst, "gain", fv);
        if (json_get_float(val, "chance", &fv) == 0)
            apply_param_float(inst, "chance", fv);
        if (json_get_float(val, "reverse_prob", &fv) == 0)
            apply_param_float(inst, "reverse_prob", fv);
        if (json_get_float(val, "pan_width", &fv) == 0)
            apply_param_float(inst, "pan_width", fv);
        if (json_get_float(val, "random_vol", &fv) == 0)
            apply_param_float(inst, "random_vol", fv);
        if (json_get_float(val, "random_pitch", &fv) == 0)
            apply_param_float(inst, "random_pitch", fv);
        if (json_get_float(val, "random_length", &fv) == 0)
            apply_param_float(inst, "random_length", fv);
        if (json_get_float(val, "random_delay", &fv) == 0)
            apply_param_float(inst, "random_delay", fv);
        if (json_get_float(val, "envelope", &fv) == 0) {
            inst->envelope = clampf(fv, 0.0f, 1.0f);
            sv_set(&inst->sm_envelope, inst->envelope, RAMP_SAMPLES);
        }
        if (json_get_int(val, "freeze", &iv) == 0)
            inst->freeze = (iv != 0) ? 1 : 0;
        if (json_get_int(val, "mute", &iv) == 0)
            inst->mute = (iv != 0) ? 1 : 0;
        if (json_get_int(val, "sync", &iv) == 0)
            inst->sync = (iv != 0) ? 1 : 0;
        if (json_get_string(val, "division", sv, sizeof(sv)) == 0)
            apply_param_enum(inst, "division", sv);
        if (json_get_string(val, "rhythm", sv, sizeof(sv)) == 0)
            apply_param_enum(inst, "rhythm", sv);
        if (json_get_float(val, "voice_count", &fv) == 0)
            apply_param_float(inst, "voice_count", fv);
        if (json_get_int(val, "bpm", &iv) == 0) {
            inst->detected_bpm = clampi(iv, 40, 300);
        }
        return;
    }

#ifdef BORIS_VST
    /* MPC VST port: host tempo from audioMasterGetTime (wrapper HAS_LFO_BPM) stands in for MIDI clock */
    if (strcmp(key, "lfo_bpm") == 0) {
        inst->detected_bpm = clampi((int)(atof(val) + 0.5f), 40, 300);
        inst->clock_running = 1;
        return;
    }
#endif

    /* Envelope accepts both names and float values */
    if (strcmp(key, "envelope") == 0) {
        inst->envelope = parse_envelope_float(val);
        sv_set(&inst->sm_envelope, inst->envelope, RAMP_SAMPLES);
        return;
    }

    /* Check enum-type params */
    if (strcmp(key, "freeze") == 0 || strcmp(key, "mute") == 0 ||
        strcmp(key, "sync") == 0 || strcmp(key, "division") == 0 ||
        strcmp(key, "rhythm") == 0) {
        apply_param_enum(inst, key, val);
        return;
    }

    /* Float/int params */
    float v = (float)atof(val);
    apply_param_float(inst, key, v);
}

static int v2_get_param(void *instance, const char *key, char *buf, int buf_len) {
    granular_instance_t *inst = (granular_instance_t *)instance;
    if (!inst) return -1;

    if (strcmp(key, "grain_size") == 0)
        return snprintf(buf, buf_len, "%.1f", inst->grain_size);
    if (strcmp(key, "position") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->position);
    if (strcmp(key, "pitch") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->pitch);
    if (strcmp(key, "density") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->density);
    if (strcmp(key, "drift") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->drift);
    if (strcmp(key, "feedback") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->feedback + 0.5f));
    if (strcmp(key, "mix") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->mix + 0.5f));
    if (strcmp(key, "gain") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->gain);
    if (strcmp(key, "chance") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->chance + 0.5f));
    if (strcmp(key, "reverse_prob") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->reverse_prob + 0.5f));
    if (strcmp(key, "pan_width") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->pan_width + 0.5f));
    if (strcmp(key, "random_vol") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->random_vol + 0.5f));
    if (strcmp(key, "random_pitch") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->random_pitch + 0.5f));
    if (strcmp(key, "random_length") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->random_length + 0.5f));
    if (strcmp(key, "random_delay") == 0)
        return snprintf(buf, buf_len, "%d", (int)(inst->random_delay + 0.5f));
    if (strcmp(key, "envelope") == 0)
        return snprintf(buf, buf_len, "%.2f", inst->envelope);
    if (strcmp(key, "freeze") == 0)
        return snprintf(buf, buf_len, "%s", inst->freeze ? "on" : "off");
    if (strcmp(key, "mute") == 0)
        return snprintf(buf, buf_len, "%s", inst->mute ? "on" : "off");
    if (strcmp(key, "sync") == 0)
        return snprintf(buf, buf_len, "%s", inst->sync ? "on" : "off");
    if (strcmp(key, "division") == 0)
        return snprintf(buf, buf_len, "%s", division_names[inst->division]);
    if (strcmp(key, "rhythm") == 0)
        return snprintf(buf, buf_len, "%s", rhythm_names[inst->rhythm]);
    if (strcmp(key, "voice_count") == 0)
        return snprintf(buf, buf_len, "%d", inst->voice_count);
    if (strcmp(key, "bpm") == 0)
        return snprintf(buf, buf_len, "%d", inst->detected_bpm);
    if (strcmp(key, "name") == 0)
        return snprintf(buf, buf_len, "Boris");

    /* Knob display name: knob_N_name (1-indexed) */
    if (strncmp(key, "knob_", 5) == 0 && strstr(key, "_name")) {
        int knob_num = atoi(key + 5);
        if (knob_num >= 1 && knob_num <= 8) {
            int idx = knob_num - 1;
            int page = inst->current_page;
            if (idx < page_knob_count[page] && page_knobs[page][idx].label) {
                return snprintf(buf, buf_len, "%s", page_knobs[page][idx].label);
            }
        }
        return -1;
    }

    /* Knob display value: knob_N_value (1-indexed) */
    if (strncmp(key, "knob_", 5) == 0 && strstr(key, "_value")) {
        int knob_num = atoi(key + 5);
        if (knob_num >= 1 && knob_num <= 8) {
            int idx = knob_num - 1;
            int page = inst->current_page;
            if (idx < page_knob_count[page] && page_knobs[page][idx].key) {
                return v2_get_param(instance, page_knobs[page][idx].key, buf, buf_len);
            }
        }
        return -1;
    }

    /* State save */
    if (strcmp(key, "state") == 0) {
        return snprintf(buf, buf_len,
            "{\"grain_size\":%.1f,\"position\":%.4f,\"pitch\":%.4f,\"density\":%.4f,"
            "\"drift\":%.4f,\"feedback\":%.1f,\"mix\":%.1f,\"gain\":%.4f,"
            "\"chance\":%.1f,\"reverse_prob\":%.1f,\"pan_width\":%.1f,"
            "\"random_vol\":%.1f,\"random_pitch\":%.1f,\"random_length\":%.1f,"
            "\"random_delay\":%.1f,\"envelope\":%.4f,\"freeze\":%d,\"mute\":%d,"
            "\"sync\":%d,\"division\":\"%s\",\"rhythm\":\"%s\","
            "\"voice_count\":%d,\"bpm\":%d}",
            inst->grain_size, inst->position, inst->pitch, inst->density,
            inst->drift, inst->feedback, inst->mix, inst->gain,
            inst->chance, inst->reverse_prob, inst->pan_width,
            inst->random_vol, inst->random_pitch, inst->random_length,
            inst->random_delay, inst->envelope,
            inst->freeze, inst->mute, inst->sync,
            division_names[inst->division], rhythm_names[inst->rhythm],
            inst->voice_count, inst->detected_bpm);
    }

    /* UI hierarchy — flat root with sub-levels (like HeatAir/Cloudseed) */
    if (strcmp(key, "ui_hierarchy") == 0) {
        const char *h = "{"
            "\"modes\":null,"
            "\"levels\":{"
                "\"root\":{"
                    "\"name\":\"Boris Granular\","
                    "\"knobs\":[\"density\",\"grain_size\",\"position\",\"pitch\","
                        "\"feedback\",\"pan_width\",\"freeze\",\"mix\"],"
                    "\"params\":["
                        "{\"level\":\"Granular\",\"label\":\"Granular\"},"
                        "{\"level\":\"Randomize\",\"label\":\"Randomize\"},"
                        "{\"level\":\"Sync\",\"label\":\"Sync\"},"
                        "{\"level\":\"Advanced\",\"label\":\"Advanced\"}"
                    "]"
                "},"
                "\"Granular\":{"
                    "\"label\":\"Granular\","
                    "\"knobs\":[\"density\",\"grain_size\",\"position\",\"pitch\","
                        "\"feedback\",\"pan_width\",\"freeze\",\"mix\"],"
                    "\"params\":[\"density\",\"grain_size\",\"position\",\"pitch\","
                        "\"feedback\",\"mix\",\"pan_width\",\"freeze\","
                        "\"envelope\",\"drift\"]"
                "},"
                "\"Randomize\":{"
                    "\"label\":\"Randomize\","
                    "\"knobs\":[\"random_length\",\"random_delay\",\"random_pitch\","
                        "\"reverse_prob\",\"random_vol\",\"chance\"],"
                    "\"params\":[\"random_length\",\"random_delay\",\"random_pitch\","
                        "\"reverse_prob\",\"random_vol\",\"chance\"]"
                "},"
                "\"Sync\":{"
                    "\"label\":\"Sync\","
                    "\"knobs\":[\"sync\",\"division\",\"rhythm\"],"
                    "\"params\":[\"sync\",\"division\",\"rhythm\"]"
                "},"
                "\"Advanced\":{"
                    "\"label\":\"Advanced\","
                    "\"knobs\":[\"gain\",\"mute\",\"voice_count\"],"
                    "\"params\":[\"gain\",\"mute\",\"voice_count\"]"
                "}"
            "}"
        "}";
        int len = (int)strlen(h);
        if (len < buf_len) {
            strcpy(buf, h);
            return len;
        }
        return -1;
    }

    /* Chain params metadata — all params so host can resolve display names */
    if (strcmp(key, "chain_params") == 0) {
        return snprintf(buf, buf_len,
            "["
            "{\"key\":\"density\",\"name\":\"Density\",\"type\":\"float\",\"min\":0.04,\"max\":1,\"step\":0.01},"
            "{\"key\":\"grain_size\",\"name\":\"Size\",\"type\":\"float\",\"min\":20,\"max\":2000,\"step\":1},"
            "{\"key\":\"pitch\",\"name\":\"Pitch Shift\",\"type\":\"float\",\"min\":0.25,\"max\":4,\"step\":0.01},"
            "{\"key\":\"envelope\",\"name\":\"Envelope\",\"type\":\"float\",\"min\":0,\"max\":1,\"step\":0.01},"
            "{\"key\":\"position\",\"name\":\"Position\",\"type\":\"float\",\"min\":0,\"max\":1,\"step\":0.01},"
            "{\"key\":\"drift\",\"name\":\"Drift\",\"type\":\"float\",\"min\":0,\"max\":1,\"step\":0.01},"
            "{\"key\":\"mix\",\"name\":\"Dry/Wet\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"freeze\",\"name\":\"Freeze\",\"type\":\"enum\",\"options\":[\"off\",\"on\"],\"default\":0},"
            "{\"key\":\"random_length\",\"name\":\"Rdm Size\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"random_delay\",\"name\":\"Rdm Delay\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"random_pitch\",\"name\":\"Rdm Shift\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"reverse_prob\",\"name\":\"Reverse\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"pan_width\",\"name\":\"Pan Width\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"random_vol\",\"name\":\"Rdm Vol\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"chance\",\"name\":\"Chance\",\"type\":\"float\",\"min\":0,\"max\":100,\"step\":1},"
            "{\"key\":\"feedback\",\"name\":\"Feedback\",\"type\":\"float\",\"min\":0,\"max\":90,\"step\":1},"
            "{\"key\":\"sync\",\"name\":\"Sync\",\"type\":\"enum\",\"options\":[\"off\",\"on\"],\"default\":0},"
            "{\"key\":\"division\",\"name\":\"Division\",\"type\":\"enum\",\"options\":[\"1/16\",\"1/8\",\"1/4\",\"1/2\",\"1/1\",\"2/1\",\"4/1\"],\"default\":3},"
            "{\"key\":\"rhythm\",\"name\":\"Rhythm\",\"type\":\"enum\",\"options\":[\"normal\",\"dotted\",\"triplet\"],\"default\":0},"
            "{\"key\":\"gain\",\"name\":\"Input\",\"type\":\"float\",\"min\":0,\"max\":1.5,\"step\":0.01},"
            "{\"key\":\"mute\",\"name\":\"Mute\",\"type\":\"enum\",\"options\":[\"off\",\"on\"],\"default\":0},"
            "{\"key\":\"voice_count\",\"name\":\"Voices\",\"type\":\"int\",\"min\":1,\"max\":24,\"step\":1}"
            "]");
    }

    return -1;
}

/* ============================================================================
 * INSTANCE LIFECYCLE
 * ============================================================================ */

static void* v2_create_instance(const char *module_dir, const char *config_json) {
    (void)module_dir;
    (void)config_json;

    plugin_log("Creating instance");

    granular_instance_t *inst = (granular_instance_t *)calloc(1, sizeof(granular_instance_t));
    if (!inst) {
        plugin_log("Failed to allocate instance");
        return NULL;
    }

    /* Allocate circular buffer (~1.7MB) */
    inst->buffer = (float *)calloc(BUFFER_SIZE, sizeof(float));
    if (!inst->buffer) {
        plugin_log("Failed to allocate audio buffer");
        free(inst);
        return NULL;
    }

    /* Initialize PRNG */
    inst->rng_state = 0xDEADBEEF;

    /* Set default parameters */
    inst->grain_size    = 200.0f;
    inst->position      = 0.0f;
    inst->pitch         = 1.0f;
    inst->density       = 0.5f;
    inst->drift         = 0.0f;
    inst->feedback      = 0.0f;
    inst->mix           = 50.0f;
    inst->gain          = 1.0f;
    inst->chance        = 100.0f;
    inst->reverse_prob  = 0.0f;
    inst->pan_width     = 50.0f;
    inst->random_vol    = 0.0f;
    inst->random_pitch  = 0.0f;
    inst->random_length = 0.0f;
    inst->random_delay  = 0.0f;
    inst->envelope      = 0.0f;    /* 0.0=Hann, 0.5=Triangle, 1.0=Trapezoid */
    inst->freeze        = 0;
    inst->mute          = 0;
    inst->sync          = 0;
    inst->division      = DIV_1_4;
    inst->rhythm        = 0;
    inst->voice_count   = MAX_VOICES;
    inst->detected_bpm  = 120;
    inst->current_page  = 0;

    /* Initialize smoothed values */
    sv_init(&inst->sm_grain_size, inst->grain_size);
    sv_init(&inst->sm_position,   inst->position);
    sv_init(&inst->sm_pitch,      inst->pitch);
    sv_init(&inst->sm_density,    inst->density);
    sv_init(&inst->sm_drift,      inst->drift);
    sv_init(&inst->sm_feedback,   inst->feedback);
    sv_init(&inst->sm_mix,        inst->mix);
    sv_init(&inst->sm_gain,       inst->gain);
    sv_init(&inst->sm_envelope,   inst->envelope);

    /* Build envelope lookup tables */
    build_envelope_tables(inst);

    plugin_log("Instance created");
    return inst;
}

static void v2_destroy_instance(void *instance) {
    granular_instance_t *inst = (granular_instance_t *)instance;
    if (!inst) return;

    plugin_log("Destroying instance");

    if (inst->buffer) {
        free(inst->buffer);
        inst->buffer = NULL;
    }

    free(inst);
}

/* ============================================================================
 * V2 API ENTRY POINT
 * ============================================================================ */

#define AUDIO_FX_API_VERSION_2 2

typedef struct audio_fx_api_v2 {
    uint32_t api_version;
    void* (*create_instance)(const char *module_dir, const char *config_json);
    void (*destroy_instance)(void *instance);
    void (*process_block)(void *instance, int16_t *audio_inout, int frames);
    void (*set_param)(void *instance, const char *key, const char *val);
    int (*get_param)(void *instance, const char *key, char *buf, int buf_len);
    void (*on_midi)(void *instance, const uint8_t *msg, int len, int source);
} audio_fx_api_v2_t;

static audio_fx_api_v2_t g_fx_api_v2;

audio_fx_api_v2_t* move_audio_fx_init_v2(const host_api_v1_t *host) {
    g_host = host;

    memset(&g_fx_api_v2, 0, sizeof(g_fx_api_v2));
    g_fx_api_v2.api_version      = AUDIO_FX_API_VERSION_2;
    g_fx_api_v2.create_instance  = v2_create_instance;
    g_fx_api_v2.destroy_instance = v2_destroy_instance;
    g_fx_api_v2.process_block    = v2_process_block;
    g_fx_api_v2.set_param        = v2_set_param;
    g_fx_api_v2.get_param        = v2_get_param;
    g_fx_api_v2.on_midi          = granular_on_midi;

    plugin_log("Boris Granular v2 plugin initialized");

    return &g_fx_api_v2;
}

/*
 * Standalone MIDI handler export - chain host discovers this via dlsym.
 * Receives MIDI clock (0xF8) for tempo sync.
 */
void move_audio_fx_on_midi(void *instance, const uint8_t *msg, int len, int source) {
    granular_on_midi(instance, msg, len, source);
}
