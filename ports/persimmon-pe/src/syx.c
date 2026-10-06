#include <string.h>
#include "syx.h"

int syx_unpack(const uint8_t *in, int n, uint8_t *out, int max) {
    int o = 0;
    for (int i = 0; i < n; i += 8) {
        uint8_t m = in[i];
        for (int j = 1; j < 8 && i + j < n && o < max; j++) out[o++] = (uint8_t)((in[i + j] & 0x7F) | (((m >> (j - 1)) & 1) << 7));
    }
    return o;
}

int syx_pack(const uint8_t *in, int n, uint8_t *out) {
    int o = 0;
    for (int i = 0; i < n; i += 7) {
        int hdr = o++;
        uint8_t m = 0;
        for (int j = 0; j < 7 && i + j < n; j++) {
            m |= (uint8_t)(((in[i + j] >> 7) & 1) << j);
            out[o++] = in[i + j] & 0x7F;
        }
        out[hdr] = m;
    }
    return o;
}

void syx_each(const uint8_t *buf, size_t len, void (*fn)(void *, int, const uint8_t *, int), void *ctx) {
    size_t i = 0;
    while (i < len) {
        if (buf[i] != 0xF0) { i++; continue; }
        size_t e = i + 1;
        while (e < len && buf[e] != 0xF7 && !(buf[e] & 0x80)) e++;
        if (e < len && buf[e] == 0xF7 && e - i >= 5 && buf[i + 1] == 0x01 && buf[i + 2] == 0x20 && buf[i + 3] == 0x01)
            fn(ctx, buf[i + 4], buf + i + 5, (int)(e - i - 5));
        i = e;
    }
}

int syx_write_program(const uint8_t prog[192], int bank, int num, uint8_t *out) {
    int o = 0;
    out[o++] = 0xF0; out[o++] = 0x01; out[o++] = 0x20; out[o++] = 0x01;
    if (bank >= 0) { out[o++] = SYX_PROGRAM; out[o++] = (uint8_t)(bank & 3); out[o++] = (uint8_t)(num & 0x7F); }
    else out[o++] = SYX_EDIT;
    o += syx_pack(prog, 192, out + o);
    out[o++] = 0xF7;
    return o;
}

int syx_write_name(const char *name, int bank, int num, uint8_t *out) {
    int o = 0;
    out[o++] = 0xF0; out[o++] = 0x01; out[o++] = 0x20; out[o++] = 0x01; out[o++] = SYX_NAME;
    out[o++] = (uint8_t)(bank & 3); out[o++] = (uint8_t)(num & 0x7F);
    int end = 0;
    for (int i = 0; i < 16; i++) {
        char c = end ? ' ' : name[i];
        if (!c) { end = 1; c = ' '; }
        out[o++] = (uint8_t)(c & 0x7F);
    }
    out[o++] = 0xF7;
    return o;
}
