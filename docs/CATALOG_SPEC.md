# Catalog specification (schema 1)

Three formats: the **release manifest** inside every zip (written by `tools/release.py`), the **registry entry**
(written once by a plugin's author), and the generated **catalog.json**. Design and roadmap: `docs/CATALOG.md`.
Validate a zip with `tools/catalog_check.py <zip> [--catalog]`; the offline test is `python3 tools/test_catalog.py`.

## Release zip
`<Name>-<X.Y.Z>-mpc-armv7.zip`, one top folder `<Name>-<X.Y.Z>/` (layout in `docs/RELEASING.md`), containing
`mpc-plugin.json`, `install.sh`, `uninstall.sh`, `plugin_list.awk`, `INSTALL.md`, `SHA256SUMS` and the plugin folder
`portable/<skin>/` (below). Every file except `SHA256SUMS` is listed there. No absolute or `..` paths, no symlinks leaving
the package. Releases made before 2026-09-29 have the old layout (`payload/`, `plugin.xml`, no `layout` field in the manifest);
`catalog_check.py` still accepts them so the catalog can list their history, but new releases are always the plugin folder.

### Plugin folder (`portable/<skin>/`)
The plugin is **one self-contained folder**, the same shape as installers that copy a folder into the device's `Synths`
content folder and register it from a file inside it (Locrian's builds; verified on a Force 2026-09-29, `docs/NOTES.md`):
```
<Vendor> - VST - <Name>/
  version.xml          identical to our skin's version.xml (<plugincontent>, identifier <vendor>.vst.<name>, version 1.0.0.0)
  plugin-meta.xml      the plugin-list <PLUGIN .../> element, with file="%payload-path%/<Vendor> - VST - <Name>/<so>"
  <name>.so            the plugin, inside the skin folder
  Plugin Skins/        the skin
  <extras>             any engine data, next to the .so (relative paths like `engine/` for MODULE_SUBDIR)
```
`install.sh` / `uninstall.sh` (`sh install.sh [-y] [-t <synths-dir>]`, default target `/sdcard/Synths`) copy the folder in,
register it with `%payload-path%` replaced by the Synths folder, and replace an older entry of the same `uid` (an old
`/sdcard/vst/...` install is not duplicated). Files the user adds inside the folder are kept across upgrades and
uninstalls: the paths in the manifest's `user_data` (folders where the user puts ROMs, kits or banks, given to `release.py`
with `--user-data`). For a plugin installed the old way the installer also removes the old `.so` and the data the package
ships in `/sdcard/vst`, and moves the user's own `user_data` files from `/sdcard/vst/<path>` into the plugin folder (merged
over the shipped files), only after the settings edit succeeded.

`%payload-path%` is a placeholder the installer replaces with the directory it copied the folder into (for example
`/media/<card>/Synths`). The folder name in `file=` must equal the folder's own name. Because the `.so` can end up
anywhere, engines must find their data next to it (`wrapper/plugin_dir.h`, `MODULE_SUBDIR`), never at a fixed
`/sdcard/...` path; `gen_vst.py` warns about a fixed path.

