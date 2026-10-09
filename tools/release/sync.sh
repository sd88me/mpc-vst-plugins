#!/bin/sh
# Makes MPC's plugin list match the plugin folders on disk, for the folders this repo's installers create. Run on the device as root:
#   sh sync.sh [-y] [-n] [--dry-run] [-t <synths-dir>]...
# Looks at <synths-dir>/*/plugin-meta.xml (default: /sdcard/Synths, then every /media/*/Synths; the same folder seen through two
# roots is registered once, the first root wins), and in MPC.settings' pluginList-arm it
#   - adds a folder that has no entry (its plugin-meta.xml, with %payload-path% replaced by the Synths folder),
#   - replaces an entry with the same uid whose .so is gone,
#   - removes an entry that points into a Synths folder but whose .so is gone,
# (a folder whose .so is missing is ignored) and leaves every other entry alone (plugins registered another way, other tools' entries). Nothing to do = no MPC restart.
# Backs up MPC.settings, checks the result, stops MPC before the edit and starts it after (-n: the caller does that, as for
# install.sh -n). --dry-run only prints what it would do. Same folder rule as MockbaMod's vstscanner.sh (/media/*/Synths/*/
# plugin-meta.xml), which instead rebuilds the whole list. Needs plugin_list.awk next to it.
set -e
cd "$(dirname "$0")"
YES=0; DEFER=0; DRY=0; ROOTS=""
die() { echo "error: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
    case "$1" in
        -y) YES=1; shift ;;
        -n) DEFER=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -t) [ -n "$2" ] || die "-t needs a folder"; case "$2" in /*) ;; *) die "-t must be an absolute path" ;; esac
            case "$2" in *"&"*|*"|"*|*"\\"*) die "the Synths path may not contain & | or backslash" ;; esac
            ROOTS="$ROOTS
$2"; shift 2 ;;
        *) die "usage: sh sync.sh [-y] [-n] [--dry-run] [-t <synths-dir>]..." ;;
    esac
done
[ -f plugin_list.awk ] || die "plugin_list.awk must be next to sync.sh"

if [ -z "$MPC_INSTALL_TEST" ]; then
    [ "$(id -u)" = 0 ] || die "run as root"
    command -v systemctl >/dev/null || die "systemctl not found"
fi
SETTINGS="${MPC_SETTINGS:-$(ls /media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings 2>/dev/null | head -n 1)}"
[ -n "$SETTINGS" ] && [ -f "$SETTINGS" ] || die "MPC.settings not found (not an MPC OS device?)"
if [ -z "$ROOTS" ]; then
    ROOTS="/sdcard/Synths"
    # Gen2: MPC.settings lists /synths/Synths as a content location (see docs/NOTES.md, 2026-10-10); scan it
    # too when present. Harmless on Gen1/Force, where /synths doesn't exist.
    [ -d /synths/Synths ] && ROOTS="$ROOTS
/synths/Synths"
    for r in /media/*/Synths; do [ -d "$r" ] && ROOTS="$ROOTS
$r"; done
fi

W="$SETTINGS.sync.$$"; mkdir "$W" || die "cannot create a work folder next to MPC.settings"
trap 'rm -rf "$W"' EXIT
TAB=$(printf '\t')

# what is registered now: uid<TAB>file
tr '\n' ' ' < "$SETTINGS" | grep -o '<PLUGIN [^>]*>' | awk '{
    f = ""; u = ""
    if (match($0, / file="[^"]*"/)) f = substr($0, RSTART + 7, RLENGTH - 8)
    if (match($0, / uid="[^"]*"/))  u = substr($0, RSTART + 6, RLENGTH - 7)
    printf "%s\t%s\n", (u == "" ? "-" : u), f }' > "$W/have" || true

# what is on disk: uid<TAB>file<TAB>plugin-meta.xml, first root wins per uid
: > "$W/want"
echo "$ROOTS" | while IFS= read -r root; do
    [ -n "$root" ] || continue
    for m in "$root"/*/plugin-meta.xml; do
        [ -f "$m" ] || continue
        line=$(sed "s|%payload-path%|$root|g" "$m" | tr '\n' ' ' | grep -o '<PLUGIN [^>]*>' | head -n 1) || true
        [ -n "$line" ] || continue
        uid=$(echo "$line" | sed -n 's/.* uid="\([^"]*\)".*/\1/p'); file=$(echo "$line" | sed -n 's/.* file="\([^"]*\)".*/\1/p')
        [ -n "$uid" ] && [ -n "$file" ] || continue
        [ -f "$file" ] || { echo "  skip   $m (its plugin file $file is missing)" >&2; continue; }
        grep -q "^$uid$TAB" "$W/want" || printf '%s\t%s\t%s\n' "$uid" "$file" "$m" >> "$W/want"
    done
done

