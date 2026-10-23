"""Browser test of "Create Synths folder" in the Install to box, with the API stubbed: no device, no Docker, no network.
Needs Playwright for Python and a Chromium (set CHROMIUM=/path/to/chromium if the default is not installed). Run from the repo root:
  python3 tools/desktop/ui_test/ui_drives.py
"""
import json, os, subprocess, time
from playwright.sync_api import sync_playwright
web = subprocess.Popen(["python3", "-m", "http.server", "8812", "--bind", "127.0.0.1", "--directory", "tools/desktop/web"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
internal = {"path": "/sdcard/Synths", "label": "Internal drive", "fs": "ext4", "freeKB": 5000000, "primary": True, "inContent": True}
made = {"path": "/media/MY DRIVE/Synths", "label": "Drive MY DRIVE", "fs": "exfat", "freeKB": 9000000, "inContent": True}
drive = {"path": "/media/MY DRIVE", "label": "Drive MY DRIVE", "fs": "exfat", "freeKB": 9000000, "noExec": False}
state = {"made": False}
posted = []
def dev():
    return {"host": "10.0.0.2", "arch": "armv7l", "fingerprint": "SHA256:x", "synths": "/sdcard/Synths", "installed": [],
            "roots": [internal] + ([made] if state["made"] else []), "drives": [] if state["made"] else [drive]}
def handle(route):
    req = route.request; p = req.url.split("/api/")[1].split("?")[0]
    def ok(o, code=200): route.fulfill(status=code, content_type="application/json", body=json.dumps(o))
    if p == "state": ok({"connected": False, "uploads": []})
    elif p == "connect": ok({"device": dev(), "problems": []})
    elif p == "catalog": ok({"plugins": []})
    elif p == "device": ok({"plugins": [], "roots": dev()["roots"]})
    elif p == "unregistered": ok({"add": [], "remove": [], "skipped": []})
    elif p == "backups": ok({"backups": {"count": 0, "totalKB": 0}, "keepDefault": 10, "keepMin": 1, "keepMax": 1000})
    elif p == "patches": ok({"patches": [], "note": "", "connected": True})
    elif p == "mkroot":
        posted.append(json.loads(req.post_data))
        if state.get("fail"): ok({"error": "could not create: Read-only file system"}, 400)
        else: state["made"] = True; ok({"device": dev(), "problems": []})
    else: ok({"error": "unexpected " + p}, 500)
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or ("/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)); pg = b.new_page(viewport={"width": 1000, "height": 1100})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.route("**/api/**", handle)
        pg.goto("http://127.0.0.1:8812/index.html?t=x"); time.sleep(0.5)
        pg.fill("#host", "10.0.0.2"); pg.fill("#pw", "x"); pg.click("#connect"); time.sleep(0.8)
        check("a drive without Synths is listed under Install to", pg.locator("#where").is_visible() and "MY DRIVE" in pg.locator("#drivelist").inner_text())
        state["fail"] = True; pg.click("#drivelist button"); time.sleep(0.5)
        check("a failure is shown and the button is usable again", "Read-only" in pg.locator("#drivemsg").inner_text() and pg.locator("#drivelist button").is_enabled())
        state["fail"] = False; pg.click("#drivelist button"); time.sleep(0.8)
        check("the drive path was sent", posted[-1] == {"drive": "/media/MY DRIVE"})
        check("the new folder is a choice and selected; the drive is no longer offered", pg.locator("#whereopts input:checked").get_attribute("value") == "/media/MY DRIVE/Synths" and pg.locator("#drives").is_hidden())
        check("no JS errors (the forced 400 aside)", not [e for e in errs if "400" not in e])
        b.close()
finally:
    web.terminate()
print("FAILED" if fails else "ALL PASSED", fails)