## `mpc-plugin.json`
(For a plugin. An addin's manifest is under "Addins" below.)

| field | meaning |
|---|---|
| `schema` | `1` |
| `id` | catalog id, `[a-z0-9]+(-[a-z0-9]+)*`; never changes |
| `name`, `manufacturer` | as in the plugin list entry |
| `version` | `X.Y.Z`; X bumps when parameter indices change |
| `param_compat` | equals X: a bump means saved projects change |
| `kind` | `instrument` or `effect` |
| `uid` | VST uid (hex), same as `plugin-meta.xml`; never changes |
| `layout` | `"portable"` (the plugin folder). Absent in releases of the old layout |
| `so` | library file name |
| `skin`, `folder` | skin folder name; the plugin folder in the zip, `portable/<skin>` |
| `extras` | data shipped next to the `.so`, relative to the plugin folder |
| `user_data` | list of folders inside the plugin folder that hold the user's own files; the installer keeps them (and moves them in from `/sdcard/vst` for an old-layout install) |
| `arch` | ELF machine of the `.so`; the catalog accepts `armv7` only |
| `max_glibc` | highest `GLIBC_x.y` symbol version needed. Up to 2.32 (MPC OS 2.x) it can be 2.x-compatible; above that and up to 2.36 it is listed as MPC OS 3.x only (a warning); above 2.36 is an error (MPC OS 3.x has 2.39, the catalog toolchain 2.36) |
| `os_compat` | `["2.x", "3.x"]` or `["3.x"]`: the MPC OS generations the plugin works on. `release.py` computes it (`tools/skin_compat.py`); a developer may narrow `["2.x", "3.x"]` to `["3.x"]` by hand, never widen it |
| `about`, `requires` | one-line description; extra requirements |
| `source_repo`, `license` | `owner/name` on GitHub; SPDX id. **Required for the catalog** |
| `cpu` | `{p99_pct, max_pct, verdict}` from `tools/bench.sh -j`, or null |

## Validator rules (`catalog_check.py`)
Errors (exit 1): unsafe paths; missing required file; manifest missing a field or wrong schema; bad id/version;
`param_compat` != major; arch not armv7; GLIBC above 2.36 (2.33 to 2.36 only warns, and the version is listed as MPC OS 3.x only); `.so` not ELF; a file missing from or wrong in `SHA256SUMS`;
a plugin folder (`portable/<skin>/`) that is missing `version.xml`, `Plugin Skins/TUI.json`, `plugin-meta.xml`, the `.so` or
an extra; a `plugin-meta.xml` whose `file=` is not `%payload-path%/<skin>/<so>` or whose `uid`/`name` disagree with the manifest;
an `os_compat` that is not `["2.x","3.x"]` or `["3.x"]`, or that claims 2.x when the check below does not confirm it;
an unknown `layout`; with `--catalog`, no `source_repo` or `license`; with `--expect-id/--expect-repo`, a registry mismatch.
Zips of the old layout (no `layout` field) are checked against their own rules (`payload/`, `plugin.xml`).

**MPC OS compatibility (`tools/skin_compat.py`, docs/OS2_SKINS.md).** The checker works out `os_compat` itself, for every version, so releases
made before the field existed are classified too. A version is `2.x` and `3.x` when the `.so` needs glibc 2.32 or less and every
object in `Plugin Skins/TUI.json` and `Q-Links.json` has a version, with fields, that the stock skins of MPC OS 2.15.1 use (the table is
`tools/skin_roles_2x.json`: version numbers and field names only, rebuilt with `skin_compat.py build <stock Synths folder>`); otherwise it
is `3.x` and the record carries `os_compat_why`, up to five short reasons ("TUI:tabs[] version 3 (2.15.1 uses 1)"). This is a check against
one 2.x version's own skins, not a test on a 2.x unit: the site and installer should say so, and show a plain "2.x" only for versions
with a 2.x device test in `tested.json`. Add-ons have no skin and carry no `os_compat`.
Warnings (need a human look): `install.sh`/`uninstall.sh`/`plugin_list.awk` differ from the repo's current template
(regenerated from the manifest and compared; not done for old-layout zips), `max_glibc` not recorded.

## Registry entry: `plugins/<id>.json` (catalog repo)
```json
{ "id": "my-synth", "name": "My Synth", "author": "Someone", "repo": "someone/my-synth-vst",
  "kind": "instrument", "license": "MIT", "summary": "One line.",
  "style": "synth", "tags": ["poly"], "source_available": false,
  "screenshot": "optional https URL", "asset_pattern": "*-mpc-armv7.zip" }
```
`style` (one slug) and `tags` (slugs) are optional and drive the site filters. `source_available: true` is required
when `license` is not on the open-source list; the site shows a "Restricted use" badge.
No version fields: they are read from the releases (or, for `build-yourself`, the git tags). `id` must equal the manifest `id`, `repo` the manifest
`source_repo`. Stable releases are GitHub releases that are not prereleases; prereleases form the beta channel.

### Build-yourself entries
For a plugin that cannot publish a zip because the build embeds the user's own firmware. Schema 1 is unchanged: the
fields below are additive and `distribution` defaults to `"release"`, so existing entries and readers are unaffected.
```json
{ "id": "monomodule", "name": "Monomodule One + FX", "author": "sd88me", "repo": "sd88me/mpc-vst-monomodule",
  "kind": "instrument", "license": "AGPL-3.0-only", "summary": "...",
  "distribution": "build-yourself",
  "requires_user_files": [ { "name": "Monomachine OS 1.32B .syx", "description": "Your own copy of the OS file." } ],
  "build": { "command": "release/release.sh <Monomachine OS 1.32B .syx> [-d <device-ip>]", "script": "release/release.sh",
             "docs_url": "https://github.com/sd88me/mpc-vst-monomodule/blob/{tag}/README.md#install", "needs": ["Docker"] },
  "components": [ { "id": "monomodule-one", "name": "Monomodule One", "kind": "instrument", "uid": "MnmO" },
                  { "id": "monomodule-fx", "name": "Monomodule FX", "kind": "effect", "uid": "MnmF" } ] }
```
| field | rules |
|---|---|
| `distribution` | `release` (default) or `build-yourself` |
| `license` | an open SPDX id from the list in `tools/catalog_build.py`; `source_available` is rejected |
| `requires_user_files` | required, non-empty: `{name, description}` each |
| `build.command` | required; shown verbatim and must contain `build.script` |
| `build.script` | required; a path inside the repo (no leading `/`, no `..`); a tag without it is not listed |
| `build.docs_url` | required, `https://`; `{tag}` is replaced by the shown version's tag (`HEAD` if none) |
| `build.needs` | optional list of strings (tools the build needs) |
| `components` | optional non-empty list of `{id, name, kind, uid?}`; ids are unique across the whole registry; `uid` is the four characters from `vst.json` |
| `asset_pattern` | not allowed |

`requires_user_files`, `build` and `components` are rejected on a `release` entry.

Versions are the repo's `vX.Y.Z` git tags (a leading `v` is optional; other tags are ignored). A tag is listed only if
`build.script` exists at it. An older tag without the script is skipped quietly (tags are never moved, so it could not
be fixed); only the newest tag missing it is reported. Builder checks and reports in `problems.json`: repo unreadable,
no valid tag, script missing at the newest tag, and (loudly, `LICENCE RISK`) a GitHub release with a `*-mpc-armv7.zip` asset. A tag without a root
`LICENSE`/`COPYING` file gets a version warning. There is no zip, so no `catalog_check.py`, sha256 or size.

## `catalog.json` (generated)
`{"schema": 1, "generated": <ISO time>, "plugins": [ <registry fields> + "versions": [ <record>, ... ], "latest",
"latest_beta", "downloads", "updated" ]}`, versions
newest first. A record is what `catalog_check.py --json` prints (`version`, `size`, `sha256` of the zip,
`param_compat`, `max_glibc`, `os_compat`, `os_compat_why`, `cpu`, `defer`, `manifest`) plus `url`, `date`, `channel` (`stable`|`beta`), `notes`, `yanked`
and `tested` (`[{device, firmware, date}]`), added by the builder.
`defer` is true when the zip's `install.sh` understands `-n` (the caller stops and starts MPC), false for an older installer that restarts MPC by
itself; batch installers (the desktop app, `mpc-store.sh`) run such a zip separately and use the flag to say how often MPC will restart.

Every plugin also has `distribution`. For `build-yourself` plugins the record carries the entry's `requires_user_files`,
`build` and `components`, and each version is `{version, tag, date, channel: "stable", source_url, yanked, downloads: 0,
warnings, tested, notes: ""}`: no `url`, `size`, `sha256`, `param_compat` or `manifest`. Readers must treat those
keys as absent for such entries (an installer must skip them: there is nothing to download).

## Addins (`kind: "addin"`)
An addin is a library MPC preloads (`docs/ADDINS.md`), released with `tools/release_addin.py`. Schema 1 is unchanged; an addin's
zip uses `layout: "addin"`:

- **Zip:** `<Name>-<X.Y.Z>-mpc-armv7.zip`, one top folder holding exactly `mpc-plugin.json`, `install.sh`, `uninstall.sh`,
  `addin-lib.sh` (from `tools/release/addin`), `addin.manifest`, `INSTALL.md`, `SHA256SUMS`, the `.so` and the settings and data
  files the manifest names. No sub folders, nothing else.
- **`mpc-plugin.json`:** `schema`, `id`, `name`, `version`, `param_compat` (the major version), `kind: "addin"`, `layout: "addin"`,
  `so`, `conf` (the settings file or null), `files` (the other files), `user_data` (`[conf]`), `arch`, `max_glibc`, `about`,
  `requires`, `source_repo`, `license`, `cpu: null`. No `uid`, `skin` or `folder`.
- **Validator:** the plugin rules that apply (paths, checksums, id, version, glibc, `--catalog` fields, registry match), plus:
  `addin.manifest` is only plain assignments of the known `ADDIN_*` keys and agrees with `mpc-plugin.json` (id, name, so, conf,
  files, version); the `.so` is a 32-bit ARM ELF; nothing else is in the package. A changed installer is a warning, as for plugins.
  `defer` is true for the installer (it understands `-n`).
- **Registry:** `"kind": "addin"` on a release entry (never `build-yourself`); the builder refuses a release whose zip is an addin
  under a plugin entry, or the reverse.
- **`catalog.tsv` columns** (tab separated, `-` when empty; clients read the ones they know and ignore extra ones): `plugin`, `id`, `version`, `latest`
  (1 for the newest stable), `kind`, `name`, `skin`, `uid`, `param_compat`, `size`, `sha256`, `url`, `user_data` (comma list), `defer` (1 when the
  installer understands `-n`), `os_compat` (`2.x,3.x`, `3.x` or `-`), `max_glibc` (the newest glibc the library needs, or `-`). `mpc-store.sh` and the
  desktop app use the last two to warn about a plugin that will not load on the device (it needs a newer glibc than the device has) or is 3.x only on
  a device that looks like MPC OS 2.x (glibc below 2.34); they warn and never block.
- **`catalog.tsv`, addins:** `skin` and `uid` are `-`. `mpc-store.sh` installs an addin to `/data/mpc-addins/<id>` and reads the installed
  version from the folder's `addin.manifest` (`ADDIN_VERSION`), not from `.mpc-store`.

## Portable paths (for engines)
Engines locate their data next to the `.so` (`wrapper/plugin_dir.h`, `MODULE_SUBDIR`), never at a fixed `/sdcard`.
The installers currently still install to the directory in the entry's `file=` and skins to `/sdcard/Synths`.
