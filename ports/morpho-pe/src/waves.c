#include <math.h>
#include <string.h>
#include "waves.h"
#include "syx.h"

static void add(float *w, int h, float a, float ph) {
    for (int i = 0; i < PE_WLEN; i++) w[i] += a * sinf(6.2831853f * h * i / PE_WLEN + ph);
}
static void norm(float *w) {
    float m = 0;
    for (int i = 0; i < PE_WLEN; i++) m = fmaxf(m, fabsf(w[i]));
    if (m > 0) for (int i = 0; i < PE_WLEN; i++) w[i] /= m;
}
static uint32_t lcg(uint32_t *s) { *s = *s * 1664525u + 1013904223u; return *s >> 8; }

void waves_open(float w[PE_NWAVES][PE_WLEN]) {
    memset(w, 0, sizeof(float) * PE_NWAVES * PE_WLEN);
    for (int k = 0; k < 96; k++) {
        float *x = w[k];
        if (k == 0) add(x, 1, 1, 0);
        else if (k == 1) for (int h = 1; h <= 40; h++) add(x, h, 1.0f / h, 0);
        else if (k == 2) for (int h = 1; h <= 40; h += 2) add(x, h, 1.0f / h, 0);
        else if (k == 3) for (int h = 1; h <= 40; h += 2) add(x, h, 1.0f / (h * h), (h & 2) ? 3.14159265f : 0);
        else if (k < 24) {          /* one formant peak walking up the harmonics */
            float c = (float)(k - 2), bw = 1.5f + 0.15f * k;
            for (int h = 1; h <= 48; h++) add(x, h, expf(-(h - c) * (h - c) / (2 * bw * bw)) + 0.15f / h, 0);
        } else if (k < 48) {        /* power-law spectra from dark to bright, with alternating sign patterns */
            float p = 2.2f - (k - 24) * 0.08f;
            int pat = k % 4;
            for (int h = 1; h <= 48; h++) add(x, h, powf((float)h, -p) * ((pat == 1 && h % 2 == 0) ? 0.2f : 1), pat == 2 && (h & 1) ? 3.14159265f : 0);
        } else if (k < 72) {        /* pulse-like spectra at swept duty cycles */
            float d = 0.03f + (k - 48) * 0.019f;
            for (int h = 1; h <= 48; h++) add(x, h, sinf(3.14159265f * h * d) / h, 0);
        } else if (k < 94) {        /* seeded random spectra (fixed: the same set every time) */
            uint32_t s = 0x5EED0000u + (uint32_t)k;
            for (int h = 1; h <= 40; h++)
                add(x, h, (lcg(&s) % 1000) / 1000.0f / sqrtf((float)h), (lcg(&s) % 6283) / 1000.0f);
        } else if (k == 95) {       /* wave 96: a folded sine of our own (the original's slot 96 is unique to the instrument) */
            for (int i = 0; i < PE_WLEN; i++) x[i] = sinf(2.5f * sinf(6.2831853f * i / PE_WLEN));
        }
        /* k == 94 (wave 95) stays blank, as on the instrument */
        norm(x);
    }
    for (int k = 96; k < 128; k++) memcpy(w[k], w[k - 96], sizeof w[k]);
}

int waves_from_dump(const uint8_t *body, int n, float out[PE_WLEN]) {
    if (n < 2) return -1;
    int slot = body[0];
    uint8_t raw[260];
    if (syx_unpack(body + 1, n - 1, raw, sizeof raw) < 256 || slot > 127) return -1;
    int16_t v[PE_WLEN];
    int big = 0;
    for (int i = 0; i < PE_WLEN; i++) {
        v[i] = (int16_t)(raw[2 * i] | (raw[2 * i + 1] << 8));
        if (v[i] > 2048 || v[i] < -2048) big = 1;
    }
    for (int i = 0; i < PE_WLEN; i++) out[i] = v[i] / (big ? 32768.0f : 2048.0f);
    return slot;
}
