import json, os, re, subprocess, sys, time
from playwright.sync_api import sync_playwright
# Addins in the page: a catalog with one plugin and one addin (listed, not downloaded: it is not https), the addin's release zip dropped
# in (/out/Test-addin-1.0.0-mpc-armv7.zip, from tools/release_addin.py), installed through the real addin installer, then removed in step 4.
UNIT = "/usr/lib/systemd/system/acvs.service"
os.makedirs(os.path.dirname(UNIT), exist_ok=True)
open(UNIT, "w").write("[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\nExecStart=/usr/bin/MPC\n")
open("/tmp/systemctl.log", "w").close()
rel = lambda v, sha, skin=None: {"version": v, "size": 1000, "sha256": sha, "url": "https://example.com/x.zip", "channel": "stable", "yanked": False,
                                  "defer": True, "param_compat": 1, "manifest": {"skin": skin} if skin else {}}
cat = {"schema": 1, "plugins": [
    {"id": "acid", "name": "Acid", "author": "sd88me", "kind": "instrument", "summary": "A synth", "distribution": "release", "latest": "1.0.0",
     "versions": [rel("1.0.0", "%064x" % 1, "sd88me - VST - Acid")]},
    {"id": "test-addin", "name": "Test addin", "author": "acme", "kind": "addin", "summary": "Loaded with MPC", "distribution": "release",
     "latest": "1.0.0", "versions": [rel("1.0.0", "%064x" % 2)]}]}
os.makedirs("/tmp/addcat", exist_ok=True)
json.dump(cat, open("/tmp/addcat/catalog.json", "w"))
web = subprocess.Popen(["python3", "-m", "http.server", "8801", "--bind", "127.0.0.1", "--directory", "/tmp/addcat"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
log = open("/out/app-addins.log", "w")
app = subprocess.Popen(["/out/mpc-installer", "--no-browser", "--port", "8771", "--catalog", "http://127.0.0.1:8801/catalog.json"], stdout=log, stderr=subprocess.STDOUT)
time.sleep(1.5)
link = re.search(r"http://127\.0\.0\.1:8771/\?t=\w+", open("/out/app-addins.log").read()).group(0)
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" " + str(extra)) if extra and not cond else ""))
    if not cond: fails.append(name)
DIR = "/data/mpc-addins/test-addin"
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(bypass_csp=True, viewport={"width": 1000, "height": 1300}).new_page()
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(link)
        pg.fill("#host", "127.0.0.1"); pg.fill("#pw", "secret"); pg.click("#connect")
        pg.wait_for_selector("#cat input[type=checkbox]", timeout=30000)
        row = pg.locator("#cat li", has_text="Test addin").first
        check("the addin is in the catalog list", row.count() == 1)
        check("the kind filter offers Addins", "Addins" in pg.locator("#f-kind").text_content())
        pg.set_input_files("#file", "/out/Test-addin-1.0.0-mpc-armv7.zip")
        pg.wait_for_selector("#ups li", timeout=20000)
        check("the dropped addin zip is accepted", "Test addin" in pg.locator("#ups").text_content(), pg.locator("#upmsg").text_content())
        pg.click("#go"); pg.wait_for_selector("#dlg[open]")
        check("one restart", "MPC will restart once." in pg.locator("#dlgtxt").text_content(), pg.locator("#dlgtxt").text_content())
        pg.click("#yes")
        pg.wait_for_function("document.getElementById('result').className.indexOf('ok') >= 0 || document.getElementById('result').className.indexOf('err') >= 0", timeout=60000)
        res = pg.locator("#result").text_content(); print("RESULT:", res); print(pg.locator("#log").text_content())
        check("install finished OK", "Done" in res, res)
        check("the addin's folder is in /data/mpc-addins", all(os.path.exists(DIR + "/" + f) for f in ("libtest.so", "uninstall.sh", "addin.manifest")))
        unit = open(UNIT).read()
        check("LD_PRELOAD keeps the list and gains the addin", "LD_PRELOAD=/usr/lib/x.so:" + DIR + "/libtest.so" in unit, unit)
        calls = [c.strip() for c in open("/tmp/systemctl.log").read().split("\n") if c.strip()]
        check("MPC stopped once and started once, no restart from the addin", calls.count("stop acvs") == 1 and calls.count("start acvs") == 1 and not [c for c in calls if c.startswith("restart")], calls)
        pg.wait_for_function("document.querySelector('#cat').textContent.indexOf('on the device') >= 0", timeout=20000)
        check("the catalog row now says it is on the device", "on the device" in pg.locator("#cat li", has_text="Test addin").first.text_content())
        pg.click("#d4 > summary")
        pg.wait_for_selector("#dev li input", timeout=20000)
        dev = pg.locator("#dev").text_content()
        check("step 4 lists the addin under Addins, with its version", "Addins · /data/mpc-addins" in dev and "Test addin" in dev and "v1.0.0" in dev, dev)
        pg.locator("#s4").screenshot(path="/out/ui-addins-s4.png")
        pg.locator("#dev li", has_text="Test addin").locator("input").check()
        pg.click("#rm"); pg.wait_for_selector("#dlg[open]")
        dt = pg.locator("#dlgtxt").text_content(); print("dialog:", dt)
        check("the dialog says what removing an addin does", "start-up list" in dt and "plugin list are deleted" not in dt, dt)
        pg.click("#yes")
        pg.wait_for_function("document.getElementById('rmresult').className.indexOf('ok') >= 0 || document.getElementById('rmresult').className.indexOf('err') >= 0", timeout=60000)
        print(pg.locator("#rmlog").text_content())
        check("removal finished OK", "Done" in pg.locator("#rmresult").text_content(), pg.locator("#rmresult").text_content())
        check("the folder is gone", not os.path.exists(DIR))
        check("the unit is back to its list", "LD_PRELOAD=/usr/lib/x.so\n" in open(UNIT).read(), open(UNIT).read())
        check("no settings backup for an addin", not [f for f in os.listdir("/media/az01-internal/Settings/MPC") if ".bak-" in f])
        check("no page errors", not errs, errs)
finally:
    app.terminate(); web.terminate()
print("ALL PASSED" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
