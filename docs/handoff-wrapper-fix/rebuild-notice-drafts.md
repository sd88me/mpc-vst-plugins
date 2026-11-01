# Drafts: wrapper fix rebuild notice (for review, nothing posted)

## Scan of catalog repos (2026-10-21, 98 plugin repos, GitHub API, default branch)

| Group | How it gets the wrapper | What the author does | Repos |
|---|---|---|---|
| A | `vst.json`, built with a checkout of mpc-vst-plugins (`build_port.sh`) | pull mpc-vst-plugins, rebuild, re-release | 78 repos (most of saustin2010, 3dthc, Devko, gmorb liminal/sfizz, jacob-sabella, nachtaktiv303, MagicStino, poloq-instruments, stampman3000-jpg, SamplingHigh, djokenzi, B0ss-M, mcardonaserrano, mmiroshnikov/maschine-group, ours) |
| B | git submodule of mpc-vst-plugins | bump the submodule, rebuild, re-release | FullPace/glass-spheres, FullPace/overcast, padbangers/drips, sunskiefer/InterzoneXXL, PlateauXXL, RMXXXL, SurgeXXL (yanked), Loop-SaboteurXXL |
| C | vendored copy of `vst2_wrap.c` (all still contain the line) | update the copy (or apply the patch), rebuild, re-release | Lewinator56/mpc-vst-helm, mmiroshnikov/mpc-airwindows, no3z/mpc-dubsiren, sd88me/mpc-vst-luckydip, sunskiefer/Evil-Tuner-XXL, LXR02XXL, LXRXXL-BAZZLINE, LXRXXL-ZYNTH (two copies each: `src/wrapper` and `third_party`), Loop-SaboteurXXL (`src/wrapper` too) |
| — | no vst.json, no wrapper copy: their own wrapper, probably not affected | nothing (worth one manual look) | gmorb/mpc-vst-dragonfly-* (4), macdigi/force-link-audio, sd88me/mpc-vst-cratedigger |

Caveat: in group A, "has a vst.json" means it builds with this repo's wrapper unless the port sets `custom_skin` with its own wrapper. A quick look per author before posting is worth it.

Our own ports that need `"refresh_display": true` before rebuilding: Machinedrum (`trackN_machine`), and to check: Morpho-PE, Profit-8, Sturm (dynamic labels), Daemon (unpolled readouts).

---

## 1. Notice in sd88me/mpc-vst-plugins (Discussion, Announcements category, pinned)

**Title:** Wrapper fix: Q-Links on the automation screen. Please rebuild and re-release your ports

Hi all, a heads-up for everyone whose plugin is built on this repo's wrapper (`wrapper/vst2_wrap.c`), which covers most ports in the catalog.

**What was wrong.** On track edit → automation, the physical Q-Links didn't move a plugin parameter, or it snapped straight back, while the on-screen knobs worked. It shows up mostly on instruments, but effects have been reported too. The wrapper answered every parameter write from MPC (each Q-Link event, each automation step) with an `audioMasterUpdateDisplay`, and MPC rebuilds its parameter screen on every one. Thanks to the port author who tracked this down and confirmed the fix on a Force.

**What changed** (#486, #487, #488, #489):
- A plain parameter write no longer asks for an UpdateDisplay. Prev/next stepper buttons (`step_of`) still do, and text readouts still refresh through the 100 ms poll.
- At most one UpdateDisplay per 50 ms.
- New per-param key `"refresh_display": true`. Put it on a param that other **unpolled** text depends on: a selector behind `dynamic_name`/`dynamic_display` labels, or a `"poll": false` readout bound with `get=`. Without it, those labels won't follow the selector anymore.
- `gen_vst.py` now writes `params.lock` next to your `vst.json` on the first build. Commit it. The build fails if an existing param changes index; inserting a param mid-list silently breaks saved projects, automation and Q-Link maps.
- `docs/PORTING.md` has new notes on the engine lock, idle hosts and poll cost.

**Existing builds are not fixed.** The wrapper is compiled into your `.so`, so you need to rebuild:
1. Update the wrapper:
   - built from a checkout: `git pull` in mpc-vst-plugins;
   - submodule: `git submodule update --remote <path>` and commit;
   - vendored copy of `wrapper/vst2_wrap.c`: copy the new one in, or apply the change from #486 (in `set_param_now()`, the last line `w->need_update_display = 1;` becomes `if (p->refresh_display) ...`), and use the new `tools/gen_vst.py`, because `param_t` gained a field.
2. If any labels or text follow another param, add `"refresh_display": true` to that param.
3. `tools/test_port.sh <vst.json>` (and `aarch64` if you ship Gen2) must print PASSED.
4. `tools/build_port.sh <vst.json>`.
5. On a device, test Q-Links on **track edit → automation**, not only on the plugin screen. Check that any stepper readouts and dynamic labels still update.
6. Bump `version`, then `release.py --repo ... --license ...`, `catalog_check.py --catalog`, publish the release, and open a catalog PR with the new version (docs/RELEASING.md).

Questions or regressions: reply here. We'll mark catalog entries "rebuild recommended" until they're updated.

---

## 2. Issue for each affected repo (groups A, B, C)

**Title:** Rebuild needed: mpc-vst-plugins wrapper fix for Q-Links on the automation screen

Hi! This plugin is built on the mpc-vst-plugins VST2 wrapper, which had a bug: on track edit → automation, Q-Links couldn't move plugin parameters (each write triggered a full screen rebuild in MPC). It's fixed upstream, but existing builds keep the bug until they're rebuilt.

**For this repo:** {GROUP_LINE}

Then rebuild, run `tools/test_port.sh`, check Q-Links on the automation screen on a device, bump the version, re-release, and send a catalog PR. If any labels follow another param (`dynamic_name`), add `"refresh_display": true` to that param.

Full details and steps: {DISCUSSION_LINK}

Thanks for building on it, and sorry for the trouble.

GROUP_LINE per group:
- A: "pull the latest mpc-vst-plugins before building."
- B: "bump the mpc-vst-plugins submodule (`git submodule update --remote`)."
- C: "your vendored `{PATH}` still has the old behaviour. Update it from upstream (and use the new `tools/gen_vst.py`), or apply the change from sd88me/mpc-vst-plugins#486."

---

## Posting plan (once you approve)
1. Merge #486–#489, after the device check on our Force.
2. Post the Discussion and pin it.
3. Open one issue per repo in groups A–C, about 95 issues, mostly saustin2010 (34) and sunskiefer (9). Alternative: for authors with many repos, one issue in their main repo listing all of them, to avoid flooding them.
4. Rebuild and re-release our own 17 sd88me ports.
