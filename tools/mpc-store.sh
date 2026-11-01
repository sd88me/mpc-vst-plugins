#!/bin/sh
# mpc-store: install, update, remove and list catalog plugins and addins on an MPC OS device. BusyBox sh + wget/curl + unzip + sha256sum.
# Run on the device as root:
#   sh mpc-store.sh [-y] [-t <synths-dir>] [--url <catalog.tsv url>] [--dry-run] <command> [args]
#     list                       the catalog's plugins, what is installed ("manual" = a folder that was not put there by this script), what is newer
#     install <id[@version]>...  download, verify (sha256 from the catalog), then run each zip's own install.sh with MPC stopped once and started once
#                                (an older installer without -n runs first and restarts MPC by itself)
#     update [id...]             install the newest version of what is installed (a major version change needs --major)
#     remove <id>...             delete the plugin folder (your own files in it are kept) and its plugin-list entry; an addin runs the
#                                uninstall.sh in its folder (out of LD_PRELOAD, folder deleted)
# Dependencies (docs/CATALOG_SPEC.md, "Dependencies"): install and update add what a plugin needs to the same batch (the catalog's pick of
# the version), update an installed plugin that the batch would leave unmet when a newer one fits, and refuse a downgrade, a conflict,
# or removing what an installed plugin needs. --force does it anyway, with a warning.
#     prune [--keep N]           delete the older MPC.settings.bak-* backups (each install, removal and sync leaves one), keeping the newest N (default 10)
#     sync                       register plugin folders that have no entry and drop entries whose file is gone (sync.sh)
# Nothing on the device changes until every download has been verified and you confirmed (-y skips the question). MPC is stopped
# once and started once, and is started again if something fails. What was installed is remembered in <synths-dir>/.mpc-store.
# Addins (catalog kind "addin": libraries MPC preloads, docs/ADDINS.md) go to /data/mpc-addins/<id> instead of a Synths folder; each
# installed addin folder holds its version (addin.manifest) and its own uninstall.sh.
# The catalog is https://sd88me.github.io/mpc-vst-plugins/catalog.tsv (docs/CATALOG.md); the helper files it lists (sync.sh,
# plugin_list.awk) are fetched from the same folder and checked against the hashes in it. Build-yourself plugins are not here.
set -e
URL="${MPC_STORE_URL:-https://sd88me.github.io/mpc-vst-plugins/catalog.tsv}"
SYNTHS=/sdcard/Synths; YES=0; DRY=0; MAJOR=0; FORCE=0
ADDINS="${MPC_ADDINS:-/data/mpc-addins}"
TAB=$(printf '\t')
die() { echo "error: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
    case "$1" in
        -y) YES=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --major) MAJOR=1; shift ;;
        --force) FORCE=1; shift ;;
        -t) [ -n "$2" ] || die "-t needs a folder"; SYNTHS="$2"; shift 2 ;;
        --url) [ -n "$2" ] || die "--url needs a link"; URL="$2"; shift 2 ;;
        -*) die "unknown option $1 (see the top of this file)" ;;
        *) break ;;
    esac
