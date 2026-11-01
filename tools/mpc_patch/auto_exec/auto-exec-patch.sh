#!/bin/sh
# auto-exec-patch.sh: let MPC load plugins from ANY drive it mounts "noexec" (a Force's SSD, a USB stick, an SD card), with nothing to
# choose: every noexec drive under /media that has a Synths folder gets a private bind mount of that folder that allows execution.
# The drives themselves stay noexec. Successor to drive-exec (tools/mpc_patch/drive_exec), which handles one named drive.
#
# ADVANCED AND OPT-IN. This installs a small systemd service on the device (and a unit in its system image). Read the warnings below.
#
#   sh auto-exec-patch.sh status                  what state the device is in (changes nothing)
#   sh auto-exec-patch.sh install [--confirmed]   install it (asks you to type PATCH first)
#   sh auto-exec-patch.sh uninstall [--confirmed] remove it (asks you to type REMOVE first)
#   sh auto-exec-patch.sh release                 take the executable mounts off (do this before ejecting a drive)
#   sh auto-exec-patch.sh verify                  does MPC itself see the executable folders, and which plugins are in them
#   sh auto-exec-patch.sh help
# Run it ON the device as root (ssh root@<device-ip>), after copying the file there (scp).
#
# What it does: a timer (every 5 seconds, from 5 s after boot) looks at the mounts; for each noexec drive directly under /media
# (not the internal storage) with a Synths folder, it bind-mounts that folder onto itself and remounts only that with exec. A drive
# that is already executable, or has no Synths folder, is left alone. MPC is not restarted. fstab, MPC's program and MPC.settings are
# not touched.
#
# Credit: the mount logic, the checks and the rollback are "ForceHD VST Exec 0.1.3" by timomacquis (issue #150 of mpc-vst-plugins).
#
# WARNINGS
#  - It adds a systemd unit to the device's system image (/usr/lib/systemd/system): the root filesystem is remounted writable for a
#    moment and restored. A firmware update may remove it; run the install again afterwards.
#  - It runs as root at every boot. The code is below: read it before you run it.
#  - A drive with an executable folder on it cannot be unmounted until the folder is released: run `release` (or `uninstall`) before
#    ejecting. A drive that is unplugged is cleaned up by the next timer pass.
#  - Do not unplug a drive while a plugin from it is loaded. `uninstall` and `release` refuse a busy mount.
#  - NOT RUN ON A DEVICE YET (offline tests only).
#  - A backup of the mount table and the unit files goes to /data/mpc-vst-plugins/backups (small: no projects, no system image).
#  - Not affiliated with Akai Professional / inMusic.
#
# Version 1. Source: tools/mpc_patch/auto_exec of the repository this came from.
set -u
VERSION=0.3.2
P=${AEX_PREFIX:-}                    # tests only: a folder that stands for / (files), nothing else changes
BK_ROOT=$P/data/mpc-vst-plugins/backups
MOUNTINFO=${AEX_MOUNTINFO:-/proc/self/mountinfo}
if [ -n "$P" ]; then AUTO_EXEC_STATE=$P/run/auto-exec; export AUTO_EXEC_STATE; fi
export AEX_PREFIX
ETC=$P/etc/auto-exec
OLD_VERSIONS="0.3.0 0.3.1"              # earlier versions this script updates: their own uninstaller (in $ETC) removes them first
DRIVE_EXEC_ETC=$P/etc/drive-exec         # drive exec, the older patch this replaces: not ours, never touched
ORIG_ETC=$P/etc/force-vst-exec          # where the contributor's original ("ForceHD VST Exec") installs itself: not ours, never touched
UNIT_BOOT=$P/usr/lib/systemd/system/auto-exec-bootstrap.service
LINK_BOOT=$P/usr/lib/systemd/system/multi-user.target.wants/auto-exec-bootstrap.service
UNIT_SVC=$P/etc/systemd/system/auto-exec.service
UNIT_TIMER=$P/etc/systemd/system/auto-exec.timer
die() { echo "ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

mi_path() { printf '%s' "$1" | sed 's/\\/\\134/g; s/ /\\040/g'; }
mi_unescape() { sed 's/\\040/ /g'; }
mount_options() { Q=$(mi_path "$1") awk '$5==ENVIRON["Q"]{v=$6} END{if(v)print v}' "$MOUNTINFO"; }
is_mounted() { [ -n "$(mount_options "$1")" ]; }
valid_root() { printf "%s\n" "$1" | grep -Eq "^/media/[A-Za-z0-9][A-Za-z0-9._+() -]*\$" && case "$1" in /media/az01-internal|/media/az01-internal-*|/media/acvs-synths) false ;; *) true ;; esac; }
mpc_service() {
    if systemctl cat acvs >/dev/null 2>&1; then echo acvs
    elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
    else echo acvs; fi
}
candidates() {   # drives mounted noexec directly under /media, one per line (internal storage left out)
    awk '$5 ~ "^/media/[^/]+$" { n = split($6, o, ","); for (i = 1; i <= n; i++) if (o[i] == "noexec") print $5 }' "$MOUNTINFO" | mi_unescape | while IFS= read -r d; do
        valid_root "$d" && printf '%s\n' "$d"
    done
}
media_mounts() {   # every mount directly under /media: "<mount point>  <fs>  <device>  <noexec|exec>" (what the drive really is, whatever its folder is called)
    awk '$5 ~ "^/media/[^/]+$" { ex = "exec"; n = split($6, o, ","); for (i = 1; i <= n; i++) if (o[i] == "noexec") ex = "noexec"; for (i = 7; i <= NF && $i != "-"; i++) ; printf "%s  %s  %s  %s\n", $5, $(i+1), $(i+2), ex }' "$MOUNTINFO" | mi_unescape
}
write_payload() {   # $1 = folder to write the patch's files into
    d=$1
    cat > "$d/auto-exec.sh" <<'AEX_EOF_AUTO_EXEC_SH'
#!/bin/sh
# Auto exec: for every drive MPC mounts noexec under /media/<name>, the drive's Synths folder gets a private bind mount that is
# remounted with exec. The drive itself keeps its noexec, nothing is configured, any number of drives. Mount logic, checks and
# rollback follow "ForceHD VST Exec 0.1.3" by timomacquis (issue #150), as adapted in tools/mpc_patch/drive_exec.
#   apply     one pass over the current mounts (the timer runs it every few seconds)
#   release   take every executable mount this patch made off again (run it before ejecting a drive)
#   status    the mounts this patch made
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
STATE=${AUTO_EXEC_STATE:-/run/auto-exec}
MOUNTINFO=${AEX_MOUNTINFO:-/proc/self/mountinfo}
FOLDER=Synths
[ "$(id -u)" = 0 ] || { echo 'Root required'; exit 1; }
mkdir -p "$STATE"
chmod 700 "$STATE"
exec 9>"$STATE/lock"
attempt=0
while ! flock -n 9; do
 [ "$attempt" -lt 10 ] || { echo 'Another operation is in progress'; exit 1; }
 sleep 1
 attempt=$((attempt+1))
done
OWNED=$STATE/owned.mounts      # one line per mount made here: "<mount id> <parent mount id> <mount point, mountinfo form>"
touch "$OWNED"
# /proc/self/mountinfo writes a space in a path as \040 (and a backslash as \134)
mi_path() { printf '%s' "$1" | sed 's/\\/\\134/g; s/ /\\040/g'; }
mi_unescape() { sed 's/\\040/ /g'; }
mount_id() { P=$(mi_path "$1") awk '$5==ENVIRON["P"]{v=$1} END{if(v)print v}' "$MOUNTINFO"; }
mount_options() { P=$(mi_path "$1") awk '$5==ENVIRON["P"]{v=$6} END{if(v)print v}' "$MOUNTINFO"; }
valid_drive() { printf '%s\n' "$1" | grep -Eq '^/media/[A-Za-z0-9][A-Za-z0-9._+() -]*$' && case "$1" in /media/az01-internal|/media/az01-internal-*|/media/acvs-synths) false ;; *) true ;; esac; }
noexec_drives() {   # one per line: "<mount id> <mount point, unescaped>" for each noexec mount directly under /media
 awk '$5 ~ "^/media/[^/]+$" { n = split($6, o, ","); for (i = 1; i <= n; i++) if (o[i] == "noexec") print $1, $5 }' "$MOUNTINFO" | mi_unescape
}
log() { echo "$*"; }
owned_line() { awk -v id="$1" '$1==id' "$OWNED"; }
forget() { grep -v "^$1 " "$OWNED" > "$OWNED.new" || true; mv "$OWNED.new" "$OWNED"; }
allow_exec() {
 options=$(mount_options "$1")
 options=$(printf '%s' "$options" | sed 's/,noexec//g;s/^noexec,//')   # keep nosuid/nodev/nosymfollow
 mount -o "remount,bind,$options,exec" "$1"
 case ",$(mount_options "$1")," in *,noexec,*) echo "noexec remains active on $1"; return 1;; esac
}
release_one() {   # $1 = mount id of one of ours; a plain umount, never forced or lazy
 line=$(owned_line "$1"); [ -n "$line" ] || return 0
 mp=$(printf '%s\n' "$line" | cut -d' ' -f3- | mi_unescape)
 if [ "$(mount_id "$mp")" = "$1" ]; then
  umount "$mp" || { log "Cannot release $mp (busy: a plugin from it is loaded?)"; return 1; }
  log "Released $mp"
 fi
 forget "$1"
}
apply_one() {   # $1 = drive mount point
 drive=$1; target=$drive/$FOLDER
 [ -d "$target" ] && [ ! -L "$target" ] || return 0            # no Synths folder: nothing to do for this drive
 [ -z "$(mount_id "$target")" ] || return 0                    # already a mount (ours, handled by the caller, or foreign: left alone)
 parent_id=$(mount_id "$drive"); parent_options=$(mount_options "$drive")
 mount --bind "$target" "$target"
 new_id=$(mount_id "$target")
 if ! { mount --make-private "$target" && allow_exec "$target"; }; then umount "$target" || true; return 0; fi
 if [ "$(mount_id "$drive")" != "$parent_id" ] || [ "$(mount_options "$drive")" != "$parent_options" ]; then
  umount "$target" || true; echo "Parent mount of $drive modified: aborting"; return 1
 fi
 printf '%s %s %s\n' "$new_id" "$parent_id" "$(mi_path "$target")" >> "$OWNED"
 log "Auto exec active on $target"
}
case "${1:-status}" in
 apply)
  # 1. mounts of ours whose drive is gone (unplugged or replaced) are taken off, so the drive's mount point can be cleaned up
  while read -r id parent mp; do
   [ -n "$id" ] || continue
   drive=$(printf '%s\n' "$mp" | sed 's|/[^/]*$||' | mi_unescape)
   if [ -z "$(mount_id "$drive")" ] || [ "$(mount_id "$drive")" != "$parent" ]; then release_one "$id" || true; fi
  done < "$OWNED"
  # 2. every noexec drive that has a Synths folder gets one
  noexec_drives | while read -r _ drive; do
   valid_drive "$drive" || continue
   apply_one "$drive" || true
  done
  # 3. one of ours that turned noexec again is fixed
  while read -r id parent mp; do
   [ -n "$id" ] || continue
   t=$(printf '%s\n' "$mp" | mi_unescape)
   [ "$(mount_id "$t")" = "$id" ] || { forget "$id"; continue; }
   case ",$(mount_options "$t")," in *,noexec,*) allow_exec "$t" || true;; esac
  done < "$OWNED"
  ;;
 release)
  ok=0
  while read -r id _; do [ -n "$id" ] || continue; release_one "$id" || ok=1; done < "$OWNED"
  exit $ok
  ;;
 status)
  n=0
  while read -r id parent mp; do
   [ -n "$id" ] || continue
   t=$(printf '%s\n' "$mp" | mi_unescape)
   if [ "$(mount_id "$t")" = "$id" ]; then
    case ",$(mount_options "$t")," in *,noexec,*) echo "BLOCKED $t";; *) echo "ACTIVE $t"; n=$((n+1));; esac
   fi
  done < "$OWNED"
  echo "Executable folders: $n"
  echo "Noexec drives:"; noexec_drives | cut -d' ' -f2- | sed 's/^/  /'
  ;;
 *) echo 'Usage: auto-exec.sh apply | release | status'; exit 1;;
