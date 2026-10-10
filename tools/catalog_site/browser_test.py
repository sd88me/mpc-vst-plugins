"""Browser test of the catalog page's install list (tools/catalog_site/index.template.html): tick plugins, get the command, refuse a
bad address, keep the selection in the link, no horizontal scroll on a phone. Needs Playwright, which the html_art image has:

  python3 tools/catalog_site.py --out /tmp/site
  docker build -q -t mpc-vst-html-art tools/html_art
  docker run --rm -v /tmp:/w -v "$PWD/tools/catalog_site":/t -w /w mpc-vst-html-art python3 /t/browser_test.py /w/site/index.html /w

The last two arguments are the built page and a folder for two screenshots (shot-desktop.png, shot-phone.png)."""
import sys
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
    # MPC OS badge and filter (docs/OS2_SKINS.md): they must agree, whatever the catalog holds (a catalog built before the field has none)
    pg.goto(URL)
    check("MPC OS filter exists", pg.locator("#f-os").count() == 1)
    for val, badge in (("2x", ".tag.ok"), ("3x", ".tag.warn:has-text('MPC OS 3.x only')")):
        pg.select_option("#f-os", val)
        cards = pg.locator("article.card")
        wrong = [i for i in range(cards.count()) if cards.nth(i).locator(badge).count() != 1]
        check("filter %s shows only cards with the matching badge" % val, not wrong, str(wrong))
    pg.select_option("#f-os", index=0)
    ok_tags = pg.locator(".tag.ok")
    if ok_tags.count():
        check("a 2.x badge says what it is", "2.x" in ok_tags.first.text_content() and ok_tags.first.get_attribute("title"))
    # Gen2 (docs/GEN2.md): the badge, the filter and the two download buttons come from the version's gen2 flag and assets{}
    pg.goto(URL)
    check("device filter exists", pg.locator("#f-gen").count() == 1)
    gen2_cards = pg.locator("article.card:has(.tag.gen)").count()
    for val, want in (("gen2", True), ("gen1", False)):
        pg.select_option("#f-gen", val)
        cards = pg.locator("article.card")
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
    tiers = pg.locator("#grid article.card .tag[class*=tier-]").evaluate_all("e => e.map(x => x.className.replace('tag tier-', ''))")
    rank = {"verified": 0, "listed": 1, "experimental": 2}
    check("every card shows a tier", len(tiers) == len(names) and len(names) > 0, str(tiers))
    check("Recommended sorts by tier", [rank[t] for t in tiers] == sorted(rank[t] for t in tiers), str(tiers))
    pg.select_option("#f-tier", index=0)
    check("experimental plugins are hidden by default", pg.locator(".tag.tier-experimental").count() == 0)
    check("the hidden-experimental note offers them", pg.locator("#exp").is_visible())
    pg.click("#show-exp")
    check("Show them reveals experimental plugins", pg.locator(".tag.tier-experimental").count() >= 1)
    pg.select_option("#f-tier", index=0)
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
