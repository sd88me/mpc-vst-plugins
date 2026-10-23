#!/usr/bin/env python3
"""Make the copy of the catalog site that keeps the OLD address alive after the repo moves to another owner (docs/ORG_MIGRATION.md,
step 2). Old installs of the desktop app and mpc-store.sh read <old site>/catalog.json, catalog.tsv, patches.json and the helper
scripts from the folder next to them; the site's pages are not served from the old address any more.

  tools/catalog_mirror.py --site catalog/dist/site --out <folder> --new-base https://open-mpc.github.io/mpc-vst-plugins/

--site is the output of tools/catalog_site.py. --out is replaced: the data files are copied as they are (catalog.tsv carries the
hashes of the helper scripts, so they must stay together) and every HTML page of the site becomes a redirect to the same page under
--new-base. Nothing is fetched or pushed here; the catalog workflow's `mirror` job commits --out to the repo that hosts the old address.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog_site  # noqa: E402

DATA_FILES = ("catalog.json", "catalog.tsv", "patches.json", "apps.json", "feed.xml", "mpc-store.sh", "sync.sh", "plugin_list.awk")


def mirror(site, out, new_base):
    if not new_base.startswith("https://") or not new_base.endswith("/"):
        raise SystemExit("--new-base must be an https:// folder address ending in /")
    for must in ("catalog.json", "catalog.tsv"):
        if not os.path.isfile(os.path.join(site, must)):
            raise SystemExit("%s is not a built site (no %s)" % (site, must))
    here = os.path.abspath(out)
    if here in (os.path.abspath(site), os.path.abspath(os.sep), os.path.abspath(os.getcwd())) or os.path.exists(os.path.join(here, ".git")):
        raise SystemExit("refusing to replace %s" % out)
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    copied, redirected = [], []
    for name in DATA_FILES:
        src = os.path.join(site, name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(out, name))
            copied.append(name)
    for root, _, files in os.walk(site):
        for f in sorted(files):
            if not f.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(root, f), site).replace(os.sep, "/")
            dest = os.path.join(out, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(catalog_site.redirect_page(new_base + ("" if rel == "index.html" else rel)))
            redirected.append(rel)
    return copied, redirected


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default="catalog/dist/site")
    ap.add_argument("--out", required=True)
    ap.add_argument("--new-base", required=True, help="where the site lives now, e.g. https://open-mpc.github.io/mpc-vst-plugins/")
    a = ap.parse_args()
    copied, redirected = mirror(a.site, a.out, a.new_base)
    print("%s: %d data files copied, %d pages turned into redirects to %s" % (a.out, len(copied), len(redirected), a.new_base))


if __name__ == "__main__":
    main()
