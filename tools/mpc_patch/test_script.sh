#!/bin/sh
# Test mpc-drum-pad-patch.sh in BusyBox (the Force's shell) against copies of the binary, in test mode (no mounts, no restart).
# Fixtures in /t: MPC.stock (the stock 3.9.1.2 MPC), MPC.v1 (stock + the earlier Machinedrum-only patch), v1bk/orig-regions.txt
# (that patch's saved original bytes), bad.bin. Run:  docker run --rm -v <fixtures>:/t busybox:1.36 sh /t/test_script.sh
S=/t/mpc-drum-pad-patch.sh
STOCK=592eebc8e1ce0797dc8c98e7002143b8
V2=@@V2@@
V1=10a7d0bb4e5fb66ffaa6b2c6a001eef2
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (got '$2', want '$3')"; fail=1; fi; }
md5() { md5sum "$1" | cut -d' ' -f1; }
run() { MPC_PATCH_TEST=$1 MPC_PATCH_BACKUP=$2 sh $S $3 2>&1; }

rm -f /t/w[2-9]
# 1 status on stock
cp /t/MPC.stock /t/w1; out=$(run /t/w1 /t/bk1 status); echo "$out" | grep -q 'not patched'; check "status on stock" $? 0
rm -f /t/w[2-9]
# 2 install on stock, wrong confirmation: cancelled, file untouched
out=$(echo nope | run /t/w1 /t/bk1 install); echo "$out" | grep -q cancelled; check "wrong confirmation cancels" $? 0
check "  file untouched" "$(md5 /t/w1)" $STOCK
rm -f /t/w[2-9]
# 3 install with PATCH
out=$(echo PATCH | run /t/w1 /t/bk1 install); echo "$out" | grep -q 'patched OK'; check "install prints patched OK" $? 0
check "  checksum is the v2 patched build" "$(md5 /t/w1)" $V2
check "  full backup is the stock file" "$(md5 /t/bk1/MPC-3.9.1.2.orig)" $STOCK
rm -f /t/w[2-9]
# 4 status, install again (no-op)
out=$(run /t/w1 /t/bk1 status); echo "$out" | grep -q 'PATCHED'; check "status after install" $? 0
out=$(echo PATCH | run /t/w1 /t/bk1 install); echo "$out" | grep -q 'Already patched'; check "second install is a no-op" $? 0
rm -f /t/w[2-9]
# 5 uninstall
out=$(run /t/w1 /t/bk1 uninstall); echo "$out" | grep -q 'restored stock'; check "uninstall says restored" $? 0
check "  checksum is stock again" "$(md5 /t/w1)" $STOCK
rm -f /t/w[2-9]
# 6 uninstall using only the saved regions (full backup removed)
cp /t/MPC.stock /t/w2; echo PATCH | run /t/w2 /t/bk2 install >/dev/null; rm /t/bk2/MPC-3.9.1.2.orig
run /t/w2 /t/bk2 uninstall >/dev/null; check "uninstall from saved regions only" "$(md5 /t/w2)" $STOCK
rm -f /t/w[2-9]
# 7 uninstall using only the full backup (regions file removed)
cp /t/MPC.stock /t/w3; echo PATCH | run /t/w3 /t/bk3 install >/dev/null; rm /t/bk3/orig-regions.txt
run /t/w3 /t/bk3 uninstall >/dev/null; check "uninstall from full backup only" "$(md5 /t/w3)" $STOCK
rm -f /t/w[2-9]
# 8 upgrade from the earlier Machinedrum-only patch
cp /t/MPC.v1 /t/w4; mkdir -p /t/bk4; cp /t/v1bk/orig-regions.txt /t/bk4/
out=$(run /t/w4 /t/bk4 status); echo "$out" | grep -q 'earlier version'; check "status recognises the earlier patch" $? 0
out=$(echo PATCH | run /t/w4 /t/bk4 install); check "  upgrade lands on the v2 build" "$(md5 /t/w4)" $V2
run /t/w4 /t/bk4 uninstall >/dev/null; check "  and uninstall returns to stock" "$(md5 /t/w4)" $STOCK
rm -f /t/w[2-9]
# 9 upgrade without the saved bytes refuses and changes nothing
cp /t/MPC.v1 /t/w5; out=$(echo PATCH | run /t/w5 /t/bk5 install); echo "$out" | grep -q 'missing'; check "upgrade without saved bytes refuses" $? 0
check "  file untouched" "$(md5 /t/w5)" $V1
rm -f /t/w[2-9]
# 10 a file that is not the 3.9.1.2 MPC
cp /t/bad.bin /t/w6; out=$(echo PATCH | run /t/w6 /t/bk6 install); echo "$out" | grep -q 'not MPC OS 3.9.1.2'; check "other firmware refused" $? 0
cmp -s /t/bad.bin /t/w6; check "  file untouched" $? 0
rm -f /t/w[2-9]
# 12 upgrade from this patch's earlier name table (the 2026-10-02 build: fixtures MPC.v3old + v3bk/orig-regions.txt)
cp /t/MPC.v3old /t/w7; mkdir -p /t/bk7; cp /t/v3bk/orig-regions.txt /t/bk7/
out=$(run /t/w7 /t/bk7 status); echo "$out" | grep -q 'earlier version'; check "status recognises the earlier name table" $? 0
out=$(echo PATCH | run /t/w7 /t/bk7 install); check "  upgrade lands on the current build" "$(md5 /t/w7)" $V2
rm -f /t/w[2-9]
# 11 uninstall on a stock file
out=$(run /t/w1 /t/bk1 uninstall); echo "$out" | grep -q 'Already stock'; check "uninstall on stock is a no-op" $? 0
[ $fail = 0 ] && echo PASSED || echo FAILED
exit $fail
