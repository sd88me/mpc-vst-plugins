#!/usr/bin/env bash
# The scheduled thumbnail check (.github/workflows/plugin-manager-g2-thumbs.yml): the manager's skin has a thumbnail baked in for every catalog
# plugin that had a screenshot when it was built, so a plugin added later shows initials until a new release. This regenerates them from the
# live catalog and, if there are NEW ones, pushes a branch and opens a PR for a person to review and release (or, when GitHub Actions may not
# create pull requests, an issue with a compare link). Images already in the repo are kept exactly as they are.
#   DRY=1 vst/thumbs_check.sh     stop before pushing anything
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
P=tools/plugin_manager_g2
python3 "$P/vst/shots.py"
# the encoder differs between machines: keep every image that is already tracked, so only a new plugin's files remain as changes
git ls-files "$P/vst/images/shots" "$P/vst/images/shots_detail" | xargs -r git checkout --
if [ -z "$(git status --porcelain "$P")" ]; then echo "thumbnails are up to date"; exit 0; fi
new=$(git status --porcelain "$P/vst/images/shots" | sed -n 's|^?? .*/shots/\(.*\)\.png$|\1|p' | tr '\n' ' ')
echo "new thumbnails: ${new:-none (the plugin list changed)}"
[ -z "${DRY:-}" ] || { git status --short "$P" | head -n 12; exit 0; }
branch="pm-g2-thumbs-$(date -u +%Y%m%d)"
if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then echo "$branch already exists: nothing more to do"; exit 0; fi
git config user.name "github-actions"
git config user.email "github-actions@users.noreply.github.com"
git checkout -q -b "$branch"
git add -A "$P"
git commit -q -m "plugin manager G2: thumbnails for new catalog plugins (${new:-list changed})"
git push -q origin "$branch"
title="plugin manager G2: thumbnails for new catalog plugins"
body="The catalog gained plugins with screenshots since the last build: ${new:-the plugin list changed}. This branch (\`$branch\`) adds their thumbnails to the manager's skin. They only reach devices in the next manager release; review, merge, then run the release workflow when you want to ship them. (Each release resets the Verified badge until it is device-tested.)"
if gh pr create --base main --head "$branch" --title "$title" --body "$body" 2>/dev/null; then exit 0; fi
gh issue create --title "$title" --body "$body

Open a pull request: https://github.com/${GITHUB_REPOSITORY:-sd88me/mpc-vst-plugins}/compare/main...$branch?expand=1"