esac
AEX_EOF_AUTO_EXEC_SH
    cat > "$d/uninstall.sh" <<'AEX_EOF_UNINSTALL_SH'
#!/bin/sh
set -eu
# Removes the patch: stops the timer, takes the executable mount off (a normal umount, never forced or lazy), deletes the files this
# patch installed. Plugins, skins, MPC.settings and fstab are not touched. Original: timomacquis, 0.1.3 (adapted: the drive and folder
# comes from the mounts, there is no config; AEX_PREFIX, tests only, redirects the paths).
P=${AEX_PREFIX:-}
if [ -z "$P" ]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi   # fixed PATH on the device; tests (AEX_PREFIX) bring their own shims
[ "$(id -u)" = 0 ] || { echo 'Root required'; exit 1; }
[ -f "$P/etc/auto-exec/VERSION" ] || { echo 'Patch not installed'; exit 0; }
[ "$(cat "$P/etc/auto-exec/VERSION")" = 0.3.2 ] || { echo 'Different version: use its matching uninstaller'; exit 1; }
mpc_service() {
 if systemctl cat acvs >/dev/null 2>&1; then echo acvs
 elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
 else echo acvs; fi
}
for pid in $(pidof MPC || true); do
 if grep -q " /media/.*/Synths/" "/proc/$pid/maps"; then
  echo "MPC is using a plugin from a drive's Synths folder. Save the project, stop MPC, then retry the removal."
  echo "Command after saving: systemctl stop $(mpc_service)"
  exit 1
 fi
