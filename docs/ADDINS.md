# Addins

An addin is a library that MPC OS standalone devices (MPC Live/One/X/Key, Force) load into the MPC process through
`LD_PRELOAD` when MPC starts, rather than a plugin that MPC's host loads on a track. Examples: a remote-control web
server, the MPC as a USB audio interface. Addins are listed in the catalog next to plugins (kind `addin`), released as
one zip each, and installed by the same tools: the zip's own `install.sh`, `tools/mpc-store.sh` on the device, or the
desktop app (`tools/desktop`).

Each addin lives in `/data/mpc-addins/<id>/`: on these devices the root filesystem is read-only and nearly full, and
`/data` is not.

## The LD_PRELOAD rules

systemd's `Environment=LD_PRELOAD=...` replaces the variable; it doesn't append to it. An addin that wrote its own
drop-in would silently drop every library the service already preloads (the firmware's own, another mod's, another
addin). So every addin installs the same way, with the installer in `tools/release/addin/` (`install.sh`,
`uninstall.sh`, `addin-lib.sh`), identical in every release:

- If a writable unit file or drop-in of MPC's service (`acvs`, or `inmusic-mpc` on some modified firmware) already
  sets `LD_PRELOAD`, the one that takes effect (the last one systemd reads) is edited in place: the addin's `.so` is
  appended, and a backup (`<file>.bak-mpc-addins`) is kept from before the first edit. Quoted, space-separated lists
  stay quoted and are written back with `:`.
- Otherwise (nothing sets it, or, as on these devices, the unit sits on the read-only root), one drop-in shared by
  every addin sets it: `/etc/systemd/system/<service>.service.d/90-mpc-addins.conf`, holding the list the unit sets,
  then the addins. It records that list (`# base:`); when a firmware update changes it, the next install or uninstall
  rebuilds the drop-in from the new list, so the firmware's own libraries are never shadowed for long. Re-run an
  addin's `install.sh` after a firmware update.
- Uninstalling takes only that addin's `.so` out, and removes the shared drop-in once no addin is left in it.
- The shared drop-in records its format (`# lib: <n>`, `ADDIN_LIB_VERSION` in `addin-lib.sh`; a drop-in without the line
  is format 2). Every installed addin carries its own copy of the installer, so copies of different ages edit the same
  file. The rule: an installer refuses to touch a drop-in written by a newer format (it says to install a newer release
  of the addin), and a new format must still read every older one. Bump the number whenever the drop-in's format
  changes.
- A folder is "writable" only if a probe file can be created in it: BusyBox's `[ -w ]` says yes to root on a
  read-only mount.

`install.sh [-y] [-n] [-t <folder>]` copies the files (each staged as `<file>.new`, then renamed, since a running
MPC keeps the old `.so` mapped), installs the settings file only when the folder has none (the user's edits survive
an upgrade), adds the `.so` to `LD_PRELOAD` and restarts MPC. `-n` leaves MPC alone: the caller stops and starts it
once for a batch (`DEFER=1` in the script tells batch installers so). The folder also gets `uninstall.sh`,
`addin-lib.sh` and `addin.manifest`, so `sh /data/mpc-addins/<id>/uninstall.sh` removes the addin later without the
release; that is what `mpc-store.sh remove` and the desktop app run.

Before anything changes, `install.sh` checks the `.so` on the device: it must be an ELF 32-bit little-endian ARM shared
object, since anything else in `LD_PRELOAD` stops MPC from starting. The folder (`-t`, default
`/data/mpc-addins/<id>`) must be an absolute path named after the addin (`.../<id>`), with no `.` or `..` segments.
`uninstall.sh` deletes only the files the installer put there: the `.so`, the files in `ADDIN_FILES`, **the settings
file** (so the user's edits to it are lost; copy it first to keep them) and the installer's own three files. It then
removes the folder if it is empty, and otherwise keeps it and says so.

An addin runs inside MPC before MPC sets itself up, so it must not take anything MPC needs first. The DRM card is
the known case: whatever opens `/dev/dri/card*` first, while the card has no master, becomes the
master, and MPC then fails with "Failed to initialise display". An addin (or a helper tool) that opens the card must
call `DRM_IOCTL_DROP_MASTER` right after opening it (NOTES.md, 2026-10-03).

### MockbaMod and other launchers that set LD_PRELOAD themselves

MockbaMod's `boot.sh` starts MPC with `export LD_PRELOAD="$(cat /dev/shm/.LD_PRELOAD)"`, a list the `AddOns/run_*.sh`
scripts fill in. The systemd line or drop-in above never reaches MPC there, so an addin installed only that way is
silently not loaded. When a card with `MockbaMod/env.sh` and an `AddOns` folder is found (via `/dev/shm/.mmPath`, else
`/media/*`), `install.sh` also writes `AddOns/run_<id>.sh` and adds the `.so` to that file straight away, so the restart
that follows loads it; `uninstall.sh` removes both. The hook adds the `.so` only if it is missing, under the same
`/dev/shm/.LD_PRELOAD.lock` the mod's own scripts use, does it before anything else (boot.sh starts every hook in the
background and launches MPC a second later) and does nothing on `kill`. Tests: case 12 in `tools/test_addin.sh`.

