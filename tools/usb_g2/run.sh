#!/bin/sh
# usb_g2/run.sh <stick> <work>: installs the OpenMPC Plugin Manager VST package that is bundled on the stick, then MPC is restarted
# (by the package's own install.sh, which backs up MPC.settings, registers the plugin, and starts MPC again even if it fails).
#
#  - The package for this CPU is chosen by `uname -m` (Gen1 and Force: armv7, Gen2: aarch64) and checked against payload.sha256,
#    which is one of the files the stock USB-script check covers, so a swapped package on the stick is refused.
#  - The Synths folder comes from the device, the same rule the OpenMPC Plugin Manager VST uses: the internal folders MPC lists in
#    MPC.settings (SynthContentLocations) that are Synths folders on a read-write, executable, lasting mount with room (a listed folder
#    that is not there yet counts if its parent is). Two paths to one folder count once. It is chosen only when exactly one qualifies;
#    otherwise nothing is installed and the result file says what was found, and what the device has. Nothing is guessed.
#  - (The internal user data partition, /media/az01-internal, is tried first; the model's own drive only when it cannot take the plugin.)
#  - When MPC lists no internal Synths folder at all (a fresh Force lists only Akai's own content), the one internal drive (/sdcard, /nvme or
#    /storage: its own mount, read-write, executable, lasting, with room) gets a Synths folder, which is added to MPC's list of plugin folders
#    (MPC stopped, MPC.settings backed up first and checked after) so the plugin's skin shows. More than one such drive: nothing is installed.
#  - Needs no network. Leaves <stick>/g2-install-result.txt. With MPC_G2_DRY_RUN=1 it only reports what it would do.
usb=$1; work=$2
log="$work/result.txt"
stopped=0
ctl() {   # stop | start MPC; a test run logs the call instead of touching MPC
    if [ -n "${MPC_USB_TEST:-}" ]; then echo "$1" >> "$STUB_LOG.ctl"; return 0; fi
    svc=acvs; systemctl cat acvs >/dev/null 2>&1 || { systemctl cat inmusic-mpc >/dev/null 2>&1 && svc=inmusic-mpc; }
    systemctl "$1" "$svc"
}
finish() {
    r=$?
    [ "$stopped" = 0 ] || ctl start   # MPC is started again even when the install failed
    cp "$log" "$usb/g2-install-result.txt" 2>/dev/null || true
    rm -rf "$work"
    exit "$r"
}
trap finish EXIT
exec > "$log" 2>&1
echo "OpenMPC Plugin Manager VST install: $(date '+%Y-%m-%d %H:%M:%S')"
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

