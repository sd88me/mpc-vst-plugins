#!/usr/bin/env python3
"""Generate the static catalog site from catalog.json (tools/catalog_build.py).

  tools/catalog_site.py [--catalog catalog/dist/catalog.json] [--out catalog/dist/site]

Writes feed.xml (Atom), index.html (one self-contained page: the catalog is embedded, filtering and sorting run in the browser),
catalog.json (for installers and other tools) and .nojekyll. Deploy the folder with GitHub Pages.
Guide pages: every catalog/pages/*.md becomes <name>.html (front matter: title, nav, order, summary; Markdown subset in
tools/catalog_md.py) and joins the menu. Standard library only. Templates and CSS: tools/catalog_site/. See docs/CATALOG.md.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
from html import escape as html_escape
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog_md  # noqa: E402


def read(name):
    return open(os.path.join(HERE, "catalog_site", name), encoding="utf-8").read()


def load_pages(pages_dir):
    """[{slug, title, nav, order, summary, body}] for catalog/pages/*.md, in menu order."""
    pages = []
    for f in sorted(glob.glob(os.path.join(pages_dir, "*.md"))):
        meta, src = catalog_md.front_matter(open(f, encoding="utf-8").read())
        name = os.path.splitext(os.path.basename(f))[0]
        pages.append({"slug": name, "title": meta.get("title", name), "nav": meta.get("nav", meta.get("title", name)),
                      "order": int(meta.get("order", 50)), "summary": meta.get("summary", ""), "body": src})
    return sorted(pages, key=lambda p: (p["order"], p["slug"]))


def patch_pages(doc, root):
    """Pages for catalog/patches.json: an overview ('patches') and one guide per patch ('patch-<id>', out of the menu), so the site
    and the installer app describe the same patches from the same manifest. The guide is the patch's own README (its `docs`)."""
    ps = doc["patches"]
    e = lambda x: html_escape(str(x), quote=True)
    cards = []
    pages = []
    for p in ps:
        sup = p["supports"]
        tags = ['<span class="tag">device patch</span>', '<span class="tag">%s</span>' % e(p["license"]),
                '<span class="tag %s">%s</span>' % ("warn" if p["restarts_mpc"] else "ok", "MPC restarts" if p["restarts_mpc"] else "No MPC restart"),
                '<span class="tag ok">Undo built in</span>' if p["reversible"] else '<span class="tag warn">No undo</span>']
        if "UNTESTED" in p["summary"]:
            tags.insert(1, '<span class="tag warn" title="Not yet run on a device by this project">Untested</span>')
        summary = p["summary"].replace("UNTESTED on a device by this project (testers wanted, see issue #150). ", "")
        rows = [("Works on", sup.get("os", "see the guide") + (" (%s)" % sup["arch"] if sup.get("arch") else "")),
                ("Changes", "<br>".join("<code>%s</code>" % e(m) for m in p["modifies"]), True),
                ("Backup", "<code>%s</code>" % e(p["backup"]), True),
                ("Script", '<a href="%s">%s</a>, sha256 <code>%s</code>' % (e(p["script"]["url"]), e(os.path.basename(p["script"]["url"])), e(p["script"]["sha256"])), True)]
        dl = "".join("<dt>%s</dt><dd>%s</dd>" % (r[0], r[1] if len(r) == 3 else e(r[1])) for r in rows)
        fw = '<p class="fw" role="note"><strong>UNTESTED on a device by this project.</strong> Testers wanted (issue #150).</p>' if "UNTESTED" in p["summary"] else ""
        cards.append('<article class="card"><header><div><h2>%s</h2><div class="by">by %s</div></div></header><div class="tags">%s</div><p>%s</p>%s'
                     '<dl class="meta">%s</dl><div class="actions"><a class="btn-l primary" href="patch-%s.html">Read the guide</a></div></article>'
                     % (e(p["title"]), e(p["author"]), "".join(tags), e(summary), fw, dl, e(p["id"])))
        guide = os.path.join(root, p["docs"])
        src = open(guide, encoding="utf-8").read() if os.path.isfile(guide) else "The guide is `%s` in the repository." % p["docs"]
        lines = src.splitlines()
        title = p["title"]
        if lines and lines[0].startswith("# "):
            title, lines = lines[0][2:].replace("`", "").strip(), lines[1:]
        pages.append({"slug": "patch-" + p["id"], "title": title, "nav": p["title"], "order": 99, "summary": p["summary"],
                      "body": "\n".join(lines) + "\n\n[All device patches](patches.html)\n", "hidden": True})
    note = ('<blockquote><p><strong>Not for most people.</strong> A device patch changes the device itself (for example Akai\'s own MPC program), it is not a plugin. '
            'Read the guide first, back up your projects, and use it at your own risk. The installer app only lists these; running one is done by hand over SSH '
            'with the script shown, whose checksum you can verify.</p></blockquote>')
    pages.append({"slug": "patches", "title": "Device patches", "nav": "Device patches", "order": 40,
                  "summary": "Advanced and optional: community patches that change the device itself, listed read-only in the installer app's step 7.",
                  "body": "", "html": note + '<div class="grid">%s</div>' % "".join(cards)})
    return pages


def nav_html(pages, current):
    items = [("index.html", "Catalog", "index")] + [(p["slug"] + ".html", p["nav"], p["slug"]) for p in pages if not p.get("hidden")]
    return "".join('<li><a href="%s"%s>%s</a></li>' % (h, ' aria-current="page"' if k == current else "", html_escape(t)) for h, t, k in items)


def render_page(page, pages):
    """A guide page as full HTML."""
    body = '<h1>%s</h1>\n<p class="lede">%s</p>\n%s' % (html_escape(page["title"]), catalog_md.inline(page["summary"]), page["html"] if "html" in page else catalog_md.render(page["body"]))
    tpl = read("page.template.html")
    for k, v in (("/*NAV*/", nav_html(pages, page["slug"])), ("/*TITLE*/", html_escape(page["title"])),
                 ("/*DESC*/", html_escape(page["summary"], quote=True)), ("/*SITE_CSS*/", read("site.css")), ("/*BODY*/", body)):
        tpl = tpl.replace(k, v)
    return tpl