## When an addin stops MPC from starting

An addin runs inside MPC, so a broken one can crash MPC at every start. SSH stays up (it is a separate service), and
everything an addin changed can be undone from there:

1. Stop MPC: `systemctl stop acvs` (`inmusic-mpc` on some modified firmware; `systemctl list-units | grep -i mpc`
   shows which).
2. **One addin:** run its `sh /data/mpc-addins/<id>/uninstall.sh -y -n`. If that fails, take its `.so` path out of the
   `Environment=LD_PRELOAD=` line of `/etc/systemd/system/acvs.service.d/90-mpc-addins.conf` by hand (leave the `# base:`
   line and the libraries before the addins alone). If the addins went into a unit file that already set
   `LD_PRELOAD`, edit that file instead (`grep -rl LD_PRELOAD /etc/systemd/system/acvs.service*`).
3. **Every addin at once:** delete `/etc/systemd/system/acvs.service.d/90-mpc-addins.conf`, and restore every
   `<file>.bak-mpc-addins` backup over the file it was taken from
   (`find /etc/systemd/system -name '*.bak-mpc-addins'`). That puts back the list the firmware set; the addins' folders
   stay in `/data/mpc-addins/` and do nothing until they are installed again.
4. `systemctl daemon-reload`, then `systemctl start acvs`.

Most addins also have an off switch in their settings file (`enabled=0`), which leaves the library loaded but idle.

## Addins that listen on the network

An addin that serves something over the network must listen on the device only by default (`bind=127.0.0.1`),
must say in its catalog `summary` what it exposes and how to reach it, and must have a `bind` setting. Addins run as
root inside MPC and the ones below have no login, so the network is opt-in.

To reach one from a computer, open an SSH tunnel to the device and leave it running, then use `localhost` on that
computer:

```sh
ssh -N -L 6730:127.0.0.1:6730 root@<device address>     # one -L per addin: 6720 for remote, 6730 for commander
```

`bind=0.0.0.0` in the addin's settings file opens it to every network interface instead (settings are read when MPC
starts). The ones in the catalog, and what anyone who can reach the port can then do:

| Addin | Port | Login | Who can reach it can |
|---|---|---|---|
| `remote` | HTTP 6720 | none | see and touch the screen, send any MIDI into MPC, and read text files in the `mcp_files` folders through its MCP endpoint (read-only; `mcp=0` turns MCP off). The MCP endpoint refuses requests from a web page on another site (`Origin` and `Host` checks); the rest of the server has no such check |
| `commander` | HTTP and WebSocket 6730 | none | change any parameter of the VST plugins MPC has loaded, send MIDI and transport commands into MPC, write to the control-surface injector file, read the most recent project file and the plugins' skins. There is no `Origin` check yet, so a web page open in a browser on the same network can reach it too |

An upgrade keeps the user's settings file, so a device that installed an older release with `bind=0.0.0.0` keeps
listening on the network until `bind` is changed by hand.

## addin.manifest

Next to the addin's files, in its build output. `install.sh` sources it as root, so it may hold only plain
assignments of these keys, comments and blank lines (`tools/catalog_check.py` refuses anything else: no `$`,
backquotes or backslashes):

