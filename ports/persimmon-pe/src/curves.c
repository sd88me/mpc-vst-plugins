#include <math.h>
#include "curves.h"

float pe_note_hz(float s) { return 8.1757989f * exp2f(s * (1.0f / 12)); }
float pe_lpf_hz(float v) { return 16.351598f * exp2f(v * (1.0f / 12)); }
/* The highpass coefficient sets step one semitone per value (measured -3 dB points: 99 = 21.55 kHz, 50 = 1.27 kHz). */
float pe_hpf_hz(float v) { return 21551.0f * exp2f((v - 99.0f) * (1.0f / 12)); }

static float interp_log(const float (*bp)[2], int n, float v) {
    if (v <= bp[0][0]) return bp[0][1];
    for (int i = 1; i < n; i++)
        if (v <= bp[i][0]) {
            float t = (v - bp[i - 1][0]) / (bp[i][0] - bp[i - 1][0]);
            return expf(logf(bp[i - 1][1]) + t * (logf(bp[i][1]) - logf(bp[i - 1][1])));
        }
    return bp[n - 1][1];
}

/* The envelope rate table is 111 step sizes; full scale / step = these tick counts (log-interpolated breakpoints, within a few
 * percent of every entry). The firmware's envelope tick rate is not in the tables: 3 kHz is an assumption (docs/FIRMWARE.md). */
float pe_env_seconds(float v) {
    static const float bp[][2] = {{0, 3.3f}, {1, 7.9f}, {3, 14.9f}, {5, 26.3f}, {10, 62.5f}, {15, 111.1f}, {19, 199.8f}, {20, 221.4f},
        {30, 496.5f}, {43, 1024}, {59, 2048}, {70, 2892.6f}, {80, 4415.1f}, {85, 6035}, {90, 9020}, {95, 14717}, {100, 25420},
        {103, 33554}, {106, 47935}, {108, 67109}, {110, 111848}};
    return interp_log(bp, sizeof bp / sizeof bp[0], v) * (1.0f / 3000);
}

/* Unsynced LFO: round decimal frequencies up to 89 (piecewise linear), then semitones from 8.18 Hz (C-2) at 90 to 261.6 Hz at 150. */
float pe_lfo_hz(int v) {
    static const float bp[][2] = {{0, 0.0333f}, {1, 0.04f}, {13, 0.16f}, {14, 0.18f}, {15, 0.2f}, {16, 0.23f}, {17, 0.26f}, {18, 0.3f},
        {19, 0.35f}, {20, 0.4f}, {30, 0.9f}, {31, 1.0f}, {38, 1.35f}, {39, 1.45f}, {42, 1.6f}, {43, 1.7f}, {46, 2.0f}, {76, 5.0f},
        {86, 7.0f}, {87, 7.3f}, {88, 7.6f}, {89, 7.7f}};
    if (v >= 90) return 8.1757989f * exp2f((v - 90) * (1.0f / 12));
    int n = sizeof bp / sizeof bp[0];
    for (int i = 1; i < n; i++)
        if (v <= bp[i][0]) return bp[i - 1][1] + (v - bp[i - 1][0]) * (bp[i][1] - bp[i - 1][1]) / (bp[i][0] - bp[i - 1][0]);
    return bp[n - 1][1];
}

/* Delay taps: 1..21 samples, then semitones (22 = C7 = 22.93 samples, 94 = C1), then round sample counts up to 48000 (1 s). */
float pe_delay_seconds(int v) {
    static const short mid[] = {1550, 1650, 1750, 1850, 2000, 2200, 2500, 2900, 3400, 3900, 4600, 5200, 5900, 6600, 7200, 8000};
    float s;
    if (v <= 0) s = 0;
    else if (v <= 21) s = v;
    else if (v <= 94) s = 48000.0f / (2093.0045f * exp2f((22 - v) * (1.0f / 12)));
    else if (v <= 110) s = mid[v - 95];
    else s = v >= 150 ? 48000 : 9000 + 1000 * (v - 111);
    return s * (1.0f / 48000);
}

/* Glide rate: not in the tables found so far; an exponential from 5 ms to about 10 s. */
float pe_glide_seconds(int v) { return v <= 0 ? 0 : 0.005f * exp2f(v * 0.11f); }
