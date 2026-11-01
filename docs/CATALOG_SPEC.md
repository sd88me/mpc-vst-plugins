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
  version.xml          identical to our skin's version.xml (<plugincontent>, identifier <vendor>.vst.<name>, version from vst.json `version`, e.g. 3.1.2.0)
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
| `user_files` | optional. The user's own files the plugin needs but a release cannot carry (a synth's ROMs): a list of folders, each `{path, label, description?, hint?, rules}`. `path` must be inside a `user_data` folder (so an upgrade keeps what was uploaded). Each rule says what a good file is: `label`, `ext` (e.g. `[".bin"]`), `size` or `size_min`/`size_max`, `header` (the file starts with this text) or `header_hex` (with these bytes, e.g. `"c0de"`), `signature` (it contains it) with `versions` (`[{prefix, label}]`: the text in the next `[...]` after the signature picks the label, first prefix match wins), and `unverified` + `note` for a kind whose content cannot be checked (it is listed as "looks right" and the plugin has the last word). For a plugin that loads files by name: `save_as` (the name the plugin loads; an upload is saved under it whatever it is called on the computer, and a file already in the folder passes only under that name), `names` (the only names the rule accepts, for kinds of the same size the plugin tells apart by name) and `name_contains` (text the name must contain). Given to `release.py` as `--user-files <json>`; `catalog_check.py` validates it (`tools/user_files.py`). The desktop installer's "Your ROMs and files" step checks each file with these rules before copying it into `<plugin folder>/<path>/` on the device, and lists what is there with the same checks. |
| `arch` | ELF machine of the `.so`; the catalog accepts `armv7` only |
| `max_glibc` | highest `GLIBC_x.y` symbol version needed. Up to 2.32 (MPC OS 2.x) it can be 2.x-compatible; above that and up to 2.36 it is listed as MPC OS 3.x only (a warning); above 2.36 is an error (MPC OS 3.x has 2.39, the catalog toolchain 2.36) |
| `os_compat` | `["2.x", "3.x"]` or `["3.x"]`: the MPC OS generations the plugin works on. `release.py` computes it (`tools/skin_compat.py`); a developer may narrow `["2.x", "3.x"]` to `["3.x"]` by hand, never widen it |
| `about`, `requires` | one-line description; extra requirements |
| `depends`, `conflicts` | optional: the other catalog plugins this version needs, and the ones it must not be installed with ("Dependencies" below). Written only when the release passes `--depends` / `--conflicts` |
| `source_repo`, `license` | `owner/name` on GitHub; SPDX id. **Required for the catalog** |
| `cpu` | `{p99_pct, max_pct, verdict}` from `tools/bench.sh -j`, or null |

