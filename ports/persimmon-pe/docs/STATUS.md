# Status (2026-10-06)

## Done (offline)
- Firmware decoded: update format, chip identification, DSP boot stream, voice tables (docs/FIRMWARE.md; `tools/fw/pe_fw.py`).
- Engine (`src/`): the full program format, 4 voices (1-8 selectable), poly / mono / unison 1 and 2 with the six key priorities,
  per-oscillator glide (normal, fingered, keyboard off), sync, slop, analog oscillators (saw, triangle, saw-tri, pulse 0-99 that
  turns off at the extremes), digital oscillators with FM and ring modulation both ways and shape sequencing, noise, 2/4-pole
  lowpass per channel with envelope, velocity, key tracking, audio mod and split, VCA, the seven output pan modes, tuned
  feedback with grunge, 4-pole highpass, distortion with noise gate, three-tap delay with both feedback paths and synced times,
  output hack, three envelopes (env 3 with delay), four LFOs (synced rates, key sync above 100), four mod slots and the
  seven fixed routes, the 4 x 16 sequencer with rests, resets, swing, clock modulation and the trigger modes, MIDI CCs.
- Plugin: 219 parameters (128 program + 64 steps + host controls + popup state), an eight-tab skin, banks from `.syx`,
  user waveshape dumps, state chunk.
- Tests: `tools/test_port.sh` passes every check but one (below); `test/test_engine.c` passes (pitch to 0.1 Hz, every built-in
  program, sequencer, extremes, SysEx and state round trips, a folder of banks and a waveshape).
- CPU: 2-6 % of one x86 core for four held voices (rough; the device bench is still to do, docs/BENCH.md of mpc-vst-plugins).

## Known limits
- `test_port.sh`: "six data wheel clicks step six" fails on Osc1 Freq (0-120): a wheel click is 1.2 steps and the wrapper
  rounds it to 2. Every parameter with a range of 101-149 behaves so. A wrapper fix is proposed separately; `nudge_pct` is
  not used because it makes sweeps run fast on these ranges.
- Guessed, not measured: the envelope tick rate (3 kHz), modulation depth per destination (table `DR` in `src/engine.c`), glide
  times, filter cutoff scale (16.35 Hz at 0, semitone steps), filter key tracking reference, split, audio mod and resonance
  scaling, distortion and noise gate curves, output hack (bit reduction), grunge (a fold), unison detune.
- External audio input, its peak and envelope follower and the Ext In trigger modes have nothing to work on in an instrument
  plugin: the Ext In trigger modes act like their keyboard counterparts and the input sources read zero.
- Sequencer MIDI-out destinations (notes, velocity, controllers) are ignored: MPC does not take MIDI from a VST.
- Not run on a device: skin, Q-Links, CPU and the MPC OS 2.x shape are unchecked.

## Next steps
1. Device: build, bench, play, save/reload a project (mpc-vst-plugins docs/PORTING.md section 4).
2. Disassemble the DSP code (needs the ADSP-219x instruction set reference) to replace the guesses above with the firmware's
   own arithmetic, starting with modulation scaling, the envelope generator and the feedback path.
3. An offline ADSP-219x interpreter as a reference rig for the digital half (docs/FIRMWARE.md section 4).
4. Recordings of a real instrument for the analog half.
5. Move to its own repository, then the catalog route (docs/CATALOG.md of mpc-vst-plugins).
