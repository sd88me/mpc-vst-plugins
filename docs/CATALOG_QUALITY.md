# Catalog quality plan (decided 2026-10-10)

Why: the catalog is growing fast, and some contributors bulk-convert open-source projects into it. Quality varies and
there is nobody with the time to review every entry. Goal: keep the registry open to everyone, but make the front of
the catalog earned by evidence, at almost no cost to the maintainer.

## Principles
1. **Gate prominence, not entry.** Anyone can list a plugin. What is evidenced is shown higher.
2. **Evidence over opinion.** Tiers come from things anyone can check (a recorded device test, a passing check), not from votes.
3. **No new maintainer workload by default.** Nothing needs a human review until a person asks for one, and a person asking is optional.
4. **Informational first, hiding later.** Show people what is missing before anything is hidden or demoted.
5. **Say it before doing it.** Each step is announced to contributors before it takes effect.

## The tiers (live in PR #267; see CATALOG.md "Trust tiers")
- **Verified:** the newest stable release has a `tested.json` entry (device, OS version, date) in the plugin's own repo.
- **Listed:** a valid release that passed the catalog's release checks; no recorded test for the newest release.
- **Experimental:** no stable release yet, or capped by a maintainer (`"tier": "experimental"` in the registry entry). Hidden from the default view.
- Default sort "Recommended": featured, then Verified, then Listed, then name.
- Rejected on purpose: star ratings, comments, upvotes as a quality signal (few users, needs a backend and moderation).

## Steps
Each step stands alone. Stop after any of them.

### Step 0: done
- [x] Tiers computed by `tools/catalog_build.py`, badges, Tier filter, Recommended sort, tests, docs (PR #267, offline).
- [x] `tested.json` added for every plugin of the maintainer's own repos (Force, MPC OS 3.9.1, 2026-10-10), so they become Verified on the first build.
- [ ] Merge PR #267 and run the catalog workflow once. Check the result against expectations (about 36 + 15 Verified, one Experimental).

### Step 1 (soft start): make the bar visible, change nothing
Define "meets the bar" as things CI can check, and show it, without hiding or demoting anything:
- a screenshot; the skin passes `skin_check`; the manifest `cpu` verdict is not a fail; ports name their upstream and licence;
  a stable release.
- Plugin cards and pages show a small "What is missing" checklist, and `catalog_check.py` prints the same list to authors.
- Contributor docs (`catalog/README.md`) explain the list and how to get Verified.
- No tier changes yet. This only collects information and tells people what is coming.

### Step 2: announce
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
- A within-tier tiebreaker (reactions or "N people use this"), never a way into a higher tier.
- A hand-picked Featured row (`"featured": true`, already supported).

## Open decisions
- Who may verify besides the author, and when.
- The exact "meets the bar" list for Step 1 (above is a draft).
- Whether the existing Listed plugins keep their tier as is (assumed yes: they were the baseline).