done
ARCH="${MPC_STORE_ARCH:-$(uname -m)}"   # Gen1 and Force: armv7l; Gen2: aarch64, which takes the catalog's aarch64 zip (columns 17-19)
CMD="${1:-}"; [ -n "$CMD" ] || die "usage: sh mpc-store.sh [-y] [-t <synths-dir>] [--url <url>] [--dry-run] [--force] list|install|update|remove|prune|sync [ids]"
shift
case "$SYNTHS" in /*) ;; *) die "-t must be an absolute path" ;; esac
case "$SYNTHS" in *"&"*|*"|"*|*"\\"*) die "the Synths path may not contain & | or backslash" ;; esac
if [ -z "$MPC_INSTALL_TEST" ] && [ "$CMD" != list ] && [ $DRY = 0 ]; then
    [ "$(id -u)" = 0 ] || die "run as root"
    case "$ARCH" in armv7*|aarch64) ;; *) die "this is for MPC OS devices (Gen1 32-bit ARM or Gen2 aarch64); this one is $ARCH" ;; esac
    command -v systemctl >/dev/null || die "systemctl not found"
fi
# Gen2 (the Live III, MPC OS 3.x aarch64): /sdcard isn't mounted, so the writable internal drive is /nvme/Synths.
# Fall back to it when the /sdcard default is in effect and absent (harmless on Gen1/Force).
[ "$SYNTHS" = /sdcard/Synths ] && [ ! -d /sdcard/Synths ] && [ -d /nvme ] && SYNTHS=/nvme/Synths
# A Gen2 unit without NVMe (an MPC One, a Key 37) keeps user content on the loopback image mounted at /storage.
[ "$SYNTHS" = /sdcard/Synths ] && [ ! -d /sdcard/Synths ] && [ -d /storage/Synths ] && SYNTHS=/storage/Synths
SETTINGS="${MPC_SETTINGS:-$(ls /media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings 2>/dev/null | head -n 1)}"
W="${MPC_STORE_TMP:-/tmp}/mpc-store.$$"; mkdir -p "$W" || die "cannot create $W"
trap 'rm -rf "$W"' EXIT
STATE="$SYNTHS/.mpc-store"

fetch() {   # fetch <url> <dest>
    if command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1" || return 1
    elif command -v curl >/dev/null 2>&1; then curl -fsSL -o "$2" "$1" || return 1
    else die "neither wget nor curl found"; fi
}
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

echo "Reading the catalog: $URL"
fetch "$URL" "$W/catalog.tsv" || die "cannot download the catalog (is the device online?)"
head -n 1 "$W/catalog.tsv" | grep -q '^#mpc-catalog-tsv 1' || die "that is not a catalog this script understands"
BASE="${URL%/*}"

row() {   # row <id> [version]: the catalog line (latest when no version)
    awk -F'\t' -v id="$1" -v v="${2:-}" '$1 == "plugin" && $2 == id && ((v == "" && $4 == 1) || (v != "" && $3 == v)) { print; exit }' "$W/catalog.tsv"
}
col() { echo "$1" | cut -d"$TAB" -f"$2"; }   # plugin id version latest kind name skin uid param_compat size sha256 url user_data
manifest_value() {   # manifest_value <key> <file>: as the installer's shell reads it, quotes and a trailing comment dropped
    sed -n "s/^$1=//p" "$2" | head -n 1 | sed -e 's/^"\([^"]*\)".*/\1/;t' -e "s/^'\\([^']*\\)'.*/\\1/;t" -e 's/[[:space:]]*#.*//'
}
addin_version() {   # the version an installed addin's folder records ("" for one installed without a catalog release)
    case "$1" in ""|*/*|.*) return 0 ;; esac
    [ -f "$ADDINS/$1/addin.manifest" ] && manifest_value ADDIN_VERSION "$ADDINS/$1/addin.manifest" || true
}
installed_version() {
    v=$(addin_version "$1"); [ -z "$v" ] || { echo "$v"; return 0; }
    [ -f "$STATE" ] && awk -F'\t' -v id="$1" '$1 == id { print $2; exit }' "$STATE"
}
installed_compat() {
    v=$(addin_version "$1"); [ -z "$v" ] || { echo "${v%%.*}"; return 0; }
    [ -f "$STATE" ] && awk -F'\t' -v id="$1" '$1 == id { print $4; exit }' "$STATE"
}
target() { if [ "$1" = addin ]; then echo "$ADDINS/$2"; else echo "$SYNTHS"; fi; }   # target <kind> <id>: where install.sh puts it
record() {   # record <kind> <id> <version> <skin> <param_compat> (an addin's folder records its own version)
    [ "$1" != addin ] || return 0; shift
    mkdir -p "$SYNTHS"; touch "$STATE"
    awk -F'\t' -v id="$1" '$1 != id' "$STATE" > "$STATE.new" || true
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$STATE.new"; mv "$STATE.new" "$STATE"
}
forget() { [ -f "$STATE" ] || return 0; awk -F'\t' -v id="$1" '$1 != id' "$STATE" > "$STATE.new" || true; mv "$STATE.new" "$STATE"; }
helper() {   # helper <file>: download a helper listed in the catalog and check its hash
    [ -f "$W/h/$1" ] && return 0
    mkdir -p "$W/h"
    want=$(awk -F'\t' -v f="$1" '$1 == "#file" && $2 == f { print $3; exit }' "$W/catalog.tsv")
    [ -n "$want" ] || die "the catalog does not list $1"
    fetch "$BASE/$1" "$W/h/$1" || die "cannot download $1"
    [ "$(sha_of "$W/h/$1")" = "$want" ] || die "$1 does not match the hash in the catalog: not using it"
}
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
stop_mpc() {
    mpc_ctl stop
    trap 'mpc_ctl start; rm -rf "$W"' EXIT
    i=0; while pidof MPC >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done   # a test run has no MPC: it passes through
    if pidof MPC >/dev/null 2>&1; then die "MPC did not stop"; fi   # an `if`: as the function's last command, a failing `pidof` would make `set -e` end the script
}
confirm() {   # confirm <question>
    [ $YES = 1 ] && return 0
    printf "%s [y/N] " "$1"; read -r ok; case "$ok" in y|Y|yes) return 0 ;; *) echo "cancelled"; exit 1 ;; esac
}

# The device's glibc ("2.33"), or nothing when it cannot be told: MPC OS 2.x has about 2.32, MPC OS 3.x and the Force 2.39. Newer glibc prints its
# version when its library is run; older glibc keeps it in the file name (libc-2.33.so). MPC_STORE_LIBC lists other places to look (tests).
libc_version() {
    for f in ${MPC_STORE_LIBC:-/lib/libc.so.6 /lib/arm-linux-gnueabihf/libc.so.6 /usr/lib/libc.so.6 /lib/libc-*.so /usr/lib/libc-*.so}; do
        [ -e "$f" ] || continue
        v=""
        if [ -x "$f" ]; then v=$("$f" 2>/dev/null | sed -n 's/.*version \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1); fi
        [ -n "$v" ] || v=$(basename "$f" | sed -n 's/^libc-\([0-9][0-9]*\.[0-9][0-9]*\)\.so$/\1/p')
        if [ -n "$v" ]; then echo "$v"; return 0; fi
    done
    return 0
}
vgt() {   # vgt 2.34 2.33 succeeds when the first version is newer than the second
    awk -v a="$1" -v b="$2" 'BEGIN { n = split(a, x, "."); m = split(b, y, "."); for (i = 1; i <= (n > m ? n : m); i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 } exit 1 }'
}
# os_warnings <todo file>: say what will not work on this device; never stops the install (the catalog's os_compat and max_glibc columns)
os_warnings() {
    libc=$(libc_version); [ -n "$libc" ] || return 0
    while IFS=$TAB read -r kind id ver latest k name skin uid compat size sha url ud defer os mg _rest; do
        [ "$k" != addin ] || continue
        if [ -n "${mg:-}" ] && [ "$mg" != "-" ] && vgt "$mg" "$libc"; then
            echo "WARNING: $name $ver needs glibc $mg but this device has $libc: MPC will list it but it will not load."
        elif [ "${os:--}" != "-" ] && ! echo ",$os," | grep -q ',2\.x,' && vgt 2.34 "$libc"; then
            echo "NOTE: $name $ver is made for MPC OS 3.x. This device looks like MPC OS 2.x (glibc $libc), so its touchscreen page may stay empty; it still works from the Q-Links."
        fi
    done < "$1"
}
# Dependencies. Catalog column 22: ';'-joined id:rules:pick:pick64 (rules comma-joined, '*' for any version; pick the version to install
# on Gen1 / Gen2, '-' when there is none). Column 23: the ids it conflicts with (either side declaring it counts).
vsat() {   # vsat <X.Y.Z> <rules>: succeeds when the version meets every rule
    [ "$2" = "*" ] && return 0
    awk -v v="$1" -v rules="$2" 'function cmp(a, b,  x, y, i) { split(a, x, "."); split(b, y, "."); for (i = 1; i <= 3; i++) { if (x[i] + 0 > y[i] + 0) return 1; if (x[i] + 0 < y[i] + 0) return -1 } return 0 }
        BEGIN { n = split(rules, r, ","); for (i = 1; i <= n; i++) { op = r[i]; sub(/[0-9.]+$/, "", op); c = cmp(v, substr(r[i], length(op) + 1))
            if ((op == ">=" && c < 0) || (op == "<=" && c > 0) || (op == ">" && c <= 0) || (op == "<" && c >= 0) || (op == "=" && c != 0)) exit 1 } exit 0 }'
}
installed_ids() {   # the catalog plugins on the device: the state file, and every catalog plugin or addin whose folder is there (with or
    # without a recorded version), as the desktop app's installedVersions counts them
    { [ ! -f "$STATE" ] || cut -f1 "$STATE"
      awk -F'\t' '$1 == "plugin" && $4 == 1 { print $2 "\t" $5 "\t" $7 }' "$W/catalog.tsv" | while IFS=$TAB read -r id k skin; do
          if [ "$k" = addin ]; then where="$ADDINS/$id"; elif [ -n "$skin" ] && [ "$skin" != "-" ]; then where="$SYNTHS/$skin"; else continue; fi
          if [ -d "$where" ]; then echo "$id"; fi
      done; } | sort -u
}
present_version() {   # the installed version; '?' when its folder is there but nothing recorded a version; nothing when it is absent
    v=$(installed_version "$1" || true); [ -z "$v" ] || { echo "$v"; return 0; }
    r=$(row "$1" ""); [ -n "$r" ] || return 0
    if [ "$(col "$r" 5)" = addin ]; then where="$ADDINS/$1"; else where="$SYNTHS/$(col "$r" 7)"; fi
    if [ -d "$where" ]; then echo "?"; fi
    return 0
}
installed_row() {   # the catalog line of the installed version (the newest when that version is no longer listed)
    r=$(row "$1" "$(installed_version "$1" || true)"); [ -n "$r" ] || r=$(row "$1" ""); echo "$r"
}
plan_version() { awk -F'\t' -v id="$1" '$2 == id { print $3; exit }' "$W/plan"; }
dep_rules() { col "$1" 22 | tr ';' '\n' | awk -F: -v id="$2" '$1 == id { print $2; exit }'; }   # dep_rules <row> <id>
refuse() { if [ $FORCE = 1 ]; then echo "WARNING (--force): $*"; else die "$*. Nothing was changed (--force does it anyway)"; fi; }
major_ok() {   # major_ok <id> <catalog line> <who>: an installed plugin replaced for a dependency keeps update's --major rule
    oc=$(installed_compat "$1" || true); nc=$(col "$2" 9)
    if [ -n "$oc" ] && [ "$oc" != "$nc" ] && [ $MAJOR = 0 ]; then
        refuse "$3 would update $1 to $(col "$2" 3), a major change (saved projects using it will change). Run with --major to allow it"
    fi
}
# resolve: grow $W/plan (catalog lines) until every dependency of the batch and of what is installed fits, and check conflicts.
# The reasons for the lines it adds go to $W/why.
resolve() {
    : > "$W/why"; pass=0
    while :; do
        pass=$((pass + 1)); [ $pass -le 50 ] || die "the dependencies did not settle"
        added=0; cp "$W/plan" "$W/plan.pass"
        while IFS= read -r r; do   # what the batch needs
            pname=$(col "$r" 6); dl=$(col "$r" 22)
            [ -n "$dl" ] && [ "$dl" != "-" ] || continue
            for d in $(echo "$dl" | tr ';' ' '); do
                did=${d%%:*}; rest=${d#*:}; rules=${rest%%:*}; rest=${rest#*:}; pick=${rest%%:*}; [ "$ARCH" != aarch64 ] || pick=${rest#*:}
                pv=$(plan_version "$did")
                if [ -n "$pv" ]; then vsat "$pv" "$rules" || refuse "$pname needs $did $rules, but this batch installs $did $pv"; continue; fi
                cur=$(present_version "$did")
                if [ "$cur" = "?" ]; then echo "NOTE: $pname needs $did ($rules); its folder is there but no version was recorded, so it is left as it is"; continue; fi
                if [ -n "$cur" ] && vsat "$cur" "$rules"; then continue; fi
                if [ "$pick" = "-" ]; then refuse "$pname needs $did ($rules), and the catalog has no build of it for this device"; continue; fi
                if [ -n "$cur" ] && vgt "$cur" "$pick"; then refuse "$pname needs $did $rules: that would take $did back from $cur to $pick"; continue; fi
                dr=$(row "$did" "$pick"); [ -n "$dr" ] || die "the catalog names $did $pick but has no line for it"
                [ -z "$cur" ] || major_ok "$did" "$dr" "$pname"
                printf '%s\n' "$dr" >> "$W/plan"; added=1
                echo "  $did $pick: needed by $pname${cur:+ (replaces $cur)}" >> "$W/why"
            done
        done < "$W/plan.pass"
        for iid in $(installed_ids); do   # what is installed and stays: does the batch still fit it?
            [ -z "$(plan_version "$iid")" ] || continue
            ir=$(installed_row "$iid"); [ -n "$ir" ] || continue
            dl=$(col "$ir" 22); [ -n "$dl" ] && [ "$dl" != "-" ] || continue
            for d in $(echo "$dl" | tr ';' ' '); do
                did=${d%%:*}; rest=${d#*:}; rules=${rest%%:*}
                pv=$(plan_version "$did"); [ -n "$pv" ] || continue
                vsat "$pv" "$rules" && continue
                lr=$(row "$iid" ""); lrules=$(dep_rules "$lr" "$did")
                if [ -n "$lr" ] && [ "$(col "$lr" 3)" != "$(installed_version "$iid" || true)" ] && { [ -z "$lrules" ] || vsat "$pv" "$lrules"; }; then
                    major_ok "$iid" "$lr" "installing $did $pv"
                    printf '%s\n' "$lr" >> "$W/plan"; added=1
                    echo "  $iid $(col "$lr" 3): updated, because $(col "$ir" 6) $(col "$ir" 3) needs $did $rules" >> "$W/why"
                else refuse "$(col "$ir" 6) $(col "$ir" 3) is installed and needs $did $rules, but this batch installs $did $pv"; fi
                break
            done
        done
        [ $added = 1 ] || break
    done
    while IFS= read -r r; do   # conflicts, declared by either side
        pid=$(col "$r" 2)
        for c in $(col "$r" 23 | tr ',' ' '); do
            [ "$c" != "-" ] || continue
            if [ -n "$(plan_version "$c")" ] || [ -n "$(present_version "$c")" ]; then refuse "$(col "$r" 6) conflicts with $c"; fi
        done
        for oid in $(installed_ids); do
            [ "$oid" != "$pid" ] && [ -z "$(plan_version "$oid")" ] || continue
            if col "$(installed_row "$oid")" 23 | tr ',' '\n' | grep -qx "$pid"; then refuse "$oid (installed) conflicts with $(col "$r" 6)"; fi
        done
    done < "$W/plan"
}

# need_warnings <todo file>: the author's extra requirements (catalog column 20) and, for an addin, the installed or chosen addins that
# replace some of the same MPC functions where one of the two may not pass the calls on (column 21, catalog_build.py hook_overlaps_of).
# Never stops the install.
need_warnings() {
    while IFS= read -r r; do
        name=$(col "$r" 6); ver=$(col "$r" 3); req=$(col "$r" 20); hooks=$(col "$r" 21)
        [ -z "$req" ] || [ "$req" = "-" ] || echo "NEEDS: $name $ver: $req"
        [ -n "$hooks" ] && [ "$hooks" != "-" ] || continue
        for o in $(echo "$hooks" | tr ',' ' '); do
            [ -n "$(addin_version "$o")" ] || [ -d "$ADDINS/$o" ] || cut -d"$TAB" -f2 "$1" | grep -qx "$o" || continue
            on=$(awk -F'\t' -v id="$o" '$1 == "plugin" && $2 == id && $4 == 1 { print $6; exit }' "$W/catalog.tsv"); [ -n "$on" ] || on=$o
            echo "NOTE: $name and $on replace some of the same MPC functions, and one of them may not pass the calls on: together, one may stop working. If it does, remove one of them."
        done
    done < "$1"
}

do_list() {
    printf '%-18s %-9s %-10s %s\n' "ID" "LATEST" "INSTALLED" "NAME"
    awk -F'\t' '$1 == "plugin" && $4 == 1 { print $2 "\t" $3 "\t" $6 "\t" $7 "\t" $5 "\t" $15 "\t" $19 "\t" $12 }' "$W/catalog.tsv" | while IFS=$TAB read -r id ver name skin kind os url64 url1; do
        inst=$(installed_version "$id" || true)
        where="$SYNTHS/$skin"; [ "$kind" != addin ] || where="$ADDINS/$id"
        if [ -z "$inst" ]; then if [ -d "$where" ]; then inst="manual"; else inst="-"; fi; fi
        [ "$kind" != addin ] || name="$name (addin)"
        mark=""; if [ "$inst" != "-" ] && [ "$inst" != "manual" ] && [ "$inst" != "$ver" ]; then mark="  (update available)"; fi
        if [ "$os" = "3.x" ]; then mark="$mark  [MPC OS 3.x only]"; fi
        if [ "$ARCH" = aarch64 ] && { [ -z "$url64" ] || [ "$url64" = "-" ]; }; then mark="$mark  [no Gen2 build]"; fi
        if [ "$ARCH" != aarch64 ] && [ "$url1" = "-" ]; then mark="$mark  [Gen2 only]"; fi
        printf '%-18s %-9s %-10s %s%s\n' "$id" "$ver" "$inst" "$name" "$mark"
    done
}

# install_rows <catalog line>...: download and verify everything first, then one stop/start around all the installs
do_install_rows() {
    # Not built for this device's architecture: skipped before the dependency check, not fatal, so the rest of a batch (other
    # plugins, and whatever else a caller like the USB stick does around this, e.g. enabling SSH) still goes ahead.
    : > "$W/plan"; skipped=0
    for r in "$@"; do
        id=$(col "$r" 2); ver=$(col "$r" 3)
        if [ "$ARCH" != aarch64 ] && [ "$(col "$r" 12)" = "-" ]; then
            echo "skipping $id $ver: Gen2 only (aarch64), no build for this device"; skipped=$((skipped + 1)); continue
        fi
        if [ "$ARCH" = aarch64 ]; then u=$(col "$r" 19); if [ -z "$u" ] || [ "$u" = "-" ]; then
            echo "skipping $id $ver: no Gen2 (aarch64) build yet for this device"; skipped=$((skipped + 1)); continue
        fi; fi
        printf '%s\n' "$r" >> "$W/plan"
    done
    resolve
    if [ -s "$W/why" ]; then echo "Also installing, for the dependencies:"; cat "$W/why"; fi
    set --; while IFS= read -r line; do set -- "$@" "$line"; done < "$W/plan"
    n=0; : > "$W/todo"
    for r in "$@"; do
        id=$(col "$r" 2); ver=$(col "$r" 3); size=$(col "$r" 10); sha=$(col "$r" 11); url=$(col "$r" 12)
        if [ "$ARCH" = aarch64 ]; then   # a Gen2 device takes the aarch64 zip; the armv7 one would not load
            url=$(col "$r" 19); size=$(col "$r" 17); sha=$(col "$r" 18)
        fi
        echo "Downloading $id $ver ($((size / 1024)) KB)"
        fetch "$url" "$W/$id.zip" || die "cannot download $url"
        [ "$(sha_of "$W/$id.zip")" = "$sha" ] || die "$id $ver does not match its sha256 in the catalog: nothing was installed"
        mkdir -p "$W/x/$id"; unzip -q -o "$W/$id.zip" -d "$W/x/$id" || die "cannot unpack $id"
        rm -f "$W/$id.zip"
        dir=$(ls -d "$W/x/$id"/*/ 2>/dev/null | head -n 1); dir="${dir%/}"
        [ -f "$dir/install.sh" ] || die "$id $ver has no install.sh"
        # an installer without -n restarts MPC by itself and must run on its own; the rest run between one stop and one start
        if grep -q 'DEFER=' "$dir/install.sh"; then echo 1 > "$W/defer.$id"; else echo 0 > "$W/defer.$id"; fi
        printf '%s\n' "$r" >> "$W/todo"; n=$((n + 1))
    done
    if [ $n -eq 0 ]; then
        if [ $skipped -gt 0 ]; then echo "Nothing to install: $skipped skipped (no build for this device)."
        else echo "Nothing to install."; fi
        return 0
    fi
    echo "Verified. About to install:"; awk -F'\t' '{ print "  " $2 " " $3 " (" $6 ($5 == "addin" ? ", an addin" : "") ")" }' "$W/todo"
    os_warnings "$W/todo"
    need_warnings "$W/todo"
    [ $DRY = 1 ] && { echo "Dry run: nothing changed."; return 0; }
    confirm "MPC will be stopped and restarted. Save your project first. Continue?"
    ok=0; failed=0
    while IFS=$TAB read -r kind id ver latest k name skin uid compat size sha url ud; do   # older installers first, each restarts MPC itself
        [ "$(cat "$W/defer.$id")" = 0 ] || continue
        dir=$(ls -d "$W/x/$id"/*/ | head -n 1); dir="${dir%/}"
        echo "Installing $name $ver (its installer restarts MPC by itself)"
        if sh "$dir/install.sh" -y -t "$(target "$k" "$id")"; then record "$k" "$id" "$ver" "$skin" "$compat"; ok=$((ok + 1))
        else echo "error: $name failed; continuing would leave a mixed state, so stopping here" >&2; failed=1; break; fi
    done < "$W/todo"
    batch=0; for f in "$W"/defer.*; do if [ "$(cat "$f")" = 1 ]; then batch=1; fi; done
    if [ $failed = 0 ] && [ $batch = 1 ]; then
        stop_mpc   # one stop here, one start when the script ends (also after a failure)
        while IFS=$TAB read -r kind id ver latest k name skin uid compat size sha url ud; do
            [ "$(cat "$W/defer.$id")" = 1 ] || continue
            dir=$(ls -d "$W/x/$id"/*/ | head -n 1); dir="${dir%/}"
            echo "Installing $name $ver"
            if sh "$dir/install.sh" -y -n -t "$(target "$k" "$id")"; then record "$k" "$id" "$ver" "$skin" "$compat"; ok=$((ok + 1))
            else echo "error: $name failed; continuing would leave a mixed state, so stopping here" >&2; break; fi
        done < "$W/todo"
    fi
    if [ $skipped -gt 0 ]; then echo "Installed $ok of $n ($skipped skipped: no build for this device)."
    else echo "Installed $ok of $n."; fi
    [ $ok = $n ] || return 1
}

