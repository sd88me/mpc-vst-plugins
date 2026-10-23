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
  generation since 2026-10-12: "Verified Gen1" (a Gen1 device) and "Verified Gen2" (a device naming Gen2, on a release with a Gen2 build).
- **Listed:** a valid release that passed the catalog's release checks; no recorded test for the newest release. Shown with no badge (since 2026-10-11): in the catalog and not Verified means Listed.
- **Experimental:** no stable release yet, or capped by a maintainer (`"tier": "experimental"` in the registry entry). Hidden from the default view.
- Default sort "Recommended": featured, then Verified, then Listed. Ties: Verified on both generations first, then the newest
  hardware-test date, then downloads, then name (2026-10-14, offline).
- Rejected on purpose: star ratings, comments, upvotes as a quality signal (few users, needs a backend and moderation).

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

## Open decisions
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
