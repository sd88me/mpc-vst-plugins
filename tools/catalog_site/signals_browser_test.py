"""Browser test of the community-signals preview on the catalog page (docs/COMMUNITY_SIGNALS.md): off without ?signals=1; the sign-in button in the
sticky header; the strip between every card's title bar and its tag chips; the popup's Community and GitHub-issues sections; sign-in handoff, reports, likes, sign-out and
account deletion; a dead service or a failing GitHub leave the page working; text from outside is escaped. Everything is MOCKED (the service and GitHub):
no network, no real accounts. Run like browser_test.py:

  python3 tools/catalog_site.py --catalog tools/catalog_site/fixture-catalog.json --out /tmp/site
  docker run --rm -v /tmp:/w -v "$PWD/tools/catalog_site":/t -w /w mpc-vst-html-art python3 /t/signals_browser_test.py /w/site/index.html"""
import json, sys
from playwright.sync_api import sync_playwright
URL = "file://" + sys.argv[1]
API = "https://signals.test"
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond: fails.append(name)

CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type", "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
        "access-control-expose-headers": "set-auth-token"}
class Service:
    """A stand-in for the Worker. `up=False` makes every call fail like a dead network."""
    def __init__(self, up=True):
        self.up, self.calls, self.token_ok = up, [], "tok-123"
        self.counts = {"test-synth": {"working": 7, "likes": 3, "versions": {"1.1.0": 4, "1.0.0": 5}}, "tested-two": {"working": 12, "likes": 1, "versions": {"1.1.0": 12}},
                       "pack-drive": {"working": 3, "likes": 1, "versions": {}}, "pack-gate": {"working": 2, "likes": 2, "versions": {}}, "pack-kick": {"working": 5, "likes": 0, "versions": {}}}
        self.detail = {"id": "test-synth", "working": 7, "likes": 3, "versions": {"1.1.0": 4, "1.0.0": 5},
                       "devices": [{"device": "MPC Live II", "os": "3.9.1", "n": 4}, {"device": "Force", "os": "3.9.1", "n": 3}],
                       "recent": [{"version": "1.1.0", "device": "MPC Live II", "os": "3.9.1", "date": "2026-11-04"}, {"version": "1.0.0", "device": "Force", "os": "3.9.1", "date": "2026-11-02"}]}
        self.me = {"user": {"id": "u1", "name": "Fan"}, "likes": [], "reports": [], "follows": [], "feedUrl": None}
    def handle(self, route):
        req = route.request; path = req.url[len(API):]; self.calls.append((req.method, path, req.post_data))
        if not self.up: return route.abort()
        if req.method == "OPTIONS": return route.fulfill(status=204, headers=CORS)
        body = json.loads(req.post_data or "{}") if req.post_data else {}
        authed = req.headers.get("authorization") == "Bearer " + self.token_ok
        j = lambda code, obj, extra=None: route.fulfill(status=code, content_type="application/json", headers={**CORS, **(extra or {})}, body=json.dumps(obj))
        if path == "/api/counts": return j(200, {"counts": self.counts})
        if path.startswith("/api/plugin?id="): pid = path.split("=")[1]; return j(200, {**self.detail, "id": pid} if pid == "test-synth" else {"id": pid, "working": 0, "likes": 0, "versions": {}, "devices": [], "recent": []})
        if path == "/api/auth/one-time-token/verify": return j(200, {}, {"set-auth-token": self.token_ok}) if body.get("token") == "abc" else j(400, {"error": "Invalid token"})
        if path.startswith("/api/signin/start?"): return route.fulfill(status=200, content_type="text/html", body="start")
        if path == "/api/auth/sign-out": return j(200, {})
        if not authed: return j(401, {"error": "Sign in first."})
        if path == "/api/me" and req.method == "GET": return j(200, self.me)
        if path == "/api/me" and req.method == "DELETE": return j(200, {"ok": True})
        if path == "/api/like": return j(200, {"ok": True})
        if path == "/api/follow":
            self.me["feedUrl"] = self.me["feedUrl"] or "https://signals.test/feed/" + "A" * 32 + ".xml"
            return j(200, {"ok": True, "feedUrl": self.me["feedUrl"]})
        if path == "/api/feed/rotate": self.me["feedUrl"] = "https://signals.test/feed/" + "B" * 32 + ".xml"; return j(200, {"ok": True, "feedUrl": self.me["feedUrl"]})
        if path == "/api/working": return j(200, {"ok": True, "created": req.method == "POST"})
        return j(404, {"error": "Not found."})

