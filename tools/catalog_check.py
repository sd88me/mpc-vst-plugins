#!/usr/bin/env python3
"""Validate a release zip made by tools/release.py against the catalog spec (docs/CATALOG_SPEC.md). Zips of the
old layout (payload/, no "layout" field) are still accepted so the catalog can list earlier releases.

  tools/catalog_check.py dist/Name-1.2.0-mpc-armv7.zip [--catalog] [--json] [--expect-id ID] [--expect-repo O/N]

Errors make the zip unfit for the catalog (exit 1); warnings need a human look. --catalog additionally requires
source_repo and license in the manifest. --json prints the version record the catalog builder stores.
Standard library only.
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_GLIBC = (2, 32)
SEMVER = re.compile(r"\d+\.\d+\.\d+")
ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def check(zpath, catalog=False, expect_id=None, expect_repo=None):
    errors, warnings = [], []
    err, warn = errors.append, warnings.append
    with zipfile.ZipFile(zpath) as z:
        names = [i.filename for i in z.infolist()]
        for n in names:
            if n.startswith("/") or ".." in n.split("/") or "\\" in n:
                err("unsafe path in zip: %r" % n)
        if errors:
            return errors, warnings, None
        tops = {n.split("/")[0] for n in names}
        if len(tops) != 1:
            err("zip must contain exactly one top folder, found %s" % sorted(tops))
            return errors, warnings, None
        top = tops.pop()
        files = {n[len(top) + 1:]: z.read(n) for n in names if not n.endswith("/") and not
                 (z.getinfo(n).external_attr >> 16) & 0o170000 == 0o120000}
        links = [n for n in names if (z.getinfo(n).external_attr >> 16) & 0o170000 == 0o120000]
        for n in links:
            t = z.read(n).decode(errors="replace")
            if t.startswith("/") or not posixpath.normpath(posixpath.join(posixpath.dirname(n), t)).startswith(top + "/"):
                err("symlink %s points outside the package: %s" % (n, t))

    if "mpc-plugin.json" not in files:
        err("missing mpc-plugin.json")
        return errors, warnings, None
    try:
        m = json.loads(files["mpc-plugin.json"])
    except ValueError as e:
        err("mpc-plugin.json is not valid JSON: %s" % e)
        return errors, warnings, None
    # Releases made before the portable layout (no "layout" field) keep validating so the catalog can list their history.
    legacy = m.get("layout") is None
    for need in ("install.sh", "uninstall.sh", "plugin_list.awk", "INSTALL.md", "SHA256SUMS") + (("plugin.xml",) if legacy else ()):
        if need not in files:
            err("missing " + need)
    if legacy and "plugin.xml" not in files:
        return errors, warnings, None
    if not legacy and m.get("layout") != "portable":
        err("unknown layout %r" % m.get("layout"))
        return errors, warnings, None

    if m.get("schema") != 1:
        err("unsupported manifest schema %r" % m.get("schema"))
    for k in ("id", "name", "version", "kind", "uid", "so", "skin", "arch", "param_compat") + (("so_dir",) if legacy else ("folder",)):
        if m.get(k) in (None, ""):
            err("manifest missing " + k)
    if errors:
        return errors, warnings, None
    if not ID.fullmatch(m["id"]):
        err("bad id %r" % m["id"])
    if not SEMVER.fullmatch(m["version"]):
        err("version %r is not X.Y.Z" % m["version"])
    elif m["param_compat"] != int(m["version"].split(".")[0]):
        err("param_compat must equal the major version")
    if m["kind"] not in ("instrument", "effect"):
        err("kind must be instrument or effect")
    if m["arch"] != "armv7":
        err("arch is %s, catalog is armv7 only" % m["arch"])
    if m.get("max_glibc"):
        if tuple(map(int, m["max_glibc"].split("."))) > MAX_GLIBC:
            err("needs GLIBC %s, limit is %d.%d" % (m["max_glibc"], *MAX_GLIBC))
    else:
        warn("max_glibc not recorded")
    if expect_id and m["id"] != expect_id:
        err("manifest id %r != registry id %r" % (m["id"], expect_id))
    if expect_repo and (m.get("source_repo") or "").lower() != expect_repo.lower():
        err("manifest source_repo %r != registry repo %r" % (m.get("source_repo"), expect_repo))
    for k in ("source_repo", "license"):
        if not m.get(k):
            (err if catalog else warn)("manifest has no " + k)
    if m.get("source_repo") and not re.fullmatch(r"[\w.-]+/[\w.-]+", m["source_repo"]):
        err("source_repo must be owner/name")

    # payload
    entry = None
    if legacy:
        so_rel = "payload/vst/" + m["so"]
        if so_rel not in files:
            err("missing " + so_rel)
        elif files[so_rel][:4] != b"\x7fELF":
            err(m["so"] + " is not an ELF file")
        skin = "payload/Synths/%s/" % m["skin"]
        for need in ("version.xml", "Plugin Skins/TUI.json"):
            if skin + need not in files:
                err("skin is missing " + need)
        for e in m.get("extras", []):
            if not any(f == "payload/vst/" + e or f.startswith("payload/vst/" + e + "/") for f in files):
                err("extra %s listed but not in payload" % e)
        entry = files["plugin.xml"].decode(errors="replace")
        attr = dict(re.findall(r'(\w+)="([^"]*)"', entry))
        if attr.get("file") != posixpath.join(m["so_dir"], m["so"]):
            err("plugin.xml file=%r doesn't match so_dir/so" % attr.get("file"))
        if attr.get("uid", "").lower() != str(m["uid"]).lower():
            err("plugin.xml uid %r != manifest uid %r" % (attr.get("uid"), m["uid"]))
        if attr.get("name") != m["name"]:
            err("plugin.xml name doesn't match the manifest")

        # portable layout (optional): one folder with the skin, the same .so, extras and a plugin-meta.xml using %payload-path%
        portable = m.get("portable")
        if portable:
            expect = "portable/" + m["skin"]
            if portable != expect:
                err("portable must be %r, not %r" % (expect, portable))
            else:
                base = portable + "/"
                for need in ("version.xml", "Plugin Skins/TUI.json", "plugin-meta.xml", m["so"]):
                    if base + need not in files:
                        err("portable folder is missing " + need)
                if base + m["so"] in files and so_rel in files and files[base + m["so"]] != files[so_rel]:
                    err("portable %s differs from payload/vst/%s" % (m["so"], m["so"]))
                for e in m.get("extras", []):
                    if not any(f == base + e or f.startswith(base + e + "/") for f in files):
                        err("portable folder is missing extra " + e)
                meta = files.get(base + "plugin-meta.xml", b"").decode(errors="replace").strip()
                want_file = "%%payload-path%%/%s/%s" % (m["skin"], m["so"])
                mattr = dict(re.findall(r'(\w+)="([^"]*)"', meta))
                if meta and mattr.get("file") != want_file:
                    err("plugin-meta.xml file=%r, expected %r" % (mattr.get("file"), want_file))
                norm = lambda x: re.sub(r'(\s)file="[^"]*"', r'\1file=""', x.strip())
                if meta and norm(meta) != norm(entry):
                    err("plugin-meta.xml differs from plugin.xml apart from file=")

    else:
        # the plugin folder: skin, the .so, extras and a plugin-meta.xml using %payload-path%
        expect = "portable/" + m["skin"]
        if m["folder"] != expect:
            err("folder must be %r, not %r" % (expect, m["folder"]))
        else:
            base = m["folder"] + "/"
            for need in ("version.xml", "Plugin Skins/TUI.json", "plugin-meta.xml", m["so"]):
                if base + need not in files:
                    err("plugin folder is missing " + need)
            if files.get(base + m["so"], b"\x7fELF")[:4] != b"\x7fELF":
                err(m["so"] + " is not an ELF file")
            for e in m.get("extras", []):
                if not any(f == base + e or f.startswith(base + e + "/") for f in files):
                    err("extra %s listed but not in the plugin folder" % e)
            entry = files.get(base + "plugin-meta.xml", b"").decode(errors="replace").strip()
            attr = dict(re.findall(r'(\w+)="([^"]*)"', entry))
            want_file = "%%payload-path%%/%s/%s" % (m["skin"], m["so"])
            if entry and attr.get("file") != want_file:
                err("plugin-meta.xml file=%r, expected %r" % (attr.get("file"), want_file))
            if entry and attr.get("uid", "").lower() != str(m["uid"]).lower():
                err("plugin-meta.xml uid %r != manifest uid %r" % (attr.get("uid"), m["uid"]))
            if entry and attr.get("name") != m["name"]:
                err("plugin-meta.xml name doesn't match the manifest")
            for e in m.get("extras", []):
                if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", e) or ".." in e.split("/"):
                    err("bad extra path %r" % e)
            for f, data in files.items():   # MPC draws an image taller than 16384 px wrongly (another user's report, not yet reproduced here)
                if f.startswith(base + "Plugin Skins/") and f.endswith(".png") and data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
                    h = int.from_bytes(data[20:24], "big")
                    if h > 16384:
                        warn("%s is %d px tall; keep skin images under 16384 px (fewer or smaller filmstrip frames)" % (f[len(base):], h))

    for d in m.get("user_data", []):
        if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", d) or ".." in d.split("/"):
            err("bad user_data path %r" % d)
    # checksums: every file listed and matching, nothing unlisted
    listed = {}
    for line in files.get("SHA256SUMS", b"").decode().splitlines():
        h, _, f = line.partition("  ")
        listed[f] = h
    for f, data in files.items():
        if f == "SHA256SUMS":
            continue
        if f not in listed:
            err("not in SHA256SUMS: " + f)
        elif hashlib.sha256(data).hexdigest() != listed[f]:
            err("checksum mismatch: " + f)
    for f in listed:
        if f not in files:
            err("SHA256SUMS lists a missing file: " + f)

    # installer: regenerate from the current template and compare (releases of the old layout were made by older templates)
    sub = {"@NAME@": m["name"], "@SO_NAME@": m["so"], "@SKIN@": m["skin"],
           "@EXTRAS@": " ".join("'%s'" % e for e in m.get("extras", [])), "@VERSION@": m["version"],
           "@UID@": str(m["uid"]), "@LEGACY_SO@": "/sdcard/vst/" + m["so"], "@USER_DATA@": " ".join(m.get("user_data", []))}
    for script in ([] if legacy else ["install.sh", "uninstall.sh"]):
        tpl = os.path.join(HERE, "release", script)
        if os.path.exists(tpl) and script in files:
            text = open(tpl).read()
            for k, v in sub.items():
                text = text.replace(k, v)
            if text.encode() != files[script]:
                warn("%s differs from this repo's current template (older release tool, or modified): review it" % script)
    canon = os.path.join(HERE, "release", "plugin_list.awk")
    if os.path.exists(canon) and "plugin_list.awk" in files and open(canon, "rb").read() != files["plugin_list.awk"]:
        warn("plugin_list.awk differs from this repo's current copy: review it")

    # does the installer understand -n (the caller stops and starts MPC)? An installer that does not restarts MPC by itself, so a batch
    # installer must run it separately (docs/RELEASING.md). Releases of the old layout have no -n.
    defer = (not legacy) and b"DEFER=" in files.get("install.sh", b"")
    record = {
        "version": m["version"], "size": os.path.getsize(zpath), "defer": defer,
        "sha256": hashlib.sha256(open(zpath, "rb").read()).hexdigest(),
        "param_compat": m["param_compat"], "max_glibc": m.get("max_glibc"), "cpu": m.get("cpu"),
        "manifest": m,
    }
    return errors, warnings, record


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip")
    ap.add_argument("--catalog", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--expect-id")
    ap.add_argument("--expect-repo")
    a = ap.parse_args()
    try:
        errors, warnings, record = check(a.zip, a.catalog, a.expect_id, a.expect_repo)
    except zipfile.BadZipFile:
        errors, warnings, record = ["not a valid zip file"], [], None
    for w in warnings:
        print("warning: " + w, file=sys.stderr)
    for e in errors:
        print("error: " + e, file=sys.stderr)
    if a.json and record and not errors:
        print(json.dumps(record, indent=2))
    elif not errors:
        print("OK: %s %s (%d warnings)" % (record["manifest"]["id"], record["version"], len(warnings)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
