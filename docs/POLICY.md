# Catalog policy (DRAFT, 2026-10-20)

Draft for the planned `open-mpc` organization (see `ORG_MIGRATION.md`). It writes down rules the catalog already applies
(`CATALOG.md`, `catalog/README.md`) and adds the governance an organization implies. Items marked **DECIDE** or **TODO** are
open; nothing here is in force until the maintainers adopt it.

## What this project is
- A community-run catalog and toolkit for native VST2 plugins on Akai MPC OS standalone devices and Force.
- **Not affiliated with, endorsed by or sponsored by Akai Professional, inMusic or Steinberg.** Product and company names are
  used only to say what the software works with. **DECIDE:** final wording, after the trademark check of the name `open-mpc`.
- Listing is not a security review. Nobody reads each plugin's code; install only from developers you trust. Installers run
  as root on a device, so the checks below exist to limit damage, not to guarantee safety.

## What can be listed
- **Open source only**, under an SPDX open licence. `source_available` is not accepted.
- **No closed binaries and no copyrighted ROMs or firmware.** A port that needs the user's own firmware lists as
  *build-yourself*: source and a build command, no download.
- **No other company's branding** in skins, screenshots or plugin names: no manufacturer names, logos or wordmarks, no
  logo-bearing panel art. "X-style" is fine; implying the maker's endorsement is not.
- **A release must be catalog-conformant** (`mpc-plugin.json` from `tools/release.py`, `catalog_check.py` OK).
- Authors keep their own repos. Listing does not require moving a repo into the organization.

## Review and merging
- A new plugin needs one reviewed pull request adding `catalog/plugins/<id>.json`. Later releases are discovered and
  validated automatically; a version that fails validation is hidden and opens an issue.
- **Who may merge:** at least two maintainers with write access; owners of the organization are listed in `MAINTAINERS`
  (**TODO:** create the file). A maintainer does not merge their own plugin's first entry without a second reviewer.
- Tiers are *Verified* (tested on real hardware and recorded in `tested.json`), *Listed* (passed automatic checks) and
  *Experimental* (hidden by default).
- Third-party workflow references to this repo's reusable workflows are pinned by commit; changing them is a reviewed PR.

## Yanking and delisting
- Any maintainer may yank a release by adding `"<id>@<version>"` (or `"<id>@*"`) to `catalog/yanked.json`. It stays listed
  as yanked and is never offered as latest. Reasons: a release that breaks loading on a device, a licence or branding
  problem, or a security problem.
- A plugin is delisted for a branding or licence violation or an unresponsive author after a public issue and a stated
  deadline (**DECIDE:** how long, suggested 14 days). The author is told in the issue; the decision and reason are public.
- Authors may ask to be removed at any time; maintainers remove the entry in a PR.

## Security
- **TODO:** a private reporting address or GitHub private vulnerability reporting for the catalog and installer. Enable it
  on the organization repo before the transfer and put the link here.
- Report a malicious or unsafe plugin through the same channel. A maintainer yanks first, then investigates.
- Maintainers: 2FA required on every account with write access (the organization setting is on as of 2026-10-20).

## Governance
- The organization has at least two owners at all times (**TODO:** second owner not yet added, 2026-10-20).
- Owners and maintainers act as volunteers; decisions are made in public issues or PRs where practical.
- **DECIDE:** how rules change (suggested: a PR to this file with approval from two maintainers).
