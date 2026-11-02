---
title: Set up and build
nav: Build
order: 20
summary: Get your computer ready, build a plugin that has no download, or turn a sound engine into a native MPC OS plugin.
---

This page is for **building**: a plugin marked "Build it yourself" in the catalog, or a plugin of your own. If you only want to put a plugin from the catalog on your device, you do not need any of it: see [Install](install.html).

You do not need to be a programmer. The commands are examples: for anything you install, the linked official pages have the current steps. Building never happens on the device; the device only receives the finished plugin.

## What you need to build
- **A Linux-style shell:** Terminal on macOS, Ubuntu on Linux, or Ubuntu inside WSL on Windows.
- **Git** and **Python 3.**
- **Docker.** The builds run inside it, so nothing else has to be installed by hand.
- Several GB of free disk space (Docker downloads build images the first time) and a few minutes.
- To put the result on a device: the [installer app](install.html) and root SSH access to your device.

## Get your computer ready
A check follows each step.

### 1. Open a terminal
- **macOS:** open the Terminal app.
- **Ubuntu or other Linux:** press Ctrl+Alt+T, or open "Terminal".
- **Windows:** the build scripts are shell scripts, so use Ubuntu inside WSL 2. In PowerShell (as administrator) run `wsl --install`, restart, then open "Ubuntu" from the Start menu and finish its first-run setup. See Microsoft's [WSL install guide](https://learn.microsoft.com/windows/wsl/install). From here on, run every command in the Ubuntu window.

### 2. Install git and Python 3
- **Ubuntu and WSL:** `sudo apt update && sudo apt install git python3`
- **macOS:** run `xcode-select --install` once; it installs git and Python 3.

Check: `git --version` and `python3 --version` each print a version number.

