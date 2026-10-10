"""Browser test of the "Advanced: device patches" step (step 7), with the API stubbed: no device, no Docker, no network.
Needs Playwright for Python and a Chromium (set CHROMIUM=/path/to/chromium if the default is not installed). Run from the repo root:
  python3 tools/desktop/ui_test/ui_patches.py
"""
import json, os, subprocess, time
from playwright.sync_api import sync_playwright
web = subprocess.Popen(["python3", "-m", "http.server", "8811", "--bind", "127.0.0.1", "--directory", "tools/desktop/web"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
dev = {"host": "10.0.0.2", "arch": "armv7l", "fingerprint": "SHA256:x", "synths": "/sdcard/Synths", "installed": [], "roots": [{"path": "/sdcard/Synths", "label": "Internal drive", "fs": "ext4", "freeKB": 5000000, "primary": True, "inContent": True}]}
base = {"id": "drum-pad-layout", "title": "16-pad drum layout for selected plugins", "summary": "Machinedrum Module, 6W6 and others get MPC's drum layout.", "author": "sd88me", "license": "x",
        "docs": "tools/mpc_patch/README.md", "supports": {"os": "MPC OS 3.9.1.2", "arch": "armv7l"}, "modifies": ["/usr/bin/MPC"], "backup": "/sdcard/MPC-backup", "restarts_mpc": True, "reversible": True}
mode = {"v": "stock"}
calls = []
runs = []
def handle(route):
    req = route.request; p = req.url.split("/api/")[1].split("?")[0]; calls.append(p)
    def ok(o, code=200): route.fulfill(status=code, content_type="application/json", body=json.dumps(o))
    if p == "state": ok({"connected": False, "uploads": []})
    elif p == "connect": ok({"device": dev, "problems": []})
    elif p == "catalog": ok({"plugins": []})
    elif p == "device": ok({"plugins": [], "roots": dev["roots"]})
    elif p == "unregistered": ok({"add": [], "remove": [], "skipped": []})
    elif p == "backups": ok({"backups": {"count": 0, "totalKB": 0}, "keepDefault": 10, "keepMin": 1, "keepMax": 1000})
    elif p == "patch/run":
        body = json.loads(req.post_data); runs.append(body)
        if body["confirm"] not in ("APPLY", "UNDO"): ok({"error": "type the word"}, 400)
        else: mode["v"] = "patched" if body["action"] == "install" else "stock"; ok({"job": "j1"})
    elif p == "job": ok({"state": "done", "lines": ["Applying: x", "  done"], "next": 2, "result": "Done."})
    elif p == "patches":
        m = mode["v"]
        if m == "none": ok({"patches": [], "note": "No device patches are published yet.", "connected": True})
        elif m == "fail": ok({"error": "cannot read the patch list: HTTP 500"}, 502)
        else: ok({"patches": [dict(base, state=m, supported=m != "unsupported", hasBackup=m == "patched", detail="checksum x" if m == "error" else "")], "note": "", "connected": True})
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
        pg.goto("http://127.0.0.1:8811/index.html?t=x"); time.sleep(0.5)
        check("step 7 exists, collapsed", pg.locator("#d7").count() == 1 and not pg.locator("#d7").evaluate("e => e.open"))
        check("looks disabled before connecting", "off" in pg.locator("#s7").get_attribute("class"))
        pg.locator("#d7 summary").click(); time.sleep(0.3)
        check("opening before connecting asks the device nothing", "patches" not in calls)
        check("hint before connecting", "Connect" in pg.locator("#patchinfo").inner_text())
        pg.fill("#host", "10.0.0.2"); pg.fill("#pw", "x"); pg.click("#connect"); time.sleep(0.8)
        check("connecting alone does not ask for patch states", "patches" not in calls)
        check("check button enabled after connecting", pg.locator("#patchcheck").is_enabled())
        for st, label in [("stock", "Not applied"), ("patched", "Applied"), ("old-patch", "Older version applied"), ("unsupported", "not supported"), ("error", "Could not check")]:
            mode["v"] = st; pg.click("#patchcheck"); time.sleep(0.5)
            t = pg.locator("#patchlist").inner_text(); tl = t.lower()
            check("state %s: the backup folder is shown as a path, never as true" % st, "a backup goes to /sdcard/MPC-backup" in t)
            check("state %s shows %r" % (st, label), label.lower() in tl and "16-pad drum layout" in t and "/usr/bin/MPC" in t and "MPC restarts" in t)
        for st, want in [("stock", ["Apply…"]), ("patched", ["Undo…"]), ("old-patch", ["Apply…", "Undo…"]), ("unsupported", []), ("error", [])]:
            mode["v"] = st; pg.click("#patchcheck"); time.sleep(0.5)
            got = [b.text_content() for b in pg.locator("#patchlist button").all()]
            check("state %s offers %s" % (st, want), got == want)
        mode["v"] = "stock"; pg.click("#patchcheck"); time.sleep(0.5)
        pg.click("#patchlist button:has-text('Apply')")
        check("a confirmation with the warning appears; nothing ran", pg.locator(".pconfirm").is_visible() and "/usr/bin/MPC" in pg.locator(".pconfirm").inner_text() and not runs)
        check("the button waits for the word", pg.locator(".pconfirm .primary").is_disabled())
        pg.fill(".pconfirm input", "apply"); check("a wrong word keeps it disabled", pg.locator(".pconfirm .primary").is_disabled())
        pg.click(".pconfirm button:has-text('Cancel')"); check("cancel removes it, nothing ran", pg.locator(".pconfirm").count() == 0 and not runs)
        pg.click("#patchlist button:has-text('Apply')"); pg.fill(".pconfirm input", "APPLY"); pg.click(".pconfirm .primary"); pg.wait_for_timeout(1500)
        check("apply sent with the word", runs == [{"id": "drum-pad-layout", "action": "install", "confirm": "APPLY"}])
        check("the log and result show, and the row is re-read as applied", "Applying" in pg.locator("#patchlog").text_content() and "Applied" in pg.locator("#patchres").text_content() and "Applied" in pg.locator("#patchlist .tag").text_content())
        pg.click("#patchlist button:has-text('Undo')"); pg.fill(".pconfirm input", "UNDO"); pg.click(".pconfirm .primary"); pg.wait_for_timeout(1500)
        check("undo sent and the row is back to not applied", runs[-1]["action"] == "uninstall" and "Not applied" in pg.locator("#patchlist .tag").text_content())
        check("guide link goes to the repo", (pg.locator("#patchlist a").get_attribute("href") or "").endswith("/blob/main/tools/mpc_patch/README.md"))
        mode["v"] = "none"; pg.click("#patchcheck"); time.sleep(0.5)
        check("nothing published", "No device patches are published yet" in pg.locator("#patchinfo").inner_text() and pg.locator("#patchlist li").count() == 0)
        mode["v"] = "fail"; pg.click("#patchcheck"); time.sleep(0.5)
        check("a failed fetch shows the error", "HTTP 500" in pg.locator("#patchinfo").inner_text())
        mode["v"] = "stock"; pg.click("#patchcheck"); time.sleep(0.5)
        errs = [e for e in errs if "502" not in e]; check("no JS errors (the forced 502 aside)", not errs or print(errs))
        b.close()
finally:
    web.terminate()
print("FAILED" if fails else "ALL PASSED", fails)
