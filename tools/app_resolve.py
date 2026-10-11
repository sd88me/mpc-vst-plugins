#!/usr/bin/env python3
"""Resolve companion-app downloads from GitHub releases (docs/CATALOG_SPEC.md, "Companion apps").

An app in catalog/apps.json may list `assets`: [{platform, label, pattern}], fnmatch patterns over the asset names of its newest
stable (non-draft, non-prerelease) GitHub release. For each match this writes {platform, label, url, sha256} into `downloads`, and
sets `version` (the tag without a leading v) and `release` (the release page). The sha256 is the asset's GitHub `digest`, else the
line for that file in a SHA256SUMS asset of the same release; an asset with neither is left out and reported.

If the release can't be read (API error, no stable release), the app keeps whatever `downloads` it has in the file, so a bad night
does not blank a card. Writes <out>/apps.json, which catalog_site.py prefers over catalog/apps.json.

  python3 tools/app_resolve.py [--apps catalog/apps.json] [--out catalog/dist]      (GITHUB_TOKEN raises the API rate limit)"""
import argparse
import copy
import fnmatch
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_check
import catalog_build


def newest_stable(releases):
    """The first release GitHub lists that is neither a draft nor a prerelease (GitHub lists newest first), or None."""
    return next((r for r in releases if not r.get("draft") and not r.get("prerelease")), None)


def read_sums(rel, fetch):
    """{asset name: sha256} from a SHA256SUMS asset ('<hash>  <name>' lines, name may start with '*'), or {}."""
    sums = next((a for a in rel.get("assets", []) if a["name"].upper() in ("SHA256SUMS", "SHA256SUMS.TXT")), None)
    out = {}
    if sums:
        for ln in fetch(sums["browser_download_url"]).splitlines():
            m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", ln)
            if m:
                out[m.group(2)] = m.group(1).lower()
    return out


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mpc-vst-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def resolve(doc, gh, fetch=fetch_text):
    """(new doc, problems). `gh` needs list_releases(repo); `fetch(url)` returns a small text file."""
    out, problems = copy.deepcopy(doc), []
    for a in out["apps"]:
        if not a.get("assets"):
            continue
        try:
            rel = newest_stable(gh.list_releases(a["repo"]))
            if rel is None:
                raise RuntimeError("no stable release")
            sums = None
            downloads = []
            for rule in a["assets"]:
                for asset in sorted(rel.get("assets", []), key=lambda x: x["name"]):
                    if not fnmatch.fnmatch(asset["name"], rule["pattern"]):
                        continue
                    digest = str(asset.get("digest") or "")
                    sha = digest[7:].lower() if digest.startswith("sha256:") else None
                    if not sha:
                        if sums is None:
                            sums = read_sums(rel, fetch)
                        sha = sums.get(asset["name"])
                    if not sha:
                        problems.append({"id": a["id"], "error": "no sha256 for %s (no digest, not in SHA256SUMS)" % asset["name"]})
                        continue
                    label = rule["label"]
                    downloads.append({"platform": rule["platform"], "label": label, "url": asset["browser_download_url"], "sha256": sha})
            if not downloads:
                raise RuntimeError("no asset matched the patterns")
            a["downloads"] = downloads
            a["release"] = rel["html_url"]
            a["version"] = rel["tag_name"].lstrip("v")
        except Exception as e:   # keep the pinned downloads; the nightly run reports it
            problems.append({"id": a["id"], "error": "kept pinned downloads: %s" % e})
    return out, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apps", default="catalog/apps.json")
    ap.add_argument("--out", default="catalog/dist")
    a = ap.parse_args()
    doc = json.load(open(a.apps, encoding="utf-8"))
    errors, _ = app_check.check(doc)
    if errors:
        sys.exit("catalog/apps.json is not valid:\n  " + "\n  ".join(errors))
    new, problems = resolve(doc, catalog_build.GitHub(os.environ.get("GITHUB_TOKEN")))
    errors, _ = app_check.check(new)
    if errors:
        sys.exit("resolved apps are not valid:\n  " + "\n  ".join(errors))
    os.makedirs(a.out, exist_ok=True)
    json.dump(new, open(os.path.join(a.out, "apps.json"), "w", encoding="utf-8"), indent=2)
    for p in problems:
        print("problem: %(id)s: %(error)s" % p, file=sys.stderr)
    print("%d apps resolved, %d problems" % (len(new["apps"]), len(problems)))


if __name__ == "__main__":
    main()
