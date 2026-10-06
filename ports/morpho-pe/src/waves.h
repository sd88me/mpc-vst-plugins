/* The digital oscillators' 128 waveshapes of 128 samples. The plugin builds an open set of its own (additive spectra); the
 * instrument's ROM waves are not in its firmware files and are never shipped, but a user's own Waveshape Data dumps
 * (F0 01 20 01 0A <n> <293 packed bytes> F7, e.g. from "Request Waveshape Dump") replace slots as they are loaded. */
#pragma once
#include <stdint.h>
#define PE_WLEN 128
#define PE_NWAVES 128
void waves_open(float w[PE_NWAVES][PE_WLEN]);
/* Decodes a waveshape dump body (after the 0x0A command byte); returns the slot 0..127 or -1. 12-bit ROM-style data
 * (|x| <= 2048) is scaled as 12 bit, anything larger as 16 bit. */
int waves_from_dump(const uint8_t *body, int n, float out[PE_WLEN]);
