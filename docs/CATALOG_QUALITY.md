# Catalog quality plan (decided 2026-10-10)

Why: the catalog is growing fast, and some contributors bulk-convert open-source projects into it. Quality varies and
there is nobody with the time to review every entry. Goal: keep the registry open to everyone, but make the front of
the catalog earned by evidence, at almost no cost to the maintainer.

## Status and handoff (2026-10-11)
**Live on the site:** Verified / Listed / Experimental tiers (Listed shows no badge; the Tier filter calls it "Not yet verified"),
"Recommended" default sort, the collapsed "To improve this listing" list on each card, and `tested.json` for all of the maintainer's
own plugins (Force, MPC OS 3.9.1, recorded 2026-10-10; 56 Verified, 50 Listed, 1 Experimental at the last build). PRs #267, #271 and #382.
**Posted:** the Step 2 announcement went out on 2026-10-10 (Discord / community). No negative feedback so far. A one-line follow-up
("Listed is now just in the catalog, no badge") is the maintainer's to add to the thread.
**Not started:** Steps 3 to 5 below. Step 3 is on hold on purpose until the maintainer decides, after the community has had a few days.

### Community signals: under discussion (2026-11-04)
With 200+ plugins listed, the maintainer asked the community whether to add feedback on top of the tiers. Posted on Discord and Facebook
on 2026-11-04 as questions only. **Nothing is built and nothing is decided; wait for the replies before starting.** Details below
("Community signals proposal").

### What to do next, in order
1. **Tidy-ups that need no decision** (do any time):
   - Fix the 5 stale checks in `tools/catalog_site/browser_test.py` (filter 2x/3x, device gen2, Gen2 card, Gen2 buttons): they count
     `article.card` across all tabs; scope them to `#grid`. They fail on `main`, so the site has less test coverage than it looks.
   - Add an optional registry field `upstream` (link and licence of the project a port is converted from), shown on the card. It is the
     missing bar item for bulk ports (`check_entry`, `catalog_build.py`; document in `catalog/README.md` and `docs/CATALOG_SPEC.md`).
   - Look at the 2 plugins with a CPU `FAIL` verdict (`bar_missing` contains `cpu-fail` in `catalog.json`) and contact the authors.
   - 78 plugins have no CPU bench figure. If that stays noisy, drop `cpu-bench` from `BAR` or label it optional.
2. **Step 3 (decision first):** new registry entries start as Experimental.
   - Decide: cap any existing weak bulk ports now (`"tier": "experimental"` in their registry files, one commit)? The maintainer names them.
   - Registry PR check (`tools/catalog_build.py --check-registry`, run by `catalog.yml`): a *new* entry must carry `"tier": "experimental"`
     (compare against `origin/main` so existing entries are not forced). Update the PR template and the "Add my plugin" issue template.
   - Promotion: automatic when the bar is met (decide the rule: for example screenshot + skin + stable release + CPU not FAIL, then a
     maintainer-free path to remove the cap, such as a PR that only deletes the `tier` line and that CI checks), or on request through an
     issue template; a maintainer spot-checks one plugin only when asked.
   - Announce first (a post, a go-live date), then merge.
3. **Step 4 (when trusted people exist):** a `verifiers` list (named GitHub handles) whose compatibility reports count toward Verified; per-plugin
   compatibility report thread or issue template ("works / doesn't work on device + OS"). Start with the maintainer alone.
4. **Step 5 (only if people ask):** abandonment and delisting policy (entries are pointers; notice, then move down or remove), a within-tier
   tiebreaker (reactions, "N people use this"), a hand-picked Featured row (`"featured": true` already works).

### Gotchas for whoever continues
- Verified needs a `tested.json` entry for the *newest stable* version, so every release by an author resets it to unverified until they add a
  line. That is intended, but say so in the announcement follow-up.
- The tier is computed in `tier_of` in `tools/catalog_build.py`; the registry can only cap it (`"tier": "experimental"`).
- `tools/catalog_site/fixture-catalog.json` drives `tools/catalog_site/browser_test.py`; update it when `catalog.json` gains fields.
- The catalog rebuilds nightly; run the "Catalog build" workflow (`gh workflow run catalog.yml`) after merging site changes to publish at once.