class GitHub:
    """A stand-in for api.github.com: mode "ok", "no-issues" or "down" (rate limited)."""
    def __init__(self, mode="ok"): self.mode, self.calls = mode, []
    def handle(self, route):
        path = route.request.url.split("api.github.com")[1]; self.calls.append(path)
        h = {"access-control-allow-origin": "*"}
        if self.mode == "down": return route.fulfill(status=403, headers=h, content_type="application/json", body="{}")
        if path.endswith("/issues?state=all&per_page=50"):
            issues = [{"number": 12, "title": "Crackles on Live II at 128 samples <b>bold</b>", "body": "Plugin: Test Synth 1.0.0\nDevice: MPC Live II", "html_url": "https://github.com/acme/test-synth/issues/12", "comments": 3, "created_at": "2026-11-01T10:00:00Z"},
                      {"number": 9, "title": "A pull request", "body": "v1.1.0", "html_url": "https://github.com/acme/test-synth/pull/9", "comments": 0, "created_at": "2026-10-30T10:00:00Z", "pull_request": {}},
                      {"number": 7, "title": "Preset names cut off", "body": "no version here", "html_url": "https://github.com/acme/test-synth/issues/7", "comments": 1, "created_at": "2026-10-20T10:00:00Z"},
                      {"number": 5, "title": "Worked before", "body": "fine in 1.0.0 but broken in 1.1.0, not in 21.1.0.5", "html_url": "https://github.com/acme/test-synth/issues/5", "comments": 0, "created_at": "2026-10-10T10:00:00Z"},
                      {"number": 3, "title": "Fixed long ago", "body": "Plugin: Test Synth 1.0.0", "html_url": "https://github.com/acme/test-synth/issues/3", "comments": 2, "created_at": "2026-10-01T10:00:00Z", "state": "closed", "closed_at": "2026-10-15T10:00:00Z"}]
            return route.fulfill(status=200, headers=h, content_type="application/json", body=json.dumps(issues))
        return route.fulfill(status=200, headers=h, content_type="application/json", body=json.dumps({"has_issues": self.mode != "no-issues", "has_discussions": True, "open_issues_count": 99}))

def page(b, svc, gh=None, query="?signals=1", hash_="", signed_in=False, size=(1280, 900)):
    ctx = b.new_context(viewport={"width": size[0], "height": size[1]})
    pg = ctx.new_page(); errors = []; gh = gh or GitHub()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: d.accept())                    # the delete-account confirm()
    pg.add_init_script("window.__SIGNALS_API = '%s'; %s" % (API, "localStorage.setItem('openmpc-signals-token', 'tok-123')" if signed_in else ""))
    pg.route(API + "/**", svc.handle); pg.route("https://api.github.com/**", gh.handle)
    pg.route("https://provider.test/**", lambda r: r.fulfill(status=200, content_type="text/html", body="provider"))
    pg.route("https://shots.invalid/**", lambda r: r.fulfill(status=404))
    pg.goto(URL + query + hash_); pg.wait_for_timeout(300)
    return ctx, pg, errors, gh
def box(loc): return loc.bounding_box()

