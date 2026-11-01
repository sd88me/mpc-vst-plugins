# MPC OS reference (third-party guide, condensed)

Condensed from the community **"MPC OS Hacking Guide"** (firmware 3.9.1.2, Gen1 RK3288, live checks on an MPC Live II;
author not named in the copy we were given; read 2026-10-13). **Not verified by us** unless a line points to NOTES. Its own
confidence labels are kept: **[P]** = it says it saw this on a device, **[S]** = read from the binaries only, **[U]** =
unresolved. Before you rely on a fact, check `docs/NOTES.md`. If you verify one, move it into NOTES with the date.

Gen1 only. Nothing here was checked on Gen2 (see `docs/GEN2.md`).

## Where it differs from what we know (read this first)

| Guide says | What we know |
|---|---|
| USB and SSD drives are exFAT **noexec** | It depends on the mount. A USB stick on our Force was not noexec (NOTES 2026-09-29); the Force SSD was (2026-10-03). Always read the mount line. |
| Manifest `arch` is `armv7` only and the installer refuses anything else | Out of date. We now ship aarch64 builds for Gen2 (`docs/GEN2.md`). |
| A drop-in written only to the `/etc` overlay may be missed at boot | Same cause, verified and fixed by us: `mpc-addins-reload.service` (NOTES 2026-10-11, `docs/ADDINS.md`). |
| Super Arp and Pixel Walkers **crash the internal USB audio device** when a control is pressed (USB disconnect, `usb_set_interface failed (-19)`, "Failed to find Linux audio device"; audio dead until reboot) [P] | Not reproduced by us. Both are in our catalog (saustin2010). Should be confirmed and reported to the author. |

## Platform

- Yocto scarthgap, vendor distro "az0x". Kernel `6.18.26-az01-...-rt4`, PREEMPT_RT, 1000 Hz, performance governor. [P]
- RK3288 (4x Cortex-A17), about 2 GB RAM, no swap. Mali-T760 on **Panfrost** (open driver). Panel `DSI-1`, 800x1280 portrait
  rotated to landscape. Touch: ILI2117, `/dev/input/event0`. Rockchip RGA at `/dev/video0`. [P]
- Kernel: modules load without a signature check. LoadPin and dm-verity are compiled in but **not enforcing** on 3.9.1
  (`/usr/lib/az0x/trusted-verity-digests` is empty; rootfs is plain ext4). A later firmware could turn this on. [P]
- No eBPF, kprobes, ftrace or uprobes. Perf events (root), usbmon, ptrace, `/dev/uinput` and `/dev/mem` are available. [P]
- ConfigFS USB gadget functions are built in: serial, mass storage, FunctionFS, UAC2, MIDI, HID. [P]
- Userland: armhf (NEON, VFPv4), glibc 2.39, GCC 13.4, BusyBox `ash`. Present: `ssh/sshd/scp`, `systemctl`, `journalctl`,
  `busctl`, `dbus-send`, `losetup`, `chroot`, `unzip`, `zstd`, `openssl`, `amidi`, `insmod`. Missing: `bash`, `python3`,
  `curl` CLI (libcurl is there), `gdb`, `strace`, `aplay`/`amixer`, `evtest`. Static ARM debug tools: TheKikGen's repos. [S]

## Boot, partitions and persistence

- U-Boot 2016.05 (inMusic fork). The boot script loads `zImage` and the DTB with **no signature check**. Serial console on
  `ttyS2` at 115200. A fastboot recovery path exists. [S] (Our NOTES: no `inmusic-unlock-magic` string in the boot
  partitions of the devices we read.)
- Chain: `acvs.service` -> `az01-launch-MPC` -> `systemd-inhibit ... /usr/bin/MPC`. No `User=`, so **MPC runs as root**.
  Journal identifier `az01-launch-MPC`; error lines start with `****`. [P]

| Mount | Device | Mode |
|---|---|---|
| `/` | `mmcblk0p6` | ext4 read-only |
| `/data` (also `/media/az01-internal`) | `mmcblk0p7` | ext4 rw, all writable state |
| `/etc`, `/var` | overlay, upper in `/data/system/{etc,var}/overlay` | rw |
| `/sdcard` | `mmcblk1p1` | ext4 rw, exec |

