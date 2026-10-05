# Firmware Builder Plan (handoff)

Status as of 2026-10-06. Read this first before continuing the firmware-builder work.

## Goal

Add a firmware builder to the MPC plugin installer app (`tools/desktop`, Go). The user gives it
Akai's **official** firmware file and picks options. The app patches it and returns an `-update.img` that the user
installs the normal way (USB stick → Preferences → Update). We never host firmware.

Options offered to the user:

- **Plugin support**: a boot-time service that registers plugins in `MPC.settings`. Users install a plugin by
  putting its folder in `Synths` on a card or drive (by hand, or the app writes it there), then restarting.
- **Plugin support + SSH**: also enables root SSH with a **user-chosen password**, **no password**, or an optional
  SSH key. The installer app then works over Wi-Fi as it does today.

Decision (2026-10-04): password login, MockbaMod-style, is the default for SSH. Keys stay available but optional.
The user judged keys too limiting for a low-risk device.

## Why

- MPC only loads plugins listed in `pluginList-arm` in
  `/media/az01-internal/Settings/MPC/MPC.settings`. That partition isn't reachable without root.
- Alternatives were checked and ruled out:
  - MPC has JUCE's plugin scanner built in, but its search paths are read-only and there's no rescan UI on the
    standalone device. Akai's AIR plugins are built into the MPC binary.
  - There's no settings import from USB. "Restore Settings" only resets to factory defaults.
  - Copying files from a computer only reaches `/sdcard`, not `Settings`.
  - Akai's `az0x-webserver` (private `/api/v1/object-*` API, `/software-update`, a factory "test app" upload) uses
    PIN pairing. Using it would mean reverse-engineering a private API. It's not a path for users, but it might be
    worth researching as a way to flash over Wi-Fi.
- Plugins vanishing after a restart (see [docs/NOTES.md](NOTES.md), 2026-09-30) are likely caused by
  editing `MPC.settings` while MPC runs, or by list-rebuilding tools. A boot service that runs **before**
  `acvs.service` and **merges** entries rather than rebuilding the list avoids both problems.

## What exists now

Branch `force-fw-builder`, commit `daa0157` (not merged to `main`, not pushed):

- `tools/firmware/build-force-fw.sh` takes Akai's Updater `.exe` or `update.img` and edits the ext4 rootfs with debugfs,
  running as a normal user with no loop mounts. It:
  - sets root login with `-p PASS` (SHA-512 in `/etc/shadow`), `-n` (no password) and/or `-k key.pub`
  - for password login, edits Akai's own `/etc/ssh/sshd_config.d/10-az0x.conf` (`PermitRootLogin yes`,
    `PasswordAuthentication yes`, plus `PermitEmptyPasswords yes` with `-n`); `sshd_config` stays factory
  - enables sshd at boot (`multi-user.target.wants/sshd.service` symlink)
  - removes Akai's **shared** `ssh_host_ed25519_key`, so each device generates its own on first boot
  - drops Akai's `cert-authority` line from `authorized_keys` unless `-a` is given
  - with `-s`, adds the MockbaMod-compatible SD-card hook (`tools/firmware/fw/az01-launch-MPC`). This is Akai's 3.9.1
    launcher plus a block that execs `/media/662522/boot.sh`, keeping Akai's `GLIBC_TUNABLES` hugetlb setting.
  - rebuilds the AZ01 container: Akai's header, recomputed SHA-1 and size, 8-byte padding plus Akai's EOF record.
    xz uses `-6 --check=crc32`.
- Verified offline only: a full rootfs diff against factory, inode owner and mode, the password hash, and
  effective settings via OpenSSH `sshd -T` (Alpine's sshd, not the device's). **Not flashed yet.**

## Rollout

1. **Test flash on the Force (3.9.1).** Build with a real password, flash, then confirm it boots, MPC runs and SSH
   works, and that the host key is unique. ← *next*
   - On this Force, MockbaMod's `shadow` and `sshd_config` copies sit in the persistent `/etc` overlay
     (`/media/az01-internal/system/etc/overlay/`) and override the image. MockbaMod's `install.sh` restores them
     if `/etc/mockba_mod_installed` is missing. Clean up by deleting those overlay files and editing `install.sh`
     on the card (a small cleanup script still needs writing).
