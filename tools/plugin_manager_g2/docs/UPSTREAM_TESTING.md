# Testing on your MPC / Force

Thanks for testing. You need SSH access as root (the same you used to install other plugins).
The test restarts MPC: **save your project first**.

## 1. Install
Download the release zip, then on the device: `unzip Plugin-Manager-*.zip && sh Plugin-Manager-*/install.sh`.
MPC restarts. Add **Plugin Manager** to a plugin track.

## 2. Check
| # | Do | Expect |
|---|---|---|
| 1 | Open the plugin | Within ~10 s the footer says `N plugins available · M updates available`; your installed plugins show **INSTALLED** or **UPDATE** |
| 2 | Tabs and page arrows | The list follows; text fits its place |
| 3 | On a small plugin you don't have (e.g. Acid): **INSTALL**, then **APPLY** | The button turns to *INSTALL · QUEUED*; a progress bar under the status, then *Ready* in amber |
| 4 | **APPLY** (now *RESTART & APPLY*) | MPC restarts by itself within ~10 s; the new plugin is in the plugin list and plays |
| 5 | Reopen the manager | That plugin shows **INSTALLED** |
| 6 | **⋮** on it, **REMOVE**, **APPLY** twice | MPC restarts; the plugin is gone from the list |
| 7 | Filter and **Sort** menus at the top; tap outside a menu | The list follows the choice; the card's last line shows the sort field; a tap outside closes the menu |
| 8 | Tap a card | Its details: screenshot, facts, description, *What's new*; **BACK** returns |
| 9 | Tap a tag in the details | The list shows the plugins with that tag and a `#tag ×` chip at the top; **×** clears it |
| 10 | **🔍**, type a few letters, **DONE** | Matches show above the keys while typing; DONE leaves them as cards with the search chip at the top |
| 11 | Queue an install, **APPLY**, wait for *Ready*, **APPLY**, then **CANCEL** | A prompt lists the change; CANCEL closes it and the change stays ready |
| 12 | **Addins** filter: **INSTALL** one, **APPLY** twice; reopen, **⋮**, **REMOVE**, **APPLY** twice | A folder appears under `/data/mpc-addins/` and the addin works after the restart; after the removal the folder is gone |

If a red banner says *Can't install on this MPC* (`No install location`, `No systemd-run`, `No unzip`, ...), stop there and
report it: that is exactly what we need to know.

## 3. Report
Open an issue or PR with:
- your model and MPC OS version, and whether it has MockbaMod or another mod;
- the table above with pass/fail per row (a photo of the screen helps if text is cut or misplaced);
- these files from the device:
  ```
  cat /tmp/openmpc-pm/device.txt /tmp/openmpc-pm/manager.log /tmp/openmpc-pm/apply.log
  ```
  `device.txt` lists your install locations, tools, and registered plugins (names and paths only).

Reports so far are in `docs/tests/`; `tested.json` lists the devices that passed.

## 4. A fix for your model (PR)
Most model differences are paths. Add a fake device to `tests/devices/<model>.sh` that recreates your `MPC.settings`
layout (locations and a few `pluginList-arm` entries, from your `device.txt`), make `tests/run.sh` pass with your
change, and include both in the PR.
