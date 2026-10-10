#include "play.h"
#include "mxgrp.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum { SR = 44100 };

typedef struct {
    int kind;
    float p[MX_PAR];
    int n;
    float lfo, z, z2, env, holdv;
    int wp, holdn;
    uint32_t rng;
    float *mem;
    int mlen;
    float *comb[4];
    int clen[4], cw[4];
    float *ap[2];
    int alen[2], aw[2];
    float apz[4];
} Fx;

typedef struct {
    MxPad desc;
    int16_t *pcm;
    int frames;
    int on, age, fade, tail, played, tail_done;
    double pos, ph, ph2;
    float vel, lp, lp2;
    uint32_t rng;
    Fx fx[MX_FX];
} Voice;

struct PlayKit {
    MxGroup g;
    Voice v[MX_PADS];
    Fx gfx[MX_FX];
    int missing;
    int focused;
    char status[160];
    char info[160];
    float bpm;
    int prev_on;
    int prev_len;
    int prev_nev;
    int prev_pad[MX_EV];
    int prev_tick[MX_EV];
    int prev_vel[MX_EV];
    double prev_pos;
    int mout_n;
    uint8_t mout[64][4]; /* frame, status, note, velocity */
    int held[16];
    double off_at[16];
};

static float kn(const float *p, int n, int i, float def) {
    if (i < 0 || i >= n) return def;
    if (p[i] < 0.f || p[i] > 1.05f) return def;
    float x = p[i];
    return x < 0 ? 0 : x > 1 ? 1 : x;
}

static float last_kn(const float *p, int n, float def) {
    for (int i = n - 1; i >= 0; i--) {
        if (p[i] > 0.001f && p[i] <= 1.05f) return p[i] > 1.f ? 1.f : p[i];
    }
    return def;
}

static float nz(uint32_t *s) {
    *s = *s * 1664525u + 1013904223u;
    return (float)(int)((*s >> 16) & 0xffff) / 32768.f - 1.f;
}

static void fx_clear(Fx *f) {
    free(f->mem);
    for (int i = 0; i < 4; i++) free(f->comb[i]);
    for (int i = 0; i < 2; i++) free(f->ap[i]);
    memset(f, 0, sizeof *f);
}

static void fx_setup(Fx *f, int kind, const float *p, int n) {
    fx_clear(f);
    f->kind = kind;
    f->n = n > MX_PAR ? MX_PAR : n;
    if (f->n) memcpy(f->p, p, (size_t)f->n * sizeof(float));
    f->rng = 0x1234567u;
    if (kind == MXFX_CHORUS || kind == MXFX_FLANGER || kind == MXFX_DELAY) {
        f->mlen = kind == MXFX_DELAY ? 24000 : 4096;
        f->mem = calloc((size_t)f->mlen, sizeof(float));
    } else if (kind == MXFX_REVERB) {
        static const int cl[4] = {1557, 1617, 1491, 1422};
        static const int al[2] = {225, 341};
        for (int i = 0; i < 4; i++) {
            f->clen[i] = cl[i];
            f->comb[i] = calloc((size_t)cl[i], sizeof(float));
        }
        for (int i = 0; i < 2; i++) {
            f->alen[i] = al[i];
            f->ap[i] = calloc((size_t)al[i], sizeof(float));
        }
    }
}

static float rd(const float *m, int len, int w, float delay) {
    if (!m || len < 2) return 0;
    if (delay < 1) delay = 1;
    if (delay > len - 2) delay = (float)(len - 2);
    float x = (float)w - delay;
    while (x < 0) x += len;
    int i0 = (int)x;
    float fr = x - (float)i0;
    int i1 = i0 + 1;
    if (i1 >= len) i1 = 0;
    return m[i0] * (1.f - fr) + m[i1] * fr;
}

static float allpass(float *z, float x, float a) {
    float y = -a * x + *z;
    *z = x + a * y;
    return y;
}

