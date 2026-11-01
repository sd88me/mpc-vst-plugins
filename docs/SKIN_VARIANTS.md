# Skin variants and switching at runtime

Some plugins are worth more than one interface: a compact one for a Live II screen, a hardware-style one
for people who map the panel to a controller, a plain one for people who only need three knobs. This page is
what we learned shipping three interfaces inside one plugin, on two ports (MPC DJ FX 2 3.1.0/3.1.1, MPC Tape Echo
1.2.0), verified on an MPC Live II running MPC OS 3.9.1.2 on 2026-10-28.

## What the device does, and what it does not

**A skin is bound when the instance is inserted.** MPC reads `Plugin Skins/TUI.json` plus the Q-Link banks
at insert time and keeps the result in memory. There is no reload call, no notification, nothing a plugin can
call to re-render itself. Consequences:

- Any skin change costs the user a *remove instance → insert instance*. Design for that: the switch stages the
  next insert, the running instance stays as it is.
- Rewriting a file under a live instance is only safe **for what it has already parsed**, and even that is an
  observation, not a documented guarantee. MPC loads `TUI.json` and the Q-Link banks at insert and keeps them in
  memory, so replacing those two was safe in our tests (MPC Live II, MPC OS 3.9.1.2, 2026-10-28: the instance kept
  running and the next insert picked up the new files). The SDK promises nothing of the sort — a future OS may
  re-read or lock these files. A filmstrip or background PNG the instance still samples is not safe to replace.

**`when=<param>:<option>` works — for widgets.** A layout line carrying `when=mode:H3` becomes an
`additionalInvalidatingHandles: ["IndexedEnabling/0/<n>/Parameter <p>"]` on the component, and MPC hides and
shows that component live when the parameter changes. Verified on the device (a throwaway page with three
labels, one per option: exactly one was visible, and it followed a tap on the parameter).

**It does not work for tabs.** `pageData.tabs[]` has no visibility field, and a tab whose components are all
hidden still shows up in the tab bar. So two variants with *different tab sets* cannot share one TUI — you
would get the union of their tabs (3 + 8 + 3 = 14 in our case). This is the single finding that decides the
design: **variants with different navigation need separate skin folders.**

If your variants are only different *looks* on the *same* tab skeleton, skip all of this and use `when=` on
the art and the controls instead — one TUI, one folder, live switching, no insert.

## The pattern that shipped

All interfaces live in the skin folder, one subfolder each; the top-level files are the active one.

```
Plugin Skins/
  TUI.json                  <- copy of the active interface, paths rewritten into its subfolder
  Q-Links.json              <- same
  ui.txt                    <- the active interface's name (read by the plugin on create)
  studio/    TUI.json  Q-Links.json  bg_*.png  strips…
  classic/   TUI.json  Q-Links.json  …
  rack/      TUI.json  Q-Links.json  …
```

`tools/make_skinset.py` builds that folder from three normal skin builds:

```sh
python3 tools/make_skinset.py -o "portable/<folder>/Plugin Skins" \
    studio=<built studio skin dir> classic=<built classic skin dir> rack=<built rack skin dir> \
    --active studio
```

It copies each build into its subfolder, rewrites every bare image reference inside that TUI to
`<name>/<file>` (absolute imports such as the generic overlays stay as they are), writes the top-level
`TUI.json`/`Q-Links.json` for `--active`, and records the choice in `ui.txt`. Re-running it is idempotent.

### Engine side

The plugin needs one parameter for the choice and one file copy. A minimal contract, in the shape both ports
use (any engine language works):

```c
/* copy <dir>/Plugin Skins/<name>/{TUI.json,Q-Links.json,Q-Links - 8by1.json} to <dir>/Plugin Skins/ */
static void skin_apply(t *self, int idx) {
    for (each of the three names) {
        if (<name> is missing in that interface) continue;      /* e.g. no "Q-Links - 8by1.json" */
        snprintf(tmp, "%s.tmp", dst);
        if (copy_file(src, tmp) && rename(tmp, dst) == 0) ok = 1;   /* never a partial file */
        else remove(tmp);
    }
    if (ok) write_small_file("<dir>/Plugin Skins/ui.txt", "<name>\n");
}

/* on create: the file on disk decides, not the project or the preset */
static void skin_sync(t *self) { self->ui = index_of(read_line("<dir>/Plugin Skins/ui.txt")); }
```

Four details that are not optional:

1. **`ui.txt` is the truth.** The parameter exists so the screen can show and change the choice. If a project
   or preset loads with an older value, ignore it and re-read the file — otherwise loading a preset silently
   rewrites another interface for everyone.
2. **`.tmp` + `rename()`.** MPC may read `TUI.json` at any moment after the user removes the instance.
3. **No image in the switch.** Only the two small JSON files, and only because MPC has already parsed them — the
   note above says how far that carries.
4. **`MODULE_SUBDIR`.** An engine only learns its own folder if `vst.json` sets
   `"defines": {"MODULE_SUBDIR": "\".\""}`; without it `create()` receives an empty `dir` and the copy
   silently does nothing — a switch that looks alive. Treat an empty `dir` as "unknown", not as a path.

### UX

- One control per interface, placed where a settings-style control belongs on that interface (we use the
  machine/preset page of each).
- Say what happens: the label under the control reads *"takes effect on the next insert"*. Without that line
  people tap it and conclude the feature is broken.
- Keep it off the Q-Link banks: a swept knob would rewrite files on every step.

### Cost

Measured with three interfaces (MPC DJ FX 2, 271 files in the zip):

| | per interface | merged |
| --- | --- | --- |
| `TUI.json` | 230–300 KB | one per interface, only the active one is read at insert |
| skin assets | 0.7 MB (cards) … 7.9 MB (filmstrip-heavy) | 15 MB on disk |
| switch | two file copies | < 10 ms, no audio stall worth measuring |

If 15 MB matters (an old card, a full `/sdcard`), keep shipping the single-interface zips as well and let
`make_skinset.py` be the opt-in.

## Watch out: the tab title comes from `qlinks`

`[tab NAME]` names the block, but the string in the tab bar is the title of that tab's `qlinks "TITLE" = …`
line. Renaming one without the other leaves the old label on screen (it cost us a build round). When you
add a tab, set both.