### 3. Install Docker
- **macOS and Windows:** install [Docker Desktop](https://docs.docker.com/desktop/) and start it. On Windows, open its settings and turn on WSL integration for Ubuntu.
- **Ubuntu:** follow Docker's [Ubuntu install guide](https://docs.docker.com/engine/install/ubuntu/). Then let your user run Docker without `sudo`: `sudo usermod -aG docker $USER`, and log out and back in.

Check: `docker run --rm hello-world` prints a short welcome message. If it does, Docker works.

### 4. Keep your files in the right place
On Windows with WSL, work inside your Ubuntu home folder (`cd ~`), not under `/mnt/c/`. Builds are much faster there and file permissions behave.

## Plugins you build yourself
A plugin with the **Build it yourself** badge in the catalog has no download: its build embeds your own firmware, so nobody can publish the result. You build it once, on **your computer**, then install the result on your device. The device itself does not build anything.

**The process at a glance:**

| | Step | Where |
|---|---|---|
| 1 | Get your own firmware or OS file | your computer |
| 2 | Set up git, Python and Docker (once) | your computer |
| 3 | Clone the plugin's source | your computer |
| 4 | Run its build command | your computer (5 to 30 minutes) |
| 5 | Install the zip it made | your device, over your network |

In detail:

1. **Get your own files.** The plugin's card lists them under "You need" (for example an Elektron OS `.syx` file). Download them from the manufacturer, or export them from your own hardware, and keep them in a folder whose path has no spaces. Use the exact version the card names: the build checks it.
2. **Set up your computer.** You need Docker, git and Python 3, and a Linux-style shell: macOS, Ubuntu, or Ubuntu in WSL on Windows. "Get your computer ready" above walks through it, with a check after each step. This is a one-time job; every later build reuses it.
3. **Get the plugin's source on your computer.** This is the `git clone` step in the plugin's README: run `git clone --recursive https://github.com/<owner>/<plugin-repo>.git`, then `cd <plugin-repo>`. The card's Source link shows the repo. `--recursive` matters: it fetches the parts the build needs.
4. **Run the build command** from the plugin's card, with the path to your own file in quotes. It builds inside Docker and takes a few minutes (some take longer; the first run also downloads what it needs). Leave the computer awake and watch the output. It stops at the first error and names the step, and it refuses to finish if its self-check fails, rather than giving you a build that is not verified. After fixing a problem, run the same command again: finished work is reused.
5. **Install it.** The build leaves a zip in the plugin's `dist/` folder. Start the [installer app](install.html), connect, and drop that zip into the box in step 2 of the page, then press Install. (If the build command has a `-d <device-ip>` option, adding it installs straight onto the device instead.) Save your project first: MPC restarts.
6. **Keep the result to yourself.** It contains data derived from your firmware. Install it on your own devices only and never share or upload it.

To update later, pull the latest source (`git pull --recurse-submodules`) and run the build command again.

The exact command, and any extra tools it needs, are on the plugin's card and in its README. Step-by-step versions for the two Elektron ports: [Monomodule](https://github.com/sd88me/mpc-vst-monomodule#install) and [Machinemodule](https://github.com/sd88me/mpc-vst-machinedrum#building).

## Build your own plugin from an engine
An MPC OS plugin is a small Linux library (`.so`) for the device's ARM processor, plus a **skin**: a folder that describes the plugin's page on the MPC screen. This repo's tools build both from one small description file, and they test the result on your PC before it goes anywhere near a device.

What you need on top of the tools above:
- A checkout of [mpc-vst-plugins](https://github.com/open-mpc/mpc-vst-plugins). A plugin lives in its own repo next to it, and points at it with the `MPC_VST` variable.
- An engine to wrap: a synth or effect core in C or C++, or an engine from Schwung (it plugs in through an adapter).
- A device to try it on. Nothing here needs one until the very last step.

### 1. Pick your kind of plugin
- **A block-rendering engine** (a synth or effect core): the common case. You provide `mpc_engine()` and the tools do the rest.
- **An engine with extra glue** (network keys, dynamic lists): write a plugin-specific wrapper. Crate Digger is the example.
- **A MIDI generator** (sequencer, arpeggiator): MPC ignores a plugin's MIDI output, so it opens its own MIDI port.
- **An app** (network, files, helper programs): allowed. Keep the audio thread from ever waiting.

The [porting checklist](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/PORTING.md) covers each case in detail.

### 2. Describe the plugin
Put a `vst.json` next to the engine:

```
{
  "name": "My Synth", "vendor": "me", "uid": "MySy", "version": 1000,
  "so": "my_synth.so",
  "params": "params.json",
  "layout": "layout.conf",
  "build": {"root": "..", "sources": ["src/engine.c"], "cflags": ["-Isrc"], "libs": ["-lm"]}
}
```

`params.json` lists the parameters in the order MPC will number them. **The order is a promise**: saved projects store values by position, so once a plugin ships you only append. `uid` and `so` also never change between versions.

The engine's side of the contract is small: create, destroy, MIDI in, set and get a parameter by key, and render 128 stereo frames at 44.1 kHz. See `wrapper/engine.h`.

### 3. Build it
```
MPC_VST=/path/to/mpc-vst-plugins
"$MPC_VST/tools/build_port.sh" vst/vst.json
```

This generates the parameter table, the skin, the plugin-list entry and the ARM `.so`, all in `build/` next to `vst.json`. Without a `layout` it makes an automatic first page, which is a good starting point.

Two rules that save a crash: vendor any third-party engine source into your repo (do not fetch it at build time), and never hardcode `/sdcard/...` in the engine. Set `"defines": {"MODULE_SUBDIR": "\"engine\""}` and the plugin finds its own data folder next to the `.so`, wherever it was installed.

### 4. Design the page
The page is a description that MPC draws: knobs, faders, switches, buttons, option lists, pop-ups, live text and your own artwork. Edit it in the **Skin Studio**, a page editor in your browser (double-click `SkinStudio.command`, `SkinStudio.bat` or `SkinStudio.sh` in the repo), then preview every page as an image:

```
"$MPC_VST/tools/studio.py" preview "build/skin/<vendor> - VST - <Name>/Plugin Skins" -o page_%d.png
```

Live text can use two fonts, Titillium Web and Roboto. Anything else has to be baked into the artwork. The [Skin Studio guide](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/SKIN_STUDIO.md) has the details.

### 5. Test on your PC
```
"$MPC_VST/tools/test_port.sh" vst/vst.json
```

This builds the wrapper and your engine for your PC under a memory checker, and plays it: two instances, every parameter, options, notes into audio, and saving and restoring state. It must print `PASSED`.

### 6. Try it on a device
Only now does a device come in. Follow the [release workflow](workflow.html): measure CPU, install with the real installer, and test. The reference ports, Maze Voice, JV-880 and Crate Digger, are good to copy from.

## When something fails
| You see | Usually means |
|---|---|
| `docker: permission denied` | Your user is not in the `docker` group yet. Run the `usermod` command above, then log out and back in. |
| `Cannot connect to the Docker daemon` | Docker is not running. Start Docker Desktop, or on Linux `sudo systemctl start docker`. |
| `ssh: connect to host ... timed out`, or `Permission denied` from `ssh` | See "Check that you can reach your device" on the [Install](install.html) page. |
| A build stops with an error about its self-check | Your OS file or your tools differ from what the plugin was built against, and the build refuses to make an unverified plugin. Check the file name and version on the plugin's card. |

## Where to read more
- [Porting checklist](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/PORTING.md)
- [What has been verified on real hardware](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/NOTES.md)
- [Skin Studio](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/SKIN_STUDIO.md)
- [CPU check](https://github.com/open-mpc/mpc-vst-plugins/blob/main/docs/BENCH.md)
