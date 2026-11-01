#!/usr/bin/env python3
"""Plugin dependencies and conflicts: the one place their syntax and version matching live (docs/CATALOG_SPEC.md, "Dependencies").

A dependency is a catalog id with optional version rules: "tr-mpc", "incipience>=1.0.0", "percolator>=2.0.0,<3.0.0", "tr-mpc=same"
(the same version as the plugin that declares it), "tr-mpc=1.2.0". Rules are joined by commas and all must hold. A conflict is a bare
catalog id. Used by release.py and release_addin.py (--depends, --conflicts), catalog_check.py (the manifest) and catalog_build.py
(the registry fallback, and hiding a version whose dependencies the catalog can't satisfy). mpc-store.sh and the desktop app match
versions the same way from the resolved rules catalog_build.py writes. Standard library only.
"""
import re

ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
VER = r"\d+\.\d+\.\d+"
OPS = (">=", "<=", ">", "<", "=")
DEP = re.compile(r"(%s)((?:(?:>=|<=|>|<|=)(?:%s|same))(?:,(?:>=|<=|>|<|=)%s)*)?" % (ID, VER, VER))
CONFLICT = re.compile(ID)


def parse(spec):
    """'percolator>=2.0.0,<3.0.0' -> ('percolator', [('>=', '2.0.0'), ('<', '3.0.0')]); 'tr-mpc=same' -> ('tr-mpc', [('=', 'same')]).
    Raises ValueError for anything else ("same" only alone, after '=')."""
    if not isinstance(spec, str) or not DEP.fullmatch(spec):
        raise ValueError("bad dependency %r: write id, id>=1.0.0, id>=1.0.0,<2.0.0 or id=same" % (spec,))
    m = DEP.fullmatch(spec)
    rules = [] if not m.group(2) else [re.match(r"(>=|<=|>|<|=)(.+)", r).groups() for r in m.group(2).split(",")]
    if any(v == "same" for _, v in rules) and rules != [("=", "same")]:
        raise ValueError("bad dependency %r: 'same' stands alone, as id=same" % spec)
    return m.group(1), rules


def resolve(spec, own_version):
    """Parse and replace 'same' with the declaring plugin's own version: -> (id, [(op, version)])."""
    pid, rules = parse(spec)
    return pid, [(op, own_version if v == "same" else v) for op, v in rules]


def key(v):
    return tuple(int(x) for x in v.split("."))


def satisfies(version, rules):
    """Does version X.Y.Z meet every (op, version) rule?"""
    k = key(version)
    return all({">=": k >= key(v), "<=": k <= key(v), ">": k > key(v), "<": k < key(v), "=": k == key(v)}[op] for op, v in rules)


def text(rules):
    """[('>=', '2.0.0'), ('<', '3.0.0')] -> '>=2.0.0,<3.0.0' ('' for any version)."""
    return ",".join(op + v for op, v in rules)


def check_lists(depends, conflicts, own_id=None):
    """Problems (strings) with a depends / conflicts pair as a manifest or registry entry holds them (None = absent)."""
    p = []
    ids = []
    if depends is not None:
        if not isinstance(depends, list):
            p.append("depends must be a list of dependencies, e.g. [\"tr-mpc=same\"]")
        else:
            for d in depends:
                try:
                    ids.append(parse(d)[0])
                except ValueError as e:
                    p.append(str(e))
    if conflicts is not None:
        if not (isinstance(conflicts, list) and all(isinstance(c, str) and CONFLICT.fullmatch(c) for c in conflicts)):
            p.append("conflicts must be a list of catalog ids")
        else:
            both = sorted(set(ids) & set(conflicts))
            if both:
                p.append("%s is both a dependency and a conflict" % ", ".join(both))
    if own_id and (own_id in ids or own_id in (conflicts if isinstance(conflicts, list) else [])):
        p.append("a plugin can't depend on or conflict with itself")
    if len(ids) != len(set(ids)):
        p.append("each dependency id once: put all its rules in one entry, joined by commas")
    return p
