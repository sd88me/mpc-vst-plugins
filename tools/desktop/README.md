# mpc-installer: install MPC OS plugins from your computer

A small local app for people who would rather not type SSH commands. It starts a web page **on your own computer**, opens it in your
browser, and from there you connect to your device, tick plugins from the catalog and/or drop release zips (including the ones you
built yourself, like Monomodule and Machinedrum), and press Install. It is one file (about 8 MB) with nothing to set up, for Windows,
macOS and Linux.

It uses the same release zips and the same `install.sh` as every other route (`docs/RELEASING.md`), so there is still one install
path. What it adds: a friendly page, one copy of each zip over SSH (as a tar stream, so executable bits and symlinks survive), and
one MPC stop and start around the whole batch when the installers allow it.

The same mode opens with an **easy stick** (`tools/desktop/easystick.go`, added 2026-10-27, offline-tested only): it downloads
the community "Plugin Manager USB for OPEN MPC" release by Twisted Cable (MIT; <https://github.com/Eurikon/plugin-manager-usb-for-open-mpc>),
pinned to one reviewed version and checked against a fixed SHA-256, never "latest" (the stick runs as root). The pin is read
at run time from `tools/desktop/easystick-pin.json` on `main` (version, URL, sha256; the URL must be under that project's
releases), so adopting a tested release is a one-file PR with no installer release; the `easyStickVersion`/`easyStickSHA256`
constants are the offline fallback, refreshed at the next installer release, and unpacks it onto an empty drive. It needs no firmware: the bundle carries the
OS 3.9.1 autorun route and the OS 3.10 controller helper, and picks the Gen1 or Gen2 runtime on the device.

A collapsed **Beta: one-prompt G2 install stick** section (`tools/desktop/g2stick.go`, added 2026-10-29, offline-tested only) asks
the MPC OS first (the stock USB prompt exists only up to 3.9.1; 3.10 and "not sure" point back to the easy stick) and writes the
"Level 1" bundle from `tools/usb_g2/build_stick.py`: our own autorun script plus both G2 packages. Before writing anything it
checks that the bundle's boot files are present, that `payload.sha256` lists exactly one armv7 and one aarch64 package, and that
each package matches its checksum; it then unpacks onto an empty drive like the easy stick. The installer downloads the bundle named in
`tools/desktop/g2stick-pin.json` (read from `main` at run time, so a new G2 release is a one-file change; the url must be under this repo's
releases and the sha256 is checked), and a local bundle file can still be chosen. Each G2 release needs a new bundle, built with
`tools/usb_g2/build_stick.py` from the user's own firmware (only the derived `autorun.check` goes in).

A password SSH stick can't work on a Gen2 (read-only root, found on a Live III 2026-10-29): the page says "Gen2 needs a key", and when the scanned firmware looks Gen2 (its name says Gen2, or it is an aarch64 executable) `stickBuild` refuses a password and the page blocks it.

Below it, a collapsed **Advanced: turn on SSH (for developers)** section (`tools/desktop/stick.go`, a Go port of the salt scan in
`tools/usb_stick/saltscan.py`, so the app needs no Python) builds a different stick: it reads the device's own stock Akai firmware
once for the check the stock "USB script" reader needs (MPC OS up to 3.9.1 only; Akai closed that route in 3.10), turns SSH on (paste
a public key, have the app generate one whose private half is shown once and never kept, or, with heavier warnings, set a password,
which needs a writable root and is refused on most Gen2 units) and reapplies every already-installed addin's `LD_PRELOAD` entry
(needed on a device with no persistent `/etc`, docs/ADDINS.md). A checkbox, on by default, also puts the plugin manager on the same
stick: the manager's files go in unmodified, its `open.sh` is kept as `autorun/manager-open.sh`, and our `open.sh` runs the SSH and
addin step first (restarting MPC once if the addins' running `LD_PRELOAD` differs, so the manager sees them), then it. The stick's
`USB-SHA256.json` is rewritten to match. A Gen2 device like the Live III forgets SSH and the addin drop-in at every reboot, so the
stick is reinserted after each one. The stick no longer installs a preset plugin list itself (`tools/usb_stick/*.py` still does).
None of this needs the device's own SSH yet. Both the firmware path and the output folder have a
**Browse…** button (`/api/browse`, a server-side folder/file picker, since a browser's own file input never exposes a real path)
instead of typing one, and the output folder step also lists this computer's mounted drives (`/api/drives`; Linux, macOS and
Windows): pick a mounted USB stick there and Build writes the stick straight onto it, with nothing left to copy by hand.

## What it does, in order

1. **Connect:** SSH as root with your password, a key in `~/.ssh` (no passphrase), or neither on a device whose root has no password. It reads the device (32-bit ARM or Gen2 aarch64: Gen2 gets the catalog's aarch64 zips; `tar`?
   `systemctl`? where is `MPC.settings`?) and refuses one that is not an MPC OS device. The device's key fingerprint is shown; nothing
   about the device is saved.
   The device scan lists every writable `Synths` location (the internal drive — `/sdcard/Synths` on Gen1/Force, `/nvme/Synths` on a Gen2 Live III and `/storage/Synths` on a Gen2 MPC One or Key 37 (no NVMe), where `/sdcard` isn't mounted — and `/media/*/Synths` for cards and drives; read-only mounts such as
   MPC's own content folder are skipped, and the same storage reached by two paths is listed once; the internal drive's `Synths` folder is created at connect when it is missing, 2026-10-11). Step 3 lets you pick where to install, the
   internal drive by default, and warns when MPC does not list the folder as a content location (the plugin still loads, but with no skin; the job log repeats it as a `WARNING`, and a package's `install.sh` prints the same warning on stderr, comparing whole entries and ignoring a trailing slash, 2026-10-27). A writable drive under `/media` (its own
   mount point, not MPC OS's `az01-*`/`acvs-*`) that has no `Synths` folder gets a **Create Synths folder** button in that box
   (`/api/mkroot`; only a drive from the last scan is accepted, never a typed path), after which it is a plugin location (2026-10-14, offline). A drive that cannot store symbolic links
   (FAT, exFAT, NTFS) is refused for a package that needs them, and so is a drive without room. A drive mounted `noexec` (an MPC/Force's SSD is) is refused too: MPC cannot load a plugin from it, so the plugin would be listed but only show "Load Plugin".
2. **Choose:** the catalog's newest stable release of every downloadable plugin, plus any zips you drop in. Tabs for Instruments, MIDI (generators and sequencers, from the catalog's `role: "midi"`), Effects, Addins and All (everything together) (2026-10-10, like the catalog page; the counts follow the search, so you can see which tab holds a match), a search box, a developer filter, a sort, and a "show" filter (not on the device, on the device, updates available, only the ones you ticked) keep a
   long list manageable; what you ticked stays ticked while you filter or change tab, and a bar at the bottom shows the count and an Install button.
   Versions installed by this app or `mpc-store.sh` are read from `<Synths>/.mpc-store` to flag updates. A zip is checked before
   it is accepted (one folder, the manifest, no paths that leave it, links that stay inside, no more than 2 GB unpacked).
3. **Install:** catalog downloads are checked against the catalog's sha256 first (a mismatch installs nothing). Then, after you confirm
   (save your project: MPC restarts), it copies every package to a private folder in the device's `/tmp`, stops MPC once, runs each
   package's `install.sh -y -n`, starts MPC once and removes the copies. An installer that predates `-n` runs first with its own
   restart. MPC is started again even if something fails, and nothing after the failing plugin is installed.
   If the SSH connection drops during a copy (a laptop waking from sleep, a Wi-Fi or VPN change), the app reconnects once, after
   checking that the device presents the same key, and copies that package again; MPC is not stopped and nothing is installed
   until every copy is done, so this is safe. A second drop stops with "Nothing was installed and MPC was not stopped"
   (`TestACopyThatLosesTheConnectionIsRetriedOnce`, offline, 2026-10-14). A connection that silently stalls (a weak Wi-Fi
   link, not a clean drop) is caught by SSH keepalives: the app pings the device every 15 s and, after a couple of missed
   replies, closes the dead connection so a command returns an error you can retry instead of hanging (2026-10-23).
   **Register every plugin folder** (ticked by default, under Install to; `InstallOpts.Register`): after the packages are in
   place, and while MPC is still stopped for the batch, the app runs its own embedded `sync.sh` with every plugin location, so
   folders you copied in by hand or that MPC forgot also get into MPC's plugin list, `MPC.settings` is backed up first, and MPC
   restarts once. Nothing has to be on the device. If registering fails the job reports it and MPC is started again
   (`TestInstallCanRegisterEveryPluginFolder`, `TestInstallWithoutRegisterLeavesHandCopiedFoldersAlone`, offline, 2026-10-14).

4. **Remove** (step 4 on the page): lists the plugin folders on the device. A plugin the app can identify (from the catalog, or from a
   zip you dropped in this session) can be ticked and removed: MPC is stopped once, `MPC.settings` is backed up and the plugin's entry is
   taken out (the edit is checked before anything is deleted), then its folder is deleted **except your own files** (the manifest's
   `user_data`: ROMs, kits, dumps), MPC is started again. A plugin it cannot identify is listed but not removable, because it cannot tell
   which files in it are yours: drop its release zip to manage it, or remove it by hand. The plugin-list edit uses
   `plugin_list.awk`, a copy of `tools/release/plugin_list.awk` embedded in the binary (a test fails if the two differ: copy it again).

5. **Register plugin folders** (step 5, collapsed, with a count when something is waiting): the plugin folders in any location that are not in MPC's
   plugin list (copied in by hand, or dropped by MPC because a card was out at startup), and entries whose plugin file is gone. It runs the
   embedded `sync.sh` (a test keeps it identical to `tools/release/sync.sh`) between one MPC stop and start; everything else in the list stays.
6. **Clean up old backups** (step 6, collapsed): every install, removal and sync leaves a copy of `MPC.settings` named
   `MPC.settings.bak-<what>-<date>` that nothing deletes. The page counts them and deletes all but the newest N (default 10, at least 1:
   the newest is never deleted, and only files named like that are touched). MPC is not stopped. `mpc-store.sh prune [--keep N]` does the
   same on the device.
7. **Advanced: device patches** (step 7, collapsed; `docs/PATCHES.md`): lists the patches in `patches.json` (published next to
   `catalog.json`) and, when you open the step or press "Check the device", asks the device which are applied. A patch changes the device itself,
   not a plugin; a row shows Not applied, Applied, Installed-not-active, or why it is not supported (for example the device's MPC checksum, or that no drive is mounted `noexec`). The app downloads the script, checks it against the manifest's sha256, copies it to a private folder on the device, runs only its
   `status` command and removes the copy. Checking never changes anything. **Apply** and **Undo** (2026-10-10, offline only: fake-device and stubbed-browser tests, not yet run on a device) open a box that names what the patch changes and asks for a typed word (`APPLY` / `UNDO`, checked again by the server); then the app runs the script's `install --confirmed` / `uninstall --confirmed` with its default settings (no options: for those, such as which buttons to remap, run the script over SSH as its guide says), shows its output like an install, asks `status` again and reports success only when the device is in the requested state (`patched` / `stock`). One job at a time; the patch is looked up by id in the manifest the app fetched, never taken from the page. Nothing is asked of the
   device at connect time, and not while a job runs. Tests: `patches_test.go`, `patches_run_test.go`, and `ui_test/ui_patches.py` (a browser test with the API stubbed).

**Addins** (catalog kind `addin`: libraries MPC loads when it starts, `docs/ADDINS.md`) go through the same steps. A catalog addin or a
dropped addin zip installs to `/data/mpc-addins/<id>` with its own `install.sh -y -n`, inside the same single MPC stop and start, whatever
location step 3 picked. Step 4 lists the addins found there after the plugins; one installed by its `install.sh` carries its own `uninstall.sh`,
which removal runs (it takes the addin out of MPC's `LD_PRELOAD` and deletes its folder; `MPC.settings` is not touched). A folder
without one is listed but not removable here.

The catalog says, for every version, whether its installer understands `-n` (`defer` in `catalog.json`, column 14 of `catalog.tsv`).
The page uses that to state the exact number of MPC restarts before you confirm, and marks releases whose older installer restarts MPC by
itself. A zip you drop in is inspected directly.

**MPC OS badge and warnings.** The catalog also says which MPC OS generations a version works on (`os_compat`, `os_compat_why` and `max_glibc` in
`catalog.json`; columns 15 and 16 of `catalog.tsv`; docs/OS2_SKINS.md). MPC OS 3.x is the standard, so the list shows only one
badge, "MPC OS 2.x tested", on a 2.x-capable version with a 2.x device test (`tested[].firmware` 2.x; 2026-10-12, as on the catalog site). Connecting
reads the device's glibc (`libc` in the device info: run the libc for its version, or take it from `libc-2.33.so`; nothing is guessed when
neither works). Against that glibc the list adds a note per plugin, and the install dialog repeats it: a plugin that needs a newer glibc than
the device has "will not load" (the button becomes *Install anyway*), and a 3.x-only plugin on a device below glibc 2.34 (MPC OS 2.x) "may
show an empty touchscreen page". It warns and never blocks. Tests: `catalog_test.go`, `device_test.go` (`TestDialReadsTheDevicesGlibc`) and
`ui_test/ui_os.py` (a browser test with the API stubbed). `tools/mpc-store.sh` prints the same notes before its confirmation.

What was installed is written to `<Synths>/.mpc-store` on the device, so `mpc-store.sh update` (the on-device script) knows about it.

## Safety

- The page is served on `127.0.0.1` only, behind a random token in the link the app prints. Every request must carry the token, the
  right `Host` and (for posts) the right `Origin`, and the page has a strict Content-Security-Policy, so other computers and other web
  pages cannot drive it.
- The password is used for that one connection and never written down. There is no telemetry. The one thing it fetches besides the catalog is the list of this repository's releases from `api.github.com` (an hourly check, 5 s timeout, nothing sent but the request) so the page can say when a newer `desktop-v*` release exists; it is silent when offline, skipped for a `dev` build, and `--no-update-check` turns it off.
- Only https downloads are accepted, and only what the catalog lists.

## Run it

Download the archive for your system from the releases, unpack it and start `mpc-installer` (double-click it, or run it in a
terminal). It prints a link and opens it in your browser. `--no-browser` only prints the link; `--port`, `--catalog`, `--no-update-check` and `--version`
exist too.

The first run is unsigned, so the system warns you once:

- **Windows:** "Windows protected your PC": click *More info*, then *Run anyway*.
- **macOS:** it will not open on a double-click. Right-click the file, choose *Open*, then *Open* again (or run
  `xattr -d com.apple.quarantine mpc-installer` in a terminal).
- **Linux:** `chmod +x mpc-installer` if needed.

## Build and test

Go 1.26 or newer, two dependencies (`golang.org/x/crypto`, `github.com/ulikunitz/xz` for the USB-stick mode's salt scan):

```
cd tools/desktop
go test -race ./...                       # includes a fake SSH device that runs the whole install in-process
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=1.0.0" -o mpc-installer .
```

A browser test of the page against a stand-in device (sshd in a container) lives in `ui_test/`; see its header. The release workflow
is `.github/workflows/desktop.yml` (Actions, "Desktop installer", Run workflow: builds Windows, macOS and Linux binaries into a
draft release; install it, try it, then publish).

The SSH stick opens its bundled manager only the first time (it writes `.plugin-manager-opened` on the stick); later insertions just redo SSH and the addins, and a file `open-plugin-manager.txt` on the stick opens it again (2026-10-29: inserting it to get SSH back kept launching the manager). Test: `TestAdvancedStickOpensTheManagerOnlyOnceUnlessAsked`.
