#!/bin/sh
# Test mpc-drum-pad-patch.sh on a Gen1 3.10.0 MPC in BusyBox, test mode (no mounts, no restart). Fixtures in /t: mpc-drum-pad-patch.sh,
# MPC.g1 (the stock Gen1 3.10.0 MPC). Run:  docker run --rm -v <fixtures>:/t busybox:1.36 sh /t/test_script_gen1.sh
S=/t/mpc-drum-pad-patch.sh
STOCK=b6cc8e7a398bdf6c3fd8f7176eecd3ee
PATCHED=496c22afe2f57f5c583072a02d754f07
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (got '$2', want '$3')"; fail=1; fi; }
md5() { md5sum "$1" | cut -d' ' -f1; }
run() { MPC_PATCH_TEST=$1 MPC_PATCH_BACKUP=$2 sh $S $3 2>&1; }
rm -rf /t/w* /t/bk*
cp /t/MPC.g1 /t/w1
out=$(run /t/w1 /t/bk1 status); echo "$out" | grep -q 'stock Gen1 MPC OS 3.10.0, not patched'; check "status on stock Gen1" $? 0
echo "$out" | grep -q 'state=stock supported=1'; check "  STATE line" $? 0
out=$(echo nope | run /t/w1 /t/bk1 install); echo "$out" | grep -q cancelled; check "wrong confirmation cancels" $? 0
check "  file untouched" "$(md5 /t/w1)" $STOCK
out=$(echo PATCH | run /t/w1 /t/bk1 install); echo "$out" | grep -q 'patched OK'; check "install prints patched OK" $? 0
check "  checksum is the patched build" "$(md5 /t/w1)" $PATCHED
check "  full backup is the stock file" "$(md5 /t/bk1/MPC-3.10.0-Gen1.orig)" $STOCK
out=$(run /t/w1 /t/bk1 status); echo "$out" | grep -q 'PATCHED'; check "status after install" $? 0
out=$(echo PATCH | run /t/w1 /t/bk1 install); echo "$out" | grep -q 'Already patched'; check "second install is a no-op" $? 0
out=$(run /t/w1 /t/bk1 uninstall); echo "$out" | grep -q 'restored stock'; check "uninstall says restored" $? 0
check "  checksum is stock again" "$(md5 /t/w1)" $STOCK
cp /t/MPC.g1 /t/w2; echo PATCH | run /t/w2 /t/bk2 install >/dev/null; rm /t/bk2/MPC-3.10.0-Gen1.orig
run /t/w2 /t/bk2 uninstall >/dev/null; check "uninstall from saved regions only" "$(md5 /t/w2)" $STOCK
cp /t/MPC.g1 /t/w3; echo PATCH | run /t/w3 /t/bk3 install >/dev/null; rm /t/bk3/orig-regions.txt
run /t/w3 /t/bk3 uninstall >/dev/null; check "uninstall from the full backup only" "$(md5 /t/w3)" $STOCK
head -c 1000 /t/MPC.g1 > /t/w4; out=$(echo PATCH | run /t/w4 /t/bk4 install); echo "$out" | grep -q 'not a supported'; check "unknown build refused" $? 0
rm -rf /t/w* /t/bk*
exit $fail
