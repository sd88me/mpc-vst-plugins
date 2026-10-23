/* Maschine 2 .mxgrp → pads.
 *
 * The file is an NI container around one Boost binary archive. Each row is
 * indexed with a width-prefixed little-endian number (the same layout
 * ConvertWithMoss walks). Class names are stored once ("NI::MASCHINE::DATA::Sampler")
 * and later sounds refer to that class by id. A sampler zone is  the block of
 * rows documented for the post-0x0D preset: path, then start/end/loop/root/gain/pan/tune
 * at fixed distances. Knob rows are a float stored twice (value, value) plus a 0, 0.5 or 1 flag.
 */
#include "mxgrp.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int read_varint(const uint8_t *d, int n, int i, int *v) {
    if (i >= n) return -1;
    int w = d[i++];
    if (w < 1 || w > 4 || i + w > n) return -1;
    int x = 0;
    for (int b = 0; b < w; b++) x |= d[i++] << (8 * b);
    *v = x;
    return i;
}

/* Split the archive body into rows. Returns the row count, or -1. Rows point into a
 * freshly malloc'd index table; the bytes themselves stay in `d`. */
static int split_rows(const uint8_t *d, int n, int begin, const uint8_t ***out_rows, int **out_len) {
    int i = begin;
    int expected = 0;
    int first = 0;
    i = read_varint(d, n, i, &first);
    if (i < 0 || first != 0) return -1;

    int cap = 1024, nrows = 0;
    const uint8_t **rows = malloc((size_t)cap * sizeof *rows);
    int *lens = malloc((size_t)cap * sizeof *lens);
    if (!rows || !lens) { free(rows); free(lens); return -1; }

    while (i <= n) {
        expected++;
        int start = i;
        int next = -1;
        while (i < n) {
            int w = d[i];
            if ((w == 1 || w == 2) && i + 1 + w <= n) {
                int val = w == 1 ? d[i + 1] : (d[i + 1] | (d[i + 2] << 8));
                if (val == expected) {
                    i += 1 + w;
                    next = val;
                    break;
                }
            }
            i++;
        }
        if (nrows == cap) {
            cap *= 2;
            const uint8_t **nr = realloc(rows, (size_t)cap * sizeof *rows);
            int *nl = realloc(lens, (size_t)cap * sizeof *lens);
            if (!nr || !nl) { free(nr ? nr : rows); free(nl ? nl : lens); return -1; }
            rows = nr;
            lens = nl;
        }
        rows[nrows] = d + start;
        if (next >= 0) {
            /* `i` sits just past the width-prefixed index that closed this row. */
            int back = (expected > 255) ? 3 : 2;
            lens[nrows] = (i - back) - start;
        } else {
            lens[nrows] = i - start;
        }
        if (lens[nrows] < 0) lens[nrows] = 0;
        nrows++;
        if (next < 0) break;
    }
    *out_rows = rows;
    *out_len = lens;
    return nrows;
}

static int find_archive(const uint8_t *d, int n) {
    const char *magic = "serialization::archive";
    int mlen = 22;
    for (int i = 0; i + mlen + 13 < n; i++) {
        if (memcmp(d + i, magic, (size_t)mlen) != 0) continue;
        /* version is 7 bytes, then the fixed 00 00 00 01 02 01 */
        int b = i + mlen + 7;
        if (b + 6 <= n && d[b] == 0 && d[b + 1] == 0 && d[b + 2] == 0 &&
            d[b + 3] == 1 && d[b + 4] == 2 && d[b + 5] == 1)
            return b + 6;
    }
    return -1;
}

static int row_float(const uint8_t *c, int n, float *out) {
    if (n < 13 || c[0] != 0) return 0;
    if (memcmp(c + 1, c + 5, 4) != 0) return 0;
    float a, flag;
    memcpy(&a, c + 1, 4);
    memcpy(&flag, c + 9, 4);
    if (a != a || fabsf(a) > 10000.f) return 0;
    if (!(flag == 0.f || fabsf(flag - 0.5f) < 0.02f || fabsf(flag - 1.f) < 0.02f)) return 0;
    *out = a;
    return 1;
}

