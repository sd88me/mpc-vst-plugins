# mpc-vst-plugins: agent guide

Native VST2 plugins for Akai MPC OS standalone devices (MPC Live/One/X/Key, Force), loaded by MPC's
built-in JUCE plugin host, with native MPC screen skins. Start here:

1. `docs/NOTES.md`: everything verified on hardware so far, plus open issues. Treat it as the source of
   truth, and add to it whenever you verify something new (with the date).
2. `docs/PORTING.md`: the checklist for porting an engine or app to a plugin.
3. `docs/BENCH.md` (CPU check) and `docs/RELEASING.md` (release zip + installer) before shipping a port.
   `docs/ROADMAP.md`: repo features still to do. `docs/COMMUNITY_SKINS.md`: design techniques from other people's ports. `docs/ADDINS.md`: addins (libraries MPC preloads) in the catalog.
4. `.claude/skills/mpc-vst-plugin/SKILL.md`: the build → skin → register → test workflow and gotchas.

Ground rules:
- Every port and release must be catalog-conformant (`mpc-plugin.json` via `release.py --repo --license`, `catalog_check.py --catalog`
  OK): see `docs/PORTING.md` section 5 and `docs/CATALOG.md`.
- Offline first: x86 host test (`tools/test_port.sh <vst.json>`, ASan) and an offline skin preview before anything goes
  to a device.
- The device is shared with the user's live setup. Ask before restarting MPC, back up `MPC.settings` before
  editing it (with MPC stopped), and stage files as `x.new` then `mv`.
- Never commit Akai's stock skin JSON or PNGs, or the Steinberg SDK. Describe formats instead; the VST2 ABI here is
  hand-written.
- Keep the repo device-generic: no private IPs, serials or MockbaMod-specific naming. MockbaMod facts go in
  NOTES.md only where they affect behaviour.
- Docs sync: a change that adds or alters a feature, tool, vst.json key, `defines` option, workflow or verified fact updates the docs
  it touches in the same PR (map in the skill's "Docs sync"; the PR template asks). Date new facts and say offline vs device. If
  none apply, write "no docs needed" in the PR. Before merging or finishing, list the recent PRs and check their docs for stale claims.
- Commit trailers per the session's instructions; one commit per concern.