- **`/etc/az01/overlayfs.conf` deletes `passwd`, `shadow`, `group`, `gshadow` and the whole `ssh/` directory from the
  `/etc` upper layer at every boot.** Account and SSH key changes made at runtime are lost on reboot. Persistent SSH
  has to be in the read-only root, which is why the SSH mod is a rebuilt image. [P]
- Stock ships OpenSSH with `sshd.service` **disabled**, `PermitRootLogin prohibit-password`, and root locked (`*`). [S]
- `debug-shell.service` (a root shell on a spare VT) is in the image but not enabled. [S]

### Update images

- `.img` = magic `AZ01`, snapshot name, compatible product codes, `PARTL`, and an xz-compressed ext4 rootfs with a SHA-1.
  TheKikGen's `mpcimg2` unpacks and repacks it. A replacement rootfs must be exactly the original size. [S]
- The updater (`ramfs-update.squashfs`) can check an RSA/SHA-256 "v3" signature against `/usr/lib/az0x/pubkeys/akai-1.pub`,
  but **an unsigned, SHA-1-only repacked image still installs from the normal update menu on 3.9.1**. [P] Akai could
  remove this in any update.
- Product codes: ACVB Live II, ACV8 Live, ACV5 X, ACV5S X SE, ACVA One, ACVA2 One+, ACVM Key 61, ACVR Key 37. (Force is not
  in this list; it has its own code.)

## The MPC application

- `/usr/bin/MPC`, 112 MB, stripped but **RTTI is kept**. JUCE 5.4.4. React-JUCE + Hermes for part of the UI
  (`binary.hbc`). libpd (Pure Data 0.50.2, block 64; how it finds patches is [U]). Lua 5.4.7 and a JavaScript registrar.
  Crashpad. [S]
- Draws on the CPU, no EGL/GLES; holds `/dev/dri/card0`, `/dev/video0`, `/dev/tty0`. The GPU is idle. [P]
- Command-line flags: `--script`, `--scriptLibs`, `--scriptOutputPath`, `--remotescreen`, `--touchtest`, `--painttest`. A
  `ScriptableTrackPool` registers 73 track operations (name, volume, pan, mute, solo, arm, routing). No outside way in
  found. [S]/[U]
- Plugin formats: VST2 proven. LADSPA loader present (`LADSPA_PATH`, `ladspa_descriptor`), VST3 and SOUL strings present:
  all [U]. `VST_PATH=/usr/lib/vst;/usr/local/lib/vst;~/.vst` is compiled in [S] (we register by `MPC.settings`, not
  by path).

## Audio

- Internal interface is USB `09e8:2047`, card ID `Audio`. Playback 6 ch, capture 2 ch, S32_LE, 44.1/48/88.2/96 kHz. MPC
  runs 44100 Hz, period 128, buffer 384. No hardware mixer. [P]
- MPC opens `hw:` directly and the PCM is exclusive. Use `hw:CARD=Audio,DEV=0`, never `hw:0,0` (card numbers move). [P]
- The engine can't run headless or next to another compositor that owns the display (stopping MPC stops audio). [P]

## Skins and pages

- Stock pages: `/usr/share/Akai/SME0/Resources/Pages`. Handlers are a fixed set (`Q-Link`, `Toggle Switch`,
  `Show Overlay`), not a script hook. [S]
- **Loader order for a page file:** the hardware layout suffix first (`4by4`, `1by4`, `8by1`, `Single`), then the bare
  name, each `.json`. Some pages fall back to the legacy `/usr/share/Akai/SME0/PluginLayouts/Layout-*.xml`. Whether a user
  directory overrides stock pages, and whether edits hot-reload: [U]. This may matter for per-device skins and for the
  MPC OS 2.x skin work (`docs/OS2_SKINS.md`).

## Data formats

- Projects, programs and tracks are gzip of five header lines (`ACVS`, producer version, type tag such as
  `SerialisableProjectData`, `json`, `Linux`) then a cereal JSON body. [S]
