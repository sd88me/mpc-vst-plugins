#!/usr/bin/env python3
"""Package a built addin (a library MPC loads through LD_PRELOAD) as one shareable zip with the shared addin installer.

  tools/release_addin.py --dir build/package --version 1.0.0 --repo owner/name --license MIT [--about "one line"] [-o dist]

--dir holds the addin's addin.manifest (plain assignments, docs/ADDINS.md), its .so and the settings and data files the
manifest names. The zip unpacks to <Name>-<version>/ with:
  addin.manifest              the addin's, with ADDIN_VERSION set to --version
  install.sh, uninstall.sh,   the installer from tools/release/addin (installs to /data/mpc-addins/<id> and adds the .so to
  addin-lib.sh                MPC's LD_PRELOAD, keeping everything else in it)
  <the .so, conf and files>   as the manifest names them
  INSTALL.md                  generated instructions
  mpc-plugin.json             the catalog manifest (kind and layout "addin", docs/CATALOG_SPEC.md)
  SHA256SUMS
Standard library only. Check the result with tools/catalog_check.py <zip> --catalog.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from catalog_check import ADDIN_FILE, ADDIN_SCRIPTS, ID, SEMVER, parse_addin_manifest  # noqa: E402


def elf_machine(path):
    d = open(path, "rb").read(20)
    return {40: "armv7", 62: "x86_64", 183: "aarch64", 3: "x86"}.get(int.from_bytes(d[18:20], "little"), "unknown") if d[:4] == b"\x7fELF" else "not-elf"


def max_glibc(path):
    found = re.findall(rb"GLIBC_(\d+(?:\.\d+){1,2})", open(path, "rb").read())
    return max((f.decode() for f in found), key=lambda v: tuple(map(int, v.split(".")))) if found else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="folder with addin.manifest, the .so and the files it names")
    ap.add_argument("--version", required=True)
    ap.add_argument("--repo", help="source repo, owner/name (for the catalog manifest)")
    ap.add_argument("--license", help="SPDX license id (for the catalog manifest)")
    ap.add_argument("--about", default="", help="one-line description")
    ap.add_argument("--requires", default="", help="extra requirements, one line")
    ap.add_argument("-o", "--out", default="dist")
    a = ap.parse_args()

    if not SEMVER.fullmatch(a.version):
        raise SystemExit("--version must be X.Y.Z")
    src = os.path.join(a.dir, "addin.manifest")
    text = open(src).read()
    try:
        am = parse_addin_manifest(text)
    except ValueError as e:
        raise SystemExit(str(e))
    aid, so = am.get("ADDIN_ID", ""), am.get("ADDIN_SO", "")
    if not ID.fullmatch(aid):
        raise SystemExit("ADDIN_ID %r: the catalog needs lowercase letters, digits and hyphens" % aid)
    conf, files = am.get("ADDIN_CONF", ""), am.get("ADDIN_FILES", "").split()
    for f in [so] + ([conf] if conf else []) + files:
        if not ADDIN_FILE.fullmatch(f) or f in ADDIN_SCRIPTS + ("addin.manifest",):
            raise SystemExit("bad file name in addin.manifest: %r" % f)
        if not os.path.isfile(os.path.join(a.dir, f)):
            raise SystemExit("%s is named in addin.manifest but missing from %s" % (f, a.dir))
    if not so.endswith(".so"):
        raise SystemExit("ADDIN_SO must be a .so")
    name = am.get("ADDIN_NAME") or aid

    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    top = "%s-%s" % (slug, a.version)
    stage = tempfile.mkdtemp()
    root = os.path.join(stage, top)
    os.makedirs(root)
    lines = [l for l in text.splitlines() if not l.startswith("ADDIN_VERSION=")]
    open(os.path.join(root, "addin.manifest"), "w", newline="\n").write("\n".join(lines + ["ADDIN_VERSION=" + a.version]) + "\n")
    for f in ADDIN_SCRIPTS:
        shutil.copy2(os.path.join(HERE, "release", "addin", f), os.path.join(root, f))
        os.chmod(os.path.join(root, f), 0o755)
    for f in [so] + ([conf] if conf else []) + files:
        shutil.copy2(os.path.join(a.dir, f), os.path.join(root, f))
        os.chmod(os.path.join(root, f), 0o644)

    done = am.get("ADDIN_DONE", "")
    install_md = """# {name} {ver}

