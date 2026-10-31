/* Streaming stereo sample-rate converter for wrappers whose host does not run at the engine's 44100 Hz (vst3_wrap.c on a
 * desktop DAW at 48 or 96 kHz). Windowed sinc (Kaiser), from a table of 512 phases per input sample with linear
 * interpolation between them; the cutoff follows the lower of the two rates, so downsampling does not alias.
 *
 *   rs_t r;  rs_init(&r, in_rate, out_rate);    allocates (not on the audio thread); rs_free(&r) when done
 *   rs_push(&r, l, r_, n);                      input frames (planar), at most rs_room(&r) of them
 *   n = rs_pull(&r, outl, outr, max);           as many output frames as the input so far allows, up to max
 *
 * Time mapping: output frame m is the input at time m * in_rate / out_rate, exactly, so the converter adds no delay of its
 * own; output frame m only becomes available once the input reaches that time plus half the filter (rs_t.half input
 * frames). Equal rates copy samples straight through. Header-only, static functions; no allocation after rs_init. */
#ifndef MPC_RESAMPLE_H
#define MPC_RESAMPLE_H

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define RS_PHASES 512
#define RS_ZEROS 16   /* sinc zero crossings each side of the kernel's centre */
#define RS_CAP 8192   /* input frames buffered; a host block is pushed in pieces of at most rs_room() */

typedef struct {
    double step;      /* input frames per output frame */
    double pos;       /* the next output's time, in input frames from buf[0] */
    int half;         /* filter half-width, in input frames (0: equal rates, a plain copy) */
    float scale;      /* the cutoff: kernel units (sinc zero crossings) per input frame */
    float *table;     /* 2 * RS_ZEROS * RS_PHASES + 2 points of the kernel, x from -RS_ZEROS to +RS_ZEROS */
    float buf[2][RS_CAP];
    int len;          /* frames in buf */
} rs_t;

static double rs_i0(double x) {   /* modified Bessel function of the first kind, order 0 (Kaiser window) */
    double s = 1, t = 1;
    for (int k = 1; k < 40; k++) { t *= (x / (2 * k)) * (x / (2 * k)); s += t; if (t < 1e-12 * s) break; }
    return s;
}

static int rs_init(rs_t *r, double in_rate, double out_rate) {
    memset(r, 0, sizeof *r);
    r->step = in_rate / out_rate;
    if (fabs(in_rate - out_rate) < 1e-6) { r->step = 1; return 1; }
    double fc = 0.95 * (r->step > 1 ? 1 / r->step : 1);   /* cutoff, as a fraction of the input's Nyquist */
    r->half = (int)ceil(RS_ZEROS / fc);
    r->scale = (float)fc;
    const double beta = 8.0, i0b = rs_i0(beta);
    int n = 2 * RS_ZEROS * RS_PHASES + 2;
    r->table = (float *)malloc(sizeof(float) * n);
    if (!r->table) return 0;
    for (int i = 0; i < n; i++) {
        double x = (double)i / RS_PHASES - RS_ZEROS, w = x / RS_ZEROS;
        double win = fabs(w) >= 1 ? 0 : rs_i0(beta * sqrt(1 - w * w)) / i0b;
        double s = fabs(x) < 1e-9 ? 1 : sin(M_PI * x) / (M_PI * x);
        r->table[i] = (float)(s * win * fc);   /* * fc: unity gain at DC */
    }
    r->pos = r->half;   /* input frame 0 sits at buf[half]: the first half frames are silence before it */
    r->len = r->half;
    return 1;
}

static inline void rs_free(rs_t *r) { free(r->table); r->table = NULL; }

static inline int rs_room(const rs_t *r) { return RS_CAP - r->len; }

static void rs_push(rs_t *r, const float *l, const float *rt, int n) {
    if (n > RS_CAP - r->len) n = RS_CAP - r->len;
    for (int i = 0; i < n; i++) { r->buf[0][r->len + i] = l ? l[i] : 0; r->buf[1][r->len + i] = rt ? rt[i] : 0; }
    r->len += n;
}

/* How many input frames rs_pull() needs before it can give `n` more output frames. */
static inline int rs_need(const rs_t *r, int n) {
    if (!r->half) return n - r->len > 0 ? n - r->len : 0;
    double last = r->pos + (n - 1) * r->step;
    int need = (int)floor(last) + r->half + 1 - r->len;
    return need > 0 ? need : 0;
}

static int rs_pull(rs_t *r, float *l, float *rt, int max) {
    int m = 0;
    if (!r->half) {
        m = max < r->len ? max : r->len;
        memcpy(l, r->buf[0], sizeof(float) * m);
        memcpy(rt, r->buf[1], sizeof(float) * m);
        memmove(r->buf[0], r->buf[0] + m, sizeof(float) * (r->len - m));
        memmove(r->buf[1], r->buf[1] + m, sizeof(float) * (r->len - m));
        r->len -= m;
        return m;
    }
    const float sc = r->scale * RS_PHASES, c0 = (float)(RS_ZEROS * RS_PHASES), tmax = (float)(2 * RS_ZEROS * RS_PHASES);
    while (m < max) {
        int ip = (int)floor(r->pos);
        if (ip + r->half >= r->len) break;   /* not enough input yet */
        float frac = (float)(r->pos - ip), al = 0, ar = 0;
        for (int k = -r->half + 1; k <= r->half; k++) {
            /* tap at input frame ip + k, at distance (k - frac) input frames from the output's time */
            float t = c0 + (k - frac) * sc;
            if (t < 0 || t >= tmax) continue;
            int ti = (int)t;
            float f = t - ti, c = r->table[ti] + (r->table[ti + 1] - r->table[ti]) * f;
            al += c * r->buf[0][ip + k];
            ar += c * r->buf[1][ip + k];
        }
        l[m] = al;
        rt[m] = ar;
        m++;
        r->pos += r->step;
    }
    int drop = (int)floor(r->pos) - r->half;   /* frames no output will touch again */
    if (drop > 0) {
        memmove(r->buf[0], r->buf[0] + drop, sizeof(float) * (r->len - drop));
        memmove(r->buf[1], r->buf[1] + drop, sizeof(float) * (r->len - drop));
        r->len -= drop;
        r->pos -= drop;
    }
    return m;
}

#endif
