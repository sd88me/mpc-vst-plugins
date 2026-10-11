#!/bin/sh
# drive-exec-patch.sh: let MPC load plugins from a drive that is mounted "noexec" (a Force's SSD is): one folder on the drive
# gets a private bind mount that allows execution; the drive itself stays noexec. Not specific to one drive or device: any drive
# mounted noexec under /media. Its author tried the original on a Force Gen1 with MPC OS 3.9.1; nothing else is known (untested elsewhere).
#
# ADVANCED AND OPT-IN. This installs a small systemd service on the device (and a unit in its system image). Read the warnings below.
#
#   sh drive-exec-patch.sh status [--root /media/<drive>]   what state the device is in (changes nothing)
#   sh drive-exec-patch.sh install [--root /media/<drive>] [--exec-dir Synths] [--confirmed]
#                                                       install it (asks you to type PATCH first)
#   sh drive-exec-patch.sh uninstall [--confirmed]   remove it (asks you to type REMOVE first)
#   sh drive-exec-patch.sh help
# Run it ON the device as root (ssh root@<device-ip>), after copying the file there (scp).
#
# What it does: on the device a timer (every 5 seconds, from 5 s after boot) checks whether the drive is mounted; once it is, it makes
# a bind mount of one folder of the drive (default: Synths, the folder our plugins install into; "vst" is the contributor's original)
# and remounts only that folder with exec. MPC does not wait for it, and MPC is not restarted. Nothing else on the drive changes;
# fstab, MPC's program and MPC.settings are not touched.
#
# Credit: the mount logic, the checks and the rollback are "ForceHD VST Exec 0.1.3" by timomacquis (issue #150 of mpc-vst-plugins),
# who contributed it to the project (he named it after his drive; it is called drive exec here because nothing in it is specific to that drive). Changes made here: the drive and folder are chosen (any /media/<name>, spaces allowed) instead of
# the fixed /media/ForceHD/vst, mount points are compared as /proc/self/mountinfo writes them, the drive and folder names are strictly
# validated, the no-op acvs drop-in is gone, and this wrapper (status line, typed confirmation, one self-contained file).
#
# WARNINGS
#  - It adds a systemd unit to the device's system image (/usr/lib/systemd/system): the root filesystem is remounted writable for a
#    moment and restored. A firmware update may remove it; run the install again afterwards.
#  - It runs as root at every boot. The code is below: read it before you run it.
#  - If the drive is not mounted when MPC starts, plugins on it are not available until it is; a project that opens by itself at
#    start may open without them. Do not unplug the drive while a plugin from it is loaded.
#  - `uninstall` needs MPC not to be using a plugin from the drive (it checks); the plugins stay on the drive but will not load again.
#  - It has been run on one Force (the contributor's); this adapted version has not been run on a device by its authors yet.
#  - A backup of the mount table and the unit files goes to /data/mpc-vst-plugins/backups (small: no projects, no system image).
#  - Not affiliated with Akai Professional / inMusic.
#
# Version @@VERSION@@. Source: tools/mpc_patch/drive_exec of the repository this came from.
set -u
VERSION=0.2.0
P=${DEX_PREFIX:-}                    # tests only: a folder that stands for / (files), nothing else changes
BK_ROOT=$P/data/mpc-vst-plugins/backups
MOUNTINFO=${DEX_MOUNTINFO:-/proc/self/mountinfo}
if [ -n "$P" ]; then DRIVE_EXEC_CONFIG=$P/etc/drive-exec/config; DRIVE_EXEC_STATE=$P/run/drive-exec; export DRIVE_EXEC_CONFIG DRIVE_EXEC_STATE; fi
export DEX_PREFIX
ETC=$P/etc/drive-exec
ORIG_ETC=$P/etc/force-vst-exec          # where the contributor's original ("ForceHD VST Exec") installs itself: not ours, never touched
UNIT_BOOT=$P/usr/lib/systemd/system/drive-exec-bootstrap.service
LINK_BOOT=$P/usr/lib/systemd/system/multi-user.target.wants/drive-exec-bootstrap.service
UNIT_SVC=$P/etc/systemd/system/drive-exec.service
UNIT_TIMER=$P/etc/systemd/system/drive-exec.timer
die() { echo "ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

mi_path() { printf '%s' "$1" | sed 's/\\/\\134/g; s/ /\\040/g'; }
mi_unescape() { sed 's/\\040/ /g'; }
mount_options() { Q=$(mi_path "$1") awk '$5==ENVIRON["Q"]{v=$6} END{if(v)print v}' "$MOUNTINFO"; }
is_mounted() { [ -n "$(mount_options "$1")" ]; }
valid_root() { printf '%s\n' "$1" | grep -Eq '^/media/[A-Za-z0-9][A-Za-z0-9._+() -]*$' && case "$1" in /media/az01-internal|/media/az01-internal-*|/media/acvs-synths) false ;; *) true ;; esac; }
valid_dir() { printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._+() -]*$'; }
has_noexec() { case ",$(mount_options "$1")," in *,noexec,*) return 0 ;; esac; return 1; }
mpc_service() {
    if systemctl cat acvs >/dev/null 2>&1; then echo acvs
    elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
    else echo acvs; fi
}
candidates() {   # drives mounted noexec directly under /media, one per line (internal storage left out)
    awk '$5 ~ /^\/media\/[^\/]+$/ { n = split($6, o, ","); for (i = 1; i <= n; i++) if (o[i] == "noexec") print $5 }' "$MOUNTINFO" | mi_unescape | while IFS= read -r d; do
        valid_root "$d" && printf '%s\n' "$d"
    done
}
media_mounts() {   # every mount directly under /media: "<mount point>  <fs>  <device>  <noexec|exec>" (what the drive really is, whatever its folder is called)
    awk '$5 ~ /^\/media\/[^\/]+$/ { ex = "exec"; n = split($6, o, ","); for (i = 1; i <= n; i++) if (o[i] == "noexec") ex = "noexec"; for (i = 7; i <= NF && $i != "-"; i++) ; printf "%s  %s  %s  %s\n", $5, $(i+1), $(i+2), ex }' "$MOUNTINFO" | mi_unescape
}
write_payload() {   # $1 = folder to write the patch's files into
    d=$1
@@PAYLOAD@@
}

