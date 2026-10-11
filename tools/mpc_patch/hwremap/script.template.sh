#!/bin/sh
# hwremap-patch.sh: remap hardware buttons on a standalone MPC or Force. An LD_PRELOAD shim
# (hwremap) sits on the controller's MIDI and turns a chosen button into other buttons, a pad
# or a touchscreen tap. The library and the two example configs are embedded below.
#
# ADVANCED AND OPT-IN. It changes how the device starts MPC. Read the warnings. Not part of any plugin.
#
#   sh hwremap-patch.sh status
#   sh hwremap-patch.sh options [--layout mpc-live|force]
#   sh hwremap-patch.sh install [--layout mpc-live|force] [--options LIST] [--with LIST] [--without LIST] [--confirmed]
#   sh hwremap-patch.sh uninstall [--confirmed]
#   sh hwremap-patch.sh help
# Run it ON the device as root, after copying this one file there.
# The Force map is made of options (which button does what). On a terminal install asks which to
# turn on; --options (an exact list, or all / none), --with and --without choose without asking, and
# options lists them. Only a config that does not exist yet is written, so the choice applies to a
# first install; edit /sdcard/hwremap.conf afterwards.
#
# Two install styles, picked from the device:
#   Hakai (a launcher /usr/bin/az01-launch-MPC): the library goes to /usr/lib/hwremap.so and that
#     launcher's LD_PRELOAD lines gain it. The root filesystem is remounted writable for a moment.
#   Force and other images that start MPC from systemd (acvs or inmusic-mpc): the library goes to
#     /data/hwremap/hwremap.so and a drop-in adds it to the service's LD_PRELOAD, keeping whatever
#     was already preloaded.
# The default button map is configs/mpc-live.conf or configs/force.conf, written to /sdcard/hwremap.conf
# only when that file does not exist yet. --layout picks which one. Edits of the config apply on the
# next button press and do not need this script again.
#
# The shim is hwremap from https://github.com/mmiroshnikov/akai_standalone_remap
# (commit 9d2aa57a570b0c4788f88b04ca242bb82176c380, MIT). Its author tried it on an MPC Live
# (Hakai, MPC 3.9.1) and a Force (stock firmware 3.9.0). This installer has been tested offline only.
#
# WARNINGS
#  - MPC is stopped and started. Save the project first.
#  - A firmware update can wipe the launcher edit or the drop-in. Run status, then install again.
#  - The default MPC Live map sends Pad Bank A-D and + / - to the Mode Menu, so those buttons no
#    longer do their old job until you hold Shift or edit the config. The Force map changes Mixer,
#    Menu and Knobs (see the guide).
#  - uninstall puts the launcher or the drop-in back and removes the library. A config you edited
#    is left in place; an untouched default config is removed.
#  - Not affiliated with Akai Professional / inMusic.
#
# Version 0.2.0. Source: tools/mpc_patch/hwremap of the repository this came from.
set -u
VERSION=0.2.0
P=${HW_PREFIX:-}                 # tests only: a folder that stands for /
MARK=$P/data/hwremap
CONF=$P/sdcard/hwremap.conf
LAUNCHER=$P/usr/bin/az01-launch-MPC
BK_ROOT=$P/data/mpc-vst-plugins/backups
SO_LAUNCHER=/usr/lib/hwremap.so
SO_DROPIN=/data/hwremap/hwremap.so
FAILED=0
STOPPED=0
ROOT_RW=0
WROTE_CONF=0
SVC=
STYLE=
LAYOUT=
OPT_SET=
OPT_WITH=
OPT_WITHOUT=
OPTS=
die() { echo "ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# --- unpack the library and the two default configs (generated; do not edit the markers)
write_so() { # $1 destination
    dest=$1
    tmp=$(mktemp) || die "cannot make a temporary file"
    # LC_ALL=C: gawk in a UTF-8 locale writes printf "%c" values above 127 as multi-byte characters, which corrupts the library
    LC_ALL=C awk 'BEGIN { for (i = 0; i < 16; i++) { d = sprintf("%x", i); v[d] = i; v[toupper(d)] = i } }
        /^$/ { next }
        { s = $0; n = length(s); for (i = 1; i <= n; i += 2) printf "%c", v[substr(s, i, 1)] * 16 + v[substr(s, i + 1, 1)] }' <<'HW_SO_HEX' > "$tmp" || { rm -f "$tmp"; die "could not unpack the library"; }
@@SO_HEX@@
HW_SO_HEX
    # the awk unpacker can drop or mangle bytes on a device (NULs): never put a library into MPC's LD_PRELOAD unchecked
    if [ "$(wc -c < "$tmp" | tr -d ' ')" != "@@SO_SIZE@@" ] || [ "$(sha256sum < "$tmp" | cut -d' ' -f1)" != "@@SO_SHA256@@" ]; then
        rm -f "$tmp"; die "the library did not unpack correctly (size or sha256 differs); nothing was changed"
    fi
    mv "$tmp" "$dest" || die "cannot install the library"
    chmod 755 "$dest" || die "cannot mark the library executable"
}
conf_raw() { # $1 mpc-live|force: the embedded map, option markers included
    case "$1" in
        mpc-live) cat <<'HW_CONF_LIVE'
@@CONF_LIVE@@HW_CONF_LIVE
            ;;
        force) cat <<'HW_CONF_FORCE'
