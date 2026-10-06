/* Parameter-to-physical curves. Each one is a formula or a short breakpoint list fitted to what the DSP firmware 3.5 tables
 * hold (docs/FIRMWARE.md has the measurements); no firmware data is copied here. */
#pragma once
float pe_note_hz(float semis);          /* osc frequency: 0 = C-2 (8.18 Hz), semitone steps (MIDI note numbers) */
float pe_lpf_hz(float v);               /* lowpass cutoff 0..164, semitones from C0 */
float pe_hpf_hz(float v);               /* 4-pole highpass 1..99, semitones; 99 = 21.55 kHz */
float pe_env_seconds(float v);          /* envelope attack/decay/release 0..110 */
float pe_lfo_hz(int v);                 /* LFO frequency 0..150 (unsynced) */
float pe_delay_seconds(int v);          /* delay tap time 0..150 (unsynced), the firmware's samples at 48 kHz */
float pe_glide_seconds(int v);          /* glide 1..100 */
