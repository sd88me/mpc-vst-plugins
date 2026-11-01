#!/bin/sh
# Offline test of stick/run.sh in an Alpine (BusyBox) container, like the device's userland. systemctl, pidof and
# strings are stubbed; the "MPC" is a tiny file carrying a version string. usage: tests/run_test.sh
set -eu
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD":/src:ro alpine:3.20 sh -eu -c '
fail=0; ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
mkdir -p /stub /data/Settings/MPC /usb/autorun/runtime /usb/mpc310-kit/Akai/SME0
echo settings > /data/Settings/MPC/MPC.settings
printf "#!/bin/sh\necho \"systemctl \$*\" >> /tmp/calls\n" > /stub/systemctl
printf "#!/bin/sh\nexit 1\n" > /stub/pidof
chmod +x /stub/*; export PATH=/stub:$PATH MPC_USB_TEST=1
echo "3.10.0.49 (test)" > /usb/mpc310-kit/VERSION; echo bin > /usb/mpc310-kit/MPC; echo x > /usb/mpc310-kit/Akai/SME0/f
(cd /usb/mpc310-kit && find . -type f | sort | xargs sha256sum) > /usb/autorun/runtime/kit.sha256
cp /src/stick/open.sh /usb/autorun/; cp /src/stick/run.sh /usb/autorun/runtime/
mkdir -p /data/mpc-addins/demo; printf "echo hook ran >> /tmp/calls\n" > /data/mpc-addins/demo/boot.sh
sh /usb/autorun/open.sh || true
r=/usb/mpc310-result.txt
[ -x /data/mpc310/MPC ] && [ "$(cat /data/mpc310/VERSION)" = "3.10.0.49 (test)" ] && ok "kit installed on first boot" || no "kit installed"
grep -q "BindReadOnlyPaths=/data/mpc310/MPC:/usr/bin/MPC /data/mpc310/Akai:/usr/share/Akai" /run/systemd/system/acvs.service.d/95-mpc310.conf && ok "3.10 drop-in written" || no "drop-in"
grep -q "hook ran" /tmp/calls && ok "addin boot hook ran" || no "boot hook"
grep -q "systemctl restart acvs" /tmp/calls && ok "MPC restarted once" || no "restart"
[ -f /data/Settings/MPC/MPC.settings.bak-before-310 ] && ok "settings backed up" || no "settings backup"
: > /tmp/calls; sh /usb/autorun/open.sh || true
! grep -q restart /tmp/calls && grep -q "already set up this boot" $r && ok "second run in the same boot does nothing" || no "marker"
rm -f /run/mpc310-boot-done /run/systemd/system/acvs.service.d/95-mpc310.conf; echo y > /usb/disable-310; sh /usb/autorun/open.sh || true
[ ! -f /run/systemd/system/acvs.service.d/95-mpc310.conf ] && grep -q disable-310 $r && ok "disable-310 keeps 3.9.1" || no "disable-310"
rm -f /usb/disable-310 /run/mpc310-boot-done; echo tampered > /usb/mpc310-kit/MPC; echo "3.10.0.50 (test)" > /usb/mpc310-kit/VERSION
sh /usb/autorun/open.sh || true
grep -q "does not match kit.sha256" $r && [ "$(cat /data/mpc310/VERSION)" = "3.10.0.49 (test)" ] && ok "tampered kit refused, old kit kept" || no "tamper check"
grep -q "BindReadOnlyPaths" /run/systemd/system/acvs.service.d/95-mpc310.conf && ok "and 3.10 still runs from the old kit" || no "fallback to old kit"
# the 16-pad drum patch, installed earlier: the stick calls its reapply, then restarts MPC because the running MPC is not the patched copy
mkdir -p /data/mpc-drumpad; echo patched > /data/mpc-drumpad/MPC
printf "echo reapply >> /tmp/calls\nmkdir -p /run/systemd/system/acvs.service.d; : > /run/systemd/system/acvs.service.d/94-mpc-drumpad.conf\n" > /data/mpc-drumpad/mpc-drum-pad-patch.sh
printf "#!/bin/sh\necho 1234\n" > /stub/pidof
rm -f /run/mpc310-boot-done; : > /tmp/calls; sh /usb/autorun/open.sh || true
grep -q "^reapply" /tmp/calls && ok "drum-pad reapply called" || no "drum-pad reapply"
[ $fail = 0 ] && echo "ALL OK" || { echo FAILURES; cat $r; exit 1; }
'
