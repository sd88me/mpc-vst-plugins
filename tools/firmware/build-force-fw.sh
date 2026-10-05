#!/bin/sh
# Build a minimally-modified Akai Force firmware image from Akai's factory
# update, giving root SSH and (optionally) the MockbaMod SD-card hook.
#
# Changes made to Akai's rootfs (nothing else is touched):
#   1. Root login, by any mix of:
#        -p PASS  root password (SHA-512 hash in /etc/shadow)
#        -n       no password: anyone on the network can log in as root
#        -k FILE  SSH public key
#      For -p/-n, Akai's sshd drop-in (sshd_config.d/10-az0x.conf) is
#      rewritten to allow root password login; sshd_config stays factory.
#      /root/.ssh/authorized_keys holds only the -k key; Akai's
#      cert-authority line is dropped unless -a is given.
#   2. sshd enabled at boot (multi-user.target.wants symlink)
#   3. Akai's baked-in ssh_host_ed25519_key removed: every Force and MPC
#      ships the same one, so sshdgenkeys now creates a unique key per
#      device on first boot (stored in the persistent /etc overlay)
#   4. -s only: /usr/bin/az01-launch-MPC replaced by tools/firmware/fw/
#      az01-launch-MPC (Akai's launcher + a hook that execs
#      /media/662522/boot.sh when that card is present)
#
# Usage:
#   tools/firmware/build-force-fw.sh -f <Force X.Y.Z Updater.exe | update.img> \
#       [-p PASS | -n] [-k key.pub] [-s] [-a] [-o out.img] [-w workdir]
#   At least one of -p, -n, -k is required. "-p -" prompts for the
#   password, keeping it out of shell history.
#     -s  include the SD-card boot.sh hook (needed for MockbaMod AddOns)
#     -a  keep Akai's own cert-authority line in authorized_keys
#
# Runs as a normal user: rootfs is edited with debugfs, no loop mounts.
# Needs: python3, xz, debugfs/e2fsck (e2fsprogs); docker only to unpack an
# Updater .exe (or pass the update.img directly).

set -e

HERE=$(cd "$(dirname "$0")" && pwd)
FACTORY= PUBKEY= PASS= NOPASS=0 SDHOOK=0 KEEPCA=0 OUT= WORK=${WORK:-$HOME/.cache/force-fw-build}

while getopts f:k:p:nsao:w: opt; do
    case $opt in
        f) FACTORY=$OPTARG ;;
        k) PUBKEY=$OPTARG ;;
        p) PASS=$OPTARG ;;
        n) NOPASS=1 ;;
        s) SDHOOK=1 ;;
        a) KEEPCA=1 ;;
        o) OUT=$OPTARG ;;
        w) WORK=$OPTARG ;;
        *) sed -n '2,29p' "$0"; exit 1 ;;
    esac
done
usage() { sed -n '2,35p' "$0"; exit 1; }
[ -f "$FACTORY" ] || usage
[ -n "$PASS$PUBKEY" ] || [ $NOPASS = 1 ] || usage
[ -n "$PASS" ] && [ $NOPASS = 1 ] && { echo "-p and -n are exclusive" >&2; exit 1; }
if [ -n "$PUBKEY" ]; then
    grep -qE '^(ssh-|ecdsa-)' "$PUBKEY" || { echo "$PUBKEY is not an SSH public key" >&2; exit 1; }
fi
[ "$PASS" = - ] && { printf 'Root password: ' >&2; read -r PASS; [ -n "$PASS" ] || exit 1; }

mkdir -p "$WORK"
FACTORY=$(readlink -f "$FACTORY")

# 1. Get Akai's update.img (the Updater .exe is a 7-Zip SFX)
case "$FACTORY" in
    *.exe|*.EXE)
        echo ">> Unpacking update.img from $(basename "$FACTORY")"
        cp "$FACTORY" "$WORK/updater.exe"
        docker run --rm -v "$WORK:/w" -w /w alpine sh -c \
            "apk add -q 7zip >/dev/null && 7z e -y updater.exe update.img >/dev/null && chown $(id -u):$(id -g) update.img"
        rm -f "$WORK/updater.exe"
        IMG=$WORK/update.img ;;
    *) IMG=$FACTORY ;;
esac

# 2. Pull the xz rootfs out of the AZ01 container (verifies Akai's sha1)
echo ">> Extracting rootfs"
python3 - "$IMG" "$WORK/rootfs.xz" <<'EOF'
import sys, struct, hashlib
d = open(sys.argv[1], 'rb').read()
assert d[:4] == b'AZ01', 'not an AZ01 image'
p = d.find(b'PARTL')
size = struct.unpack('<Q', d[p+8:p+16])[0]
off = d.find(b'\xfd7zXZ\x00', p)
assert hashlib.sha1(d[off:off+size]).digest() == d[off-20:off], 'factory sha1 mismatch'
open(sys.argv[2], 'wb').write(d[off:off+size])
print('   ', d[0x10:d.index(b'\0', 0x10)].decode(), 'rootfs', size, 'bytes')
EOF
rm -f "$WORK/rootfs"
xz -d -T0 "$WORK/rootfs.xz"

