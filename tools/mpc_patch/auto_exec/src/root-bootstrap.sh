#!/bin/sh
set -eu
# Adds or removes the bootstrap unit in the system image (the root filesystem is read-only on the device: it is remounted
# writable only for this and restored afterwards). The files are written through a bind mount of /, so they land in the
# root filesystem even when something has mounted an overlay over /usr: systemd reads the wants link at boot, before
# such an overlay exists (0.3.1; 0.3.0 wrote into the overlay and never started at boot there). Original: timomacquis,
# 0.1.3. `check` (read-only) succeeds when both are in the root filesystem. AEX_PREFIX (tests only) redirects the paths and skips the remount.
P=${AEX_PREFIX:-}
ROOT_RO=0
if [ -z "$P" ] && [ "$1" != check ]; then
 case ",$(findmnt -rn -M / -o OPTIONS)," in *,ro,*) ROOT_RO=1; mount -o remount,rw /;; esac
fi
VIEW=$(mktemp -d)
mount --bind "${P:-/}" "$VIEW"
restore_root() { sync; umount "$VIEW" && rmdir "$VIEW"; if [ "$ROOT_RO" = 1 ]; then mount -o remount,ro /; fi; }
trap restore_root EXIT
UNIT=$VIEW/usr/lib/systemd/system/auto-exec-bootstrap.service
LINK=$VIEW/usr/lib/systemd/system/multi-user.target.wants/auto-exec-bootstrap.service
case "$1" in
 install)
  [ ! -e "$UNIT" ] && [ ! -L "$LINK" ] || { echo 'Bootstrap already exists'; exit 1; }
  mkdir -p "$VIEW/usr/lib/systemd/system/multi-user.target.wants"
  cp "$2" "$UNIT"
  chmod 644 "$UNIT"
  ln -s ../auto-exec-bootstrap.service "$LINK"
  ;;
 remove)
  rm -f "$LINK" "$UNIT"
  ;;
 check)
  [ -f "$UNIT" ] && [ -L "$LINK" ]
  ;;
 *) exit 1;;
esac