# --- arguments (after the command)
CMD=${1:-help}; [ $# -gt 0 ] && shift
ROOT=; EXECDIR=Synths; CONFIRMED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --root) [ -n "${2:-}" ] || die "--root needs a drive path like /media/MyDrive"; ROOT=$2; shift 2 ;;
        --exec-dir) [ -n "${2:-}" ] || die "--exec-dir needs a folder name"; EXECDIR=$2; shift 2 ;;
        --confirmed) CONFIRMED=1; shift ;;
        *) usage 1 ;;
    esac
done

need_device() {   # root and the tools; tests (DEX_PREFIX set) skip the architecture check
    [ "$(id -u)" = 0 ] || die "run as root on the device"
    if [ -z "$P" ]; then case "$(uname -m)" in armv7*) ;; *) die "this is for 32-bit ARM MPC OS devices (Gen1); this one is $(uname -m)" ;; esac; fi
    for c in mount umount findmnt flock systemctl awk sed grep; do command -v "$c" >/dev/null || die "missing tool: $c"; done
}
installed_version() { [ -f "$ETC/VERSION" ] && cat "$ETC/VERSION"; }
backup_present() { [ -d "$BK_ROOT" ] && [ -n "$(ls "$BK_ROOT" 2>/dev/null)" ]; }

# the last line is for programs (the installer app): state=stock|patched|partial|unsupported supported=0|1 backup=0|1 [reason=<token>]
state_line() { echo "STATE state=$1 supported=$2 backup=$(backup_present && echo 1 || echo 0)${3:+ reason=$3}"; }

