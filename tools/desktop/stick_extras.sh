#!/bin/sh
# mpc-extras.sh <runtime folder>: what the advanced stick does before (or instead of) opening the plugin manager.
#  1. SSH, if the stick carries a key or a password (enable_ssh.sh).
#  2. Reapplies every already-installed addin's LD_PRELOAD entry (a no-op where it persisted; on a device with no persistent /etc,
#     e.g. a Live III, the drop-in lives on /run and a reboot wiped it, while /data/mpc-addins/<id>/ survived: docs/ADDINS.md).
#  3. Restarts MPC once if its running LD_PRELOAD differs from what the service now says, so the addins are loaded (and so the
#     plugin manager, which reads the running MPC's LD_PRELOAD, sees them).
runtime=$1
echo "MPC USB advanced stick: $(date '+%Y-%m-%d %H:%M:%S')"
if [ -z "${MPC_USB_TEST:-}" ]; then [ "$(id -u)" = 0 ] || { echo "error: not root"; exit 1; }; fi

if [ -f "$runtime/enable_ssh.sh" ]; then
    if [ -f "$runtime/authorized_key.pub" ]; then
        echo "Enabling SSH (key)"
        sh "$runtime/enable_ssh.sh" --key "$runtime/authorized_key.pub" || echo "warning: enabling SSH failed (status $?)"
    elif [ -f "$runtime/ssh_password.txt" ]; then
        echo "Enabling SSH (password -- advanced, less secure than a key)"
        sh "$runtime/enable_ssh.sh" --password "$(cat "$runtime/ssh_password.txt")" || echo "warning: enabling SSH failed (status $?)"
    fi
fi

reapplied=0
for d in "${MPC_ADDINS_DIR:-/data/mpc-addins}"/*/; do
    [ -f "$d/install.sh" ] || continue
    id=$(basename "${d%/}")
    echo "Reapplying addin: $id"
    # -n: don't restart MPC per addin; step 3 restarts it once for all of them.
    if sh "$d/install.sh" -y -n -t "${d%/}"; then reapplied=$((reapplied + 1)); else echo "warning: reapplying addin $id failed (status $?)"; fi
done

if [ "$reapplied" -gt 0 ] && [ -z "${MPC_USB_TEST:-}" ]; then
    want=$(systemctl show acvs -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^LD_PRELOAD=' || true)
    pid=$(systemctl show acvs -p MainPID --value 2>/dev/null || true)
    have=""
    [ -z "$pid" ] || [ "$pid" = 0 ] || have=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep '^LD_PRELOAD=' || true)
    if [ -n "$want" ] && [ "$want" != "$have" ]; then
        echo "Restarting MPC once so the addins load"
        systemctl restart acvs || echo "warning: restarting MPC failed"
        i=0
        while ! pidof MPC >/dev/null 2>&1 && [ "$i" -lt 60 ]; do sleep 1; i=$((i + 1)); done
    fi
fi
echo "Done."
