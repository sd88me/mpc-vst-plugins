# Community signals: design draft (2026-11-05)

Status: **draft, nothing built.** Background, research on Firmware Hub and Modwerk, cost and the community poll are in
`docs/CATALOG_QUALITY.md` ("Community signals proposal"). This page turns that into a buildable design. Cost figures there
are from searches on 2026-11-04, not tested. Items marked **DECIDE** are the maintainer's.

## Decisions so far (2026-11-05, maintainer)
1. Home: the `open-mpc` GitHub org. The site is served from `open-mpc.github.io` (root, with `catalog.json`); the old
   `sd88me.github.io/mpc-vst-plugins/` copy stays alive for months. The Worker gets its own repo in the org (not the catalog repo,
   which takes outside PRs; the Worker holds secrets). Allowed origins are configuration: `https://open-mpc.github.io` and the old
   origin during the overlap. When the catalog later moves to its own repo, nothing changes for the Worker, since the page origin
   stays `open-mpc.github.io`. No custom domain is planned, so the API would be on `*.workers.dev`, a different site from the page:
   use a **bearer token (kept in the page's storage), not a cross-site cookie**, because browsers block or partition third-party
   cookies. Verify this against the chosen auth library before building.
2. Report an issue: the plugin's own repo (fallback to a central form when the plugin repo has no Issues).
3. Counts: headline is the all-versions number ("N people report working"); the newest-version count shows in the expanded card.
   (Newest-only would reset to 0 after every release and make active plugins look empty.)
4. All sign-in methods count equally. Revisit the "aged email account" rule only if abuse shows up; hide and rate limits cover it.
5. The maintainer holds the credentials (Cloudflare, Discord app, Google OAuth). Prefer org-owned accounts so access can be shared.

## Goals and limits
- Add two signals per plugin card: **reported working** (device + OS + plugin version, one person once) and **likes**.
- Add a pre-filled **Report an issue** link. No stars, no comments, no ranking by taste across tiers.
- Never change a tier. Verified stays the author's `tested.json`; the community count is shown beside it and labelled
  "community reports, not hardware verification".
- The static site must keep working if the service is down or blocked: counts are an enhancement, never required to browse.
- No new daily maintainer work: nothing needs approval, and hiding or deleting is on request.

## Architecture
- The site stays static (GitHub Pages, `tools/catalog_site/index.template.html`, data embedded from `catalog.json`).
- A small **Cloudflare Worker + D1** service holds votes and accounts (design inspired by Modwerk; its backend is Elastic-2.0, so
  write our own, do not copy code).
- The page loads counts with one cached request, `GET /api/counts`, a JSON object `{plugin_id: {working, likes}}`, and merges
  them into the cards. On failure it shows no counts and no error. Cache 5 minutes at the edge so card views do not hit D1.
- Sign-in only happens when someone presses a button. Reading never needs an account.
- Sign-in with **Discord and Google** first; an emailed link only if people ask (adds a mail quota and a sending domain).
  Candidate library: Better Auth (Modwerk uses it). **Not yet checked:** its current docs and licence, and Google's OAuth consent
  screen setup for users outside our own account. Check both before committing to it.
- Where it lives (**DECIDE**): `tools/community_signals/` in this repo (one place, shared CI) or a separate repo (clean licence and
  secrets boundary). Recommendation: a subfolder here, with secrets only in Cloudflare, never in the repo.

## Data model (D1, SQLite)
```sql
CREATE TABLE users (id TEXT PRIMARY KEY, provider TEXT NOT NULL, provider_id TEXT NOT NULL,
  email TEXT, email_verified INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  hidden INTEGER NOT NULL DEFAULT 0, UNIQUE(provider, provider_id));
CREATE UNIQUE INDEX users_email ON users(email) WHERE email IS NOT NULL AND email_verified = 1;  -- one person, one account
CREATE TABLE likes (plugin_id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (plugin_id, user_id));
CREATE TABLE working_reports (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  plugin_id TEXT NOT NULL, version TEXT NOT NULL, device TEXT NOT NULL, os TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, hidden INTEGER NOT NULL DEFAULT 0,
  UNIQUE (user_id, plugin_id, version, device, os));
CREATE INDEX reports_plugin ON working_reports(plugin_id, hidden);
```
- `plugin_id` is the catalog id (`catalog/plugins/<id>.json`). `version` is the catalog's newest stable at the time, or the one
  the reporter picks. `device` and `os` are chosen from the catalog's known devices, free text only for an OS string.
- "N people report working" counts **distinct users**, `hidden = 0`, across versions (as Modwerk's tooltip does). The card also
  shows the count for the newest version. **DECIDE:** show both, or only the newest-version count.
- Indexes above exist because D1 free queries now fail after 5M rows read/day; counts should come from one grouped query per cache
  refresh, never a scan per card.

## Endpoints
| Route | Auth | Purpose |
|---|---|---|
| `GET /api/counts` | none, edge-cached | `{counts: {id: {working, likes, versions: {version: n}}}}`; the page picks the newest version from its own catalog data |
| `POST /api/working` | member | body `{plugin, version, device, os}`; insert or no-op on duplicate |
| `DELETE /api/working` | member | withdraw own report |
| `POST /api/like`, `DELETE /api/like` | member | like or unlike |
| `GET /api/me` | member | own likes and reports so the page can mark buttons |
| `DELETE /api/me` | member | delete the account and its rows (cascade) |
| `/api/auth/*` | | provider sign-in (Discord, Google) |

- Throttle per IP and per member (Modwerk uses 60 per window); reject unknown plugin ids by checking against the catalog list
  the build publishes (`counts` rejects ids not in `catalog.json`).
- CORS: allow only the catalog site origin. CSRF-safe session cookie (SameSite) or bearer token.
- Cap reports per user per day so a script cannot fill the table.

## Counting rules (**DECIDE**)
1. One person, once: link accounts by verified email. A Discord user with no verified email is their own identity and could also
   sign in with Google; accept that small double-count risk, or require a verified email to report.
2. Public number counts only Discord or Google accounts. If email sign-in is added later, count those only after the account is
   some days old. Chosen to blunt throwaway addresses.
3. A report belongs to a version. A new release does not inherit old reports in `working_newest`; the all-versions number keeps them.

## Site changes (`tools/catalog_site/`)
- Card: a small "reported working" line with count and tooltip ("Community reports, not hardware verification"), a heart with
  count, a "Works for me" button and a "Report an issue" link. Buttons open the sign-in dialog when signed out.
- Sort options "Most reported working" and "Most liked". **"Recommended" stays featured, then tier, then the existing ties**; the
  community count may only break ties inside a tier, never lift a plugin to a higher one.
- Hidden behind a flag (`?signals=1`) until announced, so it can be tested on the live site without showing everyone.
- `browser_test.py` and `fixture-catalog.json` need counts added; the test must also cover the API-down path (cards render with
  no counts).

## Report an issue (**DECIDE** the destination)
Ports live in many authors' repos, so a pre-filled GitHub issue link cannot assume one place.
- Option 1: the plugin's own repo (`repo` field in the registry entry), pre-filled title and body: plugin, version, device, OS.
  Works only if the author has Issues enabled; otherwise show nothing or a fallback.
- Option 2: one central issue form in this repo that tags the plugin. Always works, but puts reports on the maintainer.
Recommendation: option 1, falling back to a central form when the plugin repo has no Issues. The link is built by the site from
the registry data, so this needs no backend.

## Privacy and removal
Store only: provider, provider id, email (needed to link accounts) and verified flag, and the rows above. No IPs stored beyond
short rate-limit counters. Add an account deletion button and a short privacy note on the site. Hiding a report or a user is by
setting `hidden`; counts exclude hidden rows. State this in the announcement so nobody is surprised.

## Progress
- **Step 2 built 2026-11-05, offline only:** scratch repo `~/openmpc-signals` (schema, `GET /api/counts`, 8 tests on Miniflare's local
  D1, all pass; the count queries use the indexes). Nothing deployed; no accounts, writes or sign-in yet.

## Auth checks before step 3 (2026-11-05, docs and package metadata only, nothing run)
- **Better Auth:** MIT (npm `better-auth` 1.7.17). Discord and Google are social providers. **D1:** no first-party adapter is
  confirmed; guides use Drizzle or Kysely and create the auth instance per request (the D1 binding is not available at module
  scope). One guide claims native D1 from 1.5.0; sources disagree, so test it.
- **Account linking:** on by default, links a social sign-in to an existing account only when the provider says the email is
  verified. Do **not** set `trustedProviders` (it links without verification, a takeover risk). A Discord user with no verified
  email gets a separate account, as planned. `disableImplicitLinking` exists if we ever want it off.
- **Deletion:** `deleteUser` is a hard delete, disabled by default. OAuth users have no password, so it needs a fresh session
  (default one day) or an emailed confirmation link. Our `likes` and `working_reports` rows must reference Better Auth's user table
  with `ON DELETE CASCADE`, so the `users` table in `migrations/0001_init.sql` will be replaced or extended to match its schema.
- **Bearer tokens:** the `bearer()` plugin returns the token in a `set-auth-token` response header and the client sends
  `Authorization: Bearer`. Its docs call it a fallback for APIs that cannot use cookies and warn that misuse is a security risk;
  they say nothing about CORS, so the header must be listed in `Access-Control-Expose-Headers`. **Open problem (solved in the
  prototype, see Progress):** OAuth sign-in ends in a redirect, not a fetch, so there is no response header for the page to read.
- **Cookies cannot work here even with a custom domain:** `github.io` is on the public suffix list, so `open-mpc.github.io` and any
  API host are cross-site. Tokens are required unless the catalog itself moves to a custom domain.
- **Google:** an external app **In production** with only basic scopes (openid, email, profile) is not subject to the 100-test-user
  cap, and Google's page ties the "unverified app" warning to sensitive or restricted scopes, so verification is not needed
  (inference from that page, not a quoted rule). Staying in Testing means 100 test users and 7-day authorisation expiry (identity-only
  sign-in is excepted from the expiry). Publish the app. Discord needs the `identify` and `email` scopes; not yet checked.

- **Handoff prototype built 2026-11-05, offline only, fake provider:** Better Auth's `one-time-token` plugin (generated server-side
  in our `/api/signin/done`, 2 minutes, stored hashed, single use) plus `bearer()` gives the page a bearer token with no cookie.
  13 tests pass on Miniflare. Real Discord and Google, rate limits, write endpoints and account deletion are not built. Findings:
  Better Auth's migrator cannot run on D1 (PRAGMA), so its schema is generated to `migrations/0002_auth.sql`; generic providers
  use `/sign-in/social` with a `provider` field (not `/sign-in/oauth2`) and need `id` in the profile; `bearer()` defaults to an
  unsigned token (`requireSignature: false`), which we should switch on or justify.

- **Write endpoints built 2026-11-05, offline only, fake provider:** `GET/DELETE /api/me`, `POST/DELETE /api/working`, `POST/DELETE
  /api/like`, validated against the published catalog (writes fail closed if it cannot be read), daily caps of 30 reports and 200
  likes per person, Better Auth's database-backed per-IP limit configured (not tested to trip). Schema: `0001_auth.sql` generated,
  `0002_signals.sql` references Better Auth's `user` table, so deleting the account cascades. 22 tests pass. Not done: hide
  endpoints (set `hidden` by hand), real Discord and Google, deployment, signed bearer tokens, the page changes.

- **Admin and hardening built 2026-11-05, offline:** `POST /api/admin/hide` and `GET /api/admin/reports` behind one secret
  (`ADMIN_TOKEN`, header `x-admin-token`; 404 without it); hiding a report or a user drops it from every count and is reversible;
  bearer tokens must be the signed value (`requireSignature`); the per-IP auth rate limit trips in a test; `wrangler deploy --dry-run`
  bundles the Worker (about 329 KiB gzipped). The sign-in return address now keeps the page path, so the old address
  (`sd88me.github.io/mpc-vst-plugins/`) works as well as the root. 26 Worker tests pass.
- **Page changes built 2026-11-05 (branch `community-signals`, offline, mocked service and GitHub), redesigned after review:** behind
  `?signals=1`:
  - **Header:** a "Sign in" button in the sticky header (a name menu with Sign out and Delete my account once signed in), so it is always
    visible. Short messages appear as a toast.
  - **Cards:** a strip between the title bar and the tag chips (maintainer's placement, 2026-11-05; earlier drafts had it under the blurb): "✓ N working"
    (tooltip: community reports, not hardware verification), a like heart with its count, and "Works for me".
  - **Collections (2026-11-05):** a collection card shows the same strip with its **best plugin's** figures, not a sum (maintainer's call: a set of 22
    would always beat a single plugin, and one person confirming three members would count three times): "✓ 30 working" is the most people to
    confirm any one member (the tooltip names it), "♡" the most likes on any one member, plus the total downloads of its members and a line
    "Best of 22 plugins (8 with reports)". No buttons on the card: "Open the set to report on a plugin". The collection popup has the same strip under
    its title bar and a compact strip on every member row (count, like, Works for me), and a "Follow all N" toggle that follows each member (one request
    per plugin). The collection also has its own Atom feed, `feed/c/<id>.xml` ("N plugins updated" entries, as in `feed.xml`). "Most reported
    working" and "Most liked" use the best-plugin figures; the Recommended score uses the best matching member. Downloads stay a total (a fact about the
    repo's releases, not a vote).
  - **Downloads and the folded details (2026-11-05):** the bar under the title also carries the plugin's downloads (all versions), so it stays visible
    when the card's Details are folded: Details are closed by default on grid cards (the line beside the word says who tested it) and open in the
    popup. Without the preview, or while the service is down, the bar is just the downloads. The Sign in button is the theme yellow so it is not mistaken for
    the red current-page tab.
  - **Popup:** the same strip plus a Community section under the summary: people reported working (all versions, and on the newest
    version), likes, a "Reported on" table (device, OS, people), the latest reports (date, version, device, OS), the signed-in person's
    own reports with Withdraw, and "Issues on GitHub": the repo's open issues, open and closed (no pull requests; the latest 50 items), counted by version, with "Report an issue" (prefilled), "All
    issues" and Discussions when the repo has them. The counts come from the fetched list because GitHub's `open_issues_count` includes
    pull requests. **Issues by version:** GitHub has no version field, so an issue is placed
    under the newest known version its title or body names (the prefilled report text names one), else under the newest release that
    existed on the day it was opened, marked "placed by date". They show inside the popup's version history: each row gets its
    "N downloads" (the catalog's per-version figure; the details' Downloads is the total of all versions), "N working", and its issues
    as "N open · N closed", which expand under the row (open first, closed muted and struck through with the close date); the
    history's heading gives the totals. GitHub is read from the browser without a token (60 requests an hour per
    address), cached ten minutes; if it fails, or the repo has Issues turned off, the popup says so and the rest still works.
  - **Sorts:** "Most reported working" and "Most liked" appear once counts load. "Recommended" also uses the counts (2026-11-05): the
    community points are added to the verification points (complete Verified 3, partly verified 1.5, Listed 0): each person reporting the newest
    release working is 1, an older release 0.25, a like 0.1, so 4 people confirming a Listed plugin outrank an unreported Verified one. This is
    the maintainer's 2026-11-05 decision (see CATALOG_QUALITY.md); the Verified badge and tier themselves are unchanged.
  - With the flag off nothing changes (verified). With the service down no strips, counts or extra sorts show and the page works.
  - Worker: `GET /api/plugin?id=` returns the breakdown and latest reports anonymously (no names, emails or ids), cached 5 minutes.
  - `tools/catalog_site/signals_browser_test.py` covers it against a mocked service and a mocked GitHub (all checks pass).
    `browser_test.py` has 2 failures and a timeout that are identical on `main`, so they are not from this change.
  - **Not done:** the per-plugin and collection static share pages (`p/<id>.html`, `p/c/<id>.html`) show no signals; the other site pages
    (Install, FAQ) have no header button; "Recommended" ignores the counts (the plan allows them only as a tiebreaker inside a tier);
    the popup does not show discussion threads, only GitHub issues and a Discussions link; the service address is a placeholder
    (`REPLACE-ME`).

