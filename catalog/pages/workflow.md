---
title: Release workflow
nav: Workflow
order: 30
summary: The path from a working build to a tested, checksummed release, and how to get it listed in the catalog.
---

Develop on your PC first, test on the device once, and let a workflow package the zip that people will actually install. The order matters because the device is somebody's live setup.

## The loop
1. **Build** with `tools/build_port.sh`. It produces the `.so`, the skin and the plugin-list entry.
2. **Host test** with `tools/test_port.sh`. It must print `PASSED`.
3. **Preview the skin** with `tools/studio.py preview`, and look at every page.
4. **Measure CPU** on a device: `tools/bench.sh build/x.so <device-ip> -j | tee build/bench.txt`. It must **PASS**, or **WARN** with a note in your release notes. A plugin gets about 2.9 ms per audio block and shares it with everything else in the project.
5. **Package** the zip (below).
6. **Smoke test the zip** on a device with its own `install.sh`: load the plugin on a track, play it, turn every page and Q-Link, save and reload a project, then run `uninstall.sh`.
7. **Publish** the release on GitHub.

## Package the zip
```
tools/release.py --so build/x.so --skin "build/skin/<vendor> - VST - <Name>" \
    --entry build/pluginlist-entry.xml --version 1.2.0 --bench build/bench.txt \
    --about "One line about the plugin." \
    --repo you/your-plugin-repo --license MIT -o dist
tools/catalog_check.py dist/Name-1.2.0-mpc-armv7.zip --catalog
```

You get `Name-1.2.0-mpc-armv7.zip`: the plugin, its skin, `install.sh`, `uninstall.sh`, a generated `INSTALL.md`, checksums and a manifest (`mpc-plugin.json`) the catalog reads. `catalog_check.py` runs the same checks the catalog does, so a zip that passes here will be listed.

## Or let GitHub build it
Your repo can call this repo's reusable workflow, which builds, tests, packages and attaches the zip to a **draft** release:

```
jobs:
  vst:
    uses: sd88me/mpc-vst-plugins/.github/workflows/vst-release.yml@<commit>
    permissions: { contents: write }
    with:
      tag: my-plugin-vst-v${{ inputs.version }}
      version: ${{ inputs.version }}
      tools_ref: <commit>
      vst_dir: vst
      build: vst/build.sh
      license: MIT
      about: One line about the plugin.
```

Pin the same commit in both places. The steps that need a device, CPU and the smoke test, stay with you: run them on the draft's own zip, then publish it, so the zip you tested is the zip people get. Publishing the draft creates the tag.

## Versions
Use `X.Y.Z`.

| Bump | When |
|---|---|
| Z | Fixes |
| Y | New parameters or pages |
| X | Parameter positions change (this breaks saved projects, so avoid it) |

Keep the plugin `uid` and the `.so` name fixed forever. Projects find the plugin by uid, and the installer replaces the entry with the same uid or file name.

## Say where you tested
Add a `tested.json` at the root of your repo's default branch, and the catalog shows it on the release:

```
[ { "version": "1.2.0", "device": "MPC Live II", "firmware": "3.6.0", "date": "2026-09-29" } ]
```

## List it in the catalog
The catalog is a list of plugins you point it at. It reads versions, links and checksums from your GitHub releases, so you never edit it for a new version.

### What can be listed
- **Open source**, or with public source and a license that limits use, such as non-commercial. Limited-use plugins carry a *Restricted use* badge.
- **A GitHub repo** with the source and a license file.
- **A release zip** built with this repo's `tools/release.py` (or its workflow) for 32-bit ARM MPC OS devices, with a version like `1.2.0`.
- **No closed binaries**, and nothing that ships Akai's own skins or files. Do not include sound content you have no right to share.

