#!/bin/sh
# Runs as root after the on-screen prompt (MPC OS up to 3.9.1). Turns on SSH and puts addins back, then opens the community plugin
# manager when this stick carries it: autorun/manager-open.sh is that project's own open.sh, unmodified (MIT, runtime/licenses).
# Detaches into a systemd unit first, so it keeps going when MPC is stopped (the manager stops it) or restarted.
set -eu
here=$(CDPATH= cd "$(dirname "$0")" && pwd)
usb=$(dirname "$here")
if [ "${1-}" != --run ] && [ -z "${MPC_USB_TEST:-}" ]; then
    exec systemd-run --unit=mpc-usb-advanced --collect sh "$here/open.sh" --run
fi
log=$(mktemp /tmp/mpc-usb-extras.XXXXXX)
sh "$here/runtime/mpc-extras.sh" "$here/runtime" >"$log" 2>&1 || true
cp "$log" "$usb/mpc-extras-result.txt" 2>/dev/null || true
rm -f "$log"
[ -f "$here/manager-open.sh" ] || exit 0
# The manager opens the first time the stick is used, then only when asked: put a file called open-plugin-manager.txt on the
# stick (anywhere at its root) to open it again. Otherwise inserting the stick later just re-enables SSH and the addins.
if [ -f "$usb/.plugin-manager-opened" ] && [ ! -f "$usb/open-plugin-manager.txt" ]; then
    echo "plugin manager already opened from this stick; not opening it again (add open-plugin-manager.txt to the stick to open it)" > "$usb/mpc-extras-manager.txt" 2>/dev/null || true
    exit 0
fi
: > "$usb/.plugin-manager-opened" 2>/dev/null || true
exec sh "$here/manager-open.sh"