## Update notifications ("follow a plugin") - plan, 2026-11-05
Goal: people can subscribe to hear about a plugin's new releases and revisions.
- **A, built (offline):** `feed/<id>.xml`, an Atom feed per plugin from the catalog (same ids as `feed.xml`), and a "Follow updates" button in
  the plugin popup. No backend, no account, works forever; needs a feed reader, which many MPC users do not use.
- **B, built 2026-11-05 (offline; mocked and fake-provider tests, no email):** a signed-in "Follow" toggle in the plugin popup, a `follows` table
  and a personal feed address `GET /feed/<token>.xml` served by the Worker (the secret token is the only credential, so any feed reader can
  read it; "Regenerate" cancels the old one; account deletion removes it). The account menu has "Following and my feed" (address, copy,
  regenerate, the followed plugins with Unfollow). The feed lists the followed plugins' non-yanked releases, newest first, with the catalog's
  entry ids. **Email is not built and not planned for now:** it needs a verified sending domain (about $10-15 a year), which the
  maintainer does not want to pay for at this stage; Resend and Cloudflare only send to arbitrary addresses from a verified domain, and
  a free-mail sender address fails domain checks and lands in spam. If a domain appears later, a daily digest from a Cron Trigger would reuse
  the same `follows` table.
- **C, not planned:** Web Push (service worker, push keys, a subscription table; iOS only for installed web apps). Heavy for the audience.
- **Discord:** the release workflow appears to already post to the Discord (an org-move handoff lists a `DISCORD_RELEASE_ROLE_ID` variable); not
  verified here. A per-person Discord DM would need a bot and a different permission, so it is not proposed.
