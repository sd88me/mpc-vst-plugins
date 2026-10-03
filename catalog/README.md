# Plugin catalog

Open-source MPC/Force VST plugins, with versions and download links discovered from each plugin's GitHub releases.
Design: `docs/CATALOG.md`. Formats: `docs/CATALOG_SPEC.md`.

## Add your plugin
1. Make a release zip with `tools/release.py` (or the `vst-release.yml` workflow) with `--repo owner/name --license <SPDX>`,
   and check it: `tools/catalog_check.py <zip> --catalog`. Publish it as a GitHub release on your repo.
2. Open a PR adding `catalog/plugins/<id>.json` (the `<id>` in your manifest):
   ```json
   { "id": "my-synth", "name": "My Synth", "author": "Your name", "repo": "you/my-synth-vst",
     "kind": "instrument", "license": "MIT", "summary": "One line.",
     "style": "sampler", "tags": ["rompler"], "screenshot": "optional URL", "asset_pattern": "*-mpc-armv7.zip" }
   ```
   `style` and `tags` (lowercase slugs) feed the site's Style filter and search; pick a short, common word such as
   `synth`, `sampler`, `drum-machine`, `reverb`, `delay`, `utility`. If your license is not on the open-source list but
   the source is public, add `"source_available": true`: the plugin is listed with a "Restricted use" badge and
   its own license text shown.
3. CI checks the entry and your latest release. Once merged, new releases appear automatically (nightly, or
   run the "Catalog build" workflow).

Open-source licenses (list in `tools/catalog_build.py`) or public source with `source_available` set. No versions or
checksums go in the entry.

## Addins
An addin (a library MPC loads when it starts, through `LD_PRELOAD`) is listed the same way, with `"kind": "addin"` in its
entry. Package it with `tools/release_addin.py` instead of `release.py`: see `docs/ADDINS.md`.

## If your plugin can't publish a zip: build-yourself
Some ports compile the user's own firmware into the plugin (for example a DSP statically recompiled from an Elektron OS
file, with ROM samples), so the built `.so` and installer zip are firmware-derived and must never be published or shared.
Those are listed as **build-yourself**: no release, no download, no checksum. Your repo needs:
- an open-source SPDX license (not `source_available`) and a root `LICENSE` file;
- a one-command script that builds a personal installer from the user's own files, and a `vX.Y.Z` git tag that contains it;
- **no GitHub release with a `*-mpc-armv7.zip` asset**, ever (the nightly build reports it as a licence risk).

Add `catalog/plugins/<id>.json` with `"distribution": "build-yourself"` and the three extra fields:
```json
{ "id": "my-firmware-port", "name": "My Firmware Port", "author": "You", "repo": "you/my-firmware-port",
  "kind": "instrument", "license": "AGPL-3.0-only", "summary": "One line.",
  "distribution": "build-yourself",
  "requires_user_files": [ { "name": "Device OS 1.0.syx", "description": "Your own copy of the OS file." } ],
  "build": { "command": "release/build.sh <Device OS 1.0.syx> [-d <device-ip>]", "script": "release/build.sh",
             "docs_url": "https://github.com/you/my-firmware-port/blob/{tag}/README.md#building", "needs": ["Docker"] },
  "components": [ { "id": "my-firmware-port", "name": "My Firmware Port", "kind": "instrument", "uid": "MyFw" } ] }
```
`components` is optional; use it when one build installs several plugins. The site shows a "Build it yourself" badge,
your `requires_user_files`, the exact `build.command`, the tested-on line and a fixed warning that the result contains
firmware-derived data and must not be shared. `{tag}` in `docs_url` becomes the shown version's tag. Field rules:
`docs/CATALOG_SPEC.md`. `tested.json` works the same as for release plugins.

## Report what you tested on
Optional `tested.json` at the root of your repo's default branch; the nightly build shows it as "Tested on" for the
matching release:
```json
[ { "version": "1.2.0", "device": "MPC Live II", "firmware": "3.6.0", "date": "2026-09-29" } ]
```

## Feed
The site publishes `feed.xml` (Atom, newest 50 non-yanked releases).

## Yank a release
Add `"<id>@<version>"` (or `"<id>@*"` for all versions) to `yanked.json`. It stays in the catalog marked yanked and is
never offered as the latest.

## Build locally
`python3 tools/catalog_build.py --check-registry` validates entries; without the flag it fetches releases (set
`GITHUB_TOKEN` to avoid API limits) and writes `catalog/dist/catalog.json` and `problems.json`.
`python3 tools/catalog_site.py` then writes the site to `catalog/dist/site/` (open `index.html`).

## Guide pages
The site's Install, Build, Workflow and Add yours pages are the Markdown files in `catalog/pages/`. Edit one and
the next site build publishes it. A page starts with front matter (`title`, `nav` for the menu label, `order`,
`summary`); a new file is added to the menu automatically. The Markdown subset is described in `tools/catalog_md.py`.
