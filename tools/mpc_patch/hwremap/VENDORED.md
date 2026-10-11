# Vendored from akai_standalone_remap

Source: https://github.com/mmiroshnikov/akai_standalone_remap
Commit: `9d2aa57a570b0c4788f88b04ca242bb82176c380` (message: `LICENSE: MIT`)
Licence: MIT (`src/LICENSE`). Copyright (c) 2026 Misha Miroshnikov.

Copied as-is: `src/LICENSE`, `configs/mpc-live.conf`. `src/hwremap.c` and `src/test_hwremap.c` carry the one local change below; `configs/force.conf` is this repo's own map (the upstream one is the starting point).

Local change, build only: the device library is compiled with `arm32v7/gcc:11-bullseye` (glibc 2.31, the same image the plugins here use) instead of that repo's `arm32v7/gcc:12`.

Local change, source (2026-10-09): a `combo HOLD SRC tokens...` rule. Upstream's `hold` / `held` support a single modifier button (Shift); `combo` lets any button be the modifier for a given source button (`combo 9 114 b2 t280,487`: while Clip (9) is held, pressing Left (114) runs the tokens). 38 lines in `hwremap.c`, three cases in `test_hwremap.c`, host tests pass under ASan/UBSan. Existing rules behave as before. To be offered upstream as a pull request (not opened yet); drop this change when upstream has an equivalent. Checked on a Force (MPC OS 3.x, MockbaMod off) on 2026-10-09: Clip+Left, Mixer+arrows.
