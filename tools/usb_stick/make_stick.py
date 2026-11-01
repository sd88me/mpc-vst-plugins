#!/usr/bin/env python3
"""Write a USB stick folder that installs catalog plugins on an MPC/Force with no SSH, using MPC OS's own USB-script prompt.

  python3 tools/usb_stick/make_stick.py --firmware <update.img | MPC executable> --out <folder> [--install plugin-manager-g2,...]
                                         [--ssh-key <path to a .pub file> | --ssh-password <password>]

Copy the folder's contents to the root of a FAT32/exFAT USB stick (hidden files too), insert it, confirm the prompt on the device.
--firmware is the user's own Akai update image (or the usr/bin/MPC from it): its salt is read here and never stored in this repo.
--ssh-key or --ssh-password, advanced and optional, also enable SSH (tools/usb_stick/enable_ssh.sh): --ssh-key persistently
where root is writable, on demand until the next reboot on a verity rootfs; the private key never goes near this tool.
--ssh-password sets root's password and turns password login on instead -- a real reduction in login security, and refused
outright on a verity rootfs (most Gen2 units) since there is nowhere writable to put the password.
Background and limits: docs/USB_STICK.md.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import saltscan  # noqa: E402

PROMPT = ("MPC PLUGIN INSTALLER\n\nThis installs the plugins listed in install.txt "
          "(the plugin manager by default) and restarts MPC.\n\nHave you saved your project?")

# Names an OS or file manager creates on its own, on a drive nobody has put anything on yet: not something a user
# put there, so they don't make a folder count as "not empty" (a freshly formatted Windows drive always has System
# Volume Information; macOS Finder adds its own after browsing a drive).
HOUSEKEEPING_NAMES = {"system volume information", "$recycle.bin", ".trashes", ".spotlight-v100", ".fseventsd",
                      ".ds_store", "thumbs.db"}


def is_housekeeping(name):
    return name.startswith(".") or name.lower() in HOUSEKEEPING_NAMES


def autorun_check(autorun, files, salt):
    """What the stock reader recomputes: sha256 of autorun.json, open.sh, then each listed file in order, then the salt."""
    data = b"".join((autorun / n).read_bytes() for n in ["autorun.json", "open.sh"] + files)
    return hashlib.sha256(data + salt).hexdigest().encode()


def build(out, salt, store, install, ssh_key=None, ssh_password=None):
    if ssh_key and ssh_password:
        raise ValueError("use --ssh-key or --ssh-password, not both")
    out = Path(out)
    if out.exists():
        if not out.is_dir():
            raise FileExistsError(f"{out} already exists and is not a folder")
        if any(not is_housekeeping(p.name) for p in out.iterdir()):
            raise FileExistsError(f"{out} is not empty; pick an empty folder (or an empty, freshly formatted USB stick)")
    autorun = out / "autorun"
    runtime = autorun / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "open.sh", autorun / "open.sh")
    shutil.copyfile(HERE / "run.sh", runtime / "run.sh")
    shutil.copyfile(store, runtime / "mpc-store.sh")
    if ssh_key:
        shutil.copyfile(HERE / "enable_ssh.sh", runtime / "enable_ssh.sh")
        shutil.copyfile(ssh_key, runtime / "authorized_key.pub")
    elif ssh_password:
        shutil.copyfile(HERE / "enable_ssh.sh", runtime / "enable_ssh.sh")
        (runtime / "ssh_password.txt").write_text(ssh_password + "\n")
    files = sorted(str(p.relative_to(autorun)) for p in runtime.rglob("*") if p.is_file())
    manifest = {"value0": {"files": files, "scripts": [{
        "path": "open.sh", "askQuestion": True, "message": PROMPT,
        "yesButtonText": "Install", "noButtonText": "Cancel"}]}}
    (autorun / "autorun.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (autorun / "autorun.check").write_bytes(autorun_check(autorun, files, salt))
    ids = [i for i in (install or ["plugin-manager-g2"])]
    (out / "install.txt").write_text("# one catalog plugin id per line; edit before inserting the stick\n" + "\n".join(ids) + "\n")
    if ssh_key:
        ssh_note = ("\nSSH is also enabled for the public key you gave: persistently if the device's root can be made writable, "
                     "otherwise (a verity rootfs) until the next reboot -- reinsert the stick to redo it.\n")
    elif ssh_password:
        ssh_note = ("\nSSH password login is also turned on (advanced, less secure than a key) -- only on a device whose root "
                     "can be made writable; refused on a verity rootfs (most Gen2 units).\n")
    else:
        ssh_note = ""
    (out / "README-USB.txt").write_text(
        "Copy everything in this folder (hidden files too) to the root of a USB stick, insert it into the MPC/Force, and confirm\n"
        "the prompt. Needs internet on the device. The result is written to mpc-install-result.txt on the stick, and a copy of\n"
        "MPC.settings to MPC.settings.backup. Save your project first: MPC restarts.\n" + ssh_note)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--firmware", required=True, help="the user's Akai update image, or the MPC executable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--install", default="plugin-manager-g2", help="comma-separated catalog ids")
    ap.add_argument("--store", default=str(HERE.parent / "mpc-store.sh"))
    ap.add_argument("--ssh-key", help="a public key file (e.g. ~/.ssh/id_ed25519.pub) to also enable SSH for")
    ap.add_argument("--ssh-password", help="set root's password and enable SSH password login instead of a key (advanced, less secure)")
    a = ap.parse_args(argv)
    try:
        salt, hits = saltscan.find_salt(a.firmware)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    ids = [i.strip() for i in a.install.split(",") if i.strip()]
    try:
        build(a.out, salt, a.store, ids, a.ssh_key, a.ssh_password)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Wrote {a.out} (salt found {len(hits)}x in {a.firmware}). Copy its contents, hidden files included, to the stick's root.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