## Principles
1. **Gate prominence, not entry.** Anyone can list a plugin. What is evidenced is shown higher.
2. **Evidence over opinion.** Tiers come from things anyone can check (a recorded device test, a passing check), not from votes.
3. **No new maintainer workload by default.** Nothing needs a human review until a person asks for one, and a person asking is optional.
4. **Informational first, hiding later.** Show people what is missing before anything is hidden or demoted.
5. **Say it before doing it.** Each step is announced to contributors before it takes effect.

## The tiers (live in PR #267; see CATALOG.md "Trust tiers")
- **Verified:** the newest stable release has a `tested.json` entry (device, OS version, date) in the plugin's own repo. Shown per
  generation since 2026-10-12: "Verified Gen1" (a Gen1 device) and "Verified Gen2" (a device naming Gen2, on a release with a Gen2 build); since 2026-11-05 also
  "Verified Sample" (an MPC Sample, on a release with a Gen2 build), and an entry limited to the Sample (`devices`) is asked for that test only.
- **Listed:** a valid release that passed the catalog's release checks; no recorded test for the newest release. Shown with no badge (since 2026-10-11): in the catalog and not Verified means Listed.
- **Experimental:** no stable release yet, or capped by a maintainer (`"tier": "experimental"` in the registry entry). Hidden from the default view.
- Default sort "Recommended": featured, then Verified, then Listed. Within Verified (2026-11-05, offline; replaces the 2026-10-14
  "both generations before one" rule): a plugin whose every shipped generation is verified first (so a Gen1-only build tested on Gen1
  equals a dual build tested on both), then a dual build verified on one generation only.
  **Changed the same day (maintainer decision 2026-11-05):** the ranking is evidence points, not tiers: complete Verified 3, partly verified
  1.5, Listed 0, plus community points when the preview is on (each person reporting the newest release working 1, only an older release
  0.25, each like 0.1). So 4 people confirming a Listed plugin beat a Verified badge with no reports, 2 do not; experimental is always last.
  Reasoning: a badge is one person's record (usually the author's) of one device, several independent confirmations are broader. Risks
  noted: a new plugin starts at 0 and ranks below older ones until reports arrive; reports must come from real sign-ins (Discord, Google, one
  person once); reports of an older release count a quarter so an update does not inherit full credit. This reverses the earlier "community
  counts never lift a plugin" principle for the Recommended sort only: the Verified badge and tier are unchanged, and the card still says
  community reports are not hardware verification. Revisit the weights (3, 1, 0.25, 0.1) once there is real data. A collection takes its best matching member's score, not the members' sum. A collection card (docs/CATALOG.md, "Collections") sorts by the
  best tier among its shown members and its members' total downloads (live 2026-11-02).
- Rejected on purpose (2026-10-10): star ratings, comments, upvotes as a quality signal (few users, needs a backend and moderation).
  Revisited 2026-11-04 now that there are 200+ plugins: stars stay rejected, but a separate "reported working" count and likes are
  proposed (see "Community signals proposal"). Neither would change a tier.

## Steps
Each step stands alone. Stop after any of them.

