"""Browser test of the catalog page's install list (tools/catalog_site/index.template.html): tick plugins, get the command, refuse a
bad address, keep the selection in the link, the screenshot popup and its link, no horizontal scroll on a phone. Needs Playwright, which the html_art image has:

  python3 tools/catalog_site.py --catalog tools/catalog_site/fixture-catalog.json --out /tmp/site
  docker build -q -t mpc-vst-html-art tools/html_art
  docker run --rm -v /tmp:/w -v "$PWD/tools/catalog_site":/t -w /w mpc-vst-html-art python3 /t/browser_test.py /w/site/index.html /w

The last two arguments are the built page and a folder for two screenshots (shot-desktop.png, shot-phone.png)."""
import base64, os, re, sys
from playwright.sync_api import sync_playwright
URL = "file://" + sys.argv[1]
SHOTS = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + extra if extra and not cond else ""))
    if not cond: fails.append(name)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    # the fixture's screenshots live on a fake host: test-synth gets a 1x1 PNG, tested-two a 404 (a dead link)
    PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    pg.route("https://shots.invalid/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG)
             if r.request.url.endswith("/test-synth.png") else r.fulfill(status=404))
    pg.goto(URL)
    check("panel hidden at first", pg.locator("#inst").is_hidden())
    picks = pg.locator("[data-pick]")
    n = picks.count(); check("downloadable cards have a checkbox", n >= 3, str(n))   # the fixture has 4 downloadable cards, one experimental and so hidden by default
    ids = [picks.nth(i).get_attribute("data-pick") for i in range(n)]
    check("build-yourself cards have none", "monomodule" not in ids and "machinedrum-module" not in ids, str(ids))
    picks.nth(0).check()
    check("a bar appears on the first tick, collapsed", pg.locator("#inst").is_visible() and pg.locator("#inst").get_attribute("open") is None)
    pg.locator("#inst > summary").click()
    check("it opens on click", pg.locator("#inst").get_attribute("open") is not None)
    check("count text", pg.locator("#inst-count").text_content() == "1 plugin selected")
    main = pg.locator("#cmd-main").text_content()
    check("command has the id and a placeholder", ids[0] in main and "<device-ip>" in main and main.startswith("ssh -t root@"), main)
    pg.fill("#ip", "192.168.1.20")
    main = pg.locator("#cmd-main").text_content()
    check("ip appears", "root@192.168.1.20" in main and "<device-ip>" not in main, main)
    pg.fill("#ip", "1.2.3.4; rm -rf /")
    main = pg.locator("#cmd-main").text_content()
    check("bad ip is refused, no injection", pg.locator("#ipbad").is_visible() and "rm -rf" not in main and "<device-ip>" in main, main)
    pg.fill("#ip", "192.168.1.20")
    picks.nth(1).check()
    main = pg.locator("#cmd-main").text_content()
    check("two ids", ids[0] in main and ids[1] in main and main.count("install") == 1, main)
    check("hash keeps the selection", "sel=" + ids[0] + "," + ids[1] in pg.evaluate("location.hash").replace("%2C", ","), pg.evaluate("location.hash"))
    pg.locator("#clear").click()
    check("clear filters keeps the selection", pg.locator("[data-pick]:checked").count() == 2)
    review = pg.locator("#cmd-review").text_content()
    check("review steps: download, read, hash, run", review.count("ssh") == 4 and "cat /tmp/mpc-store.sh" in review and "sha256sum" in review, review)
    check("hash line shown", len(pg.locator("#hashline").text_content()) > 60)
    more = pg.locator("#cmd-more").text_content()
    check("other commands", "mpc-store.sh list" in more and "update" in more and "sync" in more and "prune --keep 10" in more)
    pg.screenshot(path=SHOTS + "/shot-desktop.png", full_page=False)
    pg.locator("[data-pick]").nth(0).uncheck(); pg.locator("[data-pick]").nth(0).evaluate("e => e.blur()")
    picks.nth(1).uncheck()
    check("panel hides when nothing is selected", pg.locator("#inst").is_hidden())
    # preload from the URL, and a hostile value
    pg.goto(URL + "#sel=" + ids[2] + ",<script>alert(1)</script>,nope,monomodule")
    pg.reload()
    check("preselected from the link, junk ignored", pg.locator("[data-pick]:checked").count() == 1 and pg.locator("#inst-count").text_content() == "1 plugin selected")
    check("no script ran", not errors, str(errors))
    # MPC OS row and filter (docs/OS2_SKINS.md): they must agree, whatever the catalog holds (a catalog built before the field has none).
    # 3.x is the standard, so the only badge is "MPC OS 2.x tested", on a 2.x-capable version with a 2.x device test.
    pg.goto(URL)
    check("MPC OS filter exists", pg.locator("#f-os").count() == 1)
    pg.select_option("#f-tier", "all")   # the fixture's 3.x-only plugin is experimental, hidden by default
    for val, row in (("2x", "2.x and 3.x"), ("3x", "3.x only")):
        pg.select_option("#f-os", val)
        cards = pg.locator("#grid article.card")
        wrong = [i for i in range(cards.count()) if row not in (cards.nth(i).locator("dl.meta").text_content() or "")]
        check("filter %s shows only cards whose MPC OS row matches" % val, cards.count() >= 1 and not wrong, "%d cards, wrong %s" % (cards.count(), wrong))
    pg.select_option("#f-os", index=0)
    pg.select_option("#f-tier", index=0)
    os_tags = pg.locator("#grid .tag").filter(has_text="MPC OS")
    check("no 3.x badge; the only MPC OS badge is '2.x tested'", os_tags.count() >= 1 and set(os_tags.all_text_contents()) == {"MPC OS 2.x tested"},
          str(os_tags.all_text_contents()))
    # Gen2 (docs/GEN2.md): the badge, the filter and the two download buttons come from the version's gen2 flag and assets{}
    pg.goto(URL)
    check("device filter exists", pg.locator("#f-gen").count() == 1)
    gen2_cards = pg.locator("#grid article.card:has(.tag.gen)").count()
    for val, want in (("gen2", True), ("gen1", False)):
        pg.select_option("#f-gen", val)
        cards = pg.locator("#grid article.card")
        wrong = [i for i in range(cards.count()) if (cards.nth(i).locator(".tag.gen").count() == 1) != want]
        check("device filter %s shows only the matching cards" % val, not wrong, str(wrong))
        if val == "gen2":
            check("the Gen2 filter shows the cards that have the badge", cards.count() == gen2_cards, "%d vs %d" % (cards.count(), gen2_cards))
            if cards.count():
                check("a Gen2 card has both download buttons",
                      cards.first.locator("a.btn-l:has-text('Gen1')").count() == 1 and cards.first.locator("a.btn-l:has-text('Gen2')").count() == 1)
    pg.select_option("#f-gen", index=0)
    # Trust tiers: experimental is hidden by default, shown by the Tier filter or "Show them"; Recommended puts featured, then Verified, first.
    pg.goto(URL); pg.reload()
    pg.select_option("#f-tier", "all")
    names = pg.locator("#grid article.card h2").all_inner_texts()
    tiers = pg.locator("#grid article.card").evaluate_all("e => e.map(x => x.getAttribute('data-tier'))")
    rank = {"verified": 0, "listed": 1, "experimental": 2}
    check("every card carries a tier", len(tiers) == len(names) and len(names) > 0, str(tiers))
    check("Listed has no badge; Verified and Experimental do", pg.locator("#grid article[data-tier=listed] .tag[class*=tier-]").count() == 0
          and pg.locator("#grid article[data-tier=verified] .tag.tier-verified").count() >= 1)
    check("Recommended sorts by tier", [rank[t] for t in tiers] == sorted(rank[t] for t in tiers), str(tiers))
    # Verified is split by device generation: one badge per generation, and a Tier filter option for each
    both = pg.locator("#grid article:has(h2:has-text('Tested Two')) .tag.tier-verified").all_text_contents()
    check("a plugin tested on both generations has two Verified badges", both == ["Verified Gen1", "Verified Gen2"], str(both))
    for val, gen in (("verified-gen1", "gen1"), ("verified-gen2", "gen2")):
        pg.select_option("#f-tier", val)
        cards = pg.locator("#grid article.card")
        wrong = [i for i in range(cards.count()) if cards.nth(i).locator(".tag.tier-verified[data-gen=%s]" % gen).count() != 1]
        check("Tier filter %s shows only cards with that badge" % val, cards.count() >= 1 and not wrong, "%d cards, wrong %s" % (cards.count(), wrong))
    pg.select_option("#f-tier", index=0)
    check("experimental plugins are hidden by default", pg.locator(".tag.tier-experimental").count() == 0)
    check("the hidden-experimental note offers them", pg.locator("#exp").is_visible())
    pg.click("#show-exp")
    check("Show them reveals experimental plugins", pg.locator(".tag.tier-experimental").count() >= 1)
    pg.select_option("#f-tier", index=0)
    check("only a plugin missing something shows 'To improve'", pg.locator("#grid details.how:has-text('To improve')").count() == 1)
    # Screenshot popup: the image opens the whole card over a dark backdrop, with its own link (#...&p=<id>)
    pg.goto(URL); pg.reload()
    pg.wait_for_function("!document.querySelector('#grid article[data-tier] a.shot[data-open=tested-two]')")
    check("a card with a screenshot shows it", pg.locator("#grid a.shot[data-open=test-synth] img").count() == 1)
    check("a card without one has no frame", pg.locator("#grid article:has(h2:has-text('Old Catalog')) .shot").count() == 0)
    check("a dead screenshot link leaves no empty frame", pg.locator("#grid article:has(h2:has-text('Tested Two')) .shot").count() == 0)
    shot = pg.locator("#grid a.shot[data-open=test-synth]")
    shot.click()
    check("clicking the screenshot opens the popup", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Test Synth")
    check("the popup has its own link", "p=test-synth" in pg.evaluate("location.hash"), pg.evaluate("location.hash"))
    check("focus moves to Close", pg.evaluate("document.activeElement.id") == "modal-x")
    check("the page behind does not scroll", pg.evaluate("getComputedStyle(document.body).overflow") == "hidden")
    pg.keyboard.press("Escape"); pg.wait_for_function("document.getElementById('modal').hidden")   # closing goes through history.back(), which is async
    check("Escape closes it and drops p= from the link", pg.locator("#modal").is_hidden() and "p=" not in pg.evaluate("location.hash"))
    check("focus returns to the screenshot", pg.evaluate("document.activeElement.getAttribute('data-open')") == "test-synth")
    shot.click(); pg.go_back(); pg.wait_for_function("document.getElementById('modal').hidden")
    check("Back closes it", pg.locator("#modal").is_hidden())
    shot.click(); pg.mouse.click(5, 450); pg.wait_for_function("document.getElementById('modal').hidden")
    check("a click on the backdrop closes it", pg.locator("#modal").is_hidden())
    pg.locator("#grid article:has(h2:has-text('Old Catalog')) h2 a.open").click()
    check("the title opens the popup too, also on a card without a screenshot",
          pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Old Catalog" and "p=old-catalog" in pg.evaluate("location.hash"))
    check("the popup's own title is not a link", pg.locator("#modal h2 a").count() == 0)
    pg.keyboard.press("Escape"); pg.wait_for_function("document.getElementById('modal').hidden")
    check("focus returns to the title", pg.evaluate("document.activeElement.className") == "open" and pg.locator("#modal").is_hidden())
    pg.goto(URL + "#p=test-synth"); pg.reload()
    check("the link opens the popup", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Test Synth")
    pg.wait_for_timeout(300)
    check("the popup's picture loads", pg.evaluate("(document.querySelector('#modal .shot img') || {}).naturalWidth") == 1)
    pg.locator("#modal [data-pick]").check()
    check("ticking in the popup ticks the card", pg.locator("#grid [data-pick=test-synth]").is_checked() and "sel=test-synth" in pg.evaluate("location.hash"))
    pg.evaluate("navigator.clipboard.writeText = function (t) { window.copied = t; return Promise.resolve(); }")
    pg.click("#modal-share")
    check("Copy link copies the share page's address", (pg.evaluate("window.copied") or "").endswith("/p/test-synth.html")
          and pg.locator("#modal-share").text_content() == "Link copied", str(pg.evaluate("window.copied")))
    # on a touch device Copy link opens the system share sheet instead of the clipboard
    pg.evaluate("window.matchMedia = function () { return { matches: true }; }; navigator.share = function (d) { window.shared = d; return Promise.resolve(); }")
    pg.evaluate("window.copied = null"); pg.click("#modal-share")
    check("on a touch device Copy link opens the share sheet with the share page's address",
          (pg.evaluate("(window.shared || {}).url") or "").endswith("/p/test-synth.html") and pg.evaluate("window.shared.title") == "Test Synth"
          and pg.evaluate("window.copied") is None, str(pg.evaluate("window.shared")))
    pg.click("#modal-x"); pg.wait_for_function("document.getElementById('modal').hidden")
    check("Close closes a popup opened from a link", pg.locator("#modal").is_hidden() and "p=" not in pg.evaluate("location.hash"))
    for junk in ("nope", "<img src=x onerror=alert(1)>", "../test-synth"):
        pg.goto(URL + "#p=" + junk); pg.reload()
        check("p=%s opens nothing" % junk, pg.locator("#modal").is_hidden())
    # Share pages (catalog_site.py share_page): link previews read Open Graph tags from p/<id>.html, and a browser goes on to the popup
    site = os.path.dirname(sys.argv[1])
    share = open(os.path.join(site, "p", "test-synth.html"), encoding="utf-8").read()
    og = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', share))
    check("share page has the card's Open Graph tags", og.get("og:title") == "Test Synth by A" and og.get("og:image") == "https://shots.invalid/test-synth.png"
          and og.get("twitter:card") == "summary_large_image" and "og:description" in og, str(og))
    og = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', open(os.path.join(site, "p", "old-catalog.html"), encoding="utf-8").read()))
    check("without a screenshot: no og:image, small card", "og:image" not in og and og.get("twitter:card") == "summary", str(og))
    check("share page does not use a meta refresh (crawlers would follow it)", "http-equiv" not in share)
    check("the card links point at the share page", pg.locator("#grid a.shot[data-open=test-synth]").get_attribute("href") == "p/test-synth.html")
    pg.goto("file://" + os.path.join(site, "p", "test-synth.html"))
    pg.wait_for_url(re.compile(r"index\.html#p=test-synth$"))
    check("the share page opens the popup", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Test Synth")
    check("no script errors", not errors, str(errors))
    m = b.new_page(viewport={"width": 390, "height": 800}, device_scale_factor=2)
    m.goto(URL + "#sel=" + ids[0]); m.reload()
    m.locator("#inst > summary").click(); m.fill("#ip", "192.168.1.20")
    m.screenshot(path=SHOTS + "/shot-phone.png")
    over = m.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    check("no horizontal scroll on a phone", not over)
    b.close()
print("FAILED: %s" % fails if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
