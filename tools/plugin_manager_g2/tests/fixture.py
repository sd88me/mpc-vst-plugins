#!/usr/bin/env python3
"""The offline addin fixture for tests/run.sh: three addin packages made with mpc-vst-plugins' release_addin.py from
stand-in files (a fake ELF, a conf), and a catalog.json listing them with file:// downloads, in vst/build/tests/.
alpha and gamma are also "installed" by tests/addins.sh (alpha older and removable, gamma by hand); beta is new."""
import hashlib, json, os, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
mv = os.environ.get("MPC_VST", os.path.join(root, "..", ".."))
out = os.path.join(root, "vst", "build", "tests")
os.makedirs(out, exist_ok=True)
ADDINS = [("alpha-addin", "Alpha addin", "0.1.0"), ("beta-addin", "Beta addin", "1.2.0"), ("gamma-addin", "Gamma addin", "0.3.0")]
plugins = []
for aid, name, ver in ADDINS:
    base = aid.replace("-", "_")
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "addin.manifest"), "w").write(
            'ADDIN_ID=%s\nADDIN_NAME="%s"\nADDIN_SO=%s.so\nADDIN_CONF=%s.conf\nADDIN_FILES=""\n' % (aid, name, base, base))
        hdr = bytearray(b"\x7fELF" + bytes(16))
        hdr[18:20] = (40).to_bytes(2, "little")   # armv7
        open(os.path.join(d, base + ".so"), "wb").write(bytes(hdr) + b"\0GLIBC_2.30\0")
        open(os.path.join(d, base + ".conf"), "w").write("# settings\n")
        subprocess.run([sys.executable, os.path.join(mv, "tools", "release_addin.py"), "--dir", d, "--version", ver,
                        "--repo", "acme/mpc-addin-" + aid, "--license", "MIT", "--about", "A stand-in addin for the tests.",
                        "-o", out], check=True, stdout=subprocess.DEVNULL)
    zpath = os.path.join(out, "%s-%s-mpc-armv7.zip" % (name.replace(" ", "-"), ver))
    data = open(zpath, "rb").read()
    plugins.append({"id": aid, "name": name, "author": "acme", "repo": "acme/mpc-addin-" + aid, "kind": "addin",
                    "license": "MIT", "summary": "A stand-in addin for the tests.", "style": "utility", "tags": ["test"],
                    "distribution": "release", "latest": ver,
                    "versions": [{"version": ver, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                  "url": "file:///p/vst/build/tests/" + os.path.basename(zpath), "channel": "stable",
                                  "date": "2026-01-01", "yanked": False}]})
# a plugin (not an addin) whose package needs a symbolic link (MODES line "l"): refused on a drive that cannot store links
import zipfile
lz = os.path.join(out, "Linky-1.0.0-mpc-armv7.zip")
with zipfile.ZipFile(lz, "w") as z:
    for name, body in (("install.sh", "#!/bin/sh\nexit 0\n"), ("uninstall.sh", "#!/bin/sh\nexit 0\n"),
                       ("MODES", "x\tinstall.sh\nl\tlib/a.so\tb.so\n"), ("mpc-plugin.json", "{}\n")):
        z.writestr("Linky-1.0.0/" + name, body)
data = open(lz, "rb").read()
plugins.append({"id": "linky", "name": "Linky", "author": "acme", "repo": "acme/mpc-vst-linky", "kind": "instrument",
                "license": "MIT", "summary": "A stand-in plugin whose package needs a symbolic link.", "style": "utility", "tags": ["test"],
                "distribution": "release", "latest": "1.0.0",
                "versions": [{"version": "1.0.0", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                              "url": "file:///p/vst/build/tests/" + os.path.basename(lz), "channel": "stable",
                              "date": "2026-01-01", "yanked": False}]})
