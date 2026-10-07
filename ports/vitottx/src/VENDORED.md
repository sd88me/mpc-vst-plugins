# Vendored: Vital's OTT compressor DSP, from vitOTTx

- Upstream: https://github.com/Sakhnovkrg/vitOTTx, commit `738ba9dc33448ced48c37b341ce96bd917857224`
  (itself based on Yegor Suslin's vitOTT and Matt Tytel's Vital).
- Copied: `Source/vital_dsp/` → `src/vital_dsp/` (all of it). Not copied: the JUCE plugin, its editor and UI.
- Licence: GPL-3.0 (`../LICENSE`, the upstream file unchanged).

Local changes (re-apply after a re-vendor):
1. `framework/common.h`: `#include "JuceHeader.h"` replaced by `<cmath>`, `<algorithm>`, `<memory>` and no-op
   definitions of `JUCE_LEAK_DETECTOR` and `JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR` (deleted copy
   constructor/assignment). Those two macros were all the DSP used from JUCE.

Nothing else changed. Build flags the DSP needs on the device: `-mfpu=neon -DNEON_ARM32` (vst.json `build.cflags_arm`):
the armhf compiler doesn't assume NEON, and Vital's `vdivq_f32` is AArch64-only (`NEON_ARM32` selects its
reciprocal-estimate path). `src/engine.cpp` (ours) replaces vitOTTx's `PluginProcessor` and follows its `updParams()`.