### Step 0: done
- [x] Tiers computed by `tools/catalog_build.py`, badges, Tier filter, Recommended sort, tests, docs (PR #267, offline).
- [x] `tested.json` added for every plugin of the maintainer's own repos (Force, MPC OS 3.9.1, 2026-10-10), so they become Verified on the first build.
- [ ] Merge PR #267 and run the catalog workflow once. Check the result against expectations (about 36 + 15 Verified, one Experimental).

### Step 1 (soft start): make the bar visible, change nothing (built 2026-10-10, offline; live after the next catalog build)
"Meets the bar" is what CI can check, shown without hiding or demoting anything:
- [x] stable release, screenshot, a skin (instruments and effects), CPU verdict not FAIL, a CPU bench figure, a `tested.json` entry.
      The skin and release checks themselves already gate the zip, so "skin" here only means the zip ships one.
- [x] Each card has a collapsed "To improve this listing" list; the build log counts plugins missing each item.
- [x] `catalog/README.md` explains the list ("Improve your listing") and how to get Verified.
- [ ] Not in the bar yet: "ports name their upstream and licence" (no registry field says a plugin is a port; add an optional
      `upstream` field first), and `catalog_check.py` printing the list to authors (it does not see the registry entry).
- No tier changes. This only tells people what is coming.

### Step 2: announce (draft below; post it only when you are ready)
- Post to the community (Discord and a pinned GitHub Discussion) what the tiers mean, how to move up (add `tested.json`, meet the bar),
  and what changes next. Contributors with existing entries hear it first and get a chance to fix them.

### Step 3: new entries start as Experimental
- A registry PR check requires `"tier": "experimental"` on a new entry. The existing entries stay as they are.
- Promotion is automatic once the Step 1 bar passes, or on request: the contributor opens an issue from a template and a
  maintainer spot-checks one plugin when they have time. Nothing waits on a review that nobody asked for.
- Cap weak existing bulk ports as Experimental if the maintainer names them (optional, one commit).

### Step 4: when trusted people exist
- A small `verifiers` list (named GitHub handles). A compatibility report from a listed verifier counts toward Verified,
  in addition to the author's own `tested.json`. Start with the maintainer alone.
- Compatibility reports through GitHub Discussions or an issue template ("works / doesn't work on device + OS").

### Step 5: only if people ask
- Abandonment and delisting policy: entries are pointers to the author's repo; broken or abandoned ones are noticed and
  then moved down or removed.
- Losing Verified (decided 2026-10-11, not built): a confirmed "doesn't work" report on the newest stable version (an issue
  or Discussion, reproduced by the maintainer or a listed verifier) drops the plugin to Listed until a fixed release, or a
  new `tested.json` entry, wins it back. No time-based expiry: an unchanged plugin does not get worse with age. (A new
  release without a `tested.json` entry already drops to Listed today.)
- A within-tier tiebreaker (reactions or "N people use this"), never a way into a higher tier.
- A hand-picked Featured row (`"featured": true`, already supported).

## Community signals proposal (2026-11-04, research only, nothing built)
Context: Step 4 (compatibility reports) and Step 5 (tiebreaker) were already planned. Two other community catalogs were studied;
what is below comes from their public pages and the Modwerk repo (source read, not run). Not measured on any device.

**What others do**
- *Firmware Hub* (FM-1 firmware, thefirmwarehub.com): gates entry (maintainer review, real-device test required, open source or a
  link card), 1-5 star ratings with a count, "Top rated" default sort, favourites and wishes, optional passwordless emailed-link
  account, installing needs no account. Their rating details beyond that are not on the page.
- *Modwerk* (Elektron modules, modwerk.app, github.com/repeat98/modwerk): two separate signals per card, **reported working** (the
  tick count: distinct members who confirmed it, across versions, tooltip says it is not hardware qualification) and **likes** (heart),
  each with its own sort ("Most reported working", "Most liked"). Also downloads, "In regular use", estimated load gauges, per-module
  Discussion and Issues tabs, Follow updates, Bookmark, a "Works for me" and a "Report an issue" button. Needs a verified account to
  post, like or report; everyone can read.
- Modwerk's backend is a Cloudflare Worker + D1 (SQLite) with Better Auth. Working reports are unique per (user, module, context),
  where context is device + OS + module versions; a quick press stores the catalog version at that moment and does not claim the user
  tested it. Public bugs go to GitHub as the single tracker (private details kept on the site, only the agreed public fields
  mirrored), with webhooks notifying the reporter. Per-IP and per-member throttles. **Its backend is Elastic-2.0 licensed: study
  the design, do not copy code.**

**Proposed for us (a proposal, awaiting replies)**
1. "Works on my device": device + OS + plugin version, one per person per plugin and context, shown as "N people report working".
   Sits beside the tier, never changes it, labelled as not hardware qualification. Reports are tied to a version.
2. Likes: browsing and sorting only (the Step 5 tiebreaker), never a way into a higher tier.
3. "Report an issue": a pre-filled link (device, OS, plugin version) to the plugin's repo.
4. No star ratings (scores bunch at the top, and they measure taste, not "does it load on my MPC").
5. Verified stays exactly as it is (author's `tested.json`).

**Why not GitHub-only voting:** most MPC users have no GitHub account, so counts would be tiny and skewed to developers. Decided
2026-11-04 that a small service with its own sign-in is needed if this goes ahead.

**Sign-in:** Discord and Google (Gmail) first, an emailed link only if people ask. Discord and Google need no outgoing mail. Link
accounts by verified email so one person counts once; a Discord user without a verified email could double-count via Google.
Optional rule to consider: only Discord or Google accounts (or aged email accounts) count toward the public number.
Better Auth supports these providers per Modwerk's use of it; its current docs and Google's OAuth consent-screen setup for outside
users were **not** checked.

**Cost (searched 2026-11-04, official docs where noted, not tested):** about $0 at our size.
- Cloudflare Workers Free: 100,000 requests/day. D1 Free: 5M rows read/day, 100k rows written/day, 5 GB total and 500 MB per
  database. Since 2026-09-01 D1 queries on the free plan **fail** after the daily limit until midnight UTC, so vote and count queries
  need indexes (a 5,000-row scan counts as 5,000 reads).
- Email path only, if added: Resend free is 100 emails/day and 3,000/month, Brevo free is 300/day (adds a footer). A sending domain
  (about $10-15 a year, unless the catalog already has one) is needed for deliverability. Skipped entirely with Discord/Google only.
- The real cost is maintainer time: abuse handling, hiding a bad report, deleting an account on request.

**Posted 2026-11-04** (Discord discussion, shortened to Facebook): the idea, the three sign-in options, and six questions (would you
use it and sign in with Discord/Google; likes as well; need email; follow a plugin for updates; anyone to moderate or verify;
anything you would rather not see). The post says that if most prefer the catalog as it is, it stays as it is.

**Update 2026-11-05:** replies were positive, so the buildable design is drafted in `docs/COMMUNITY_SIGNALS.md` (architecture,
D1 schema, endpoints, counting rules, build order). Still nothing built; its "Open questions" need the maintainer first.

**Next:**
1. Read the replies. Count who would sign in, and note whether anyone offers to moderate.
2. If it is a no, record that here and stay with tiers alone. If yes, design the Worker first (schema, throttles, hide and delete
   paths, version-tied reports) and check Better Auth and Google OAuth setup before announcing a date.
3. Decide where "Report an issue" points for ports that live in other people's repos (central issues in this repo vs the author's repo).
4. Announce first, then build (principle 5).

## Open decisions
- Whether to build community signals at all (waiting on the 2026-11-04 replies), and the sign-in set (Discord + Google, email later?).
- Where issue reports go for ports in other authors' repos.
- Who may verify besides the author, and when.
- The exact "meets the bar" list for Step 1 (above is a draft).
- Whether the existing Listed plugins keep their tier as is (assumed yes: they were the baseline).

## Announcement draft (Step 2)
Short version for Discord, then link the longer text in a pinned GitHub Discussion.

> **Catalog update: trust tiers (nothing is being removed or blocked)**
>
> The catalog has grown fast, which is great. To help people find plugins that work, every plugin now shows one of three tiers:
> - **Verified**: the author has recorded a test of the newest release on real hardware (device and MPC OS version).
> - **Listed**: a valid release that passed the catalog's checks, with no recorded hardware test yet.
> - **Experimental**: no stable release yet. Hidden from the default view; the Tier filter shows it.
>
> The default sort is now "Recommended" (Verified first), and "Recently updated" is still one click away.
>
> **Moving up is up to you and costs one file.** Add a `tested.json` to your plugin's repo:
> `[ { "version": "1.2.0", "device": "MPC Live II", "firmware": "3.6.0", "date": "2026-10-10" } ]`
> and the next catalog build marks that release Verified. Each card also has a "To improve this listing" list (screenshot, skin,
> CPU bench, stable release) as advice only.
>
> **What is not changing:** adding a plugin is still one small PR, with no committee and no ratings or comments. Stars measure
> taste, not "does it load on my MPC", and a small community can't keep them honest.
>
> **Coming next, announced first:** new entries will start as Experimental and move up automatically when they meet the checklist.
> Questions or objections: reply here.

Before posting: tell authors who are Listed that one file moves them up, and give the date the change goes live.