done
# Retain the existing enabled state if revert fails.
ENABLED=0
systemctl is-enabled --quiet auto-exec.timer && ENABLED=1 || true
systemctl disable --now auto-exec.timer
systemctl stop auto-exec.service
if ! /bin/sh "$P/etc/auto-exec/auto-exec.sh" release; then
 [ "$ENABLED" = 0 ] || systemctl enable --now auto-exec.timer
 echo 'Uninstallation cancelled: mount busy or unmanaged'
 exit 1
fi
/bin/sh "$P/etc/auto-exec/root-bootstrap.sh" remove
systemctl stop auto-exec-bootstrap.service 2>/dev/null || true
rm -f "$P/etc/systemd/system/auto-exec.service" "$P/etc/systemd/system/auto-exec.timer"
rm -f "$P/etc/auto-exec/auto-exec.sh" "$P/etc/auto-exec/VERSION" "$P/etc/auto-exec/uninstall.sh" "$P/etc/auto-exec/bootstrap.sh" "$P/etc/auto-exec/root-bootstrap.sh"
rmdir "$P/etc/auto-exec" 2>/dev/null || true
systemctl daemon-reload
rm -f "${AUTO_EXEC_STATE:-$P/run/auto-exec}/lock" "${AUTO_EXEC_STATE:-$P/run/auto-exec}/owned.mounts"
rmdir "${AUTO_EXEC_STATE:-$P/run/auto-exec}" 2>/dev/null || true
sync
echo 'Patch removed. The drive itself stays mounted as it was.'
echo 'Backups remain in /data/mpc-vst-plugins/backups.'
echo "If MPC was stopped manually, restart it: systemctl start $(mpc_service)"
echo 'Plugins on the drive stay where they are, but they will not load again until the patch is back (the drives are noexec).'
AEX_EOF_UNINSTALL_SH
    cat > "$d/bootstrap.sh" <<'AEX_EOF_BOOTSTRAP_SH'
