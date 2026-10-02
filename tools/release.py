#!/usr/bin/env python3
"""Package a built plugin as one shareable zip with an installer and generated install instructions.

  tools/release.py --so build/x.so --skin "build/skin/<vendor> - VST - <name>" --entry build/pluginlist-entry.xml \
      --version 1.0.0 [--extra DIR:sub] [--bench bench.json] [--about "one line"] [-o dist]

The zip unpacks to <Name>-<version>/ with:
  install.sh / uninstall.sh   run on the device as root (MPC is stopped and restarted, MPC.settings is backed up)
  portable/<skin>/            the plugin as ONE self-contained folder, copied into a Synths folder (default /sdcard/Synths):
                              version.xml, plugin-meta.xml (file="%payload-path%/<skin>/<so>", the installer fills in the
                              Synths folder), the .so, Plugin Skins/ and any extras (data next to the .so)
  INSTALL.md                  generated instructions (scripted and manual), requirements, bench results
  mpc-plugin.json             machine-readable manifest for the catalog (docs/CATALOG_SPEC.md)
  plugin_list.awk, SHA256SUMS
Standard library only. See docs/RELEASING.md.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--so", required=True)
ap.add_argument("--skin", required=True, help="the skin folder '<vendor> - VST - <name>'")
ap.add_argument("--entry", required=True, help="pluginlist-entry.xml from the port's build")
ap.add_argument("--version", required=True)
ap.add_argument("--extra", action="append", default=[], help="SRC:DEST extra data, DEST relative to the plugin folder (e.g. bin:engine/bin); a leading vst/ is accepted for old scripts")
ap.add_argument("--bench", help="JSON line from `tools/bench.sh ... -j` on a Gen1 device")
ap.add_argument("--about", default="", help="one-line description for INSTALL.md")
ap.add_argument("--id", help="catalog id: lowercase letters, digits, hyphens (default: from the plugin name)")
ap.add_argument("--repo", help="source repo, owner/name (for the catalog manifest)")
ap.add_argument("--license", help="SPDX license id of the plugin (for the catalog manifest)")
ap.add_argument("--requires", default="", help="extra requirements, one line (e.g. 'MockbaMod firmware')")
ap.add_argument("--user-data", action="append", default=[], metavar="REL",
                help="path inside the plugin folder where the USER puts their own files (ROMs, kits); the installer keeps it on upgrade and moves it in from the old /sdcard/vst layout")
ap.add_argument("-o", "--out", default="dist")
a = ap.parse_args()

entry = open(a.entry).read().strip()
attr = dict(re.findall(r'(\w+)="([^"]*)"', entry))
name, so_name = attr["name"], os.path.basename(attr["file"])
if os.path.basename(a.so) != so_name:
    raise SystemExit("entry file= is %s but --so is %s" % (so_name, os.path.basename(a.so)))
skin_name = os.path.basename(os.path.normpath(a.skin))
if skin_name != "%s - VST - %s" % (attr["manufacturer"], name):
    raise SystemExit("skin folder must be named '%s - VST - %s'" % (attr["manufacturer"], name))
for need in ("version.xml", "Plugin Skins/TUI.json"):
    if not os.path.exists(os.path.join(a.skin, need)):
        raise SystemExit("skin is missing " + need)
bench = json.loads(open(a.bench).read().strip().splitlines()[-1]) if a.bench else None

slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
top = "%s-%s" % (slug, a.version)
stage = tempfile.mkdtemp()
root = os.path.join(stage, top)
os.makedirs(root)
# The plugin is ONE folder: the skin, the .so and its data. plugin-meta.xml names the .so with a %payload-path% placeholder that
# the installer fills in with wherever it puts the folder (e.g. /sdcard/Synths or /media/<card>/Synths). Engines find their data
# next to the .so (wrapper/plugin_dir.h, MODULE_SUBDIR), so extras go inside the same folder.
folder = "portable/" + skin_name
pdir = os.path.join(root, "portable", skin_name)
shutil.copytree(a.skin, pdir)
shutil.copy2(a.so, os.path.join(pdir, so_name))
extras = []
for spec in a.extra:
    src, dest = spec.split(":", 1)
    dest = dest[4:] if dest.startswith("vst/") else dest
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", dest) or ".." in dest.split("/"):
        raise SystemExit("--extra DEST must be a relative path of letters, digits, . _ - and / (no spaces or ..): %r" % dest)
    d = os.path.join(pdir, dest)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copytree(src, d, symlinks=True) if os.path.isdir(src) else shutil.copy2(src, d)
    extras.append(dest)
meta = re.sub(r'(\s)file="[^"]*"', lambda m: '%sfile="%%payload-path%%/%s/%s"' % (m.group(1), skin_name, so_name), entry, count=1)
open(os.path.join(pdir, "plugin-meta.xml"), "w").write(meta + "\n")
shutil.copy2(os.path.join(HERE, "release", "plugin_list.awk"), root)

for d in a.user_data:
    if not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", d) or ".." in d.split("/"):
        raise SystemExit("--user-data must be a relative path of letters, digits, . _ - and / (no spaces or ..): %r" % d)
legacy_so = "/sdcard/vst/" + so_name   # where the previous layout installed the .so (and its data, next to it)
sub = {"@NAME@": name, "@SO_NAME@": so_name, "@SKIN@": skin_name,
       "@EXTRAS@": " ".join("'%s'" % e for e in extras), "@VERSION@": a.version,
       "@UID@": attr["uid"], "@LEGACY_SO@": legacy_so, "@USER_DATA@": " ".join(a.user_data)}
for script in ("install.sh", "uninstall.sh"):
    text = open(os.path.join(HERE, "release", script)).read()
    for k, v in sub.items():
        text = text.replace(k, v)
    p = os.path.join(root, script)
    open(p, "w", newline="\n").write(text)
    os.chmod(p, 0o755)

# INSTALL.md
kind = "instrument" if attr.get("isInstrument") == "1" else "effect"
b = ""
if bench:
    b = ("\n## CPU\n\nMeasured on a Gen1 device (MPC Live/One/X/Force class, Cortex-A17) with `tools/bench.sh` from "
         "[mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins): worst p99 **%.1f%%** of one audio block, worst "
         "block %.1f%%, verdict **%s**. As a rule of thumb, several instances run comfortably when p99 is under 15%%.\n"
         % (bench["p99_pct"], bench["max_pct"], bench["verdict"]))
extra_md = "".join("- `%s` (data next to the plugin)\n" % e for e in extras)
user_md = ("\nYour own files go in %s inside the plugin folder (`/sdcard/Synths/%s/`); the installer keeps them when you upgrade "
           "and uninstall, and moves them there from the old `/sdcard/vst` location if you had installed the plugin that way.\n"
           % (", ".join("`%s/`" % d for d in a.user_data), skin_name)) if a.user_data else ""
install_md = """# {name} {ver}