static int row_int(const uint8_t *c, int n) {
    int i = (n && c[0] == 0) ? 1 : 0;
    int v = 0;
    if (read_varint(c, n, i, &v) < 0) return 0;
    return v;
}

static int name_of(const uint8_t *c, int n, char *out, int out_n) {
    if (n < 4 || c[0] != 0 || c[1] != 1) return 0;
    int len = c[2];
    if (len < 1 || len > 48 || n < 3 + len || n > 3 + len + 1) return 0;
    for (int i = 0; i < len; i++) if (c[3 + i] < 32 || c[3 + i] > 126) return 0;
    if (len >= out_n) len = out_n - 1;
    memcpy(out, c + 3, (size_t)len);
    out[len] = 0;
    return 1;
}

static int class_of(const uint8_t *c, int n, char *name, int name_n, int *id) {
    const char *tag = "NI::MASCHINE::DATA::";
    const int tag_n = 20;
    for (int i = 0; i + tag_n + 1 < n; i++) {
        if (memcmp(c + i, tag, (size_t)tag_n) != 0) continue;
        int k = 0;
        while (i + tag_n + k < n && k < name_n - 1) {
            unsigned char ch = c[i + tag_n + k];
            if (!((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9'))) break;
            name[k++] = (char)ch;
        }
        name[k] = 0;
        *id = -1;
        if (k > 0 && i >= 4 && c[i - 2] == 1 && c[i - 4] == 1) *id = c[i - 3];
        return k > 0;
    }
    return 0;
}

static int ref_id(const uint8_t *c, int n) {
    static const uint8_t pre[8] = {0, 1, 1, 1, 1, 0, 0, 0};
    if (n == 10 && memcmp(c, pre, 8) == 0 && c[8] == 1) return c[9];
    return -1;
}

static int find_sample(const uint8_t *c, int n, char *out, int out_n) {
    const char *key = "Samples/";
    for (int i = 0; i + 12 < n; i++) {
        if (memcmp(c + i, key, 8) != 0) continue;
        int k = 0;
        while (i + k < n && k < out_n - 1 && c[i + k] >= 32 && c[i + k] < 127) {
            out[k] = (char)c[i + k];
            k++;
            if (k >= 4 && memcmp(out + k - 4, ".wav", 4) == 0) {
                out[k] = 0;
                return 1;
            }
        }
    }
    return 0;
}

static int src_kind(const char *name) {
    if (!strcmp(name, "Sampler")) return MX_SAMPLE;
    if (!strcmp(name, "Kick")) return MX_KICK;
    if (!strcmp(name, "Snare")) return MX_SNARE;
    if (!strcmp(name, "Hihat")) return MX_HAT;
    if (!strcmp(name, "Tom")) return MX_TOM;
    if (!strcmp(name, "Perc")) return MX_PERC;
    if (!strcmp(name, "Cymbal")) return MX_CYM;
    return MX_EMPTY;
}

static const char *fx_title(int kind, const char *ni) {
    switch (kind) {
    case MXFX_CHORUS: return "Chorus";
    case MXFX_FLANGER: return "Flanger";
    case MXFX_PHASER: return "Phaser";
    case MXFX_DELAY: return "Delay";
    case MXFX_REVERB: return "Reverb";
    case MXFX_SAT: return "Saturator";
    case MXFX_LIMIT: return "Limiter";
    case MXFX_MAX: return "Maximizer";
    case MXFX_GATE: return "Gate";
    case MXFX_LOFI: return "Lo-Fi";
    case MXFX_COMP: return "Compressor";
    default: return ni;
    }
}

static int fx_kind(const char *name) {
    if (!strcmp(name, "Chorus")) return MXFX_CHORUS;
    if (!strcmp(name, "Flanger")) return MXFX_FLANGER;
    if (!strcmp(name, "Phaser")) return MXFX_PHASER;
    if (!strcmp(name, "BeatDelay") || !strcmp(name, "GrainDelay") || !strcmp(name, "Delay")) return MXFX_DELAY;
    if (!strcmp(name, "Metaverb") || !strcmp(name, "PlateReverb") || !strcmp(name, "Iceverb") ||
        !strcmp(name, "Reverb") || !strcmp(name, "Hall")) return MXFX_REVERB;
    if (!strcmp(name, "Saturator") || !strcmp(name, "Distortion") || !strcmp(name, "Tube") ||
        !strcmp(name, "Overdrive")) return MXFX_SAT;
    if (!strcmp(name, "Limiter")) return MXFX_LIMIT;
    if (!strcmp(name, "Maximizer")) return MXFX_MAX;
    if (!strcmp(name, "Gate")) return MXFX_GATE;
    if (!strcmp(name, "LoFi") || !strcmp(name, "Lofi")) return MXFX_LOFI;
    if (!strcmp(name, "Compressor")) return MXFX_COMP;
    return MXFX_SKIP;
}

static void collect_knobs(const uint8_t **rows, const int *lens, int nrows, int from, int to, float *p, int *np) {
    *np = 0;
    if (to > nrows) to = nrows;
    for (int i = from; i < to && *np < MX_PAR; i++) {
        float f;
        if (row_float(rows[i], lens[i], &f)) p[(*np)++] = f;
    }
}

static float zone_float(const uint8_t **rows, const int *lens, int nrows, int row) {
    float f = 0;
    if (row >= 0 && row < nrows && row_float(rows[row], lens[row], &f)) return f;
    return 0;
}

static void gain_pan_tune(float g, float pan, float tune, float *lg, float *lp, float *lt) {
    if (g < 1e-5f) g = 0.75f;
    float db = 80.05f * log10f(g / 0.75f);
    *lg = powf(10.f, db / 20.f);
    *lp = (pan >= -1.f && pan <= 1.f) ? pan : 0;
    *lt = (tune >= -36.f && tune <= 36.f) ? tune : 0;
}

static const char *src_label(int src) {
    switch (src) {
    case MX_SAMPLE: return "sample";
    case MX_KICK: return "kick";
    case MX_SNARE: return "snare";
    case MX_HAT: return "hat";
    case MX_TOM: return "tom";
    case MX_PERC: return "perc";
    case MX_CYM: return "cymbal";
    default: return "empty";
    }
}


typedef struct { int row; char name[40]; } NameRow;
typedef struct { int row; char cls[24]; } PlugRow;

static void plugs_in(const uint8_t **rows, const int *lens, int nrows, const char classes[256][24],
                     int from, int to, PlugRow *out, int *nout, int max) {
    *nout = 0;
    if (to > nrows) to = nrows;
    for (int i = from; i < to && *nout < max; i++) {
        char cls[24];
        int id = -1;
        if (class_of(rows[i], lens[i], cls, sizeof cls, &id)) {
            if (!strcmp(cls, "NoteEvent")) continue;
            snprintf(out[*nout].cls, sizeof out[*nout].cls, "%s", cls);
            out[*nout].row = i;
            (*nout)++;
            continue;
        }
        id = ref_id(rows[i], lens[i]);
        if (id >= 0 && classes[id][0] && strcmp(classes[id], "NoteEvent")) {
            snprintf(out[*nout].cls, sizeof out[*nout].cls, "%s", classes[id]);
            out[*nout].row = i;
            (*nout)++;
        }
    }
}

/* Playable inserts only. Skipped devices are named in the chain text but take no slot. */
static int add_fx(MxFx *dst, int *n, const char *cls, const float *p, int np) {
    int k = fx_kind(cls);
    if (k == MXFX_SKIP || k == MXFX_NONE) return 0;
    if (*n >= MX_FX) return 0;
    MxFx *f = &dst[*n];
    memset(f, 0, sizeof *f);
    f->kind = k;
    snprintf(f->name, sizeof f->name, "%s", fx_title(k, cls));
    f->n = np > MX_PAR ? MX_PAR : np;
    if (f->n) memcpy(f->p, p, (size_t)f->n * sizeof(float));
    (*n)++;
    return 1;
}

static void chain_add(char *dst, int dst_n, const char *label, int skipped) {
    int used = (int)strlen(dst);
    if (used >= dst_n - 1) return;
    snprintf(dst + used, (size_t)(dst_n - used), "%s%s%s",
             used ? " · " : "", label, skipped ? "*" : "");
}

static void fill_sound(MxPad *pad, const uint8_t **rows, const int *lens, int nrows,
                       const PlugRow *plugs, int nplugs) {
    snprintf(pad->chain, sizeof pad->chain, "%s", src_label(MX_EMPTY));
    for (int i = 0; i < nplugs; i++) {
        int sk = src_kind(plugs[i].cls);
        int next = (i + 1 < nplugs) ? plugs[i + 1].row : plugs[i].row + 70;
        if (next > plugs[i].row + 70) next = plugs[i].row + 70;
        if (sk == MX_SAMPLE && pad->src == MX_EMPTY) {
            pad->src = MX_SAMPLE;
            int path_row = -1;
            for (int r = plugs[i].row; r < plugs[i].row + 8 && r < nrows; r++) {
                if (find_sample(rows[r], lens[r], pad->sample, sizeof pad->sample)) { path_row = r; break; }
            }
            if (path_row >= 0) {
                pad->start = (path_row + 4 < nrows) ? row_int(rows[path_row + 4], lens[path_row + 4]) : 0;
                pad->end = (path_row + 7 < nrows) ? row_int(rows[path_row + 7], lens[path_row + 7]) : 0;
                pad->loop = (path_row + 18 < nrows && row_int(rows[path_row + 18], lens[path_row + 18])) ? 1 : 0;
                float g = zone_float(rows, lens, nrows, path_row + 52);
                float pan = zone_float(rows, lens, nrows, path_row + 56);
                float tune = zone_float(rows, lens, nrows, path_row + 60);
                gain_pan_tune(g, pan, tune, &pad->gain, &pad->pan, &pad->tune);
            } else {
                pad->gain = 1;
            }
            continue;
        }
        if (sk != MX_EMPTY && pad->src == MX_EMPTY) {
            pad->src = sk;
            collect_knobs(rows, lens, nrows, plugs[i].row + 1, next, pad->sp, &pad->ns);
            pad->gain = 1;
            continue;
        }
        if (sk != MX_EMPTY) continue;
        float p[MX_PAR];
        int np = 0;
        collect_knobs(rows, lens, nrows, plugs[i].row + 1, next, p, &np);
        int stored = add_fx(pad->fx, &pad->nfx, plugs[i].cls, p, np);
        int k = fx_kind(plugs[i].cls);
        chain_add(pad->chain, sizeof pad->chain, k == MXFX_SKIP ? plugs[i].cls : fx_title(k, plugs[i].cls), !stored);
    }
    if (pad->gain == 0 && pad->src != MX_EMPTY) pad->gain = 1;
    /* chain_add started from the placeholder "empty"; put the real source in front. */
    {
        char fxpart[96];
        snprintf(fxpart, sizeof fxpart, "%s", pad->chain);
        const char *rest = fxpart;
        if (!strncmp(rest, "empty", 5)) rest += 5;
        snprintf(pad->chain, sizeof pad->chain, "%s%s", src_label(pad->src), rest);
    }
}

static int has(const char *s, const char *part) {
    return s && part && strstr(s, part) != NULL;
}

/* A pattern name row is "00 01 <len> <text>" with extra bytes after the text allowed.
 * Pad names use the stricter name_of(), which rejects those longer rows. */
static int loose_name(const uint8_t *c, int n, char *out, int out_n) {
    if (n < 4 || c[0] != 0 || c[1] != 1) return 0;
    int len = c[2];
    if (len < 1 || len > 40 || n < 3 + len) return 0;
    for (int i = 0; i < len; i++) if (c[3 + i] < 32 || c[3 + i] > 126) return 0;
    if (len >= out_n) len = out_n - 1;
    memcpy(out, c + 3, (size_t)len);
    out[len] = 0;
    return 1;
}

/* NoteEvent's class id is per file (86 in the 808 kit, 91 in Flumex). The int
 * before it is the position in 960 ticks per quarter. Hits are not always on a
 * grid: 8-Ball and Flumex store swung and recorded times. */
static int musical_tick(int t) {
    return t >= 0 && t <= 200000;
}

static int find_note_class(const uint8_t **rows, const int *lens, int nrows) {
    const char *key = "NI::MASCHINE::DATA::NoteEvent";
    int klen = 29;
    for (int r = 0; r < nrows; r++) {
        const uint8_t *c = rows[r];
        int n = lens[r];
        for (int j = 0; j + klen <= n; j++) {
            if (memcmp(c + j, key, (size_t)klen)) continue;
            if (j >= 4 && c[j - 2] == 1 && c[j - 1] == klen && c[j - 4] == 1) return c[j - 3];
        }
    }
    return 86;
}

static int has_text(const uint8_t *c, int n, const char *s) {
    int m = (int)strlen(s);
    if (m <= 0 || m > n) return 0;
    for (int i = 0; i + m <= n; i++)
        if (!memcmp(c + i, s, (size_t)m)) return 1;
    return 0;
}

/* Varint whose last byte sits at end-1. Returns its start, or -1. */
static int varint_ending_at(const uint8_t *c, int end, int *v) {
    if (end < 2) return -1;
    for (int w = 1; w <= 4; w++) {
        int s = end - 1 - w;
        if (s < 0) break;
        if (c[s] != w) continue;
        int x = 0;
        for (int k = 0; k < w; k++) x |= c[s + 1 + k] << (8 * k);
        *v = x;
        return s;
    }
    return -1;
}

static int row_has_note_class(const uint8_t *c, int n, int cid) {
    if (cid < 0 || cid > 255) return 0;
    for (int i = 0; i + 1 < n; i++) if (c[i] == 1 && c[i + 1] == (uint8_t)cid) return 1;
    return 0;
}

/* Explicit velocity, or -1 when this row is only a time (a list link).
 * 0 is a note-off and must not be played. The full note is
 * pitch, velocity (or a single 00), pointer, tick, class — length is not always 240. */
static int note_velocity(const uint8_t *c, int n, int cid) {
    int at = -1;
    for (int i = 0; i + 1 < n; i++)
        if (c[i] == 1 && c[i + 1] == (uint8_t)cid) at = i;
    if (at < 0) return -1;
    int tick = 0, tick_at = varint_ending_at(c, at, &tick);
    if (tick_at <= 0) return -1;
    int ptr = 0, ptr_at = varint_ending_at(c, tick_at, &ptr);
    if (ptr_at <= 0) return -1;
    if (c[ptr_at - 1] == 0) return 0;
    if (ptr_at >= 2 && c[ptr_at - 2] == 1 && c[ptr_at - 1] >= 1 && c[ptr_at - 1] <= 127)
        return c[ptr_at - 1];
    return -1;
}

static int row_note_tick(const uint8_t *c, int n, int cid, int *tick, int *vel) {
    if (!c || n < 4 || n > 48 || has_text(c, n, "NI::") || !row_has_note_class(c, n, cid)) return 0;
    /* "01 <count> 00 01 <class>" is the first hit, at tick 0. The 00 is the time, not a velocity. */
    if (n >= 5 && c[0] == 1 && c[1] >= 1 && c[1] <= 64 && c[2] == 0 && c[3] == 1 && c[4] == (uint8_t)cid) {
        *tick = 0;
        *vel = -1;
        return 1;
    }
    int at = -1;
    for (int i = 0; i + 1 < n; i++)
        if (c[i] == 1 && c[i + 1] == (uint8_t)cid) at = i;
    int t = 0;
    if (varint_ending_at(c, at, &t) < 0 || !musical_tick(t)) return 0;
    *tick = t;
    *vel = note_velocity(c, n, cid);
    return 1;
}

/* A list head is a short "01 <count> … 01 <class>" row. The count includes this row.
 * The next pattern's list for the same sound starts at the following head. */
static int is_list_head(const uint8_t *c, int n, int cid) {
    if (!c || n < 5 || n > 8 || c[0] != 1 || cid < 0 || cid > 255) return 0;
    if (c[n - 2] != 1 || c[n - 1] != (uint8_t)cid) return 0;
    return c[1] >= 1 && c[1] <= 64;
}

static int is_note_end(const uint8_t *c, int n, int cid) {
    if (!c || n < 2) return 0;
    if (c[0] == 0xff) return 1;
    if (cid < 0 || cid > 255) return 0;
    for (int i = 0; i + 3 < n; i++)
        if (c[i] == 0xff && c[i + 1] == 1 && c[i + 2] == 1 && c[i + 3] == (uint8_t)cid) return 1;
    return 0;
}

/* The "01 02" markers are the starts of the 16 sounds, in pad order. */
static int pad_of_row(const int *markers, int nmark, int row) {
    for (int i = 0; i < nmark; i++) {
        int nxt = (i + 1 < nmark) ? markers[i + 1] : 100000000;
        if (row >= markers[i] && row < nxt) return i;
    }
    return -1;
}

static void add_ev(MxPattern *pat, int pad, int tick, int vel) {
    int explicit_vel = vel >= 1 && vel <= 127;
    if (vel < 0) vel = 100;
    if (pad < 0 || pad >= MX_PADS || vel <= 0 || !musical_tick(tick)) return;
    for (int i = 0; i < pat->nev; i++) {
        if (pat->ev[i].pad == pad && pat->ev[i].tick == tick) {
            /* A later full note carries the real velocity; the list link before it does not. */
            if (explicit_vel) pat->ev[i].vel = vel;
            return;
        }
    }
    if (pat->nev >= MX_EV) return;
    pat->ev[pat->nev].pad = pad;
    pat->ev[pat->nev].tick = tick;
    pat->ev[pat->nev].vel = vel;
    pat->nev++;
}

/* Walk the note list that starts at `head`. The pad is the sound that contains
 * that list. The pattern-level pointer sits on another sound's marker, so the
 * pad is not the marker index itself. A second list head in the same sound is
 * the next pattern, not more notes of this one. */
static void collect_voice(MxPattern *pat, const uint8_t **rows, const int *lens, int nrows,
                          const int *markers, int nmark, int head, int cid) {
    if (head < 0 || head >= nrows) return;
    int pad = pad_of_row(markers, nmark, head);
    if (pad < 0) return;
    int stop = (pad + 1 < nmark) ? markers[pad + 1] : nrows;
    if (stop > nrows) stop = nrows;
    int count = 0, got = 0, in_list = 0;
    for (int i = head; i < stop; i++) {
        if (i > head && is_note_end(rows[i], lens[i], cid)) break;
        if (is_list_head(rows[i], lens[i], cid)) {
            if (in_list) break;
            in_list = 1;
            count = rows[i][1];
        }
        int tick = 0, vel = -1;
        if (!row_note_tick(rows[i], lens[i], cid, &tick, &vel)) continue;
        in_list = 1;
        add_ev(pat, pad, tick, vel);
        if (count && ++got >= count) break;
    }
}

/* A pattern event points at the first note of one sound. The constant 16 sits
 * between that row and the following sound's marker. A shorter event omits the 16. */
static int event_head(const uint8_t *c, int n, const uint8_t **rows, const int *lens, int nrows,
                      const int *markers, int nmark, int cid) {
    if (!c || n < 6 || n > 20 || c[0] != 0x01) return -1;
    int vals[8];
    int nv = 0, i = 0;
    while (i < n && nv < 8) {
        int v = 0, ni = read_varint(c, n, i, &v);
        if (ni < 0) break;
        vals[nv++] = v;
        i = ni;
    }
    int at = -1;
    for (int k = 0; k < nv; k++) if (vals[k] == 16) { at = k; break; }
    if (at >= 1 && vals[at - 1] >= 0 && vals[at - 1] < nrows && pad_of_row(markers, nmark, vals[at - 1]) >= 0)
        return vals[at - 1];
    for (int k = 1; k < nv; k++) {
        int head = vals[k];
        if (head < 0 || head >= nrows || pad_of_row(markers, nmark, head) < 0) continue;
        int dummy = 0, dvel = 0;
        if (is_list_head(rows[head], lens[head], cid) || row_note_tick(rows[head], lens[head], cid, &dummy, &dvel))
            return head;
    }
    return -1;
}

static void sort_events(MxPattern *p) {
    for (int i = 1; i < p->nev; i++) {
        MxEvent e = p->ev[i];
        int j = i;
        while (j > 0 && p->ev[j - 1].tick > e.tick) {
            p->ev[j] = p->ev[j - 1];
            j--;
        }
        p->ev[j] = e;
    }
}

static void parse_patterns(MxGroup *g, const uint8_t **rows, const int *lens, int nrows, int from) {
    int markers[MX_PADS], nmark = 0;
    for (int i = 0; i < nrows && nmark < MX_PADS; i++) {
        if (lens[i] == 2 && rows[i][0] == 1 && rows[i][1] == 2) markers[nmark++] = i;
    }
    if (nmark < 1 || from < 0) return;

    int start[MX_PATS];
    int nstart = 0;
    int skip_title = !g->name[0];
    for (int i = from + 1; i < nrows && nstart < MX_PATS; i++) {
        char nm[40];
        if (!loose_name(rows[i], lens[i], nm, sizeof nm)) continue;
        if (!strcmp(nm, "Group") || !strcmp(nm, "Default")) continue;
        if (g->name[0] && !strcmp(nm, g->name)) continue;
        if (skip_title) { skip_title = 0; continue; }
        start[nstart] = i;
        snprintf(g->pat[nstart].name, sizeof g->pat[nstart].name, "%s", nm);
        nstart++;
    }
    g->npat = nstart;
    int cid = find_note_class(rows, lens, nrows);

    for (int p = 0; p < nstart; p++) {
        int end = (p + 1 < nstart) ? start[p + 1] : nrows;
        MxPattern *pat = &g->pat[p];
        int max_tick = 0;
        for (int i = start[p]; i < end; i++) {
            if (pat->length == 0 && lens[i] >= 7 && rows[i][0] == 0 && rows[i][1] == 2 && rows[i][4] == 2) {
                int a = rows[i][2] | (rows[i][3] << 8);
                int b = rows[i][5] | (rows[i][6] << 8);
                if (a == b && a >= 960 && a <= 200000) pat->length = a;
            }
            int head = event_head(rows[i], lens[i], rows, lens, nrows, markers, nmark, cid);
            if (head < 0) continue;
            collect_voice(pat, rows, lens, nrows, markers, nmark, head, cid);
        }
        for (int e = 0; e < pat->nev; e++)
            if (pat->ev[e].tick > max_tick) max_tick = pat->ev[e].tick;
        if (pat->length <= max_tick) pat->length = max_tick + 1;
        sort_events(pat);
    }
}

static void assign_chokes(MxGroup *g) {
    for (int i = 0; i < g->npad; i++) {
        if (!has(g->pad[i].name, "Closed")) continue;
        for (int j = 0; j < g->npad; j++) {
            if (i == j || !has(g->pad[j].name, "Open")) continue;
            if (g->pad[i].nchoke < 4) g->pad[i].choke[g->pad[i].nchoke++] = j;
        }
    }
}

int mx_parse(const uint8_t *data, int n, MxGroup *g) {
    memset(g, 0, sizeof *g);
    int body = find_archive(data, n);
    if (body < 0) return -1;
    const uint8_t **rows = NULL;
    int *lens = NULL;
    int nrows = split_rows(data, n, body, &rows, &lens);
    if (nrows < 16) { free(rows); free(lens); return -1; }

    char classes[256][24];
    memset(classes, 0, sizeof classes);
    for (int i = 0; i < nrows; i++) {
        char cls[24];
        int id = -1;
        if (class_of(rows[i], lens[i], cls, sizeof cls, &id) && id >= 0 && id < 256)
            snprintf(classes[id], sizeof classes[id], "%s", cls);
    }

    NameRow names[24];
    int nnames = 0;
    int pattern_row = nrows;
    for (int i = 0; i < nrows; i++) {
        char nm[40];
        if (!name_of(rows[i], lens[i], nm, sizeof nm)) continue;
        if (!strncmp(nm, "Pattern", 7)) {
            if (pattern_row == nrows) pattern_row = i;
            continue;
        }
        if (nnames < 24 && i < pattern_row) {
            names[nnames].row = i;
            snprintf(names[nnames].name, sizeof names[nnames].name, "%s", nm);
            nnames++;
        }
    }
    /* The name sitting just before Pattern 1 is the group, not a pad. */
    int nsounds = nnames;
    int group_row = nrows;
    if (pattern_row < nrows && nsounds > 0) {
        nsounds--;
        snprintf(g->name, sizeof g->name, "%s", names[nsounds].name);
        group_row = names[nsounds].row;
    }
    if (nsounds > MX_PADS) nsounds = MX_PADS;
    g->npad = nsounds;

    for (int s = 0; s < nsounds; s++) {
        MxPad *pad = &g->pad[s];
        snprintf(pad->name, sizeof pad->name, "%s", names[s].name);
        int end = (s + 1 < nnames) ? names[s + 1].row : group_row;
        PlugRow plugs[8];
        int np = 0;
        plugs_in(rows, lens, nrows, classes, names[s].row, end, plugs, &np, 8);
        fill_sound(pad, rows, lens, nrows, plugs, np);
    }
    assign_chokes(g);

    if (group_row < pattern_row) {
        PlugRow plugs[12];
        int np = 0;
        plugs_in(rows, lens, nrows, classes, group_row, pattern_row, plugs, &np, 12);
        for (int i = 0; i < np; i++) {
            if (src_kind(plugs[i].cls) != MX_EMPTY) continue;
            int next = (i + 1 < np) ? plugs[i + 1].row : plugs[i].row + 48;
            float p[MX_PAR];
            int npar = 0;
            collect_knobs(rows, lens, nrows, plugs[i].row + 1, next, p, &npar);
            int stored = add_fx(g->gfx, &g->ngfx, plugs[i].cls, p, npar);
            int k = fx_kind(plugs[i].cls);
            chain_add(g->group_fx, sizeof g->group_fx,
                      k == MXFX_SKIP ? plugs[i].cls : fx_title(k, plugs[i].cls), !stored);
        }
    }

    parse_patterns(g, rows, lens, nrows, group_row < nrows ? group_row : (nsounds > 0 ? names[nsounds - 1].row : -1));

    free(rows);
    free(lens);
    return g->npad > 0 || g->name[0] ? 0 : -1;
}