## Validator rules (`catalog_check.py`)
Errors (exit 1): unsafe paths; missing required file; manifest missing a field or wrong schema; bad id/version;
`param_compat` != major; arch not armv7; GLIBC above 2.36 (2.33 to 2.36 only warns, and the version is listed as MPC OS 3.x only); `.so` not ELF; a file missing from or wrong in `SHA256SUMS`;
a plugin folder (`portable/<skin>/`) that is missing `version.xml`, `Plugin Skins/TUI.json`, `plugin-meta.xml`, the `.so` or
an extra; a `plugin-meta.xml` whose `file=` is not `%payload-path%/<skin>/<so>` or whose `uid`/`name` disagree with the manifest;
an `os_compat` that is not `["2.x","3.x"]` or `["3.x"]`, or that claims 2.x when the check below does not confirm it;
an unknown `layout`; with `--catalog`, no `source_repo` or `license`; with `--expect-id/--expect-repo`, a registry mismatch.
Zips of the old layout (no `layout` field) are checked against their own rules (`payload/`, `plugin.xml`). `catalog_check.py` warns for each one ("old layout"); with `--require-portable` it is an error. The builder reports a problem (and `catalog_issues.py` opens an issue) when a plugin's **newest stable** release is of the old layout; older versions stay silent history. A PR that adds or changes a registry entry runs `catalog_build.py --require-portable <ids>`, so a new listing must already release the portable folder. The plugins those entries depend on are built
too, so the dependency check sees them, but only the named entries are judged (2026-10-31: before this, every dependent's PR failed with its
host "not in the catalog").

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
`style` (one slug) and `tags` (slugs) are optional and drive the site filters. `role` is optional, `"midi"` only, and only on an `instrument`: the plugin is a MIDI generator or sequencer that plays other tracks (or outboard gear) rather than making its own sound; the catalog page and the installer list it under their MIDI tab instead of Instruments. A synth with a built-in arpeggiator is not `midi`. `source_available: true` is required
when `license` is not on the open-source list; the site shows a "Restricted use" badge.
No version fields: they are read from the releases (or, for `build-yourself`, the git tags). `id` must equal the manifest `id`, `repo` the manifest
`source_repo`. Stable releases are GitHub releases that are not prereleases; prereleases form the beta channel.
`depends` and `conflicts` (optional, release entries only) are the fallback for releases whose manifest has no such key: a maintainer can
declare a dependency the author's zips don't, without a new release ("Dependencies" below).

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
"latest_beta", "downloads", "updated", "tier", "verified_on", "bar_missing", "featured" ]}`, versions
newest first. A record is what `catalog_check.py --json` prints (`version`, `size`, `sha256` of the zip,
`param_compat`, `max_glibc`, `os_compat`, `os_compat_why`, `cpu`, `defer`, `requires`, `manifest`, and for an addin `hooks`) plus `url`, `date`, `channel` (`stable`|`beta`), `notes`, `yanked`
and `tested` (`[{device, firmware, date}]`), added by the builder. `tier` is `verified`|`listed`|`experimental`; `verified_on`
(`[]`, or `gen1` and/or `gen2`) says which device generations the newest stable release was tested on: a `tested` device naming Gen2 is
`gen2` (only on a version with an aarch64 build), any other is `gen1`. Readers must treat a missing `verified_on` on a verified plugin as `["gen1"]`.
A version may also carry `assets.aarch64` and `gen2: true` (a Gen2 build beside the armv7 zip, docs/GEN2.md). **Gen2 only:** an entry whose `asset_pattern` names the
aarch64 zip and no armv7 one (`"*-mpc-aarch64.zip"`) lists that zip alone: `assets: {aarch64: {...}}`, `gen2: true`, `gen2_only: true`, and `url`/`sha256`/`size` are the
aarch64 zip (a reader that knows no `gen2_only` still parses it); in `catalog.tsv` the size, sha256 and url columns are `-`. A client on a Gen1 device or a Force must not offer a
`gen2_only` version. The zip's manifest `arch` must be `aarch64`.
`defer` is true when the zip's `install.sh` understands `-n` (the caller stops and starts MPC), false for an older installer that restarts MPC by
itself; batch installers (the desktop app, `mpc-store.sh`) run such a zip separately and use the flag to say how often MPC will restart.
`requires` (2026-10-26) is the manifest's one line of extra requirements, trimmed (`""` when none): ROMs, a network connection, another
plugin in the same project. The site shows it as a "Needs" row and both installers print it before installing. Older catalogs have it only
in `manifest.requires`; readers fall back to that.
**Addins that may break each other (2026-10-26):** an addin's record has `hooks`, the functions its `so` defines (global or weak functions
in its dynamic symbol table, less `_init`/`_fini` and a bundled C/C++ runtime's names, `catalog_check.RUNTIME_PREFIXES`; data and its helper programs
don't count; 2026-10-31), and `chains`, true when that library looks like it passes a hooked call on (it imports `dlsym` or `dlvsym`, and doesn't
both import `dlopen` and contain `libasound.so`; a record without it counts as true). A version with a Gen2 zip has both builds' hooks, and chains
only when both builds do (2026-10-31).
Each addin plugin gets `shares_hooks: [{id, name, symbols, unchained}]`: the other addins whose newest version (stable, else beta) defines some of the
same names, listed only when at least one of the two doesn't chain (`unchained`, their ids). The builder writes the same pairs to `overlaps.json`
(`[{ids: [a, b], versions: [va, vb], symbols, unchained}]`). In `LD_PRELOAD` the first definition wins, so such a pair may stop one of them
working. It is information, never a rejection: the site shows it on the card, `mpc-store.sh` and the desktop app warn when the other addin is
installed or chosen too, and `catalog_issues.py` opens one issue per pair and set of functions.

### Dependencies (2026-10-26)
A version may need another catalog plugin (an Out or Tap that only works with its host plugin), or be unable to live beside one.

- **Syntax** (`tools/deps.py`, the one parser): a dependency is a catalog id with optional rules, joined by commas, all of which must hold:
  `tr-mpc`, `incipience>=1.0.0`, `percolator>=2.0.0,<3.0.0`, `tr-mpc=1.2.0`, or `machinemodule-gen2=same` (the declaring version's own version;
  `same` stands alone after `=`). Operators: `>=`, `<=`, `>`, `<`, `=`. A conflict is a bare catalog id; either side declaring it counts.
  An id is listed once, never as both a dependency and a conflict, and never the plugin's own.
- **Where they come from:** the manifest's `depends` / `conflicts` (`release.py` / `release_addin.py --depends ... --conflicts ...`) when the key is
  there, else the registry entry's. `catalog_check.py` and `catalog_build.py --check-registry` reject bad specs.
- **In `catalog.json`:** each version record has `depends: [{id, rules: [[op, X.Y.Z], ...], pick: {armv7, aarch64}}]` (`same` resolved) and
  `conflicts: [ids]`. `pick` is the newest listed version of the dependency that meets the rules and has a build for that device generation
  (`null` when none).
- **Hiding:** a version is listed for a device generation only when every dependency has a listed, unyanked version that meets the rules and has
  that generation's build; a stable version needs a stable one. The builder repeats this until nothing changes (hiding one version can hide
  what depends on it). A version that loses its Gen2 build loses `assets.aarch64` and `gen2`; one that loses its Gen1 build becomes `gen2_only`;
  one that loses both is dropped. Each hidden build is a problem the builder reports (`catalog_issues.py` opens an issue).
- **Installers** (`mpc-store.sh`, the desktop app, the same rules): a batch's plugins with no build for the device are skipped first
  (`mpc-store.sh`; the app doesn't offer them), then it gains each missing dependency at its `pick`, or the update of an
  installed one that is too old, with the reason shown. They refuse, with nothing changed, unless forced (`mpc-store.sh --force`, the app's
  "Install anyway" / "Remove anyway"): a dependency with no build for the device, one that would have to go back to an older version, a batch
  that doesn't fit what it needs, an install that breaks an installed plugin's dependency (when a newer version of that plugin fits, it is
  updated instead), a dependency update or such an update that is a major change (`param_compat`; `mpc-store.sh --major` allows it, as for
  `update`; 2026-10-31), a conflict either way, and removing a plugin that an installed one needs. An installed plugin whose version wasn't
  recorded is left as it is, but still counts as installed for conflicts and for what it needs (2026-10-31: both installers).

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
  installer understands `-n`), `os_compat` (`2.x,3.x`, `3.x` or `-`), `max_glibc` (the newest glibc the library needs, or `-`), `size64`, `sha256_64`,
  `url64` (the Gen2 zip), `requires` (the version's `requires`), `shares_hooks` (comma list of the addin ids in `shares_hooks`, 2026-10-26), `depends` (`id:rules:pick:pick64`
  joined by `;`, rules as `>=1.0.0,<2.0.0` or `*` for any version, a missing pick `-`) and `conflicts` (comma list of ids). `mpc-store.sh` and the
  desktop app use `os_compat` and `max_glibc` to warn about a plugin that will not load on the device (it needs a newer glibc than the device has) or is 3.x only on
  a device that looks like MPC OS 2.x (glibc below 2.34); they warn and never block.
- **`catalog.tsv`, addins:** `skin` and `uid` are `-`. `mpc-store.sh` installs an addin to `/data/mpc-addins/<id>` and reads the installed
  version from the folder's `addin.manifest` (`ADDIN_VERSION`), not from `.mpc-store`.

- **Share pages, `p/<id>.html`:** `catalog_site.py` writes one small page per plugin id (ids that are lowercase words joined by hyphens) next to
  `index.html`. It carries the card's Open Graph and Twitter tags (title, summary, https screenshot) because link previews read neither the
  `#p=<id>` hash nor scripts, then sends a browser on to `index.html#p=<id>` by script (not a meta refresh: Facebook's crawler would follow it).
  The catalog page's popup, "Copy link" button and card links point at these pages. Not part of `catalog.json`, `catalog.tsv` or any installer.

