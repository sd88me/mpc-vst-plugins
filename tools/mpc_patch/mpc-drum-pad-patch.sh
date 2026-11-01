#!/bin/sh
# mpc-drum-pad-patch.sh: give selected plugins MPC's 16-pad DRUM layout on the Force (MPC OS 3.9.1.2), on Gen1 MPCs (3.10.0), and on Gen2
# devices such as the MPC Live III (aarch64; MPC OS 3.9.1 and the 3.10.0 kit; see "Gen2" below).
#
# ADVANCED AND OPT-IN. This changes Akai's factory program, /usr/bin/MPC, on the device. Read the warnings below.
#
#   sh mpc-drum-pad-patch.sh status       what state the device is in (changes nothing)
#   sh mpc-drum-pad-patch.sh install      patch it (asks you to type PATCH first)
#   sh mpc-drum-pad-patch.sh install --confirmed   the same without the question (for a tool that already asked you)
#   sh mpc-drum-pad-patch.sh uninstall    put the original bytes back (also from a build this script does not know, if its
#                                         saved full backup is the stock program: it asks you to type RESTORE first)
#   sh mpc-drum-pad-patch.sh reapply     Gen2 only: after a reboot, switch the patched copy back on (add --restart to restart MPC)
#   sh mpc-drum-pad-patch.sh help
# Gen2: the read-only system is not changed. A patched COPY of MPC goes to /data/mpc-drumpad and a drop-in in /run makes MPC use
# it, until the next reboot (then `reapply`, or `install` again). `uninstall` removes the copy and the drop-in.
# Run it ON the device as root (ssh root@<device-ip>), after copying the file there (scp).
#
# What it does: the stock MPC treats only Akai's own "DrumSynth:Multi" as a drum instrument (16 pads, but only 8 lit and
# working). The patch (a) makes MPC treat any plugin whose name is in the table below as a drum instrument, (b) gives the
# drum layout 16 pads instead of 8, and (c) lights all 16 pads (red). Pad n then sends MIDI note n-1. Akai's DrumSynth Multi
# keeps its layout but also shows 16 lit pads. Nothing else changes.
#
# Plugins in the table (8): Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip
#
# WARNINGS
#  - It modifies the factory MPC OS. Do it only if you are comfortable with that; you use it at your own risk.
#  - It works ONLY on the builds it knows (Force / MPC OS 3.9.1.2, Gen1 MPC OS 3.10.0, Gen2 3.9.1 and 3.10.0), checked by the exact
#    checksum of /usr/bin/MPC. On anything else it refuses.
#  - A firmware update replaces /usr/bin/MPC and removes the patch. Run this again after updating (it will refuse until
#    this project supports the new build).
#  - Installing stops and restarts MPC: save your project first.
#  - Before changing anything it saves the full original MPC (about 115 MB) and the original bytes to /sdcard/MPC-backup, and
#    checks the result by checksum; if that fails it restores the original by itself. `uninstall` restores them.
#  - Nothing of Akai's is in this file: only the changed bytes and checksums. The device uses its own copy.
#  - Not affiliated with Akai Professional / inMusic.
#
# Version 8. Source and plugin-name table: see the README of the repository this came from.
set -u
STOCK_MD5=592eebc8e1ce0797dc8c98e7002143b8
PATCHED_MD5=7cf96599ec61b1079688f253f3b65b9f
V1_MD5=10a7d0bb4e5fb66ffaa6b2c6a001eef2     # the earlier Machinedrum-only patch (mpc-vst-machinedrum release/mpc_patch)
V2_MD5=730c959f317ea405c472f273342bc235     # this patch with the name table of 2026-10-01 (it still said "TR-Kit")
V3_MD5=f899e581cba179a831212083f9a55ae0     # this patch with the name table of 2026-10-02 (before Machinemodule and Lucky Dip)
BK=${MPC_PATCH_BACKUP:-/sdcard/MPC-backup}
REG=$BK/orig-regions.txt
FULL=$BK/MPC-3.9.1.2.orig
MNT=/tmp/mpc-patch-root
TEST=${MPC_PATCH_TEST:-}                      # set to a file path to run against a copy of the binary (no mounts, no restart)

