Hi Locrian,

Thanks for the write-up. It was the most useful kind of bug report: a root cause, a one-line fix, and a note on what not to try. Here's what we did with each item.

**1. UpdateDisplay on every host write — fixed (mpc-vst-plugins #486, #487)**
You were right. A plain parameter write no longer asks MPC for an `audioMasterUpdateDisplay`; the ones that remain are the step buttons and anything that opts in. I did not delete the line outright, because it was added on 2026-09-24 to keep `get=`-bound readouts (bank/patch names) from freezing after a direct Q-Link turn. Instead:
- A plain write sends nothing.
- A new per-param key, `"refresh_display": true`, asks for a refresh on that param's writes. It's for text that follows a param and isn't polled, such as labels behind a machine selector.
- The existing 100 ms text poll covers the rest, so the readouts you'd expect to break still update.
- On top of that, at most one UpdateDisplay goes out per 50 ms, so a burst of Q-Link events or a held stepper can't turn into a screen rebuild per block.

Checked on a Force with the JV-880: Q-Links work on track edit → automation, and the bank and patch readouts still follow the arrows and a direct Q-Link turn. Offline, a test now checks that 32 host writes cause no UpdateDisplay. We did not try the ticker or `audioMasterAutomate` echo you warned about.

**2. Reports only go out from the render callback — documented (#489)**
We agree, and a timer thread calling the host from outside its own threads looked riskier than the bug. It's now in PORTING.md: render is not a heartbeat, and MM-303's 50 ms ticker is the known workaround.

**3. Poll cost on the audio thread — documented (#489)**
Written up in PORTING.md with the advice you gave: `"poll": false` on readouts that only change on a tap, and nothing costly behind a polled key. Skipping params the skin doesn't show is still on our list.

**4. One lock over set/get/MIDI/render — documented (#489)**
Your SQLite example is now in PORTING.md as the reason for "no I/O in `set_param`/`get_param`": use a worker thread plus a `trylock` pickup. We haven't changed the lock itself.

**5. No `effGetParameterProperties` — documented, not implemented (#489)**
As far as we can tell (from reading, not a device test), the VST2 properties MPC's host could use don't include a "disabled" flag, so we agree controls must be made inert in the engine. It's in PORTING.md. One open question: whether MPC honours the switch and whole-step flags, which could let Q-Links step option lists natively. That needs a probe plugin on a device, and nothing is implemented yet.

**6. Skin binds by index — fixed (#488)**
`gen_vst.py` now writes a `params.lock` next to `vst.json` on the first build, and a later build fails when an existing key changes index (`GEN_VST_RELOCK=1` accepts a deliberate break). One note: our own skins resolve keys to indices when built, so a rebuilt skin follows an insert. The real danger is saved projects, automation and Q-Link maps, which store the index, and that's what the lock protects.

**Regressions:** the only expected one is a label that followed another param and relied on the old refresh. We went through our own ports: Machinemodule needed `refresh_display` on the machine and LFO selectors, and the others needed nothing. Every port has to be rebuilt against the new wrapper to get the fix, as you said, and we're rebuilding ours now. We'll post a notice for the other authors in the catalog.