#!/bin/sh
set -eu
# Reload after the writable /etc overlay appears; schedule work without waiting for SSD. (Original: timomacquis, 0.1.3.)
systemctl daemon-reload
systemctl --no-block start auto-exec.timer
AEX_EOF_BOOTSTRAP_SH
    cat > "$d/root-bootstrap.sh" <<'AEX_EOF_ROOT_BOOTSTRAP_SH'
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
AEX_EOF_ROOT_BOOTSTRAP_SH
    cat > "$d/auto-exec.service" <<'AEX_EOF_AUTO_EXEC_SERVICE'
[Unit]
Description=Auto exec - scoped executable mount
After=edisksd.service
Wants=edisksd.service

[Service]
Type=oneshot
ExecStart=/bin/sh /etc/auto-exec/auto-exec.sh apply
TimeoutStartSec=15
PrivateMounts=no
AEX_EOF_AUTO_EXEC_SERVICE
    cat > "$d/auto-exec.timer" <<'AEX_EOF_AUTO_EXEC_TIMER'
[Unit]
Description=Check the auto exec mount

[Timer]
OnBootSec=5s
OnUnitInactiveSec=5s
AccuracySec=1s
Unit=auto-exec.service

[Install]
WantedBy=timers.target
AEX_EOF_AUTO_EXEC_TIMER
    cat > "$d/auto-exec-bootstrap.service" <<'AEX_EOF_AUTO_EXEC_BOOTSTRAP_SERVICE'
