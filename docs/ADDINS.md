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
- A folder is "writable" only if a probe file can be created in it: BusyBox's `[ -w ]` says yes to root on a
  read-only mount.

`install.sh [-y] [-n] [-t <folder>]` copies the files (each staged as `<file>.new`, then renamed, since a running
MPC keeps the old `.so` mapped), installs the settings file only when the folder has none (the user's edits survive
an upgrade), adds the `.so` to `LD_PRELOAD` and restarts MPC. `-n` leaves MPC alone: the caller stops and starts it
once for a batch (`DEFER=1` in the script tells batch installers so). The folder also gets `uninstall.sh`,
`addin-lib.sh` and `addin.manifest`, so `sh /data/mpc-addins/<id>/uninstall.sh` removes the addin later without the
release; that is what `mpc-store.sh remove` and the desktop app run.

An addin runs inside MPC before MPC sets itself up, so it must not take anything MPC needs first. The DRM card is
the known case: whatever opens `/dev/dri/card*` first, while the card has no master, becomes the
master, and MPC then fails with "Failed to initialise display". An addin (or a helper tool) that opens the card must
call `DRM_IOCTL_DROP_MASTER` right after opening it (NOTES.md, 2026-10-03).

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
  list, the folder's own uninstaller, refusals of odd folders and bad manifests. `BUSYBOX=/path/to/busybox` runs it
  in the device's shell (the default when `busybox` is on the PATH).
- `tools/test_catalog.py` (`AddinTest`, `StoreTest`): packaging, validation and tampering, registry and
  `catalog.tsv`, and `mpc-store.sh` installing, updating and removing an addin alongside a plugin.
- `tools/desktop`: `go test ./...` (`addin_test.go`) and `ui_test/ui_addins.py`.