- `.xpj` project (`data.version` 28, 960 PPQN), `.xpm` program, `.xfx/.xid/.xtd/.xty` insert/instrument/track data,
  `.xpl` plugin preset (XML `pluginstate`, `state` is a non-standard base64), `.xmm` MIDI-learn map (XML),
  `Expansion.xml`, `.articulation` and `.progression` (plain JSON). [S]
- Don't build a project from scratch: about 13 KB of nested state, track types 0-6 serialise differently, and
  `sampleFile` is relative to the sibling `<project>_[ProjectData]/` folder. Change a known-good version-28 template and
  load it on the device to check. [S]

## Network listeners

| Port | Owner | State |
|---|---|---|
| TCP 80 | `az0x-webserver` | object API (`/api/v1/object-meta`, `object-properties`, `object-method`, `subtree`, `/api/auth`, `/files`). Pairing-gated (`401 {"pairState":"notPaired"}`; notPaired -> pending with `pairPin` -> paired). MPC itself shows no sign of registering objects with it. [U] |
| TCP/UDP 51000, mDNS | `DeviceControlServer.bin` | "Network MIDI AZ01 Server", protocol undecoded [U] |
| UDP 127.0.0.1:8080 | `az01-script-runner` | local command dispatcher, format unknown [U] |
| TCP 41401 | MPC | unknown |
| TCP 1979 | MPC (SMEX default) | not seen listening |

- **SMEX** (MPC's remote screen, touch, control and file transfer protocol): envelope = 4-byte LE magic `2c 9e b4 f2`,
  4-byte LE length, payload, no checksum. One-byte routes: 0 control, 1 file transfer, 2 image (likely), 3 touch, 4 ping.
  Control strings include `smex.restart.standalone`, `smex.brightness.set`; file transfer uses `driveInfoList`,
  `fileInfoList`, `transferFile`. Handshake, image encoding and touch fields: [U]. [S]

## Routes to install plugins without SSH

What any route needs, from our own work: copy the plugin folder to an exec mount, then add a `<PLUGIN>` line to
`MPC.settings` (`pluginList-arm`, or `pluginList-arm-64bit` on Gen2) while MPC is stopped. The second step needs root.
The guide does **not** describe a stock no-SSH route. What it adds:

1. **Stock autorun stick** (not in the guide; reported by a community developer whose USB plugin manager uses it, tested by them on a Live II, 3.9.1; not run by us; check algorithm read offline 2026-10-13, see NOTES.md). `autorun/autorun.json` plus `autorun/autorun.check` (a firmware-specific hash) on the stick; the firmware asks, then runs `open.sh` as root.. Runs a
   script as root after an on-screen prompt. Still the only known no-hack route. The guide's `az01-script-runner`
   (local UDP dispatcher, enabled on stock) is a candidate for the part of the firmware that runs it: unchecked.
2. **A temporary SSH session from an autorun stick** (idea, not tried): `sshd` is installed but disabled, and
   `overlayfs.conf` wipes `/etc/ssh` and `shadow` at boot, so changes can't persist. A root script could run `sshd`
   for this boot only, with a key and config under `/run`. Our desktop app and `install.sh` would then work on stock
   firmware unchanged, until the next reboot.
3. **Unsigned update image** [P]: proven, but it is the firmware mod we want to avoid.
4. **Serial console** (`ttyS2`, 115200) [S]: needs the case opened and a UART adapter.
5. **SMEX `transferFile`** and **`az0x-webserver` `/files`** [U]: could copy files without SSH, but they would not register
   a plugin, and neither is decoded.

## Leads for our work

- `/dev/uinput` is present (MPC's acceptance untested): a possible way to inject button presses without hooking
  `snd_rawmidi_open`, if MPC reads any buttons from evdev.
- `perf` events work for root, so `docs/BENCH.md` could profile on the device with a static `perf`.
- The page-file suffix order (`4by4`, `1by4`, `8by1`, `Single`) is a lead for per-hardware plugin skins.
- Project format notes are useful for any tool that writes `.xpj`/`.xpm` (e.g. clip import).

## References

- TheKikGen/MPC-LiveXplore (image tools `mpcimg`/`mpcimg2`, SSH images, bootstrap and hacking libs)
- jacob-sabella/mpc-addin-remote (screen + MCP addin)
- niklasnisbeth.gitlab.io/mpc-internals
