"""Browser test of the Level 1 beta section on the stick tab (OS question first), with the API stubbed. Run from the repo root:
  python3 tools/desktop/ui_test/ui_l1.py
"""
import json, subprocess, sys, time, os
from playwright.sync_api import sync_playwright
web = subprocess.Popen(["python3", "-m", "http.server", "8813", "--bind", "127.0.0.1", "--directory", "tools/desktop/web"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
posted = []
def handle(route):
    req = route.request; p = req.url.split("/api/")[1].split("?")[0]
    def ok(o, code=200): route.fulfill(status=code, content_type="application/json", body=json.dumps(o))
    if p == "stick/g2":
        posted.append(json.loads(req.post_data))
        if posted[-1]["Out"].endswith("bad"): ok({"error": "payload.sha256 doesn't match"}, 400)
        else: ok({"out": posted[-1]["Out"], "version": "local file"})
    elif p == "stick/easyinfo": ok({"version": "v1.2.3"})
    elif p == "drives": ok({"drives": [{"label": "E: (removable drive)", "path": "E:\\"}]})
    elif p == "browse": ok({"dir": "C:\\", "parent": "", "entries": []})
    else: ok({}, 200)
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None); pg = b.new_page(viewport={"width": 1000, "height": 900})
        pg.route("**/api/**", handle)
        pg.goto("http://127.0.0.1:8813/index.html?t=x"); time.sleep(0.5)
        check("form hidden until an OS is chosen", not pg.is_visible("#l1-form"))
        pg.check("input[name=l1-os][value=new]")
        check("3.10 hides the writer", not pg.is_visible("#l1-form"))
        check("3.10 points to the plugin manager stick", "3.10" in pg.inner_text("#l1-os-msg") and "plugin manager stick" in pg.inner_text("#l1-os-msg"))
        pg.check("input[name=l1-os][value=unsure]")
        check("not sure hides the writer", not pg.is_visible("#l1-form") and pg.inner_text("#l1-os-msg") != "")
        pg.check("input[name=l1-os][value=old]")
        check("3.9.1 shows the writer and clears the note", pg.is_visible("#l1-form") and pg.inner_text("#l1-os-msg") == "")
        check("lists the mounted drive in the section", "E:" in pg.inner_text("#l1-drives"))
        pg.click("#l1-drives button"); check("a drive button fills the stick field", pg.input_value("#l1-out") == "E:\\")
        pg.fill("#l1-out", "")
        pg.click("#l1-out-browse"); time.sleep(0.3)
        check("the folder dialog offers drives when it can't go above C:", pg.is_visible("#bdlgdrives") and "E:" in pg.inner_text("#bdlgdrives"))
        pg.click("#bdlgcancel")
        pg.click("#l1-build")
        check("asks for a drive first", "Pick an empty" in pg.inner_text("#l1-msg") and not posted)
        pg.fill("#l1-bundle", "/tmp/b.zip"); pg.fill("#l1-out", "/media/usb"); pg.click("#l1-build"); time.sleep(0.5)
        check("posts out and bundle", posted == [{"Out": "/media/usb", "Bundle": "/tmp/b.zip"}])
        check("shows success", "Wrote the Level 1 stick" in pg.inner_text("#l1-msg"))
        pg.fill("#l1-out", "/media/bad"); pg.click("#l1-build"); time.sleep(0.5)
        check("shows the server's refusal", "doesn't match" in pg.inner_text("#l1-msg"))
        b.close()
finally:
    web.terminate()
sys.exit(1 if fails else 0)
