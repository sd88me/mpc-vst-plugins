# Handoff: the "UpdateDisplay on every host write" wrapper fix and the port rollout

Started 2026-10-21. **Last updated: 2026-10-21, all wrapper-based ports released** (see "Status" below; the table is the source of truth).
Update this file whenever a release, PR or finding changes. Dates and "device" or "offline" for every claim.

## 1. What this is about

A port author (Dexed+ port built on this wrapper; the person the catalog calls Locrian) sent `sd88me-architecture-flaws.md`:
six flaws in `wrapper/vst2_wrap.c` and the port workflow. Two were fixed in code, four documented.

| # | Flaw | What we did |
|---|---|---|
| 1 | Every host write sent `audioMasterUpdateDisplay`; MPC rebuilds its parameter screen on each, so Q-Links could not move a param on track edit → automation | Fixed: plain writes send nothing; `step_of` buttons still ask; per-param opt-in `"refresh_display": true`; at most one UpdateDisplay per 50 ms (mpc-vst-plugins #486, #487) |
| 2 | Reports only go out from `processReplacing()` | Documented (PORTING.md, #489). No code change |
| 3 | `housekeeping()` polls DSP text on the audio thread | Documented (#489). Skipping unshown params is still open (ROADMAP idea) |
| 4 | One lock over set/get/midi/render | Documented (#489): no I/O in set/get; worker + trylock |
| 5 | No `effGetParameterProperties` (opcode 56) | Documented (#489). Probed on the Force 2026-10-23: MPC never asks for opcode 56 and ignores the flags, so there is nothing to implement |
| 6 | Skin binds params by index; an insert mid-list breaks them | Fixed: `gen_vst.py` writes `<port>/params.lock`, build fails if an existing key changes index (#488) |

Why not the author's one-line fix (delete the flag): it was added on 2026-09-24 so `get=`-bound readouts (jv880 bank/patch names)
refresh after a direct Q-Link turn (NOTES.md "A readout bound elsewhere (get=)"). The 100 ms text poll now covers polled readouts;
`refresh_display` covers unpolled text that depends on a param.

Verified: **device (Force, 2026-10-21)**, JV-880 rebuilt with #486 + #487: Q-Links work on track edit → automation, bank/patch readouts
still follow the stepper and a Q-Link turn; the PLAY-page macro spacing fix (see 4) looked good ("mini-jv looks good").
Offline only: everything else (host tests `tools/host_test.c`: 32 host writes → 0 UpdateDisplays; a stepper pressed every block →
at most 2 per 4096 frames; `params.lock` fails on an inserted param).

## 2. Merged in mpc-vst-plugins

#486 wrapper + `refresh_display` · #487 50 ms cap · #488 `params.lock` · #489 PORTING.md limits + NOTES.md. NOTES.md entries dated 2026-10-21.

## 3. Which ports need what

- **Rebuild against the new wrapper, then re-release** (compiled in; existing `.so` files keep the bug).
- **`"refresh_display": true`** needed only where unpolled text depends on a param. Checked 2026-10-21:
  - Machinemodule: yes: `trackN_machine`, `trackN_lfo_track`, `trackN_lfo_param` (SYN1-8 labels via `dynamic_name`; LFO destination via
    `dynamic_display`). Done (mpc-vst-machinedrum #16).
  - Profit-8, Morpho-PE, Sturm: no (`_display` is formatted from the param's own value; they use `HAS_DISPLAY_REV`, which bumps on patch changes).
  - Daemon / Daemon Listen: no (all `poll: false` readouts are driven by `d->rev`, buttons bump it).
  - TR-MPC: **yes, found on the device 2026-10-23** (missed in the first review, which only looked at labels): `sNN_fam` is derived from the voice
    `sNN_src` and drives the skin's `when=` panels, so slots stopped reskinning when the voice changed. Fixed with `refresh_display` on the 16 `sNN_src`
    (mpc-vst-TR-MPC #5, released as trmpc-vst-v1.0.2, device-verified). Lesson: grep every layout for `when=` and check what writes the param it reads.
  - JV-880 (`env_view_N`, set by the user's own tap), Daemon (`kb`, `runok`, `mic`; `d->rev`): `when=` panels work on the device.
  - Luckydip, Boris, Clementine, Model-72, dx7, OTT, Maze: no dynamic labels or `when=` found.
- **Not affected** (own hand-written wrapper, no `mpc_engine`): Acid, Euclidier, Monomodule, Cratedigger (no vst.json), force-link-audio,
  the four gmorb dragonfly ports (checked by file listing only, 2026-10-21: worth a look).
- **Vendored copies of `vst2_wrap.c`** (need the copy updated, not just a rebuild): Luckydip (done, PR below), Lewinator56/mpc-vst-helm,
  mmiroshnikov/mpc-airwindows, no3z/mpc-dubsiren, sunskiefer/Evil-Tuner-XXL, LXR02XXL, LXRXXL-BAZZLINE, LXRXXL-ZYNTH, Loop-SaboteurXXL.
- **Submodule users**: FullPace/glass-spheres, overcast; padbangers/drips; sunskiefer/InterzoneXXL, PlateauXXL, RMXXXL, SurgeXXL, Loop-SaboteurXXL.
- **Everyone else with a `vst.json`**: pull mpc-vst-plugins, rebuild, re-release (78 repos; see the scan file in section 6).

## 4. Status of our own ports (2026-10-21)

Each release: patch version +1, previous release's metadata and data folders reused, new `.so`; both armv7 and aarch64 zips, `catalog_check.py --catalog` OK.
Gen2 (aarch64) is **offline-only** everywhere except where a device is named. The source change is on a branch per repo (`wrapper-fix-1021`) with a PR to merge (the
release tag points at that branch's commit).

| Port | Repo | Release | PR to merge | Notes |
|---|---|---|---|---|
| JV-880 (Mini-JV) | sd88me/mpc-vst-jv880 | v1.0.8 (published) | #17 merged | also macro knobs smaller, rows spread (value text was clipped); device-checked |
| Machinemodule (public Gen2) | sd88me/mpc-vst-machinedrum | v0.4.1 (published; v0.4.0 draft still exists, unpublished) | #16 merged | Gen2 only: the Force (armhf) build needs the user's own OS + flash files and is never published; not rebuilt |
| Boris Granular | sd88me/mpc-vst-boris | v1.0.1 | #1 merged | |
| Clementine-XT | sd88me/mpc-vst-clementineXT | clementine-xt-v0.9.6 | #5 merged | |
| Model-72 | sd88me/mpc-vst-model72 | model72-v1.0.1 | #2 merged | `catalog_check` warns: network / process calls (check whether 1.0.0 had it) |
| Dexed (DX7) | sd88me/mpc-vst-dx7 | dx7-v1.0.7 | #13 merged | host tests fail 11 checks, identical on the pre-change wrapper (needs bank data): not caused by this work |
| Morpho-PE | sd88me/mpc-vst-morpho-PE | morpho-pe-v1.0.2 | #1 merged | host test: 1 failure (`osc1_freq` wheel clicks), also on the old wrapper |
| Sturm-TP | sd88me/mpc-vst-sturm | sturm-tp-v0.1.2 | #1 merged | |
| Profit-08 | sd88me/mpc-vst-profit8 | profit-08-v0.1.3 | #8 merged | |
| Luckydip | sd88me/mpc-vst-luckydip | v0.9.2 | #1 (re-vendor) merged; #2 (Gen2 target, params.lock) open | first Gen2 build of Luckydip, offline only |
| Daemon + Daemon Listen | sd88me/mpc-vst-daemon | v1.0.1 (one release, 4 zips) | #1 merged | `catalog_check` warns on network/dlopen (expected, as in 1.0.0) |
| Maze Voice | sd88me/mpc-vst-maze | maze-voice-vst-v1.0.5 | #18 open | Maze Sequencer has its own wrapper (`maze_seq_vst.cpp`): not affected, not released. Checkout moved from the merged `gen2-aarch64` branch to main |
| OTT | sd88me/mpc-vst-OTT | ottmpc-vst-v1.0.1 | #1 open | repo has no `main`: its default branch is `claude/friendly-wozniak-m9ak1l`; Gen2 target added |
| TR-MPC family | sd88me/mpc-vst-TR-MPC | 6w6/8w8/9w9/cw78-vst-v1.1.2, trmpc-vst-v1.0.1, trmpc-tap-fx-vst-v1.0.1 | #4 merged | six plugins, six tags; Gen2 target was missing and is added; TR-MPC host test: 3 fails, same on old wrapper; one transient g++ segfault on the aarch64 build, a retry passed |
| Cratedigger, monomodule, euclidier, acid | | not affected | | own wrapper |

Local only, not for the repo: `params.lock` is committed on each release branch; builds were made against `mpc-vst-plugins` main at 8c7be1c or later.

## 5. How to do a port release (what worked)

**For several plugins in one repo, give `rel.sh` the old tag (`TAG=...`) and a `SUFFIX`; the default picks the repo's latest release.

**Do not run two builds or host tests of one port at once, and do not run an older mpc-vst-plugins checkout's `test_port.sh` on a port while it builds:** both write `<port>/vst/build/params.h`. That race made Profit-08's first build fail with `'param_t' has no member named 'refresh_display'`; a clean rebuild fixed it.

1. A throwaway worktree of mpc-vst-plugins `origin/main`: `git worktree add <dir> origin/main` (the shared checkout switches branches under you).
2. In the port repo: tracked tree clean, branch from main: `git checkout -b wrapper-fix-1021`.
3. `vst.json`: add `"targets": ["armv7", "aarch64"]` if missing (otherwise the aarch64 step silently does nothing).
4. `<worktree>/tools/test_port.sh vst.json` and `... aarch64`; `<worktree>/tools/build_port.sh vst.json` (builds both). A port with its own `build.sh` (jv880, Machinemodule) uses that instead.
5. Package: `release.py` with the **previous release's** `mpc-plugin.json` values (`id`, `about`, `requires`, `license`, `extras`, `user_data`, repo), extras taken
   from the previous zip, new `--version`; once per `.so` (armv7, aarch64). `catalog_check.py --catalog` on each zip.
6. Commit (`vst.json`, `params.lock`), push the branch, `gh release create <tag> <zips> --target <branch commit>`, open the PR, never merge your own without being told.
7. The catalog entry (`catalog/plugins/<id>.json`) follows the latest release; no PR needed unless the name or repo changes.

The scripts used this session lived in the session scratchpad (`rel.sh`, `port.sh`, `rebuild.sh`) and are not in the repo. Step 5-6 is about 60 lines of shell.

## 6. Other authors

- Drafts (not posted): a pinned Discussion in this repo and a short issue per affected repo, the scan table, and the posting plan. Saved in
  `docs/handoff-wrapper-fix/rebuild-notice-drafts.md`; the raw scan (repo, wrapper copy found, vst.json count, submodule) is
  `docs/handoff-wrapper-fix/catalog-scan-2026-10-21.txt`. **Nothing has been posted.**
- Reply to the author who reported it: drafted (`docs/handoff-wrapper-fix/reply-to-reporting-author.md`), **not sent**. It lists what was implemented (1, 6), documented (2-5),
  why a refresh opt-in replaced the line deletion, and asks which build and which effect they saw it on.
- Catalog idea, not done: mark entries built before the fix "rebuild recommended" until the author re-releases.

## 7. Open items, in order

1. Finish batch 1 ((done), then Luckydip (after its PR); ask about Maze and OTT (non-main branches).
2. Merge the open per-port PRs: Luckydip #2, Maze #18, OTT #1.
3. Check the Model-72 catalog warning against its 1.0.0 release.
4. Test one more port on the Force (an effect, since the report says effects show the problem too): track edit → automation with a Q-Link.
5. Post the notice and issues to the other authors after the user approves the text; decide per-repo issues vs one per author.
6. Reply to the reporting author.
7. Done 2026-10-23: probe run on the Force, MPC never asks for opcode 56 and ignores the flags (NOTES.md); no wrapper change. (Was: probe opcode 56 (`effGetParameterProperties`) on a device in `poc/`; only then consider wrapper changes for flaw 5.)
8. Done 2026-10-23 (offline; merged in #530): skip polling for params the layout does not show, and spread the polls across blocks (NOTES.md). Our ports take it at their next normal release; no re-release just for this (decided with the user). Idea, not started: a catalog "rebuild recommended" flag.
9. Machinemodule: publish or delete the old v0.4.0 draft; the Gen2 build is untried on a Gen2 device.