cmd_status() {
    if [ "$(id -u)" != 0 ]; then echo "Not root: run this on the device as root."; state_line unsupported 0 not-root; return; fi
    if [ -z "$P" ]; then case "$(uname -m)" in armv7*) ;; *) echo "This is for 32-bit ARM MPC OS devices; this one is $(uname -m)."; state_line unsupported 0 arch; return ;; esac; fi
    for c in mount umount findmnt flock systemctl awk sed grep; do command -v "$c" >/dev/null || { echo "Missing tool: $c"; state_line unsupported 0 tools; return; }; done
    if [ -e "$ORIG_ETC" ]; then
        echo "The original ForceHD VST Exec is installed ($ORIG_ETC): remove it with its own uninstaller (sh $ORIG_ETC/uninstall.sh) before using this one."
        state_line unsupported 0 other-install; return
    fi
    if v=$(installed_version); then
        if [ "$v" != "$VERSION" ]; then
            echo "Another version of this patch is installed ($v; this script is $VERSION): remove it with its own uninstaller first."
            state_line unsupported 0 other-version; return
        fi
        out=$(/bin/sh "$ETC/drive-exec.sh" status 2>&1); echo "$out"
        case "$out" in *"State: ACTIVE"*) echo "Installed and active."; state_line patched 1 ;;
            *) echo "Installed, but the executable mount is not active now (the drive is not mounted, or the mount was removed)."; state_line partial 1 ;; esac
        return
    fi
    if [ -n "$ROOT" ]; then
        valid_root "$ROOT" || { echo "Not a usable drive path: $ROOT"; state_line unsupported 0 bad-drive; return; }
        is_mounted "$ROOT" || { echo "$ROOT is not mounted."; state_line unsupported 0 no-drive; return; }
        has_noexec "$ROOT" || { echo "$ROOT already allows running programs: the patch is not needed."; state_line unsupported 0 not-needed; return; }
        echo "Not installed. $ROOT is mounted noexec: the patch can be installed."; state_line stock 1; return
    fi
    n=$(candidates | wc -l)
    if [ "$n" = 0 ]; then
        echo "Not installed. No drive under /media is mounted noexec (is it plugged in, and is it already executable?)."
        echo "Mounted under /media right now (a folder with no line here is only an empty mount point, not a drive):"; media_mounts | sed 's/^/  /'
        state_line unsupported 0 no-noexec-drive; return
    fi
    echo "Not installed. Drives mounted noexec:"; candidates | sed 's/^/  /'
    echo "All mounts under /media (the drive is the one marked noexec; a drive can be named by its label or by a number):"; media_mounts | sed 's/^/  /'
    [ "$n" = 1 ] || echo "More than one: install needs --root /media/<drive>."
    state_line stock 1
}

