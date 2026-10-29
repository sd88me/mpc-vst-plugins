#!/bin/sh
# usb_stick/run.sh <stick> <work>: optionally enables SSH (enable_ssh.sh, if the stick carries authorized_key.pub
# and/or ssh_password.txt -- advanced, optional; see docs/USB_STICK.md), reapplies every already-installed addin's
# LD_PRELOAD entry (needed on a device with no persistent /etc, where it lives on /run and a reboot wipes it;
# docs/ADDINS.md, "A device with no persistent /etc"), then installs the catalog plugins named in <stick>/install.txt
# (default: plugin-manager-g2) with mpc-store.sh, which stops MPC once, starts it once, and starts it again if
# anything fails. Leaves <stick>/mpc-install-result.txt.
usb=$1; work=$2
log="$work/result.txt"
finish() {
    r=$?
    cp "$log" "$usb/mpc-install-result.txt" 2>/dev/null || true
    rm -rf "$work"
    exit "$r"
}
trap finish EXIT
exec > "$log" 2>&1
echo "MPC USB install: $(date '+%Y-%m-%d %H:%M:%S')"
if [ -z "${MPC_USB_TEST:-}" ]; then [ "$(id -u)" = 0 ] || { echo "error: not root"; exit 1; }; fi

if [ -f "$work/enable_ssh.sh" ]; then
    if [ -f "$work/authorized_key.pub" ]; then
        echo "Enabling SSH (key)"
        sh "$work/enable_ssh.sh" --key "$work/authorized_key.pub" || echo "warning: enabling SSH failed (status $?)"
    elif [ -f "$work/ssh_password.txt" ]; then
        echo "Enabling SSH (password -- advanced, less secure than a key)"
        sh "$work/enable_ssh.sh" --password "$(cat "$work/ssh_password.txt")" || echo "warning: enabling SSH failed (status $?)"
    fi
fi

# Redo every already-installed addin's LD_PRELOAD entry. A no-op where it persisted (it just rewrites the same
# thing); on a device with no persistent /etc at all (a verity rootfs, e.g. Gen2's Live III) the shared drop-in
# lives on /run and a reboot wiped it, while /data/mpc-addins/<id>/ -- including its own copy of install.sh and
# mpc-plugin.json, kept there for exactly this -- survived. -n: don't restart MPC per addin; the catalog install
# below restarts it once for everything.
for d in "${MPC_ADDINS_DIR:-/data/mpc-addins}"/*/; do
    [ -f "$d/install.sh" ] || continue
    id=$(basename "${d%/}")
    echo "Reapplying addin: $id"
    sh "$d/install.sh" -y -n -t "${d%/}" || echo "warning: reapplying addin $id failed (status $?)"
done

ids=""
if [ -f "$usb/install.txt" ]; then
    ids=$(sed -e 's/#.*//' -e 's/[[:space:]]*$//' "$usb/install.txt" | grep -E '^[a-z0-9][a-z0-9._-]*$' | tr '\n' ' ')
fi
[ -n "$ids" ] || ids="plugin-manager-g2"
echo "Installing: $ids"
settings="${MPC_SETTINGS:-$(ls /media/az01-internal/Settings/*/MPC.settings /data/Settings/*/MPC.settings 2>/dev/null | head -n 1)}"
if [ -f "$settings" ]; then
    cp "$settings" "$usb/MPC.settings.backup" 2>/dev/null && echo "MPC.settings copied to the stick (MPC.settings.backup)"
fi
# shellcheck disable=SC2086
sh "$work/mpc-store.sh" -y install $ids
rc=$?
if [ "$rc" -eq 0 ]; then echo "Done."; else echo "Install failed (status $rc); MPC was started again."; fi
exit "$rc"
