#!/usr/bin/env python3
"""Validate a release zip made by tools/release.py (or, for an addin, tools/release_addin.py) against the catalog spec
(docs/CATALOG_SPEC.md). Zips of the old layout (payload/, no "layout" field) are still accepted so the catalog can list earlier releases.

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
sys.path.insert(0, HERE)
import skin_compat  # noqa: E402

MAX_GLIBC_GEN2 = (2, 39)   # aarch64 (Gen2) runs MPC OS 3.x only, which has glibc 2.39, so there is no 2.x ceiling to respect
MAX_GLIBC = (2, 36)   # the newest glibc a catalog plugin may need: MPC OS 3.x and the Force have 2.39, the catalog toolchain (arm32v7/gcc:12) is 2.36.
# Above skin_compat.MAX_GLIBC_2X (2.32, MPC OS 2.x) it is listed as MPC OS 3.x only; it is not rejected.
SEMVER = re.compile(r"\d+\.\d+\.\d+")
ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
ADDIN_KEYS = ("ADDIN_ID", "ADDIN_NAME", "ADDIN_SO", "ADDIN_CONF", "ADDIN_FILES", "ADDIN_DONE", "ADDIN_VERSION")
ADDIN_SCRIPTS = ("install.sh", "uninstall.sh", "addin-lib.sh")
ADDIN_FILE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")


ARCHES = ("armv7", "aarch64")   # armv7 = Gen1 MPC and Force (32-bit); aarch64 = Gen2 MPC (RK3588, 64-bit; docs/GEN2.md)


def arm64(d):
    """Whether the bytes start an ELF file for a Gen2 device: 64-bit (EI_CLASS 2), little-endian, AArch64 (e_machine 183)."""
    return d[:4] == b"\x7fELF" and d[4:6] == b"\x02\x01" and int.from_bytes(d[18:20], "little") == 183


def arch_ok(d, arch):
    return arm64(d) if arch == "aarch64" else arm32(d)


def arm32(d):
    """Whether the bytes start an ELF file for MPC OS: 32-bit (EI_CLASS 1), little-endian (EI_DATA 1), ARM (e_machine 40)."""
    return d[:4] == b"\x7fELF" and d[4:6] == b"\x01\x01" and int.from_bytes(d[18:20], "little") == 40


def max_glibc(path):
    """The newest GLIBC_x.y[.z] symbol version the ELF file needs, as "x.y[.z]", from its version-needs section
    (never from a string search: a library may carry a version name as data without needing it). None if it needs
    none, or the file is not ELF."""
    with open(path, "rb") as f:
        d = f.read()
    if d[:4] != b"\x7fELF":
        return None
    bits64, little = d[4] == 2, d[5] == 1
    u16, u32 = (lambda o: int.from_bytes(d[o:o + 2], "little" if little else "big")), \
        (lambda o: int.from_bytes(d[o:o + 4], "little" if little else "big"))
    if bits64:
        shoff = int.from_bytes(d[40:48], "little" if little else "big")
        shentsize, shnum = u16(58), u16(60)
    else:
        shoff, shentsize, shnum = u32(32), u16(46), u16(48)
    sections = []
    for k in range(shnum):
        o = shoff + k * shentsize
        if bits64:
            sections.append((u32(o + 4), int.from_bytes(d[o + 24:o + 32], "little" if little else "big"),
                             int.from_bytes(d[o + 32:o + 40], "little" if little else "big"), u32(o + 40)))
        else:
            sections.append((u32(o + 4), u32(o + 16), u32(o + 20), u32(o + 24)))
    found = []
    for sh_type, off, size, link in sections:
        if sh_type != 0x6FFFFFFE or link >= len(sections):   # SHT_GNU_verneed, strings in its linked section
            continue
        str_off = sections[link][1]
        o = off
        while o < off + size:
            cnt, aux, nxt = u16(o + 2), u32(o + 8), u32(o + 12)
            a = o + aux
            for _ in range(cnt):
                name_off = str_off + u32(a + 8)
                name = d[name_off:d.index(b"\0", name_off)]
                m = re.fullmatch(rb"GLIBC_(\d+(?:\.\d+){1,2})", name)
                if m:
                    found.append(m[1].decode())
                nxa = u32(a + 12)
                if not nxa:
                    break
                a += nxa
            if not nxt:
                break
            o += nxt
    return max(found, key=lambda v: tuple(map(int, v.split(".")))) if found else None


def parse_addin_manifest(text):
    """addin.manifest -> {key: value}. install.sh sources it as root, so only plain assignments of the known keys are allowed:
    KEY=bare, KEY="text" or KEY='text' (no $, backquote or backslash), comments and blank lines. Raises ValueError."""
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"""([A-Z_]+)=("[^"$`\\]*"|'[^']*'|[A-Za-z0-9._/:,+-]*)(\s+#.*)?\s*""", line)
        if not m or m.group(1) not in ADDIN_KEYS:
            raise ValueError("addin.manifest line %d is not a plain assignment of a known key: %r" % (n, line))
        v = m.group(2)
        out[m.group(1)] = v[1:-1] if v[:1] in ("'", '"') else v
    return out


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
    addin = m.get("layout") == "addin"   # a library MPC preloads (tools/release_addin.py), not a plugin
    needs = (("addin.manifest",) + ADDIN_SCRIPTS if addin else ("install.sh", "uninstall.sh", "plugin_list.awk")) + ("INSTALL.md", "SHA256SUMS")
    for need in needs + (("plugin.xml",) if legacy else ()):
        if need not in files:
            err("missing " + need)
    if legacy and "plugin.xml" not in files:
        return errors, warnings, None
    if not legacy and m.get("layout") not in ("portable", "addin"):
        err("unknown layout %r" % m.get("layout"))
        return errors, warnings, None

    if m.get("schema") != 1:
        err("unsupported manifest schema %r" % m.get("schema"))
    keys = ("id", "name", "version", "kind", "so", "arch", "param_compat")
    for k in keys + (() if addin else ("uid", "skin")) + (("so_dir",) if legacy else () if addin else ("folder",)):
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
    if addin and m["kind"] != "addin":
        err("an addin's kind must be addin")
    elif not addin and m["kind"] not in ("instrument", "effect"):
        err("kind must be instrument or effect")
    if m["arch"] not in ARCHES:
        err("arch is %s, catalog takes %s" % (m["arch"], " or ".join(ARCHES)))
    if addin and m["arch"] != "armv7":
        err("addins are armv7 only for now")
    if m.get("max_glibc"):
        need = tuple(int(x) for x in m["max_glibc"].split(".")[:2])
        limit = MAX_GLIBC_GEN2 if m["arch"] == "aarch64" else MAX_GLIBC
        if need > limit:
            err("needs GLIBC %s, limit is %d.%d (MPC OS 3.x has 2.39)" % (m["max_glibc"], *limit))
        elif need > skin_compat.MAX_GLIBC_2X and m["arch"] == "armv7":
            warn("needs GLIBC %s: listed as MPC OS 3.x only (MPC OS 2.x has about 2.32; build with arm32v7/gcc:11-bullseye to reach it)" % m["max_glibc"])
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
        elif not arm32(files[so_rel]):
            err(m["so"] + " is not a 32-bit ARM library")
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

    elif addin:
        # every file at the top: the installer, addin.manifest, the .so, its settings and data files; nothing else
        try:
            am = parse_addin_manifest(files["addin.manifest"].decode(errors="replace"))
        except ValueError as e:
            err(str(e))
            am = None
        conf, extra = m.get("conf") or "", m.get("files") or []
        own = [m["so"]] + ([conf] if conf else []) + list(extra)
        for f in own:
            if not isinstance(f, str) or not ADDIN_FILE.fullmatch(f) or f in needs:
                err("bad addin file name %r" % f)
            elif f not in files:
                err("missing " + f)
        if files.get(m["so"], b"\x7fELF")[:4] != b"\x7fELF":
            err(m["so"] + " is not an ELF file")
        elif m["so"] in files and not arm32(files[m["so"]]):
            err(m["so"] + " is not a 32-bit ARM library")
        if not m["so"].endswith(".so"):
            err("so must be a .so")
        for f in sorted(set(files) - set(needs) - set(own) - {"mpc-plugin.json"}):
            err("unexpected file %s (an addin package is the installer, addin.manifest, mpc-plugin.json and the files it names)" % f)
        if am is not None:
            want = {"ADDIN_ID": m["id"], "ADDIN_NAME": m["name"], "ADDIN_SO": m["so"], "ADDIN_CONF": conf,
                    "ADDIN_FILES": " ".join(extra), "ADDIN_VERSION": m["version"]}
            for k, v in want.items():
                got = am.get(k, "")
                if k == "ADDIN_NAME" and not got:
                    got = am.get("ADDIN_ID", "")
                if " ".join(got.split()) != v:
                    err("addin.manifest %s=%r but mpc-plugin.json says %r" % (k, got, v))
        if m.get("user_data") not in ([conf] if conf else [], None):
            err("an addin's user_data is its settings file only")

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
            elif base + m["so"] in files and not arch_ok(files[base + m["so"]], m["arch"]):
                err(m["so"] + " is not a %s library (manifest arch %s)" % ("64-bit ARM" if m["arch"] == "aarch64" else "32-bit ARM", m["arch"]))
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
    sub = {"@NAME@": m["name"], "@SO_NAME@": m["so"], "@SKIN@": m.get("skin", ""),
           "@EXTRAS@": " ".join("'%s'" % e for e in m.get("extras", [])), "@VERSION@": m["version"],
           "@UID@": str(m.get("uid", "")), "@LEGACY_SO@": "/sdcard/vst/" + m["so"], "@USER_DATA@": " ".join(m.get("user_data", []))}
    for script in ([] if legacy else list(ADDIN_SCRIPTS) if addin else ["install.sh", "uninstall.sh"]):
        tpl = os.path.join(HERE, "release", "addin" if addin else "", script)
        if os.path.exists(tpl) and script in files:
            text = open(tpl).read()
            for k, v in sub.items():
                text = text.replace(k, v)
            if text.encode() != files[script]:
                warn("%s differs from this repo's current template (older release tool, or modified): review it" % script)
    canon = os.path.join(HERE, "release", "plugin_list.awk")
    if os.path.exists(canon) and "plugin_list.awk" in files and open(canon, "rb").read() != files["plugin_list.awk"]:
        warn("plugin_list.awk differs from this repo's current copy: review it")

    # Which MPC OS generations it works on, from its library and its skin (docs/OS2_SKINS.md). Computed here, never taken on trust: a
    # manifest's os_compat may only narrow it (a developer holding a plugin back), and a claim of 2.x that the check cannot confirm is an error.
    os_gens, os_why = None, []
    if not addin:
        sbase = ("payload/Synths/%s/" % m["skin"]) if legacy else (m["folder"] + "/")
        try:
            tui = json.loads(files["%sPlugin Skins/TUI.json" % sbase]) if "%sPlugin Skins/TUI.json" % sbase in files else None
            qraw = files.get("%sPlugin Skins/Q-Links.json" % sbase)
            qlinks = json.loads(qraw) if qraw else None
        except ValueError:
            tui = qlinks = None
        os_gens, os_why = skin_compat.os_compat(m.get("max_glibc"), tui, qlinks)
        claim = m.get("os_compat")
        if claim is not None:
            if claim not in (["2.x", "3.x"], ["3.x"]):
                err('os_compat must be ["2.x", "3.x"] or ["3.x"], not %r' % (claim,))
            elif "2.x" in claim and "2.x" not in os_gens:
                err("os_compat claims 2.x but the check does not confirm it: " + "; ".join(os_why[:3]))
            else:
                os_gens = [g for g in os_gens if g in claim]

    # does the installer understand -n (the caller stops and starts MPC)? An installer that does not restarts MPC by itself, so a batch
    # installer must run it separately (docs/RELEASING.md). Releases of the old layout have no -n.
    defer = (not legacy) and b"DEFER=" in files.get("install.sh", b"")
    record = {
        "version": m["version"], "size": os.path.getsize(zpath), "defer": defer,
        "sha256": hashlib.sha256(open(zpath, "rb").read()).hexdigest(),
        "param_compat": m["param_compat"], "max_glibc": m.get("max_glibc"), "cpu": m.get("cpu"),
        "manifest": m,
    }
    if os_gens is not None:
        record["os_compat"] = os_gens
        if "2.x" not in os_gens:
            record["os_compat_why"] = os_why[:5]
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
