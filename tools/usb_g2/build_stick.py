#!/usr/bin/env python3
"""Write the "Level 1" USB stick: confirm the stock prompt and it installs the OpenMPC Plugin Manager VST and restarts MPC, with no
SSH, no network and no plugin-manager UI to learn. Both generations' packages ride on the stick; the device picks its own.

  python3 tools/usb_g2/build_stick.py --firmware <update.img | MPC executable> --out <folder> (--g2-dir <folder with the two zips> | --download)
                                      [--zip <bundle.zip>]

The stock USB-script check covers autorun.json, open.sh and the files listed in autorun.json (here: runtime/run.sh and
runtime/payload.sha256, which carries the packages' checksums). The packages themselves are NOT listed, so the same boot files serve
every package version, but a package swapped on the stick no longer matches payload.sha256 and is refused on the device.
--firmware is the user's own Akai update image (or the usr/bin/MPC from it): its salt is read here, only to compute autorun.check,
and is never stored. The resulting stick carries that check and nothing else derived from the firmware. Background: docs/USB_STICK.md.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "usb_stick"))
import make_stick  # noqa: E402  (autorun_check, is_housekeeping)
import saltscan  # noqa: E402

PLUGIN_ID = "plugin-manager-g2"
ARCHES = ("armv7", "aarch64")
CATALOG_JSON = "https://sd88me.github.io/mpc-vst-plugins/catalog.json"
PROMPT = ("OPENMPC PLUGIN MANAGER VST\n\nThis installs the OpenMPC Plugin Manager VST and restarts MPC. "
          "It needs no network.\n\nHave you saved your project?")
MARKER = ".mpc-g2-stick"


def zip_name(version, arch):
    return "Plugin-Manager-G2-%s-mpc-%s.zip" % (version, arch)


def check_package(path, version, arch):
    """A package must be the G2 plugin for this CPU and version, and carry its own installer."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        installers = [n for n in names if n.split("/")[-1] == "install.sh" and n.count("/") <= 1]
        manifests = [n for n in names if n.split("/")[-1] == "mpc-plugin.json" and n.count("/") <= 1]
        if len(installers) != 1 or len(manifests) != 1:
            raise ValueError("%s: expected one install.sh and one mpc-plugin.json at the top of the package" % Path(path).name)
        m = json.loads(z.read(manifests[0]))
    if m.get("id") != PLUGIN_ID:
        raise ValueError("%s: this is plugin %r, not %s" % (Path(path).name, m.get("id"), PLUGIN_ID))
    if m.get("version") != version:
        raise ValueError("%s: version %r, expected %s" % (Path(path).name, m.get("version"), version))
    if (m.get("arch") or "armv7") != arch:
        raise ValueError("%s: arch %r, expected %s" % (Path(path).name, m.get("arch"), arch))


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build(out, salt, zips, version):
    """zips: {arch: Path}. Writes the stick folder and returns it."""
    if set(zips) != set(ARCHES):
        raise ValueError("both packages are needed: " + ", ".join(ARCHES))
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)*", version):
        raise ValueError("unusable version %r" % version)
    for arch in ARCHES:
        check_package(zips[arch], version, arch)
    out = Path(out)
    if out.exists():
        if not out.is_dir():
            raise FileExistsError("%s already exists and is not a folder" % out)
        if any(not make_stick.is_housekeeping(p.name) for p in out.iterdir()):
            raise FileExistsError("%s is not empty; pick an empty folder (or an empty, freshly formatted USB stick)" % out)
    autorun = out / "autorun"
    runtime = autorun / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (out / "g2").mkdir(exist_ok=True)
    shutil.copyfile(HERE / "open.sh", autorun / "open.sh")
    shutil.copyfile(HERE / "run.sh", runtime / "run.sh")
    lines = []
    for arch in ARCHES:
        name = zip_name(version, arch)
        shutil.copyfile(zips[arch], out / "g2" / name)
        lines.append("%s  g2/%s\n" % (sha256_of(out / "g2" / name), name))
    (runtime / "payload.sha256").write_text("".join(lines))
    files = sorted(str(p.relative_to(autorun)) for p in runtime.rglob("*") if p.is_file())
    manifest = {"value0": {"files": files, "scripts": [{
        "path": "open.sh", "askQuestion": True, "message": PROMPT,
        "yesButtonText": "Install", "noButtonText": "Cancel"}]}}
    (autorun / "autorun.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (autorun / "autorun.check").write_bytes(make_stick.autorun_check(autorun, files, salt))
    (out / MARKER).write_text("mpc-usb-g2-v1\nversion=%s\n" % version)
    (out / "README-USB.txt").write_text(
        "OpenMPC Plugin Manager VST stick (version %s).\n\n"
        "Copy everything in this folder (hidden files too) to the root of an empty USB stick, insert it into the MPC or Force and\n"
        "confirm the prompt. The plugin manager is installed in the device's own plugin folder and MPC restarts once. Save your project\n"
        "first. It works with MPC OS 3.9.1 and older; MPC OS 3.10 has no USB prompt (use the plugin manager stick there).\n"
        "The result is written to g2-install-result.txt on the stick, and a copy of MPC.settings to MPC.settings.backup.\n" % version)
    return out


def write_zip(folder, dest):
    """A deterministic zip of the folder's contents (sorted, fixed time stamps), the packages stored, not recompressed."""
    folder = Path(folder)
    with zipfile.ZipFile(dest, "w") as z:
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder).as_posix()
            info = zipfile.ZipInfo(rel + ("/" if p.is_dir() else ""), (1980, 1, 1, 0, 0, 0))
            info.external_attr = (0o40755 if p.is_dir() else 0o100644) << 16
            if p.is_dir():
                z.writestr(info, b"")
                continue
            info.compress_type = zipfile.ZIP_STORED if p.suffix == ".zip" else zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    return Path(dest)