# the Synths folder: exactly one candidate, taken from the device. MPC lists its plugin folders in MPC.settings (SynthContentLocations);
# the internal ones (a One: /media/az01-internal/Synths, a Force: /sdcard/Synths, Gen2: /nvme or /storage) are candidates, the same rule
# the OpenMPC Plugin Manager VST itself uses. A candidate must be a Synths folder on a read-write, executable, lasting mount with room,
# and a listed folder that does not exist yet is fine when its parent does (the package's installer creates it). Two paths to the same
# folder count once. Removable cards and USB drives are never chosen: a plugin on one disappears with it.
mounts="${MPC_MOUNTS:-/proc/mounts}"
mount_ok() {   # the mount holding $1 is read-write, allows executables and keeps its files; sets mount_why when not
    awk -v d="$1" '
        { mp=$2; if (mp=="/" || d==mp || index(d, mp "/")==1) { if (length(mp)>best) { best=length(mp); opts="," $4 "," ; ty=$3 ; m=mp } } }
        END {
            if (!best) { print "is not on a mounted filesystem"; exit 1 }
            if (opts !~ /,rw,/) { print m " is read-only"; exit 1 }
            if (opts ~ /,noexec,/) { print m " does not allow executables (noexec)"; exit 1 }
            if (ty ~ /^(tmpfs|ramfs|devtmpfs|squashfs|erofs|iso9660|cramfs)$/) { print m " is " ty ", which is not kept across restarts"; exit 1 }
            exit 0 }' "$mounts"
}
free_kb() { df -kP "$1" 2>/dev/null | awk 'NR==2 {print $4}'; }   # -P: without it a long device name wraps the line and $4 is empty (seen on a Force)
registered() { grep -qF "<Location>$1</Location>" "$settings" || grep -qF "<Location>$1/</Location>" "$settings"; }
internal() { for pre in ${MPC_G2_INTERNAL:-/media/az01-internal /sdcard /nvme /storage}; do case "$1" in "$pre"/*) return 0 ;; esac; done; return 1; }
if [ -n "${MPC_G2_CANDIDATES:-}" ]; then list=$(printf '%s\n' $MPC_G2_CANDIDATES)
else
    list=$(grep -o '<Location>[^<]*</Location>' "$settings" | sed 's/<[^>]*>//g' | while read -r l; do l=${l%/}; internal "$l" && echo "$l"; done)
    while read -r l; do
        l=${l%/}; [ -n "$l" ] || continue
        internal "$l" || echo "Listed: $l is not on the internal drive, so it is not used"
    done <<EOF
$(grep -o '<Location>[^<]*</Location>' "$settings" | sed 's/<[^>]*>//g')
EOF
fi
# A scan of every real drive that needs no model names, for the report only (nothing here changes what is installed): a drive is an
# internal candidate when it is a block device that is not on a USB bus, read-write, executable, lasting, with 64 MB free, and not a
# system folder; one line per partition. Reports from many models will say whether this rule could replace the model drives above.
shadow_scan() {
    echo "--- drive scan (for support; not used to choose yet) ---"
    sysblk="${MPC_G2_SYSFS:-/sys/class/block}"; seen_dev=" "
    while read -r dev mp ty opts rest; do
        case "$dev" in /dev/*) ;; *) continue ;; esac
        p=$(printf '%b' "$mp"); name=${dev#/dev/}
        case "$seen_dev" in *" $dev "*) continue ;; esac
        seen_dev="$seen_dev$dev "
        bus=$(readlink -f "$sysblk/$name" 2>/dev/null)
        why=""
        case "$p" in /|/usr|/usr/*|/var|/var/*|/etc|/etc/*|/boot|/boot/*|/factory|/factory/*|/synths|/synths/*|/media/acvs-*|/lib|/lib/*|/proc|/sys|/dev|/run|/tmp) why="is a system folder" ;; esac
        [ -n "$why" ] || case "$dev" in /dev/dm-*|/dev/ram*) why="is not a drive" ;; esac
        if [ -z "$why" ]; then case "$dev" in /dev/loop*)
            # an MPC One or Key keeps its internal drive (/storage) as an image file on /data, mounted through a loop device: it is internal
            # when that file lives on internal storage (not under /media, where external drives are mounted)
            bf=$(cat "$sysblk/$name/loop/backing_file" 2>/dev/null)
            case "$bf" in /data/*|/sdcard/*|/nvme/*|/storage/*) bus="" ;; *) why="is a loop device not backed by an internal file${bf:+ ($bf)}" ;; esac ;;
        esac; fi
        [ -n "$why" ] || case "$bus" in */usb*) why="is on a USB bus (external)" ;; esac
        [ -n "$why" ] || case ",$opts," in *,rw,*) ;; *) why="is read-only" ;; esac
        [ -n "$why" ] || case ",$opts," in *,noexec,*) why="does not allow executables (noexec)" ;; esac
        [ -n "$why" ] || case "$ty" in tmpfs|ramfs|devtmpfs|squashfs|erofs|iso9660|cramfs) why="is $ty, not kept across restarts" ;; esac
        fk=$(free_kb "$p")
        [ -n "$why" ] || [ "${fk:-0}" -ge 65536 ] || why="has too little free space"
        listed=""; registered "$p/Synths" && listed=", MPC lists $p/Synths"

        if [ -z "$why" ]; then echo "  $p ($name, $ty, ${fk:-?} KB free$listed) would qualify"; else echo "  $p ($name, $ty, ${fk:-?} KB free) $why"; fi
    done < "$mounts"
    echo "--- end of drive scan ---"
}
found=""; n=0; seen=" "
while read -r c; do
    [ -n "$c" ] || continue
    why=""; parent=$(dirname "$c"); at=$c
    case "$c" in */Synths) ;; *) why="is not a Synths folder" ;; esac
    [ -n "$why" ] || case "$c" in /usr/*) why="is factory content" ;; esac
    [ -n "$why" ] || case "$c" in *[!A-Za-z0-9._/-]*) why="has characters the installer does not accept" ;; esac
    if [ -z "$why" ]; then
        if [ -d "$c" ]; then at=$c; elif [ -d "$parent" ]; then at=$parent; else why="does not exist, and neither does its parent folder"; fi
    fi
    [ -n "$why" ] || registered "$c" || why="is not a plugin location MPC lists"   # a skin is drawn only from a listed location
    [ -n "$why" ] || { r=$(mount_ok "$at") || why=$r; }
    if [ -z "$why" ]; then
        free=$(free_kb "$at")
        [ "${free:-0}" -ge 65536 ] || why="has too little free space (${free:-unknown} KB free; the plugin manager needs about 40 MB, and 64 MB is required)"
    fi
    if [ -z "$why" ]; then
        key=$(stat -L -c '%d:%i' "$at" 2>/dev/null)
        [ -d "$c" ] || key="$key/Synths"
        case "$seen" in *" $key "*) echo "Candidate: $c (the same folder as another candidate)"; continue ;; esac
        seen="$seen$key "
    fi
    if [ -z "$why" ]; then found="$c"; n=$((n + 1)); [ -d "$c" ] && echo "Candidate: $c (qualifies)" || echo "Candidate: $c (qualifies; MPC lists it and it will be created)"; else echo "Candidate: $c $why"; fi
done <<EOF
$list
EOF
if [ "$n" -lt 1 ]; then
    # what a person helping needs to see, since nothing was found
    echo "--- what this device has (for support) ---"
    echo "plugin locations MPC lists:"; grep -o "<Location>[^<]*</Location>" "$settings" 2>/dev/null | sed 's/<[^>]*>//g; s/^/  /' || true
    echo "MPC.settings: $settings"
    echo "mounts that look like internal storage (device, mount point, type, options, free space, folder id):"
    grep -E " ${MPC_G2_DIAG_MOUNTS:-/(sdcard|nvme|storage|data|synths|media[^ ]*|content)} " "$mounts" 2>/dev/null | while read -r dev mp ty opts rest; do
        p=$(printf '%b' "$mp"); echo "  $dev $mp $ty $(printf %s "$opts" | cut -d, -f1-3) free=$(free_kb "$p")KB id=$(stat -L -c '%d:%i' "$p" 2>/dev/null)"
    done || true
    echo "folders: $(ls -d /sdcard/Synths /nvme/Synths /storage/Synths /media/*/Synths 2>/dev/null | tr '\n' ' ')"
    echo "--- end ---"
