#!/usr/bin/env bash
# Offline tests in the gcc:12 Docker image (needs network: they read the live catalog and download one zip).
#   ONLY=<section> tests/run.sh   one section (devices addins links pick theme safety arch) in a minute or two; no ONLY: everything (about 9 minutes)
#   tests/run.sh            the wrapper host test, each fake device in tests/devices/, then the addin flow against
#                           an offline fixture (tests/fixture.py: three addin packages and a file:// catalog)
# A fake device is a shell script that builds the device's files inside the container: MPC.settings (the real format,
# trimmed), plugin folders, a stub systemctl. FS_ANY=1 lets the container's overlay filesystem count as internal storage.
# Add one for your model (copy its MPC.settings layout from the device.txt the plugin writes) and send it with your PR.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
MV="${MPC_VST:-$here/../..}"
python3 "$MV/tools/gen_vst.py" "$here/vst/vst.json" --params-h >/dev/null
MPC_VST="$MV" python3 "$here/tests/fixture.py"
docker run --rm -e ONLY -e TRACE -e DEV -v "$here":/p -v "$MV":/mv:ro -w /p gcc:12 bash -c '
set -eo pipefail; [ -z "$TRACE" ] || set -x
SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1"
want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }   # ONLY=safety: just that section (devices, addins, links, pick, theme, safety, arch)
export PM_TAPMS=40   # the double-tap window, short (FS_ANY builds only)
export PM_GLIBC=2.39   # a Gen2 / MPC OS 3.x glibc: the container has 2.36, which reads as OS 2.x and refused the live catalog packages (a 120 s wait per device)
gcc $SAN -std=gnu11 -w -Ivst/build src/manager.c /mv/tools/host_test.c /mv/wrapper/vst2_wrap.c -lpthread -ldl -lm -o /tmp/host_test
if want devices; then
(cd /tmp && ./host_test | tail -n 1)
gcc $SAN -DFS_ANY=1 -std=gnu11 -w src/manager.c tests/drive.c -lpthread -ldl -o /tmp/drive
for dev in tests/devices/${DEV:-*}.sh; do
  echo "== $dev"
  # each device starts from a clean filesystem
  rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts; mkdir -p /media
  echo "   $(date +%T)"
  sh "$dev"
  mkdir -p /tmp/openmpc-pm /tmp/zipcache; cp /tmp/zipcache/*.zip /tmp/openmpc-pm/ 2>/dev/null || true   # the catalog zip downloaded once, not once per device
  /tmp/drive > /tmp/drive.out && grep -E "location|target|problem" /tmp/openmpc-pm/device.txt
  # a device that can install must get the first catalog plugin to "ready" (apply_state 3): a scenario that quietly timed out hid a broken install path for weeks
  if grep -q "^problem: none" "${dev%.sh}.expect"; then grep -q "apply_state 3" /tmp/drive.out || { echo "FAIL $dev: the install never reached ready"; grep "status(" /tmp/drive.out | tail -n 2; exit 1; }; fi
  # tests/devices/<name>.banner: the red banner a device with a problem must show (plain words)
  [ ! -f "${dev%.sh}.banner" ] || grep -qF -- "$(cat "${dev%.sh}.banner")" /tmp/drive.out || { echo "FAIL $dev: banner is not: $(cat "${dev%.sh}.banner")"; grep banner /tmp/drive.out | head -n 2; exit 1; }
  cp -n /tmp/openmpc-pm/*.zip /tmp/zipcache/ 2>/dev/null || true
  # tests/devices/<name>.expect: lines that must be in device.txt (a test fails without them)
  exp="${dev%.sh}.expect"
  [ -f "$exp" ] || { echo "MISSING $exp: every fake device says what it must resolve to"; exit 1; }
  while IFS= read -r line; do
    grep -qxF -- "$line" /tmp/openmpc-pm/device.txt || { echo "FAIL $dev: device.txt lacks: $line"; exit 1; }
  done < "$exp"
done
fi # devices
if want addins; then
echo "== addins (offline fixture)"
fi # addins-head
gcc $SAN -DFS_ANY=1 -DCATALOG_URL=\"file:///p/vst/build/tests/catalog.json\" -std=gnu11 -w src/manager.c tests/drive.c -lpthread -ldl -o /tmp/drive_addins
if want addins; then
rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts; mkdir -p /media
sh tests/devices/mpc-one.sh && sh tests/addins.sh && /tmp/drive_addins addins
grep -E "^addin" /tmp/openmpc-pm/device.txt
echo "-- apply.sh:"; grep -E "^(sh|echo)" /tmp/openmpc-pm/apply.sh
grep -q "/install.sh'"'"' -y -n -t '"'"'/data/mpc-addins/beta-addin'"'"'" /tmp/openmpc-pm/apply.sh
grep -q "/data/mpc-addins/alpha-addin/uninstall.sh'"'"' -y -n -t '"'"'/data/mpc-addins/alpha-addin'"'"'" /tmp/openmpc-pm/apply.sh
! grep -q gamma /tmp/openmpc-pm/apply.sh
echo "addins OK"
fi # addins
if want links; then
echo "== links (offline fixture): a package that needs a symbolic link"
rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts; mkdir -p /media
sh tests/devices/mpc-one.sh
PM_NOLINKS=1 /tmp/drive_addins links > /tmp/links-no.out
grep -F "Linky: needs a drive that stores symbolic links, and /media/az01-internal/Synths does not. Nothing on the MPC was changed." /tmp/links-no.out
grep -q "apply_state 4" /tmp/links-no.out
[ ! -f /tmp/openmpc-pm/apply.sh ] || { echo "FAIL: apply.sh written for a refused package"; exit 1; }
rm -rf /tmp/openmpc-pm; /tmp/drive_addins links > /tmp/links-yes.out
! grep -q "symbolic links" /tmp/links-yes.out
grep -q "apply_state 3" /tmp/links-yes.out
grep -q "/linky.*install.sh\|Linky-1.0.0/install.sh" /tmp/openmpc-pm/apply.sh
echo "links OK"
fi # links
if want pick; then
echo "== pick (offline fixture): two usable locations, CHANGE on the restart prompt"
rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts
mkdir -p /media
sh tests/devices/two-targets.sh
/tmp/drive_addins pick > /tmp/pick.out
grep -qF "prompt: confirm=1 pick=1 |Install to: /sdcard/Synths  (1 of 2)|" /tmp/pick.out
grep -qF "after CHANGE: confirm=1 pick=1 |Install to: /media/CARD/Synths  (2 of 2)|" /tmp/pick.out
grep -qF -- "-t '"'"'/media/CARD/Synths'"'"'" /tmp/openmpc-pm/apply.sh
# the confirmed place is remembered: a fresh start names it first; with that drive gone it falls back and keeps the preference
grep -qx "/media/CARD/Synths" /media/az01-internal/.openmpcpm-target
rm -rf /tmp/openmpc-pm; /tmp/drive_addins pickshow > /tmp/pickshow.out
grep -qF "first prompt: confirm=1 pick=1 |Install to: /media/CARD/Synths  (2 of 2)|" /tmp/pickshow.out || { cat /tmp/pickshow.out; exit 1; }
printf "x /sdcard ext4 rw,relatime 0 0\n" > /tmp/pm-mounts   # the card is gone
rm -rf /tmp/openmpc-pm; /tmp/drive_addins pickshow > /tmp/pickgone.out
grep -qF "/sdcard/Synths" /tmp/openmpc-pm/apply.sh && ! grep -qF "/media/CARD" /tmp/openmpc-pm/apply.sh || { cat /tmp/pickgone.out; exit 1; }
grep -qx "/media/CARD/Synths" /media/az01-internal/.openmpcpm-target
echo "pick OK"
fi # pick
if want theme; then
echo "== theme (offline fixture): the switch, the prompt, and the skin swap in apply.sh"
rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts /tmp/own; mkdir -p /media
sh tests/devices/mpc-one.sh
for t in "Plugin Skins" "Plugin Skins.dark" "Plugin Skins.light"; do mkdir -p "/tmp/own/$t"; done
echo dark > "/tmp/own/Plugin Skins/.theme"; echo dark > "/tmp/own/Plugin Skins.dark/.theme"; echo light > "/tmp/own/Plugin Skins.light/.theme"
export PM_OWN=/tmp/own
# the default: no preference saved and the light skin in place: LIGHT, nothing pending
echo light > "/tmp/own/Plugin Skins/.theme"
/tmp/drive_addins themeshow > /tmp/theme0.out
grep -qF "start: can=1 theme=1 |LIGHT| apply_state=0" /tmp/theme0.out
# the user chose dark earlier and dark is in place: one tap (which MPC sends twice) switches to light
echo dark > "/tmp/own/Plugin Skins/.theme"; echo dark > /media/az01-internal/.openmpcpm-theme
/tmp/drive_addins theme > /tmp/theme.out
grep -qF "start: can=1 theme=0 |DARK| apply_state=0" /tmp/theme.out
grep -qF "pressed: theme=1 |LIGHT  after restart| apply_state=1" /tmp/theme.out
grep -qF "prompt: confirm=1 |Theme: light|" /tmp/theme.out
grep -qx light /media/az01-internal/.openmpcpm-theme
sh /tmp/openmpc-pm/apply.sh
[ "$(cat "/tmp/own/Plugin Skins/.theme")" = light ] || { echo "FAIL: the light skin was not swapped in"; exit 1; }
[ -d "/tmp/own/Plugin Skins.light" ] && [ -d "/tmp/own/Plugin Skins.dark" ] || { echo "FAIL: a skin variant was lost"; exit 1; }
/tmp/drive_addins themeshow > /tmp/theme2.out
grep -qF "start: can=1 theme=1 |LIGHT| apply_state=0" /tmp/theme2.out
unset PM_OWN
echo "theme OK"
fi # theme
if want safety; then
echo "== safety (offline fixture): refused before MPC stops; a failed install is rolled back and reported"
rm -rf /media /sdcard /nvme /synths /data /tmp/openmpc-pm /tmp/pm-mounts; mkdir -p /media
sh tests/devices/mpc-one.sh
/tmp/drive_addins one Wrongarch > /tmp/safe-arch.out
grep -qF "is built for aarch64, this MPC is armv7. Nothing on the MPC was changed." /tmp/safe-arch.out
rm -rf /tmp/openmpc-pm
/tmp/drive_addins one Evil > /tmp/safe-evil.out
grep -qF "has unsafe file names in its zip. Nothing on the MPC was changed." /tmp/safe-evil.out
[ ! -e /tmp/openmpc-pm/Evil ] || { echo "FAIL: an unsafe zip was unpacked"; exit 1; }
rm -rf /tmp/openmpc-pm
/tmp/drive_addins one Faily > /tmp/safe-fail.out
grep -q "apply_state 3" /tmp/safe-fail.out
T=$(grep -o "/media/[A-Za-z0-9_-]*/Synths\|/sdcard/Synths" /tmp/openmpc-pm/apply.sh | head -n 1)
mkdir -p "$T/Faily dir" && echo old > "$T/Faily dir/old"
sh /tmp/openmpc-pm/apply.sh
grep -q "^faily|fail|disk full" /tmp/openmpc-pm/result
[ -f "$T/Faily dir/old" ] && [ ! -e "$T/Faily dir/partial" ] || { echo "FAIL: the folder was not put back"; exit 1; }
# the same with a "big" folder (threshold 0 KB): the safety copy goes beside it on its own drive, and is gone afterwards
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Faily > /dev/null
mkdir -p "$T/Faily dir" && echo old > "$T/Faily dir/old"; rm -rf "$T/Faily dir/partial"
PM_SNAP_KB=0 sh /tmp/openmpc-pm/apply.sh
grep -q "^faily|fail|disk full" /tmp/openmpc-pm/result
[ -f "$T/Faily dir/old" ] && [ ! -e "$T/Faily dir/partial" ] && [ ! -e "$T/.pm-snap-faily" ] || { echo "FAIL: the big-folder rollback"; exit 1; }
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Faily > /dev/null
mkdir -p "$T/Faily dir/x"; mkdir -p "$T/.pm-snap-faily"
PM_SNAP_KB=0 sh /tmp/openmpc-pm/apply.sh
grep -q "^faily|fail|an earlier update left a safety copy" /tmp/openmpc-pm/result
rm -rf "$T/.pm-snap-faily" "$T/Faily dir"
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Faily > /dev/null
mkdir -p "$T/Faily dir"; echo old > "$T/Faily dir/old"; cp "$T/Faily dir/old" /tmp/old.keep
sh /tmp/openmpc-pm/apply.sh
/tmp/drive_addins status > /tmp/safe-status.out
grep -qF "Last apply: 0 done, 1 failed and put back as they were. Faily: disk full" /tmp/safe-status.out
/tmp/drive_addins one Newlib > /tmp/safe-glibc.out
grep -qF "Newlib: needs glibc 9.99 or newer, this MPC has" /tmp/safe-glibc.out
rm -rf /tmp/openmpc-pm; PM_GLIBC=2.39 /tmp/drive_addins one Oldos > /tmp/safe-os.out
grep -qF "Oldos: is for a different MPC OS, and this one reads as 3.x (from its glibc 2.39). Nothing on the MPC was changed." /tmp/safe-os.out
# a folder MPC does not list (plugin-meta.xml, no entry) is a card in INSTALLED; REGISTER adds its entry and nothing else changes
SY=$(find /media -type d -name Synths 2>/dev/null | head -n 1)
mkdir -p "$SY/Orphan Test Folder"; : > "$SY/Orphan Test Folder/o.so"
cat > "$SY/Orphan Test Folder/plugin-meta.xml" <<EOF
<PLUGIN name="Orphan Test" descriptiveName="Orphan Test" format="VST" category="Synth" manufacturer="OpenMPC"
 version="1.0" file="%payload-path%/Orphan Test Folder/o.so" uid="4f544f31" isInstrument="1" fileTime="0" infoUpdateTime="0"
 numInputs="0" numOutputs="2" isShell="0" hasARAExtension="0" uniqueId="1" pluginFormatName="VST"/>