cmd_install() {
    need_device
    [ ! -e "$ORIG_ETC" ] || die "the original ForceHD VST Exec is installed ($ORIG_ETC): remove it with its own uninstaller (sh $ORIG_ETC/uninstall.sh) first"
    v=$(installed_version) && die "this patch is already installed (version $v). Uninstall it first (sh $0 uninstall)."
    valid_dir "$EXECDIR" || die "the folder name may only have letters, digits, . _ + ( ) - and spaces, and must start with a letter or digit"
    if [ -z "$ROOT" ]; then
        n=$(candidates | wc -l)
        [ "$n" -ge 1 ] || die "no drive under /media is mounted noexec: nothing to patch (is it plugged in?)"
        [ "$n" = 1 ] || { echo "More than one drive is mounted noexec:"; candidates | sed 's/^/  /'; die "choose one with --root /media/<drive>"; }
        ROOT=$(candidates)
    fi
    valid_root "$ROOT" || die "not a usable drive path: $ROOT (it must be /media/<name> with letters, digits, . _ + ( ) - and spaces)"
    is_mounted "$ROOT" || die "$ROOT is not mounted"
    has_noexec "$ROOT" || die "$ROOT already allows running programs: the patch is not needed"
    TARGET=$ROOT/$EXECDIR
    [ -z "$(mount_options "$TARGET")" ] || die "$TARGET is already a mount point: refusing"
    [ ! -L "$TARGET" ] || die "$TARGET is a symbolic link: refusing"
    for path in "$UNIT_BOOT" "$LINK_BOOT" "$ETC" "$UNIT_SVC" "$UNIT_TIMER"; do
        [ ! -e "$path" ] && [ ! -L "$path" ] || die "already exists: $path (an earlier install of this patch? uninstall it with its own uninstaller first)"
    done
    echo "Installing the drive exec patch ($VERSION):"
    echo "  drive:  $ROOT   (stays noexec)"
    echo "  folder: $TARGET   (gets an executable bind mount; plugins put their .so inside it)"
    echo "  files:  $ETC/, $UNIT_SVC, $UNIT_TIMER and the bootstrap unit in /usr/lib/systemd/system"
    echo "  MPC is not restarted. Save your project anyway."
    if [ "$CONFIRMED" = 0 ]; then
        printf "\nType PATCH to continue: "
        if [ -n "$P" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = PATCH ] || die "cancelled; nothing was changed"
    fi
    BACKUP=$BK_ROOT/drive-exec-$VERSION-$(date +%Y%m%d-%H%M%S)
    [ ! -e "$BACKUP" ] || die "backup folder exists: $BACKUP"
    mkdir -p "$BACKUP" || die "cannot create $BACKUP"
    chmod 700 "$BACKUP"
    cat /proc/mounts > "$BACKUP/mounts.before"
    cat "$MOUNTINFO" > "$BACKUP/mountinfo.before"
    systemctl cat "$(mpc_service)" > "$BACKUP/mpc-service.before" 2>&1 || true
    systemctl cat edisksd > "$BACKUP/edisksd.before" 2>&1 || true
    [ -f /etc/fstab ] && cp /etc/fstab "$BACKUP/fstab.reference"
    printf '%s\n' 'Patch-only backup: reference mounts and unit files; no projects, no system image.' > "$BACKUP/README.txt"
    FAILED=1; stage=
    cleanup() {
        [ -z "$stage" ] || rm -rf "$stage"
        if [ "$FAILED" = 1 ]; then
            echo 'Installation interrupted: rolling back the patch'
            systemctl disable --now drive-exec.timer 2>/dev/null || true
            systemctl stop drive-exec.service 2>/dev/null || true
            if [ -f "$ETC/drive-exec.sh" ]; then
                if ! /bin/sh "$ETC/drive-exec.sh" revert; then echo 'Cannot remove the mount: recovery files retained'; return; fi
            fi
            if [ -f "$ETC/root-bootstrap.sh" ]; then /bin/sh "$ETC/root-bootstrap.sh" remove; fi
            rm -f "$UNIT_SVC" "$UNIT_TIMER"
            rm -f "$ETC/drive-exec.sh" "$ETC/config" "$ETC/VERSION" "$ETC/uninstall.sh" "$ETC/bootstrap.sh" "$ETC/root-bootstrap.sh"
            rmdir "$ETC" 2>/dev/null || true
            systemctl daemon-reload
        fi
    }
    trap cleanup EXIT
    stage=$(mktemp -d) || exit 1
    write_payload "$stage"
    mkdir -p "$ETC" "$P/etc/systemd/system" || exit 1
    chmod 755 "$ETC"
    cp "$stage/drive-exec.sh" "$stage/uninstall.sh" "$stage/bootstrap.sh" "$stage/root-bootstrap.sh" "$ETC/" || exit 1
    printf "DRIVE_ROOT='%s'\nEXEC_DIR='%s'\n" "$ROOT" "$EXECDIR" > "$ETC/config" || exit 1
    printf '%s\n' "$VERSION" > "$ETC/VERSION"
    chmod 755 "$ETC/drive-exec.sh" "$ETC/uninstall.sh"
    chmod 644 "$ETC/config" "$ETC/VERSION"
    cp "$stage/drive-exec.service" "$stage/drive-exec.timer" "$P/etc/systemd/system/" || exit 1
    /bin/sh "$ETC/root-bootstrap.sh" install "$stage/drive-exec-bootstrap.service" || exit 1
    rm -rf "$stage"
    systemctl daemon-reload || exit 1
    /bin/sh "$ETC/drive-exec.sh" apply || exit 1
    /bin/sh "$ETC/drive-exec.sh" status || exit 1
    systemctl enable --now drive-exec.timer || exit 1
    systemctl start drive-exec.service || exit 1
    find "$ETC" -type f -exec sha256sum {} \; > "$BACKUP/installed.sha256"
    sha256sum "$UNIT_SVC" "$UNIT_TIMER" "$UNIT_BOOT" >> "$BACKUP/installed.sha256"
    FAILED=0
    trap - EXIT
    sync
    echo "Patch $VERSION installed. Backup: $BACKUP"
    echo "MPC remains running. Plugins installed into $TARGET (for example with the installer app, to this drive) can now load."
    echo "Check it after a reboot: sh $0 status"
}

cmd_uninstall() {
    need_device
    v=$(installed_version) || { echo "Not installed. Nothing to do."; exit 0; }
    [ "$v" = "$VERSION" ] || die "another version is installed ($v): use its own uninstaller"
    if [ "$CONFIRMED" = 0 ]; then
        echo "This removes the executable mount and the files of the patch. Plugins on the drive stay, but will not load until the patch is back."
        printf "Type REMOVE to continue: "
        if [ -n "$P" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = REMOVE ] || die "cancelled; nothing was changed"
    fi
    /bin/sh "$ETC/uninstall.sh"
}

case "$CMD" in
    status) cmd_status ;;
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