with sync_playwright() as p:
    b = p.chromium.launch()
    # 1. off without the flag
    svc = Service(); ctx, pg, errs, gh = page(b, svc, query="")
    check("no flag: no signals UI, no service calls", pg.locator(".sig:not(.stat)").count() == 0 and pg.locator("#sig-in").count() == 0 and not svc.calls, svc.calls)
    check("no flag: no sort options added", "Most liked" not in pg.locator("#sort").inner_text())
    ctx.close()
    # 2. signed out: header button, strip placement, counts, sorts
    svc = Service(); ctx, pg, errs, gh = page(b, svc)
    check("Sign in is a button in the sticky header", pg.locator(".bar #sig-in").is_visible())
    pg.mouse.wheel(0, 1500); pg.wait_for_timeout(200)
    bb = box(pg.locator("#sig-in")); check("and it stays in view after scrolling", bb is not None and 0 <= bb["y"] < 80, bb)
    pg.evaluate("scrollTo(0, 0)")
    row = pg.locator('.sig[data-sig="test-synth"]')
    check("the strip shows the count", row.count() == 1 and "7 working" in row.inner_text().replace("\n", " ").replace("✓", "").strip().replace("  ", " ") or "7" in row.inner_text(), row.inner_text() if row.count() else "")
    check("the strip also carries the downloads count", "6" in row.locator('.sig-v[title^="Downloads"]').inner_text() and row.locator('.sig-v[title^="Downloads"]').count() == 1, row.inner_text())
    check("the Sign in button is the theme yellow (amber), not the red of the current-page tab", pg.evaluate("""() => { const a = getComputedStyle(document.querySelector('#sig-in')).backgroundColor, b = getComputedStyle(document.querySelector('.nav a[aria-current]')).backgroundColor; return [a, b, a !== b && a === 'rgb(224, 161, 0)']; }""")[2], pg.evaluate("getComputedStyle(document.querySelector('#sig-in')).backgroundColor"))
    check("the count says it is not verification", "not hardware verification" in row.locator(".sig-n").get_attribute("title"))
    card = pg.locator("article.card", has=row)
    order = card.evaluate("el => [...el.children].map(c => c.className.split(' ')[0] || c.tagName.toLowerCase())")
    check("the strip comes right after the title bar and before the tag chips", order.index("sig") == order.index("header") + 1 and order[order.index("sig") + 1] == "tags", order)
    check("the title bar is above it and the tags below it", box(card.locator("header"))["y"] < box(row)["y"] < box(card.locator(".tags"))["y"])
    check("a plugin without reports shows zero", "0" in pg.locator('.sig[data-sig="old-catalog"] .sig-n').inner_text())
    check("sort options appear", "Most reported working" in pg.locator("#sort").inner_text() and "Most liked" in pg.locator("#sort").inner_text())
    pg.select_option("#sort", "working"); pg.wait_for_timeout(100)
    names = pg.locator("#grid article.card h2").all_inner_texts()
    check("most reported working puts the 12 before the 7", names.index("TESTED TWO") < names.index("TEST SYNTH") if "TESTED TWO" in names and "TEST SYNTH" in names else False, names)
    pg.locator('[data-sig-work="test-synth"]').click()
    check("signed out: Works for me opens the sign-in dialog", pg.locator("#sig-dialog").is_visible() and pg.locator("[data-sig-provider]").count() == 2)
    pg.locator('[data-sig-provider="discord"]').click()
    try: pg.wait_for_url("**/api/signin/start?**", timeout=5000)
    except Exception: pass
    starts = [c[1] for c in svc.calls if c[1].startswith("/api/signin/start?")]
    check("sign-in is a navigation to the service's start route (so the state cookie is first-party), with a return address", len(starts) == 1 and "provider=discord" in starts[0] and "&return=" in starts[0] and "/api/signin/start?provider=discord" in pg.url, [starts, pg.url])
    check("sign-in no longer uses a cross-site fetch to /api/auth/sign-in/social", not any(c[1] == "/api/auth/sign-in/social" for c in svc.calls))
    ctx.close()
    # 3. handoff, bad token
    svc = Service(); ctx, pg, errs, gh = page(b, svc, hash_="#ott=abc")
    check("one-time token is exchanged and not left in the address", any(c[1] == "/api/auth/one-time-token/verify" and json.loads(c[2])["token"] == "abc" for c in svc.calls) and "ott" not in pg.evaluate("location.hash"))
    check("the bearer token is kept and the header shows the person", pg.evaluate("localStorage.getItem('openmpc-signals-token')") == "tok-123" and "fan" in pg.locator(".bar #sig-who").inner_text().lower())
    check("a short message says so", "signed in" in pg.locator("#sig-toast").inner_text().lower())
    ctx.close()
    svc = Service(); ctx, pg, errs, gh = page(b, svc, hash_="#ott=wrong")
    check("a bad one-time token shows a message and no sign-in", "did not finish" in pg.locator("#sig-toast").inner_text() and pg.locator("#sig-who").count() == 0 and pg.locator("#sig-in").is_visible())
    ctx.close()
    # 4. signed in: report, like, withdraw, header menu, sign out
    svc = Service(); ctx, pg, errs, gh = page(b, svc, signed_in=True)
    pg.locator('[data-sig-work="test-synth"]').click()
    check("report dialog lists versions and devices", pg.locator('#sig-form select[name=version] option').count() == 2 and pg.locator('#sig-form select[name=device] option').count() >= 8)
    pg.fill('#sig-form input[name=os]', "3.9.1"); pg.select_option('#sig-form select[name=device]', "MPC Live II"); pg.select_option('#sig-form select[name=version]', "1.1.0")
    pg.locator('#sig-form button[type=submit]').click(); pg.wait_for_timeout(300)
    sent = json.loads([c for c in svc.calls if c[0] == "POST" and c[1] == "/api/working"][-1][2])
    check("the report is sent as typed", sent == {"plugin": "test-synth", "version": "1.1.0", "device": "MPC Live II", "os": "3.9.1"}, sent)
    check("the count goes up once and the button says so", "8" in pg.locator('.sig[data-sig="test-synth"] .sig-n').inner_text() and "you reported this" in pg.locator('[data-sig-work="test-synth"]').inner_text().lower())
    pg.locator('[data-sig-like="test-synth"]').click(); pg.wait_for_timeout(200)
    check("like fills the heart and counts", pg.locator('[data-sig-like="test-synth"]').get_attribute("aria-pressed") == "true" and "4" in pg.locator('[data-sig-like="test-synth"]').inner_text())
    pg.locator('[data-sig-like="test-synth"]').click(); pg.wait_for_timeout(200)
    check("unlike sends DELETE", any(c[0] == "DELETE" and c[1] == "/api/like" for c in svc.calls) and pg.locator('[data-sig-like="test-synth"]').get_attribute("aria-pressed") == "false")
    # 5. the popup
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(700)
    pop = pg.locator("#modal-body")
    check("popup has the same strip, with the Community section right after it", pop.locator(".sig").count() == 1)
    det = pop.locator(".sig-detail")
    check("popup lists who reported on what", "Reported on" in det.inner_text() and "MPC Live II" in det.inner_text() and "4 people" in det.inner_text() and "Force" in det.inner_text(), det.inner_text()[:300])
    check("popup lists the latest reports", "Latest reports" in det.inner_text() and "2026-11-04" in det.inner_text())
    check("popup shows the newest-version count", "4 on v1.1.0" in det.inner_text(), det.inner_text()[:200])
    check("popup lists the person's own report with a withdraw button", pop.locator("[data-sig-wd]").count() == 1)
    gh_t = pop.locator(".sig-gh").inner_text()
    check("popup counts open and closed issues by version (pull requests left out, GitHub's own count ignored)", "3 open · 1 closed issues by version: v1.1.0 (2 open), v1.0.0 (1 open · 1 closed)" in gh_t and "99" not in gh_t, gh_t)
    check("it links to report, all issues and discussions", pop.locator('a:has-text("Report an issue")').count() == 1 and "All issues" in gh_t and pop.locator('a:has-text("Discussions")').count() == 1)
    pop.locator("[data-sig-showvers]").click(); pg.wait_for_timeout(200)
    det_v = pop.locator("details.vers")
    check("Show them in the version history opens it", det_v.get_attribute("open") is not None)
    rows = det_v.locator("table > tbody > tr:not(.sig-vi), table > tr:not(.sig-vi)")
    rowtxt = [r.inner_text().replace("\t", " ").lower() for r in rows.all()]   # the CSS uppercases some labels
    check("each version row has its downloads, working count and open/closed issues", any("v1.1.0" in t and "3 downloads" in t and "4 working" in t and "2 open" in t and "closed" not in t.split("4 working")[1] for t in rowtxt) and any("v1.0.0" in t and "3 downloads" in t and "5 working" in t and "1 open · 1 closed" in t for t in rowtxt), rowtxt)
    check("the history's summary counts the open issues", "3 open · 1 closed issues" in det_v.locator("summary").inner_text().lower(), det_v.locator("summary").inner_text())
    check("issues start collapsed", det_v.locator("tr.sig-vi:visible").count() == 0)
    det_v.locator('[data-sig-vi="1.0.0"]').click()
    li = det_v.locator("tr.sig-vi:visible li")
    check("a version lists its open issues first, then closed ones marked closed", li.count() == 2 and "Crackles" in li.nth(0).inner_text() and "closed 2026-10-15" in li.nth(1).inner_text() and li.nth(1).get_attribute("class") == "sig-closed", li.all_inner_texts())
    check("expanding a version shows its issue, escaped", "Crackles on Live II" in det_v.locator("tr.sig-vi:visible").inner_text() and det_v.locator(".sig-issues b").count() == 0 and "<b>bold</b>" in det_v.locator("tr.sig-vi:visible").inner_text() and "placed by date" not in det_v.locator("tr.sig-vi:visible").inner_text())
    det_v.locator('[data-sig-vi="1.1.0"]').click()
    t11 = det_v.locator('[data-sig-vi="1.1.0"]').locator("xpath=ancestor::tr[1]/following-sibling::tr[1]").inner_text()
    check("an issue that names a version goes there (newest named), others go by date and say so", "Worked before" in t11 and "Preset names cut off" in t11 and t11.count("placed by date") == 1, t11)
    check("a longer version number is not mistaken for a known one", "Worked before" not in det_v.locator('[data-sig-vi="1.0.0"]').locator("xpath=ancestor::tr[1]/following-sibling::tr[1]").inner_text())
    n = len(gh.calls); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(500)
    check("reopening the popup does not ask GitHub again", len(gh.calls) == n, (n, len(gh.calls)))
    pg.locator("[data-sig-wd]").click(); pg.wait_for_timeout(500)
    check("withdrawing in the popup sends DELETE and lowers the count", any(c[0] == "DELETE" and c[1] == "/api/working" for c in svc.calls) and pg.locator("#modal-body [data-sig-wd]").count() == 0 and "7" in pg.locator('#modal-body .sig-n').inner_text())
    pg.keyboard.press("Escape")
    pg.locator("#sig-who").click()
    check("header menu opens", pg.locator("#sig-menu").is_visible())
    pg.locator("#sig-out").click(); pg.wait_for_timeout(200)
    check("sign out forgets the token and shows Sign in again", pg.evaluate("localStorage.getItem('openmpc-signals-token')") is None and pg.locator(".bar #sig-in").is_visible())
    ctx.close()
    # 5b. follow a plugin and the personal feed
    svc = Service(); ctx, pg, errs, gh = page(b, svc)
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(500)
    f = pg.locator("#modal-follow")
    check("preview on: the popup button is a Follow toggle", f.inner_text().strip().endswith("Follow") and "Follow updates" not in f.inner_text() and f.get_attribute("aria-pressed") == "false", f.inner_text())
    f.click()
    check("signed out: Follow asks you to sign in (and does not leave the page)", pg.locator("#sig-dialog").is_visible() and pg.locator("[data-sig-provider]").count() == 2 and pg.url.startswith("file://"))
    ctx.close()
    svc = Service(); ctx, pg, errs, gh = page(b, svc, signed_in=True)
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(500)
    pg.locator("#modal-follow").click(); pg.wait_for_timeout(400)
    check("Follow sends the plugin and the button says Following", any(c[0] == "POST" and c[1] == "/api/follow" and json.loads(c[2]) == {"plugin": "test-synth"} for c in svc.calls) and pg.locator("#modal-follow").get_attribute("aria-pressed") == "true" and "Following" in pg.locator("#modal-follow").inner_text())
    check("a message says where the feed address is", "feed address" in pg.locator("#sig-toast").inner_text())
    pg.keyboard.press("Escape"); pg.wait_for_timeout(100)
    pg.locator("#sig-who").click(); pg.locator("#sig-follows").click(); pg.wait_for_timeout(300)
    dl = pg.locator("#sig-dialog")
    check("the account menu opens Following and my feed with the address and the list", dl.is_visible() and pg.locator("#sig-feed").input_value() == "https://signals.test/feed/" + "A" * 32 + ".xml" and "Test Synth" in dl.inner_text() and pg.locator("[data-sig-unfollow]").count() == 1)
    check("the address field is read-only and warns to keep it private", pg.locator("#sig-feed").get_attribute("readonly") is not None and "keep it private" in dl.inner_text())
    pg.locator("[data-sig-rotate]").click(); pg.wait_for_timeout(300)
    check("Regenerate shows a new address and says the old one stops", pg.locator("#sig-feed").input_value() == "https://signals.test/feed/" + "B" * 32 + ".xml" and "no longer works" in pg.locator("#sig-err").inner_text())
    pg.locator("[data-sig-unfollow]").click(); pg.wait_for_timeout(300)
    check("Unfollow in the list sends DELETE and empties it", any(c[0] == "DELETE" and c[1] == "/api/follow" for c in svc.calls) and "not following any plugins" in pg.locator("#sig-dialog").inner_text())
    pg.locator("[data-sig-close]").click()
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(300)
    check("the popup button is back to Follow", pg.locator("#modal-follow").get_attribute("aria-pressed") == "false")
    check("the popup's Community section links the plugin's RSS feed", pg.locator('#modal-body a[href="feed/test-synth.xml"]').count() == 1)
    ctx.close()
    svc = Service(up=False); ctx, pg, errs, gh = page(b, svc)
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(300)
    check("service down: the button stays a plain link to the plugin's feed", pg.locator("#modal-follow").get_attribute("href") == "feed/test-synth.xml" and "Follow updates" in pg.locator("#modal-follow").inner_text() and pg.locator("#modal-follow").get_attribute("aria-pressed") is None)
    ctx.close()
    # 5c. collections: an aggregate on the card, per-plugin reporting inside, Follow all, sorting
    svc = Service(); ctx, pg, errs, gh = page(b, svc, signed_in=True)
    cs = pg.locator('.sig[data-sig-coll="acme-pack"]')
    check("the collection card shows its best plugin's figures, not a sum, with no buttons", cs.count() == 1 and "5" in cs.locator(".sig-n").inner_text() and "10" not in cs.inner_text() and "Best of 5 plugins (3 with reports)" in cs.inner_text() and cs.locator("button").count() == 0 and "Open the set" in cs.inner_text(), cs.inner_text() if cs.count() else "")
    check("its tooltip names the plugin that has the most reports", "Pack Kick" in cs.locator(".sig-n").get_attribute("title"))
    check("the collection strip shows the total downloads of its members", "55" in cs.inner_text(), cs.inner_text())
    ccard = pg.locator("article.card.coll", has=cs); order = ccard.evaluate("el => [...el.children].map(c => c.className.split(' ')[0] || c.tagName.toLowerCase())")
    check("the strip sits between the title bar and the tag chips", order.index("sig") == order.index("header") + 1 and order[order.index("sig") + 1] == "tags", order)
    pg.select_option("#sort", "working"); pg.wait_for_timeout(100)
    ns = pg.locator("#grid article.card h2").all_inner_texts()
    check("Most reported working places the collection by its best plugin (12, then 7, then 5)", ns.index("TESTED TWO") < ns.index("TEST SYNTH") < ns.index("ACME PACK"), ns)
    pg.locator('h2 a[data-coll="acme-pack"]').first.click(); pg.wait_for_timeout(500)
    pop = pg.locator("#modal-body")
    check("the collection popup has the same strip under its title bar", pop.locator('.sig[data-sig-coll="acme-pack"]').count() == 1 and "5" in pop.locator('.sig[data-sig-coll="acme-pack"] .sig-n').inner_text() and "Report on each plugin below" in pop.inner_text())
    check("each member row has its own strip with Works for me and a like", pop.locator(".member .sig.mini").count() == 5 and pop.locator('.member .sig.mini[data-sig="pack-kick"]').inner_text().replace("\n", " ").count("5") >= 1 and pop.locator(".member [data-sig-work]").count() == 5)
    f = pg.locator("#modal-follow")
    check("the popup offers Follow all 5", f.is_visible() and f.inner_text().strip().endswith("Follow all 5") and f.get_attribute("aria-pressed") == "false", f.inner_text())
    pop.locator('[data-sig-work="pack-kick"]').click(); pg.wait_for_timeout(300)
    check("Works for me on a member opens that plugin's report dialog", pg.locator("#sig-dialog").is_visible() and "Pack Kick" in pg.locator("#sig-dialog h2").inner_text())
    pg.fill('#sig-form input[name=os]', "3.9.1"); pg.locator('#sig-form button[type=submit]').click(); pg.wait_for_timeout(400)
    check("the report raises the member's count and the collection's best figure, in the popup", "6" in pg.locator('#modal-body .sig[data-sig="pack-kick"] .sig-n').inner_text() and "6" in pg.locator('#modal-body .sig[data-sig-coll="acme-pack"] .sig-n').inner_text())
    n0 = len([c for c in svc.calls if c[0] == "POST" and c[1] == "/api/follow"])
    pg.locator("#modal-follow").click(); pg.wait_for_timeout(700)
    posted = [json.loads(c[2])["plugin"] for c in svc.calls if c[0] == "POST" and c[1] == "/api/follow"][n0:]
    check("Follow all follows every member, one request each", sorted(posted) == ["pack-drive", "pack-gate", "pack-kick", "pack-seq", "pack-verb"], posted)
    check("and the button says Following all 5", pg.locator("#modal-follow").get_attribute("aria-pressed") == "true" and "Following all 5" in pg.locator("#modal-follow").inner_text(), pg.locator("#modal-follow").inner_text())
    d0 = len([c for c in svc.calls if c[0] == "DELETE" and c[1] == "/api/follow"])
    pg.locator("#modal-follow").click(); pg.wait_for_timeout(700)
    check("pressing it again unfollows them all", len([c for c in svc.calls if c[0] == "DELETE" and c[1] == "/api/follow"]) - d0 == 5 and pg.locator("#modal-follow").get_attribute("aria-pressed") == "false")
    ctx.close()
    svc = Service(); ctx, pg, errs, gh = page(b, svc)
    pg.locator('h2 a[data-coll="acme-pack"]').first.click(); pg.wait_for_timeout(400)
    pg.locator('#modal-body [data-sig-work="pack-kick"]').click(); pg.wait_for_timeout(200)
    a_ok = pg.locator("#sig-dialog").is_visible() and pg.locator("[data-sig-provider]").count() == 2
    pg.locator("[data-sig-close]").click(); pg.wait_for_timeout(100)
    pg.locator("#modal-follow").click(); pg.wait_for_timeout(200)
    check("signed out: reporting on a member or following all asks you to sign in", a_ok and pg.locator("#sig-dialog").is_visible() and pg.locator("[data-sig-provider]").count() == 2)
    ctx.close()
    svc = Service(up=False); ctx, pg, errs, gh = page(b, svc)
    check("service down: the collection card has no strip", pg.locator("article.card.coll .sig:not(.stat)").count() == 0 and "55" in pg.locator("article.card.coll .sig.stat").inner_text())
    pg.locator('h2 a[data-coll="acme-pack"]').first.click(); pg.wait_for_timeout(300)
    check("service down: the collection popup keeps a plain link to the collection's feed and has no strips", pg.locator("#modal-follow").get_attribute("href") == "feed/c/acme-pack.xml" and pg.locator("#modal-body .sig:not(.stat)").count() == 0)
    ctx.close()
    # 6. delete account from the header menu
    svc = Service(); ctx, pg, errs, gh = page(b, svc, signed_in=True)
    pg.locator("#sig-who").click(); pg.locator("#sig-del").click(); pg.wait_for_timeout(500)
    check("delete my account sends the confirmation and signs out", any(c[0] == "DELETE" and c[1] == "/api/me" and json.loads(c[2]) == {"confirm": "delete my account"} for c in svc.calls) and pg.evaluate("localStorage.getItem('openmpc-signals-token')") is None and "deleted" in pg.locator("#sig-toast").inner_text())
    ctx.close()
    # 7. a rejected token is dropped quietly
    svc = Service(); svc.token_ok = "other"; ctx, pg, errs, gh = page(b, svc, signed_in=True)
    check("a rejected token is cleared", pg.locator("#sig-in").is_visible())
    ctx.close()
    # 8. GitHub failing or Issues turned off
    for mode, want in (("down", "Could not load issues"), ("no-issues", "turned Issues off")):
        svc = Service(); ctx, pg, errs, gh = page(b, svc, gh=GitHub(mode)); pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(700)
        check("github %s: says so, the rest of the popup works" % mode, want in pg.locator("#modal-body .sig-gh").inner_text() and "Reported on" in pg.locator("#modal-body .sig-comm").inner_text() and "working" in pg.locator("#modal-body details.vers").text_content(), pg.locator("#modal-body .sig-gh").inner_text())
        ctx.close()
    # 9. a dead service leaves the page working
    svc = Service(up=False); ctx, pg, errs, gh = page(b, svc)
    check("service down: no community strips, but the downloads bars stay, and cards still render", pg.locator(".sig:not(.stat)").count() == 0 and pg.locator(".sig.stat").count() >= 3 and pg.locator("#grid article.card").count() >= 3)
    check("service down: no extra sorts, Sign in still offered, no errors", "Most liked" not in pg.locator("#sort").inner_text() and pg.locator("#sig-in").is_visible() and not errs, errs)
    pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(300)
    check("service down: popup opens without a Community section", pg.locator("#modal-body .sig-detail").count() == 0 and pg.locator("#modal-body h2").count() == 1)
    ctx.close()
    # 10. text from outside is escaped
    svc = Service(); svc.me = {"user": {"id": "u1", "name": "<img src=x onerror=window.__x=1>"}, "likes": [], "reports": [{"plugin_id": "test-synth", "version": "1.1.0", "device": "<b>d</b>", "os": "<i>o</i>"}]}
    svc.detail["devices"][0]["device"] = "<u>dev</u>"
    ctx, pg, errs, gh = page(b, svc, signed_in=True); pg.locator('a[data-open="test-synth"]').first.click(); pg.wait_for_timeout(700)
    check("names and report fields are escaped", pg.evaluate("window.__x") is None and pg.locator(".bar img").count() == 0 and pg.locator("#modal-body .sig-detail u, #modal-body .sig-detail b, #modal-body .sig-detail i").count() == 0 and "<u>dev</u>" in pg.locator("#modal-body .sig-comm").inner_text())
    ctx.close()
    # 11. phone: header button reachable, no sideways scroll, strip fits
    svc = Service(); ctx, pg, errs, gh = page(b, svc, size=(375, 800))
    check("phone: Sign in is visible in the header", pg.locator(".bar #sig-in").is_visible() and 0 <= box(pg.locator("#sig-in"))["y"] < 120, box(pg.locator("#sig-in")))
    check("phone: no horizontal scroll", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), pg.evaluate("[document.documentElement.scrollWidth, innerWidth]"))
    sb = box(pg.locator('.sig[data-sig="test-synth"]')); cb = box(pg.locator("article.card", has=pg.locator('.sig[data-sig="test-synth"]')))
    check("phone: the strip stays inside its card", sb["x"] >= cb["x"] and sb["x"] + sb["width"] <= cb["x"] + cb["width"] + 1, (sb, cb))
    ctx.close(); b.close()
print("%d failed" % len(fails) if fails else "all passed"); sys.exit(1 if fails else 0)
