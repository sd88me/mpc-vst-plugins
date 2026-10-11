---
title: Install a plugin
nav: Install
order: 10
summary: Install, update and remove plugins on your MPC or Force with the MPC plugin installer app. The manual ways are at the bottom.
---

The easiest way to put plugins from the catalog on your MPC or Force is the **MPC plugin installer**: a small app you run on your computer. You pick plugins from a list (or drop zip files into it), press Install, and it does the rest: it checks every download, copies the plugins to your device, and restarts MPC once. You do not type any commands.

> Installing plugins this way is unofficial. It edits MPC's settings file, so it needs **root (SSH) access**, which stock MPC OS does not offer. These plugins are for modded units. Back up your projects first and use it at your own risk.

## What you need
- A first-generation MPC OS standalone device with a 32-bit ARM processor: Force, MPC Live and Live II, One, X and Key 61. The installer refuses anything else. Newer models are untested.
- MPC OS 2.x (for example 2.15) ships an older system library (glibc, about 2.32) than MPC OS 3.x and the Force (2.39 where checked). A plugin built to need no newer than glibc 2.32 can work on both; one that needs more is still listed but marked **MPC OS 3.x only**, and the catalog checks this from the plugin's files. A plugin from elsewhere, or an old build, may be listed by MPC and still not load.
- Each plugin card says which MPC OS it works on: **MPC OS 2.x + 3.x** or **MPC OS 3.x only** (hover for the reason). On MPC OS 2.x a 3.x-only plugin still loads and plays from the Q-Links, but its touchscreen page stays empty; making it work there is up to the plugin's developer, who can publish a release with a compatible skin (the badge then changes by itself). The catalog works the label out from the plugin's files: it is a check against MPC OS 2.15.1's own skins and system library, not a test on every 2.x unit, and "tested" is added only when a 2.x device test is listed. The *MPC OS* filter narrows the list. The installer app and the install script read your device's system library and warn before installing a plugin that will not load, or a 3.x-only one onto a device that looks like MPC OS 2.x; they never block.
- Root SSH access to the device, and its IP address. The address is assigned by your router, so look it up on the device or in your router each time.
- A Windows, Mac or Linux computer on the same network as the device.
- Optional: an SD card or USB drive in the device, if you want plugins on it instead of on the internal drive (see "Where it goes" under step 5).

## Check that you can reach your device
Find the IP address in the device's network settings, or in your router's list of connected devices. It can change, so check it each time. The app tests the connection for you when you press **Connect**, but you can try it first from a terminal (Terminal on a Mac, PowerShell on Windows 10 or later):

```
ssh root@<device-ip>
```

