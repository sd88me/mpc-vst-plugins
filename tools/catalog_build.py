#!/usr/bin/env python3
"""Build catalog.json from the registry (catalog/plugins/*.json) and the plugins' GitHub releases or tags.

  tools/catalog_build.py [--registry catalog/plugins] [--out catalog/dist] [--cache catalog/.cache]
                         [--yanked catalog/yanked.json] [--keep 10] [--check-registry]

For every registry entry with distribution "release" (the default): list the repo's releases, download the asset
matching asset_pattern, validate it with tools/catalog_check.py (--catalog, id and repo must match the entry), and record
it. A release that fails is left out and reported in <out>/problems.json (the previous good versions stay listed).
Downloads are cached by asset id.

An entry with distribution "build-yourself" (a plugin that must never publish a built zip, because the build embeds
the user's own firmware) has no download: versions are the repo's vX.Y.Z git tags, and each tag must contain the
declared build script. A GitHub release that carries a *-mpc-armv7.zip asset is reported loudly (it would break the
licence position). No zip is fetched or validated.

GITHUB_TOKEN (optional) raises the API rate limit. --check-registry only validates the registry files (for PRs).
Standard library only. See docs/CATALOG.md and docs/CATALOG_SPEC.md.
"""
import argparse
import datetime
import fnmatch
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_check  # noqa: E402

ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
REPO = re.compile(r"[\w.-]+/[\w.-]+")
KINDS = ("instrument", "effect")
DISTRIBUTIONS = ("release", "build-yourself")
BUILD_YOURSELF_FIELDS = ("requires_user_files", "build", "components")
TAG_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
ZIP_PATTERN = "*-mpc-armv7.zip"
# SPDX ids accepted as open source; anything else needs a human decision (edit this list in the PR that adds it).
OPEN_LICENSES = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Apache-2.0", "GPL-2.0-only", "GPL-2.0-or-later",
                 "GPL-3.0-only", "GPL-3.0-or-later", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only",
                 "LGPL-3.0-or-later", "AGPL-3.0-only", "AGPL-3.0-or-later", "MPL-2.0", "Unlicense", "CC0-1.0", "Zlib"}


def check_entry(e, fname=None):
    """Problems with one registry entry (a list of strings)."""
    p = []
    for k in ("id", "name", "author", "repo", "kind", "license", "summary"):
        if not isinstance(e.get(k), str) or not e[k].strip():
            p.append("missing " + k)
    if p:
        return p
    if not ID.fullmatch(e["id"]):
        p.append("bad id %r" % e["id"])
    if fname and os.path.splitext(os.path.basename(fname))[0] != e["id"]:
        p.append("file name must be <id>.json")
    if not REPO.fullmatch(e["repo"]):
        p.append("repo must be owner/name")
    if e["kind"] not in KINDS:
        p.append("kind must be one of %s" % ", ".join(KINDS))
    if e["license"] not in OPEN_LICENSES and e.get("source_available") is not True:
        p.append("license %r is not on the open-source list: set \"source_available\": true if the source is public "
                 "but the license limits use (shown as a badge), see docs/CATALOG.md" % e["license"])
    if "source_available" in e and not isinstance(e["source_available"], bool):
        p.append("source_available must be true or false")
    if "style" in e and not (isinstance(e["style"], str) and ID.fullmatch(e["style"])):
        p.append("style must be a lowercase slug, e.g. sampler, synth, reverb")
    if "tags" in e and not (isinstance(e["tags"], list) and all(isinstance(t, str) and ID.fullmatch(t) for t in e["tags"])):
        p.append("tags must be a list of lowercase slugs")
    dist = e.get("distribution", "release")
    if dist not in DISTRIBUTIONS:
        p.append("distribution must be one of %s" % ", ".join(DISTRIBUTIONS))
    elif dist == "release":
        for k in BUILD_YOURSELF_FIELDS:
            if k in e:
                p.append("%s only applies to distribution \"build-yourself\"" % k)
    else:
        p += check_build_yourself(e)
    return p


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def check_build_yourself(e):
    """Registry rules for a "build-yourself" entry (offline; the tag and script checks need GitHub, see build())."""
    p = []
    if e["license"] not in OPEN_LICENSES:
        p.append("build-yourself needs an open-source SPDX license (source_available is not enough): the source must be "
                 "open even though no built zip is published")
    if e.get("source_available"):
        p.append("source_available cannot be combined with distribution \"build-yourself\"")
    for k in ("asset_pattern",):
        if k in e:
            p.append("%s makes no sense without a release zip" % k)
    files = e.get("requires_user_files")
    if not (isinstance(files, list) and files):
        p.append("requires_user_files must list the user's own files the build needs (non-empty)")
    else:
        for i, f in enumerate(files):
            if not (isinstance(f, dict) and _nonempty_str(f.get("name")) and _nonempty_str(f.get("description"))):
                p.append("requires_user_files[%d] needs a name and a description" % i)
    b = e.get("build")
    if not isinstance(b, dict):
        p.append("build must be an object with command, script, docs_url and needs")
    else:
        for k in ("command", "script", "docs_url"):
            if not _nonempty_str(b.get(k)):
                p.append("build.%s is required" % k)
        s = b.get("script")
        if _nonempty_str(s) and (s.startswith("/") or ".." in s.split("/") or "\\" in s):
            p.append("build.script must be a path inside the repo (no leading /, no ..)")
        if _nonempty_str(s) and _nonempty_str(b.get("command")) and s not in b["command"]:
            p.append("build.command must run build.script (%s)" % s)
        if _nonempty_str(b.get("docs_url")) and not b["docs_url"].startswith("https://"):
            p.append("build.docs_url must be an https:// link (\"{tag}\" in it becomes the shown version's git tag)")
        if "needs" in b and not (isinstance(b["needs"], list) and all(_nonempty_str(n) for n in b["needs"])):
            p.append("build.needs must be a list of strings")
    comps = e.get("components")
    if comps is not None:
        if not (isinstance(comps, list) and comps):
            p.append("components must be a non-empty list when present")
        else:
            seen = set()
            for i, c in enumerate(comps):
                if not (isinstance(c, dict) and isinstance(c.get("id"), str) and ID.fullmatch(c["id"]) and _nonempty_str(c.get("name"))
                        and c.get("kind") in KINDS):
                    p.append("components[%d] needs a slug id, a name and a kind (%s)" % (i, ", ".join(KINDS)))
                    continue
                if c["id"] in seen:
                    p.append("duplicate component id %r" % c["id"])
                seen.add(c["id"])
                if "uid" in c and not (isinstance(c["uid"], str) and re.fullmatch(r"[ -~]{4}", c["uid"])):
                    p.append("components[%d].uid must be the four characters of the uid in vst.json (e.g. MnmO)" % i)
    return p