{about}A native MPC OS plugin ({kind}) with its own MPC screen skin, loaded by MPC's built-in plugin host.

## Requirements

- A first-generation MPC OS standalone device (32-bit ARM, like the Force, MPC Live / Live II, One, X and Key 61).
  The installer refuses anything else. Newer models are untested.
- **Root shell access** (SSH) to the device. Stock MPC OS doesn't offer this; you need a modded unit.
- Tested on MPC OS with a Force. Installing plugins this way is unofficial: back up first, use at your own risk.

## Install (scripted)

1. Unzip, then copy the whole folder to the device, e.g. `scp -r {top} root@<device-ip>:/tmp/`
2. Run it: `ssh root@<device-ip> sh /tmp/{top}/install.sh`

The installer checks the device, **stops MPC** (save your project first), copies `portable/{skin}/` (the plugin, its skin
and its data, as one folder) into `/sdcard/Synths`, backs up `MPC.settings`, adds the plugin to MPC's plugin list from the
folder's `plugin-meta.xml` and starts MPC again. Running it again upgrades in place, keeping your own files.
An older install of this plugin (the previous layout, with the `.so` in `/sdcard/vst`) is replaced, not duplicated.
`-y` skips the confirmation prompt; `-t <folder>` installs into another Synths folder (for example on a card).
{user_md}
Then add **{name}** to a track from the plugin browser ({where}). Its screen appears in the plugin view,
and the Q-Links follow the page.

## Uninstall

`ssh root@<device-ip> sh /tmp/{top}/uninstall.sh` removes the plugin folder and the plugin-list entry (it also stops and
restarts MPC). Projects that use the plugin will load without it. Files you added yourself are kept.

## Install by hand

1. Copy `portable/{skin}/` to `/sdcard/Synths/{skin}/`. It holds `{so}`, `plugin-meta.xml`, `version.xml`, `Plugin Skins/`
   and the data:
{extra_md}2. Stop MPC: `systemctl stop acvs`. If there is no `acvs` service (`systemctl cat acvs` fails, as on some MPC OS 2.x versions and on Hakai-enabled systems), use `systemctl stop inmusic-mpc`.
3. Back up the settings file, `MPC.settings` (on a Force: `/media/az01-internal/Settings/MPC/MPC.settings`).
4. In `MPC.settings`, inside `<VALUE name="pluginList-arm"><KNOWNPLUGINS>`, add the line from `plugin-meta.xml` with
   `%payload-path%` replaced by `/sdcard/Synths`. If there is no `pluginList-arm` value yet, add one just before `</PROPERTIES>`:
   ```xml
   <VALUE name="pluginList-arm">
     <KNOWNPLUGINS>
       (the line from plugin-meta.xml)
     </KNOWNPLUGINS>
   </VALUE>
   ```