{about}An addin for MPC OS standalone devices: a library MPC loads at its start (through `LD_PRELOAD`), not a plugin on a
track. It is installed to `/data/mpc-addins/{id}/`.

## Requirements

- A first-generation MPC OS standalone device (32-bit ARM: Force, MPC Live / Live II, One, X, Key 61 and Key 37).
- **Root shell access** (SSH) to the device. Stock MPC OS doesn't offer this; you need a modded unit.
{requires}- Installing addins this way is unofficial: back up first, use at your own risk.

## Install

1. Unzip, then copy the whole folder to the device, e.g. `scp -r {top} root@<device-ip>:/tmp/`
2. Run it: `ssh root@<device-ip> sh /tmp/{top}/install.sh`

The installer copies the addin into `/data/mpc-addins/{id}/`, adds `{so}` to the `LD_PRELOAD` list of MPC's service
and **restarts MPC** (save your project first). The list is extended, never replaced: other addins and the
libraries the firmware preloads stay. Where no writable file sets the list (the unit is on the read-only root), one
drop-in shared by every addin sets it, `/etc/systemd/system/<service>.service.d/90-mpc-addins.conf`. Re-run the
installer after a firmware update. `-y` skips the question, `-n` leaves the restart to you.
{conf_md}{done_md}
## Uninstall

`ssh root@<device-ip> sh /data/mpc-addins/{id}/uninstall.sh` takes the addin out of `LD_PRELOAD`, restarts MPC and
deletes its folder.

## Files

See `SHA256SUMS`. Made with [mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins) (`docs/ADDINS.md`).
""".format(name=name, ver=a.version, about=(a.about + "\n\n") if a.about else "", id=aid, top=top, so=so,
           requires=("- %s\n" % a.requires) if a.requires else "",
           conf_md=("\nSettings are in `/data/mpc-addins/%s/%s`; an upgrade keeps your edits.\n" % (aid, conf)) if conf else "",
           done_md=("\n" + done + "\n") if done else "")
    open(os.path.join(root, "INSTALL.md"), "w").write(install_md)

    manifest = {
        "schema": 1, "id": aid, "name": name, "version": a.version, "kind": "addin", "layout": "addin",
        "so": so, "conf": conf or None, "files": files, "user_data": [conf] if conf else [],
        "arch": elf_machine(os.path.join(root, so)), "max_glibc": max_glibc(os.path.join(root, so)),
        "param_compat": int(a.version.split(".")[0]), "about": a.about, "requires": a.requires,
        "source_repo": a.repo, "license": a.license, "cpu": None,
    }
    open(os.path.join(root, "mpc-plugin.json"), "w").write(json.dumps(manifest, indent=2) + "\n")

    names = sorted(os.listdir(root))
    open(os.path.join(root, "SHA256SUMS"), "w").write("".join(
        "%s  %s\n" % (hashlib.sha256(open(os.path.join(root, f), "rb").read()).hexdigest(), f) for f in names))
    os.makedirs(a.out, exist_ok=True)
    zpath = os.path.join(a.out, top + "-mpc-armv7.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(root)):
            p = os.path.join(root, f)
            info = zipfile.ZipInfo(top + "/" + f, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | (0o755 if f in ADDIN_SCRIPTS else 0o644)) << 16
            z.writestr(info, open(p, "rb").read())
    shutil.rmtree(stage)
    print("%s (%d files, %.1f MB)" % (zpath, len(names) + 1, os.path.getsize(zpath) / 1e6))


if __name__ == "__main__":
    main()
