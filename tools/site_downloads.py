#!/usr/bin/env python3
"""Copy the Install page's downloads into the built site (dl/), checked against their pinned SHA-256.

    tools/site_downloads.py [--list catalog/downloads.json] [--out catalog/dist/site] [--cache DIR]

The page can't download from GitHub Releases itself (no CORS there), but it can read files on its own site, so it writes these
to a USB stick in one step. Each entry has a url and sha256, or a "pin" file in the desktop installer's format (the 3.9.1 stick,
tools/desktop/g2stick-pin.json), so the site and the installer can't drift. A release that isn't there yet (404) is skipped
with a warning and the page falls back to "choose a zip you downloaded"; a checksum mismatch stops the build. --cache reads
and keeps the files in a folder (offline builds and tests). Writes dl/downloads.json, the list of what was published.
Standard library only."""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MAX = 64 << 20
NEED = {"pm-stick": ["autorun/autorun.json", "autorun/autorun.check", "autorun/open.sh", "autorun/runtime/run.sh", "autorun/runtime/payload.sha256", ".mpc-g2-stick"]}  # as g2stick.go (g2StickNeed)


def entries(path):
    out = []
    for e in json.load(open(path))["files"]:
        if "pin" in e:
            pin = json.load(open(os.path.join(ROOT, e["pin"])))
            e = dict(e, url=pin["url"], sha256=pin["sha256"], version=pin["version"], file=pin["url"].rsplit("/", 1)[1])
        if not (e["url"].startswith("https://github.com/") and len(e["sha256"]) == 64 and "/" not in e["file"] and e["file"].endswith(".zip")):
            raise SystemExit("bad downloads entry: %r" % e)
        out.append(e)
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "open-mpc-catalog"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX + 1)
    if len(data) > MAX:
        raise SystemExit("%s is larger than %d bytes" % (url, MAX))
    return data


def build(list_path, out, cache=None, get=fetch):
    dl = os.path.join(out, "dl")
    os.makedirs(dl, exist_ok=True)
    published = {}
    for e in entries(list_path):
        data, cached = None, cache and os.path.join(cache, e["file"])
        if cached and os.path.isfile(cached):
            data = open(cached, "rb").read()
        else:
            try:
                data = get(e["url"])
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    print("warning: %s not released yet, skipped (%s)" % (e["file"], e["url"]), file=sys.stderr)
                    continue
                raise
        got = hashlib.sha256(data).hexdigest()
        if got != e["sha256"]:
            raise SystemExit("%s: sha256 %s, pinned %s" % (e["file"], got, e["sha256"]))
        if cached and not os.path.isfile(cached):
            open(cached, "wb").write(data)
        open(os.path.join(dl, e["file"]), "wb").write(data)
        published[e["id"]] = {"path": "dl/" + e["file"], "sha256": e["sha256"], "version": e["version"], "url": e["url"], "need": NEED.get(e["id"], [])}
    with open(os.path.join(dl, "downloads.json"), "w") as f:
        json.dump(published, f, indent=1, sort_keys=True)
    return published


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default=os.path.join(ROOT, "catalog", "downloads.json"))
    ap.add_argument("--out", default="catalog/dist/site")
    ap.add_argument("--cache")
    a = ap.parse_args()
    for k, v in sorted(build(a.list, a.out, a.cache).items()):
        print("%s -> %s" % (k, v["path"]))