PATCH_DATA='2494954 002090e500c09fe50cf08fe0cc695e02
4a7b330 00c09fe50cf08fe04476df01
2494bb4 00c09fe50cf08fe040dd3d04
6872900 0040a0e3040095e50410a0e128209fe51cc09fe50cc08fe03cff2fe1014084e2100054e3f6ffff1a040095e504c09fe50cf08fe04c05bffba822c2fb00007f00
6872980 04402de564108fe20040d1e5000054e30f00000a0230a0e10140d3e401c0d1e40c0054e10400001a000054e3f9ffff1a04409de40100a0e31eff2fe100005ce3f0ffff0a01c0d1e400005ce3fcffff1aecffffea04409de408109fe501108fe004c09fe50cf08fe07cfd23fe00600bfa4d616368696e656472756d204d6f64756c65004d616368696e656d6f64756c6500365736003857380043572d3738003957390054522d4d5043004c75636b79204469700000000000
18ff260 10
18ffbd8 10
18ffc84 10
1900e04 10
1900e98 10
19016fc 10'

# MPC Gen1 (Live / One / X / Key; armv7 like the Force, same in-place method): MPC OS 3.10.0. Picked by the checksum of the MPC found.
STOCK_G1_310=b6cc8e7a398bdf6c3fd8f7176eecd3ee
PATCHED_G1_310=496c22afe2f57f5c583072a02d754f07
PATCH_DATA_G1_310='6c7c730 0040a0e3040095e50410a0e17f28a0e31cc09fe50cc08fe03cff2fe1014084e2100054e3f6ffff1a040095e504c09fe50cf08fe0549ea8fb04c0bdfb
6c7c76c 04402de564108fe20040d1e5000054e30f00000a0230a0e10140d3e401c0d1e40c0054e10400001a000054e3f9ffff1a04409de40100a0e31eff2fe100005ce3f0ffff0a01c0d1e400005ce3fcffff1aecffffea04409de408109fe501108fe004c09fe50cf08fe0f0560cfe3cf2ccf94d616368696e656472756d204d6f64756c65004d616368696e656d6f64756c6500365736003857380043572d3738003957390054522d4d5043004c75636b79204469700000
28584e4 00c09fe50cf08fe07c424204
28584e0 002090e5
2858740 00c09fe50cf08fe0e43f4204
1193600 10
1194100 10
11942c0 10
11954bc 10
1195550 10
11958a8 10'
pick_build() {   # $1 = md5 of /usr/bin/MPC: switch the globals to the Gen1 build when it is one (else the Force's 3.9.1.2 stay)
    case "$1" in
        "$STOCK_G1_310"|"$PATCHED_G1_310") STOCK_MD5=$STOCK_G1_310; PATCHED_MD5=$PATCHED_G1_310; PATCH_DATA=$PATCH_DATA_G1_310
            FULL=$BK/MPC-3.10.0-Gen1.orig; BUILD="Gen1 MPC OS 3.10.0" ;;
    esac
}
BUILD="MPC OS 3.9.1.2 (Force, Gen1 3.9.1.2)"

die() { echo "ERROR: $*" >&2; exit 1; }
md5() { md5sum "$1" | cut -d' ' -f1; }
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

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
    need_root_device
    was_mounted=0; [ -z "$TEST" ] && mountpoint -q "$MNT" 2>/dev/null && was_mounted=1
    open_root
    cur=$(md5 "$F"); pick_build "$cur"; st=$(state_of "$cur")
    [ -z "$TEST" ] && [ $was_mounted = 0 ] && umount "$MNT" 2>/dev/null   # status looked only: do not leave the bind mount of / behind
    echo "MPC checksum: $cur"
    case "$st" in
        stock) echo "State: stock $BUILD, not patched." ;;
        patched) echo "State: PATCHED (plugin names: Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip)." ;;
        old-patch) echo "State: patched with an earlier version of this patch (Machinedrum-only, or an older name table); 'install' upgrades it." ;;
        *) echo "State: not a build this script supports (MPC OS 3.9.1.2 on a Force; Gen1 MPC OS 3.10.0), or a build this script did not make. 'install' will not touch it."
           [ -f "$FULL" ] && echo "       A full backup from an earlier install is in $BK: 'uninstall' can put the stock program back from it (it checks the backup first)." ;;
    esac
    [ -f "$FULL" ] && echo "Backup: $FULL present" || echo "Backup: no full backup in $BK"
    [ -f "$REG" ] && echo "Original bytes: $REG present" || echo "Original bytes: not saved yet"
    # the last line is for programs (the installer app): state=stock|patched|old-patch|unsupported, supported=1 when install may run
    sup=1; [ "$st" = unknown ] && { sup=0; st=unsupported; }
    bk=0; { [ -f "$FULL" ] || [ -f "$REG" ]; } && bk=1
    echo "STATE state=$st supported=$sup backup=$bk checksum=$cur"
}

