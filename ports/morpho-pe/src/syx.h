/* Poly Evolver / Evolver SysEx (manual p. 54-61): F0 01 20 01 <cmd> ... F7, data in the "packed MS bit" format
 * (7 data bytes per 8 MIDI bytes, the first byte of each group holding their top bits, bit 0 = first byte). */
#pragma once
#include <stdint.h>
#include <stddef.h>
enum { SYX_PROGRAM = 0x02, SYX_EDIT = 0x03, SYX_PARAM = 0x01, SYX_SEQ = 0x08, SYX_WAVE = 0x0A, SYX_NAME = 0x11 };
int syx_unpack(const uint8_t *in, int n, uint8_t *out, int max);      /* -> bytes written */
int syx_pack(const uint8_t *in, int n, uint8_t *out);                 /* -> MIDI bytes written (n + ceil(n/7)) */
/* Walks every message in buf; calls fn for each F0 01 20 01 message (cmd, body after the command byte, body length). */
void syx_each(const uint8_t *buf, size_t len, void (*fn)(void *ctx, int cmd, const uint8_t *body, int n), void *ctx);
/* A program dump of 128 parameters + 64 steps; bank < 0 writes an edit-buffer dump. Returns the message length (226 or 228). */
int syx_write_program(const uint8_t prog[192], int bank, int num, uint8_t *out);
int syx_write_name(const char *name, int bank, int num, uint8_t *out);   /* 23 bytes */