[Unit]
Description=Auto exec bootstrap after writable etc
Requires=etc.mount
After=etc.mount

[Service]
Type=oneshot
ExecStart=/bin/sh /etc/auto-exec/bootstrap.sh
RemainAfterExit=yes
TimeoutStartSec=15
PrivateMounts=no
AEX_EOF_AUTO_EXEC_BOOTSTRAP_SERVICE
}

# --- arguments (after the command)
CMD=${1:-help}; [ $# -gt 0 ] && shift
CONFIRMED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --confirmed) CONFIRMED=1; shift ;;
        *) usage 1 ;;
    esac
done

need_device() {   # root and the tools; tests (AEX_PREFIX set) skip the architecture check
    [ "$(id -u)" = 0 ] || die "run as root on the device"
    if [ -z "$P" ]; then case "$(uname -m)" in armv7*) ;; *) die "this is for 32-bit ARM MPC OS devices (Gen1); this one is $(uname -m)" ;; esac; fi
    for c in mount umount findmnt flock systemctl awk sed grep; do command -v "$c" >/dev/null || die "missing tool: $c"; done
}
installed_version() { [ -f "$ETC/VERSION" ] && cat "$ETC/VERSION"; }
is_old() { case " $OLD_VERSIONS " in *" $1 "*) true ;; *) false ;; esac; }
no_leftovers() {
    for path in "$UNIT_BOOT" "$LINK_BOOT" "$ETC" "$UNIT_SVC" "$UNIT_TIMER"; do
        [ ! -e "$path" ] && [ ! -L "$path" ] || die "already exists: $path (an earlier install of this patch? uninstall it with its own uninstaller first)"
    done
}
backup_present() { [ -d "$BK_ROOT" ] && [ -n "$(ls "$BK_ROOT" 2>/dev/null)" ]; }
helper() { AUTO_EXEC_STATE=${AUTO_EXEC_STATE:-$P/run/auto-exec} AEX_MOUNTINFO=$MOUNTINFO /bin/sh "$ETC/auto-exec.sh" "$@"; }

# the last line is for programs (the installer app): state=stock|patched|partial|unsupported supported=0|1 backup=0|1 [reason=<token>]
state_line() { echo "STATE state=$1 supported=$2 backup=$(backup_present && echo 1 || echo 0)${3:+ reason=$3}"; }

cmd_status() {
    if [ "$(id -u)" != 0 ]; then echo "Not root: run this on the device as root."; state_line unsupported 0 not-root; return; fi
    if [ -z "$P" ]; then case "$(uname -m)" in armv7*) ;; *) echo "This is for 32-bit ARM MPC OS devices; this one is $(uname -m)."; state_line unsupported 0 arch; return ;; esac; fi
    for c in mount umount findmnt flock systemctl awk sed grep; do command -v "$c" >/dev/null || { echo "Missing tool: $c"; state_line unsupported 0 tools; return; }; done
    if [ -e "$ORIG_ETC" ] || [ -e "$DRIVE_EXEC_ETC" ]; then
        echo "drive exec or the original ForceHD VST Exec is installed: remove it with its own uninstaller before using this one."
        state_line unsupported 0 other-install; return
    fi
    if v=$(installed_version); then
        if is_old "$v"; then
            echo "An older version of this patch is installed ($v). Install updates it to $VERSION (it removes $v with its own uninstaller first)."
            state_line old-patch 1; return
        fi
        if [ "$v" != "$VERSION" ]; then
            echo "Another version of this patch is installed ($v; this script is $VERSION): remove it with its own uninstaller first."
            state_line unsupported 0 other-version; return
        fi
        if ! /bin/sh "$ETC/root-bootstrap.sh" check; then
            echo "The bootstrap unit is not in the root filesystem (an overlay over /usr hides where it is, or a firmware update removed it): it will not start at boot. Run: sh $0 uninstall, then install again."
            state_line partial 1 bootstrap-missing; return
        fi
        out=$(helper status 2>&1); echo "$out"
        case "$out" in *"ACTIVE "*) echo "Installed and active. Check that MPC sees it: sh $0 verify"; state_line patched 1 ;;
            *) echo "Installed. No executable folder right now (no noexec drive with a Synths folder is mounted)."; state_line partial 1 ;; esac
        return
    fi
    n=$(candidates | wc -l)
    echo "Not installed. Mounts directly under /media (the drives are the ones marked noexec; a drive is named by its label or a number):"
    media_mounts | sed 's/^/  /'
    if [ "$n" = 0 ]; then echo "No drive is mounted noexec right now; the patch can still be installed and will act when one is."; fi
    state_line stock 1
}