# 3. Edit the ext4 rootfs in place
echo ">> Applying changes"
debugfs -R "cat /root/.ssh/authorized_keys" "$WORK/rootfs" 2>/dev/null > "$WORK/authorized_keys"
[ $KEEPCA = 1 ] && grep cert-authority "$WORK/authorized_keys" > "$WORK/akai_ca" || : > "$WORK/akai_ca"
cat "$WORK/akai_ca" ${PUBKEY:+"$PUBKEY"} > "$WORK/authorized_keys"

PWLOGIN=0
if [ -n "$PASS" ] || [ $NOPASS = 1 ]; then
    PWLOGIN=1
    if [ $NOPASS = 1 ]; then HASH=; else HASH=$(printf '%s\n' "$PASS" | openssl passwd -6 -stdin); fi
    debugfs -R "cat /etc/shadow" "$WORK/rootfs" 2>/dev/null |
        awk -F: -v OFS=: -v h="$HASH" '$1 == "root" { $2 = h } 1' > "$WORK/shadow"
    grep -q "^root:$HASH:" "$WORK/shadow" || { echo "failed to set root password" >&2; exit 1; }
    debugfs -R "cat /etc/ssh/sshd_config.d/10-az0x.conf" "$WORK/rootfs" 2>/dev/null |
        sed -e 's/^PermitRootLogin .*/PermitRootLogin yes/' \
            -e 's/^PasswordAuthentication .*/PasswordAuthentication yes/' > "$WORK/10-az0x.conf"
    [ $NOPASS = 1 ] && echo "PermitEmptyPasswords yes" >> "$WORK/10-az0x.conf"
fi

{
    echo "rm /root/.ssh/authorized_keys"
    echo "write $WORK/authorized_keys /root/.ssh/authorized_keys"
    echo "sif /root/.ssh/authorized_keys mode 0100600"
    echo "sif /root/.ssh/authorized_keys uid 0"
    echo "sif /root/.ssh/authorized_keys gid 0"
    if [ $PWLOGIN = 1 ]; then
        for f in /etc/shadow:0100400 /etc/ssh/sshd_config.d/10-az0x.conf:0100644; do
            echo "rm ${f%:*}"
            echo "write $WORK/$(basename "${f%:*}") ${f%:*}"
            echo "sif ${f%:*} mode ${f#*:}"
            echo "sif ${f%:*} uid 0"
            echo "sif ${f%:*} gid 0"
        done
    fi
    echo "rm /etc/ssh/ssh_host_ed25519_key"
    echo "rm /etc/ssh/ssh_host_ed25519_key.pub"
    echo "symlink /etc/systemd/system/multi-user.target.wants/sshd.service /usr/lib/systemd/system/sshd.service"
    if [ $SDHOOK = 1 ]; then
        echo "rm /usr/bin/az01-launch-MPC"
        echo "write $HERE/fw/az01-launch-MPC /usr/bin/az01-launch-MPC"
        echo "sif /usr/bin/az01-launch-MPC mode 0100755"
        echo "sif /usr/bin/az01-launch-MPC uid 0"
        echo "sif /usr/bin/az01-launch-MPC gid 0"
    fi
} > "$WORK/debugfs.cmds"
debugfs -w -f "$WORK/debugfs.cmds" "$WORK/rootfs" >/dev/null 2>"$WORK/debugfs.log"
if grep -vE '^debugfs [0-9]' "$WORK/debugfs.log" | grep -q .; then
    cat "$WORK/debugfs.log" >&2; exit 1
fi
e2fsck -fn "$WORK/rootfs" >"$WORK/fsck.log" 2>&1 || { cat "$WORK/fsck.log" >&2; exit 1; }

# 4. Recompress (CRC32 check like Akai's own images) and rebuild the container
echo ">> Compressing rootfs"
xz -6 -T0 --check=crc32 -c "$WORK/rootfs" > "$WORK/rootfs.xz"

[ -n "$OUT" ] || OUT=$(dirname "$IMG")/$(basename "$IMG" .img)-root$([ $SDHOOK = 1 ] && echo -sd).img
echo ">> Writing $OUT"
python3 - "$IMG" "$WORK/rootfs.xz" "$OUT" <<'EOF'
import sys, struct, hashlib
src, xzf, out = sys.argv[1:]
d = open(src, 'rb').read()
p = d.find(b'PARTL')
off = d.find(b'\xfd7zXZ\x00', p)
payload = open(xzf, 'rb').read()
hdr = bytearray(d[:off])
hdr[p+8:p+16] = struct.pack('<Q', len(payload))
hdr[off-20:off] = hashlib.sha1(payload).digest()
body = bytes(hdr) + payload
body += b'\0' * (-len(body) % 8) + d[-16:]   # 8-byte align, then Akai's EOF record
open(out, 'wb').write(body)
EOF
rm -f "$WORK/rootfs" "$WORK/rootfs.xz" "$WORK/authorized_keys" "$WORK/akai_ca" "$WORK/shadow" "$WORK/10-az0x.conf" "$WORK/debugfs.cmds" "$WORK/debugfs.log" "$WORK/fsck.log"
echo ">> Done: $OUT ($(du -h "$OUT" | cut -f1))"