def load_registry(path):
    entries, problems, ids, repos, comp_ids = [], [], {}, {}, {}
    for f in sorted(glob.glob(os.path.join(path, "*.json"))):
        try:
            e = json.load(open(f))
        except ValueError as ex:
            problems.append((f, "invalid JSON: %s" % ex))
            continue
        errs = check_entry(e, f)
        if not errs:
            if e["id"] in ids:
                errs.append("duplicate id, also in " + ids[e["id"]])
            other = repos.get(e["repo"].lower())   # (id, asset_pattern): a repo may hold several plugins if each names its own asset_pattern
            if other and not (e.get("asset_pattern") and other[1] and e["asset_pattern"] != other[1]):
                errs.append("repo already listed as " + other[0])
            for c in e.get("components", []):   # component ids share the id namespace with entries (its own id is fine)
                if c["id"] != e["id"] and (c["id"] in ids or c["id"] in comp_ids):
                    errs.append("component id %r is already used by %s" % (c["id"], ids.get(c["id"]) and c["id"] or comp_ids[c["id"]]))
            if e["id"] in comp_ids:
                errs.append("id is already a component of " + comp_ids[e["id"]])
        for x in errs:
            problems.append((f, x))
        if not errs:
            ids[e["id"]], repos[e["repo"].lower()] = f, (e["id"], e.get("asset_pattern"))
            for c in e.get("components", []):
                comp_ids[c["id"]] = e["id"]
            entries.append(e)
    return entries, problems


class GitHub:
    """Release listing and asset download over the GitHub API. Tests substitute a fake with the same two methods."""
    def __init__(self, token=None):
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "mpc-vst-catalog"}
        if token:
            self.headers["Authorization"] = "Bearer " + token

    def list_releases(self, repo):
        out, page = [], 1
        while True:
            req = urllib.request.Request("https://api.github.com/repos/%s/releases?per_page=100&page=%d" % (repo, page),
                                         headers=self.headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                chunk = json.load(r)
            out += chunk
            if len(chunk) < 100:
                return out
            page += 1

    def _get(self, url):
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)

    def list_tags(self, repo):
        """[{name, sha}] for the repo's tags (sha = the tagged commit). Raises if the repo can't be read."""
        out, page = [], 1
        while True:
            chunk = self._get("https://api.github.com/repos/%s/tags?per_page=100&page=%d" % (repo, page))
            out += [{"name": t["name"], "sha": t["commit"]["sha"]} for t in chunk]
            if len(chunk) < 100:
                return out
            page += 1

    def tag_date(self, repo, sha):
        """YYYY-MM-DD of a commit."""
        c = self._get("https://api.github.com/repos/%s/commits/%s" % (repo, sha))
        return (c["commit"]["committer"]["date"] or "")[:10]

    def file_exists(self, repo, path, ref):
        try:
            self._get("https://api.github.com/repos/%s/contents/%s?ref=%s" % (repo, urllib.parse.quote(path), urllib.parse.quote(ref)))
            return True
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return False
            raise

    def tested(self, repo):
        """Optional tested.json at the root of the repo's default branch: [{version, device, firmware, date}]."""
        req = urllib.request.Request("https://raw.githubusercontent.com/%s/HEAD/tested.json" % repo,
                                     headers={"User-Agent": "mpc-vst-catalog"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return []
            raise

    def download(self, asset, dest):
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "mpc-vst-catalog"})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest + ".part", "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        os.replace(dest + ".part", dest)


