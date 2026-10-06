# Persimmon-PE: agent guide

MPC OS VST2 instrument modelled on the DSI Poly Evolver voice. Start with `README.md`, `docs/STATUS.md` and `docs/FIRMWARE.md`,
then mpc-vst-plugins' `CLAUDE.md`, `docs/NOTES.md` and `docs/PORTING.md`.

Ground rules:
- Never commit DSI/Sequential firmware files, decoded images (`pe_fw.py unpack` output), extracted tables, factory programs or
  waveshape dumps, or recordings of the instrument. The engine's curves are formulas and short breakpoint lists fitted to the
  firmware (document each fit in docs/FIRMWARE.md); `tools/fw/pe_fw.py` re-derives them from the user's own files.
- No "Evolver", "DSI", "Dave Smith" or "Sequential" in the product name, plugin id or skin art; the README may say what it is
  modelled on, with the disclaimer.
- `vst/params.json`, `src/patch_tab.h` and `vst/layout.conf` are generated: edit `tools/gen_patch.py` / `tools/gen_layout.py`
  and run `tools/make_layout.sh`. Parameter order is the instrument's and append-only once released.
