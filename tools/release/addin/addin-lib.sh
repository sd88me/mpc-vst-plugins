# The addin installer (mpc-vst-plugins tools/release/addin, docs/ADDINS.md): shared by install.sh and uninstall.sh, identical in
# every addin release; only addin.manifest differs. tools/release_addin.py puts the three next to the addin's files.
# It finds MPC's systemd service, edits its LD_PRELOAD list and loads addin.manifest. ADDIN_LIB_VERSION identifies this copy.
ADDIN_LIB_VERSION=2
# Tests set ADDIN_INSTALL_TEST=1, SYSTEMD_ROOT (a scratch tree holding the unit files) and ADDIN_TEST_LOG.

UNIT_DIRS="/etc/systemd/system /run/systemd/system /usr/lib/systemd/system /lib/systemd/system"
DROPIN_NAME=90-mpc-addins.conf   # one drop-in shared by every addin, where no writable file sets LD_PRELOAD

svc() {   # systemctl, or a log line under test
    if [ -n "$ADDIN_INSTALL_TEST" ]; then echo "systemctl $*" >> "${ADDIN_TEST_LOG:-/dev/null}"; return 0; fi
    systemctl "$@"
}

# MPC's service: acvs on stock firmware, inmusic-mpc on some modified ones.
mpc_service() {
    for s in acvs inmusic-mpc; do
        for d in $UNIT_DIRS; do
            [ -f "$SYSTEMD_ROOT$d/$s.service" ] && { echo "$s"; return; }
        done
    done
    echo acvs
}

ours() { echo "$SYSTEMD_ROOT/etc/systemd/system/$1.service.d/$DROPIN_NAME"; }   # service
writable() {   # file: can it be replaced? A probe file, since busybox's [ -w ] says yes to root on a read-only mount
    w="$(dirname "$1")/.mpc-addins-probe.$$"
    [ -w "$1" ] && (: > "$w") 2>/dev/null && rm -f "$w"
}

# The unit file or drop-in whose Environment= line sets LD_PRELOAD and wins (the last one systemd reads), if any;
# a second argument leaves that file out.
unit_with_preload() {
    found=""
    for d in $UNIT_DIRS; do   # the main unit: the first directory that has it
        f="$SYSTEMD_ROOT$d/$1.service"
        if [ -f "$f" ]; then grep -q '^Environment=.*LD_PRELOAD=' "$f" && found="$f"; break; fi
    done
    for f in $(for d in $UNIT_DIRS; do ls "$SYSTEMD_ROOT$d/$1.service.d/"*.conf 2>/dev/null; done | awk -F/ '{print $NF "\t" $0}' | sort | cut -f2); do
        [ "$f" = "$2" ] && continue
        grep -q '^Environment=.*LD_PRELOAD=' "$f" && found="$f"   # drop-ins apply in name order
    done
    echo "$found"
}

# Rewrite the LD_PRELOAD value on each matching line of a file with an awk program ("add" or "remove" $so).
edit_preload() {   # file mode so
    awk -v mode="$2" -v so="$3" '
    /^Environment=/ && (i = index($0, "LD_PRELOAD=")) {
        pre = substr($0, 1, i - 1); rest = substr($0, i + 11)
        quoted = substr(pre, length(pre), 1) == "\""   # Environment="LD_PRELOAD=/a.so /b.so" runs to the quote
        e = index(rest, quoted ? "\"" : " "); if (!e) e = length(rest) + 1
        val = substr(rest, 1, e - 1); post = substr(rest, e)
        n = split(val, parts, /[: ]+/); out = ""; seen = 0
        for (k = 1; k <= n; k++) {
            if (parts[k] == "") continue
            if (parts[k] == so) { seen = 1; if (mode == "remove") continue }
            out = out (out == "" ? "" : ":") parts[k]
        }
        if (mode == "add" && !seen) out = out (out == "" ? "" : ":") so
        if (out == "") {                              # nothing left: drop the assignment (and its quotes)
            if (quoted) { pre = substr(pre, 1, length(pre) - 1); post = substr(post, 2) }
            sub(/^ +/, "", post); print pre post; next
        }
        print pre "LD_PRELOAD=" out post; next
    }
    { print }' "$1" > "$1.new"
    sed -i 's/^Environment= *$//' "$1.new"
    mv "$1.new" "$1"
}

# The LD_PRELOAD value a file sets (its last such line), ":"-joined; "" if none.
preload_of() {
    [ -f "$1" ] || return 0
    awk '/^Environment=/ && (i = index($0, "LD_PRELOAD=")) {
        pre = substr($0, 1, i - 1); rest = substr($0, i + 11)
        e = index(rest, substr(pre, length(pre), 1) == "\"" ? "\"" : " "); if (!e) e = length(rest) + 1
        v = substr(rest, 1, e - 1); gsub(/[: ]+/, ":", v); sub(/^:/, "", v); sub(/:$/, "", v); out = v
    } END { print out }' "$1"
}
in_list() { case ":$1:" in *":$2:"*) return 0 ;; esac; return 1; }   # list item