static float fx_one(Fx *f, float x) {
    float *p = f->p;
    int n = f->n;
    switch (f->kind) {
    case MXFX_SAT: {
        float d = 1.f + kn(p, n, 0, 0.35f) * 8.f;
        float y = tanhf(x * d) / tanhf(d);
        float mix = last_kn(p, n, 0.8f);
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_LIMIT: {
        float amt = kn(p, n, 0, 0.6f);
        float a = fabsf(x);
        f->env += (a - f->env) * (a > f->env ? 0.2f : 0.002f);
        float ceil = 0.92f - amt * 0.15f;
        float g = (f->env > ceil && f->env > 1e-6f) ? ceil / f->env : 1.f;
        return x * (1.f - amt) + x * g * amt;
    }
    case MXFX_MAX: {
        float amt = kn(p, n, 0, 0.5f);
        float y = x * (1.f + amt * 2.5f);
        float a = fabsf(y);
        f->env += (a - f->env) * (a > f->env ? 0.4f : 0.005f);
        if (f->env > 0.9f) y *= 0.9f / f->env;
        return tanhf(y);
    }
    case MXFX_COMP: {
        float amt = kn(p, n, 0, 0.5f);
        float a = fabsf(x);
        f->env += (a - f->env) * (a > f->env ? 0.05f : 0.002f);
        float th = 0.35f - amt * 0.2f;
        float g = 1.f;
        if (f->env > th) g = th / f->env;
        g = 1.f + (g - 1.f) * (0.4f + amt);
        return x * g * (1.f + amt * 0.6f);
    }
    case MXFX_GATE: {
        float amt = kn(p, n, 0, 0.f);
        if (amt < 0.02f) return x;
        float th = 0.01f + kn(p, n, 1, 0.5f) * 0.08f;
        if (fabsf(x) >= th) f->env = 1.f;
        else f->env *= 0.95f;
        float g = f->env < 0.05f ? 0.f : f->env;
        return x * (1.f - amt) + x * g * amt;
    }
    case MXFX_LOFI: {
        int hold = 1 + (int)(kn(p, n, 0, 0.4f) * 7.f);
        if (++f->holdn >= hold) { f->holdv = x; f->holdn = 0; }
        float y = f->holdv;
        int bits = 12 - (int)(kn(p, n, 1, 0.4f) * 7.f);
        if (bits < 4) bits = 4;
        float q = powf(2.f, (float)bits);
        y = rintf(y * q) / q;
        float mix = last_kn(p, n, 0.85f);
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_CHORUS: {
        if (!f->mem) return x;
        float rate = 0.15f + kn(p, n, 0, 0.3f) * 2.5f;
        float depth = 80.f + kn(p, n, 1, 0.4f) * 280.f;
        float mix = kn(p, n, 2, last_kn(p, n, 0.35f));
        f->lfo += 2.f * 3.14159265f * rate / SR;
        if (f->lfo > 6.28f) f->lfo -= 6.28f;
        float d = 220.f + depth * (0.5f + 0.5f * sinf(f->lfo));
        float y = rd(f->mem, f->mlen, f->wp, d);
        f->mem[f->wp] = x;
        if (++f->wp >= f->mlen) f->wp = 0;
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_FLANGER: {
        if (!f->mem) return x;
        float rate = 0.08f + kn(p, n, 0, 0.4f) * 1.5f;
        float depth = 20.f + kn(p, n, 1, 0.5f) * 160.f;
        float fb = kn(p, n, 2, 0.35f) * 0.65f;
        float mix = kn(p, n, 3, last_kn(p, n, 0.4f));
        f->lfo += 2.f * 3.14159265f * rate / SR;
        float d = 40.f + depth * (0.5f + 0.5f * sinf(f->lfo));
        float y = rd(f->mem, f->mlen, f->wp, d);
        f->mem[f->wp] = x + y * fb;
        if (++f->wp >= f->mlen) f->wp = 0;
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_PHASER: {
        float rate = 0.1f + kn(p, n, 0, 0.35f) * 2.f;
        float mix = last_kn(p, n, 0.4f);
        f->lfo += 2.f * 3.14159265f * rate / SR;
        float a = 0.2f + 0.7f * (0.5f + 0.5f * sinf(f->lfo));
        float y = x;
        for (int i = 0; i < 4; i++) y = allpass(&f->apz[i], y, a);
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_DELAY: {
        if (!f->mem) return x;
        float time = 0.08f + kn(p, n, 0, 0.4f) * 0.38f;
        float fb = kn(p, n, 1, 0.35f) * 0.8f;
        float mix = n >= 3 ? last_kn(p, n, 0.3f) : 0.3f;
        int di = (int)(time * SR);
        if (di < 1) di = 1;
        if (di >= f->mlen) di = f->mlen - 1;
        int r = f->wp - di;
        if (r < 0) r += f->mlen;
        float y = f->mem[r];
        float w = x + y * fb;
        if (w > 1.5f) w = 1.5f;
        else if (w < -1.5f) w = -1.5f;
        f->mem[f->wp] = w;
        if (++f->wp >= f->mlen) f->wp = 0;
        return x * (1.f - mix) + y * mix;
    }
    case MXFX_REVERB: {
        if (!f->comb[0]) return x;
        float room = 0.55f + kn(p, n, 0, 0.55f) * 0.4f;
        float damp = kn(p, n, 1, 0.4f);
        float mix = last_kn(p, n, 0.25f);
        if (mix > 0.85f) mix = 0.85f;
        float acc = 0;
        float in = x * 0.35f;
        for (int i = 0; i < 4; i++) {
            float y = f->comb[i][f->cw[i]];
            f->z += (y - f->z) * (0.15f + damp * 0.5f);
            float w = in + f->z * room;
            if (w > 2.f) w = 2.f;
            else if (w < -2.f) w = -2.f;
            f->comb[i][f->cw[i]] = w;
            if (++f->cw[i] >= f->clen[i]) f->cw[i] = 0;
            acc += y;
        }
        acc *= 0.25f;
        for (int i = 0; i < 2; i++) {
            float buf = f->ap[i][f->aw[i]];
            float y = -0.5f * acc + buf;
            f->ap[i][f->aw[i]] = acc + 0.5f * y;
            if (++f->aw[i] >= f->alen[i]) f->aw[i] = 0;
            acc = y;
        }
        return x * (1.f - mix) + acc * mix;
    }
    default:
        return x;
    }
}

static int fx_tails(const Fx *f, int nfx) {
    for (int i = 0; i < nfx; i++) {
        int k = f[i].kind;
        if (k == MXFX_DELAY || k == MXFX_REVERB || k == MXFX_CHORUS || k == MXFX_FLANGER) return 1;
    }
    return 0;
}

static float synth(Voice *v, const MxPad *p, int *done) {
    const float *sp = p->sp;
    int ns = p->ns;
    float tune = kn(sp, ns, 0, 0.5f);
    float dec = kn(sp, ns, 1, 0.45f);
    float tone = kn(sp, ns, 2, 0.5f);
    float t = (float)v->age / SR;
    float s = 0;
    *done = 0;
    switch (p->src) {
    case MX_KICK: {
        float f0 = 36.f * powf(2.f, (tune - 0.45f) * 2.4f);
        float env = expf(-t / (0.06f + dec * 1.05f));
        float f = f0 * (1.f + (0.4f + tone) * 7.f * env);
        v->ph += 2.0 * 3.1415926535 * f / SR;
        float click = nz(&v->rng) * expf(-t / 0.0035f);
        s = sinf((float)v->ph) * env * 0.9f + click * 0.28f;
        if (env < 0.0008f) *done = 1;
        break;
    }
    case MX_SNARE: {
        float f0 = 160.f * powf(2.f, (tune - 0.5f) * 1.6f);
        float body = expf(-t / (0.03f + dec * 0.16f));
        float nenv = expf(-t / (0.04f + dec * 0.22f));
        v->ph += 2.0 * 3.1415926535 * f0 / SR;
        float n = nz(&v->rng);
        v->lp += (n - v->lp) * (0.15f + tone * 0.5f);
        s = sinf((float)v->ph) * body * 0.45f + (n - v->lp) * nenv * 0.55f;
        if (nenv < 0.001f) *done = 1;
        break;
    }
    case MX_HAT: {
        float open = strstr(p->name, "Open") ? 2.4f : 1.f;
        float nenv = expf(-t / ((0.012f + dec * 0.12f) * open));
        float n = nz(&v->rng);
        float c = 0.25f + tone * 0.65f;
        v->lp += (n - v->lp) * c;
        v->lp2 += (v->lp - v->lp2) * c;
        s = (n - v->lp2) * nenv * 0.55f;
        if (nenv < 0.001f) *done = 1;
        break;
    }
    case MX_TOM: {
        float f0 = 70.f * powf(2.f, (tune - 0.4f) * 2.2f);
        float env = expf(-t / (0.05f + dec * 0.55f));
        float f = f0 * (1.f + tone * 3.f * env);
        v->ph += 2.0 * 3.1415926535 * f / SR;
        s = sinf((float)v->ph) * env * 0.85f;
        if (env < 0.001f) *done = 1;
        break;
    }
    case MX_PERC: {
        float f0 = 180.f * powf(2.f, (tune - 0.5f) * 2.5f);
        float env = expf(-t / (0.02f + dec * 0.28f));
        v->ph += 2.0 * 3.1415926535 * f0 / SR;
        float n = nz(&v->rng);
        s = (sinf((float)v->ph) * (1.f - tone) + n * tone) * env * 0.6f;
        if (env < 0.001f) *done = 1;
        break;
    }
    case MX_CYM: {
        float env = expf(-t / (0.08f + dec * 1.3f));
        float n = nz(&v->rng);
        v->ph += 2.0 * 3.1415926535 * (280.f * powf(2.f, (tune - 0.5f) * 1.5f)) / SR;
        v->ph2 += 2.0 * 3.1415926535 * 647.f / SR;
        float metal = sinf((float)v->ph) * 0.3f + sinf((float)v->ph2) * 0.2f + sinf((float)(v->ph * 1.63)) * 0.15f;
        v->lp += (n - v->lp) * 0.4f;
        s = (metal + (n - v->lp) * 0.45f) * env * 0.45f;
        if (env < 0.0008f || t > 3.f) *done = 1;
        break;
    }
    default:
        *done = 1;
        break;
    }
    v->age++;
    if (v->age > SR * 4) *done = 1;
    return s;
}

static int le16(const uint8_t *p) { return p[0] | (p[1] << 8); }
static int le32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | (p[3] << 24); }

static int chunk(const uint8_t *d, int n, const char *id, int *off, int *sz) {
    int i = 12;
    while (i + 8 <= n) {
        int csz = le32(d + i + 4);
        if (csz < 0 || csz > n) return 0;
        if (memcmp(d + i, id, 4) == 0) { *off = i + 8; *sz = csz; return 1; }
        i += 8 + csz + (csz & 1);
        if (i < 0) return 0;
    }
    return 0;
}

/* Mono int16 at 44100. start/end are source-file frames and come back scaled. */
static int16_t *load_wav(const char *path, int *frames, int *start, int *end) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    if (sz < 44 || sz > 32 * 1024 * 1024) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *d = malloc((size_t)sz);
    if (!d || fread(d, 1, (size_t)sz, f) != (size_t)sz) { fclose(f); free(d); return NULL; }
    fclose(f);
    if (memcmp(d, "RIFF", 4) || memcmp(d + 8, "WAVE", 4)) { free(d); return NULL; }
    int fo = 0, fs = 0, dao = 0, das = 0;
    if (!chunk(d, (int)sz, "fmt ", &fo, &fs) || fs < 16 || !chunk(d, (int)sz, "data", &dao, &das)) {
        free(d);
        return NULL;
    }
    int format = le16(d + fo);
    int ch = le16(d + fo + 2);
    int rate = le32(d + fo + 4);
    int bits = le16(d + fo + 14);
    if (ch < 1 || ch > 2 || rate < 8000 || rate > 192000) { free(d); return NULL; }
    if (dao + das > (int)sz) das = (int)sz - dao;
    int bpf = ch * (bits / 8);
    if (bpf < 1) { free(d); return NULL; }
    int src_n = das / bpf;
    if (src_n < 1) { free(d); return NULL; }
    if (*end <= 0 || *end > src_n) *end = src_n;
    if (*start < 0) *start = 0;
    if (*start >= *end) *start = 0;

    double ratio = (double)rate / (double)SR;
    int out_n = (int)((double)src_n / ratio + 1);
    if (out_n > SR * 20) out_n = SR * 20;
    int16_t *pcm = calloc((size_t)out_n + 2, sizeof(int16_t));
    if (!pcm) { free(d); return NULL; }

    for (int i = 0; i < out_n; i++) {
        double sp = (double)i * ratio;
        int i0 = (int)sp;
        if (i0 >= src_n) { out_n = i; break; }
        int i1 = i0 + 1 < src_n ? i0 + 1 : i0;
        float fr = (float)(sp - i0);
        float acc = 0;
        for (int c = 0; c < ch; c++) {
            float a = 0, b = 0;
            const uint8_t *p0 = d + dao + (i0 * ch + c) * (bits / 8);
            const uint8_t *p1 = d + dao + (i1 * ch + c) * (bits / 8);
            if (format == 1 && bits == 16) {
                a = (int16_t)le16(p0);
                b = (int16_t)le16(p1);
            } else if (format == 1 && bits == 24) {
                int v0 = p0[0] | (p0[1] << 8) | (p0[2] << 16);
                int v1 = p1[0] | (p1[1] << 8) | (p1[2] << 16);
                if (v0 & 0x800000) v0 |= ~0xffffff;
                if (v1 & 0x800000) v1 |= ~0xffffff;
                a = (float)v0 / 256.f;
                b = (float)v1 / 256.f;
            } else if (format == 3 && bits == 32) {
                float fa, fb;
                memcpy(&fa, p0, 4);
                memcpy(&fb, p1, 4);
                a = fa * 32767.f;
                b = fb * 32767.f;
            } else {
                free(pcm);
                free(d);
                return NULL;
            }
            acc += a * (1.f - fr) + b * fr;
        }
        acc /= (float)ch;
        if (acc > 32767) acc = 32767;
        if (acc < -32768) acc = -32768;
        pcm[i] = (int16_t)acc;
    }
    free(d);
    *start = (int)((double)*start / ratio);
    *end = (int)((double)*end / ratio);
    if (*end > out_n) *end = out_n;
    if (*start >= *end) *start = 0;
    *frames = out_n;
    return pcm;
}

static int is_file(const char *p) {
    struct stat st;
    return stat(p, &st) == 0 && S_ISREG(st.st_mode);
}

static int find_root(const char *file, char *out, int n) {
    char dir[512];
    snprintf(dir, sizeof dir, "%s", file);
    for (int up = 0; up < 8; up++) {
        char *sl = strrchr(dir, '/');
        if (!sl || sl == dir) break;
        *sl = 0;
        char probe[540];
        snprintf(probe, sizeof probe, "%s/Samples", dir);
        struct stat st;
        if (stat(probe, &st) == 0 && S_ISDIR(st.st_mode)) {
            snprintf(out, (size_t)n, "%s", dir);
            return 1;
        }
    }
    return 0;
}

/* The group stores library paths like Samples/Drums/Kick/Kick.wav. Prefer that
 * under a Samples/ folder. Otherwise accept the same path with Samples/ omitted
 * (One Shots/… next to a parent of the group) or the bare filename beside the group. */
static int resolve_sample(const char *mxgrp, const char *rel, char *out, int n) {
    char root[512];
    if (find_root(mxgrp, root, sizeof root)) {
        snprintf(out, (size_t)n, "%s/%s", root, rel);
        if (is_file(out)) return 1;
    }
    const char *rest = rel;
    if (!strncmp(rel, "Samples/", 8)) rest = rel + 8;
    const char *base = strrchr(rel, '/');
    base = base ? base + 1 : rel;

    char dir[512];
    snprintf(dir, sizeof dir, "%s", mxgrp);
    for (int up = 0; up < 8; up++) {
        char *sl = strrchr(dir, '/');
        if (!sl || sl == dir) break;
        *sl = 0;
        if (rest[0]) {
            snprintf(out, (size_t)n, "%s/%s", dir, rest);
            if (is_file(out)) return 1;
        }
        if (up == 0 && base[0]) {
            snprintf(out, (size_t)n, "%s/%s", dir, base);
            if (is_file(out)) return 1;
        }
    }
    return 0;
}

static void voice_reset_src(Voice *v, int pad) {
    v->on = 1;
    v->age = 0;
    v->fade = 0;
    v->tail = 0;
    v->played = 1;
    v->tail_done = 0;
    v->pos = v->desc.start;
    v->ph = v->ph2 = 0;
    v->lp = v->lp2 = 0;
    v->rng = 0xA5A5u * (uint32_t)(pad + 1) + 1u;
}

PlayKit *play_load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    if (n < 64 || n > 4 * 1024 * 1024) { fclose(f); return NULL; }
    rewind(f);
    uint8_t *d = malloc((size_t)n);
    if (!d || fread(d, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(d); return NULL; }
    fclose(f);
    PlayKit *k = calloc(1, sizeof *k);
    if (!k || mx_parse(d, (int)n, &k->g) != 0) { free(d); free(k); return NULL; }
    free(d);

    for (int i = 0; i < k->g.npad; i++) {
        Voice *v = &k->v[i];
        v->desc = k->g.pad[i];
        if (v->desc.src == MX_SAMPLE && v->desc.sample[0]) {
            char full[768];
            int st = v->desc.start, en = v->desc.end, fr = 0;
            if (resolve_sample(path, v->desc.sample, full, sizeof full))
                v->pcm = load_wav(full, &fr, &st, &en);
            if (v->pcm) {
                v->frames = fr;
                v->desc.start = st;
                v->desc.end = en;
            } else {
                k->missing++;
            }
        } else if (v->desc.src == MX_SAMPLE) {
            k->missing++;
        }
        for (int fx = 0; fx < v->desc.nfx; fx++)
            fx_setup(&v->fx[fx], v->desc.fx[fx].kind, v->desc.fx[fx].p, v->desc.fx[fx].n);
    }
    for (int i = 0; i < k->g.ngfx; i++)
        fx_setup(&k->gfx[i], k->g.gfx[i].kind, k->g.gfx[i].p, k->g.gfx[i].n);

    int samples = 0, synths = 0;
    for (int i = 0; i < k->g.npad; i++) {
        if (k->g.pad[i].src == MX_SAMPLE) samples++;
        else if (k->g.pad[i].src != MX_EMPTY) synths++;
    }
    if (k->missing && samples > 0 && k->missing == samples)
        snprintf(k->status, sizeof k->status, "%s · library not found", k->g.name);
    else if (k->missing)
        snprintf(k->status, sizeof k->status, "%s · %d sample%s missing", k->g.name, k->missing, k->missing == 1 ? "" : "s");
    else if (samples && !synths)
        snprintf(k->status, sizeof k->status, "%s · %d samples", k->g.name, samples);
    else if (synths && !samples)
        snprintf(k->status, sizeof k->status, "%s · drumsynth", k->g.name);
    else
        snprintf(k->status, sizeof k->status, "%s · %d sounds", k->g.name, k->g.npad);
    if (k->g.group_fx[0]) {
        int used = (int)strlen(k->status);
        snprintf(k->status + used, sizeof k->status - (size_t)used, " · %s", k->g.group_fx);
    }
    snprintf(k->info, sizeof k->info, "%s", k->g.npad ? k->v[0].desc.chain : "");
    k->focused = 0;
    k->bpm = 120.f;
    return k;
}

void play_free(PlayKit *k) {
    if (!k) return;
    for (int i = 0; i < MX_PADS; i++) {
        free(k->v[i].pcm);
        for (int f = 0; f < MX_FX; f++) fx_clear(&k->v[i].fx[f]);
    }
    for (int f = 0; f < MX_FX; f++) fx_clear(&k->gfx[f]);
    free(k);
}

void play_note(PlayKit *k, int note, int vel) {
    if (!k) return;
    /* Four rows of four. Chromatic C puts the bottom-left pad on MIDI 48, and each
     * row is four notes higher, so note % 16 is the pad (48 is pad 1, bottom left).
     * Notes 0–15 are the same pads, which is what a drum-bank patch sends. */
    int pad = (note >= 0 && note < 128) ? (note % MX_PADS) : -1;
    if (pad < 0) return;
    if (pad >= k->g.npad) return;
    if (vel <= 0) {
        if (k->v[pad].desc.loop) {
            k->v[pad].on = 0;
            k->v[pad].fade = 64;
        }
        return;
    }
    Voice *v = &k->v[pad];
    for (int c = 0; c < v->desc.nchoke; c++) {
        int t = v->desc.choke[c];
        if (t >= 0 && t < MX_PADS && k->v[t].on) {
            k->v[t].on = 0;
            k->v[t].fade = 48;
        }
    }
    v->vel = vel / 127.f;
    if (v->vel < 0.05f) v->vel = 0.05f;
    voice_reset_src(v, pad);
    k->focused = pad;
    snprintf(k->info, sizeof k->info, "%s", v->desc.chain);
}

static float voice_sample(Voice *v, int *alive, int fx_on) {
    *alive = 0;
    if (!v->on && v->fade <= 0 && v->tail <= 0 && !v->played) return 0;
    MxPad *p = &v->desc;
    float s = 0;
    int producing = v->on || v->fade > 0;
    if (producing && p->src == MX_SAMPLE && v->pcm && p->end > p->start) {
        if (v->pos >= p->end) {
            if (p->loop && v->on) v->pos = p->start;
            else { v->on = 0; v->pos = p->end; }
        }
        if (v->pos < p->end) {
            int i0 = (int)v->pos;
            if (i0 < 0) i0 = 0;
            int i1 = i0 + 1;
            if (i1 >= v->frames) i1 = v->frames - 1;
            if (i0 >= v->frames) i0 = v->frames - 1;
            float fr = (float)(v->pos - (int)v->pos);
            s = ((float)v->pcm[i0] * (1.f - fr) + (float)v->pcm[i1] * fr) / 32768.f;
            double step = pow(2.0, (double)p->tune / 12.0);
            v->pos += step;
            *alive = 1;
        }
    } else if (producing && p->src != MX_SAMPLE && p->src != MX_EMPTY) {
        int done = 0;
        s = synth(v, p, &done);
        if (done) v->on = 0;
        else *alive = 1;
    } else if (v->on) {
        v->on = 0; /* sample missing, or an empty pad */
    }
    if (v->fade > 0) {
        s *= (float)v->fade / 64.f;
        v->fade--;
        *alive = 1;
    }
    if (!*alive) {
        if (!v->tail_done && v->played && fx_on && fx_tails(v->fx, p->nfx)) {
            v->tail = SR;
            v->tail_done = 1;
        }
        if (v->tail > 0) {
            v->tail--;
            *alive = 1;
            s = 0;
        } else {
            v->played = 0;
        }
    }
    if (*alive) {
        s *= p->gain * v->vel;
        if (fx_on)
            for (int i = 0; i < p->nfx; i++) s = fx_one(&v->fx[i], s);
    }
    return s;
}

enum { MIDI_CH = 0, MIDI_GATE = 240 }; /* channel 1, so a recorded clip plays on a normal track. A 16th-note gate. */

static void midi_push(PlayKit *k, int frame, int status, int note, int vel) {
    if (!k || k->mout_n >= 64 || note < 0 || note > 127) return;
    if (frame < 0) frame = 0;
    if (frame > 255) frame = 255;
    k->mout[k->mout_n][0] = (uint8_t)frame;
    k->mout[k->mout_n][1] = (uint8_t)status;
    k->mout[k->mout_n][2] = (uint8_t)note;
    k->mout[k->mout_n][3] = (uint8_t)vel;
    k->mout_n++;
}

static void midi_close_held(PlayKit *k) {
    for (int p = 0; p < 16; p++) {
        if (k->held[p]) midi_push(k, 0, 0x80 | MIDI_CH, 48 + p, 0);
        k->held[p] = 0;
        k->off_at[p] = -1;
    }
}

/* Hits and scheduled note-offs whose tick falls in [lo, hi). */
static void preview_window(PlayKit *k, double lo, double hi, int frame0, int frames) {
    if (hi <= lo || frames <= 0) return;
    typedef struct { double at; int pad, note, vel, on; } Slot;
    Slot ev[MX_EV + 16];
    int n = 0;
    int first[16];
    for (int p = 0; p < 16; p++) first[p] = -1;
    for (int i = 0; i < k->prev_nev; i++) {
        int pad = k->prev_pad[i];
        double tick = k->prev_tick[i];
        if (pad < 0 || pad >= 16 || tick < lo || tick >= hi) continue;
        if (first[pad] < 0 || tick < k->prev_tick[first[pad]]) first[pad] = i;
    }
    for (int p = 0; p < 16; p++) {
        if (!k->held[p]) continue;
        double at = k->off_at[p];
        if (at < lo || at >= hi) continue;
        if (first[p] >= 0 && k->prev_tick[first[p]] <= at) continue;
        if (n < (int)(sizeof ev / sizeof ev[0])) ev[n++] = (Slot){ at, p, 48 + p, 0, 0 };
    }
    for (int i = 0; i < k->prev_nev; i++) {
        int pad = k->prev_pad[i];
        double tick = k->prev_tick[i];
        if (pad < 0 || pad >= 16 || tick < lo || tick >= hi) continue;
        int vel = k->prev_vel[i] > 0 ? k->prev_vel[i] : 100;
        if (vel > 127) vel = 127;
        if (n < (int)(sizeof ev / sizeof ev[0])) ev[n++] = (Slot){ tick, pad, 48 + pad, vel, 1 };
    }
    for (int i = 1; i < n; i++) {
        Slot s = ev[i];
        int j = i;
        while (j > 0 && (ev[j - 1].at > s.at || (ev[j - 1].at == s.at && ev[j - 1].on > s.on))) {
            ev[j] = ev[j - 1];
            j--;
        }
        ev[j] = s;
    }
    double span = hi - lo;
    for (int i = 0; i < n; i++) {
        int frame = frame0 + (span > 0 ? (int)((ev[i].at - lo) / span * frames) : 0);
        if (frame < 0) frame = 0;
        if (frame > 255) frame = 255;
        if (ev[i].on) {
            if (k->held[ev[i].pad]) midi_push(k, frame, 0x80 | MIDI_CH, ev[i].note, 0);
            play_note(k, ev[i].pad, ev[i].vel);
            midi_push(k, frame, 0x90 | MIDI_CH, ev[i].note, ev[i].vel);
            k->held[ev[i].pad] = 1;
            double off = ev[i].at + MIDI_GATE;
            if (k->prev_len > 0 && off >= k->prev_len) off -= k->prev_len;
            k->off_at[ev[i].pad] = off;
        } else if (k->held[ev[i].pad]) {
            midi_push(k, frame, 0x80 | MIDI_CH, ev[i].note, 0);
            k->held[ev[i].pad] = 0;
        }
    }
}

static void preview_advance(PlayKit *k, int frames) {
    if (!k || !k->prev_on || k->prev_len <= 0 || k->prev_nev <= 0 || frames <= 0) return;
    float bpm = k->bpm > 1.f ? k->bpm : 120.f;
    double ticks = (double)frames * ((double)bpm / 60.0) * 960.0 / (double)SR;
    double t = k->prev_pos;
    double end = t + ticks;
    if (end <= k->prev_len) {
        preview_window(k, t, end, 0, frames);
    } else {
        double first = (double)k->prev_len - t;
        int f0 = ticks > 0 ? (int)(first / ticks * frames) : 0;
        if (f0 < 0) f0 = 0;
        if (f0 > frames) f0 = frames;
        if (f0 > 0) preview_window(k, t, (double)k->prev_len, 0, f0);
        if (frames - f0 > 0) preview_window(k, 0, end - k->prev_len, f0, frames - f0);
    }
    k->prev_pos = end >= k->prev_len ? end - k->prev_len : end;
    if (k->prev_pos < 0) k->prev_pos = 0;
}

void play_render(PlayKit *k, int16_t *lr, int frames, float master, int fx_on) {
    if (k) preview_advance(k, frames);
    for (int i = 0; i < frames; i++) {
        float L = 0, R = 0;
        if (k) {
            for (int p = 0; p < k->g.npad; p++) {
                int alive = 0;
                float s = voice_sample(&k->v[p], &alive, fx_on);
                if (!alive) continue;
                float pan = k->v[p].desc.pan;
                float pl = pan < 0 ? 1.f : 1.f - pan;
                float pr = pan > 0 ? 1.f : 1.f + pan;
                L += s * pl;
                R += s * pr;
            }
            if (fx_on) {
                float m = 0.5f * (L + R);
                for (int g = 0; g < k->g.ngfx; g++) m = fx_one(&k->gfx[g], m);
                /* keep a little of the stereo pan by blending the wet mono back */
                float side = 0.5f * (L - R);
                L = m + side;
                R = m - side;
            }
        }
        L *= master;
        R *= master;
        if (L > 1.f) L = 1.f;
        if (L < -1.f) L = -1.f;
        if (R > 1.f) R = 1.f;
        if (R < -1.f) R = -1.f;
        lr[2 * i] = (int16_t)(L * 32000.f);
        lr[2 * i + 1] = (int16_t)(R * 32000.f);
    }
}

/* FX bypass has to skip the inserts. voice_sample always runs them; split that. */
int play_npad(const PlayKit *k) { return k ? k->g.npad : 0; }
const char *play_pad_name(const PlayKit *k, int pad) {
    if (!k || pad < 0 || pad >= k->g.npad) return "";
    return k->v[pad].desc.name;
}

static int name_has(const char *s, const char *w) {
    if (!s || !w || !w[0]) return 0;
    for (; *s; s++) {
        const char *a = s, *b = w;
        while (*a && *b) {
            char ca = (*a >= 'A' && *a <= 'Z') ? (char)(*a + 32) : *a;
            char cb = (*b >= 'A' && *b <= 'Z') ? (char)(*b + 32) : *b;
            if (ca != cb) break;
            a++;
            b++;
        }
        if (!*b) return 1;
    }
    return 0;
}

int play_pad_tint(const char *name) {
    if (!name || !name[0] || !strcmp(name, "—")) return 0;
    if (name_has(name, "kick") || name_has(name, "bass drum") || name_has(name, "bassdrum")) return 1;
    if (name_has(name, "hh") || name_has(name, "hat") || name_has(name, "shaker") || name_has(name, "shake") ||
        name_has(name, "cymbal") || name_has(name, "ride") || name_has(name, "crash") ||
        name_has(name, "china") || name_has(name, "splash")) return 3;
    if (name_has(name, "snare") || name_has(name, "clap") || name_has(name, "rim")) return 2;
    if (name_has(name, "tom")) return 5;
    if (name_has(name, "perc") || name_has(name, "conga") || name_has(name, "bongo") || name_has(name, "tamb") ||
        name_has(name, "cowbell") || name_has(name, "clave") || name_has(name, "wood") || name_has(name, "block") ||
        name_has(name, "agogo") || name_has(name, "guiro") || name_has(name, "maraca") || name_has(name, "cabasa") ||
        name_has(name, "snap")) return 4;
    return 0;
}
int play_pad_active(const PlayKit *k, int pad) {
    if (!k || pad < 0 || pad >= k->g.npad) return 0;
    return k->v[pad].on || k->v[pad].fade > 0 || k->v[pad].tail > 0 || k->v[pad].played;
}
const char *play_group(const PlayKit *k) { return k ? k->g.name : ""; }
const char *play_status(const PlayKit *k) { return k ? k->status : ""; }
const char *play_info(const PlayKit *k) { return k ? k->info : ""; }

void play_set_bpm(PlayKit *k, float bpm) {
    if (!k) return;
    if (bpm < 20.f || bpm > 400.f) bpm = 120.f;
    k->bpm = bpm;
}

int play_npat(const PlayKit *k) { return k ? k->g.npat : 0; }

const char *play_pat_name(const PlayKit *k, int index) {
    if (!k || index < 0 || index >= k->g.npat) return "";
    return k->g.pat[index].name;
}

int play_pat_events(const PlayKit *k, int index) {
    if (!k || index < 0 || index >= k->g.npat) return 0;
    return k->g.pat[index].nev;
}

static void pat_slice(const PlayKit *k, int index, int cols, const MxPattern **out, int *len) {
    *out = NULL;
    *len = 1;
    if (!k || index < 0 || index >= k->g.npat || cols < 1 || cols > 16) return;
    *out = &k->g.pat[index];
    if ((*out)->length > 0) *len = (*out)->length;
}

static int pat_col(int tick, int len, int cols) {
    int col = (int)((long long)tick * cols / len);
    if (col < 0) col = 0;
    if (col >= cols) col = cols - 1;
    return col;
}

void play_pat_columns(const PlayKit *k, int index, int cols, uint16_t rows[16]) {
    if (rows) memset(rows, 0, 16 * sizeof rows[0]);
    const MxPattern *p;
    int len;
    pat_slice(k, index, cols, &p, &len);
    if (!p || !rows) return;
    for (int i = 0; i < p->nev; i++) {
        int pad = p->ev[i].pad;
        if (pad < 0 || pad >= 16) continue;
        rows[pad] |= (uint16_t)(1u << pat_col(p->ev[i].tick, len, cols));
    }
}

void play_pat_levels(const PlayKit *k, int index, int cols, uint8_t vel[16][16]) {
    if (vel) memset(vel, 0, 16 * 16);
    const MxPattern *p;
    int len;
    pat_slice(k, index, cols, &p, &len);
    if (!p || !vel) return;
    for (int i = 0; i < p->nev; i++) {
        int pad = p->ev[i].pad;
        if (pad < 0 || pad >= 16) continue;
        int col = pat_col(p->ev[i].tick, len, cols);
        int v = p->ev[i].vel;
        if (v < 0) v = 0;
        if (v > 127) v = 127;
        if (v > vel[pad][col]) vel[pad][col] = (uint8_t)v;
    }
}

int play_vel_band(int vel) {
    if (vel <= 0) return 0;
    if (vel < 48) return 1;
    if (vel < 80) return 2;
    if (vel < 108) return 3;
    return 4;
}

void play_preview(PlayKit *k, int index, int on) {
    if (!k) return;
    midi_close_held(k);
    k->prev_on = 0;
    k->prev_nev = 0;
    k->prev_pos = 0;
    if (!on || index < 0 || index >= k->g.npat) return;
    MxPattern *p = &k->g.pat[index];
    k->prev_len = p->length > 0 ? p->length : 960 * 4;
    k->prev_nev = p->nev;
    if (k->prev_nev > MX_EV) k->prev_nev = MX_EV;
    for (int i = 0; i < k->prev_nev; i++) {
        k->prev_pad[i] = p->ev[i].pad;
        k->prev_tick[i] = p->ev[i].tick;
        k->prev_vel[i] = p->ev[i].vel;
    }
    k->prev_on = k->prev_nev > 0;
}

int play_midi_out(PlayKit *k, uint8_t ev[][4], int max) {
    if (!k || !ev || max <= 0) {
        if (k) k->mout_n = 0;
        return 0;
    }
    int n = k->mout_n < max ? k->mout_n : max;
    for (int i = 0; i < n; i++) memcpy(ev[i], k->mout[i], 4);
    k->mout_n = 0;
    return n;
}

int play_pattern_text(const PlayKit *k, int index, char *buf, int n) {
    if (!buf || n <= 0) return 0;
    buf[0] = 0;
    if (!k || index < 0 || index >= k->g.npat) return 0;
    const MxPattern *p = &k->g.pat[index];
    int used = snprintf(buf, (size_t)n, "# pattern: %s\n# ppq: 960\n# length: %d\n# note\ttick\tvelocity\n",
                        p->name, p->length);
    if (used < 0) return 0;
    if (used >= n) used = n - 1;
    for (int i = 0; i < p->nev; i++) {
        int note = 48 + p->ev[i].pad;
        int vel = p->ev[i].vel > 0 ? p->ev[i].vel : 100;
        int w = snprintf(buf + used, (size_t)(n - used), "%d\t%d\t%d\n", note, p->ev[i].tick, vel);
        if (w < 0 || used + w >= n) break;
        used += w;
    }
    return p->nev;
}

static int wr_vlq(uint8_t *p, int cap, unsigned v) {
    uint8_t t[5];
    int n = 0;
    t[n++] = (uint8_t)(v & 0x7f);
    v >>= 7;
    while (v && n < 5) {
        t[n++] = (uint8_t)((v & 0x7f) | 0x80);
        v >>= 7;
    }
    if (n > cap) return -1;
    for (int i = 0; i < n; i++) p[i] = t[n - 1 - i];
    return n;
}

typedef struct { int tick, note, vel, on; } MEv;

static int cmp_mev(const void *a, const void *b) {
    const MEv *x = a, *y = b;
    if (x->tick != y->tick) return x->tick < y->tick ? -1 : 1;
    if (x->on != y->on) return x->on - y->on;
    return x->note - y->note;
}

int play_pattern_midi(const PlayKit *k, int index, int bpm, uint8_t *dst, int dst_n) {
    if (!k || !dst || dst_n < 32 || index < 0 || index >= k->g.npat) return 0;
    const MxPattern *p = &k->g.pat[index];
    int nev = p->nev > MX_EV ? MX_EV : p->nev;
    if (nev <= 0) return 0;
    MEv *ev = calloc((size_t)nev * 2, sizeof *ev);
    if (!ev) return 0;
    int len = p->length > 0 ? p->length : 960 * 4;
    int m = 0;
    for (int i = 0; i < nev; i++) {
        int note = 48 + p->ev[i].pad;
        if (p->ev[i].pad < 0 || p->ev[i].pad > 15 || note > 127) continue;
        int vel = p->ev[i].vel > 0 ? p->ev[i].vel : 100;
        if (vel > 127) vel = 127;
        int on = p->ev[i].tick < 0 ? 0 : p->ev[i].tick;
        int off = on + 120;
        for (int j = 0; j < nev; j++) {
            if (j == i || p->ev[j].pad != p->ev[i].pad) continue;
            int t = p->ev[j].tick;
            if (t > on && t < off) off = t;
        }
        if (off > len) off = len;
        if (off <= on) off = on + 1;
        ev[m++] = (MEv){ on, note, vel, 1 };
        ev[m++] = (MEv){ off, note, 0, 0 };
    }
    if (m == 0) { free(ev); return 0; }
    qsort(ev, (size_t)m, sizeof *ev, cmp_mev);
    if (bpm < 20 || bpm > 400) bpm = 120;
    unsigned tempo = 60000000u / (unsigned)bpm;
    uint8_t *trk = malloc((size_t)m * 8 + 32);
    if (!trk) { free(ev); return 0; }
    int u = 0;
    u += wr_vlq(trk + u, 8, 0);
    trk[u++] = 0xff; trk[u++] = 0x51; trk[u++] = 0x03;
    trk[u++] = (uint8_t)(tempo >> 16); trk[u++] = (uint8_t)(tempo >> 8); trk[u++] = (uint8_t)tempo;
    int at = 0;
    for (int i = 0; i < m; i++) {
        int d = ev[i].tick - at;
        if (d < 0) d = 0;
        int w = wr_vlq(trk + u, 8, (unsigned)d);
        if (w < 0) { free(ev); free(trk); return 0; }
        u += w;
        trk[u++] = (uint8_t)(ev[i].on ? 0x90 : 0x80);
        trk[u++] = (uint8_t)ev[i].note;
        trk[u++] = (uint8_t)(ev[i].on ? ev[i].vel : 0);
        at = ev[i].tick;
    }
    u += wr_vlq(trk + u, 8, 0);
    trk[u++] = 0xff; trk[u++] = 0x2f; trk[u++] = 0x00;
    free(ev);
    if (22 + u > dst_n) { free(trk); return 0; }
    memcpy(dst, "MThd", 4);
    dst[4] = 0; dst[5] = 0; dst[6] = 0; dst[7] = 6;
    dst[8] = 0; dst[9] = 0;
    dst[10] = 0; dst[11] = 1;
    dst[12] = (uint8_t)(960 >> 8); dst[13] = (uint8_t)(960 & 0xff);
    memcpy(dst + 14, "MTrk", 4);
    dst[18] = (uint8_t)(u >> 24); dst[19] = (uint8_t)(u >> 16);
    dst[20] = (uint8_t)(u >> 8); dst[21] = (uint8_t)u;
    memcpy(dst + 22, trk, (size_t)u);
    free(trk);
    return 22 + u;
}