@@CONF_FORCE@@HW_CONF_FORCE
            ;;
        *) die "unknown layout: $1" ;;
    esac
}
conf_options() { # $1 layout: one "name<TAB>on|off<TAB>description" line per option
    conf_raw "$1" | awk '/^#@option[ \t]/ { n = $2; d = $3; $1 = ""; $2 = ""; $3 = ""; sub(/^[ \t]+/, ""); printf "%s\t%s\t%s\n", n, d, $0 }'
}
render_conf() { # $1 layout, $2 chosen options (space separated): the map with only those blocks
    conf_raw "$1" | awk -v sel=" $2 " '
        function chosen(n) { return index(sel, " " n " ") > 0 }
        function holds(expr,    alts, na, i, terms, nt, j, t, ok) {
            na = split(expr, alts, "|")
            for (i = 1; i <= na; i++) {
                nt = split(alts[i], terms, "&")
                ok = 1
                for (j = 1; j <= nt; j++) {
                    t = terms[j]
                    if (substr(t, 1, 1) == "!") { if (chosen(substr(t, 2))) ok = 0 }
                    else if (!chosen(t)) ok = 0
                }
                if (ok) return 1
            }
            return 0
        }
        BEGIN { inc = 1 }
        /^#@always/ { inc = 1; next }
        /^#@option[ \t]/ {
            n = $2; $1 = ""; $2 = ""; $3 = ""; sub(/^[ \t]+/, "")
            inc = chosen(n)
            if (inc) print "# " $0
            next
        }
        /^#@if[ \t]/ { inc = holds($2); next }
        /^#@end/ { inc = 1; next }
        /^#@hide/ { inc = 0; next }
        /^#@show/ { inc = 1; next }
        /^#@/ { print "ERROR: unknown marker " $1 > "/dev/stderr"; exit 2 }
        inc { print }
    '
}
write_default_conf() { # $1 path, $2 mpc-live|force, $3 chosen options
    render_conf "$2" "$3" > "$1"
}
tty_ok() { ( : < /dev/tty ) 2>/dev/null; } # a failed redirect on a builtin ends a BusyBox shell, so try it in a subshell
list_has() { case " $1 " in *" $2 "*) return 0 ;; esac; return 1; }
list_add() { if list_has "$1" "$2"; then echo "$1"; else echo "${1:+$1 }$2"; fi; }
list_del() { out=; for x in $1; do [ "$x" = "$2" ] || out="${out:+$out }$x"; done; echo "$out"; }
choose_options() { # sets OPTS from the layout's defaults and the --options / --with / --without flags
    names=$(conf_options "$LAYOUT" | cut -f1 | tr '\n' ' ')
    names=${names% }
    if [ -z "$names" ]; then
        [ -z "$OPT_SET$OPT_WITH$OPT_WITHOUT" ] || die "the $LAYOUT map has no options"
        OPTS=; return
    fi
    case "$OPT_SET" in
        "") OPTS=$(conf_options "$LAYOUT" | awk -F'\t' '$2 == "on" { printf "%s ", $1 }'); OPTS=${OPTS% } ;;
        all) OPTS=$names ;;
        none) OPTS= ;;
        *) OPTS=$(printf '%s' "$OPT_SET" | tr ',' ' ') ;;
    esac
    for n in $(printf '%s' "$OPT_WITH" | tr ',' ' '); do OPTS=$(list_add "$OPTS" "$n"); done
    for n in $(printf '%s' "$OPT_WITHOUT" | tr ',' ' '); do OPTS=$(list_del "$OPTS" "$n"); done
    for n in $OPTS $(printf '%s %s' "$OPT_WITH" "$OPT_WITHOUT" | tr ',' ' '); do
        list_has "$names" "$n" || die "unknown option '$n' (known: $names)"
    done
}
ask_options() { # a checklist on the terminal; changes OPTS
    names=$(conf_options "$LAYOUT" | cut -f1 | tr '\n' ' ')
    while :; do
        echo
        echo "Which button remaps do you want? (the default is marked)"
        i=0
        conf_options "$LAYOUT" | while IFS='	' read -r n d t; do
            i=$((i + 1))
            if list_has "$OPTS" "$n"; then m=x; else m=' '; fi
            printf '  %2d [%s] %s\n' "$i" "$m" "$t"
        done
        printf 'Number to switch on/off, a = all, n = none, Enter = continue: '
        if on_device && tty_ok; then read -r a < /dev/tty; else read -r a; fi
        case "$a" in
            "") return ;;
            a) OPTS=${names% } ;;
            n) OPTS= ;;
            *[!0-9]*) echo "Not a number." ;;
            *)
                n=$(printf '%s' "$names" | awk -v k="$a" '{ print $k }')
                if [ -z "$n" ]; then echo "No option $a."
                elif list_has "$OPTS" "$n"; then OPTS=$(list_del "$OPTS" "$n")
                else OPTS=$(list_add "$OPTS" "$n"); fi
                ;;
        esac
    done
}
can_ask() { # a terminal to ask on (tests: HW_ASK=1 reads stdin)
    if on_device; then tty_ok; else [ "${HW_ASK:-}" = 1 ]; fi
}