## Companion apps (`catalog/apps.json`)
Desktop tools that work with a standalone MPC but are not plugins. Not part of `catalog.json`, `catalog.tsv` or any installer: the site
shows them on its Companion apps tab, and `apps.json` is published next to `catalog.json`. Checked by `tools/app_check.py` (the site build
refuses an invalid file). `{"schema": 1, "apps": [...]}`, each app:

| field | |
|---|---|
| `id`, `title`, `summary`, `author`, `license`, `repo` | required; `id` is lowercase words joined by hyphens, `repo` is `owner/name` |
| `release` | required https URL of the release page |
| `platforms` | required, from `macos`, `windows`, `linux` |
| `release` | https URL of the release page; optional when `assets` is given (then set from the release) |
| `assets` | optional rules `{platform, label, pattern}` (`pattern` is an fnmatch over asset names); `tools/app_resolve.py` reads them against the newest stable release (no drafts or prereleases) and fills `downloads`, `version` and `release` |
| `downloads` | optional list of `{platform, label, url, sha256}`, `platform` one of the app's, `url` https, `sha256` 64 lowercase hex. Written by `app_resolve.py`; when there are no `assets`, or the release can't be read, the pinned list in the file is used |
| `version`, `needs` (list), `tested` (`{device, os}`) | optional, shown on the card |
| `screenshot` | optional https URL of a picture for the card (as a plugin's `screenshot`: 1280×628, the plugin area's shape, fits best; the card shows it at 2:1) |

`tools/app_resolve.py` runs in the Catalog build workflow (nightly, on pushes to `main` touching the catalog, and by hand) and writes `catalog/dist/apps.json`, which `catalog_site.py` prefers over `catalog/apps.json`. The sha256 is the asset's GitHub `digest`, else its line in a `SHA256SUMS` asset of the same release; an asset with neither is left out and reported. A failed read keeps the pinned `downloads`, so a bad night does not blank a card. A new release therefore appears on the next build, with no PR to this repo.

## Portable paths (for engines)
Engines locate their data next to the `.so` (`wrapper/plugin_dir.h`, `MODULE_SUBDIR`), never at a fixed `/sdcard`.
The installers currently still install to the directory in the entry's `file=` and skins to `/sdcard/Synths`.