Answer `yes` to the fingerprint question. You should get a shell prompt on the device; type `exit` to leave. If this does not work, fix it first, because every way of installing uses it. In an SSH app such as [Termius](https://termius.com/), the same test is adding a host with the IP and the username `root`, then connecting.

| You see | Usually means |
|---|---|
| `ssh: connect to host ... timed out` | Wrong IP, the device is asleep, or it is on a different network. |
| `Permission denied` | Root SSH is not enabled on this unit, or the password is wrong. |

## 1. Download the app
Open [the latest release](https://github.com/sd88me/mpc-vst-plugins/releases/latest) and download the file for your computer from **Assets**:

| Your computer | Download the file that ends with |
|---|---|
| **Windows** (almost every PC) | `-windows.zip` |
| **Mac with an Apple chip** (M1, M2, M3, M4 or later: any Mac from late 2020 on) | `-mac-apple-silicon.tar.gz` |
| **Mac with an Intel chip** (older Macs: Apple menu, About This Mac, says "Intel") | `-mac-intel.tar.gz` |
| Linux | `-linux.tar.gz` |
| Windows or Linux on an ARM chip (rare) | `-windows-arm64.zip` or `-linux-arm64.tar.gz` |

Unpack it. You get one program, `mpc-installer`, and a short `README.txt`. The release also has a `SHA256SUMS` file if you want to check your download.

## 2. Start it
Double-click `mpc-installer` (or run it in a terminal). It prints a link and opens it in your browser. The page only works on your own computer.

The first time, your system warns that the program is from an unknown developer, because it is not signed:

- **Windows:** "Windows protected your PC": click **More info**, then **Run anyway**.
- **Mac:** it will not open on a double-click. Right-click the file, choose **Open**, then **Open** again. If that does not work, run `xattr -d com.apple.quarantine mpc-installer` in a terminal.
- **Linux:** run `chmod +x mpc-installer` if the file does not start.

## 3. Connect to your device
Type your device's IP address. Leave the password empty if you log in to the device with an SSH key; otherwise type the password. Press **Connect**. The page shows what it found: the device type, the plugin folders already on it, and the places plugins can go: the internal drive, and any SD card or USB drive that has a `Synths` folder, each with its free space. The password is used for that one connection and is not saved, and nothing about your device is stored on your computer.

## 4. Choose plugins
The list shows every plugin in the catalog that has a download, with its version, size and a short description. Tick the ones you want. A plugin that is already on your device is marked **on the device**, and if the catalog has a newer version than the one you installed, it shows **update**.

With many plugins, use the search box, the filters (kind, developer, whether it is already on the device or has an update) and the sort. What you tick stays ticked while you filter, and a bar at the bottom shows how many you have picked.

You can also **drop zip files** into the box under the list: plugins you downloaded yourself, or ones you built. A plugin marked **Build it yourself** in the catalog has no download, because it contains data from your own firmware; the [Build](build.html#plugins-you-build-yourself) page shows how to make the zip. The page checks each zip before it accepts it and tells you if something is wrong with it.

## 5. Install
Press **Install…** and read the question. **Save your project on the device first**: MPC is stopped and started again. Confirm, and watch the log. The app:

- downloads each zip and checks it against the checksum in the catalog, before it changes anything on your device (if a checksum does not match, nothing is installed);
- copies the plugins to the device, stops MPC once, runs each plugin's own installer, and starts MPC again;
- makes a backup of MPC's settings file first, and starts MPC again even if something fails.

**Where it goes.** If your device has an SD card or a USB drive with a `Synths` folder as well as its internal drive, an **Install to** choice appears above the Install button. The internal drive is the default. A card or drive works too, with three things to know: MPC must list its `Synths` folder as a content location, or a plugin's screen may not show (the page tells you if it does not); a drive that is formatted exFAT or FAT cannot store the symbolic links some plugins need (Crate Digger's bundled Python), so the app refuses those installs and tells you to use the internal drive; a drive mounted `noexec` (a Force's SSD is) is refused as well, because MPC cannot load plugins from it; and if the drive is not in when MPC starts, its plugins drop out of MPC's plugin list until you register them again (see "Register plugin folders").

Some older releases have an installer that restarts MPC by itself, so MPC may restart more than once; the page says so before you confirm and the log shows it. Newer releases are installed in one go.

## 6. Use it
On the device, add the plugin to a track from the plugin browser: instruments under Instrument plugins, effects under Insert effects. Its screen appears in the plugin view, and the Q-Links follow the page. Save and reload a project once to make sure it comes back. If you turn on the manufacturer tab at the bottom of the browser, plugins are grouped by developer.

## Update to a new version
Start the app, connect, and tick the plugin that shows **update**, then install as above. The new version replaces the old files in place and keeps the same plugin entry, so your projects still find the plugin. Files you added yourself (ROMs, kits, banks) are kept. A plugin you installed with an older release (the `.so` in `/sdcard/vst`) is replaced and your files are moved into its new folder in `/sdcard/Synths`.

The catalog shows a **Compat** number for each version. If it goes up, the parameters changed, and projects saved with an older version will sound different. Read the release notes before updating a plugin you use in finished songs. If MPC still runs the old version afterwards, remove every copy of the plugin from your project and insert it again.

## Remove a plugin
In the app, open **Remove plugins** (step 4 on the page; click **Show**; plugins are grouped by the drive they are on), tick the plugin and press **Remove…**. MPC is stopped once, MPC's settings are backed up and the plugin is taken out of the plugin list, then its folder is deleted **except your own files** (ROMs, kits and dumps are kept), and MPC is started again. Projects that used the plugin still open, without it.

The app only removes plugins it can identify: ones from the catalog, or ones whose zip you have dropped into the page. For any other plugin it cannot tell which files in the folder are yours, so it lists the plugin but does not offer to remove it. Drop that plugin's zip to manage it, or remove it by hand.

## Register plugin folders
A plugin only shows up in MPC once it is in MPC's plugin list. Folders you copied into a `Synths` folder yourself, plugins from other collections, or plugins MPC forgot (for example because a card was out when MPC started) are not in the list. In the app, open **Register plugin folders** (step 5 on the page; click **Show**). If something is waiting, a count appears next to the title and the list shows each folder and where it is. Press **Register…**: MPC is stopped once, its settings are backed up and the folders are added to the plugin list (entries whose plugin file is gone are dropped), and MPC is started again. Everything else in the list stays as it is.

## Clean up old backups
Every install, removal and sync makes a copy of MPC's settings file on the device, and nothing deletes them, so they pile up (they are small). In the app, open **Clean up old backups** (step 6 on the page; click **Show**), choose how many of the newest to keep (10 is a good number) and press **Delete older backups…**. The newest backup is never deleted, MPC is not restarted, and nothing but the backups is touched.

## Advanced: device patches
At the bottom of the app, step 7 (**Advanced: device patches**, collapsed) lists community patches that change the device itself, not a plugin. An example is the 16-pad drum layout for some plugins, which changes Akai's own MPC program. **This is not for most people**, and the app only looks: open the step (or press **Check the device**) and it asks the device which patches are applied. It cannot apply or undo a patch yet; each row links to a guide for running the script yourself over SSH. The same patches, with what each one changes, its backup and its script checksum, are on the [Device patches](patches.html) page.

Three patches are listed today: the 16-pad drum layout (it changes Akai's MPC program), the **drive exec patch** (it lets MPC load plugins from a drive mounted `noexec`, such as an MPC/Force's SSD, by making one folder of the drive executable; it adds a service to the device; the original was tried on one Force by its author, and this adapted version is **untested on a device so far, testers are wanted**), and the **button remap** (an LD_PRELOAD shim that turns a hardware button into other buttons, a pad or a screen tap; its author tried it on an MPC Live with Hakai and on a Force, and this installer is **untested on a device so far, testers are wanted**: it edits MPC's launcher or adds a service drop-in, remounts the root filesystem writable for a moment and restarts MPC, so keep an SSH session open and know how to run its `uninstall` before you try it). A row can also say **Installed, not active** (the patch is installed but not in effect right now, for example because a drive is not mounted, or because MPC has not loaded the remap).

A row can say **This firmware is not supported**. That is the patch refusing, on purpose: it only works on one exact build of MPC OS, checked by a checksum, and the row shows your device's checksum and what the patch supports. If an earlier install left a backup of the stock program, the patch's guide explains how to restore it first.

## If a plugin disappears after a restart
MPC keeps its whole plugin list in one place: the `pluginList-arm` list in its settings file, `MPC.settings`. Every way of installing plugins edits that same list, so one method can undo another. The plugin's files usually are still on the card; only its line in the list is gone. The usual causes:

- **The settings file was edited while MPC was running.** MPC holds its settings in memory while it runs and saves them itself, so a change made underneath it can be overwritten. Stop MPC first (`systemctl stop acvs`; if `systemctl cat acvs` finds no such service, as on some MPC OS 2.x versions and on Hakai-enabled systems, the service is `inmusic-mpc`), edit, then start it (`systemctl start acvs`). The app and the installers do this for you.
- **Another tool rebuilt the whole list.** Some community installers and scan scripts do not add one line: they write a new list from the plugin folders they find in the `Synths` folders (each folder with a `plugin-meta.xml` inside). A plugin that is not such a folder, for example one added by hand or installed by an older release with its `.so` in `/sdcard/vst`, drops off the list at the next scan. A release is such a folder if its zip has a `portable/` folder inside, and a scan keeps it. Reinstall anything older with a release that has one.
- **The settings file became invalid.** After a broken edit MPC resets `MPC.settings` to its defaults, which empties the plugin list along with your other preferences. Restore a backup (below).
- **The line points to a file that is not there**: a plugin folder was moved or renamed, or the card it is on is not inserted.

Check what MPC has registered, and whether each file exists (on the device, over SSH):

```
grep -o 'file="[^"]*"' /media/az01-internal/Settings/*/MPC.settings | cut -d'"' -f2 |
    while read -r f; do [ -f "$f" ] && echo "ok       $f" || echo "MISSING  $f"; done
```

To get plugins back:
- **Register the plugin folders** in the app (step 5, "Register plugin folders"). If the plugin's folder is still on the device or its card, this adds its line back to the list without reinstalling anything. This is the quickest fix, and the right one when a card was out when MPC started.
- **Install the plugin again** (the current release) with the app. It adds its own line back and leaves every other plugin's line alone. This is the safest fix.
- **Or restore a backup of the settings file.** The app and the installers leave one next to the original each time they change it, named `MPC.settings.bak-<plugin>-<date>` (or `bak-remove-…`, `bak-sync-…`). List them newest first with `ls -t /media/az01-internal/Settings/*/MPC.settings.bak-*`, then stop MPC, copy the one you want over `MPC.settings`, and start MPC. A backup also brings back the preferences you had at that time.

Before you paste a command you found online into the device's shell, copy the settings file to your computer: `scp "root@<device-ip>:/media/az01-internal/Settings/*/MPC.settings" .` Any command that rebuilds, restores or resets that file replaces your whole plugin list.

## If something goes wrong
- **The app cannot connect.** Check the IP address (it can change), that the device is on and on the same network, and that SSH is enabled. If you use a password, check it; otherwise the app only tries an SSH key in `~/.ssh` that has no passphrase.
- **The app says it cannot install on this device.** It only installs to a 32-bit ARM MPC OS device where you are logged in as root.
- **MPC shows default settings after the restart.** The edited settings file was not accepted. Restore the backup the installer made, next to `MPC.settings` (see above).
- **The plugin is not in the list.** MPC reads its plugin list at startup. Check that the app's log ended with "Done", then see "If a plugin disappears after a restart" above.
- **The plugin is in the list but only "Load Plugin" shows.** MPC could not load the library. Two usual causes: the plugin sits on a drive mounted `noexec` (an MPC/Force's SSD is; check with `mount | grep noexec`, and install to the internal drive or an SD card instead, or, if you are comfortable with SSH, the optional **drive exec patch** listed in the app's "Advanced: device patches" step, which makes one folder of the drive executable: it is untested on a device so far, read its guide first, it adds a small service to the device), or it is a build that needs a newer glibc than your MPC OS has (a copy installed by hand, or a version older than the catalog's current one). Install the newest version from the app. If it still fails, send the `journalctl -u acvs` lines (or `journalctl -u inmusic-mpc` where there is no acvs) from the moment you add the plugin to a track, plus the output of `ls -l /lib/libc.so.6`.
- **The page is empty on MPC OS 2.x.** The plugin is marked *MPC OS 3.x only*: its skin is in the newer format, which MPC OS 2.x does not draw. It still plays from the Q-Links. Look for a release marked *MPC OS 2.x + 3.x*, or ask the plugin's developer for one.
- **The plugin loads but has no screen.** The skin goes in a `/sdcard/Synths` folder, and MPC must have that folder in its content locations. The installer warns if it does not.
- **Silence, or default sounds.** Some plugins need files you provide, such as ROMs or banks. Check the plugin's own page.

Ask in the community with the plugin's name, version, your device model and the installer's output (the log in the app).

## Other ways to install
You do not need any of these if you use the app. They are here for people who prefer a terminal, or who cannot run the app. Each one installs the same release zips, with the same installer, so they can be mixed.

::: details One command for several plugins (no app to download)
On the [catalog](index.html), tick **Add to install list** on each plugin you want, open the bar that appears at the bottom, type your device's IP address and copy the command. Paste it into a terminal (Terminal on a Mac, PowerShell on Windows 10 or later) and press Enter. The command logs in to your device, downloads a small script (`mpc-store.sh`) from this site and runs it. The script:

- downloads every zip you picked and checks it against the checksum in the catalog, before it changes anything on the device;
- asks you to confirm, then stops MPC **once**, runs each plugin's own installer, and starts MPC again **once**;
- remembers what it installed, so `update` later installs newer versions (and holds back a change that would alter saved projects unless you add `--major`).

Prefer to read the script before running it? The bar has a "Read the script first" section with the steps and the hash the script should have. The same command with `list`, `update`, `remove <id>`, `prune` or `sync` at the end shows what is available, updates what you installed, removes a plugin (your own files in its folder are kept), deletes old backups of MPC's settings (`prune --keep 10`), or registers plugin folders you copied into `Synths` by hand. It needs the same root SSH access, and the device needs internet access. Plugins you build yourself are not included.
:::

::: details By hand with ssh and scp (download, copy, run)
**1. Download and check the zip.** Download the zip from the plugin's card on the catalog. Every version lists a checksum (SHA-256). Compare it with your download:

```
shasum -a 256 Name-1.2.0-mpc-armv7.zip      # macOS and Linux
certutil -hashfile Name-1.2.0-mpc-armv7.zip SHA256    # Windows
```

If the first characters do not match the catalog, download it again. Also open the plugin's source link and read what you are about to run as root: the installer is a plain shell script.

**2. Copy it to the device.** Unzip it, then copy the whole folder over:

```
unzip Name-1.2.0-mpc-armv7.zip
scp -r Name-1.2.0 root@<device-ip>:/tmp/
```

**3. Run the installer.** Save your project on the device first. The installer **stops MPC and starts it again**.

```
ssh root@<device-ip> sh /tmp/Name-1.2.0/install.sh
```

It checks the device, stops MPC, copies the plugin folder (the plugin, its skin and its data) into `/sdcard/Synths`, backs up `MPC.settings` next to the original, adds the plugin to MPC's plugin list and starts MPC again. Add `-y` to skip the confirmation question. If anything fails, MPC is restarted and your settings are left unchanged.

**Update:** run the new version's `install.sh` the same way. **Remove:** run `ssh root@<device-ip> sh /tmp/Name-1.2.0/uninstall.sh`; it removes the files and the plugin-list entry (after a backup), keeps your own files, and restarts MPC.
:::

::: details With Termius (click instead of type)
If you would rather click than type, use an SSH app with a file browser. [Termius](https://termius.com/) is one (macOS, Windows, Linux, iPhone, iPad and Android); other SFTP and SSH apps work the same way. You do the same two things as steps 2 and 3 of the "By hand" version, with the mouse:

1. **Add your device as a host.** In Termius, add a new host with the device's IP address and the username `root`, using the same login you would use with `ssh`. Connect once to check it works.
2. **Copy the folder over.** Unzip the plugin's zip on your computer first. Open the host's file browser (SFTP), go to `/tmp` on the device, and drag the unzipped plugin folder into it.
3. **Run the installer.** Open a terminal on the same host and type `sh /tmp/<the-folder-name>/install.sh` (Tab completes the folder name). Save your project first: it stops and restarts MPC. Answer `y` when it asks, or add `-y` to skip the question.

The app's buttons and plans change over time, so check Termius's own help if a screen looks different. It is only a nicer way to copy and run: the plugin, the checksum check and the installer are the same.
:::

::: details Fully by hand (without the installer script)
Each zip's `INSTALL.md` lists the manual steps: copy the plugin folder (`portable/<Vendor> - VST - <Name>/` in the zip) to `/sdcard/Synths/`, stop MPC (`systemctl stop acvs`), back up `MPC.settings`, add the line from that folder's `plugin-meta.xml` to the plugin list with `%payload-path%` replaced by `/sdcard/Synths`, and start MPC (`systemctl start acvs`, or `inmusic-mpc` if that is the service you stopped). Edit the settings file only while MPC is stopped (see "If a plugin disappears after a restart" above).

If you use a community tool that scans `Synths` folders for plugins, the same plugin folder works there: copy it into `Synths` and run the scan. Such a scan rebuilds the whole plugin list from the folders it finds, so it drops any plugin that is not such a folder, and it does not back up your settings first.
:::
