#!/usr/bin/env bash
# The addin installer (tools/release/addin: install.sh, uninstall.sh, addin-lib.sh) against scratch systemd layouts, with two
# addins side by side: the cases listed in docs/ADDINS.md, Tests. BUSYBOX=/path/to/busybox runs them in the device's shell (the
# default when busybox is installed).
set -euo pipefail
cd "$(dirname "$0")/release/addin"
SH="sh"; BB="${BUSYBOX:-$(command -v busybox || true)}"; [ -n "$BB" ] && SH="$BB sh"
T=$(mktemp -d); trap 'chmod -R u+w "$T"; rm -rf "$T"' EXIT
fails=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails + 1)); }
elf() {   # elf <file> <class+data> <e_type> <e_machine>: the first 20 bytes of an ELF header, then padding
    printf "\\177ELF$2\\001\\000\\000\\000\\000\\000\\000\\000\\000\\000$3$4padding" > "$1"
}
pkg() {   # pkg <id>: a package folder for a fake addin
    rm -rf "$T/pkg-$1"; mkdir -p "$T/pkg-$1"
    cp install.sh uninstall.sh addin-lib.sh "$T/pkg-$1/"
    printf 'ADDIN_ID=%s\nADDIN_NAME="Test %s"\nADDIN_SO=lib%s.so\nADDIN_CONF=%s.conf\nADDIN_FILES="%s.dat"\nADDIN_DONE="see %s"\nADDIN_VERSION=1.2.3\n' "$1" "$1" "$1" "$1" "$1" "$1" > "$T/pkg-$1/addin.manifest"
    elf "$T/pkg-$1/lib$1.so" '\001\001' '\003\000' '\050\000'; echo "default=1" > "$T/pkg-$1/$1.conf"; echo data > "$T/pkg-$1/$1.dat"
}
run() {   # run <id> <script> [args]: as the device would, with the addin folder under the scratch tree
    ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/pkg-$1/$2" -y -t "$T/addins/$1" "${@:3}" > "$T/out" 2>&1 || { cat "$T/out"; return 1; }
}
A="$T/addins/a/liba.so"; B="$T/addins/b/libb.so"
unit() { mkdir -p "$T/root/usr/lib/systemd/system"; printf '[Unit]\nDescription=MPC\n\n[Service]\n%s\nExecStart=/usr/bin/az01-launch-MPC\n' "$1" > "$T/root/usr/lib/systemd/system/acvs.service"; }
line() { grep '^Environment' "$T/root/usr/lib/systemd/system/acvs.service" || true; }
fresh() { [ ! -d "$T/root" ] || chmod -R u+w "$T/root"; rm -rf "$T/root" "$T/addins" "$T/log"; pkg a; pkg b; }
ro() { chmod "$1" "$T/root/usr/lib/systemd/system" "$T/root/usr/lib/systemd/system/acvs.service"; }   # a-w | u+w
DROP="$T/root/etc/systemd/system/acvs.service.d/90-mpc-addins.conf"

# 1. the service already preloads two libraries (the stock layout with a mouse and a MIDI shim)
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so'
run a install.sh
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A" ] && ok "appended to the existing list" || bad "append: $(line)"
[ -f "$T/root/usr/lib/systemd/system/acvs.service.bak-mpc-addins" ] && ok "backup kept" || bad "no backup"
[ -f "$A" ] && [ -f "$T/addins/a/a.conf" ] && [ -f "$T/addins/a/a.dat" ] && ok "files installed" || bad "files"
grep -q "systemctl restart acvs" "$T/log" && grep -q "see a" "$T/out" && ok "MPC restarted, done line shown" || bad "restart/done"
echo "mine=1" > "$T/addins/a/a.conf"; echo old > "$T/addins/a/a.dat"
run a install.sh -n
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A" ] && ok "installing again changes nothing" || bad "idempotent: $(line)"
grep -q "mine=1" "$T/addins/a/a.conf" && grep -q data "$T/addins/a/a.dat" && ok "settings kept, data files replaced" || bad "conf/data"
for f in addin.manifest addin-lib.sh uninstall.sh; do cmp -s "$T/pkg-a/$f" "$T/addins/a/$f" || bad "$f not copied into the folder"; done
grep -q "Test a 1.2.3" "$T/out" && ok "the folder carries its uninstaller; the version is shown" || bad "self files / version"
[ "$(grep -c restart "$T/log")" = 1 ] && ok "-n doesn't restart" || bad "-n restarted"
run b install.sh
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A:$B" ] && ok "a second addin joins the list" || bad "second: $(line)"
run a uninstall.sh
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$B" ] && [ ! -e "$T/addins/a" ] && [ -f "$B" ] \
  && ok "uninstalling one leaves the other" || bad "uninstall one: $(line)"
