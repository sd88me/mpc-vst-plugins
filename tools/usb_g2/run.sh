#!/bin/sh
# usb_g2/run.sh <stick> <work>: installs the OpenMPC Plugin Manager G2 package that is bundled on the stick, then MPC is restarted
# (by the package's own install.sh, which backs up MPC.settings, registers the plugin, and starts MPC again even if it fails).
#
#  - The package for this CPU is chosen by `uname -m` (Gen1 and Force: armv7, Gen2: aarch64) and checked against payload.sha256,
#    which is one of the files the stock USB-script check covers, so a swapped package on the stick is refused.
#  - The Synths folder is chosen only when exactly one candidate qualifies: it exists, sits on a read-write mount that is not
#    noexec (a plugin .so must be loadable from it), and MPC already lists it as a plugin location. Otherwise nothing is
#    installed and the result file says what was found. Nothing is guessed.
#  - Needs no network. Leaves <stick>/g2-install-result.txt. With MPC_G2_DRY_RUN=1 it only reports what it would do.
usb=$1; work=$2
log="$work/result.txt"
finish() {
    r=$?
    cp "$log" "$usb/g2-install-result.txt" 2>/dev/null || true
    rm -rf "$work"
    exit "$r"
}
trap finish EXIT
exec > "$log" 2>&1
echo "OpenMPC Plugin Manager G2 install: $(date '+%Y-%m-%d %H:%M:%S')"
if [ -z "${MPC_USB_TEST:-}" ]; then [ "$(id -u)" = 0 ] || { echo "error: not root"; exit 1; }; fi
fail() { echo "error: $*"; echo "Nothing was installed."; exit 1; }

case "${MPC_G2_ARCH:-$(uname -m)}" in
    armv7*) arch=armv7 ;;
    aarch64) arch=aarch64 ;;
    *) fail "this is for MPC OS devices (Gen1 or Force: 32-bit ARM, Gen2: aarch64); this one reports $(uname -m)" ;;
esac
echo "CPU: $arch"

# the package for this CPU, and its checksum from the covered manifest
[ -f "$work/payload.sha256" ] || fail "payload.sha256 is missing from the stick's runtime"
lines=$(grep -c -E "[-]mpc-$arch[.]zip\$" "$work/payload.sha256" || true)
[ "$lines" = 1 ] || fail "expected exactly one $arch package in the manifest, found $lines"
line=$(grep -E "[-]mpc-$arch[.]zip\$" "$work/payload.sha256")
want=${line%% *}
rel=${line#*  }
case "$rel" in g2/*.zip) ;; *) fail "unexpected package path in the manifest: $rel" ;; esac
case "$rel" in *[!A-Za-z0-9._/-]*|*..*) fail "unexpected characters in the package path: $rel" ;; esac
zip="$usb/$rel"
[ -f "$zip" ] || fail "the package is missing from the stick: $rel"
got=$(sha256sum "$zip" | cut -d' ' -f1)
[ "$got" = "$want" ] || fail "the package on the stick does not match its checksum ($rel); copy the stick again"
echo "Package: $rel (checksum ok)"

settings="${MPC_SETTINGS:-$(ls /media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings 2>/dev/null | head -n 1)}"
[ -f "$settings" ] || fail "cannot find MPC.settings on this device"

# the Synths folder: exactly one candidate that exists, is on a rw non-noexec mount, and is a location MPC already lists
mounts="${MPC_MOUNTS:-/proc/mounts}"
mount_ok() {   # the mount holding $1 is read-write and not noexec
    awk -v d="$1" '
        { mp=$2; if (mp=="/" || d==mp || index(d, mp "/")==1) { if (length(mp)>best) { best=length(mp); opts="," $4 "," } } }
        END { if (best && opts ~ /,rw,/ && opts !~ /,noexec,/) exit 0; exit 1 }' "$mounts"
}
registered() { grep -qF "<Location>$1</Location>" "$settings" || grep -qF "<Location>$1/</Location>" "$settings"; }
found=""; n=0
for c in ${MPC_G2_CANDIDATES:-/sdcard/Synths /nvme/Synths /storage/Synths}; do
    why=""
    [ -d "$c" ] || why="does not exist"
    [ -n "$why" ] || mount_ok "$c" || why="is not on a read-write mount that allows executables"
    [ -n "$why" ] || registered "$c" || why="is not a plugin location MPC lists"
    if [ -z "$why" ]; then found="$c"; n=$((n + 1)); echo "Candidate: $c (qualifies)"; else echo "Candidate: $c $why"; fi
done
[ "$n" -ge 1 ] || fail "no internal Synths folder qualifies on this device"
[ "$n" -eq 1 ] || fail "more than one Synths folder qualifies; not choosing between them"
target=$found
echo "Installing into: $target"

# MPC_G2_DRY_RUN=1 stops here: everything above is checked and nothing is changed (a way to see what a device would do)
if [ -n "${MPC_G2_DRY_RUN:-}" ]; then echo "Dry run: would install $rel into $target. Nothing was changed."; exit 0; fi

# the package is unpacked in RAM (/tmp), so check there is room (the plugin is ~330 MB unpacked)
if [ -z "${MPC_USB_TEST:-}" ]; then
    avail=$(df -k "$work" | awk 'NR==2 {print $4}')
    [ "${avail:-0}" -ge 600000 ] || fail "not enough free memory to unpack the package (${avail:-0} KB free, 600000 needed); restart the device and try again"
fi
mkdir -p "$work/pkg"
unzip -q -o "$zip" -d "$work/pkg" || fail "could not unpack the package"
set -- $(find "$work/pkg" -maxdepth 2 -name install.sh)
[ "$#" -eq 1 ] || fail "the package has no single install.sh"
pkgdir=$(dirname "$1")

cp "$settings" "$usb/MPC.settings.backup" 2>/dev/null && echo "MPC.settings copied to the stick (MPC.settings.backup)"
echo "Running the package's installer (it restarts MPC)"
(cd "$pkgdir" && sh ./install.sh -y -t "$target")
rc=$?
if [ "$rc" -eq 0 ]; then echo "Done. OpenMPC Plugin Manager G2 is installed in $target."; else echo "The package's installer failed (status $rc); MPC was started again."; fi
exit "$rc"