def render(catalog, pages=(), helper_hashes=None):
    """The catalog page HTML for a catalog dict. The JSON is embedded in a <script type=application/json>, so '<' is escaped."""
    data = json.dumps(catalog, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    store = json.dumps({k: v for k, v in (helper_hashes or {}).items() if isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)})
    tpl = read("index.template.html").replace("/*STORE_JSON*/", store)
    marker = "/*CATALOG_JSON*/"
    if tpl.count(marker) != 1:
        raise SystemExit("template must contain the marker exactly once")
    guides = "".join('<a href="%s.html"><b>%s</b><span>%s</span></a>' % (p["slug"], html_escape(p["nav"]), html_escape(p["summary"])) for p in pages if not p.get("hidden"))
    return tpl.replace("/*GUIDES*/", guides).replace("/*NAV*/", nav_html(list(pages), "index")).replace("/*SITE_CSS*/", read("site.css")).replace(marker, data)


def atom(catalog, base=""):
    """Atom feed of the 50 newest non-yanked releases. `base` is the site URL (feed ids fall back to tag: URIs)."""
    items = []
    for p in catalog["plugins"]:
        for v in p["versions"]:
            if not v["yanked"] and v.get("date"):
                items.append((v["date"], p, v))
    items.sort(key=lambda t: (t[0], t[1]["name"].lower()), reverse=True)
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
           "<title>MPC OS Plugin Catalog: new releases</title>", "<id>tag:mpc-vst-catalog,2026:releases</id>",
           "<updated>%s</updated>" % (items[0][0] + "T00:00:00Z" if items else catalog.get("generated", "1970-01-01T00:00:00Z"))]
    if base:
        out.append('<link rel="self" href="%s"/>' % escape(base.rstrip("/") + "/feed.xml", {'"': "&quot;"}))
    for date, p, v in items[:50]:
        beta = " (beta)" if v["channel"] == "beta" else ""
        out.append("<entry><title>%s %s%s</title><id>tag:mpc-vst-catalog,2026:%s@%s</id><updated>%sT00:00:00Z</updated>"
                   '<link href="%s"/><author><name>%s</name></author><summary>%s</summary></entry>' % (
                       escape(p["name"]), escape(v["version"]), beta, escape(p["id"]), escape(v["version"]), date,
                       escape(v.get("url") or v.get("source_url", ""), {'"': "&quot;"}), escape(p["author"]), escape(p["summary"])))
    out.append("</feed>")
    return "\n".join(out) + "\n"