2. **Boot-time plugin service.**
   - It's a systemd unit ordered `Before=acvs.service`.
   - It scans `/sdcard/Synths` and `/media/*/Synths` for plugin folders with `plugin-meta.xml`.
   - It backs up `MPC.settings` and merges entries into `pluginList-arm`, validating the XML before writing.
   - It removes only entries it added (use a marker) whose folder is gone. It keeps entries for removable media
     that's absent at boot, so plugins don't disappear when a card isn't inserted.
   - Reuse the merge logic from [tools/mpc-store.sh](../tools/mpc-store.sh) (tested under BusyBox). Add the service
     to `build-force-fw.sh` as the default and make SSH optional.
3. **Builder in the installer app (Force 3.9.1 first).**
   - Port to Go using CE's approach: per-firmware **byte-span recipes** generated from `build-force-fw.sh`, a
     pinned SHA-256 of Akai's file, and a placeholder for the password hash or key.
   - The app decompresses, applies the spans, inserts the hash or key, recompresses and rewrites the header.
     That avoids needing ext4 code on Windows or Mac.
   - Reuse CE's MIT-licensed Go (`builder/image.go`, `patch.go`; `github.com/ulikunitz/xz`).
   - Add a plugin-support install target that writes plugin folders to a card or drive mounted on the computer.
4. **Small beta** with Force owners first.
5. **Gen1 MPCs** (Live II, One, X) once someone tests them. Gen1 now uses AZ01 too, and needs its own recipe.
6. **Maybe a browser version** (Go → WASM) on the catalog site.

## Open questions and risks

- **Akai could enforce signed images.** `libaz01-prog` contains `az01_verify_image`, `az01_verify_signature` and
  an onboard key (`/usr/lib/az0x/pubkeys/akai-1.pub`). Current images are unsigned and accepted. A future
  official firmware could refuse modified images, so keep a list of known-working versions.