do_install() {
    [ $# -gt 0 ] || die "install what? (see: list)"
    : > "$W/rows"
    for a in "$@"; do
        id="${a%%@*}"; ver=""; case "$a" in *@*) ver="${a#*@}" ;; esac
        r=$(row "$id" "$ver"); [ -n "$r" ] || die "$a is not in the catalog as a downloadable plugin (build-yourself plugins are built from your own files: see their README)"
        printf '%s\n' "$r" >> "$W/rows"
    done
    set --; while IFS= read -r line; do set -- "$@" "$line"; done < "$W/rows"
    do_install_rows "$@"
}

do_update() {
    ids="$*"
    if [ -z "$ids" ]; then
        [ ! -f "$STATE" ] || ids=$(cut -f1 "$STATE")
        for d in "$ADDINS"/*/; do [ -d "$d" ] || continue; d="${d%/}"; d="${d##*/}"; [ -z "$(addin_version "$d")" ] || ids="$ids $d"; done
    fi
    [ -n "$ids" ] || { echo "Nothing installed through mpc-store yet."; return 0; }
    set --
    for id in $ids; do
        cur=$(installed_version "$id" || true); [ -n "$cur" ] || { echo "$id: not installed through mpc-store, skipped"; continue; }
        r=$(row "$id" ""); [ -n "$r" ] || { echo "$id: not in the catalog any more, skipped"; continue; }
        ver=$(col "$r" 3); [ "$ver" != "$cur" ] || { echo "$id: up to date ($cur)"; continue; }
        oc=$(installed_compat "$id" || true); nc=$(col "$r" 9)
        if [ -n "$oc" ] && [ "$oc" != "$nc" ] && [ $MAJOR = 0 ]; then
            echo "$id: $ver is a major change (saved projects using it will change): not updated. Run with --major to allow it."; continue
        fi
        echo "$id: $cur -> $ver"; set -- "$@" "$r"
    done
    [ $# -gt 0 ] || { echo "Everything is up to date."; return 0; }
    do_install_rows "$@"
}