# the zip for the device: "Dual" has a (missing) armv7 zip and a real aarch64 one, "Armonly" only an armv7 one (nothing to install on Gen2)
base = "file:///p/vst/build/tests/"
sha = hashlib.sha256(data).hexdigest()
for name, date, assets in (("Dual", "2026-02-01", {"armv7": {"url": base + "missing-armv7.zip", "sha256": "0" * 64, "size": 1},
                                                    "aarch64": {"url": base + os.path.basename(lz), "sha256": sha, "size": len(data)}}),
                           ("Armonly", "2026-01-01", {"armv7": {"url": base + os.path.basename(lz), "sha256": sha, "size": len(data)}})):
    plugins.append({"id": name.lower(), "name": name, "author": "acme", "repo": "acme/mpc-vst-" + name.lower(), "kind": "effect",
                    "license": "MIT", "summary": "A stand-in for the per-architecture zips.", "style": "utility", "tags": ["test"],
                    "distribution": "release", "latest": "1.0.0",
                    "versions": [{"version": "1.0.0", "size": 1, "sha256": "0" * 64, "url": base + "missing-armv7.zip", "assets": assets,
                                  "channel": "stable", "date": date, "yanked": False}]})

# M3: a package whose install.sh fails after writing part of its folder (rolled back), one built for the other architecture (refused before
# MPC stops) and one whose zip has a "../" name (refused before unpacking). All effects, older than Dual/Armonly so the cards keep their order.
def pkg(name, files, date):
    zp = os.path.join(out, "%s-1.0.0-mpc-armv7.zip" % name)
    with zipfile.ZipFile(zp, "w") as z:
        for fn, body in files:
            z.writestr(fn, body)
    d = open(zp, "rb").read()
    plugins.append({"id": name.lower(), "name": name, "author": "acme", "repo": "acme/mpc-vst-" + name.lower(), "kind": "effect",
                    "license": "MIT", "summary": "A stand-in for a failing package.", "style": "utility", "tags": ["test"],
                    "distribution": "release", "latest": "1.0.0",
                    "versions": [{"version": "1.0.0", "size": len(d), "sha256": hashlib.sha256(d).hexdigest(),
                                  "url": base + os.path.basename(zp), "channel": "stable", "date": date, "yanked": False}]})
FAIL_SH = ('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -t ] && T=$2; shift; done\n'
           'mkdir -p "$T/Faily dir" && echo partial > "$T/Faily dir/partial" && echo "disk full" && exit 3\n')
pkg("Faily", [("Faily-1.0.0/install.sh", FAIL_SH), ("Faily-1.0.0/uninstall.sh", "#!/bin/sh\nexit 0\n"),
              ("Faily-1.0.0/mpc-plugin.json", '{"folder": "portable/Faily dir", "arch": "armv7"}\n')], "2025-03-01")
pkg("Wrongarch", [("Wrongarch-1.0.0/install.sh", "#!/bin/sh\nexit 0\n"), ("Wrongarch-1.0.0/uninstall.sh", "#!/bin/sh\nexit 0\n"),
                  ("Wrongarch-1.0.0/mpc-plugin.json", '{"arch": "aarch64"}\n')], "2025-02-01")
pkg("Newlib", [("Newlib-1.0.0/install.sh", "#!/bin/sh\nexit 0\n"), ("Newlib-1.0.0/mpc-plugin.json", '{"arch": "armv7", "max_glibc": "9.99"}\n')], "2024-12-01")
pkg("Oldos", [("Oldos-1.0.0/install.sh", "#!/bin/sh\nexit 0\n"), ("Oldos-1.0.0/mpc-plugin.json", '{"arch": "armv7", "os_compat": ["2.x"]}\n')], "2024-11-01")
pkg("Evil", [("Evil-1.0.0/install.sh", "#!/bin/sh\nexit 0\n"), ("Evil-1.0.0/../escape.txt", "x")], "2025-01-01")
json.dump({"schema": 1, "plugins": plugins}, open(os.path.join(out, "catalog.json"), "w"), indent=1)
print("fixture: %d packages in %s" % (len(plugins), out))