mpc_service() {
    if systemctl cat acvs >/dev/null 2>&1; then echo acvs
    elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
    else echo ""; fi
}
detect_style() {
    # a Force has the launcher file too (the script its service runs) but it sets no LD_PRELOAD: that one takes the drop-in
    if [ -f "$LAUNCHER" ] && grep -q 'LD_PRELOAD=' "$LAUNCHER"; then echo launcher
    elif [ -n "$(mpc_service)" ]; then echo dropin
    else echo ""; fi
}
so_path() { # device path of the library for a style (no test prefix)
    case "$1" in launcher) echo "$SO_LAUNCHER" ;; dropin) echo "$SO_DROPIN" ;; esac
}
so_file() { # where the bytes are written (under the test prefix)
    case "$1" in launcher) echo "$P$SO_LAUNCHER" ;; dropin) echo "$P$SO_DROPIN" ;; esac
}
dropin_file() { echo "$P/etc/systemd/system/$1.service.d/hwremap.conf"; }
installed_version() { [ -f "$MARK/VERSION" ] && cat "$MARK/VERSION"; }
backup_present() { [ -d "$BK_ROOT" ] && [ -n "$(ls "$BK_ROOT" 2>/dev/null)" ]; }
state_line() { echo "STATE state=$1 supported=$2 backup=$(backup_present && echo 1 || echo 0)${3:+ reason=$3}"; }

need_tools() {
    for c in awk sed grep cmp mktemp systemctl pidof wc tr cut sha256sum; do
        command -v "$c" >/dev/null || return 1
    done
    return 0
}
on_device() { [ -z "$P" ]; }
root_rw() {
    on_device || return 0
    mount -o remount,rw / || die "could not remount / read-write"
    ROOT_RW=1
}
root_ro() {
    on_device || return 0
    [ "$ROOT_RW" = 1 ] || return 0
    sync
    mount -o remount,ro / || echo "WARNING: could not remount / read-only"
    ROOT_RW=0
}
stop_mpc() {
    systemctl stop "$SVC" || die "could not stop $SVC"
    STOPPED=1
}
start_mpc() {
    systemctl start "$SVC" || echo "WARNING: could not start $SVC; start it yourself: systemctl start $SVC"
    STOPPED=0
}

