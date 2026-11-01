#!/bin/sh
# Test the Gen2 (aarch64) branch of mpc-drum-pad-patch.sh in BusyBox against copies of the stock Gen2 binaries, in test mode
# (no systemctl, no running-MPC check; the "root MPC", the kit and /run are folders under /t).
# Fixtures in /t: mpc-drum-pad-patch.sh, MPC-3.9.1 and MPC-3.10.0 (the stock /usr/bin/MPC of each build), bad.bin, and
# expect.txt with lines "<build> <stock md5> <patched md5>". Run:
#   docker run --rm -v <fixtures>:/t busybox:1.36 sh /t/test_script_gen2.sh
S=/t/mpc-drum-pad-patch.sh
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (got '$2', want '$3')"; fail=1; fi; }
md5() { md5sum "$1" | cut -d' ' -f1; }
exp() { grep "^$1 " /t/expect.txt | cut -d' ' -f$2; }
run() {   # $1 root MPC, rest = script args
    r=$1; shift
    MPC_PATCH_ARCH=aarch64 MPC_G2_TEST=1 MPC_G2_DIR=/t/w/g2 MPC_G2_DROPIN_DIR=/t/w/dd MPC_G2_ROOTMPC=$r sh $S "$@" 2>&1
}
fresh() { rm -rf /t/w; mkdir -p /t/w/dd; }

for B in 3.9.1 3.10.0; do
    ST=$(exp $B 2); PT=$(exp $B 3)
    echo "== Gen2 $B"
    fresh
    if [ $B = 3.10.0 ]; then   # the kit case: a drop-in binds the kit's MPC; the root's MPC is another file
        cp /t/MPC-3.9.1 /t/w/rootmpc; ROOT=/t/w/rootmpc
        printf '[Service]\nBindReadOnlyPaths=/t/MPC-3.10.0:/usr/bin/MPC /t/akai:/usr/share/Akai\n' > /t/w/dd/95-mpc310.conf
        SRC=/t/MPC-3.10.0
    else ROOT=/t/MPC-3.9.1; SRC=$ROOT; fi
    out=$(run $ROOT status); echo "$out" | grep -q 'not patched'; check "status on stock" $? 0
    echo "$out" | grep -q "state=stock supported=1"; check "  STATE line" $? 0
    out=$(echo nope | run $ROOT install); echo "$out" | grep -q cancelled; check "wrong confirmation cancels" $? 0
    [ ! -e /t/w/g2/MPC ] && [ ! -e /t/w/dd/94-mpc-drumpad.conf ]; check "  nothing created" $? 0
    out=$(echo PATCH | run $ROOT install); echo "$out" | grep -q 'patched OK'; check "install prints patched OK" $? 0
    check "  patched copy has the patched checksum" "$(md5 /t/w/g2/MPC)" $PT
    check "  source untouched" "$(md5 $SRC)" $ST
    grep -q "BindReadOnlyPaths=/t/w/g2/MPC:/usr/bin/MPC" /t/w/dd/94-mpc-drumpad.conf; check "  drop-in binds the copy" $? 0
    [ "$(ls /t/w/dd | head -n 1)" = 94-mpc-drumpad.conf ]; check "  drop-in sorts first" $? 0
    out=$(run $ROOT status); echo "$out" | grep -q 'PATCHED and running'; check "status after install" $? 0
    out=$(echo PATCH | run $ROOT install); echo "$out" | grep -q 'Already patched'; check "second install is a no-op" $? 0
    rm /t/w/dd/94-mpc-drumpad.conf   # a reboot clears /run
    out=$(run $ROOT status); echo "$out" | grep -q 'not active'; check "after a reboot: prepared, not active" $? 0
    out=$(run $ROOT reapply); echo "$out" | grep -q 'drop-in written'; check "reapply writes the drop-in" $? 0
    out=$(run $ROOT status); echo "$out" | grep -q 'PATCHED and running'; check "  active again" $? 0
    out=$(run $ROOT uninstall); echo "$out" | grep -q 'restored'; check "uninstall says restored" $? 0
    [ ! -e /t/w/g2/MPC ] && [ ! -e /t/w/dd/94-mpc-drumpad.conf ]; check "  copy and drop-in gone" $? 0
    check "  source still stock" "$(md5 $SRC)" $ST
    out=$(run $ROOT uninstall); echo "$out" | grep -q 'Already stock'; check "second uninstall is a no-op" $? 0
    out=$(run $ROOT reapply); echo "$out" | grep -q 'nothing installed'; check "reapply with nothing installed" $? 0
done

echo "== other cases"
fresh; cp /t/MPC-3.9.1 /t/w/rootmpc
echo PATCH | run /t/w/rootmpc install >/dev/null
printf 'x' >> /t/w/rootmpc    # the system's MPC changes (an update): the saved copy no longer fits
rm /t/w/dd/94-mpc-drumpad.conf
out=$(run /t/w/rootmpc reapply); echo "$out" | grep -q 'different MPC\|knows'; check "reapply refuses a copy for another MPC" $? 0
[ ! -e /t/w/dd/94-mpc-drumpad.conf ]; check "  no drop-in written" $? 0
fresh; out=$(run /t/bad.bin status); echo "$out" | grep -q 'state=unsupported supported=0'; check "unknown build: unsupported" $? 0
out=$(echo PATCH | run /t/bad.bin install); echo "$out" | grep -q 'Refusing'; check "unknown build: install refuses" $? 0
out=$(run /t/MPC-3.9.1 bogus); echo "$out" | grep -q -i 'usage\|status'; check "bad command prints usage" $? 0
exit $fail