fi
is_mountpoint() { awk -v d="$1" '$2 == d {f = 1} END {exit !f}' "$mounts"; }
register=0
# try_drives <drive>...: how many of these are usable internal drives (fn) and the Synths folder of the last one (fb)
try_drives() {
    fn=0; fb=""
    for drive in "$@"; do
        why=""
        [ -d "$drive" ] || why="is not there"
        [ -n "$why" ] || is_mountpoint "$drive" || why="is not a drive of its own"
        [ -n "$why" ] || { r=$(mount_ok "$drive") || why=$r; }
        if [ -z "$why" ]; then
            free=$(free_kb "$drive")
            [ "${free:-0}" -ge 65536 ] || why="has too little free space (${free:-unknown} KB free; the plugin manager needs about 40 MB, and 64 MB is required)"
        fi
        if [ -z "$why" ]; then fn=$((fn + 1)); fb="$drive/Synths"; echo "Internal drive: $drive (usable; MPC lists no Synths folder on it)"; else echo "Internal drive: $drive $why"; fi
    done
}
if [ "$n" -lt 1 ] && [ -z "${MPC_G2_CANDIDATES:-}" ]; then
    # MPC lists no usable internal Synths folder. The conventional internal drive is the one place a plugin can go and still show its skin once
    # it is listed, so: exactly one such drive, as a mount of its own (a stub folder on the root filesystem is not a drive), read-write,
    # executable, lasting, with room. The internal user data partition comes first (/media/az01-internal, the user space, where an MPC One keeps
    # its plugins). Only when it is not usable does the model's own drive count (a Force or Live /sdcard, Gen2 /nvme or /storage). A Force's
    # /sdcard is the system partition and is meant to hold little free space; where both are usable the first tier wins and the second is not
    # even looked at.
    try_drives ${MPC_G2_DRIVES2:-/media/az01-internal}
    if [ "$fn" -eq 0 ]; then
        echo "The internal user space is not usable; trying the model's own drive"
        try_drives ${MPC_G2_DRIVES:-/sdcard /nvme /storage}
    fi
    if [ "$fn" -eq 1 ]; then
        grep -q '</SynthContentLocations>' "$settings" || fail "MPC.settings has no list of plugin folders (SynthContentLocations) to add $fb to; not editing it"
        found=$fb; n=1; register=1
        echo "Will create $fb and add it to MPC's list of plugin folders"
    fi
