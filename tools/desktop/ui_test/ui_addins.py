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
     "versions": [dict(rel("1.0.0", "%064x" % 1, "sd88me - VST - Acid"), requires="Your own ROMs")]},
    {"id": "test-addin", "name": "Test addin", "author": "acme", "kind": "addin", "summary": "Loaded with MPC", "distribution": "release",
     "latest": "1.0.0", "versions": [rel("1.0.0", "%064x" % 2)], "shares_hooks": [{"id": "rec-addin", "name": "Rec addin", "symbols": ["snd_pcm_writei"], "unchained": ["rec-addin"]}]},
    # replaces a function test-addin also replaces and may not pass it on (catalog shares_hooks): its row says so once test-addin is on the device
    {"id": "rec-addin", "name": "Rec addin", "author": "acme", "kind": "addin", "summary": "Records", "distribution": "release",
     "latest": "1.0.0", "versions": [rel("1.0.0", "%064x" % 3)], "shares_hooks": [{"id": "test-addin", "name": "Test addin", "symbols": ["snd_pcm_writei"], "unchained": ["rec-addin"]}]},
    # dependencies (catalog_build.py resolves the rules and picks): one that brings Rec addin along, one that conflicts with Test addin
    {"id": "dep-addin", "name": "Dep addin", "author": "acme", "kind": "addin", "summary": "Brings its dependency", "distribution": "release",
     "latest": "1.0.0", "versions": [dict(rel("1.0.0", "%064x" % 4), depends=[{"id": "rec-addin", "rules": [[">=", "1.0.0"]], "pick": {"armv7": "1.0.0", "aarch64": None}}])]},
    {"id": "rival-addin", "name": "Rival addin", "author": "acme", "kind": "addin", "summary": "Declares a conflict", "distribution": "release",
     "latest": "1.0.0", "versions": [dict(rel("1.0.0", "%064x" % 5), conflicts=["test-addin"])]}]}
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
        pg.goto(link); pg.click("#mode-install")
        pg.fill("#host", "127.0.0.1"); pg.fill("#pw", "secret"); pg.click("#connect")
        pg.wait_for_selector("#cat input[type=checkbox]", timeout=30000)
        check("a plugin's requires is shown", "Acid needs: Your own ROMs" in pg.locator("#cat li", has_text="Acid").first.text_content())
        pg.locator("#cat li", has_text="Acid").first.screenshot(path="/out/ui-requires-row.png")
        check("the kind tabs offer Addins", "Addins" in pg.locator("#ktabs").text_content())
        pg.click("#kt-addin")   # the list opens on Instruments (#266)
        row = pg.locator("#cat li", has_text="Test addin")
        check("the addin is in the catalog list", row.count() == 1)
        check("no hook note while the other addin is neither installed nor ticked", "same MPC functions" not in pg.locator("#cat li", has_text="Rec addin").first.text_content())
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
        check("the catalog row now says it is on the device", "on the device" in pg.locator("#cat li:has(#c_test-addin)").text_content())
        rec = pg.locator("#cat li", has_text="Rec addin").first.text_content()
        pg.locator("#cat li", has_text="Rec addin").first.screenshot(path="/out/ui-hooks-row.png")
        check("an addin that hooks the same calls as an installed one says so", "Rec addin and Test addin replace some of the same MPC functions (snd_pcm_writei), and one of them may not pass the calls on" in rec, rec)
        pg.check("#c_dep-addin"); pg.click("#go"); pg.wait_for_selector("#dlg[open]")
        dt = pg.locator("#dlgtxt").text_content()
        check("a missing dependency is added to the batch, with the reason", "About to install: Dep addin 1.0.0" in dt and "Also installing, for the dependencies: Rec addin 1.0.0 (needed by Dep addin)" in dt, dt)
        pg.locator("#dlg").screenshot(path="/out/ui-deps-dialog.png")
        check("nothing refused: the button is plain Install", pg.locator("#yes").text_content() == "Install", pg.locator("#yes").text_content())
        pg.click("#no"); pg.uncheck("#c_dep-addin")
        pg.check("#c_rival-addin"); pg.click("#go"); pg.wait_for_selector("#dlg[open]")
        dt = pg.locator("#dlgtxt").text_content()
        pg.locator("#dlg").screenshot(path="/out/ui-conflict-dialog.png")
        check("a conflict with an installed addin is refused unless forced", "Warning: Rival addin conflicts with Test addin." in dt and pg.locator("#yes").text_content() == "Install anyway", dt)
        pg.click("#no"); pg.uncheck("#c_rival-addin")
        r = pg.evaluate("""fetch('/api/install', {method: 'POST', headers: {'X-MPC-Token': T, 'Content-Type': 'application/json'},
                           body: JSON.stringify({catalog: ['rival-addin'], uploads: [], confirm: true})}).then(r => r.status)""")
        check("the app refuses the conflicting install without force (409)", r == 409, r)
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
        check("no settings backup for an addin", not [f for f in os.listdir("/media/az01-internal/Settings/MPC") if ".bak-" in f], os.listdir("/media/az01-internal/Settings/MPC"))
        check("no page errors", not errs, errs)
finally:
    app.terminate(); web.terminate()
print("ALL PASSED" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
