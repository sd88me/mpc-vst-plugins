"""The user_files part of a plugin manifest: the user's own files (ROMs) a plugin needs but a release cannot carry.

Shared by release.py (writes it) and catalog_check.py (checks it). The desktop installer (desktop/userfiles.go) reads it: per
folder, rules that say what a good file is, so a beginner is told "Virus C: OK" or why a file is wrong before it reaches the
device. docs/CATALOG_SPEC.md describes the fields.
"""
import re

PATH_RE = r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*"
RULE_KEYS = {"label", "ext", "size", "size_min", "size_max", "header", "signature", "versions", "unverified", "note"}
GROUP_KEYS = {"path", "label", "description", "hint", "rules"}


def user_files_problems(groups, user_data):
    """A list of what is wrong with a user_files value (empty when it is fine). Each folder must be inside a user_data folder,
    so the installer keeps the uploaded files when the plugin is upgraded."""
    if not isinstance(groups, list):
        return ["must be a list of folders"]
    out = []
    for i, g in enumerate(groups):
        where = "folder %d" % (i + 1)
        if not isinstance(g, dict):
            out.append("%s is not an object" % where)
            continue
        p = g.get("path", "")
        where = "%r" % p
        if not isinstance(p, str) or not re.fullmatch(PATH_RE, p) or ".." in p.split("/"):
            out.append("bad folder path %s" % where)
        elif not any(p == d or p.startswith(d + "/") for d in user_data):
            out.append("%s is not inside a user_data folder, so an upgrade would delete what the user uploaded" % where)
        for k in g:
            if k not in GROUP_KEYS:
                out.append("%s: unknown field %r" % (where, k))
        if not g.get("label"):
            out.append("%s needs a label" % where)
        rules = g.get("rules")
        if not isinstance(rules, list) or not rules:
            out.append("%s needs at least one rule" % where)
            continue
        for j, r in enumerate(rules):
            rw = "%s rule %d" % (where, j + 1)
            if not isinstance(r, dict):
                out.append("%s is not an object" % rw)
                continue
            for k in r:
                if k not in RULE_KEYS:
                    out.append("%s: unknown field %r" % (rw, k))
            exts = r.get("ext")
            if not r.get("label"):
                out.append("%s needs a label" % rw)
            if not isinstance(exts, list) or not exts or not all(isinstance(e, str) and re.fullmatch(r"\.[A-Za-z0-9]{1,8}", e) for e in exts):
                out.append("%s: ext must be a list like [\".bin\"]" % rw)
            for k in ("size", "size_min", "size_max"):
                if k in r and not (isinstance(r[k], int) and not isinstance(r[k], bool) and r[k] > 0):
                    out.append("%s: %s must be a positive number of bytes" % (rw, k))
            if r.get("size_min", 0) > r.get("size_max", 1 << 62):
                out.append("%s: size_min is above size_max" % rw)
            if "versions" in r and not r.get("signature"):
                out.append("%s: versions need a signature to read them after" % rw)
            for v in r.get("versions", []):
                if not (isinstance(v, dict) and v.get("prefix") and v.get("label")):
                    out.append("%s: each version needs a prefix and a label" % rw)
            if r.get("unverified") and not r.get("note"):
                out.append("%s: an unverified rule needs a note that tells the user what happens next" % rw)
    return out