```sh
ADDIN_ID=remote                       # the folder, /data/mpc-addins/remote; the catalog id (lowercase, digits, -)
ADDIN_NAME="MPC Remote"               # shown to the user
ADDIN_SO=mpc_remote_addin.so          # preloaded into MPC
ADDIN_CONF=mpc_remote_addin.conf      # installed only when the folder has none ("" none)
ADDIN_FILES="standalone"              # other files, replaced on every install ("" none)
ADDIN_DONE="Open http://<device>:6720 in a browser."   # printed at the end ("" none)
```

`ADDIN_VERSION` is added by `tools/release_addin.py`. File names are plain names (no `/`, no leading `.`) and may not
be the installer's own. An addin finds its settings file in its own folder (the `.so`'s folder, through
`/proc/self/maps`, as `wrapper/plugin_dir.h` does for plugins).

## Releasing

1. Build the `.so` for armhf (an older glibc than the device's, as for plugins: `docs/RELEASING.md`) into a folder with `addin.manifest`
   and the files it names.
2. Package and check it:
   ```sh
   tools/release_addin.py --dir build/package --version 1.0.0 --repo owner/mpc-addin-<name> --license MIT \
       --about "One line." -o dist
   tools/catalog_check.py dist/<Name>-1.0.0-mpc-armv7.zip --catalog --expect-id <id> --expect-repo owner/mpc-addin-<name>
   ```
   The zip unpacks to `<Name>-<version>/` with the installer, `addin.manifest` (with `ADDIN_VERSION`), the addin's
   files, `INSTALL.md`, `mpc-plugin.json` (`kind` and `layout` `"addin"`, `docs/CATALOG_SPEC.md`) and `SHA256SUMS`,
   and nothing else.
3. Test it on a device: `sh install.sh`, use it, `sh /data/mpc-addins/<id>/uninstall.sh`.
4. Publish it as a GitHub release of the addin's repo and add a registry entry with `"kind": "addin"`
   (`catalog/README.md`). Addins are always release entries, never build-yourself.

### Releasing from CI
`.github/workflows/addin-release.yml` does steps 1, 2 and 4's upload in GitHub Actions: it builds under QEMU, runs the
host test, packages and checks the zip, and attaches it to a **draft** release in the addin's repo. Step 3 stays on a
device, with the draft's zip; publishing the draft creates the tag. Call it from the addin's repo with a
`workflow_dispatch` workflow that takes the version, pinning this repo to one commit in both places:
```yaml
jobs:
  addin:
    uses: sd88me/mpc-vst-plugins/.github/workflows/addin-release.yml@<sha>
    permissions: { contents: write }
    with:
      tag: my-addin-v${{ inputs.version }}
      version: ${{ inputs.version }}
      tools_ref: <sha>                 # the same commit
      package_dir: build/package       # the build writes addin.manifest, the .so and the files it names here
      build: tools/build_armhf.sh      # run from the repo root; MPC_VST is set
      host_test: tools/test_host.sh    # optional; MPC_VST is set
      about: One line about the addin.
      license: MIT                     # needed to be listed in the catalog
      dry_run: ${{ inputs.dry_run }}   # optional: the zip as a run artifact only
```
Re-running with the same version replaces the draft's zip; a version that is already published is refused.

Addin repos are named `mpc-addin-<name>`. For a quick test without a release, unzip the package from step 2 (or copy
the three installer files next to the build output) and run its `install.sh`.

## Tests

- `tools/test_addin.sh` (run by `tools/test_catalog.py`): the installer against scratch systemd trees with two
  addins side by side: appending to a list, idempotency, settings kept, one uninstall leaving the other, the quoted
  form, the shared drop-in, the winning drop-in, `inmusic-mpc`, a read-only unit and a firmware update changing its
  list, the folder's own uninstaller, refusals of odd folders (`/`, `/etc`, `..`, a folder not named after the addin)
  and bad manifests, a library that is not a 32-bit ARM shared object, a drop-in from a newer format, and an
  uninstall that keeps a file the user added. `BUSYBOX=/path/to/busybox` runs it
  in the device's shell (the default when `busybox` is on the PATH).
- `tools/test_catalog.py` (`AddinTest`, `StoreTest`): packaging, validation and tampering, registry and
  `catalog.tsv`, and `mpc-store.sh` installing, updating and removing an addin alongside a plugin.
- `tools/desktop`: `go test ./...` (`addin_test.go`) and `ui_test/ui_addins.py`.