def fetch_from_catalog(dest):
    """The catalog's newest plugin-manager-g2 for both CPUs, each checked against the catalog's sha256 and size."""
    with urllib.request.urlopen(CATALOG_JSON, timeout=60) as r:
        catalog = json.load(r)
    entry = next((p for p in catalog["plugins"] if p.get("id") == PLUGIN_ID), None)
    if not entry:
        raise ValueError("%s is not in the catalog" % PLUGIN_ID)
    v = entry["versions"][0]
    assets = {"armv7": {"url": v["url"], "sha256": v["sha256"], "size": v["size"]}, **(v.get("assets") or {})}
    zips = {}
    for arch in ARCHES:
        a = assets.get(arch)
        if not a or not a.get("url"):
            raise ValueError("the catalog has no %s package for %s %s" % (arch, PLUGIN_ID, v["version"]))
        target = Path(dest) / zip_name(v["version"], arch)
        with urllib.request.urlopen(a["url"], timeout=300) as r, open(target, "wb") as f:
            shutil.copyfileobj(r, f)
        if sha256_of(target) != a["sha256"] or (a.get("size") and target.stat().st_size != int(a["size"])):
            raise ValueError("%s does not match the catalog's checksum" % target.name)
        zips[arch] = target
    return v["version"], zips


def zips_in(folder):
    found = {}
    for arch in ARCHES:
        matches = sorted(Path(folder).glob("Plugin-Manager-G2-*-mpc-%s.zip" % arch))
        if len(matches) != 1:
            raise ValueError("expected one %s package in %s, found %d" % (arch, folder, len(matches)))
        found[arch] = matches[0]
    versions = {re.fullmatch(r"Plugin-Manager-G2-(.+)-mpc-(?:armv7|aarch64)\.zip", p.name).group(1) for p in found.values()}
    if len(versions) != 1:
        raise ValueError("the two packages are for different versions: %s" % ", ".join(sorted(versions)))
    return versions.pop(), found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--firmware", required=True, help="the user's Akai update image, or the MPC executable")
    ap.add_argument("--out", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--g2-dir", help="a folder holding Plugin-Manager-G2-<version>-mpc-armv7.zip and -aarch64.zip")
    src.add_argument("--download", action="store_true", help="fetch the catalog's current packages, checked against its checksums")
    ap.add_argument("--zip", help="also write the stick as one deterministic zip")
    a = ap.parse_args(argv)
    try:
        salt, hits = saltscan.find_salt(a.firmware)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    try:
        if a.download:
            with tempfile.TemporaryDirectory() as tmp:
                version, zips = fetch_from_catalog(tmp)
                build(a.out, salt, zips, version)
        else:
            version, zips = zips_in(a.g2_dir)
            build(a.out, salt, zips, version)
    except (ValueError, FileExistsError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    print("Wrote %s (plugin manager %s; salt found %dx in %s). Copy its contents, hidden files included, to the stick's root." % (a.out, version, len(hits), a.firmware))
    if a.zip:
        write_zip(a.out, a.zip)
        print("Zip: %s sha256 %s" % (a.zip, sha256_of(a.zip)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
