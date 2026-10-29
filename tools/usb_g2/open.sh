#!/bin/sh
# Runs as root when the stock USB-script prompt is confirmed. Copies the runtime to RAM and runs it as a systemd unit, so it keeps
# going when MPC is stopped and when the stick is pulled. Needs nothing on the device: no SSH, no network, no addins.
set -eu
here=$(CDPATH= cd "$(dirname "$0")" && pwd)
usb=$(dirname "$here")
work=$(mktemp -d /tmp/mpc-g2-install.XXXXXX)
cp -R "$here/runtime/." "$work/"
if [ -n "${MPC_USB_TEST:-}" ]; then exec sh "$work/run.sh" "$usb" "$work"; fi
exec systemd-run --unit=mpc-g2-install --collect sh "$work/run.sh" "$usb" "$work"