# Insert the library into every LD_PRELOAD assignment that does not already name it.
# A line with $CURSOR_SO gets the library just before that, which is where the Hakai launcher expects it.
patch_launcher() {
    src=$1
    tmp=$(mktemp) || die "cannot make a temporary file"
    awk '
        /^[[:space:]]*#/ { print; next }
        /LD_PRELOAD=/ && index($0, "hwremap.so") == 0 {
            if (index($0, "$CURSOR_SO") > 0)
                sub(/\$CURSOR_SO/, "/usr/lib/hwremap.so $CURSOR_SO")
            else if (match($0, /LD_PRELOAD="[^"]*"/))
                $0 = substr($0, 1, RSTART + RLENGTH - 2) " /usr/lib/hwremap.so" substr($0, RSTART + RLENGTH - 1)
            else if (match($0, /LD_PRELOAD=[^[:space:]]+/))
                $0 = substr($0, 1, RSTART + RLENGTH - 1) ":/usr/lib/hwremap.so" substr($0, RSTART + RLENGTH)
            else {
                print "ERROR: a launcher line sets LD_PRELOAD in a shape this patch cannot edit" > "/dev/stderr"
                print $0 > "/dev/stderr"
                exit 2
            }
        }
        { print }
    ' "$src" > "$tmp" || { rm -f "$tmp"; die "could not edit the launcher"; }
    if cmp -s "$src" "$tmp"; then rm -f "$tmp"; die "the launcher has no LD_PRELOAD line to add the library to"; fi
    cat "$tmp" > "$src" || { rm -f "$tmp"; die "could not write the launcher"; }
    rm -f "$tmp"
}
current_preload() {
    raw=$(systemctl show "$SVC" -p Environment 2>/dev/null || true)
    printf '%s\n' "$raw" | awk '
        {
            s = $0
            sub(/^Environment=/, "", s)
            if (match(s, /LD_PRELOAD=/)) {
                rest = substr(s, RSTART + RLENGTH)
                if (match(rest, / [A-Za-z_][A-Za-z0-9_]*=/))
                    rest = substr(rest, 1, RSTART - 1)
                gsub(/^[" ]+|[" ]+$/, "", rest)
                print rest
            }
        }'
}
plain_preload() { # refuse a value we would not want to write back into a unit file
    printf '%s' "$1" | grep -q '["'"'"'`$]' && return 1
    return 0
}

hook_present() { # something already redirects MPC through hwremap, with or without our marker
    if [ -f "$LAUNCHER" ] && grep -q hwremap.so "$LAUNCHER"; then return 0; fi
    if [ -f "$P$SO_LAUNCHER" ] || [ -f "$P$SO_DROPIN" ]; then return 0; fi
    svc=$(mpc_service)
    if [ -n "$svc" ] && [ -f "$(dropin_file "$svc")" ]; then return 0; fi
    return 1
}
maps_have_it() {
    if ! on_device; then
        [ -n "${HW_MAPS:-}" ] && [ -f "$HW_MAPS" ] && grep -q hwremap "$HW_MAPS"
        return
    fi
    pid=$(pidof MPC 2>/dev/null) || return 1
    grep -q hwremap "/proc/$pid/maps"
}
mpc_running() {
    if ! on_device; then
        [ -n "${HW_PID:-}" ]
        return
    fi
    pidof MPC >/dev/null 2>&1
}

restore_hook() { # undo the launcher edit or the drop-in; the library is removed by the caller
    style=$(cat "$MARK/STYLE")
    svc=$(cat "$MARK/SERVICE")
    case "$style" in
        launcher)
            [ -f "$MARK/az01-launch-MPC.orig" ] || die "the saved launcher is missing ($MARK/az01-launch-MPC.orig); not touching $LAUNCHER"
            root_rw
            cat "$MARK/az01-launch-MPC.orig" > "$LAUNCHER" || die "could not restore the launcher"
            rm -f "$P$SO_LAUNCHER"
            root_ro
            ;;
        dropin)
            rm -f "$(dropin_file "$svc")"
            rmdir "$P/etc/systemd/system/$svc.service.d" 2>/dev/null || true
            rm -f "$P$SO_DROPIN"
            systemctl daemon-reload || echo "WARNING: systemctl daemon-reload failed"
            ;;
        *) die "unknown install style: $style" ;;
    esac
}

