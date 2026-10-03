#!/bin/sh
# mpc-drum-pad-patch.sh: give selected plugins MPC's 16-pad DRUM layout on the Force / MPC (MPC OS 3.9.1.2 only).
#
# ADVANCED AND OPT-IN. This changes Akai's factory program, /usr/bin/MPC, on the device. Read the warnings below.
#
#   sh mpc-drum-pad-patch.sh status       what state the device is in (changes nothing)
#   sh mpc-drum-pad-patch.sh install      patch it (asks you to type PATCH first)
#   sh mpc-drum-pad-patch.sh uninstall    put the original bytes back
#   sh mpc-drum-pad-patch.sh help
# Run it ON the device as root (ssh root@<device-ip>), after copying the file there (scp).
#
# What it does: the stock MPC treats only Akai's own "DrumSynth:Multi" as a drum instrument (16 pads, but only 8 lit and
# working). The patch (a) makes MPC treat any plugin whose name is in the table below as a drum instrument, (b) gives the
# drum layout 16 pads instead of 8, and (c) lights all 16 pads (red). Pad n then sends MIDI note n-1. Akai's DrumSynth Multi
# keeps its layout but also shows 16 lit pads. Nothing else changes.
#
# Plugins in the table (@@COUNT@@): @@NAMES@@
#
# WARNINGS
#  - It modifies the factory MPC OS. Do it only if you are comfortable with that; you use it at your own risk.
#  - It works ONLY on MPC OS 3.9.1.2, checked by the exact checksum of /usr/bin/MPC. On anything else it refuses.
#  - A firmware update replaces /usr/bin/MPC and removes the patch. Run this again after updating (it will refuse until
#    this project supports the new build).
#  - Installing stops and restarts MPC: save your project first.
#  - Before changing anything it saves the full original MPC (112 MB) and the original bytes to /sdcard/MPC-backup, and
#    checks the result by checksum; if that fails it restores the original by itself. `uninstall` restores them.
#  - Nothing of Akai's is in this file: only the changed bytes and checksums. The device uses its own copy.
#  - Not affiliated with Akai Professional / inMusic.
#
# Version @@VERSION@@. Source and plugin-name table: see the README of the repository this came from.
set -u
STOCK_MD5=592eebc8e1ce0797dc8c98e7002143b8
PATCHED_MD5=@@PATCHED_MD5@@
V1_MD5=10a7d0bb4e5fb66ffaa6b2c6a001eef2     # the earlier Machinedrum-only patch (mpc-vst-machinedrum release/mpc_patch)
V2_MD5=730c959f317ea405c472f273342bc235     # this patch with the name table of 2026-10-01 (it still said "TR-Kit")
V3_MD5=f899e581cba179a831212083f9a55ae0     # this patch with the name table of 2026-10-02 (before Machinemodule and Lucky Dip)
BK=${MPC_PATCH_BACKUP:-/sdcard/MPC-backup}
REG=$BK/orig-regions.txt
FULL=$BK/MPC-3.9.1.2.orig
MNT=/tmp/mpc-patch-root
TEST=${MPC_PATCH_TEST:-}                      # set to a file path to run against a copy of the binary (no mounts, no restart)

PATCH_DATA='@@PATCH@@'

die() { echo "ERROR: $*" >&2; exit 1; }
md5() { md5sum "$1" | cut -d' ' -f1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

if [ -n "$TEST" ]; then F=$TEST; else F=$MNT/usr/bin/MPC; fi

state_of() {   # md5 -> word
    case "$1" in "$STOCK_MD5") echo stock ;; "$PATCHED_MD5") echo patched ;; "$V1_MD5"|"$V2_MD5"|"$V3_MD5") echo old-patch ;; *) echo unknown ;; esac
}

need_root_device() {
    [ -n "$TEST" ] && return 0
    [ "$(id -u)" = 0 ] || die "run as root on the device"
    case "$(uname -m)" in armv7*) ;; *) die "this is for 32-bit ARM MPC OS devices; this one is $(uname -m)" ;; esac
    command -v systemctl >/dev/null || die "systemctl not found (not an MPC OS device?)"
    [ -f /usr/bin/MPC ] || die "/usr/bin/MPC not found"
}

open_root() {
    [ -n "$TEST" ] && return 0
    # the real factory file, through a bind mount of the root, so a MockbaMod overlay on /usr cannot hide it
    mkdir -p "$MNT"; mountpoint -q "$MNT" 2>/dev/null || mount --bind / "$MNT" || die "bind mount failed"
    for u in /media/*/system/usr/overlay /media/*/*/system/usr/overlay; do
        [ -e "$u/bin/MPC" ] && die "an MPC exists in the MockbaMod overlay ($u/bin/MPC); remove it first"
    done
    return 0
}

writable() {   # $1 = rw | ro
    [ -n "$TEST" ] && return 0
    if [ "$1" = rw ]; then
        systemctl stop acvs; mount -o remount,rw / && mount -o remount,rw,bind "$MNT" || { systemctl start acvs; die "could not remount read-write"; }
    else
        sync; mount -o remount,ro,bind "$MNT"; mount -o remount,ro /; umount "$MNT"
        systemctl start acvs; sleep 5
        pidof MPC >/dev/null && echo "MPC is running" || echo "WARNING: MPC is not running; run: sh $0 uninstall"
    fi
}

