#!/usr/bin/env python3
"""Keep this catalog repo's issues in step with problems.json (from tools/catalog_build.py).

  tools/catalog_issues.py [--problems catalog/dist/problems.json] [--repo owner/name] [--dry-run]

A failing version is already left out of catalog.json, so the previous good version stays the latest. This only makes
the failure visible:
- one issue per failing release (or unreadable plugin), keyed by title, so a problem that persists is reported once;
- none for a release marked "superseded" (a newer release of the same plugin passes: an old tag can't be rebuilt, so
  it is history, not something to fix);
- none for a per-tag title that has a closed issue: closing it is the answer, it is not opened again (a tag can't
  be rebuilt). A tagless "cannot be read" title is different: its repo can go from unreadable to readable and back,
  so it reopens if only closed issues exist for it;
- an open issue whose problem is gone or superseded is closed with a comment, unless its plugin could not be read in
  this build (then nothing is known about its releases); a second open issue with the same title is closed as a
  duplicate.
Risky-call flags (flags.json, also from catalog_build.py: the newest stable version of each plugin) get one issue per plugin
and set of call categories, "Catalog: <id> flagged for review (network, runs programs)". Closing it is the review: it is never
reopened, and a later version with the same categories opens nothing; new categories open a new issue. Open issues in the old
per-version form ("Catalog: <id> <version> flagged for review") are closed.
Needs the `gh` CLI (GITHUB_TOKEN with issues: write in Actions). Standard library only.
"""
import argparse
import json
import re
import subprocess
import sys

TITLE_RE = re.compile(r"^Catalog: (\S+) (?:(\S+) failed validation|cannot be read)$")


def title(p):
    return "Catalog: %s %s failed validation" % (p["id"], p["tag"]) if p.get("tag") else "Catalog: %s cannot be read" % p["id"]


def unread(p):
    """The plugin's repo or releases could not be read: its other issues can't be judged in this build."""
    return p.get("unreadable", False)


def reopenable(t):
    """A tagless title ("... cannot be read") names no fixed release: the repo can go from unreadable to
    readable and back, so the problem can return after its issue is closed. Only an open issue with that
    title then counts as known. A per-tag title is different: a tag can't be rebuilt, so a closed issue
    is the final word and must never reopen."""
    return t.endswith(" cannot be read")


def plan(problems, issues):
    """problems: problems.json; issues: [{number, title, state}] of this repo (open and closed).
    -> (to_open [(title, body)], to_close [(number, comment)])."""
    want = {}
    for p in problems:
        if not p.get("superseded"):
            want.setdefault(title(p), []).append(p["error"])
    known_open = {i["title"] for i in issues if i["state"].upper() == "OPEN"}
    known_closed = {i["title"] for i in issues} - known_open
    blocked = known_open | {t for t in known_closed if not reopenable(t)}
    to_open = [(t, "The nightly catalog build excluded this release.\n\n" + "\n".join("- " + e for e in errs) +
                "\n\nFix the release (or the registry entry). This issue is closed automatically once the release "
                "passes or a newer release of this plugin passes.")
               for t, errs in want.items() if t not in blocked]
    superseded = {title(p) for p in problems if p.get("superseded")}
    skip_ids = {p["id"] for p in problems if unread(p)}
    to_close, seen = [], set()
    for i in sorted((i for i in issues if i["state"].upper() == "OPEN"), key=lambda i: i["number"]):
        m = TITLE_RE.match(i["title"])
        if not m:
            continue
        if i["title"] in seen:
            to_close.append((i["number"], "Duplicate of an older open issue with the same title."))
            continue
        seen.add(i["title"])
        if i["title"] in want or m.group(1) in skip_ids:
            continue
        to_close.append((i["number"], "A newer release of this plugin passes the catalog build, so this one is history."
                         if i["title"] in superseded else "The catalog build no longer reports this problem."))
    return to_open, to_close


OLD_FLAG_RE = re.compile(r"^Catalog: \S+ \S+ flagged for review$")


def flag_title(f):
    cats = sorted({c for r in f["flags"].values() for c in r})
    return "Catalog: %s flagged for review (%s)" % (f["id"], ", ".join(cats))


def close_old_flags(issues):
    """-> [(number, comment)] for open issues in the old per-version form."""
    return [(i["number"], "Flag issues are now one per plugin and set of calls, for its newest stable version; see the new issue if any.")
            for i in issues if i["state"].upper() == "OPEN" and OLD_FLAG_RE.match(i["title"])]


def plan_flags(flagged, issues):
    """flagged: flags.json; issues as in plan(). -> to_open [(title, body)] for flag sets with no issue in any state."""
    known = {i["title"] for i in issues}
    out = {}
    for f in flagged:
        t = flag_title(f)
        if t in known or t in out:
            continue
        lines = ["- `%s`: %s" % (name, "; ".join("%s (%s)" % (c, ", ".join(v)) for c, v in r.items())) for name, r in f["flags"].items()]
        out[t] = ("The catalog's release check found calls a synth or effect normally has no reason to make "
                  "(network, running programs, loading code at runtime, changing the system):\n\n" + "\n".join(lines) +
                  "\n\nThis is a flag, not a rejection: the release stays listed. Look at the source, or ask the author why "
                  "it needs these, then close this issue (or list the categories in the entry's `flags_reviewed`). "
                  "A closed issue is not reopened; a later version with the same calls opens nothing.\n\nVersion checked: " + f["version"])
    return list(out.items())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--problems", default="catalog/dist/problems.json")
    ap.add_argument("--flags", default="catalog/dist/flags.json")
    ap.add_argument("--repo", help="owner/name (default: the current repo)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        with open(a.problems) as f:
            problems = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Cannot read {a.problems}: {e}", file=sys.stderr)
        return 1
    repo = ["--repo", a.repo] if a.repo else []

    def gh(*args):
        return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout

    try:
        listing = json.loads(gh("issue", "list", *repo, "--state", "all", "--search", "Catalog: in:title",
                                "--json", "number,title,state", "--limit", "1000"))
        to_open, to_close = plan(problems, listing)
        try:
            with open(a.flags) as f:
                to_open += plan_flags(json.load(f), listing)
            to_close += close_old_flags(listing)
        except (OSError, json.JSONDecodeError) as e:
            print(f"No flags read from {a.flags}: {e}", file=sys.stderr)
        for t, body in to_open:
            print("open:", t)
            if not a.dry_run:
                gh("issue", "create", *repo, "--title", t, "--body", body)
        for n, comment in to_close:
            print("close: #%d (%s)" % (n, comment))
            if not a.dry_run:
                gh("issue", "close", *repo, str(n), "--comment", comment)
    except FileNotFoundError:
        print("Error: the gh CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error running {' '.join(map(str, e.cmd[:3]))}: {e}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Failed to parse gh output: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
