# Moving to a GitHub organization: migration checklist

Status: **preparation under way, nothing transferred** (updated 2026-11-01; first draft 2026-10-14; scratch-repo experiments run 2026-10-19 and 2026-10-20, see "Facts to verify"). Proposal from the community: create an org (created 2026-10-20 as `open-mpc`; the working name was "OpenMPC") for the
structural repos, and optionally take in other developers' repos with their consent. This file is the plan and the
list of what would break. Mark items as they are done, with the date and whether it was checked offline or on a device.

## Handoff: resume here (state at 2026-11-01)
To pick this up in a new session, say: **"Continue the open-mpc migration from the handoff in docs/ORG_MIGRATION.md."** Read this
section first, then "Sequence" and "Facts to verify", and check each PR below with `gh` (state, CI, comments) before acting.

**Decided 2026-11-01**
- **Name and org:** OpenMPC, https://github.com/open-mpc. No custom domain.
- **The address users go to: `https://open-mpc.github.io/`** (the site), with `catalog.json`, `catalog.tsv`, `patches.json` and
  `mpc-store.sh` at the root. It is served by the org's own Pages repo `open-mpc/open-mpc.github.io`, so it works before the transfer
  and does not change if repos are later split or renamed. (This replaces the earlier `open-mpc.github.io/mpc-vst-plugins/`.) After the
  transfer, the moved repo's own Pages address `open-mpc.github.io/mpc-vst-plugins/` becomes a redirect to the root.