hex_to_bytes() {
    h=$1
    case $h in ''|*[!0-9a-fA-F]*) echo "ERROR: bad hex in a patch line" >&2; return 1 ;; esac
    [ $(( ${#h} % 2 )) = 0 ] || { echo "ERROR: odd-length hex in a patch line" >&2; return 1; }
    while [ -n "$h" ]; do r=${h#??}; c=${h%"$r"}; printf "\\$(printf %03o $((0x$c)))"; h=$r; done
}
write_regions() {   # stdin: "<hex offset> <hex bytes>" lines (a stray carriage return is ignored)
    while read -r o h; do
        o=$(printf %s "$o" | tr -d '\r'); h=$(printf %s "$h" | tr -d '\r')
        [ -n "$o" ] || continue
        hex_to_bytes "$h" | dd bs=1 seek=$((0x$o)) 1<>"$F" 2>/dev/null
    done
}
patch_lines() { echo "$PATCH_DATA" | grep -v '^[[:space:]]*$'; }
save_orig() {
    : > "$REG"
    patch_lines | while read -r o h; do
        echo "$o $(dd if="$F" bs=1 skip=$((0x$o)) count=$((${#h}/2)) 2>/dev/null | od -b -v | awk '{for(i=2;i<=NF;i++)printf "%02x",substr($i,1,1)*64+substr($i,2,1)*8+substr($i,3,1)}')" >> "$REG"
    done
}

restore_stock() {   # needs the file writable
    [ -f "$REG" ] && write_regions < "$REG"
    if [ "$(md5 "$F")" != "$STOCK_MD5" ] && [ -f "$FULL" ]; then
        echo "restoring from the full backup"; cat "$FULL" > "$F"
    fi
    [ "$(md5 "$F")" = "$STOCK_MD5" ]
}

cmd_status() {
    need_root_device; open_root
    cur=$(md5 "$F"); st=$(state_of "$cur")
    echo "MPC checksum: $cur"
    case "$st" in
        stock) echo "State: stock MPC OS 3.9.1.2, not patched." ;;
        patched) echo "State: PATCHED (plugin names: @@NAMES@@)." ;;
        old-patch) echo "State: patched with an earlier version of this patch (Machinedrum-only, or an older name table); 'install' upgrades it." ;;
        *) echo "State: not MPC OS 3.9.1.2 (or modified some other way). This script will not touch it." ;;
    esac
    [ -f "$FULL" ] && echo "Backup: $FULL present" || echo "Backup: no full backup in $BK"
    [ -f "$REG" ] && echo "Original bytes: $REG present" || echo "Original bytes: not saved yet"
}

cmd_install() {
    need_root_device; open_root
    cur=$(md5 "$F"); st=$(state_of "$cur")
    case "$st" in
        patched) echo "Already patched. Nothing to do."; exit 0 ;;
        stock|old-patch) ;;
        *) die "this is not MPC OS 3.9.1.2 (checksum $cur). Refusing; nothing was changed." ;;
    esac
    cat <<EOF

 This modifies the FACTORY MPC OS (/usr/bin/MPC) on this device, for MPC OS 3.9.1.2 only.
  - Plugins that get the 16-pad drum layout: @@NAMES@@
  - MPC will be stopped and started again: save your project first.
  - A firmware update replaces the file and removes the patch.
  - The full original MPC (112 MB) and the original bytes are saved to $BK first.
  - Undo any time with: sh $0 uninstall
  - You use this at your own risk. It is not an Akai product.
EOF
    if [ "$st" = old-patch ]; then echo " - This device has an earlier version of this patch; it is replaced by this one."; fi
    printf "\nType PATCH to continue: "
    if [ -n "$TEST" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
    [ "$a" = PATCH ] || die "cancelled; nothing was changed"
    mkdir -p "$BK" || die "cannot create $BK"
    if [ "$st" = old-patch ]; then
        [ -f "$REG" ] || die "the earlier patch's saved original bytes ($REG) are missing; cannot upgrade safely. Restore stock firmware first."
        echo "step 1/2: undoing the earlier patch"; writable rw; restore_stock || { writable ro; die "could not restore stock; run uninstall"; }
        echo "stock restored"; writable ro; open_root
        cur=$(md5 "$F"); [ "$cur" = "$STOCK_MD5" ] || die "device is not stock after the undo (checksum $cur)"
    fi
    if [ ! -f "$FULL" ] || [ "$(md5 "$FULL")" != "$STOCK_MD5" ]; then
        avail=$(df -k "$BK" | awk 'NR==2{print $4}'); [ "${avail:-0}" -gt 140000 ] || die "need about 140 MB free in $BK for the backup"
        cat "$F" > "$FULL" && [ "$(md5 "$FULL")" = "$STOCK_MD5" ] || die "backup to $FULL failed; nothing was changed"
    fi
    save_orig; [ -s "$REG" ] || die "could not save the original bytes"
    echo "backup: $FULL and $REG"
    writable rw
    patch_lines | write_regions
    if [ "$(md5 "$F")" = "$PATCHED_MD5" ]; then
        echo "patched OK"
    else
        echo "ERROR: checksum mismatch after patching; restoring the original"
        restore_stock && echo "restored stock MPC" || echo "ERROR: restore failed; copy $FULL over /usr/bin/MPC"
    fi
    writable ro
}

cmd_uninstall() {
    need_root_device; open_root
    cur=$(md5 "$F"); st=$(state_of "$cur")
    case "$st" in
        stock) echo "Already stock. Nothing to do."; exit 0 ;;
        patched|old-patch) ;;
        *) die "MPC is neither stock nor a build this script made (checksum $cur); not touching it" ;;
    esac
    [ -f "$REG" ] || [ -f "$FULL" ] || die "no backup found in $BK; cannot restore"
    writable rw
    if restore_stock; then echo "restored stock MPC"; else echo "ERROR: checksum is not stock; copy $FULL over /usr/bin/MPC"; fi
    writable ro
}

case "${1:-help}" in
    status) cmd_status ;;
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