# verify: "installed" is not "works". MPC is a separate process: it must SEE the executable mounts.
# Last line, for programs: VERIFY result=ok|not-installed|not-active|mpc-blind|mpc-stopped|no-plugins [plugins=N]
verify_line() { echo "VERIFY result=$1${2:+ $2}"; }
cmd_verify() {
    installed_version >/dev/null || { echo "The patch is not installed."; verify_line not-installed; return 1; }
    mounts=$(helper status 2>&1 | sed -n 's/^ACTIVE //p')
    if [ -z "$mounts" ]; then
        echo "No executable folder is active: no noexec drive with a Synths folder is mounted (or the timer has not run yet: wait 10 seconds, or run: systemctl start auto-exec.service)."
        verify_line not-active; return 1
    fi
    echo "$mounts" | sed 's/^/OK: executable (drive stays noexec): /'
    pid=$(pidof MPC 2>/dev/null | awk '{print $1}')
    if [ -z "$pid" ]; then echo "MPC is not running now, so what it sees was not checked."; verify_line mpc-stopped; return 0; fi
    blind=0
    while IFS= read -r T; do
        Q=$(mi_path "$T")
        mo=$(Q="$Q" awk '$5==ENVIRON["Q"]{v=$6} END{if(v)print v}' "${AEX_MPC_MOUNTINFO:-/proc/$pid/mountinfo}" 2>/dev/null)
        if [ -z "$mo" ] || case ",$mo," in *,noexec,*) true ;; *) false ;; esac; then
            echo "PROBLEM: MPC (pid $pid) does not see $T as executable (it sees: ${mo:-nothing})."; blind=1
        fi
    done <<EOM
