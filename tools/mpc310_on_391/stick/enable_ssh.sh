#!/bin/sh
# usb_stick/enable_ssh.sh --key <authorized_key.pub> | --password <password>: lets root in over SSH.
#
# --key (recommended): stock sshd_config already allows key-based root login and forbids empty/password auth
#   (PermitRootLogin without-password/prohibit-password, PasswordAuthentication no, PermitEmptyPasswords no);
#   nothing here weakens authentication, only adds a key.
# --password: sets root's password and turns PasswordAuthentication on -- a real reduction in login security
#   (anyone on the same network who guesses or captures the password gets a root shell). Needs a writable root
#   filesystem to set the password in: refused outright on a true read-only (dm-verity) root, most Gen2 units,
#   rather than leaving the device in a half-changed state.
#
# Two cases for a writable root, detected the same way tools/release/addin/addin-lib.sh's resolve_dropin_root() does:
#  - A writable root (or one that can be remounted rw, as on Gen1/Force): persistent across a reboot.
#  - A true read-only root (dm-verity, e.g. Gen2's Live III; remount refused outright, not just denied): --key goes
#    on tmpfs and sshd is started directly, for this boot only (re-run, e.g. by reinserting the stick, after one);
#    --password is refused here, since there is nowhere writable to put it.
set -e
MODE=""
KEYFILE=""
PASSWORD=""
while [ $# -gt 0 ]; do
    case "$1" in
        --key) KEYFILE=$2; MODE=key; shift 2 ;;
        --password) PASSWORD=$2; MODE=password; shift 2 ;;
        *) echo "usage: enable_ssh.sh --key <authorized_key.pub> | --password <password>" >&2; exit 1 ;;
    esac
done
if [ "$MODE" = key ]; then
    [ -f "$KEYFILE" ] || { echo "error: no public key file: $KEYFILE" >&2; exit 1; }
    KEY=$(cat "$KEYFILE")
    case "$KEY" in ssh-*) ;; *) echo "error: $KEYFILE does not look like an SSH public key" >&2; exit 1 ;; esac
elif [ "$MODE" = password ]; then
    [ -n "$PASSWORD" ] || { echo "error: empty password" >&2; exit 1; }
else
    echo "usage: enable_ssh.sh --key <authorized_key.pub> | --password <password>" >&2
    exit 1
fi

# sshd keeps the FIRST value it reads for a directive, and the stock sshd_config starts with `Include /etc/ssh/sshd_config.d/*.conf`
# (which sets PasswordAuthentication no, and its own AuthorizedKeysFile), so a line edited or appended further down is ignored. Put ours
# before the Include instead.
sshd_first() {
    cfg=${ENABLE_SSH_CONFIG:-/etc/ssh/sshd_config}
    [ -f "$cfg" ] || : > "$cfg"
    cp -p "$cfg" "$cfg.mpc-usb.bak" 2>/dev/null || true
    for l in "$@"; do sed -i "/^${l%% *}[ \t]/d" "$cfg"; done
    { for l in "$@"; do echo "$l"; done; cat "$cfg"; } > "$cfg.mpc-usb.new" && cat "$cfg.mpc-usb.new" > "$cfg"
    rm -f "$cfg.mpc-usb.new"
}

was_ro=0
if awk '$2 == "/" && $4 ~ /(^|,)ro(,|$)/ { f = 1 } END { exit !f }' /proc/mounts; then was_ro=1; fi
writable=0
if [ $was_ro = 0 ] || mount -o remount,rw / 2>/dev/null; then writable=1; fi

if [ "$MODE" = password ] && [ $writable = 0 ]; then
    echo "error: this device's root filesystem is read-only and can't be remounted (a verity rootfs, most Gen2 units)," >&2
    echo "so there is nowhere to persist a password. Use a key instead (it works here, on tmpfs, until the next reboot)." >&2
    exit 1
fi

if [ $writable = 1 ]; then
    echo "root is writable: installing $([ "$MODE" = key ] && echo "the key" || echo "a password") persistently"
    if [ "$MODE" = key ]; then
        mkdir -p /root/.ssh && chmod 700 /root/.ssh   # no `install` applet in the Force busybox (set -e killed the script here)
        grep -qxF "$KEY" /root/.ssh/authorized_keys 2>/dev/null || echo "$KEY" >> /root/.ssh/authorized_keys
        chmod 600 /root/.ssh/authorized_keys
        # the firmware's own drop-in points sshd at /data/ssh/authorized_keys (persistent; /root may be an overlay), so put the key there too
        mkdir -p /data/ssh 2>/dev/null && { grep -qxF "$KEY" /data/ssh/authorized_keys 2>/dev/null || echo "$KEY" >> /data/ssh/authorized_keys; chmod 600 /data/ssh/authorized_keys; }
        sshd_first "AuthorizedKeysFile .ssh/authorized_keys /data/ssh/authorized_keys"
    else
        echo "root:$PASSWORD" | chpasswd
        sshd_first "PasswordAuthentication yes" "PermitRootLogin yes" "AuthenticationMethods any"
    fi
    # enable sshd at boot (host keys are made on first boot by sshdgenkeys.service, already stock)
    for d in /lib/systemd/system /usr/lib/systemd/system; do
        [ -f "$d/sshd.service" ] && ln -sf "$d/sshd.service" /etc/systemd/system/multi-user.target.wants/sshd.service 2>/dev/null && break
    done
    systemctl daemon-reload 2>/dev/null || true
    # restart, not start: an sshd that is already up (a stock Force starts one) would keep its old config and refuse the new setup
    systemctl restart sshd 2>/dev/null || systemctl start sshd 2>/dev/null || /usr/sbin/sshd 2>/dev/null || true
    sync
    [ $was_ro = 0 ] || mount -o remount,ro / 2>/dev/null || echo "warning: / is still writable; it is read-only again after a reboot" >&2
    echo "done: $([ "$MODE" = key ] && echo "the key is installed" || echo "the password is set") and sshd starts at boot"
else
    echo "root is read-only and could not be remounted (a verity rootfs): starting sshd on demand instead, until the next reboot"
    mkdir -p /var/run/sshd /run/sshd /run/ssh
    cp "$KEYFILE" /run/ssh/authorized_keys
    chmod 600 /run/ssh/authorized_keys
    AUTHOPTS="-o AuthorizedKeysFile=/run/ssh/authorized_keys -o PermitRootLogin=prohibit-password -o PubkeyAuthentication=yes -o PasswordAuthentication=no -o PermitEmptyPasswords=no"
    HK=""
    for k in /etc/ssh/ssh_host_ed25519_key /etc/ssh/ssh_host_ecdsa_key /etc/ssh/ssh_host_rsa_key; do
        [ -f "$k" ] || continue
        case "$(stat -c %a "$k" 2>/dev/null)" in
            600|400|640|440) HK="$HK -h $k" ;;
        esac
    done
    if [ -z "$HK" ]; then
        ssh-keygen -q -t ed25519 -f /run/ssh/hostkey -N "" && HK="-h /run/ssh/hostkey"
    fi
    [ -f /run/ssh/sshd.pid ] && kill "$(cat /run/ssh/sshd.pid 2>/dev/null)" 2>/dev/null
    # shellcheck disable=SC2086
    /usr/sbin/sshd $HK $AUTHOPTS -o PidFile=/run/ssh/sshd.pid
    echo "done: sshd is running with that key, until the next reboot (re-run this, e.g. by reinserting the stick, after one)"
fi
