/* Load a parsed group: samples from the library next to the .mxgrp, drumsynth for
 * Kick/Snare/Hihat/Tom/Perc/Cymbal, and the insert effects we can play. */
#pragma once
#include <stdint.h>

typedef struct PlayKit PlayKit;

PlayKit *play_load(const char *mxgrp_path);
void play_free(PlayKit *k);
void play_note(PlayKit *k, int note, int vel);
void play_render(PlayKit *k, int16_t *lr, int frames, float master, int fx_on);
void play_set_bpm(PlayKit *k, float bpm);

int play_npad(const PlayKit *k);
const char *play_pad_name(const PlayKit *k, int pad);   /* 0-based; "" if none */
/* Colour of a pad from its name: 0 yellow, 1 kick, 2 snare, 3 hat, 4 percussion, 5 tom. */
int play_pad_tint(const char *name);
int play_pad_active(const PlayKit *k, int pad);
const char *play_group(const PlayKit *k);
const char *play_status(const PlayKit *k);
const char *play_info(const PlayKit *k);

int play_npat(const PlayKit *k);
const char *play_pat_name(const PlayKit *k, int index); /* "" if none */
int play_pat_events(const PlayKit *k, int index);
/* Sixteen time slices of one pattern: bit c of row p is set when pad p has a hit in slice c. */
void play_pat_columns(const PlayKit *k, int index, int cols, uint16_t rows[16]);
/* Loudest velocity in each slice, 0 when that pad is silent there. */
void play_pat_levels(const PlayKit *k, int index, int cols, uint8_t vel[16][16]);
/* 0 silent, then four steps up to 4 (full). A quieter hit is a lower step. */
int play_vel_band(int vel);
void play_preview(PlayKit *k, int index, int on);
/* Notes the preview just produced: each row is frame, status, note, velocity. Drains the queue. */
int play_midi_out(PlayKit *k, uint8_t ev[][4], int max);
/* Tab-separated "note tick velocity" lines, 960 ticks per quarter. Returns the event count. */
int play_pattern_text(const PlayKit *k, int index, char *buf, int n);
/* One-track MIDI file, 960 ticks per quarter, note 48 = pad 1. Returns the byte count, or 0. */
int play_pattern_midi(const PlayKit *k, int index, int bpm, uint8_t *dst, int dst_n);
