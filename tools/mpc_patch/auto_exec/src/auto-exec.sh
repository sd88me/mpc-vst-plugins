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