EOF
SET=$(find /media /data -name MPC.settings 2>/dev/null | head -n 1 || true)
! grep -q 4f544f31 "$SET"
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one "Orphan Test" 1 1 > /tmp/safe-orphan.out
grep -q "apply_state 3" /tmp/safe-orphan.out || { cat /tmp/safe-orphan.out; exit 1; }
sh /tmp/openmpc-pm/apply.sh
grep -q "^orphan-Orphan-Test-Folder|ok|register" /tmp/openmpc-pm/result || { cat /tmp/openmpc-pm/result /tmp/openmpc-pm/apply.log; exit 1; }
grep -q "uid=\"4f544f31\"" "$SET" && grep -q "file=\"$SY/Orphan Test Folder/o.so\"" "$SET" || { echo "FAIL: the entry was not added"; exit 1; }
/tmp/drive_addins one "Orphan Test" 1 1 | grep -q "card 1: OR" && { echo "FAIL: a registered folder is still offered"; exit 1; }
rm -rf "$SY/Orphan Test Folder"
# a zip put on the drive (local-plugins/) is a card and installs by the same steps
LD=$(dirname "$(find /media -type d -name Synths 2>/dev/null | head -n 1)")/local-plugins
mkdir -p "$LD"; cp /p/vst/build/tests/Linky-1.0.0-mpc-armv7.zip "$LD/Mine-1.0.0.zip"
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Mine-1.0.0 1 > /tmp/safe-local.out
grep -q "apply_state 3" /tmp/safe-local.out || { cat /tmp/safe-local.out; ls -la "$LD"; exit 1; }
sh /tmp/openmpc-pm/apply.sh
grep -q "^local-Mine-1.0.0|ok|install local" /tmp/openmpc-pm/result
rm -rf "$LD"
# backups pile up: after a success only the newest 10 MPC.settings.bak-* stay, and nothing else is touched
SD=$(dirname "$(find /media /data -name MPC.settings 2>/dev/null | head -n 1)")
for k in 01 02 03 04 05 06 07 08 09 10 11 12 13 14; do echo b > "$SD/MPC.settings.bak-t$k"; touch -d "2026-01-$k 10:00" "$SD/MPC.settings.bak-t$k"; done
echo keep > "$SD/MPC.settings.keep"
# a success writes the history: Armonly (its install.sh exits 0); the apply also empties MPC image cache (MPC is stopped, nothing has it open)
mkdir -p /var/volatile/tmp/filmstrips; : > /var/volatile/tmp/filmstrips/temp_1.img; : > /var/volatile/tmp/filmstrips/keep.txt
rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Armonly > /dev/null
sh /tmp/openmpc-pm/apply.sh
[ ! -e /var/volatile/tmp/filmstrips/temp_1.img ] && [ -e /var/volatile/tmp/filmstrips/keep.txt ] || { echo "FAIL: the image cache was not emptied, or too much was"; ls /var/volatile/tmp/filmstrips; exit 1; }
grep -q "image cache emptied" /tmp/openmpc-pm/apply.log
grep -q "^armonly|ok|install 1.0.0" /tmp/openmpc-pm/result
/tmp/drive_addins status > /dev/null
H=$(find /media /data -name .openmpcpm-history.json 2>/dev/null | head -n 1 || true)
grep -q "\"id\": \"armonly\", \"version\": \"1.0.0\", \"installed\": true" "$H" || { echo "FAIL: no history entry"; cat "$H"; exit 1; }
echo '"'"'garbage'"'"' > "$H"; rm -rf /tmp/openmpc-pm; /tmp/drive_addins one Armonly > /dev/null; sh /tmp/openmpc-pm/apply.sh; /tmp/drive_addins status > /dev/null
[ "$(cat "$H")" = garbage ] || { echo "FAIL: a file that is not ours was overwritten"; exit 1; }
[ "$(ls "$SD" | grep -c '"'"'^MPC.settings.bak-'"'"')" -le 10 ] && [ ! -e "$SD/MPC.settings.bak-t01" ] && [ -e "$SD/MPC.settings.bak-t14" ] && [ -e "$SD/MPC.settings.keep" ] || { echo "FAIL: backup pruning"; ls "$SD"; exit 1; }
# the image cache nearly full (black patches on a Live III): a warning, and none when there is room
rm -rf /tmp/openmpc-pm; PM_CACHE_PCT=92 /tmp/drive_addins status > /tmp/safe-cache.out
grep -qF "image cache is 92% full: restart the MPC" /tmp/safe-cache.out || { cat /tmp/safe-cache.out; exit 1; }
rm -rf /tmp/openmpc-pm; PM_CACHE_PCT=10 /tmp/drive_addins status > /tmp/safe-cache2.out
! grep -q "image cache" /tmp/safe-cache2.out
echo "safety OK"
# last: after it the next "rm -rf /media" fails in the container (cause not found), so nothing may follow it
fi # safety
if want arch; then
echo "== arch (offline fixture): the aarch64 zip on Gen2, the armv7 one otherwise, and no card when there is none"
rm -rf /tmp/openmpc-pm; PM_ARCH=aarch64 /tmp/drive_addins arch > /tmp/arch-64.out
grep -q "card 1: DU" /tmp/arch-64.out      # Dual only: Armonly has no aarch64 zip
! grep -q "card 1: AR\|card 2: DU" /tmp/arch-64.out
grep -q "apply_state 3" /tmp/arch-64.out   # the aarch64 zip downloaded and verified
rm -rf /tmp/openmpc-pm; /tmp/drive_addins arch 2 > /tmp/arch-32.out
grep -q "card 1: AR" /tmp/arch-32.out && grep -q "card 2: DU" /tmp/arch-32.out
grep -q "apply_state 4" /tmp/arch-32.out   # Dual'"'"'s armv7 zip is missing: the install fails
echo "arch OK"
fi # arch
'