$mounts
EOM
    if [ "$blind" = 1 ]; then
        echo "Fix: stop and start MPC (systemctl restart $(mpc_service); save your project first), then run verify again."
        verify_line mpc-blind; return 1
    fi
    echo "OK: MPC (pid $pid) sees them too."
    n=0
    while IFS= read -r T; do
        for f in "$T"/*/plugin-meta.xml; do [ -f "$f" ] || continue; n=$((n+1)); echo "  plugin folder: $(basename "$(dirname "$f")")"; done
    done <<EOM
$mounts
EOM
    if [ "$n" = 0 ]; then
        echo "No plugin is installed in those folders yet. Install them into a drive's Synths folder (the installer app: Install to), then run: sh $0 verify"
        verify_line no-plugins plugins=0; return 0
    fi
    echo "$n plugin folder(s) there. If a plugin still only shows \"Load Plugin\": it was registered while the drive was not ready. In the installer app run step 5 (Register plugin folders), then restart MPC."
    verify_line ok plugins=$n
}

cmd_install() {
    need_device
    [ ! -e "$ORIG_ETC" ] || die "the original ForceHD VST Exec is installed ($ORIG_ETC): remove it with its own uninstaller first"
    [ ! -e "$DRIVE_EXEC_ETC" ] || die "drive exec is installed ($DRIVE_EXEC_ETC): uninstall it first (this patch replaces it)"
    OLD=
    if v=$(installed_version); then
        is_old "$v" || die "this patch is already installed (version $v). Uninstall it first (sh $0 uninstall)."
        OLD=$v
    else
        no_leftovers
    fi
    echo "Installing the auto exec patch ($VERSION):"
    [ -z "$OLD" ] || echo "  first removes the installed version $OLD with its own uninstaller (the drives' executable folders go away for a moment)."
    echo "  every drive under /media mounted noexec gets an executable bind mount of its Synths folder (the drive stays noexec)."
    echo "  Noexec drives right now:"; candidates | sed 's/^/    /'
    echo "  files:  $ETC/, $UNIT_SVC, $UNIT_TIMER and the bootstrap unit in /usr/lib/systemd/system"
    echo "  MPC is not restarted. Save your project anyway."
    if [ "$CONFIRMED" = 0 ]; then
        printf "\nType PATCH to continue: "
        if [ -n "$P" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = PATCH ] || die "cancelled; nothing was changed"
    fi
    if [ -n "$OLD" ]; then
        /bin/sh "$ETC/uninstall.sh" || die "could not remove version $OLD (see above); $OLD stays installed and nothing else was changed"
        no_leftovers
        echo "Version $OLD removed."
    fi
    BACKUP=$BK_ROOT/auto-exec-$VERSION-$(date +%Y%m%d-%H%M%S)
    [ ! -e "$BACKUP" ] || BACKUP=$BACKUP-$$                     # a second install within the same second (an update right after one)
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
            systemctl disable --now auto-exec.timer 2>/dev/null || true
            systemctl stop auto-exec.service 2>/dev/null || true
            if [ -f "$ETC/auto-exec.sh" ]; then
                if ! helper release; then echo 'Cannot remove a mount: recovery files retained'; return; fi
            fi
            if [ -f "$ETC/root-bootstrap.sh" ]; then /bin/sh "$ETC/root-bootstrap.sh" remove; fi
            rm -f "$UNIT_SVC" "$UNIT_TIMER"
            rm -f "$ETC/auto-exec.sh" "$ETC/VERSION" "$ETC/uninstall.sh" "$ETC/bootstrap.sh" "$ETC/root-bootstrap.sh"
            rmdir "$ETC" 2>/dev/null || true
            systemctl daemon-reload
        fi
    }
    trap cleanup EXIT
    stage=$(mktemp -d) || exit 1
    write_payload "$stage"
    mkdir -p "$ETC" "$P/etc/systemd/system" || exit 1
    chmod 755 "$ETC"
    cp "$stage/auto-exec.sh" "$stage/uninstall.sh" "$stage/bootstrap.sh" "$stage/root-bootstrap.sh" "$ETC/" || exit 1
    printf '%s\n' "$VERSION" > "$ETC/VERSION"
    chmod 755 "$ETC/auto-exec.sh" "$ETC/uninstall.sh"
    chmod 644 "$ETC/VERSION"
    cp "$stage/auto-exec.service" "$stage/auto-exec.timer" "$P/etc/systemd/system/" || exit 1
    /bin/sh "$ETC/root-bootstrap.sh" install "$stage/auto-exec-bootstrap.service" || exit 1
    rm -rf "$stage"
    systemctl daemon-reload || exit 1
    helper apply || exit 1
    helper status || exit 1
    systemctl enable --now auto-exec.timer || exit 1
    systemctl start auto-exec.service || exit 1
    find "$ETC" -type f -exec sha256sum {} \; > "$BACKUP/installed.sha256"
    sha256sum "$UNIT_SVC" "$UNIT_TIMER" "$UNIT_BOOT" >> "$BACKUP/installed.sha256"
    FAILED=0
    trap - EXIT
    sync
    echo "Patch $VERSION installed. Backup: $BACKUP"
    echo "MPC remains running. Plugins installed into a drive's Synths folder can now load. Run \`release\` before ejecting a drive."
    echo "Check it after a reboot: sh $0 status"
    echo; cmd_verify || echo "(The patch is installed; see the note above.)"
}

cmd_uninstall() {
    need_device
    v=$(installed_version) || { echo "Not installed. Nothing to do."; exit 0; }
    [ "$v" = "$VERSION" ] || is_old "$v" || die "another version is installed ($v): use its own uninstaller"
    if [ "$CONFIRMED" = 0 ]; then
        echo "This removes the executable mounts and the files of the patch. Plugins on the drives stay, but will not load until the patch is back."
        printf "Type REMOVE to continue: "
        if [ -n "$P" ]; then read -r a; else read -r a < /dev/tty 2>/dev/null || read -r a; fi
        [ "$a" = REMOVE ] || die "cancelled; nothing was changed"
    fi
    /bin/sh "$ETC/uninstall.sh"
}

cmd_release() {
    need_device
    installed_version >/dev/null || die "not installed"
    helper release && echo "Released: the drives can be ejected. The timer makes the folders executable again on its next pass (stop it first with: systemctl stop auto-exec.timer, start it again with: systemctl start auto-exec.timer)."
}

case "$CMD" in
    status) cmd_status ;;
    verify) need_device; cmd_verify ;;
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    release) cmd_release ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