cmd_install() {   # $1: --confirmed skips the typed question; a caller that shows the same warnings and asks for the word itself passes it
    need_root_device; open_root
    cur=$(md5 "$F"); pick_build "$cur"; st=$(state_of "$cur")
    case "$st" in
        patched) echo "Already patched. Nothing to do."; exit 0 ;;
        stock|old-patch) ;;
        *) die "this is not a supported MPC OS build (checksum $cur). Refusing; nothing was changed." ;;
    esac
    cat <<EOF

 This modifies the FACTORY MPC OS (/usr/bin/MPC) on this device, for $BUILD only.
  - Plugins that get the 16-pad drum layout: Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip
  - MPC will be stopped and started again: save your project first.
  - A firmware update replaces the file and removes the patch.
  - The full original MPC (about 115 MB) and the original bytes are saved to $BK first.
  - Undo any time with: sh $0 uninstall
  - You use this at your own risk. It is not an Akai product.
EOF
    if [ "$st" = old-patch ]; then echo " - This device has an earlier version of this patch; it is replaced by this one."; fi
    if [ "${1:-}" = --confirmed ]; then
        echo "Confirmed by the caller."
    else
        printf "\nType PATCH to continue: "
        if [ -n "$TEST" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = PATCH ] || die "cancelled; nothing was changed"
    fi
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

# A build this script does not know (for example an earlier development version of the patch). It is only ever replaced by the full
# backup an earlier install saved, and only if that backup's checksum is the stock program's; the result is checked the same way.
restore_unknown() {
    cur=$1
    [ -f "$FULL" ] || die "MPC is neither stock nor a build this script made (checksum $cur) and there is no full backup in $BK; not touching it"
    echo "MPC is a build this script does not know (checksum $cur). Checking the saved full backup..."
    [ "$(md5 "$FULL")" = "$STOCK_MD5" ] || die "the full backup $FULL is not the stock MPC (checksum $(md5 "$FULL")); not touching anything"
    echo "The backup is the stock MPC program. It will replace /usr/bin/MPC (about 115 MB), then MPC restarts: save your project first."
    if [ "${2:-}" != --confirmed ]; then
        printf "Type RESTORE to continue: "
        if [ -n "$TEST" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = RESTORE ] || die "cancelled; nothing was changed"
    fi
    writable rw
    cat "$FULL" > "$F"
    if [ "$(md5 "$F")" = "$STOCK_MD5" ]; then echo "restored stock MPC from the full backup"
    else echo "ERROR: checksum is not stock; copy $FULL over /usr/bin/MPC"; fi
    writable ro
}

cmd_uninstall() {   # $1: --confirmed skips the typed question that a restore from the full backup asks
    need_root_device; open_root
    cur=$(md5 "$F"); pick_build "$cur"; st=$(state_of "$cur")
    case "$st" in
        stock) echo "Already stock. Nothing to do."; exit 0 ;;
        patched|old-patch) ;;
        *) restore_unknown "$cur" "${1:-}"; return ;;
    esac
    [ -f "$REG" ] || [ -f "$FULL" ] || die "no backup found in $BK; cannot restore"
    writable rw
    if restore_stock; then echo "restored stock MPC"; else echo "ERROR: checksum is not stock; copy $FULL over /usr/bin/MPC"; fi
    writable ro
}