5. Start MPC: `systemctl start acvs`, or `systemctl start inmusic-mpc` if that is the service you stopped. If MPC shows default settings, restore your backup (the XML was malformed).

Edit `MPC.settings` only while MPC is stopped: MPC can save its own copy over a change made while it runs. Tools that
rebuild the whole plugin list from the plugin folders in `Synths` keep this plugin, because it is such a folder.
{bench}
## Files

See `SHA256SUMS`. Made with [mpc-vst-plugins](https://github.com/sd88me/mpc-vst-plugins).
""".format(name=name, ver=a.version, about=(a.about + "\n\n") if a.about else "", kind=kind, top=top, so=so_name,
           skin=skin_name, extra_md=extra_md, bench=b, user_md=user_md,
           where="Instrument plugins" if kind == "instrument" else "Insert effects")
open(os.path.join(root, "INSTALL.md"), "w").write(install_md)

def max_glibc(path):
    """Highest GLIBC_x.y[.z] symbol version the .so asks for, as 'x.y[.z]' (None if it needs none)."""
    found = re.findall(rb"GLIBC_(\d+(?:\.\d+){1,2})", open(path, "rb").read())
    return max((f.decode() for f in found), key=lambda v: tuple(map(int, v.split(".")))) if found else None


def elf_machine(path):
    d = open(path, "rb").read(20)
    return {40: "armv7", 62: "x86_64", 183: "aarch64", 3: "x86"}.get(int.from_bytes(d[18:20], "little"), "unknown") if d[:4] == b"\x7fELF" else "not-elf"


def walk(top):
    """Every file and symlink under top (symlinks, including ones to directories, are not followed)."""
    for d, dirs, files in os.walk(top):
        dirs.sort()
        for f in sorted(files + [x for x in dirs if os.path.islink(os.path.join(d, x))]):
            yield os.path.join(d, f)


plugin_id = a.id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", plugin_id):
    raise SystemExit("--id must be lowercase letters, digits and hyphens")
manifest = {
    "schema": 1,
    "id": plugin_id,
    "name": name,
    "version": a.version,
    "kind": kind,
    "uid": attr["uid"],
    "manufacturer": attr["manufacturer"],
    "layout": "portable",
    "so": so_name,
    "skin": skin_name,
    "folder": folder,
    "extras": extras,
    "user_data": a.user_data,
    "arch": elf_machine(a.so),
    "max_glibc": max_glibc(a.so),
    "param_compat": int(a.version.split(".")[0]),
    "about": a.about,
    "requires": a.requires,
    "source_repo": a.repo,
    "license": a.license,
    "cpu": {"p99_pct": bench["p99_pct"], "max_pct": bench["max_pct"], "verdict": bench["verdict"]} if bench else None,
}
open(os.path.join(root, "mpc-plugin.json"), "w").write(json.dumps(manifest, indent=2) + "\n")
# a copy travels with the installed folder, so a device-side manager can tell which version is installed
open(os.path.join(pdir, "mpc-plugin.json"), "w").write(json.dumps(manifest, indent=2) + "\n")

# MODES: the executable files and symlinks inside the plugin folder (tab separated: "x<TAB>path", "l<TAB>path<TAB>target").
# A zip unpacked on Windows, or copied file by file, loses exec bits and turns symlinks into small text files; install.sh
# re-applies this list after copying so an engine's bundled binaries (yt-dlp, ffmpeg, a private Python) still run.
modes = []
for p in walk(pdir):
    rel = os.path.relpath(p, pdir)
    if "\t" in rel or "\n" in rel:
        raise SystemExit("a file name with a tab or newline can't go in MODES: %r" % rel)
    if os.path.islink(p):
        modes.append("l\t%s\t%s" % (rel, os.readlink(p)))
    elif os.stat(p).st_mode & stat.S_IXUSR:
        modes.append("x\t" + rel)
open(os.path.join(root, "MODES"), "w", newline="\n").write("\n".join(modes) + ("\n" if modes else ""))

sums = []
for p in walk(root):
    if not os.path.islink(p):
        sums.append("%s  %s" % (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.relpath(p, root)))
open(os.path.join(root, "SHA256SUMS"), "w").write("\n".join(sums) + "\n")

os.makedirs(a.out, exist_ok=True)
zpath = os.path.join(a.out, top + "-mpc-armv7.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for p in walk(root):
        info = zipfile.ZipInfo(os.path.relpath(p, stage), date_time=(2026, 1, 1, 0, 0, 0))
        info.create_system = 3   # unix, so modes and symlinks survive
        if os.path.islink(p):
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, os.readlink(p))
        else:
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | (0o755 if os.stat(p).st_mode & stat.S_IXUSR else 0o644)) << 16
            with open(p, "rb") as f:
                z.writestr(info, f.read())
shutil.rmtree(stage)
print("%s (%d files, %.1f MB)" % (zpath, len(sums) + 1, os.path.getsize(zpath) / 1e6))
