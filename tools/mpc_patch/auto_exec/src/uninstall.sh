#!/bin/sh
set -eu
# Removes the patch: stops the timer, takes the executable mount off (a normal umount, never forced or lazy), deletes the files this
# patch installed. Plugins, skins, MPC.settings and fstab are not touched. Original: timomacquis, 0.1.3 (adapted: the drive and folder
# comes from the mounts, there is no config; AEX_PREFIX, tests only, redirects the paths).
P=${AEX_PREFIX:-}
if [ -z "$P" ]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi   # fixed PATH on the device; tests (AEX_PREFIX) bring their own shims
[ "$(id -u)" = 0 ] || { echo 'Root required'; exit 1; }
[ -f "$P/etc/auto-exec/VERSION" ] || { echo 'Patch not installed'; exit 0; }
[ "$(cat "$P/etc/auto-exec/VERSION")" = 0.3.2 ] || { echo 'Different version: use its matching uninstaller'; exit 1; }
mpc_service() {
 if systemctl cat acvs >/dev/null 2>&1; then echo acvs
 elif systemctl cat inmusic-mpc >/dev/null 2>&1; then echo inmusic-mpc
 else echo acvs; fi
}
for pid in $(pidof MPC || true); do
 if grep -q " /media/.*/Synths/" "/proc/$pid/maps"; then
  echo "MPC is using a plugin from a drive's Synths folder. Save the project, stop MPC, then retry the removal."
  echo "Command after saving: systemctl stop $(mpc_service)"
  exit 1
 fi
done
# Retain the existing enabled state if revert fails.
ENABLED=0
systemctl is-enabled --quiet auto-exec.timer && ENABLED=1 || true
systemctl disable --now auto-exec.timer
systemctl stop auto-exec.service
if ! /bin/sh "$P/etc/auto-exec/auto-exec.sh" release; then
 [ "$ENABLED" = 0 ] || systemctl enable --now auto-exec.timer
 echo 'Uninstallation cancelled: mount busy or unmanaged'
 exit 1
fi
/bin/sh "$P/etc/auto-exec/root-bootstrap.sh" remove
systemctl stop auto-exec-bootstrap.service 2>/dev/null || true
rm -f "$P/etc/systemd/system/auto-exec.service" "$P/etc/systemd/system/auto-exec.timer"
rm -f "$P/etc/auto-exec/auto-exec.sh" "$P/etc/auto-exec/VERSION" "$P/etc/auto-exec/uninstall.sh" "$P/etc/auto-exec/bootstrap.sh" "$P/etc/auto-exec/root-bootstrap.sh"
rmdir "$P/etc/auto-exec" 2>/dev/null || true
systemctl daemon-reload
rm -f "${AUTO_EXEC_STATE:-$P/run/auto-exec}/lock" "${AUTO_EXEC_STATE:-$P/run/auto-exec}/owned.mounts"
rmdir "${AUTO_EXEC_STATE:-$P/run/auto-exec}" 2>/dev/null || true
sync
echo 'Patch removed. The drive itself stays mounted as it was.'
echo 'Backups remain in /data/mpc-vst-plugins/backups.'
echo "If MPC was stopped manually, restart it: systemctl start $(mpc_service)"
echo 'Plugins on the drive stay where they are, but they will not load again until the patch is back (the drives are noexec).'