# ---------------------------------------------------------------------------------------------------------------------
# Gen2 (aarch64: MPC Live III and kin; MPC OS 3.9.1 and the 3.10.0 kit). The root filesystem there is read-only (dm-verity), so
# /usr/bin/MPC is never changed. A patched COPY is made under $G2 (from the MPC that system would run: the root's, or the
# 3.10 kit's) and a systemd drop-in in /run bind-mounts it over /usr/bin/MPC for the acvs service. /run is cleared by a
# reboot: `reapply` puts the drop-in back (a boot stick can call it), `uninstall` removes everything.
# ---------------------------------------------------------------------------------------------------------------------
G2=${MPC_G2_DIR:-/data/mpc-drumpad}
G2_DD=${MPC_G2_DROPIN_DIR:-/run/systemd/system/acvs.service.d}
G2_DROPIN=$G2_DD/94-mpc-drumpad.conf      # sorts before the 3.10 kit's 95-mpc310.conf: systemd keeps the FIRST bind of a path
G2_ROOTMPC=${MPC_G2_ROOTMPC:-/usr/bin/MPC}
G2_TEST=${MPC_G2_TEST:-}                  # set: no systemctl, no running-MPC check (offline tests)
STOCK_G2_391=a7ace6a9993df33afeae50571755bbf9
STOCK_G2_310=15a664f6b6ae591c8b78baae8b376f02
PATCHED_G2_391=0c819376e5a72803ec97c5c8b582f36e
PATCHED_G2_310=b6a49a4f20055cf0aa937e55acd9856f
PATCH_DATA_G2_391='4b3b908 f51300f915028052800640f9a1060051e20fa052a41e7597b506007161ffff54800640f963d27517
4b3b930 020040f9a10a00f021f03c9124004039a4010034e30302aa64144038251440389f00056b8100005484ffff3520008052c0035fd6c5feff3425144038e5ffff35f3ffff17e101009021e03a91314d1317
4c92f3c 4d616368696e656472756d204d6f64756c65004d616368696e656d6f64756c6500365736003857380043572d3738003957390054522d4d5043004c75636b79204469700000
28b00a4 232e8a14
28b00a8 1f2003d51f2003d5
28b0290 9e2d8a14
1e42ba8 01028052
1e43500 01028052
1e435ac 01028052
1e445ec 01028052
1e4468c 01028052
1e44eac 01028052'
PATCH_DATA_G2_310='79a71a0 f51300f915028052800640f9a1060051e20fa052d6fec496b506007161ffff54800640f9f597c916
79a71c8 020040f9010000902160089124004039a4010034e30302aa64144038251440389f00056b8100005484ffff3520008052c0035fd6c5feff3425144038e5ffff35f3ffff1741a1feb021e00391736e5a16
79a7218 4d616368696e656472756d204d6f64756c65004d616368696e656d6f64756c6500365736003857380043572d3738003957390054522d4d5043004c75636b79204469700000
2c0cf84 91683615
2c0cf88 1f2003d51f2003d5
2c0d170 0c683615
1795268 01028052
1795d08 01028052
1795ec0 01028052
1796f8c 01028052
179702c 01028052
179733c 01028052'