- Gen2 devices are unsupported. **Analysed 2026-10-04 (`Docs/MPC-3.9.1-Gen2-update.img`) and the Gen1
  repack method does NOT transfer — Gen2 is cryptographically signed.** Details:
  - Different container: magic `AZ0x` (not `AZ01`), with a partition table of 7 entries: 4 A/B `BOOT`
    slots, `PARR` (recovery rootfs), `PART` (boot), and the 331 MB main `PART` rootfs (idx 79). Each
    partition payload is xz.
  - Partition digests are plain **SHA-256** and recompute cleanly (the main rootfs digest matched), so
    editing a rootfs and fixing its digest is still easy — but that is no longer sufficient:
  - The header carries an `akai-1` **key name** and an **86-byte signature blob** immediately after the
    partition table (offset 0x278: u64 length 0x56 then the signature). Neither exists on Gen1/Force,
    whose header is a plain checksum with no key reference. This signature covers the partition table
    (which contains every partition's SHA-256), so altering any rootfs invalidates it.
  - The `BOOT` payload is a **U-Boot FIT image** (`d00dfeed`) with RSA / SHA-256 signatures, a
    `key-name-hint`, and an embedded PKCS#7/DER blob — i.e. standard U-Boot **verified boot** against a
    key fused into the SoC/baked into U-Boot.
  - Implication: a modified Gen2 image fails signature verification (at the updater via `akai-1`, and/or
    at the verified-boot chain). Producing a valid image needs Akai's **private** signing key, which we
    do not have. This matches `libaz01-prog`'s `az01_verify_signature` / `az01_image_set_onboard_key_lookup`
    and `/usr/lib/az0x/pubkeys/akai-1.pub`, and why both CE and HAKAI refuse Gen2.
  - Caveat: this is static analysis of the image, not a confirmed rejection from running the updater, but
    the signed FIT boot chain alone is normally a hard blocker for the *updater-image* route.
  - **Fastboot-unlock lead (2026-10-05, github.com/Lewinator56/mpc-vst-helm — a Helm VST port using our
    catalog).** There is a second way in that sidesteps the signed-image wall. Lewinator's README documents:
    reboot the MPC into fastboot/bootloader mode, run `fastboot oem inmusic-unlock-magic-7de5fbc22b8c524e`
    to UNLOCK THE BOOTLOADER, then `fastboot flash rootfs <modified-rootfs>` and `fastboot reboot`. An
    unlocked bootloader disables AVB/verified-boot, so the signature chain above is moot *if the OEM unlock
    command works*. The rootfs content edits are identical to ours (10-az0x.conf PermitRootLogin/
    PasswordAuthentication yes + root pw in /etc/shadow + sshd.service symlink). Tested by him on MPC Key 37
    Gen1; he flags the open risk that Akai may have disabled/locked unlock on Gen2.
  - Confirmed from our stock Gen2 image: its bootloader IS fastboot-capable with `oem` handlers incl.
    OTP/eFuse ops (`oem OTP has already been write!`). Could NOT confirm the specific unlock token is present
    (U-Boot is LZMA/raw inside the FIT, not plaintext), so Gen2 unlock is plausible-unverified.
  - **Cheapest decisive Gen2 test:** on a physical Gen2 unit, enter fastboot and run
    `fastboot oem inmusic-unlock-magic-7de5fbc22b8c524e`. OK = unlockable (our rootfs edits flashed via
    `fastboot flash rootfs` would give SSH, no signing key needed); fail = OTP likely locks unlock, back to
    the hard SoC/secure-boot case.
  - **Discord, 2026-10-06 (Lewinator56 and fuzboxz, mpc-vst-helm/catalog server).** fuzboxz (has the Gen2
    firmware running in QEMU, no hardware yet) reports the unlock magic string is **not present/available in
    Gen2 fastboot**, and separately that Gen2's firmware is signature-patched and that the known SSH route
    there is a *different* vulnerability, not the fastboot-unlock method. Both points are single-source and
    hardware-unconfirmed (QEMU fastboot may not reflect the real `oem` handler), but they lower confidence in
    the fastboot-unlock lead for Gen2 specifically. Lewinator56 also confirmed Windows fastboot binaries don't
    detect the MPC at all (matches our usbipd-win/WSL caveat) and that Gen2 is an RK3588 (vs. RK3288 on Gen1).
  - **Origin of the unlock command (github.com/RedHate/Unbricking-inMusic-Products).** This repo documents the
    same `fastboot oem inmusic-unlock-magic-7de5fbc22b8c524e` command, with no stated origin, for MPC ONE,
    Gen1 MPC, Force and Numark Mixstream Pro (ENGINE OS). It does **not** cover Gen2 or RK3588, and never
    mentions signing or verified boot. Steps: unpack with TheKikGen's `mpcimg`, enter fastboot via a
    device-specific button combo, unlock, `fastboot flash rootfs <img>` (~81s), reboot. Partition layout for
    Gen1/Force is 8 entries (`uboot-spl`, `env`, `uboot`, `splash`, `recoverysplash`, `rootfs`, `content`,
    `data`) — different from Gen2's 7-entry A/B `BOOT`+`PARR`/`PART` layout we found, consistent with Gen2's
    boot flow being redesigned, not just resigned. **Useful as a Force/Gen1 unbrick recovery procedure** —
    worth adding to our rollout as a safety net before step 1's test flash, even though it doesn't extend to
    Gen2.
  - **Confirmed 2026-10-06: Gen2 plugins need a separate aarch64 build, independent of the SSH question.**
    Extracted and inspected `/usr/bin/MPC` from `Docs/MPC-3.9.1-Gen2-update.img`'s main rootfs partition
    (idx 79, decompresses cleanly to a 687 MB ext4 image): it is **ELF64 aarch64** (PIE, dynamically linked,
    interpreter `/usr/lib/ld-linux-aarch64.so.1`), not armhf. The rootfs has no 32-bit libraries anywhere —
    a clean 64-bit-only userland, no multilib. A 64-bit process cannot `dlopen()` a 32-bit `.so` (no compat
    shim exists at the dynamic-linker level for this; this is why tools like JBridge do out-of-process
    bridging). So even once Gen2 SSH access is solved, our existing armhf plugin catalog won't load there —
    each plugin needs its own aarch64 build and test pass. This matches fuzboxz's original claim in Discord
    and corrects Lewinator56's initial "ARM64 is backwards compatible with ARMHF" response (true for the
    kernel/syscall layer, not for userspace shared-object loading). **Conclusion: Gen2 plugin support is a
    separate project gated on both (a) a working SSH/root method and (b) an aarch64 build pipeline — not
    just a firmware unlock problem.**
  - Fastboot route is MORE work and higher risk for end users than our updater image (needs a PC with
    fastboot; on Windows usbipd-win + WSL USB passthrough; a bootloader unlock that typically factory-resets
    the device and leaves a persistent "unlocked" state). So it is NOT a replacement for the Gen1/Force
    updater-image flow — reserve it for Gen2, only if unlock works. For a fastboot path, `build-force-fw.sh`
    would just need an optional mode that emits the bare ext4 rootfs (the content is already correct);
    proposed flag `-R`/`--raw-rootfs`, not yet implemented.
