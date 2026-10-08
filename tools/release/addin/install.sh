#!/bin/sh
# Install an MPC addin (the one addin.manifest describes) on an MPC OS device. Run on the device as root, from
# the unpacked folder:   sh install.sh [-y] [-n] [-t <folder>]
# Copies the addin's files into <folder> (default /data/mpc-addins/<id>), adds its .so to the LD_PRELOAD of MPC's
# systemd service, and restarts MPC. LD_PRELOAD is extended, never replaced: other addins already in it stay. Where
# a writable file sets it, the line that takes effect is edited in place (a backup is kept). Otherwise (nothing
# sets it, or the unit is on a read-only root) one drop-in shared by every addin sets it: the unit's list, then
# the addins. The folder also gets uninstall.sh, so `sh <folder>/uninstall.sh` removes the addin later.
#   -y  don't ask   -n  don't restart MPC (the caller stops and starts it; the addin starts with MPC's next start)
# mpc-vst-plugins tools/release/addin: identical in every addin release (docs/ADDINS.md).
set -e
cd "$(dirname "$0")"
YES=0; RESTART=1; DIR=""; DEFER=1   # DEFER: this installer understands -n (batch installers look for it)
die() { echo "error: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
    case "$1" in
        -y) YES=1; shift ;;
        -n) RESTART=0; shift ;;
        -t) [ -n "$2" ] || die "-t needs a folder"; DIR="$2"; shift 2 ;;
        *) die "usage: sh install.sh [-y] [-n] [-t <folder>]" ;;
    esac
done
. ./addin-lib.sh
load_manifest
check_dir
SO="$DIR/$ADDIN_SO"
if [ -z "$ADDIN_INSTALL_TEST" ]; then
    [ "$(id -u)" = 0 ] || die "run as root"
    case "$(uname -m)" in armv7*) ;; *) die "this build is for 32-bit ARM MPC OS devices; this one is $(uname -m)" ;; esac
fi
for f in "$ADDIN_SO" $ADDIN_CONF $ADDIN_FILES; do [ -f "$f" ] || die "$f is missing next to install.sh"; done
check_so "$ADDIN_SO"

SVC=$(mpc_service)
check_lib "$SVC"
UNIT=$(unit_with_preload "$SVC" "$(ours "$SVC")")   # not our own drop-in: it repeats the unit's list
echo "Installing $ADDIN_NAME${ADDIN_VERSION:+ $ADDIN_VERSION}:"
echo "  $DIR/"
if edits_in_place "$SVC" "$UNIT"; then echo "  LD_PRELOAD in $UNIT gains $ADDIN_SO (a backup is kept)"
else echo "  $(ours "$SVC") sets LD_PRELOAD: ${UNIT:+the list from $UNIT, then }the addins"; fi
if [ $RESTART = 1 ]; then echo "  then MPC restarts: save your project first"; fi
if [ $YES = 0 ]; then
    printf "Continue? [y/N] "; read -r ok
    case "$ok" in y|Y|yes) ;; *) echo "cancelled"; exit 1 ;; esac
fi

mkdir -p "$DIR"
for f in "$ADDIN_SO" $ADDIN_FILES; do   # staged, then renamed: a running MPC keeps the old file mapped
    cp "$f" "$DIR/$f.new" && chmod 644 "$DIR/$f.new" && mv "$DIR/$f.new" "$DIR/$f"
done
for f in $ADDIN_CONF; do [ -f "$DIR/$f" ] || cp "$f" "$DIR/$f"; done
if [ "$(cd "$DIR" && pwd)" != "$(pwd)" ]; then   # not when reinstalling from the folder itself
    for f in $SELF_FILES; do cp "$f" "$DIR/$f.new" && chmod 644 "$DIR/$f.new" && mv "$DIR/$f.new" "$DIR/$f"; done
fi
preload_add "$SVC" "$UNIT" "$SO"
mockba_hook_add "$SO"
svc daemon-reload
sync
if [ $RESTART = 1 ]; then svc restart "$SVC"; echo "Done. MPC restarted."
else echo "Done. The addin starts with MPC's next start."; fi
[ -z "$ADDIN_DONE" ] || echo "$ADDIN_DONE"
