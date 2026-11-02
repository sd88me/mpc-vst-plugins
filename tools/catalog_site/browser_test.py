"""Browser test of the catalog page's install list (tools/catalog_site/index.template.html): tick plugins, get the command, refuse a
bad address, keep the selection in the link, the screenshot popup and its link, no horizontal scroll on a phone. Needs Playwright, which the html_art image has:

  python3 tools/catalog_site.py --catalog tools/catalog_site/fixture-catalog.json --out /tmp/site
  docker build -q -t mpc-vst-html-art tools/html_art
  docker run --rm -v /tmp:/w -v "$PWD/tools/catalog_site":/t -w /w mpc-vst-html-art python3 /t/browser_test.py /w/site/index.html /w

The last two arguments are the built page and a folder for the screenshots (shot-desktop.png, shot-phone.png, shot-collection-card.png,
shot-collection-view.png). Also covers collections: one card per collection, per-tab counts, search, the #c= view with Pick all, share pages."""
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
    # "Newest in catalog" sorts by when the entry was added (catalog/added.json), newest first, not by release date
    import json
    fixture = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture-catalog.json")))
    # one card per plugin outside a collection, one per collection (its "added" is its oldest member's)
    cards = [(x["added"], x["name"]) for x in fixture["plugins"] if not x.get("collection")] + [(c["added"], c["title"]) for c in fixture["collections"]]
    want = [n.upper() for _, n in sorted(cards, key=lambda t: t[0], reverse=True)]
    pg.select_option("#sort", "added")
    got = [t.upper() for t in pg.locator("#grid article.card h2").all_inner_texts()]
    check("Newest in catalog sorts by date added, newest first", got == want, "%s vs %s" % (got, want))
    pg.select_option("#sort", index=0)
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
    # Collections (docs/CATALOG.md): the fixture's five acme/pack plugins are one card (Pack Drive is experimental, a beta only)
    pg.goto(URL); pg.reload()
    coll = pg.locator("#grid article.coll")
    check("a collection is one card", coll.count() == 1 and coll.locator("h2").text_content() == "Acme Pack", str(coll.count()))
    check("its members get no card of their own", pg.locator("#grid article:not(.coll) h2").filter(has_text="Pack ").count() == 0)
    check("the card has the Collection badge, the best member tier and the kind counts",
          coll.locator(".tag.coll").text_content() == "Collection" and coll.get_attribute("data-tier") == "verified"
          and coll.locator(".tag.tier-verified").all_text_contents() == ["Verified Gen1"]
          and coll.locator(".counts").text_content() == "1 instrument \u00b7 1 MIDI plugin \u00b7 3 effects", coll.locator(".counts").text_content())
    chips = lambda: coll.locator(".chip:not(.more)").all_text_contents()
    check("first members as chips, the experimental one hidden by default, no match line", sorted(chips()) == ["Pack Gate", "Pack Kick", "Pack Seq", "Pack Verb"]
          and coll.locator(".chip.more").count() == 0 and coll.locator(".matchline").count() == 0, str(chips()))
    check("the count line counts plugins, members included", pg.locator("#count").text_content().startswith("7 of 9 "), pg.locator("#count").text_content())
    pg.select_option("#f-tier", "all")
    check("more members than chips: +N", len(chips()) == 4 and coll.locator(".chip.more").text_content() == "+1")
    pg.select_option("#f-tier", index=0)
    check("the card links to the collection page and the repo", coll.locator("a.btn-l", has_text="View all").get_attribute("href") == "p/c/acme-pack.html"
          and coll.locator("a.btn-l", has_text="Source").get_attribute("href") == "https://github.com/acme/pack")
    for tab, counts, names in (("instrument", "1 instrument", ["Pack Kick"]), ("midi", "1 MIDI plugin", ["Pack Seq"]), ("effect", "3 effects", ["Pack Gate", "Pack Verb"])):
        pg.click("#tab-" + tab)
        check("tab %s: the card shows with that kind's members only" % tab, coll.count() == 1 and coll.locator(".counts").text_content() == counts
              and sorted(chips()) == names, "%s %s" % (coll.locator(".counts").all_text_contents(), chips()))
    pg.click("#tab-addin")
    check("not under a kind it does not cover", coll.count() == 0)
    pg.click("#tab-all")
    check("tab counts count the members", pg.locator("#n-effect").text_content() == "3" and pg.locator("#n-midi").text_content() == "1", pg.locator("#n-effect").text_content())
    pg.fill("#q", "shimmer")
    check("a search that matches a member surfaces the card with that member", coll.count() == 1 and chips() == ["Pack Verb"]
          and coll.locator(".matchline").text_content().startswith("1 of 5 match"), str(chips()))
    pg.fill("#q", "acme pack")
    check("a search for the collection's title shows all its members", coll.count() == 1 and len(chips()) == 4)
    pg.fill("#q", "drum")
    check("a word in its summary lists only the members that match", coll.count() == 1 and chips() == ["Pack Kick"]
          and coll.locator(".matchline").text_content().startswith("1 of 5 match"), str(chips()))
    pg.fill("#q", "every acme plugin")
    check("its summary alone does not surface it", coll.count() == 0)
    pg.fill("#q", "nothing like this")
    check("a search matching no member hides it", coll.count() == 0)
    pg.fill("#q", ""); pg.select_option("#f-dev", "Acme")
    check("filters apply to members", coll.count() == 1 and pg.locator("#grid article").count() == 1)
    pg.select_option("#f-dev", index=0); pg.dispatch_event("#f-dev", "change")
    pg.select_option("#sort", "downloads")
    check("sorted by its members' total downloads", pg.locator("#grid article.card").first.get_attribute("class") == "card coll")
    pg.select_option("#sort", index=0)
    tiers = pg.locator("#grid article.card").evaluate_all("e => e.map(x => x.getAttribute('data-tier'))")
    check("Recommended places it by its best member tier", [rank[t] for t in tiers] == sorted(rank[t] for t in tiers) and tiers.index("verified") == 0, str(tiers))
    # the collection view: members by kind, ticks and Pick all feed the install list
    coll.locator("a.btn-l", has_text="View all").click()
    check("View all opens the collection view with its own link", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Acme Pack"
          and "c=acme-pack" in pg.evaluate("location.hash"), pg.evaluate("location.hash"))
    heads = pg.locator("#modal .cgroup h3").all_text_contents()
    check("members grouped by kind", heads == ["Instruments (1)", "MIDI (1)", "Effects (3)"], str(heads))
    check("every member is listed, experimental too, with a badge", pg.locator("#modal .member").count() == 5
          and pg.locator("#modal .member:has-text('Pack Drive') .tag.tier-experimental").count() == 1)
    check("a member without a stable release has no checkbox", pg.locator("#modal [data-pick=pack-drive]").count() == 0 and pg.locator("#modal [data-pick]").count() == 4)
    pg.click("#modal [data-pickall=effect]")
    sel = pg.evaluate("location.hash").replace("%2C", ",")
    check("Pick all ticks the group's installable members", pg.locator("#modal [data-pick=pack-gate]").is_checked() and pg.locator("#modal [data-pick=pack-verb]").is_checked()
          and "pack-gate" in sel and "pack-verb" in sel and pg.locator("#modal [data-pickall=effect]").text_content() == "Unpick all", sel)
    check("the install list has them", pg.locator("#inst-count").text_content() == "2 plugins selected" and "pack-verb" in pg.locator("#cmd-main").text_content())
    pg.locator("#modal [data-pick=pack-kick]").check()
    check("a single tick joins the list", pg.locator("#inst-count").text_content() == "3 plugins selected")
    pg.click("#modal [data-pickall=effect]")
    check("Unpick all clears the group only", pg.locator("#inst-count").text_content() == "1 plugin selected" and pg.locator("#modal [data-pickall=effect]").text_content() == "Pick all")
    pg.evaluate("navigator.clipboard.writeText = function (t) { window.copied = t; return Promise.resolve(); }; window.matchMedia = function () { return { matches: false }; }")
    pg.click("#modal-share")
    check("Copy link copies the collection page", (pg.evaluate("window.copied") or "").endswith("/p/c/acme-pack.html"), str(pg.evaluate("window.copied")))
    pg.click("#modal .member a.nm:has-text('Pack Verb')")
    check("a member opens its own popup, with the breadcrumb", pg.locator("#modal h2").text_content() == "Pack Verb"
          and pg.locator("#modal .crumb").text_content() == "Part of Acme Pack" and "p=pack-verb" in pg.evaluate("location.hash"))
    pg.keyboard.press("Escape"); pg.wait_for_function("document.querySelector('#modal h2') && document.querySelector('#modal h2').textContent === 'Acme Pack'")
    check("Escape goes back to the collection", pg.locator("#modal").is_visible() and "p=" not in pg.evaluate("location.hash"))
    pg.keyboard.press("Escape"); pg.wait_for_function("document.getElementById('modal').hidden")
    check("and Escape again closes it", "c=" not in pg.evaluate("location.hash") and pg.locator("#grid [data-coll]").count() >= 1)
    coll.locator(".chip", has_text="Pack Kick").click()
    check("a chip opens the member's popup", pg.locator("#modal h2").text_content() == "Pack Kick")
    pg.click("#modal .crumb a")
    check("the breadcrumb opens the collection", pg.locator("#modal h2").text_content() == "Acme Pack" and "c=acme-pack" in pg.evaluate("location.hash")
          and pg.locator("#modal [data-pick=pack-kick]").is_checked())
    pg.keyboard.press("Escape"); pg.wait_for_function("document.querySelector('#modal h2') && document.querySelector('#modal h2').textContent === 'Pack Kick'")
    check("Escape steps back through the history: the member first", pg.locator("#modal").is_visible() and "c=" not in pg.evaluate("location.hash"))
    pg.keyboard.press("Escape"); pg.wait_for_function("document.getElementById('modal').hidden")
    pg.goto(URL + "#c=acme-pack"); pg.reload()
    check("a #c= link opens the collection view", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Acme Pack")
    for junk in ("nope", "<b>x</b>", "pack-kick"):
        pg.goto(URL + "#c=" + junk); pg.reload()
        check("c=%s opens nothing" % junk, pg.locator("#modal").is_hidden())
    cshare = open(os.path.join(site, "p", "c", "acme-pack.html"), encoding="utf-8").read()
    og = dict(re.findall(r'<meta (?:property|name)="([^"]+)" content="([^"]*)"', cshare))
    check("collection share page: Open Graph tags, a member's screenshot, members by kind", og.get("og:title") == "Acme Pack by Acme"
          and og.get("og:image") == "https://shots.invalid/pack-kick.png" and "http-equiv" not in cshare
          and re.findall(r"<h2>([^<]+)</h2>", cshare) == ["Instruments (1)", "MIDI (1)", "Effects (3)"] and 'href="../pack-verb.html"' in cshare, str(og))
    mshare = open(os.path.join(site, "p", "pack-verb.html"), encoding="utf-8").read()
    check("a member's share page says which collection it is part of", 'Part of <a href="c/acme-pack.html">Acme Pack</a>' in mshare)
    check("a plugin outside a collection has no breadcrumb", "Part of" not in share)
    pg.goto("file://" + os.path.join(site, "p", "c", "acme-pack.html"))
    pg.wait_for_url(re.compile(r"index\.html#c=acme-pack$"))
    check("the collection share page opens the collection view", pg.locator("#modal").is_visible() and pg.locator("#modal h2").text_content() == "Acme Pack")
    pg.goto(URL); pg.reload()
    pg.screenshot(path=SHOTS + "/shot-collection-card.png", full_page=True)
    coll.locator("a.btn-l", has_text="View all").click()
    pg.screenshot(path=SHOTS + "/shot-collection-view.png")
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