rollback() {
    echo "Installation interrupted: putting back what was changed"
    if [ -f "$MARK/az01-launch-MPC.orig" ] && [ -f "$LAUNCHER" ]; then
        if cat "$MARK/az01-launch-MPC.orig" > "$LAUNCHER"; then
            rm -f "$MARK/az01-launch-MPC.orig"
        else
            echo "WARNING: could not restore the launcher; the original is at $MARK/az01-launch-MPC.orig and in the backup"
        fi
    fi
    rm -f "$P$SO_LAUNCHER" "$P$SO_DROPIN"
    if [ -n "$SVC" ]; then
        rm -f "$(dropin_file "$SVC")"
        systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    if [ "$WROTE_CONF" = 1 ]; then rm -f "$CONF"; fi
    rm -f "$MARK/VERSION" "$MARK/STYLE" "$MARK/SERVICE" "$MARK/config.default" "$MARK/OPTIONS"
    rmdir "$MARK" 2>/dev/null || true
    root_ro
    if [ "$STOPPED" = 1 ] && [ -n "$SVC" ]; then
        systemctl start "$SVC" || echo "WARNING: could not start $SVC again"
        STOPPED=0
    fi
}
on_exit() {
    if [ "$FAILED" = 1 ]; then
        rollback
        exit 1
    fi
}
confirm() { # $1 word
    [ "$CONFIRMED" = 1 ] && return 0
    printf 'Type %s to continue: ' "$1"
    if on_device && tty_ok; then read -r a < /dev/tty; else read -r a; fi
    [ "$a" = "$1" ] || die "cancelled; nothing was changed"
}

cmd_status() {
    if on_device; then
        if [ "$(id -u)" != 0 ]; then echo "Not root: run this on the device as root."; state_line unsupported 0 not-root; return; fi
        case "$(uname -m)" in armv7*) ;; *) echo "This is for 32-bit ARM MPC OS devices; this one is $(uname -m)."; state_line unsupported 0 arch; return ;; esac
    fi
    if ! need_tools; then echo "A tool this patch needs is missing (awk, sed, grep, cmp, mktemp, systemctl, pidof, wc, tr, cut, sha256sum)."; state_line unsupported 0 tools; return; fi
    STYLE=$(detect_style)
    if [ -z "$STYLE" ]; then
        echo "This device has neither the Hakai launcher ($LAUNCHER) nor an acvs or inmusic-mpc service."
        state_line unsupported 0 unknown-layout
        return
    fi
    if v=$(installed_version); then
        if [ "$v" != "$VERSION" ]; then
            echo "Another version of this patch is installed ($v; this script is $VERSION). Remove it with its own script first."
            state_line unsupported 0 other-version
            return
        fi
        st=$(cat "$MARK/STYLE" 2>/dev/null || echo "?")
        echo "Installed (version $VERSION, style $st)."
        [ ! -f "$MARK/OPTIONS" ] || echo "Options chosen at install: $(cat "$MARK/OPTIONS" | sed 's/^$/none/')."
        if [ ! -f "$(so_file "$st")" ]; then echo "The library file is missing."; state_line partial 1 incomplete; return; fi
        if maps_have_it; then echo "MPC has loaded it."; state_line patched 1; return; fi
        if mpc_running; then echo "MPC is running but has not loaded it. Restart MPC."; state_line partial 1 not-loaded; return; fi
        echo "MPC is not running, so the remap is not in effect until it starts."; state_line partial 1 not-running
        return
    fi
    if hook_present; then
        echo "hwremap is already on this device (the library or an LD_PRELOAD line) but this patch did not install it. Remove that copy first; this script will not overwrite it."
        state_line unsupported 0 hand-install
        return
    fi
    echo "Not installed. Style this script would use: $STYLE."
    state_line stock 1
}

prepare() { # shared checks for install and uninstall; sets SVC
    if on_device; then
        [ "$(id -u)" = 0 ] || die "run as root on the device"
        case "$(uname -m)" in armv7*) ;; *) die "this is for 32-bit ARM MPC OS devices (this one is $(uname -m))" ;; esac
    fi
    need_tools || die "a tool this patch needs is missing (awk, sed, grep, cmp, mktemp, systemctl, pidof, wc, tr, cut, sha256sum)"
    SVC=$(mpc_service)
    [ -n "$SVC" ] || die "cannot find the MPC service (looked for acvs and inmusic-mpc)"
}