fi
shadow_scan
[ "$n" -ge 1 ] || fail "no internal Synths folder qualifies on this device"
[ "$n" -eq 1 ] || fail "more than one Synths folder qualifies; not choosing between them"
target=$found
echo "Installing into: $target"

# MPC_G2_DRY_RUN=1 stops here: everything above is checked and nothing is changed (a way to see what a device would do)
if [ -n "${MPC_G2_DRY_RUN:-}" ]; then
    [ "$register" = 0 ] || echo "Dry run: would also add $target to MPC's list of plugin folders in $settings (backed up first)."
    echo "Dry run: would install $rel into $target. Nothing was changed."; exit 0
fi

# the package is unpacked in RAM (/tmp), so check there is room (it is ~40 MB unpacked; 150 MB leaves a wide margin)
if [ -z "${MPC_USB_TEST:-}" ]; then
    avail=$(free_kb "$work")
    [ "${avail:-0}" -ge 150000 ] || fail "not enough free memory to unpack the package (${avail:-0} KB free, 150000 needed); restart the device and try again"
fi
mkdir -p "$work/pkg"
unzip -q -o "$zip" -d "$work/pkg" || fail "could not unpack the package"
set -- $(find "$work/pkg" -maxdepth 2 -name install.sh)
[ "$#" -eq 1 ] || fail "the package has no single install.sh"
pkgdir=$(dirname "$1")

cp "$settings" "$usb/MPC.settings.backup" 2>/dev/null && echo "MPC.settings copied to the stick (MPC.settings.backup)"
if [ "$register" = 1 ]; then
    # MPC overwrites its settings when it stops, so it is stopped first; the package's installer then runs with -n (it leaves MPC
    # stopped) and MPC is started again when this script ends, whatever happens.
    ctl stop; stopped=1
    if [ -z "${MPC_USB_TEST:-}" ]; then
        i=0; while pidof MPC >/dev/null && [ "$i" -lt 30 ]; do sleep 1; i=$((i + 1)); done
        ! pidof MPC >/dev/null || fail "MPC did not stop; nothing was changed"
    fi
    bak="$settings.bak-g2loc-$(date +%Y%m%d-%H%M%S)"
    cp "$settings" "$bak" || fail "could not back up MPC.settings; nothing was changed"
    awk -v loc="$target" '!d && sub(/<\/SynthContentLocations>/, "<Location>" loc "</Location></SynthContentLocations>") {d = 1} {print}' "$settings" > "$settings.new"
    ok=1
    [ "$(grep -c -F "<Location>$target</Location>" "$settings.new")" = 1 ] || ok=0
    grep -q '<PROPERTIES' "$settings.new" && grep -q '</PROPERTIES>' "$settings.new" || ok=0
    if [ "$ok" = 1 ] && command -v python3 >/dev/null 2>&1; then
        python3 -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$settings.new" 2>/dev/null || ok=0
    fi
    if [ "$ok" = 1 ]; then cat "$settings.new" > "$settings" && echo "Added $target to MPC's plugin folders (MPC.settings backed up as $bak)"; fi
    rm -f "$settings.new"
    [ "$ok" = 1 ] || fail "the edited MPC.settings did not check out, so it was left as it was"
fi
echo "Running the package's installer$( [ "$register" = 1 ] || echo " (it restarts MPC)")"
if [ "$register" = 1 ]; then (cd "$pkgdir" && sh ./install.sh -y -n -t "$target"); else (cd "$pkgdir" && sh ./install.sh -y -t "$target"); fi
rc=$?
if [ "$rc" -eq 0 ]; then echo "Done. OpenMPC Plugin Manager VST is installed in $target."; else echo "The package's installer failed (status $rc); MPC was started again."; fi
exit "$rc"
