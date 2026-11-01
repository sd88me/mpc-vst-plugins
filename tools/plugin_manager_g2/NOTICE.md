# Who wrote what

| Source | Licence | How it is used here | Credit / permission |
|---|---|---|---|
| poloq, `poloq-instruments/mpc-vst-manager` @ `f01948b` (1.2.0) | MIT | the whole code base is the starting point (git history kept, remote `upstream`) | `LICENSE` keeps poloq's notice |
| jacob-sabella, poloq PR #1 and later commits on the manager | MIT (same repo) | addin support (catalog kind `addin`, `/data/mpc-addins/<id>`), the offline addin fixture and test, the Key 37 test pass, the Instruments-browser tile | part of poloq's repo history, kept; credited in the README |
| `sd88me/mpc-vst-plugins` (catalog, installers, Gen2 findings, PR #12 "Gen2 compatibility") | MIT | catalog format, `install.sh` contract, device facts; PR #12 is the author's own | none needed |
| Eurikon, `plugin-manager-usb-for-open-mpc` | MIT | **ideas first** (see DESIGN.md section 4); copy code only file by file, with the file's notice and a line in this table | credit in README when anything is copied |
| FullPace ("Padbangers"), poloq PRs #7 and #8 (64-entry catalog limit; reworked screen) | **not stated** on the PRs | read for ideas; **do not copy code until they say yes** (ask on the PR). They asked to be credited as **Padbangers**, not the account name | ask first; credit as Padbangers |
| lionel-lints, camerondphillips, Potreba, djru5h (issues #3, #4, #5, #9, #10) | n/a (bug reports) | requirements; we write our own fixes | thanks in the changelog |

Nothing of Akai's (firmware, stock skins) or Steinberg's SDK is in this repo, and none may be added.