def _f(x):
    return str(x).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def tsv(catalog, helpers):
    """catalog.tsv for shell clients (tools/mpc-store.sh, BusyBox sh has no JSON): a header, one '#file' line per helper file
    with its sha256, then one 'plugin' line per stable, non-yanked version of every downloadable (distribution 'release') plugin:
    plugin id version latest kind name skin uid param_compat size sha256 url user_data defer os_compat max_glibc size64 sha256_64 url64
    (tab separated, '-' when
    empty; defer is 1 when the zip's installer understands -n, 0 when it restarts MPC by itself; os_compat is "2.x,3.x" or "3.x", the MPC OS
    generations the version works on, '-' when the catalog does not say; max_glibc is the newest glibc it needs; the last three are the
    Gen2 (aarch64) zip's size, sha256 and url, '-' when the version has none, and a Gen2 device picks them). Clients that read fewer
    columns ignore the rest. An addin (kind 'addin') has no skin or uid ('-'): it installs to /data/mpc-addins/<id>."""
    out = ["#mpc-catalog-tsv 1"]
    for name, path in helpers:
        out.append("#file\t%s\t%s" % (name, hashlib.sha256(open(path, "rb").read()).hexdigest()))
    for p in catalog["plugins"]:
        if p.get("distribution") != "release":
            continue
        for v in p.get("versions", []):
            if v.get("yanked") or v.get("channel", "stable") != "stable" or not v.get("url"):
                continue
            m = v["manifest"]
            a64 = (v.get("assets") or {}).get("aarch64") or {}
            row = ["plugin", p["id"], v["version"], "1" if v["version"] == p.get("latest") else "0", p["kind"], p["name"], m.get("skin") or "-",
                   m.get("uid") or "-", v.get("param_compat", 1), v["size"], v["sha256"], v["url"], ",".join(m.get("user_data", [])) or "-",
                   "1" if v.get("defer") else "0", ",".join(v.get("os_compat") or []) or "-", v.get("max_glibc") or "-",
                   a64.get("size", "-"), a64.get("sha256", "-"), a64.get("url", "-")]
            out.append("\t".join(_f(x) for x in row))
    return "\n".join(out) + "\n"


# pages that no longer exist and where their content went (setup.html was merged into build.html on 2026-10-01)
MOVED_PAGES = {"setup.html": "build.html"}


def redirect_page(target):
    t = html_escape(target, quote=True)
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Moved</title>'
            '<meta http-equiv="refresh" content="0; url=%s"><link rel="canonical" href="%s"></head>'
            '<body><p>This page moved to <a href="%s">%s</a>.</p></body></html>\n' % (t, t, t, t))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", default="catalog/dist/catalog.json")
    ap.add_argument("--out", default="catalog/dist/site")
    ap.add_argument("--pages", default="catalog/pages", help="folder of guide pages (Markdown)")
    ap.add_argument("--patches", default="catalog/patches.json", help="device patches the installer app may offer (docs/PATCHES.md); published as patches.json if it exists")
    ap.add_argument("--base-url", default="", help="public site URL, for the feed's self link")
    a = ap.parse_args()
    catalog = json.load(open(a.catalog, encoding="utf-8"))
    if catalog.get("schema") != 1:
        raise SystemExit("unsupported catalog schema %r" % catalog.get("schema"))
    os.makedirs(a.out, exist_ok=True)
    pages = load_pages(a.pages)
    patches_doc = None
    if os.path.isfile(a.patches):   # the installer app reads it from next to catalog.json; a manifest that fails its checks is not published
        import patch_check
        patches_doc = json.load(open(a.patches, encoding="utf-8"))
        errors, _ = patch_check.check(patches_doc)
        if errors:
            raise SystemExit("catalog/patches.json is not valid:\n  " + "\n  ".join(errors))
        pages = sorted(pages + patch_pages(patches_doc, os.path.dirname(HERE)), key=lambda p: (p["order"], p["slug"]))
    helpers = [("mpc-store.sh", os.path.join(HERE, "mpc-store.sh")), ("sync.sh", os.path.join(HERE, "release", "sync.sh")),
               ("plugin_list.awk", os.path.join(HERE, "release", "plugin_list.awk"))]
    hashes = {name: hashlib.sha256(open(path, "rb").read()).hexdigest() for name, path in helpers}
    open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(render(catalog, pages, hashes))
    for pg in pages:
        open(os.path.join(a.out, pg["slug"] + ".html"), "w", encoding="utf-8").write(render_page(pg, pages))
    open(os.path.join(a.out, "feed.xml"), "w", encoding="utf-8").write(atom(catalog, a.base_url))
    shutil.copy(a.catalog, os.path.join(a.out, "catalog.json"))
    if patches_doc is not None:
        shutil.copy(a.patches, os.path.join(a.out, "patches.json"))
    for name, path in helpers:   # the files a device downloads next to catalog.tsv, checked against the hashes listed in it
        shutil.copy(path, os.path.join(a.out, name))
    open(os.path.join(a.out, "catalog.tsv"), "w", encoding="utf-8", newline="\n").write(tsv(catalog, helpers))
    for old, new in MOVED_PAGES.items():   # links to pages that were merged into another still work
        open(os.path.join(a.out, old), "w", encoding="utf-8").write(redirect_page(new))
    open(os.path.join(a.out, ".nojekyll"), "w").close()
    print("%s (%d plugins, %d guide pages)" % (os.path.join(a.out, "index.html"), len(catalog["plugins"]), len([p for p in pages if not p.get("hidden")])))


if __name__ == "__main__":
    main()