g2_sysd() { [ -n "$G2_TEST" ] || systemctl "$@"; }
g2_source() {   # the MPC this system runs when we are not installed: a bind-mount drop-in of someone else's, else the root's
    for f in "$G2_DD"/*.conf; do
        [ -f "$f" ] || continue
        [ "$f" = "$G2_DROPIN" ] && continue
        p=$(grep -o '[^ =]*:/usr/bin/MPC' "$f" 2>/dev/null | head -n 1); p=${p%:/usr/bin/MPC}
        [ -n "$p" ] && { echo "$p"; return; }
    done
    echo "$G2_ROOTMPC"
}
g2_pick() {   # $1 = stock md5 -> sets G2_ID, G2_STOCK, G2_PATCHED, G2_DATA; returns 1 when unknown
    case "$1" in
        "$STOCK_G2_391") G2_ID=3.9.1; G2_STOCK=$STOCK_G2_391; G2_PATCHED=$PATCHED_G2_391; G2_DATA=$PATCH_DATA_G2_391 ;;
        "$STOCK_G2_310") G2_ID=3.10.0; G2_STOCK=$STOCK_G2_310; G2_PATCHED=$PATCHED_G2_310; G2_DATA=$PATCH_DATA_G2_310 ;;
        *) return 1 ;;
    esac
}
g2_running_md5() { [ -n "$G2_TEST" ] && { [ -f "$G2_DROPIN" ] && md5 "$G2/MPC"; return 0; }; p=$(pidof MPC | cut -d' ' -f1); [ -n "$p" ] && md5 "/proc/$p/exe"; }
g2_write_dropin() {
    mkdir -p "$G2_DD" && printf '[Service]\n# 16-pad drum layout (mpc-drum-pad-patch.sh): a patched copy of MPC over /usr/bin/MPC. Remove with: sh mpc-drum-pad-patch.sh uninstall\nBindReadOnlyPaths=%s/MPC:/usr/bin/MPC\n' "$G2" > "$G2_DROPIN.new" && mv "$G2_DROPIN.new" "$G2_DROPIN"
}
g2_wait_running() {   # $1 = md5 expected for the running MPC; true when it shows up within ~25 s
    [ -n "$G2_TEST" ] && return 0
    n=0; while [ $n -lt 12 ]; do sleep 2; [ "$(g2_running_md5)" = "$1" ] && return 0; n=$((n+1)); done; return 1
}

g2_need() {
    [ -n "$G2_TEST" ] || { [ "$(id -u)" = 0 ] || die "run as root on the device"; command -v systemctl >/dev/null || die "systemctl not found (not an MPC OS device?)"; }
    SRC=$(g2_source); [ -f "$SRC" ] || die "$SRC not found"
    SRC_MD5=$(md5 "$SRC")
    g2_pick "$SRC_MD5" && return 0
    G2_ID=; return 1
}

g2_cmd_status() {
    g2_need || true
    echo "MPC this system runs: $SRC (checksum $SRC_MD5)"
    prepared=0; [ -f "$G2/MPC" ] && [ -f "$G2/STOCK" ] && [ "$(cat "$G2/STOCK")" = "$SRC_MD5" ] && prepared=1
    if [ -z "$G2_ID" ]; then
        st=unsupported; sup=0; echo "State: not a Gen2 build this script knows (MPC OS 3.9.1 or 3.10.0). 'install' will not touch it."
    elif [ -f "$G2_DROPIN" ] && [ "$(g2_running_md5)" = "$G2_PATCHED" ]; then
        st=patched; sup=1; echo "State: PATCHED and running (Gen2 $G2_ID; plugin names: Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip)."
    else
        st=stock; sup=1
        if [ $prepared = 1 ]; then echo "State: Gen2 $G2_ID, not active. A patched copy is prepared in $G2: 'reapply' (or 'install') switches it on."
        else echo "State: stock Gen2 $G2_ID, not patched."; fi
    fi
    bk=$prepared
    echo "STATE state=$st supported=$sup backup=$bk checksum=$SRC_MD5"
}

g2_cmd_install() {
    g2_need || die "this is not a Gen2 build this script knows (checksum $SRC_MD5). Refusing; nothing was changed."
    if [ -f "$G2_DROPIN" ] && [ "$(g2_running_md5)" = "$G2_PATCHED" ]; then echo "Already patched and running. Nothing to do."; exit 0; fi
    cat <<EOF

 This switches this Gen2 device to a PATCHED COPY of MPC OS $G2_ID's program, for the plugins that get the 16-pad drum layout:
  Machinedrum Module, Machinemodule, 6W6, 8W8, CW-78, 9W9, TR-MPC, Lucky Dip
  - $SRC and the read-only system are not changed. The copy goes to $G2 (about 130 MB), and a drop-in in /run points MPC at it.
  - MPC will be stopped and started again: save your project first.
  - A reboot puts the stock MPC back until 'reapply' runs again (an autorun stick can do that); a new firmware or kit needs a new patch.
  - Undo any time with: sh $0 uninstall
  - You use this at your own risk. It is not an Akai product.
EOF
    if [ "${1:-}" = --confirmed ]; then echo "Confirmed by the caller."
    else
        printf "\nType PATCH to continue: "
        if [ -n "$G2_TEST" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = PATCH ] || die "cancelled; nothing was changed"
    fi
    mkdir -p "$G2" || die "cannot create $G2"
    avail=$(df -k "$G2" | awk 'NR==2{print $4}'); [ "${avail:-0}" -gt 150000 ] || die "need about 150 MB free in $G2"
    cat "$SRC" > "$G2/MPC.new" || { rm -f "$G2/MPC.new"; die "could not copy $SRC"; }
    [ "$(md5 "$G2/MPC.new")" = "$SRC_MD5" ] || { rm -f "$G2/MPC.new"; die "the copy of $SRC does not match it; nothing was changed"; }
    F=$G2/MPC.new
    echo "$G2_DATA" | grep -v '^[[:space:]]*$' | write_regions
    if [ "$(md5 "$F")" != "$G2_PATCHED" ]; then rm -f "$G2/MPC.new"; die "checksum mismatch after patching; nothing was changed"; fi
    chmod 755 "$G2/MPC.new"; mv "$G2/MPC.new" "$G2/MPC"; echo "$SRC_MD5" > "$G2/STOCK"
    [ -f "$0" ] && cp "$0" "$G2/mpc-drum-pad-patch.sh.new" && mv "$G2/mpc-drum-pad-patch.sh.new" "$G2/mpc-drum-pad-patch.sh"   # a boot stick runs this copy's reapply
    echo "patched copy ready: $G2/MPC"
    g2_write_dropin || die "could not write $G2_DROPIN"
    g2_sysd daemon-reload; g2_sysd restart acvs
    if g2_wait_running "$G2_PATCHED"; then echo "patched OK: MPC is running the patched copy"
    else
        echo "ERROR: MPC did not come back with the patched copy; switching back to stock"
        rm -f "$G2_DROPIN"; g2_sysd daemon-reload; g2_sysd restart acvs
        die "rolled back; check 'sh $0 status'"
    fi
}

g2_cmd_reapply() {   # for a boot stick: puts the drop-in back after a reboot. --restart also restarts MPC (a stick that restarts it anyway need not)
    g2_need || { echo "reapply: not a Gen2 build this script knows; nothing to do"; exit 0; }
    if [ ! -f "$G2/MPC" ] || [ ! -f "$G2/STOCK" ]; then echo "reapply: nothing installed; nothing to do"; exit 0; fi
    if [ "$(cat "$G2/STOCK")" != "$SRC_MD5" ] || [ "$(md5 "$G2/MPC")" != "$G2_PATCHED" ]; then
        echo "reapply: the saved copy is for a different MPC than this system runs; leaving stock (run install to make a new one)"; exit 0
    fi
    g2_write_dropin || die "could not write $G2_DROPIN"
    g2_sysd daemon-reload
    if [ "${1:-}" = --restart ]; then g2_sysd restart acvs; g2_wait_running "$G2_PATCHED" && echo "reapply: MPC runs the patched copy" || echo "reapply: WARNING: MPC is not running the patched copy"
    else echo "reapply: drop-in written; it takes effect when MPC (acvs) next starts"; fi
}

g2_cmd_uninstall() {
    if [ ! -f "$G2_DROPIN" ] && [ ! -f "$G2/MPC" ]; then echo "Already stock. Nothing to do."; exit 0; fi
    rm -f "$G2_DROPIN"; g2_sysd daemon-reload
    g2_sysd restart acvs
    rm -f "$G2/MPC" "$G2/STOCK" "$G2/MPC.new" "$G2/mpc-drum-pad-patch.sh"; rmdir "$G2" 2>/dev/null
    echo "restored: MPC runs the system's own program again (patched copy removed)"
    [ -n "$G2_TEST" ] || { sleep 6; pidof MPC >/dev/null && echo "MPC is running" || echo "WARNING: MPC is not running; check: systemctl status acvs"; }
}

G2_ARCH=${MPC_PATCH_ARCH:-$(uname -m)}
if [ "$G2_ARCH" = aarch64 ]; then
case "${1:-help}" in
    status) g2_cmd_status ;;
    install) case "${2:-}" in ""|--confirmed) g2_cmd_install "${2:-}" ;; *) usage 1 ;; esac ;;
    reapply) case "${2:-}" in ""|--restart) g2_cmd_reapply "${2:-}" ;; *) usage 1 ;; esac ;;
    uninstall) case "${2:-}" in ""|--confirmed) g2_cmd_uninstall "${2:-}" ;; *) usage 1 ;; esac ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
exit 0
fi

case "${1:-help}" in
    status) cmd_status ;;
    install) case "${2:-}" in ""|--confirmed) cmd_install "${2:-}" ;; *) usage 1 ;; esac ;;
    uninstall) case "${2:-}" in ""|--confirmed) cmd_uninstall "${2:-}" ;; *) usage 1 ;; esac ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
