#!/usr/bin/env python3
"""Build a USB stick that runs MPC 3.10 on an MPC Live III (Gen2) that stays on MPC OS 3.9.1.

  python3 build_stick.py --img310 MPC-3.10.0-Gen2-update.img --img391 MPC-3.9.1-Gen2-update.img --out STICK
                         [--ssh-key ~/.ssh/id_ed25519.pub] [--ask]

Both images are Akai's official Gen2 update files, downloaded by you. From the 3.10 image this takes the MPC program
and /usr/share/Akai (the kit, copied to the device on first boot); from the 3.9.1 image it reads the salt the stock
USB-script reader uses to check autorun.check. Nothing Akai-made is in this tool, and the salt is never written
anywhere except into the checksum. Copy everything in STICK to the root of a FAT32 stick. Needs Linux (or WSL) with
`debugfs` (e2fsprogs). --ask shows MPC's confirmation prompt at every boot instead of running hands-free.
"""
import argparse
import hashlib
import json
import lzma
import mmap
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "tools"))
import saltscan  # noqa: E402

FAT_BAD = re.compile(r'[<>:"\\|?*\x00-\x1f]')


def rootfs(img, dst):
    """The rootfs is the third xz stream of a Gen2 update image."""
    with open(img, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        offs, i = [], 0
        while (i := m.find(b"\xfd7zXZ\x00", i)) >= 0:
            offs.append(i); i += 1
        if len(offs) < 3:
            sys.exit(f"{img}: expected three xz streams (recovery, boot, rootfs); is this a Gen2 update image?")
        f.seek(offs[2]); d = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        with open(dst, "wb") as o:
            while not d.eof:
                c = f.read(1 << 20)
                if not c:
                    break
                o.write(d.decompress(c))


def debugfs(cmd, fs):
    r = subprocess.run(["debugfs", "-R", cmd, fs], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"debugfs failed: {r.stderr.strip()}")


def build_kit(img310, kit):
    with tempfile.TemporaryDirectory() as t:
        fs = os.path.join(t, "rootfs.img")
        print("extracting the 3.10 rootfs (about a minute)...")
        rootfs(img310, fs)
        kit.mkdir(parents=True)
        debugfs(f"dump /usr/bin/MPC {kit / 'MPC'}", fs)
        debugfs(f"rdump /usr/share/Akai {kit}", fs)
    data = (kit / "MPC").read_bytes()
    m = re.search(rb"(3\.10\.[0-9.]+ \([0-9a-f]+\))", data)
    if not m:
        sys.exit("the MPC program in that image is not 3.10")
    (kit / "VERSION").write_text(m.group(1).decode() + "\n")
    return m.group(1).decode()


def check_fat(kit):
    bad = []
    for p in kit.rglob("*"):
        if p.is_symlink():
            bad.append(f"symlink: {p.relative_to(kit)}")
        elif FAT_BAD.search(p.name) or p.name.endswith((" ", ".")):
            bad.append(f"name: {p.relative_to(kit)}")
        elif p.is_file() and p.stat().st_size >= 4 << 30:
            bad.append(f"over 4 GB: {p.relative_to(kit)}")
    if bad:
        sys.exit("the kit has files a FAT32 stick cannot hold:\n  " + "\n  ".join(bad[:20]))


def manifest(kit):
    lines = []
    for p in sorted(kit.rglob("*")):
        if p.is_file():
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(kit).as_posix()}")
    return "\n".join(lines) + "\n"


def autorun_check(autorun, files, salt):
    """What the stock reader recomputes: sha256 of autorun.json, open.sh, each listed file in order, then the salt."""
    data = b"".join((autorun / f).read_bytes() for f in ["autorun.json", "open.sh"] + files)
    return hashlib.sha256(data + salt).hexdigest().encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--img310", required=True, help="Akai's MPC 3.10 Gen2 update image")
    ap.add_argument("--img391", required=True, help="Akai's MPC 3.9.1 Gen2 update image (or the MPC program from it)")
    ap.add_argument("--out", required=True, help="new folder; its contents go to the stick's root")
    ap.add_argument("--ssh-key", help="an SSH public key: root SSH for each boot (optional, for developers)")
    ap.add_argument("--ask", action="store_true", help="ask on the MPC screen at every boot (default: hands-free)")
    a = ap.parse_args()
    if not shutil.which("debugfs"):
        sys.exit("needs debugfs (Debian/Ubuntu/WSL: sudo apt install e2fsprogs)")
    out = pathlib.Path(a.out)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"{out} is not empty")
    salt, hits = saltscan.find_salt(a.img391)
    print(f"checksum salt found in {a.img391} ({len(hits)}x)")

    ver = build_kit(a.img310, out / "mpc310-kit")
    check_fat(out / "mpc310-kit")
    autorun, rt = out / "autorun", out / "autorun" / "runtime"
    rt.mkdir(parents=True)
    shutil.copy(HERE / "stick" / "open.sh", autorun / "open.sh")
    shutil.copy(HERE / "stick" / "run.sh", rt / "run.sh")
    (rt / "kit.sha256").write_text(manifest(out / "mpc310-kit"))
    files = ["runtime/run.sh", "runtime/kit.sha256"]
    if a.ssh_key:
        key = pathlib.Path(a.ssh_key).expanduser().read_text().strip()
        if not key.startswith("ssh-"):
            sys.exit(f"{a.ssh_key} does not look like an SSH public key")
        (rt / "authorized_key.pub").write_text(key + "\n")
        shutil.copy(HERE / "stick" / "enable_ssh.sh", rt / "enable_ssh.sh")
        files += ["runtime/enable_ssh.sh", "runtime/authorized_key.pub"]
    (autorun / "autorun.json").write_text(json.dumps({"value0": {"files": files, "scripts": [{
        "path": "open.sh", "askQuestion": a.ask,
        "message": f"MPC {ver.split()[0]}\n\nRun MPC {ver.split()[0]} for this boot (stays on MPC OS 3.9.1)."
                   + ("\nAlso starts SSH." if a.ssh_key else ""),
        "yesButtonText": "Start", "noButtonText": "Cancel"}]}}, indent=2) + "\n")
    (autorun / "autorun.check").write_bytes(autorun_check(autorun, files, salt))
    print(f"stick ready in {out}: MPC {ver}{', SSH' if a.ssh_key else ''}, {'asks' if a.ask else 'hands-free'}")
    print("Copy everything in it to the root of a FAT32 USB stick and leave the stick in the Live III.")


if __name__ == "__main__":
    main()
