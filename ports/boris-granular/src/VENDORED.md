# Vendored DSP

`src/dsp/` is vendored from https://github.com/filliformes/boris-move at commit
`f3b03b2cbe45eac90b2de2db82444a1c0be20afc` (`src/dsp/granular.c`, `audio_fx_api_v1.h`, `plugin_api_v1.h`), GPL-3.0
(`../LICENSE`). boris-move is a plain-C Schwung `audio_fx_api_v2` rewrite of Alessandro Gaiba's
[Boris Granular Station](https://github.com/glesdora/boris-granular-station) (JUCE/RNBO, GPL-3.0).

Local changes (all in `granular.c`, behind `#ifdef BORIS_VST`):
- `set_param("lfo_bpm", <bpm>)` sets the tempo and marks the clock running, so Sync follows MPC's tempo
  (`audioMasterGetTime`, the wrapper's `HAS_LFO_BPM`) instead of MIDI clock, which an MPC insert effect does not get.

Not changed: everything else. `src/engine.c` is this port's own glue (mpc_engine_t on top of `move_audio_fx_init_v2`).