do_remove() {
    [ $# -gt 0 ] || die "remove what?"
    for oid in $(installed_ids); do   # an installed plugin that stays must not lose what it needs
        case " $* " in *" $oid "*) continue ;; esac
        for d in $(col "$(installed_row "$oid")" 22 | tr ';' ' '); do
            [ "$d" != "-" ] || continue
            case " $* " in *" ${d%%:*} "*) refuse "$oid is installed and needs ${d%%:*}: remove $oid too, or keep ${d%%:*}" ;; esac
        done
    done
    plugins=0
    for id in "$@"; do
        r=$(row "$id" ""); [ -n "$r" ] || die "$id is not in the catalog"
        if [ "$(col "$r" 5)" = addin ]; then   # an addin removes itself with the uninstall.sh its folder carries
            [ -f "$ADDINS/$id/uninstall.sh" ] || die "$id is not installed in $ADDINS (or its folder was made by hand: remove it by hand)"
            echo "Will remove the addin $ADDINS/$id (and take it out of MPC's LD_PRELOAD)"
            continue
        fi
        plugins=$((plugins + 1))
        skin=$(col "$r" 7); [ -d "$SYNTHS/$skin" ] || die "$id is not installed in $SYNTHS"
        echo "Will remove $SYNTHS/$skin (keeping: $(col "$r" 13))"
    done
    [ $DRY = 1 ] && { echo "Dry run: nothing changed."; return 0; }
    confirm "MPC will be stopped once and restarted at the end. Save your project first. Continue?"
    if [ $plugins -gt 0 ]; then
        helper plugin_list.awk
        [ -n "$SETTINGS" ] && [ -f "$SETTINGS" ] || die "MPC.settings not found"
    fi
    stop_mpc
    if [ $plugins -gt 0 ]; then BAK="$SETTINGS.bak-store-$(date +%Y%m%d-%H%M%S)"; cp "$SETTINGS" "$BAK"; cp "$SETTINGS" "$W/cur"; fi
    for id in "$@"; do
        r=$(row "$id" ""); skin=$(col "$r" 7); uid=$(col "$r" 8); keep=$(col "$r" 13)
        if [ "$(col "$r" 5)" = addin ]; then
            sh "$ADDINS/$id/uninstall.sh" -y -n -t "$ADDINS/$id" || die "removing the addin $id failed"
            forget "$id"; echo "removed $id"; continue
        fi
        awk -v mode=remove -v file="$SYNTHS/$skin/.none" -v uid="$uid" -f "$W/h/plugin_list.awk" "$W/cur" > "$W/next" && mv "$W/next" "$W/cur"
        if [ -n "$keep" ] && [ "$keep" != "-" ]; then   # keep the user's own folders: move them out, delete the rest, move them back
            mkdir -p "$W/keep/$id"; oldifs=$IFS; IFS=,
            for d in $keep; do
                if [ -e "$SYNTHS/$skin/$d" ]; then mkdir -p "$W/keep/$id/$(dirname "$d")"; mv "$SYNTHS/$skin/$d" "$W/keep/$id/$d"; fi
            done
            IFS=$oldifs
            rm -rf "$SYNTHS/$skin"
            if [ -n "$(ls -A "$W/keep/$id" 2>/dev/null)" ]; then
                mkdir -p "$SYNTHS/$skin"; cp -a "$W/keep/$id/." "$SYNTHS/$skin/"; echo "kept your files in $SYNTHS/$skin"
            fi
        else rm -rf "$SYNTHS/$skin"; fi
        forget "$id"; echo "removed $id"
    done
    if [ $plugins = 0 ]; then echo "Done. MPC is being started."; return 0; fi
    grep -q '<PROPERTIES' "$W/cur" && grep -q '</PROPERTIES>' "$W/cur" || die "edited settings lost their root element; MPC.settings unchanged"
    if command -v python3 >/dev/null; then
        python3 -c 'import sys, xml.etree.ElementTree as E; E.parse(sys.argv[1])' "$W/cur" 2>/dev/null || die "edited settings aren't valid XML; MPC.settings unchanged"
    fi
    cp "$W/cur" "$SETTINGS.new" && mv "$SETTINGS.new" "$SETTINGS"; sync
    echo "Done. Settings backup: $BAK. MPC is being started."
}