# the plan
: > "$W/add"; : > "$W/drop"
while IFS=$TAB read -r uid file meta; do
    [ -n "$uid" ] || continue
    ok=0
    while IFS=$TAB read -r hu hf; do
        [ "$hu" = "$uid" ] && [ -f "$hf" ] && ok=1
    done < "$W/have"
    [ $ok = 1 ] || printf '%s\t%s\t%s\n' "$uid" "$file" "$meta" >> "$W/add"
done < "$W/want"
while IFS=$TAB read -r hu hf; do
    case "$hf" in */Synths/*) [ -f "$hf" ] || printf '%s\t%s\n' "$hu" "$hf" >> "$W/drop" ;; esac
done < "$W/have"

nadd=$(wc -l < "$W/add" | tr -d ' '); ndrop=$(wc -l < "$W/drop" | tr -d ' ')
while IFS=$TAB read -r uid file meta; do echo "  add    $file"; done < "$W/add"
while IFS=$TAB read -r hu hf; do echo "  remove $hf (file is gone)"; done < "$W/drop"
if [ $nadd = 0 ] && [ $ndrop = 0 ]; then echo "Nothing to do: the plugin list already matches the plugin folders."; exit 0; fi
[ $DRY = 1 ] && { echo "Dry run: $nadd to add, $ndrop to remove; nothing changed."; exit 0; }

if [ $YES = 0 ]; then
    if [ $DEFER = 1 ]; then msg="MPC must already be stopped."; else msg="MPC will be stopped and restarted. Save your project first."; fi
    printf "%s Continue? [y/N] " "$msg"
    read -r ok; case "$ok" in y|Y|yes) ;; *) echo "cancelled"; exit 1 ;; esac
fi

# MPC's service is acvs on stock firmware, inmusic-mpc on Hakai-enabled systems; use whichever exists (acvs if neither is found).
mpc_service() {
    if systemctl cat acvs >/dev/null 2>&1; then echo acvs
    elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
    else echo acvs; fi
}
mpc_ctl() {   # stop | start; a test run logs the call to $MPC_TEST_LOG instead of touching MPC
    if [ -n "$MPC_INSTALL_TEST" ]; then [ -z "$MPC_TEST_LOG" ] || echo "$1" >> "$MPC_TEST_LOG"; return 0; fi
    systemctl "$1" "$(mpc_service)"
}
if [ $DEFER = 1 ]; then
    [ -n "$MPC_INSTALL_TEST" ] || ! pidof MPC >/dev/null || die "MPC is running: with -n stop it first (stop the MPC service first, see INSTALL.md)"
else
    mpc_ctl stop
    trap 'mpc_ctl start; rm -rf "$W"' EXIT
    if [ -z "$MPC_INSTALL_TEST" ]; then
        i=0; while pidof MPC >/dev/null && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
        pidof MPC >/dev/null && die "MPC did not stop"
    fi
fi

BAK="$SETTINGS.bak-sync-$(date +%Y%m%d-%H%M%S)"
cp "$SETTINGS" "$BAK"
cp "$SETTINGS" "$W/cur"
while IFS=$TAB read -r hu hf; do   # dropped entries: by file
    awk -v mode=remove -v file="$hf" -f plugin_list.awk "$W/cur" > "$W/next" && mv "$W/next" "$W/cur"
done < "$W/drop"
while IFS=$TAB read -r uid file meta; do   # added or replaced: same uid or same file goes first
    root=$(dirname "$(dirname "$meta")")
    sed "s|%payload-path%|$root|g" "$meta" | tr '\n' ' ' | grep -o '<PLUGIN [^>]*>' | head -n 1 > "$W/entry"
    # same key choice as install.sh (see plugin_list.awk): the installed folder carries its own mpc-plugin.json
    pkgarch=$(sed -n 's/.*"arch": *"\([a-z0-9]*\)".*/\1/p' "$(dirname "$meta")/mpc-plugin.json" 2>/dev/null | head -n 1)
    case "$pkgarch" in aarch64) listkey=pluginList-arm-64bit ;; *) listkey=pluginList-arm ;; esac
    awk -v mode=add -v file="$file" -v uid="$uid" -v entryfile="$W/entry" -v listkey="$listkey" -f plugin_list.awk "$W/cur" > "$W/next" && mv "$W/next" "$W/cur"
done < "$W/add"
# check: every planned uid is there exactly once, the root element is intact, valid XML when python3 exists
while IFS=$TAB read -r uid file meta; do
    n=$(grep -c " uid=\"$uid\"" "$W/cur" || true)
    [ "$n" = 1 ] || die "settings edit failed (uid $uid appears $n times); MPC.settings unchanged"
done < "$W/add"
grep -q '<PROPERTIES' "$W/cur" && grep -q '</PROPERTIES>' "$W/cur" || die "edited settings lost their root element; MPC.settings unchanged"
if command -v python3 >/dev/null; then
    python3 -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$W/cur" 2>/dev/null || die "edited settings aren't valid XML; MPC.settings unchanged"
fi
cp "$W/cur" "$SETTINGS.new" && mv "$SETTINGS.new" "$SETTINGS"
sync
echo "Done: $nadd added, $ndrop removed. Settings backup: $BAK"