- Every official Akai update removes the mod, so users must re-run the builder. The installer should detect this.
- The no-password option gives root to anyone on the network, and the app must say so.
- Distribution: never host images, only recipes, and tell users not to share their built images. Document going
  back to stock with Akai's updater.

## Research findings (reference)

| Image | Format | Changes vs Akai | Notes |
|---|---|---|---|
| Akai Force 3.9.1 | AZ01, multi-block xz, CRC32 | — | Build `SNAPSHOT-20260709105005`. The Updater `.exe` is a 7-Zip SFX containing `update.img`. |
| MockbaMod Force 3.9.1 (`Docs/Force-3.9.1-m-update.img`) | AZ01, single-block CRC32 (TheKikGen `mpcimg2`) | 3 files: `az01-launch-MPC` (SD hook to `boot.sh`), `shadow` (root/`force`), old 2018 `sshd_config` (drops `Include`) | Drops Akai's `GLIBC_TUNABLES` hugetlb. Typo `messagebuis` in `shadow`. Dead-code typo `systemd-irun nhibit`. |
| HAKAI MPC Gen1 3.9.1 (`Docs/MPC-3.9.1-Gen1-update.img`) | Old FIT format, CRC64 (TheKikGen Python `mpcimg`, timestamp `0x5dee18e1`) | `MPC` 5 bytes (`cmp #8` → `#32`, raising the 8-track cap to 32) then UPX-packed; LD_PRELOAD `hakai_driver.so` (Launchpad via rawmidi hooks), `mpc_cursor.so`, `customBufferSizeMPC.so` (Amit Talwar) | Root with **empty** password; `/etc/shadow` mode 0755. |
| MPC 3 Community Edition (github.com/zsoltf/mpc-3-community-edition, mpc3ce.com) | AZ01, browser builder (Go → WASM), byte-span recipes over the official image | `MPC` version label only; LD_PRELOAD observer started by a systemd unit that stops `acvs` and relaunches MPC; key-only SSH, masked by default | Live II 3.9.1 only. MIT licence. The best model to follow. |
| TheKikGen MPC-LiveXplore | — | Origin of the method: unsigned images, `mpcimg`/`mpcimg2`, the SSH template, LD_PRELOAD rawmidi hijack (IamForce, anyctrl) | |

- **Akai's shared host key.** Akai ships one shared SSH host private key (`az0x-device`, SHA256
  `HjNpS/GOYOQdh+0aFjkqArbsSpq/3azmfAone5VATXw`), identical in the Force and Gen1 MPC 3.9.1 images.
- **Akai's own SSH setup.** Akai's sshd allows key-only root login (`10-az0x.conf`), and `/root/.ssh/authorized_keys`
  holds an Akai `cert-authority` key. sshd is installed but not enabled. The firewall rule files are empty.
- **Official Gen1 image.** It's on Akai's CDN at
  `https://cdn.inmusicbrands.com/Software/MPC/MVSU391APC/MPC-3.9.1-Gen1-update.img`.

## Scratch files

`~/fwcmp` (about 6 GB, safe to delete; everything can be regenerated):

- `F` / `M`: Force factory and MockbaMod rootfs
- `A` / `H`: MPC official and HAKAI rootfs
- `unp/`: unpacked HAKAI `MPC`
- `kik/`: TheKikGen repo
- `ce/`: CE repo
- `work/update.img`: Akai's Force image
- `out/`: throwaway test images (`t-pass-sd.img` has the password `test pass!`); don't flash these
