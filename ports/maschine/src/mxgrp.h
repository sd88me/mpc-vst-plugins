/* A Maschine 2 group (.mxgrp): 16 sounds, each a sampler or drumsynth plus insert
 * effects, an optional group effect chain, and the MIDI patterns stored in the group. */
#pragma once
#include <stdint.h>

enum { MX_PADS = 16, MX_FX = 4, MX_PAR = 8, MX_PATS = 16, MX_EV = 512 };

enum {
    MX_EMPTY = 0,
    MX_SAMPLE,
    MX_KICK,
    MX_SNARE,
    MX_HAT,
    MX_TOM,
    MX_PERC,
    MX_CYM
};

enum {
    MXFX_NONE = 0,
    MXFX_CHORUS,
    MXFX_FLANGER,
    MXFX_PHASER,
    MXFX_DELAY,
    MXFX_REVERB,
    MXFX_SAT,
    MXFX_LIMIT,
    MXFX_MAX,
    MXFX_GATE,
    MXFX_LOFI,
    MXFX_COMP,
    MXFX_SKIP          /* named in the chain, not rendered */
};

typedef struct {
    int kind;              /* MXFX_* */
    char name[24];         /* what the screen shows */
    float p[MX_PAR];
    int n;
} MxFx;

typedef struct {
    char name[40];
    int src;               /* MX_* */
    char sample[240];      /* library-relative, empty if none */
    int start, end;        /* source frames; end 0 = whole file */
    int loop;
    float gain;            /* linear, 1 = 0 dB */
    float pan;             /* -1..1 */
    float tune;            /* semitones */
    float sp[MX_PAR];      /* drumsynth knobs, 0..1 when Maschine normalised them */
    int ns;
    MxFx fx[MX_FX];
    int nfx;
    int choke[4];          /* pad indices this pad silences */
    int nchoke;
    char chain[96];        /* "sample · Chorus" */
} MxPad;

typedef struct {
    int pad;               /* 0-based sound that owns the note */
    int tick;              /* position, 960 ticks per quarter */
    int vel;               /* 1..127 */
} MxEvent;

typedef struct {
    char name[40];
    int length;            /* loop length in ticks */
    MxEvent ev[MX_EV];
    int nev;
} MxPattern;

typedef struct {
    char name[64];
    MxPad pad[MX_PADS];
    int npad;
    MxFx gfx[MX_FX];
    int ngfx;
    char group_fx[96];
    MxPattern pat[MX_PATS];
    int npat;
} MxGroup;

/* 0 on success. Only Maschine 2 archives (boost library version >= 13). */
int mx_parse(const uint8_t *data, int n, MxGroup *g);
