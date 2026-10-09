#!/bin/bash
# Read-only facts from ext2/3/4 partition dumps of an MPC (e.g. Gen2 / Live III), for docs/GEN2.md.
# Usage: tools/gen2_image_facts.sh <image> [<image>...]
# Uses `debugfs -c` (catalog mode, never writes, no mounting, no root needed). Prints only small facts,
# never file contents beyond a few matched lines, so the output is safe to paste into an issue.
# Never commit the images or anything extracted from them (CLAUDE.md).
set -u
command -v debugfs >/dev/null || { echo "needs debugfs (e2fsprogs)" >&2; exit 2; }
[ $# -gt 0 ] || { echo "usage: $0 <image>..." >&2; exit 2; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
dfs() { debugfs -c -R "$1" "$IMG" 2>/dev/null; }
has() { dfs "stat $1" | grep -q "^Inode:"; }
cat_() { dfs "cat $1" 2>/dev/null; }

for IMG in "$@"; do
  echo "== $IMG ($(du -h "$IMG" | cut -f1))"
  dfs "stats" | grep -q "Filesystem UUID" || { echo "  not ext2/3/4 (skipped)"; continue; }
  echo "  label: $(dfs stats | sed -n 's/^Filesystem volume name: *//p')"
  echo "  top level: $(dfs 'ls -p /' | awk -F/ 'NF>5 && $6!="." && $6!=".." {printf "%s ", $6}')"
  for p in /Settings/MPC/MPC.settings /data/Settings/MPC/MPC.settings /Settings /data; do
    has "$p" && echo "  has $p"
  done
  for p in /usr/lib/libc.so.6 /lib/libc.so.6 /usr/lib/aarch64-linux-gnu/libc.so.6 /usr/lib/ld-linux-aarch64.so.1 /usr/lib/ld-linux-armhf.so.3 /lib/ld-linux-armhf.so.3; do
    has "$p" && echo "  has $p"
  done
  # libc / libstdc++ version from the file name they link to
  for d in /usr/lib /lib /usr/lib/aarch64-linux-gnu; do
    dfs "ls -p $d" | awk -F/ '$6 ~ /^(libc-[0-9.]+\.so|libstdc\+\+\.so\.6\.[0-9.]+)$/ {print "  " "'"$d"'/" $6}'
  done
  # service names and mounts
  for d in /usr/lib/systemd/system /lib/systemd/system /etc/systemd/system; do
    dfs "ls -p $d" | awk -F/ '$6 ~ /^(acvs|inmusic-mpc|mpc)[^ ]*\.service$/ {print "  unit " "'"$d"'/" $6}'
  done
  if has /etc/fstab; then
    echo "  fstab (mount points):"
    cat_ /etc/fstab | grep -v '^#' | awk 'NF>=2 {print "    " $2 " " $3}'
  fi
  for f in /Settings/MPC/MPC.settings /data/Settings/MPC/MPC.settings; do
    if has "$f"; then
      cat_ "$f" > "$T/s.xml"
      echo "  $f: $(wc -c < "$T/s.xml") bytes, locations:"
      grep -o '<Location[^>]*>' "$T/s.xml" | sed 's/^/    /' | head -20
      grep -c 'pluginList-arm' "$T/s.xml" | sed 's/^/    pluginList-arm lines: /'
    fi
  done
done