- Open for the maintainer: whether people actually use feed readers (if not, a Discord channel post for every release, or a domain for email, is the next step).

## Build order (each step ships alone)
1. **Spec agreed**, replies from the Discord and Facebook posts summarised in `CATALOG_QUALITY.md`.
2. Worker + D1 + schema + `GET /api/counts`, run locally with `wrangler dev` and tests (offline, no real accounts).
3. Sign-in (Discord, Google) and the write endpoints, with throttles and deletion; abuse and duplicate tests.
4. Site changes behind `?signals=1`, browser tests with the fixture.
5. Announce a date, then remove the flag.
6. Later, only if asked: email sign-in, follow a plugin for updates, likes as a sort tiebreaker beyond the tier.

## Docs that change when this ships
`docs/CATALOG.md` (tiers section and the new signals), `docs/CATALOG_QUALITY.md`, `catalog/README.md` (what authors see),
`docs/CATALOG_SPEC.md` if any field is added, `docs/ROADMAP.md`, and a new section in `docs/NOTES.md` for anything verified on
the live deployment, dated and marked offline or live.

## Open questions
- Which providers, finally: Discord and Google, with email only if asked.
- Where the service lives, the site origin it serves, and who holds the Cloudflare and OAuth credentials.
- Whether to show all-version and newest-version counts, or one.
- Where issue reports go for ports in other repos.
- Who moderates, and whether trusted verifiers (Step 4) should also be able to hide reports.