run b uninstall.sh
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so" ] && ok "back to the original line" || bad "restore: $(line)"

# 2. quoted, space-separated, with another variable on the line
fresh; unit 'Environment="LD_PRELOAD=/usr/lib/x.so /usr/lib/y.so" FOO=1'
run a install.sh
[ "$(line)" = "Environment=\"LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A\" FOO=1" ] && ok "quoted form" || bad "quoted: $(line)"
run a uninstall.sh
[ "$(line)" = 'Environment="LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so" FOO=1' ] && ok "quoted form uninstall" || bad "quoted uninstall: $(line)"

# 3. nothing preloaded yet: one shared drop-in for both addins, gone with the last one
fresh; unit 'Restart=always'
run a install.sh
grep -qx "Environment=LD_PRELOAD=$A" "$DROP" && ok "a drop-in when nothing preloads" || bad "drop-in"
run b install.sh
grep -qx "Environment=LD_PRELOAD=$A:$B" "$DROP" && [ "$(ls "$(dirname "$DROP")" | wc -l)" = 1 ] && ok "the second addin shares it" || bad "shared drop-in: $(cat "$DROP")"
run a uninstall.sh
grep -qx "Environment=LD_PRELOAD=$B" "$DROP" && ok "uninstalling the first keeps the drop-in for the second" || bad "drop-in after a: $(cat "$DROP" 2>&1)"
run b uninstall.sh
[ ! -e "$DROP" ] && ok "the drop-in goes with the last addin" || bad "drop-in left"

# 3b. removing from the installed folder itself, without the release, and reinstalling from it
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so'
run a install.sh
ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/addins/a/install.sh" -y -n > "$T/out" 2>&1 && bad "the folder has an install.sh" || ok "the folder has no install.sh"
ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/addins/a/uninstall.sh" -y -n -t "$T/addins/a" > "$T/out" 2>&1 || cat "$T/out"
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so" ] && [ ! -e "$T/addins/a" ] && ok "the folder's own uninstall.sh removes it" || bad "self uninstall: $(line)"

# 4. a line holding only this addin: uninstall drops the assignment
fresh; unit "Environment=LD_PRELOAD=$A"
run a uninstall.sh
[ -z "$(line)" ] && ok "a line holding only this addin goes away" || bad "only: $(line)"

# 5. another drop-in sets LD_PRELOAD (it wins over the unit): that one is edited
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so'
mkdir -p "$T/root/etc/systemd/system/acvs.service.d"
printf '[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so:/data/nam.so\n' > "$T/root/etc/systemd/system/acvs.service.d/10-nam.conf"
run a install.sh
grep -qx "Environment=LD_PRELOAD=/usr/lib/x.so:/data/nam.so:$A" "$T/root/etc/systemd/system/acvs.service.d/10-nam.conf" \
  && [ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so" ] && ok "the winning drop-in is the one edited" || bad "drop-in precedence"

# 6. the inmusic-mpc service name
fresh; mkdir -p "$T/root/usr/lib/systemd/system"; printf '[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\n' > "$T/root/usr/lib/systemd/system/inmusic-mpc.service"
run a install.sh
grep -qF "$A" "$T/root/usr/lib/systemd/system/inmusic-mpc.service" && grep -q "restart inmusic-mpc" "$T/log" && ok "inmusic-mpc service" || bad "inmusic-mpc"

# 7. the unit is on a read-only root (as on the devices): the shared drop-in repeats its list, then the addins
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so'; ro a-w
U0=$(cat "$T/root/usr/lib/systemd/system/acvs.service")
run a install.sh; run b install.sh; out=$(cat "$T/out")
case "$out" in *"the list from $T/root/usr/lib/systemd/system/acvs.service, then the addins"*) ok "the second install names the unit's list, not the drop-in" ;;
  *) bad "second install's summary: $(echo "$out" | tr "\n" "/")" ;; esac
