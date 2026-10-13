"""Browser test of the MPC OS badge and the per-device warnings in the catalog list and the install dialog, with the API stubbed: no device,
no Docker needed for the app itself, no network. Needs Playwright for Python and a Chromium (set CHROMIUM=/path/to/chromium if the default
is not installed). Run from the repo root:
  python3 tools/desktop/ui_test/ui_os.py
"""
import json, os, subprocess, time
from playwright.sync_api import sync_playwright
web = subprocess.Popen(["python3", "-m", "http.server", "8812", "--bind", "127.0.0.1", "--directory", "tools/desktop/web"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
root = {"path": "/sdcard/Synths", "label": "Internal drive", "fs": "ext4", "freeKB": 9000000, "primary": True, "inContent": True}
def device(libc): return {"host": "10.0.0.2", "arch": "armv7l", "fingerprint": "SHA256:x", "synths": "/sdcard/Synths", "installed": [], "roots": [root], "libc": libc}
def row(id_, name, os_compat, why=None, glibc="2.30", kind="instrument", tested_2x=False):
    return {"id": id_, "name": name, "author": "me", "kind": kind, "summary": "s", "version": "1.0.0", "size": 100000, "sha256": "a" * 64, "url": "https://x/y.zip",
            "skin": "me - VST - " + name, "param_compat": 1, "uid": "1", "user_data": [], "defer": True, "os_compat": os_compat, "os_compat_why": why or [],
            "max_glibc": glibc, "tested_2x": tested_2x, "installed": False, "update": False}
catalog = [row("both", "Both", ["2.x", "3.x"], tested_2x=True), row("untested", "Untested", ["2.x", "3.x"]), row("three", "Three", ["3.x"], ["TUI:tabs[] version 3 (2.15.1 uses 1)"]), row("newlib", "Newlib", ["3.x"], glibc="2.34"),
           row("legacy", "Legacy", None, glibc=""), row("addin1", "Addin One", None, kind="addin")]
catalog[4]["os_compat"] = []
state = {"libc": "2.33"}
def handle(route):
    req = route.request; p = req.url.split("/api/")[1].split("?")[0]
    def ok(o, code=200): route.fulfill(status=code, content_type="application/json", body=json.dumps(o))
    if p == "state": ok({"connected": False, "uploads": []})
    elif p == "connect": ok({"device": device(state["libc"]), "problems": []})
    elif p == "catalog": ok({"plugins": catalog})
    elif p == "device": ok({"plugins": [], "roots": [root]})
    elif p == "unregistered": ok({"add": [], "remove": [], "skipped": []})
    elif p == "backups": ok({"backups": {"count": 0, "totalKB": 0}, "keepDefault": 10, "keepMin": 1, "keepMax": 1000})
    elif p == "plan":
        ids = json.loads(req.post_data or "{}").get("catalog", [])
        ok({"items": [{"title": r["name"], "version": r["version"]} for r in catalog if r["id"] in ids], "restarts": 1, "maybeMore": False})
    else: ok({"error": "unexpected " + p}, 500)
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" " + str(extra)) if extra and not cond else ""))
    if not cond: fails.append(name)
def connect(pg, libc):
    state["libc"] = libc
    pg.goto("http://127.0.0.1:8812/index.html?t=x"); time.sleep(0.4)
    pg.fill("#host", "10.0.0.2"); pg.fill("#pw", "x"); pg.click("#connect")
    pg.wait_for_selector("#cat input[type=checkbox]", timeout=10000)
    pg.click("#kt-all")   # addins have their own tab; All lists every row the checks look at
def li(pg, name): return pg.locator("#cat li", has_text=name).first
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None); pg = b.new_page(viewport={"width": 1000, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/**", handle)
        connect(pg, "2.33")   # looks like MPC OS 2.x
        t = lambda name: li(pg, name).inner_text().lower()
        check("2.x tested badge", "mpc os 2.x tested" in t("Both") and "needs glibc" not in t("Both") and "3.x" not in t("Both"), t("Both"))
        check("no badge on a 2.x-capable plugin without a 2.x test", "mpc os" not in t("Untested"), t("Untested"))
        check("no badge on a 3.x-only plugin (3.x is the standard)", "mpc os 3.x only" not in t("Three") and pg.locator("#cat .tag.warn").count() == 0, t("Three"))
        check("no badge when the catalog does not say, and none on an addin", "mpc os" not in t("Legacy") and "mpc os" not in t("Addin One"), t("Legacy") + t("Addin One"))
        check("a 3.x only plugin on a 2.x device gets a note", "made for mpc os 3.x" in t("Three") and "glibc 2.33" in t("Three"), t("Three"))
        check("no note for a plugin that works on 2.x", "made for mpc os 3.x" not in t("Both") and "will not load" not in t("Both"))
        check("a plugin needing a newer glibc is told it will not load", "needs glibc 2.34 but this device has 2.33" in t("Newlib") and "will not load" in t("Newlib"), t("Newlib"))
        li(pg, "Three").locator("input").check(); pg.click("#go"); pg.wait_for_selector("#dlg[open]", timeout=5000)
        d = pg.locator("#dlgtxt").inner_text()
        check("the dialog carries the note and the button stays Install", "Note: Three is made for MPC OS 3.x" in d and pg.locator("#yes").inner_text().lower() == "install", d)
        pg.keyboard.press("Escape"); li(pg, "Three").locator("input").uncheck()
        li(pg, "Newlib").locator("input").check(); pg.click("#go"); pg.wait_for_selector("#dlg[open]", timeout=5000)
        d = pg.locator("#dlgtxt").inner_text()
        check("a will-not-load warning changes the button to Install anyway", "Warning: Newlib needs glibc 2.34" in d and pg.locator("#yes").inner_text().lower() == "install anyway", d)
        pg.keyboard.press("Escape"); li(pg, "Newlib").locator("input").uncheck()
        li(pg, "Both").locator("input").check(); pg.click("#go"); pg.wait_for_selector("#dlg[open]", timeout=5000)
        d = pg.locator("#dlgtxt").inner_text()
        check("no note in the dialog for a plugin that is fine", "Note:" not in d and "Warning:" not in d, d)
        pg.keyboard.press("Escape")
        connect(pg, "2.39")   # a Force or MPC OS 3.x
        t = lambda name: li(pg, name).inner_text().lower()
        check("on a 3.x device the badge stays, the warnings go", "mpc os 2.x tested" in t("Both") and "made for mpc os 3.x" not in t("Three") and "will not load" not in t("Newlib"), t("Both") + t("Three") + t("Newlib"))
        connect(pg, "")        # glibc not known: never warn about what we cannot know
        t = lambda name: li(pg, name).inner_text().lower()
        check("unknown glibc: no warnings", "made for mpc os 3.x" not in t("Three") and "will not load" not in t("Newlib"), t("Three") + t("Newlib"))
        check("no JS errors", not errs or print(errs))
        b.close()
finally:
    web.terminate()
print("FAILED" if fails else "ALL PASSED", fails)