do_prune() {
    keep=10
    while [ $# -gt 0 ]; do
        case "$1" in
            --keep) [ -n "${2:-}" ] || die "--keep needs a number"; keep="$2"; shift 2 ;;
            *) die "usage: prune [--keep N]" ;;
        esac
    done
    case "$keep" in ""|*[!0-9]*) die "--keep needs a whole number" ;; esac
    [ "$keep" -ge 1 ] || die "--keep must be at least 1: the newest backup is never deleted"
    [ -n "$SETTINGS" ] && [ -f "$SETTINGS" ] || die "MPC.settings not found"
    ls -t "$SETTINGS".bak-* 2>/dev/null > "$W/baks" || true   # newest first; only files named like the ones this tooling makes
    total=$(wc -l < "$W/baks" | tr -d ' ')
    if [ "$total" -le "$keep" ]; then echo "$total backup(s) of MPC.settings: nothing to delete (keeping the newest $keep)."; return 0; fi
    del=$((total - keep))
    tail -n +$((keep + 1)) "$W/baks" > "$W/old"
    echo "$total backups of MPC.settings: keeping the newest $keep, deleting the $del older ones."
    [ $DRY = 1 ] && { echo "Dry run: nothing deleted."; return 0; }
    confirm "Delete $del older backup(s)? MPC is not touched."
    while IFS= read -r f; do rm -f -- "$f"; done < "$W/old"
    echo "Deleted $del."
}

do_sync() {
    helper sync.sh; helper plugin_list.awk
    args=""; [ $YES = 1 ] && args="-y"; [ $DRY = 1 ] && args="$args --dry-run"
    # shellcheck disable=SC2086
    sh "$W/h/sync.sh" $args -t "$SYNTHS"
}

case "$CMD" in
    list) do_list ;;
    install) do_install "$@" ;;
    update) do_update "$@" ;;
    remove) do_remove "$@" ;;
    prune) do_prune "$@" ;;
    sync) do_sync ;;
    *) die "unknown command $CMD (list, install, update, remove, prune, sync)" ;;
esac