> Does your plugin need the user's own firmware to build, so that a built zip would contain someone else's code or ROMs? Then you can't publish a release. See [Plugins that can't ship a zip](#plugins-that-can-t-ship-a-zip) below.

### 1. Publish a release the catalog can read
Build your zip with a repo, a license and, if you like, a catalog id, then check it locally:

```
tools/release.py ... --repo you/your-plugin-repo --license MIT --id your-plugin -o dist
tools/catalog_check.py dist/Your-Plugin-1.0.0-mpc-armv7.zip --catalog
```

Attach the zip to a GitHub release on your repo. The [release workflow](workflow.html) page has the whole path.

### 2. Add one file
Open a pull request to [mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) adding `catalog/plugins/<id>.json`, where `<id>` is the id in your zip's manifest:

```
{ "id": "your-plugin", "name": "Your Plugin", "author": "Your name",
  "repo": "you/your-plugin-repo", "kind": "instrument", "license": "MIT",
  "summary": "One line that says what it sounds like or does.",
  "style": "sampler", "tags": ["rompler"] }
```

| Field | Notes |
|---|---|
| `id` | Lowercase letters, digits and hyphens. The file name must match. Never changes. |
| `kind` | `instrument` or `effect` |
| `license` | An SPDX id such as `MIT` or `GPL-3.0-only` |
| `source_available` | `true` if the license is not on the open-source list but the source is public. Shows the *Restricted use* badge. |
| `style`, `tags` | Optional lowercase words for the Style filter and search: `synth`, `sampler`, `drum-machine`, `reverb`, `delay`, `utility` |
| `screenshot` | Optional. An `https://` link to an image, shown at the top of your card; see [Screenshots](#screenshots). |
| `homepage` | Optional link |
| `asset_pattern` | Optional. Which release file to use. The default is `*-mpc-armv7.zip`. |

Do not put versions or checksums in this file. The catalog reads them from your release.

### Screenshots
Add a `screenshot` field to your entry and the card shows that image at the top, edge to edge. Clicking it opens the full image.
1. Commit a PNG or JPG of your plugin's MPC screen to your plugin's repo, for example `docs/screenshots/your-plugin.png`.
2. Put its public raw link in the entry: `"screenshot": "https://raw.githubusercontent.com/you/your-plugin-repo/<tag-or-commit>/docs/screenshots/your-plugin.png"`.
3. Open the pull request. The image appears after the next catalog build; it is not part of a release, so you do not need a new one.

- The link must start with `https://`. Anything else, including a relative path, is ignored and the card shows no image.
- Every card uses the same 2:1 frame. An image close to 2:1 is shown whole; other shapes are cropped at the edges, so keep the important part in the middle. A very wide banner is cropped hardest.
- The site links to your image instead of copying it. Use a tag or commit in the link, not a branch, so renaming or deleting the branch does not leave an empty box on your card.

### 3. What happens next
- The pull request runs a check on your entry, and a maintainer merges it.
- Every night, and whenever the catalog build is run, the catalog reads your releases, downloads each zip and checks it: file layout, checksums, ARM build, the highest glibc it needs, that the installer matches the standard one, and that the id, uid and repo agree with your entry.
- A release that passes appears on the site with its date, size and checksum. GitHub prereleases show up as beta.
- A release that fails is left out, your previous good version stays, and an issue is opened on the catalog repository explaining why.

### MPC OS 2.x and 3.x (optional)
Every release is labelled on the site as **MPC OS 2.x + 3.x** or **MPC OS 3.x only**. You do not declare it: the check works it out from your zip, and a 3.x-only plugin is listed like any other.
- **2.x + 3.x** needs both: the library needs glibc 2.32 or less (the default build does), and the skin only uses the file versions MPC OS 2.15.1's own skins use. A skin written with the current tools uses newer versions, so it is labelled 3.x only, and on MPC OS 2.x it shows no touchscreen page (the Q-Links still work).
- **To offer 2.x**, write the skin in the 2.x shape (the generator writes it when built with `SHADOW_SKIN_MPC_OS=2`; for a hand-written skin see [the table](https://github.com/sd88me/mpc-vst-plugins/blob/main/docs/OS2_SKINS.md)), run `python3 tools/skin_compat.py check "<skin>/Plugin Skins/TUI.json" "<skin>/Plugin Skins/Q-Links.json"` to see what still stops it, and publish a new release. The label updates on the next catalog build, and `tools/release.py` prints it when you build the zip.
- A library that needs glibc 2.33 to 2.36 is still listed, as 3.x only; more than 2.36 is rejected.
- Whether to support 2.x is your call: earlier releases keep their label, and people on MPC OS 2.x are told before they install a 3.x-only plugin.

### Plugins that can't ship a zip
Some plugins compile the user's own firmware into the plugin. Their build contains firmware-derived data, so it must never be published or shared. Those are listed as **Build it yourself**: the catalog shows what you need, the exact build command and a warning, and offers no download.

Your repo needs an open-source license and a root `LICENSE` file, a one-command build script and a `vX.Y.Z` git tag that contains it. Never put a `*-mpc-armv7.zip` on a GitHub release; the nightly build flags it. The pull request adds the same registry file with `"distribution": "build-yourself"` and three extra fields: `requires_user_files`, `build` and, for a build that installs several plugins, `components`. The [catalog README](https://github.com/sd88me/mpc-vst-plugins/blob/main/catalog/README.md#if-your-plugin-cant-publish-a-zip-build-yourself) has a complete example.

### Keeping it working
- Keep the `uid`, the `.so` name and the catalog id fixed across releases.
- Raise the major version only when parameter positions change, because that breaks saved projects.
- Add a `tested.json` to say which devices you tried. See the [release workflow](workflow.html).
- To pull a bad release, open a pull request adding `"<id>@<version>"` to `catalog/yanked.json`. It stays listed as yanked and is never offered as the latest.

### Rules of the road
This is community software that runs as root on people's devices. Say what the plugin does, keep the source public, and fix release problems quickly. Maintainers may remove a plugin that is unsafe or misleading.

### A desktop tool, not a plugin?
A tool that runs on the user's computer next to an MPC (not a plugin, nothing installed on the device by the catalog) is listed on the **Companion apps** tab: add an entry to `catalog/apps.json` with your repo and, per platform, a pattern for the release asset: the nightly build then fills in the links, version and checksums from your newest stable release. See `catalog/README.md`.

## After the release
The catalog finds new releases by itself every night. To list a plugin for the first time, see [List it in the catalog](#list-it-in-the-catalog) above. If a release fails the checks, it is left out, the previous version stays listed, and an issue is opened on the [catalog repository](https://github.com/sd88me/mpc-vst-plugins/issues) saying why.
