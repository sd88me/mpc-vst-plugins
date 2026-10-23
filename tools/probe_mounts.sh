#!/bin/sh
# Read-only report of how an MPC OS device mounts external drives and where `noexec` comes from. Changes nothing.
#   ssh root@<device-ip> sh -s < tools/probe_mounts.sh > mounts-report.txt
# Plug the drives you use in first (SD card, USB stick, the SSD), then run it. It is for working out a patch that mounts
# drives so plugins can load from them (docs/NOTES.md 2026-10-14). Post the output; it holds no passwords or keys, but it does
# list your drive names and the processes running, so read it before you share it.
B=${MPC_BIN:-/usr/bin/MPC}
say() { echo; echo "== $*"; }
say "device"
uname -m; grep -m1 -E "^VERSION=" /etc/os-release 2>/dev/null; uname -r
say "mounts under /media and /sdcard (the options are the point: exec or noexec, and the uhelper= tag if there is one)"
grep -E " /(media|sdcard|synths)" /proc/mounts
say "who mounted them: processes that look like a disk or mount daemon"
for p in $(ps -eo pid= 2>/dev/null | tr -d ' '); do
    c=$(cat /proc/$p/cmdline 2>/dev/null | tr '\0' ' ')
    case "$c" in *disks*|*udisk*|*automount*|*usbmount*|*mount*|*udevd*) echo "$p $c" ;; esac
done | grep -v "probe_mounts" | head -n 20
say "systemd units that mention mount, disks or udisks (names only)"
systemctl list-units --all --no-legend 2>/dev/null | awk '{print $1}' | grep -i -E "disk|mount|media|udev" | head -n 40
say "unit files for the disk daemon (ExecStart and anything about options)"
for u in $(systemctl list-unit-files --no-legend 2>/dev/null | awk '{print $1}' | grep -i -E "disk|automount" | head -n 6); do
    echo "-- $u"; systemctl cat "$u" 2>/dev/null | grep -E "^(\[|ExecStart|Environment|After|Wants)" | head -n 12
done
say "udev rules and config that mention exec, mount options or the disk daemon"
grep -rIl -i -E "noexec|mount_options|uhelper|edisksd|udisks" /etc /lib/udev /usr/lib/udev /lib/systemd /usr/lib/systemd /usr/share/udisks2 2>/dev/null | head -n 30
say "the lines in those files (first 30)"
grep -rI -n -i -E "noexec|mount_options|uhelper" /etc /lib/udev /usr/lib/udev /usr/share/udisks2 2>/dev/null | cut -c1-220 | head -n 30
say "disk daemon binaries: does the program contain the option string (a hard-coded noexec means a config edit will not do)"
for b in $(command -v edisksd udisksd 2>/dev/null) /usr/libexec/udisks2/udisksd /usr/sbin/edisksd /usr/bin/edisksd; do
    [ -f "$b" ] || continue
    echo "-- $b"; strings -n 4 "$b" 2>/dev/null | grep -i -E "noexec|nosuid|nodev|uhelper|mount_options|\.conf" | sort -u | head -n 25
done
say "does MPC see the same mounts as the shell (a different mount namespace would hide a remount)"
p=$(pidof MPC)
if [ -n "$p" ]; then
    echo "MPC pid $p: namespace $(readlink /proc/$p/ns/mnt)   shell: $(readlink /proc/$$/ns/mnt)"
    grep -E " /media/" /proc/$p/mountinfo | cut -c1-200
else
    echo "MPC is not running"
fi
say "/etc/fstab and the read-only state of /"
cat /etc/fstab 2>/dev/null; findmnt -rn -M / -o OPTIONS 2>/dev/null
echo; echo "done: nothing was changed"