def tag_versions(e, src, yanked, tested, keep, problems):
    """Versions of a build-yourself entry: one per vX.Y.Z git tag that contains the declared build script.
    No download, checksum or size exists for these (nothing is published). Also reports any release zip on the repo."""
    repo, script = e["repo"], e["build"]["script"]
    try:
        tags = src.list_tags(repo)
    except Exception as ex:  # repo missing, private or unreachable
        problems.append({"id": e["id"], "tag": None, "error": "cannot read the repo or its tags (does it exist and is it public?): %s" % ex})
        return []
    try:   # a built zip published on a release would break the licence position: shout, but keep the entry listed
        for rel in src.list_releases(repo):
            if rel.get("draft"):
                continue
            for a in rel.get("assets", []):
                if fnmatch.fnmatch(a["name"], ZIP_PATTERN):
                    problems.append({"id": e["id"], "tag": rel.get("tag_name"), "error":
                                     "LICENCE RISK: release asset %s is published, but a build-yourself plugin embeds the user's own "
                                     "firmware and must never ship a built zip. Delete the asset." % a["name"]})
    except Exception as ex:
        problems.append({"id": e["id"], "tag": None, "error": "cannot check releases for a published zip: %s" % ex})
    semver = [(tuple(int(x) for x in m.groups()), t) for t in tags for m in [TAG_VERSION.fullmatch(t["name"])] if m]
    if not semver:
        problems.append({"id": e["id"], "tag": None, "error": "no vX.Y.Z tag found: tag a release to be listed"})
        return []
    versions = []
    ordered = sorted(semver, key=lambda kt: kt[0], reverse=True)[:keep]
    for i, (key, t) in enumerate(ordered):
        version = ".".join(map(str, key))
        try:
            if not src.file_exists(repo, script, t["name"]):
                # An old tag from before the script existed can never be fixed (tags are not moved), so it is skipped
                # quietly; only the newest tag failing is a problem worth an issue.
                if i == 0:
                    problems.append({"id": e["id"], "tag": t["name"], "error": "build script %s does not exist at this tag" % script})
                continue
            date = src.tag_date(repo, t["sha"])
            has_license = any(src.file_exists(repo, n, t["name"]) for n in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"))
        except Exception as ex:
            problems.append({"id": e["id"], "tag": t["name"], "error": "cannot inspect tag: %s" % ex})
            continue
        versions.append({
            "version": version, "tag": t["name"], "date": date, "channel": "stable", "notes": "",
            "source_url": "https://github.com/%s/tree/%s" % (repo, t["name"]),
            "yanked": "%s@%s" % (e["id"], version) in yanked or "%s@*" % e["id"] in yanked,
            "downloads": 0,
            "warnings": [] if has_license else ["no LICENSE file at the root of this tag"],
            "tested": [{k: x.get(k, "") for k in ("device", "firmware", "date")} for x in tested if str(x["version"]).lstrip("v") == version],
        })
    return versions


def build(entries, src, cache, yanked, keep=10, now=None):
    """-> (catalog dict, problems list [{id, tag, error}])."""
    os.makedirs(cache, exist_ok=True)
    plugins, problems = [], []
    for e in entries:
        versions = []
        build_yourself = e.get("distribution", "release") == "build-yourself"
        releases = []
        if not build_yourself:
            try:
                releases = src.list_releases(e["repo"])
            except Exception as ex:  # a repo we can't read: keep going, report it
                problems.append({"id": e["id"], "tag": None, "error": "cannot list releases: %s" % ex})
        tested = []
        if hasattr(src, "tested"):
            try:
                tested = [t for t in src.tested(e["repo"]) if isinstance(t, dict) and t.get("version") and t.get("device")]
            except Exception as ex:  # optional file: a bad one only costs the badges
                problems.append({"id": e["id"], "tag": None, "error": "tested.json ignored: %s" % ex})
        if build_yourself:
            versions = tag_versions(e, src, yanked, tested, keep, problems)
        for rel in releases:
            if rel.get("draft"):
                continue
            tag = rel.get("tag_name")
            assets = [a for a in rel.get("assets", []) if fnmatch.fnmatch(a["name"], e.get("asset_pattern", "*-mpc-armv7.zip"))]
            if not assets and "asset_pattern" in e:
                continue   # a release of another plugin in a shared repo
            if len(assets) != 1:
                problems.append({"id": e["id"], "tag": tag, "error": "expected one asset matching the pattern, found %d" % len(assets)})
                continue
            asset = assets[0]
            zpath = os.path.join(cache, "%s-%s.zip" % (e["id"], asset["id"]))
            try:
                if not os.path.exists(zpath):
                    src.download(asset, zpath)
                errors, warnings, rec = catalog_check.check(zpath, catalog=True, expect_id=e["id"], expect_repo=e["repo"])
            except Exception as ex:
                problems.append({"id": e["id"], "tag": tag, "error": "download/validate failed: %s" % ex})
                continue
            if errors:
                problems.append({"id": e["id"], "tag": tag, "error": "; ".join(errors)})
                continue
            if any(v["version"] == rec["version"] for v in versions):
                problems.append({"id": e["id"], "tag": tag, "error": "duplicate version %s" % rec["version"]})
                continue
            rec.update({
                "url": asset["browser_download_url"],
                "date": (rel.get("published_at") or "")[:10],
                "channel": "beta" if rel.get("prerelease") else "stable",
                "notes": rel.get("body") or "",
                "yanked": "%s@%s" % (e["id"], rec["version"]) in yanked or "%s@%s" % (e["id"], "*") in yanked,
                "warnings": warnings,
                "downloads": asset.get("download_count", 0),
            })
            rec["tested"] = [{k: t.get(k, "") for k in ("device", "firmware", "date")} for t in tested
                             if str(t["version"]).lstrip("v") == rec["version"]]
            versions.append(rec)
        vkey = lambda v: tuple(int(x) for x in v["version"].split("."))
        versions.sort(key=vkey, reverse=True)
        versions = versions[:keep]
        item = {k: e[k] for k in ("id", "name", "author", "repo", "kind", "license", "summary") }
        for k in ("screenshot", "homepage", "style"):
            if e.get(k):
                item[k] = e[k]
        item["tags"] = e.get("tags", [])
        item["source_available"] = bool(e.get("source_available"))
        item["distribution"] = e.get("distribution", "release")
        if build_yourself:
            for k in BUILD_YOURSELF_FIELDS:
                if k in e:
                    item[k] = json.loads(json.dumps(e[k]))   # a copy: the registry entry stays untouched
            item["build"].setdefault("needs", [])
        item["versions"] = versions
        item["latest"] = next((v["version"] for v in versions if v["channel"] == "stable" and not v["yanked"]), None)
        item["latest_beta"] = next((v["version"] for v in versions if v["channel"] == "beta" and not v["yanked"]), None)
        item["downloads"] = sum(v["downloads"] for v in versions)
        item["updated"] = max((v["date"] for v in versions if not v["yanked"]), default="")
        plugins.append(item)
    plugins.sort(key=lambda p: p["name"].lower())
    catalog = {"schema": 1, "generated": (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "plugins": plugins}
    return catalog, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default="catalog/plugins")
    ap.add_argument("--out", default="catalog/dist")
    ap.add_argument("--cache", default="catalog/.cache")
    ap.add_argument("--yanked", default="catalog/yanked.json")
    ap.add_argument("--keep", type=int, default=10)
    ap.add_argument("--check-registry", action="store_true")
    a = ap.parse_args()
    entries, reg_problems = load_registry(a.registry)
    for f, m in reg_problems:
        print("error: %s: %s" % (f, m), file=sys.stderr)
    if a.check_registry:
        print("%d entries, %d problems" % (len(entries), len(reg_problems)))
        sys.exit(1 if reg_problems else 0)
    yanked = set(json.load(open(a.yanked))) if os.path.exists(a.yanked) else set()
    catalog, problems = build(entries, GitHub(os.environ.get("GITHUB_TOKEN")), a.cache, yanked, a.keep)
    os.makedirs(a.out, exist_ok=True)
    json.dump(catalog, open(os.path.join(a.out, "catalog.json"), "w"), indent=1)
    json.dump(problems, open(os.path.join(a.out, "problems.json"), "w"), indent=1)
    for p in problems:
        print("problem: %(id)s %(tag)s: %(error)s" % p, file=sys.stderr)
    print("%d plugins, %d versions, %d problems" % (len(catalog["plugins"]), sum(len(p["versions"]) for p in catalog["plugins"]), len(problems)))
    sys.exit(1 if reg_problems else 0)


if __name__ == "__main__":
    main()
