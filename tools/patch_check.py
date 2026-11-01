#!/usr/bin/env python3
"""Validate catalog/patches.json (the device patches the installer app may offer; docs/PATCHES.md).

  tools/patch_check.py [catalog/patches.json] [--online]

Errors exit 1. For a script URL that points into this repository at a pinned commit, the local file at the same path must
hash to the manifest's sha256 (so a script edited without re-pinning the manifest fails); other https URLs are only
checked for shape unless --online downloads them. Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
SHA = re.compile(r"[0-9a-f]{64}")
MD5 = re.compile(r"[0-9a-f]{32}")
OWN = re.compile(r"https://raw\.githubusercontent\.com/open-mpc/mpc-vst-plugins/([0-9a-f]{40})/(.+)")
REQUIRED = ["id", "title", "summary", "author", "license", "docs", "script", "supports", "modifies", "backup", "restarts_mpc", "reversible"]
MAX_SCRIPT = 1 << 20


def check(doc, root=ROOT, online=False):
    errors, warnings = [], []
    if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("patches"), list):
        return ['top level must be {"schema": 1, "patches": [...]}'], warnings
    seen = set()
    for i, p in enumerate(doc["patches"]):
        where = "patch %d" % i
        if not isinstance(p, dict):
            errors.append("%s: not an object" % where)
            continue
        where = "patch %r" % p.get("id", i)
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            errors.append("%s: missing %s" % (where, ", ".join(missing)))
            continue
        if not ID.fullmatch(str(p["id"])):
            errors.append("%s: id must be lowercase words joined by dashes" % where)
        if p["id"] in seen:
            errors.append("%s: duplicate id" % where)
        seen.add(p["id"])
        for k in ("title", "summary", "author", "license", "backup"):
            if not isinstance(p[k], str) or not p[k].strip():
                errors.append("%s: %s must be a non-empty string" % (where, k))
        if str(p["license"]).strip().lower() in ("unspecified", "unknown", "tbd"):
            warnings.append("%s: no licence chosen yet" % where)
        for k in ("restarts_mpc", "reversible"):
            if not isinstance(p[k], bool):
                errors.append("%s: %s must be true or false" % (where, k))
        if p["reversible"] is not True:
            errors.append("%s: a patch without an uninstall is not accepted" % where)
        if not isinstance(p["modifies"], list) or not p["modifies"] or not all(isinstance(x, str) and x.startswith("/") for x in p["modifies"]):
            errors.append("%s: modifies must list absolute device paths" % where)
        sup = p["supports"]
        if not isinstance(sup, dict) or not sup.get("os") or not sup.get("arch"):
            errors.append("%s: supports needs os and arch" % where)
        elif not all(MD5.fullmatch(str(m)) for m in sup.get("mpc_md5", [])):
            errors.append("%s: supports.mpc_md5 must be 32-hex checksums" % where)
        doc_path = str(p["docs"])
        if doc_path.startswith("/") or ".." in doc_path.split("/") or not os.path.isfile(os.path.join(root, doc_path)):
            errors.append("%s: docs %r is not a file in the repository" % (where, doc_path))
        s = p["script"]
        if not isinstance(s, dict) or not isinstance(s.get("url"), str) or not SHA.fullmatch(str(s.get("sha256", ""))):
            errors.append("%s: script needs url and a 64-hex sha256" % where)
            continue
        url = s["url"]
        if not url.startswith("https://"):
            errors.append("%s: script url must be https" % where)
            continue
        m = OWN.fullmatch(url)
        if m:
            path = m.group(2)
            if ".." in path.split("/"):
                errors.append("%s: script path escapes the repository" % where)
                continue
            local = os.path.join(root, path)
            if not os.path.isfile(local):
                errors.append("%s: %s is not in this repository" % (where, path))
            elif hashlib.sha256(open(local, "rb").read()).hexdigest() != s["sha256"]:
                errors.append("%s: sha256 does not match %s (script changed: re-pin the commit and the hash)" % (where, path))
        elif re.search(r"/(main|master|HEAD)/", url):
            errors.append("%s: script url must be pinned to a commit, not a branch" % where)
        else:
            warnings.append("%s: script is not in this repository; its hash is only checked with --online" % where)
        if online and not m:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read(MAX_SCRIPT + 1)
            if len(data) > MAX_SCRIPT:
                errors.append("%s: script is larger than %d bytes" % (where, MAX_SCRIPT))
            elif hashlib.sha256(data).hexdigest() != s["sha256"]:
                errors.append("%s: downloaded script does not match sha256" % where)
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?", default=os.path.join(ROOT, "catalog", "patches.json"))
    ap.add_argument("--online", action="store_true")
    a = ap.parse_args()
    errors, warnings = check(json.load(open(a.manifest)), online=a.online)
    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    print("OK" if not errors else "FAILED", "(%d error(s), %d warning(s))" % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