- **The old address `https://sd88me.github.io/mpc-vst-plugins/` stays alive:** before the transfer it is this repo's own Pages; after
  it, a copy in `sd88me/sd88me.github.io` (#485), because a transferred repo's Pages URL 404s at once.
- **Scope, phase 1:** only `mpc-vst-plugins` moves, as in "Sequence" below. Ports stay under `sd88me`. **Phase 2 (later, its own plan):**
  split the monorepo into a few repos in the org (catalog first) once phase 1 has run for a few catalog cycles.
- **Timing:** the transfer happens in a quiet period, not before the week of 2026-11-09.

**Pieces**
| Piece | Where | State |
|---|---|---|
| Org settings (2FA required, base permission Read, member repo creation off) | `open-mpc` | done 2026-10-20; one owner (sd88me), second owner after the transfer |
| Org Pages repo with the catalog files | `open-mpc/open-mpc.github.io` | created 2026-11-01; `catalog.json`, `catalog.tsv`, `patches.json` live (checked 2026-11-01) |
| Copy each build to the org repo (`mirror-org` job in `catalog.yml`, secret `OPENMPC_PAGES_TOKEN`) | #677 | **merged** 2026-11-01; first run green 2026-11-01 |
| Plugin Manager: org address first, old one as fallback | #677 | **merged** 2026-11-01 (offline tests); ships in the next Manager release |
| Desktop installer + `mpc-store.sh`: org address first, old one as fallback | #484 | **merged** 2026-11-01 (offline tests); ships in the next installer release |
| Whole site at the root (mirror job copies the site, `mpc-store.sh`, `SITE` fallback) | #679 | open; offline check only |
| Old address after the transfer (`tools/catalog_mirror.py`, `mirror` job into `sd88me/sd88me.github.io`) | draft #485 | offline tests only; must land before or at the transfer |
| Owner change `sd88me` to `open-mpc` in workflows, `patch_check.py`, `patches.json`, links | draft #483 | **do not merge before the transfer**; rebase on main first (it predates #484/#677) |
| `POLICY.md` | this branch | draft; open items listed in it |

**The plan, with status.**
1. [x] Client fallbacks merged: installer and `mpc-store.sh` (#484), Plugin Manager (#677), 2026-11-01.
2. [x] Org address live and kept up to date by the catalog build (#677 `mirror-org`), 2026-11-01.
3. [ ] Whole site at `open-mpc.github.io/`: PR #679 (mirror-org copies the whole site; `SITE` fallback).
4. [ ] Release the clients with the fallback (Plugin Manager, desktop installer) and give people time to update. Old installs cannot
       be updated after the old address dies, so this goes well before the transfer.
5. [ ] Rebase #485; make it copy into `sd88me/sd88me.github.io` under `mpc-vst-plugins/`; deploy key with write access on that repo in
       the secret `MIRROR_DEPLOY_KEY`, variable `CATALOG_MIRROR_REPO=sd88me/sd88me.github.io`; delete the scratch `scratch-tools/` folder
       there. Dry-run with the real folder name before the transfer.
6. [ ] Write down this repo's settings to re-add after the move: webhooks (Discord release hook), variables, secrets (`OPENMPC_PAGES_TOKEN`,
       `DISCORD_RELEASE_WEBHOOK`), branch protection, deploy keys, Pages source.
7. [ ] Merge this docs branch (this file, `POLICY.md`).
8. [ ] **Transfer** `sd88me/mpc-vst-plugins` to `open-mpc` (user, in the UI). Never create anything at the old name afterwards.
9. [ ] Straight after: merge #483 (rebased); change the `uses:` line in the `sd88me` ports' release workflows (they break at once); point
       the repo's own Pages at a redirect to `open-mpc.github.io/`; re-add the step 6 settings; run `catalog.yml`; check the old address
       answers through the `sd88me.github.io` copy.
10. [ ] Tell external plugin authors to change one line to `open-mpc/mpc-vst-plugins/.github/workflows/...@<sha>`; announce with the
        policy page.
11. [ ] Add the second owner; finish `POLICY.md` (security contact, `MAINTAINERS`, delisting deadline, unaffiliated wording).
12. [ ] After a few catalog cycles: move this checklist into `NOTES.md` (dated), trim this file, then plan phase 2.

**Still unverified.** `catalog_build.py`'s `urllib` following the API's 301 with its auth header (or update the registry entries and do not
rely on it); variables, webhooks, branch protection and deploy keys across a transfer; download counts. The committed binary
`tools/desktop/desktop` (x86-64 ELF) still holds the old address and is not rebuilt anywhere.

**What a session can and cannot do** (learned 2026-10-19/20, still true 2026-11-01 with the user's own `gh` login): repo creation and
transfers, org members and org-level settings are done by the user in the UI. A local session with the user's `gh` can create repos in the
org, push and run workflows (it created `open-mpc/open-mpc.github.io` on 2026-11-01). Offline tests: `go test ./...` in `tools/desktop`;
`python3 tools/test_catalog.py` (run from `tools/`); `python3 tools/test_patches.py`; `tools/plugin_manager_g2/tests/run.sh`.

**Leftovers to clean up (user, in the UI):** `mpc-vst-test/scratch-caller`, the `mpc-vst-test` org if unwanted, and the `scratch-tools/`
folder in `sd88me/sd88me.github.io` (keep that repo: the old-address copy needs it).

## Decisions to make first
- [~] **Org name: `open-mpc`** (created by the user on 2026-10-20, https://github.com/open-mpc, so the name was available).
      Trademark/name check done by the user (2026-10-20), org settings done (2FA required, base permission Read, repo creation
      by members off). **Second owner: decided to add one after the transfer, when a trusted person is found** (a change from the
      plan, which wanted 2+ before; until then the org depends on one account, so keep its recovery codes safe). Nothing has been
      moved into it yet. Pages URL: `open-mpc.github.io/` (decided 2026-11-01, see the handoff), the new `uses:` path
      `open-mpc/mpc-vst-plugins/.github/workflows/...@<sha>`.
      (The site is already titled "Open MPC - Plugin Catalog".)
- [ ] **Owners.** At least two, so no single account is a point of failure. Decide who gets merge rights on the catalog.
- [ ] **What moves.** Proposed: `mpc-vst-plugins` (wrapper, tools, catalog, site, installer) and the ports `sd88me` owns.
      Other developers' repos stay where they are and stay listed; an invitation to join is optional and needs their consent.
- [~] **Policy page.** Draft written 2026-10-20 in `POLICY.md` (rules the catalog already applies plus governance). Open items
      in it: the unaffiliated wording after the trademark check, a security contact, `MAINTAINERS`, the delisting deadline, the second owner.

## What is hard-coded to `sd88me` (found offline, 2026-10-14)
74 files mention it; 35 are `sd88me/mpc-vst-plugins`. The ones that matter at run time:

| Where | What | Breaks if not handled |
|---|---|---|
| `tools/desktop/catalog.go` `defaultCatalogURL` | `https://sd88me.github.io/mpc-vst-plugins/catalog.json` | **Every installed copy of the desktop app.** Pages URLs are not redirected on transfer. |
| `tools/mpc-store.sh` `URL=` | `.../catalog.tsv` (overridable with `MPC_STORE_URL`) | Copies already on devices. |
| `tools/catalog_site/index.template.html` | `SITE` fallback | Minor (only when not served over http). |
| `catalog/patches.json`, `docs/PATCHES.md` | `raw.githubusercontent.com/sd88me/mpc-vst-plugins/<commit>/...` | Raw URLs after a transfer: verify, do not assume. |
| `.github/workflows/{vst,addin}-release.yml` and the docs that show them | `uses: sd88me/mpc-vst-plugins/.github/workflows/...@<sha>` | **Other developers' release workflows** pin this path. |
| `.github/workflows/vst-release.yml:106`, `addin-release.yml:88` | `repository: sd88me/mpc-vst-plugins` in the "Check out mpc-vst-plugins (tools)" step | Every release run that uses the reusable workflow, until the owner is changed here. Whether the checkout follows a transfer redirect is unverified. |
| `tools/catalog_build.py` | `api.github.com/repos/<owner>/<name>/...` through `urllib` (follows redirects on GET) | Probably nothing, but untested. Update the registry entry anyway. |
| `catalog/plugins/*.json` | `repo` for ~23 `sd88me` entries | Catalog discovery if a repo moves and the entry is not updated. |
| `README.md`, `catalog/pages/*.md`, `docs/*` | links | Cosmetic once redirects work. |
| `docs/NOTES.md` | historical mentions | Leave alone; they are history. |

## What will and will not be resolved (2026-10-14, offline analysis; redirect behaviour unverified)

### Cannot be fully resolved
| Problem | Why |
|---|---|
| Old installs of the desktop app and `mpc-store.sh` | They default to `sd88me.github.io/...`. Pages URLs reportedly do not redirect on transfer. A copy can be kept at the old URL, but only by keeping something under `sd88me` for as long as old installs exist. |
| Old external links (forum, Discord, videos) to the Pages site | Repo links redirect; Pages links reportedly do not. |
| Stars, download counts shown on the catalog | Whether they carry over is unverified. |
| Reusing the old name | Creating anything at `sd88me/mpc-vst-plugins` later can break the redirect. A permanent constraint on the old account. |
| Third parties who never update their workflow | They stay on whatever the redirect (if any) gives them. |

### Can be fixed
| Problem | Fix |
|---|---|
| Hard-coded owner in 74 files, including the two `repository:` checkouts above | One reviewed PR with tests (`test_patches.py`, desktop tests, `catalog_check.py --catalog`) and docs updated in the same PR. |
| Clients with one catalog URL | Release the desktop app and `mpc-store.sh` with both URLs (new first, old as fallback) before the transfer. |
| `repo` in the ~23 `sd88me` registry entries | Update each in the same step as that repo's transfer. |
| Pinned raw URLs in `catalog/patches.json` | Rewrite once the redirect behaviour is known. |
| Secrets, webhooks, Pages source, branch protection | Redo on the org (checklist item). |
| Trust and governance | Policy page, 2+ owners. |
| Name and trademark | Check before committing to the name. |

### What contributors will need to do
- **Authors who stay in their own repos:** possibly nothing, if a `uses:` reference follows the redirect. If not, change one
  line in their release workflow (`sd88me/mpc-vst-plugins/...@<sha>` to the org path). Their registry entry is unaffected.
- **Authors whose repo moves into the org:** consent to and accept the transfer (ownership and admin change), and update
  their `catalog/plugins/<id>.json` `repo` field in a PR.
- **Anyone with a fork or clone:** update the remote URL (the old one keeps working while the redirect stands).
- **New contributors:** catalog PRs go to the org's repo; the docs and PR template say so.

### Effect on the catalog
- **Discovery:** plugins that do not move are unaffected. For moved repos the API redirect should carry the call, but
  update the registry entry rather than rely on it.
- **Site URL:** `open-mpc.github.io/` (decided 2026-11-01; served by the org's Pages repo, not this repo). The old one needs a redirect page or a copy.
- **`catalog.json`, `catalog.tsv`, `patches.json`:** must be live at the new URL before clients switch.
- **Version history and `tested.json`:** live in the plugin repos and the catalog repo, so they move with them. Check the
  nightly build after every transfer.
- **Risk window:** between the transfer and clients learning the new URL. This is why the dual-URL client release goes first.

## Facts to verify before relying on them
GitHub's docs were not reachable from the agent session (network policy), so these come from search snippets or memory.
Check each by hand, ideally on a throwaway repo and org first.
- [x] **Git and web links redirect after a transfer; GitHub Pages does not.** Confirmed live (2026-10-19). Git clone and
      `github.com` links redirect (see below). Pages: user opened both URLs in a browser after the transfer:
      `https://mpc-vst-test.github.io/scratch-tools/` (old) gave **404**, and `https://sd88me.github.io/scratch-tools/` (new)
      loaded without re-enabling Pages. So the old Pages URL dies at once, as the table above assumed.
- [x] **Do creating a new repo at the old name, or recreating the old repo to host a Pages redirect, break the redirect?**
      **Yes, it breaks all of them** (live, 2026-10-20). After the user created a new public `mpc-vst-test/scratch-tools` (old name of the
      transferred repo), every old-name probe hit the new repo instead of `sd88me/scratch-tools`: `github.com/<old>` 200 (was 301),
      `git clone` returned the new repo's commits, `api.../repos/<old>/releases` returned `[]`, the release asset download and the raw
      URL at the old pinned sha both 404, `actions/checkout` with the old `repository:` at the old sha failed (git exit 128, sha not
      in the new repo), and the old-path `uses:` stayed refused. The new owner path still worked (`sd88me/...@<sha>` ran green).
      Consequence: never create anything at `sd88me/mpc-vst-plugins` after the move; a Pages redirect/keep-alive must live in a
      differently named repo (`sd88me.github.io` or another name) and not at the old repo name. Whether deleting the new repo
      restores the redirect was not tested (rollback unverified; GitHub's docs say a redirect can be reclaimed only if the name is
      freed, so do not rely on it).
      **Rollback test (live, 2026-10-20): deleting the new repo did NOT restore the redirect.** After the user deleted it, the old name
      returned 404 for everything: `github.com/<old>`, `api.../repos/<old>` and `/releases`, `git clone`, the release asset download and
      the raw URL. The old-path `uses:` stayed refused, and `actions/checkout` with the old `repository:` failed. The `sd88me` path
      for `uses:` still resolved, but its job failed at the reusable workflow's own hard-coded `repository: <old owner>/scratch-tools`
      checkout, which only worked while the redirect existed (green on 2026-10-19, red now). **Once the old name is taken, even
      briefly, the transferred repo is reachable only under its new name**, so the `repository:` lines in `vst-release.yml:106` and
      `addin-release.yml:88` must be changed in the owner-change PR, and no repo may be created at the old name before that.
- [x] **Does `uses: owner/repo/.github/workflows/x.yml@<sha>` follow a transfer redirect?** **No** (live, 2026-10-19).
      Scratch repos `mpc-vst-test/scratch-tools` (transferred to `sd88me`) and `mpc-vst-test/scratch-caller`. After the transfer,
      dispatching the caller with the old path was refused: `error parsing called workflow ... "mpc-vst-test/scratch-tools/.github/workflows/x.yml@<sha>": workflow was not found`.
      Control: the same caller with `sd88me/scratch-tools/...@<sha>` ran green, and the same old-path caller ran green before the
      transfer. **Every external release workflow pinning `sd88me/mpc-vst-plugins/.github/workflows/...@<sha>` needs a one-line
      edit after the transfer**, so this is the main thing to announce to plugin authors.
- [x] **Does `actions/checkout` with `repository: <old owner>/<name>` follow it?** **Yes** (live, 2026-10-19). A workflow in
      `scratch-caller` doing `actions/checkout@v4` with `repository: mpc-vst-test/scratch-tools` at the pinned sha, after the
      transfer, succeeded and read the file. The hard-coded `repository:` lines in `vst-release.yml:106` / `addin-release.yml:88`
      keep working through the redirect, but change them anyway.
- [~] **Does `urllib` in `catalog_build.py` follow the API's redirect for a transferred repo** (and keep its auth header)?
      Partly verified (live, 2026-10-19). `GET api.github.com/repos/<old>/releases` answers `301 Moved Permanently` with
      `Location: https://api.github.com/repositories/<id>/releases`, so the redirect exists. **Not verified end to end**: the agent
      proxy rejects `/repositories/{id}/...` paths (and `sd88me/scratch-tools` was not in the session scope), so `urllib` got 403 from
      the proxy, not from GitHub. `urllib` follows a 301 on GET to the same host and resends its headers, which is expected to keep
      the auth header, but this was not observed. Re-run on a machine without that proxy, or just update the registry entry first.
- [x] **`releases/download/...` and `raw.githubusercontent.com` URLs after a transfer.** **Both still work under the old name**
      (live, 2026-10-19). `github.com/<old>/releases/download/v1/asset.txt` (curl -L) ends 200 with the asset;
      `raw.githubusercontent.com/<old>/<sha>/pinned.txt` returns 200 with the pinned content; the new name serves the same. The pinned
      raw URLs in `catalog/patches.json` therefore do not break on transfer, but rewrite them in the owner-change PR anyway.
      Also seen: `github.com/<old>` answers `301` to `github.com/<new>`, and the `git clone` of the old URL worked (remote stays the old URL).
- [~] Which settings travel with a transfer: Pages config, Actions secrets and variables, webhooks (the Discord release
      workflow), branch protection, deploy keys, and the release-asset download counts the catalog shows.
      Observed by the user in the UI (2026-10-19, scratch repo): **Pages config traveled** (new URL served without re-enabling),
      **the Actions secret traveled**, **the star traveled**. Not tested: variables, webhooks, branch protection, deploy keys,
      release download counts. Redo the untested ones by hand after the real transfer.
- [x] Org Pages URL: `open-mpc.github.io/` from the org's Pages repo, no custom domain (decided 2026-11-01). Was: whether a custom domain is wanted instead.

## Sequence (revised 2026-10-20 after the scratch-repo experiments; only `mpc-vst-plugins` moves)
The checklist in the handoff (2026-11-01) is the current order; this section keeps the reasoning behind each step.
Scope: transfer `sd88me/mpc-vst-plugins` to the org and nothing else. The ports stay under `sd88me` and stay listed; their
`catalog/plugins/<id>.json` entries do not change. Rules from the experiments (see "Facts to verify"): `uses:` paths with the old
owner stop working at once, the old Pages URL 404s at once, everything else redirects, and **nothing may ever be created at
`sd88me/mpc-vst-plugins`** (it permanently kills the redirects; deleting it again does not restore them).

1. **Prepare the org.** Create it with 2FA required (done 2026-10-20; the second owner is added after the transfer, see the org-name item), set base permissions, check the name against Akai's
   trademarks, the address is `open-mpc.github.io/` (decided 2026-11-01; was: confirm `<org>.github.io/mpc-vst-plugins/` or a custom domain). Write the policy page.
2. **Make the old catalog URL survive without a repo at the old name.** *(Code: draft PR #485, offline tests only, 2026-10-20: `tools/catalog_mirror.py` and a `mirror` job in `catalog.yml` that stays off until the variable `CATALOG_MIRROR_REPO` is set; it needs a write deploy key on `sd88me/sd88me.github.io` in the secret `MIRROR_DEPLOY_KEY`, and the scratch `scratch-tools/` folder in that repo should be deleted.)* Create `sd88me.github.io` (a user-site repo) holding a
   copy of `catalog.json`, `catalog.tsv` and `patches.json` under `mpc-vst-plugins/` plus a redirect page for the site, so
   `sd88me.github.io/mpc-vst-plugins/...` keeps answering once the project repo has left. **Verified (live, user browser,
   2026-10-20)**: with the project repo `sd88me/scratch-tools` deleted, `sd88me.github.io/scratch-tools/catalog.json` and
   `.../index.html` both serve the user-site repo's `scratch-tools/` folder, so the old catalog URLs can be kept alive this way
   without a repo at the old name. Caveat: right after the delete the `index.html` URL still showed the deleted project site's page
   for a while (a stale cache), so expect a delay of minutes before the old project page gives way. A first run, with the project
   repo still present, was disturbed by an accidental delete of the folder, so precedence while both exist is not established;
   it does not matter, since the project repo is gone after the transfer. Still do a dry run with the real folder name before
   the transfer. The org repo's
   nightly job must push the copy (needs a token secret). New catalog files must be live at the new URL before clients switch.
3. **Ship the dual-URL clients.** *(Draft PR #484, offline tests only, 2026-10-20; the app release itself is not done.)* Release the desktop app and `mpc-store.sh` trying the org URL first and the old one as a
   fallback. Old installs cannot be updated after the old URL dies, so this goes before the transfer.
4. **Prepare, but do not merge, one PR** *(Draft PR #483, 2026-10-20; excludes `mpc-store.sh` and `catalog.go`, which #484 changes, and leaves the Go module path, `NOTES.md`/`ROADMAP.md` history and the ports' catalog entries)* for `sd88me/mpc-vst-plugins` that replaces the owner in the table above:
   `repository:` in `vst-release.yml:106` and `addin-release.yml:88` (this one is required: it only worked through the redirect),
   the `uses:` paths in the workflows and docs, `defaultCatalogURL`, `mpc-store.sh`, the `SITE` fallback, the raw URLs in
   `catalog/patches.json`, README and docs. Tests: `tools/test_patches.py`, the desktop tests, `catalog_check.py --catalog`.
   Docs updated in the same PR (CLAUDE.md "Docs sync").
5. **Update the `sd88me` ports' own workflows** (the `uses:` line pointing at `sd88me/mpc-vst-plugins/...@<sha>`) in
   branches ready to merge the moment the transfer is done, since those would otherwise break. The new `uses:` path can only be
   pinned to a sha that exists in the org repo, which is the same history after a transfer.
6. **Transfer `mpc-vst-plugins` to the org** in a quiet period, then at once: re-check Pages (the config traveled in the
   scratch test; re-enable from the Actions workflow if not), re-add what was not tested (variables, webhooks such as the Discord
   release hook, branch protection, deploy keys), merge the PR from step 4 and the port branches from step 5, run the nightly
   `catalog.yml`, and push the first copy to `sd88me.github.io`. Check the site, `catalog.json`, `catalog.tsv`, `patches.json`.
7. **Tell external plugin authors**: their catalog entries are unaffected, downloads and git keep working, and they must change
   one line in their release workflow to `<org>/mpc-vst-plugins/.github/workflows/...@<sha>`. This cannot be avoided without
   recreating the old name, which loses every redirect, so do not do it.
8. **Announce** with the policy page. Mention that listing does not require moving.
9. **After a few catalog cycles**, archive the checklist into `NOTES.md` (dated, with what was verified and where) and trim
   this file. Keep the `sd88me.github.io` copy and the dual-URL clients for at least one release cycle, longer if old installs remain.

Still to verify before step 6 (not covered by the 2026-10-19/20 scratch tests): variables, webhooks, branch protection and
deploy keys across a transfer; and `catalog_build.py` following the API's 301 with its auth
header (needs a machine without the agent proxy). Stars and the Actions secret traveled; download counts are untested.

## Rollback
A transfer can be reversed only by transferring the repo back, which needs the old name to be free; creating anything at the
old name, even briefly, loses the redirects for good (live, 2026-10-20). Do not create anything at the old names until the new
setup has run for a few catalog cycles. Keep the old Pages redirect and the dual-URL clients for at least one release cycle.

## Prior art (from memory, not re-checked)
- VCV Rack's `library` repo: one thread or manifest per plugin, authors keep their repos, maintainers build and update.
  (README fetched 2026-10-14: updates are a version bump plus a commit hash posted to the plugin's thread; it does not
  describe hosting.)
- conda-forge: staged-recipes PR for first entry, then per-package repos kept up by bots.
- Homebrew: curated core plus third-party taps.
