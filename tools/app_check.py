#!/usr/bin/env python3
"""Validate catalog/apps.json: companion apps (desktop tools that work with a standalone MPC but are not plugins), shown on the
catalog page's Companion apps tab. Each app may list `assets` ({platform, label, pattern}: tools/app_resolve.py fills `downloads`, `version` and `release` from the newest stable release) and/or `downloads` ({platform, label, url, sha256}: pinned to a release asset, the fallback). Usage: app_check.py [apps.json]. Returns (errors, apps) from check()."""
import json
import re
import sys

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PLATFORMS = {"macos", "windows", "linux"}
REQUIRED = ("id", "title", "summary", "author", "license", "repo", "platforms")


def check(doc):
    errors, apps = [], doc.get("apps") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(apps, list):
        return ["apps.json must be an object with schema 1 and an 'apps' list"], []
    seen = set()
    for i, a in enumerate(apps):
        where = "apps[%d]" % i
        for k in REQUIRED:
            if not a.get(k):
                errors.append("%s: missing '%s'" % (where, k))
        if not a.get("release") and not a.get("assets"):
            errors.append("%s: needs 'release' (a release page URL) or 'assets' (rules app_resolve.py reads from the latest release)" % where)
        for j, rule in enumerate(a.get("assets") or []):
            if rule.get("platform") not in a.get("platforms", []) or not rule.get("label") or not rule.get("pattern"):
                errors.append("%s.assets[%d]: needs a platform of the app, a label and a pattern" % (where, j))
        if a.get("id") and not ID_RE.match(a["id"]):
            errors.append("%s: id must be lowercase words joined by hyphens" % where)
        if a.get("id") in seen:
            errors.append("%s: duplicate id %r" % (where, a["id"]))
        seen.add(a.get("id"))
        if not set(a.get("platforms") or []) <= PLATFORMS:
            errors.append("%s: platforms must be from %s" % (where, sorted(PLATFORMS)))
        for k in ("release",):
            if a.get(k) and not str(a[k]).startswith("https://"):
                errors.append("%s: %s must be an https URL" % (where, k))
        for j, dl in enumerate(a.get("downloads") or []):
            w = "%s.downloads[%d]" % (where, j)
            if dl.get("platform") not in a.get("platforms", []):
                errors.append("%s: platform must be one of the app's platforms" % w)
            if not dl.get("label") or not str(dl.get("url", "")).startswith("https://"):
                errors.append("%s: needs a label and an https url" % w)
            if not re.match(r"^[0-9a-f]{64}$", str(dl.get("sha256", ""))):
                errors.append("%s: sha256 must be 64 lowercase hex characters" % w)
        if a.get("repo") and not re.match(r"^[\w.-]+/[\w.-]+$", a["repo"]):
            errors.append("%s: repo must be owner/name" % where)
    return errors, apps


if __name__ == "__main__":
    errs, apps = check(json.load(open(sys.argv[1] if len(sys.argv) > 1 else "catalog/apps.json", encoding="utf-8")))
    print("\n".join(errs) or "OK (%d apps)" % len(apps))
    sys.exit(1 if errs else 0)