# The shared drop-in, where no writable file sets LD_PRELOAD (on these devices the unit is on a read-only root).
# systemd replaces the variable, so the drop-in repeats the unit's list (its "base", recorded in a comment) and
# appends the addins. When the unit's list changes (a firmware update), the next install or uninstall rebuilds it
# from the new base: the addins are kept, the firmware's libraries are not shadowed.
sync_ours() {   # service add-so remove-so
    f=$(ours "$1"); base=$(preload_of "$(unit_with_preload "$1" "$f")"); addins=""
    if [ -f "$f" ]; then
        oldbase=$(sed -n 's/^# base: *//p' "$f"); IFS0=$IFS; IFS=:
        for e in $(preload_of "$f"); do in_list "$oldbase" "$e" || addins="$addins${addins:+:}$e"; done
        IFS=$IFS0
    fi
    new=""; IFS0=$IFS; IFS=:
    for e in $addins $2; do
        [ -n "$e" ] && [ "$e" != "$3" ] && ! in_list "$base" "$e" && ! in_list "$new" "$e" && new="$new${new:+:}$e"
    done
    IFS=$IFS0
    if [ -z "$new" ]; then rm -f "$f"; rmdir "$(dirname "$f")" 2>/dev/null || true; return 0; fi
    mkdir -p "$(dirname "$f")"
    printf '[Service]\n# MPC addins (mpc-vst-plugins addin installer). systemd replaces LD_PRELOAD, so this repeats the base list from\n# the unit, then the addins. Edit with install.sh / uninstall.sh, which rebuild it when the base changes.\n# base: %s\nEnvironment=LD_PRELOAD=%s\n' \
        "$base" "$base${base:+:}$new" > "$f.new"
    mv "$f.new" "$f"
}

edits_in_place() { [ -n "$2" ] && [ "$2" != "$(ours "$1")" ] && writable "$2"; }   # service unit

preload_add() {   # service unit so
    if edits_in_place "$1" "$2"; then
        bak="$2.bak-mpc-addins"   # the first edit keeps a backup
        [ -f "$bak" ] || cp "$2" "$bak"
        cp "$2" "$2.prev"
        edit_preload "$2" add "$3"
        grep -qF "$3" "$2" || { mv "$2.prev" "$2"; echo "error: editing $2 failed; restored" >&2; exit 1; }
        rm -f "$2.prev"
    else
        sync_ours "$1" "$3" ""
        grep -qF "$3" "$(ours "$1")" || { echo "error: writing $(ours "$1") failed" >&2; exit 1; }
    fi
}

preload_remove() {   # service so: out of every writable file that lists it, then out of the shared drop-in
    o=$(ours "$1")
    for d in $UNIT_DIRS; do
        for f in "$SYSTEMD_ROOT$d/$1.service" "$SYSTEMD_ROOT$d/$1.service.d/"*.conf; do
            [ -f "$f" ] && [ "$f" != "$o" ] && grep -qF "$2" "$f" || continue
            if writable "$f"; then edit_preload "$f" remove "$2"; else echo "warning: $f lists $2 but is read-only" >&2; fi
        done
    done
    [ ! -f "$o" ] || sync_ours "$1" "" "$2"
}

# addin.manifest, next to install.sh: shell assignments, checked before anything uses them.
#   ADDIN_ID      folder and identity: /data/mpc-addins/<id> (letters, digits, - and _)
#   ADDIN_NAME    shown to the user
#   ADDIN_SO      the library, preloaded into MPC
#   ADDIN_CONF    settings file: installed only when the folder has none, so the user's edits survive ("" none)
#   ADDIN_FILES   other files, replaced on every install ("" none)
#   ADDIN_DONE    a line printed after installing ("" none)
#   ADDIN_VERSION X.Y.Z, written by tools/release_addin.py ("" for a build that was not released)
# Only plain assignments: tools/catalog_check.py refuses a manifest with anything else in it.
SELF_FILES="addin.manifest addin-lib.sh uninstall.sh"   # copied into the folder too, so it can remove itself
load_manifest() {
    [ -f addin.manifest ] || die "addin.manifest is missing next to install.sh"
    ADDIN_ID=""; ADDIN_NAME=""; ADDIN_SO=""; ADDIN_CONF=""; ADDIN_FILES=""; ADDIN_DONE=""; ADDIN_VERSION=""
    . ./addin.manifest
    case "$ADDIN_ID" in ""|*[!A-Za-z0-9_-]*) die "addin.manifest: bad ADDIN_ID '$ADDIN_ID'" ;; esac
    for f in "$ADDIN_SO" $ADDIN_CONF $ADDIN_FILES; do
        case "$f" in ""|*/*|.*|*[!A-Za-z0-9._-]*) die "addin.manifest: bad file name '$f'" ;; esac
    done
    case "$ADDIN_SO" in *.so) ;; *) die "addin.manifest: ADDIN_SO must be a .so" ;; esac
    for f in $ADDIN_CONF $ADDIN_FILES; do
        case " $SELF_FILES " in *" $f "*) die "addin.manifest: $f is the installer's own file" ;; esac
    done
    case "$ADDIN_VERSION" in ""|[0-9]*.[0-9]*.[0-9]*) ;; *) die "addin.manifest: bad ADDIN_VERSION '$ADDIN_VERSION'" ;; esac
    case "$ADDIN_VERSION" in *[!0-9.]*) die "addin.manifest: bad ADDIN_VERSION '$ADDIN_VERSION'" ;; esac
    [ -n "$ADDIN_NAME" ] || ADDIN_NAME="$ADDIN_ID"
    DIR="${DIR:-/data/mpc-addins/$ADDIN_ID}"
}

check_dir() {
    case "$DIR" in /*) ;; *) die "-t must be an absolute path" ;; esac
    case "$DIR" in *[!A-Za-z0-9/._-]*) die "the folder may only contain letters, digits and / . _ -" ;; esac
}