grep -qx "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A:$B" "$DROP" && grep -qx "# base: /usr/lib/x.so:/usr/lib/y.so" "$DROP" \
  && [ "$(cat "$T/root/usr/lib/systemd/system/acvs.service")" = "$U0" ] && ok "read-only unit: the drop-in carries its list" || bad "read-only: $(cat "$DROP" 2>&1)"
ro u+w; unit 'Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/z.so'; ro a-w   # a firmware update changes the unit
run a install.sh -n
grep -qx "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/z.so:$A:$B" "$DROP" && ok "a new base list is picked up, addins kept" || bad "rebase: $(cat "$DROP")"
run a uninstall.sh
grep -qx "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/z.so:$B" "$DROP" && ok "read-only unit: uninstalling one keeps the other" || bad "ro uninstall: $(cat "$DROP")"
run b uninstall.sh
[ ! -e "$DROP" ] && [ ! -e "$(dirname "$DROP")" ] && ok "read-only unit: the drop-in goes with the last addin" || bad "ro drop-in left"
fresh; unit 'Environment="LD_PRELOAD=/usr/lib/x.so /usr/lib/y.so" FOO=1'; ro a-w
run a install.sh
grep -qx "Environment=LD_PRELOAD=/usr/lib/x.so:/usr/lib/y.so:$A" "$DROP" && ok "read-only unit, quoted list" || bad "ro quoted: $(cat "$DROP")"
fresh; unit 'Restart=always'; ro a-w
run a install.sh
grep -qx "Environment=LD_PRELOAD=$A" "$DROP" && ok "read-only unit without LD_PRELOAD" || bad "ro none: $(cat "$DROP")"

# 8. refusals: odd folders, bad manifests, missing files
refused() {   # refused <what> <id> [args]: install must fail
    if ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" $SH "$T/pkg-$2/install.sh" -y "${@:3}" >/dev/null 2>&1; then bad "$1 accepted"; else ok "$1 refused"; fi
}
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so'
refused "an odd folder" a -t '/data/x;rm'
refused "a relative folder" a -t 'rel/dir'
for m in 'ADDIN_VERSION=1.x' 'ADDIN_VERSION="1.0.0;x"' 'ADDIN_CONF=uninstall.sh' 'ADDIN_FILES=addin-lib.sh' 'ADDIN_ID="../x"' 'ADDIN_ID=' 'ADDIN_SO=../../usr/lib/evil.so' 'ADDIN_SO=liba.txt' 'ADDIN_CONF=/etc/passwd' 'ADDIN_FILES="ok.dat ../x"'; do
    pkg a; echo "$m" >> "$T/pkg-a/addin.manifest"; refused "manifest $m" a -t "$T/addins/a"