cmd_options() { # list the options of a layout and which are on by default
    [ -n "$LAYOUT" ] || LAYOUT=force
    case "$LAYOUT" in mpc-live|force) ;; *) die "--layout must be mpc-live or force" ;; esac
    if [ -z "$(conf_options "$LAYOUT")" ]; then echo "The $LAYOUT map has no options."; return; fi
    echo "Options of the $LAYOUT map (default: on = marked):"
    conf_options "$LAYOUT" | while IFS='	' read -r n d t; do
        if [ "$d" = on ]; then m=on; else m=off; fi
        printf '  %-18s %-3s %s\n' "$n" "$m" "$t"
    done
}

cmd_install() {
    prepare
    v=$(installed_version) && die "this patch is already installed (version $v). Uninstall it first (sh $0 uninstall)."
    hook_present && die "hwremap is already on this device without this patch's marker. Remove that copy first (see the guide); this script will not overwrite it."
    STYLE=$(detect_style)
    [ -n "$STYLE" ] || die "this device has neither the Hakai launcher nor an acvs or inmusic-mpc service"
    if [ -z "$LAYOUT" ]; then
        case "$STYLE" in launcher) LAYOUT=mpc-live ;; dropin) LAYOUT=force ;; esac
    fi
    case "$LAYOUT" in mpc-live|force) ;; *) die "--layout must be mpc-live or force" ;; esac
    OPTS=
    if [ ! -f "$CONF" ]; then
        choose_options
        if [ -z "$OPT_SET$OPT_WITH$OPT_WITHOUT" ] && [ "$CONFIRMED" = 0 ] && [ -n "$(conf_options "$LAYOUT")" ]; then
            if can_ask; then ask_options; else echo "No terminal to ask on: using the default options (see: sh $0 options)."; fi
        fi
    elif [ -n "$OPT_SET$OPT_WITH$OPT_WITHOUT" ]; then
        echo "Note: $CONF already exists and is left as it is, so the option flags are ignored."
    fi
    case "$STYLE" in
        launcher) where="$SO_LAUNCHER (and $LAUNCHER)"; need_rw="The root filesystem is remounted writable, then read-only again." ;;
        dropin) where="$SO_DROPIN (and a systemd drop-in for $SVC)"; need_rw="The root filesystem is not remounted." ;;
    esac
    echo "Installing button remap $VERSION."
    echo "  style:   $STYLE"
    echo "  library: $where"
    echo "  $need_rw"
    if [ -f "$CONF" ]; then echo "  config:  $CONF already exists and will be left as it is."
    else
        echo "  config:  $CONF will be created from the $LAYOUT map (edit it to change what the buttons do)."
        [ -z "$(conf_options "$LAYOUT")" ] || echo "  options: ${OPTS:-none}"
    fi
    echo "  MPC ($SVC) will be stopped and started. Save your project first."
    confirm PATCH
    [ "${HW_FAIL:-}" = before-write ] && die "test failure before any change"
    BACKUP=$BK_ROOT/hwremap-$VERSION-$(date +%Y%m%d-%H%M%S)
    [ ! -e "$BACKUP" ] || die "backup folder exists: $BACKUP"
    FAILED=1
    trap on_exit EXIT
    mkdir -p "$BACKUP" "$MARK" "$P/sdcard" || die "cannot create the backup folder"
    chmod 700 "$BACKUP" || die "cannot protect the backup folder"
    if [ "$STYLE" = launcher ]; then cp "$LAUNCHER" "$BACKUP/az01-launch-MPC.orig" || die "cannot back up the launcher"; fi
    systemctl show "$SVC" -p Environment > "$BACKUP/environment.before" 2>/dev/null || true
    printf '%s\n' "Patch-only backup of the launcher or the service environment. No projects." > "$BACKUP/README.txt"
    stop_mpc
    case "$STYLE" in
        launcher)
            root_rw
            cp "$LAUNCHER" "$MARK/az01-launch-MPC.orig" || die "cannot save the launcher"
            patch_launcher "$LAUNCHER"
            [ "${HW_FAIL:-}" = after-launcher ] && die "test failure after editing the launcher"
            mkdir -p "$P/usr/lib" || die "cannot create /usr/lib"
            write_so "$P$SO_LAUNCHER"
            cp "$LAUNCHER" "$BACKUP/az01-launch-MPC.patched"
            ;;
        dropin)
            cur=$(current_preload)
            plain_preload "$cur" || die "the current LD_PRELOAD is not a plain list of paths; refusing to rewrite it"
            case " $cur " in *" $SO_DROPIN "*) new=$cur ;; "") new=$SO_DROPIN ;; *) new="$cur $SO_DROPIN" ;; esac
            mkdir -p "$MARK" "$(dirname "$(dropin_file "$SVC")")" || die "cannot create the drop-in folder"
            write_so "$P$SO_DROPIN"
            [ "${HW_FAIL:-}" = after-launcher ] && die "test failure after writing the library"
            {
                echo "[Service]"
                printf 'Environment="LD_PRELOAD=%s"\n' "$new"
            } > "$(dropin_file "$SVC")" || die "cannot write the drop-in"
            cp "$(dropin_file "$SVC")" "$BACKUP/hwremap.conf"
            systemctl daemon-reload || die "systemctl daemon-reload failed"
            ;;
    esac
    if [ ! -f "$CONF" ]; then
        write_default_conf "$CONF" "$LAYOUT" "$OPTS" || die "cannot write the config"
        printf '%s\n' "$OPTS" > "$MARK/OPTIONS"
        cp "$CONF" "$MARK/config.default" || die "cannot save the default config"
        WROTE_CONF=1
    fi
    printf '%s\n' "$VERSION" > "$MARK/VERSION"
    printf '%s\n' "$STYLE" > "$MARK/STYLE"
    printf '%s\n' "$SVC" > "$MARK/SERVICE"
    root_ro
    start_mpc
    FAILED=0
    trap - EXIT
    on_device && sync
    echo "Button remap $VERSION installed. Backup: $BACKUP"
    echo "Config: $CONF (a change there applies on the next button press)."
    echo "Check it: sh $0 status"
}

