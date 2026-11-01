#!/bin/sh
# mpc310-on-391 stick, run.sh <stick> <work>: every boot, as root (started by open.sh from MPC's USB autorun).
#  1. SSH for this boot, if the stick carries authorized_key.pub (optional).
#  2. Re-add installed addins (the Live III has no persistent /etc: their drop-in lives on /run).
#  3. Install or update the MPC 3.10 kit in /data/mpc310 from the stick (checked against kit.sha256), first boot only.
#  4. Run MPC 3.10 for this boot: a /run drop-in binds the kit over /usr/bin/MPC and /usr/share/Akai.
#  5. Run each addin's own boot.sh (if it has one), put the 16-pad drum patch back if it was installed (its own reapply),
#     then restart MPC once if it is not 3.10 yet or not running the patched copy.
# A file named disable-310 at the stick's root skips 3-5 (plain 3.9.1). Leaves <stick>/mpc310-result.txt.
usb=$1; work=$2
log="$work/result.txt"
KIT=/data/mpc310
D=/run/systemd/system/acvs.service.d
S=/data/Settings/MPC/MPC.settings
finish() { r=$?; cp "$log" "$usb/mpc310-result.txt" 2>/dev/null || true; rm -rf "$work"; exit "$r"; }
trap finish EXIT
exec > "$log" 2>&1
echo "mpc310-on-391: $(date '+%Y-%m-%d %H:%M:%S')"
if [ -z "${MPC_USB_TEST:-}" ]; then [ "$(id -u)" = 0 ] || { echo "error: not root"; exit 1; }; fi
mpc_version() { p=$(pidof MPC || true); [ -n "$p" ] && strings "/proc/$p/exe" 2>/dev/null | grep -m1 -E '^3\.[0-9]+\.[0-9.]+ \(' || true; }

ssh_on=0
if [ -f "$work/enable_ssh.sh" ] && [ -f "$work/authorized_key.pub" ]; then
    echo "SSH: enabling for this boot"
    sh "$work/enable_ssh.sh" --key "$work/authorized_key.pub" && ssh_on=1 || echo "warning: enabling SSH failed"
fi

for d in "${MPC_ADDINS_DIR:-/data/mpc-addins}"/*/; do
    [ -f "$d/install.sh" ] || continue
    echo "Re-adding addin: $(basename "${d%/}")"
    sh "$d/install.sh" -y -n -t "${d%/}" || echo "warning: re-adding $(basename "${d%/}") failed"
done

if [ -f "$usb/disable-310" ]; then
    echo "disable-310 found on the stick: staying on MPC 3.9.1"
elif [ -f /run/mpc310-boot-done ]; then
    echo "already set up this boot"
else
    : > /run/mpc310-boot-done
    want=$(cat "$usb/mpc310-kit/VERSION" 2>/dev/null || true)
    have=$(cat "$KIT/VERSION" 2>/dev/null || true)
    if [ -n "$want" ] && [ "$want" != "$have" ]; then
        echo "Installing MPC $want to $KIT (first boot or update)"
        need=$(du -sk "$usb/mpc310-kit" | cut -f1); free=$(df -k /data | awk 'NR == 2 { print $4 }')
        rm -rf "$KIT.new"
        if [ "$free" -le $((need + 51200)) ]; then
            echo "error: not enough space in /data (need ${need} KB + 50 MB); keeping the installed kit, if any"
        elif ! cp -R "$usb/mpc310-kit" "$KIT.new" || ! (cd "$KIT.new" && sha256sum -c "$work/kit.sha256" >/dev/null); then
            echo "error: the kit copy does not match kit.sha256; keeping the installed kit, if any"; rm -rf "$KIT.new"
        else
            chmod 755 "$KIT.new/MPC"
            rm -rf "$KIT.old"; if [ -d "$KIT" ]; then mv "$KIT" "$KIT.old"; fi; mv "$KIT.new" "$KIT"; rm -rf "$KIT.old"
        fi
    fi
    if [ -x "$KIT/MPC" ] && [ -d "$KIT/Akai/SME0" ]; then
        [ -f "$S.bak-before-310" ] || cp -p "$S" "$S.bak-before-310" 2>/dev/null || true
        mkdir -p "$D"
        printf '[Service]\nBindReadOnlyPaths=%s/MPC:/usr/bin/MPC %s/Akai:/usr/share/Akai\n' "$KIT" "$KIT" > "$D/95-mpc310.conf.new"
        mv "$D/95-mpc310.conf.new" "$D/95-mpc310.conf"
        systemctl daemon-reload
        for d in "${MPC_ADDINS_DIR:-/data/mpc-addins}"/*/; do
            [ -f "$d/boot.sh" ] || continue
            echo "Boot hook: $(basename "${d%/}")"
            sh "$d/boot.sh" || echo "warning: boot hook $(basename "${d%/}") failed"
        done
        # the 16-pad drum patch (mpc-drum-pad-patch.sh install on this device): put its /run drop-in back
        DP=/data/mpc-drumpad; drum=0
        if [ -f "$DP/mpc-drum-pad-patch.sh" ]; then
            sh "$DP/mpc-drum-pad-patch.sh" reapply || echo "warning: drum-pad reapply failed"
            [ -f "$D/94-mpc-drumpad.conf" ] && drum=1
        fi
        p=$(pidof MPC || true)
        if [ $drum = 1 ] && [ -n "$p" ] && [ "$(md5sum "/proc/$p/exe" | cut -d' ' -f1)" != "$(md5sum "$DP/MPC" | cut -d' ' -f1)" ]; then
            echo "Restarting MPC with the drum-pad patch"; systemctl restart acvs; sleep 8
        else
            case "$(mpc_version)" in
            3.10.*) echo "MPC is already 3.10" ;;
            *) echo "Restarting MPC as 3.10"; systemctl restart acvs; sleep 8 ;;
            esac
        fi
        echo "MPC now: $(mpc_version), acvs $(systemctl is-active acvs)"
    else
        echo "error: no MPC 3.10 kit in $KIT and none on the stick"
    fi
fi

if [ $ssh_on = 1 ]; then
    echo "Staying alive so sshd (in this unit) keeps running until reboot."
    cp "$log" "$usb/mpc310-result.txt" 2>/dev/null || true
    trap - EXIT
    exec sleep 31536000
fi