done
pkg a; rm "$T/pkg-a/a.dat"; refused "a missing file" a -t "$T/addins/a"
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so" ] && ok "refusals changed nothing" || bad "a refusal changed the unit: $(line)"
pkg a; echo n | ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" $SH "$T/pkg-a/install.sh" > "$T/out" 2>&1 || true
grep -q "/data/mpc-addins/a/" "$T/out" && grep -q cancelled "$T/out" && [ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so" ] \
  && ok "the default folder is /data/mpc-addins/<id>; answering no changes nothing" || bad "default folder / cancel: $(cat "$T/out")"

# 9. the library is checked before it goes into LD_PRELOAD
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so'
pkg a; echo so > "$T/pkg-a/liba.so"; refused "a .so that is not ELF" a -t "$T/addins/a"
pkg a; elf "$T/pkg-a/liba.so" '\002\001' '\003\000' '\050\000'; refused "a 64-bit .so" a -t "$T/addins/a"
pkg a; elf "$T/pkg-a/liba.so" '\001\001' '\003\000' '\076\000'; refused "an x86-64 .so" a -t "$T/addins/a"
pkg a; elf "$T/pkg-a/liba.so" '\001\001' '\002\000' '\050\000'; refused "an ARM executable" a -t "$T/addins/a"
[ "$(line)" = "Environment=LD_PRELOAD=/usr/lib/x.so" ] && [ ! -e "$T/addins/a" ] && ok "a bad .so changes nothing" || bad "bad .so: $(line)"

# 10. uninstall only ever deletes what the addin installed, in a folder named after it
uremoved() {   # uremoved <what> <folder>: uninstall must refuse, and the folder must survive
    mkdir -p "$2" 2>/dev/null || true
    if ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/pkg-a/uninstall.sh" -y -n -t "$2" >/dev/null 2>&1; then bad "uninstall -t $1 accepted"; else ok "uninstall -t $1 refused"; fi
}
fresh; unit 'Environment=LD_PRELOAD=/usr/lib/x.so'
mkdir -p "$T/victim/a"; echo keep > "$T/victim/keep"
uremoved "/" /
uremoved "/etc" /etc
uremoved "a folder not named after the addin" "$T/victim"
uremoved "with a .. segment" "$T/victim/x/../a"
uremoved "with a . segment" "$T/victim/./a"
uremoved "ending in /" "$T/victim/a/"
[ -f "$T/victim/keep" ] && [ -d /etc ] && ok "refused uninstalls deleted nothing" || bad "a refused uninstall deleted files"
run a install.sh; echo mine > "$T/addins/a/notes.txt"
run a uninstall.sh
[ -f "$T/addins/a/notes.txt" ] && [ ! -e "$T/addins/a/liba.so" ] && [ ! -e "$T/addins/a/a.conf" ] && [ ! -e "$T/addins/a/uninstall.sh" ] && grep -q "kept" "$T/out" \
  && ok "uninstall deletes the addin's files and keeps the user's" || bad "uninstall with a user file: $(ls "$T/addins/a" 2>&1)"

# 11. the shared drop-in records its format; an older installer leaves a newer one alone
fresh; unit 'Restart=always'; ro a-w
run a install.sh
grep -qx "# lib: 2" "$DROP" && ok "the drop-in records its format" || bad "no lib line: $(cat "$DROP")"
sed -i 's/^# lib: 2$/# lib: 99/' "$DROP"; cp "$DROP" "$T/drop.before"
refused "a drop-in from a newer installer (install)" b -t "$T/addins/b"
if ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" $SH "$T/pkg-a/uninstall.sh" -y -n -t "$T/addins/a" >/dev/null 2>&1; then bad "uninstall under a newer drop-in accepted"; else ok "a drop-in from a newer installer (uninstall) refused"; fi
cmp -s "$DROP" "$T/drop.before" && [ -f "$A" ] && ok "a newer drop-in is left as it was" || bad "a newer drop-in changed"
sed -i '/^# lib:/d' "$DROP"
run b install.sh
grep -qx "# lib: 2" "$DROP" && grep -qx "Environment=LD_PRELOAD=$A:$B" "$DROP" && ok "a drop-in without a format line is read as format 2" || bad "old drop-in: $(cat "$DROP")"

# 12. a MockbaMod card: boot.sh exports LD_PRELOAD from a file the AddOns/run_*.sh scripts fill in, so the installer
# writes a hook (and arms the file now); the hook is idempotent; uninstall removes both
fresh; unit 'Restart=always'; ro a-w
export MOCKBA_PRELOAD_FILE="$T/shm-ld" MOCKBA_MMPATH="$T/shm-mm" MOCKBA_ROOTS="$T/none"
mkdir -p "$T/card/MockbaMod" "$T/card/AddOns"; : > "$T/card/MockbaMod/env.sh"; echo "$T/card" > "$MOCKBA_MMPATH"
echo "/m/mockbaMagic.so /m/anyctrl.so " > "$MOCKBA_PRELOAD_FILE"
run a install.sh
H="$T/card/AddOns/run_a.sh"
[ -x "$H" ] && grep -qF "$A" "$MOCKBA_PRELOAD_FILE" && grep -qF "/m/mockbaMagic.so" "$MOCKBA_PRELOAD_FILE" \
  && ok "MockbaMod: hook written and the preload file armed" || bad "mockba install: $(cat "$MOCKBA_PRELOAD_FILE" 2>&1)"
sed -i "s| *$A||" "$MOCKBA_PRELOAD_FILE"; $SH "$H"; $SH "$H"
[ "$(grep -o "$A" "$MOCKBA_PRELOAD_FILE" | wc -l)" = 1 ] && ok "MockbaMod: the hook arms once, however often it runs" || bad "hook: $(cat "$MOCKBA_PRELOAD_FILE")"
cp "$MOCKBA_PRELOAD_FILE" "$T/ld.before"; $SH "$H" kill; cmp -s "$MOCKBA_PRELOAD_FILE" "$T/ld.before" && ok "MockbaMod: the hook leaves the file alone on kill" || bad "kill changed the file"
run a uninstall.sh
[ ! -e "$H" ] && ! grep -qF "$A" "$MOCKBA_PRELOAD_FILE" && grep -qF "/m/anyctrl.so" "$MOCKBA_PRELOAD_FILE" && ok "MockbaMod: uninstall removes the hook and only this addin" || bad "mockba uninstall: $(cat "$MOCKBA_PRELOAD_FILE") $(ls "$T/card/AddOns")"
fresh; rm -rf "$T/card"; run a install.sh
[ ! -e "$T/card" ] && ok "no MockbaMod: nothing extra is written" || bad "wrote files without MockbaMod"
unset MOCKBA_PRELOAD_FILE MOCKBA_MMPATH MOCKBA_ROOTS

# 13. ADDIN_NETWORK: a first interactive install asks about bind; -y and reinstalls leave it
fresh; unit 'Restart=always'; ro a-w
echo 'ADDIN_NETWORK=1' >> "$T/pkg-a/addin.manifest"; echo 'bind=127.0.0.1' > "$T/pkg-a/a.conf"
printf 'y\ny\n' | ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/pkg-a/install.sh" -t "$T/addins/a" > "$T/out" 2>&1
grep -qx 'bind=0.0.0.0' "$T/addins/a/a.conf" && ok "ADDIN_NETWORK: a yes opens it" || bad "bind: $(cat "$T/addins/a/a.conf") $(cat "$T/out")"
fresh; echo 'ADDIN_NETWORK=1' >> "$T/pkg-a/addin.manifest"; echo 'bind=127.0.0.1' > "$T/pkg-a/a.conf"
printf 'y\nn\n' | ADDIN_INSTALL_TEST=1 SYSTEMD_ROOT="$T/root" ADDIN_TEST_LOG="$T/log" $SH "$T/pkg-a/install.sh" -t "$T/addins/a" > "$T/out" 2>&1
run a install.sh
grep -qx 'bind=127.0.0.1' "$T/addins/a/a.conf" && ok "ADDIN_NETWORK: a no, and -y, keep it local" || bad "bind: $(cat "$T/addins/a/a.conf")"

[ $fails = 0 ] && echo "installer: all passed" || { echo "installer: $fails FAILED"; exit 1; }
