# vitOTTx for MPC

An insert-effect port of [vitOTTx](https://github.com/Sakhnovkrg/vitOTTx) (Vital's OTT multiband up/down
compressor) for MPC OS standalone devices, with an OTT-style skin and live per-band level meters.

- Engine: `src/vital_dsp/` vendored unchanged except for the JUCE header (`src/VENDORED.md`); `src/engine.cpp`
  is the `mpc_engine()` glue (as vitOTTx's processor: depth/upward/downward scale the band ratios, time sets attack
  and release, thresholds and ratios keep vitOTTx's defaults).
- Controls (Q-Links in this order): Depth, Time, In Gain, Out Gain, Upward, Downward, Mix, H/M/L band gain,
  Low/Mid and Mid/High crossover.
- Meters: per band, a thin input strip and the output bar over the band's upward (beige) and downward (green)
  zones, -60..0 dB in 24 steps, plus the output level as text. They are `picture` widgets on engine-driven option
  parameters (`HAS_DISPLAY_REV`), not filmstrip `meter`s: wide bars as square filmstrip frames would cost tens of MB
  of MPC's filmstrip cache per load (docs/NOTES.md "MPC's filmstrip cache").
- Skin art: `art/make_art.py` (Pillow) draws `art/*.png` to match `layout.conf`; rerun it after changing either.

Build and test from the repo root:

    tools/test_port.sh ports/vitottx/vst.json     # x86, ASan: PASSED
    tools/build_port.sh ports/vitottx/vst.json    # armhf .so + skin in ports/vitottx/build/

Licence: GPL-3.0 (`LICENSE`), as upstream.

![Offline skin preview](preview.png) (offline render, meters lit by hand; not a device screenshot)