cmd_uninstall() {
    prepare
    v=$(installed_version) || { echo "Not installed. Nothing to do."; exit 0; }
    [ "$v" = "$VERSION" ] || die "another version is installed ($v): use its own script"
    echo "This removes the library and the startup hook. MPC ($SVC) will be stopped and started."
    if [ -f "$MARK/config.default" ] && [ -f "$CONF" ] && cmp -s "$MARK/config.default" "$CONF"; then
        echo "The default config has not been edited, so $CONF will be removed too."
    elif [ -f "$CONF" ]; then
        echo "$CONF was edited or was already there: it will be left in place."
    fi
    confirm REMOVE
    stop_mpc
    trap 'if [ "$STOPPED" = 1 ]; then systemctl start "$SVC" || echo "WARNING: could not start $SVC again"; fi' EXIT
    if [ -f "$MARK/config.default" ] && [ -f "$CONF" ] && cmp -s "$MARK/config.default" "$CONF"; then
        rm -f "$CONF"
    fi
    restore_hook
    rm -f "$MARK/VERSION" "$MARK/STYLE" "$MARK/SERVICE" "$MARK/config.default" "$MARK/OPTIONS" "$MARK/az01-launch-MPC.orig"
    rmdir "$MARK" 2>/dev/null || true
    start_mpc
    trap - EXIT
    echo "Removed. The buttons are back to what the device shipped with (once MPC is up)."
    if [ -f "$CONF" ]; then echo "Left $CONF in place."; fi
}

# --- arguments
CMD=${1:-help}; [ $# -gt 0 ] && shift
CONFIRMED=0
while [ $# -gt 0 ]; do
    case "$1" in
        --layout) [ -n "${2:-}" ] || die "--layout needs mpc-live or force"; LAYOUT=$2; shift 2 ;;
        --options) [ -n "${2:-}" ] || die "--options needs a comma list, all or none"; OPT_SET=$2; shift 2 ;;
        --with) [ -n "${2:-}" ] || die "--with needs a comma list"; OPT_WITH=$2; shift 2 ;;
        --without) [ -n "${2:-}" ] || die "--without needs a comma list"; OPT_WITHOUT=$2; shift 2 ;;
        --confirmed) CONFIRMED=1; shift ;;
        *) usage 1 ;;
    esac
done

case "$CMD" in
    status) cmd_status ;;
    options) cmd_options ;;
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    help|-h|--help) usage 0 ;;
    *) usage 1 ;;
esac
