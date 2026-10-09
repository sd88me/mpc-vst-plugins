#!/usr/bin/env python3
"""Offline test of the release manifest and validator: builds a fake package with tools/release.py and checks that
tools/catalog_check.py accepts it and rejects tampered copies. No device, no toolchain: python3 tools/test_catalog.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog_check  # noqa: E402

ENTRY = ('<PLUGIN name="Test Synth" format="VST" category="Synth" manufacturer="Acme" version="1.0" '
         'file="/sdcard/vst/test_synth.so" uid="1a2b3c4d" isInstrument="1" fileTime="0" infoUpdateTime="0" '
         'numInputs="0" numOutputs="2" isShell="0" hasARAExtension="0" uniqueId="0"/>')


def fake_so(path, machine=40, glibc=b"GLIBC_2.30", elf_class=1):
    """A 32-bit little-endian ELF with just a string table and a version-needs section naming glibc (one need of
    libc.so.6 with one version), the shape the release tools read the glibc requirement from."""
    strtab = b"\0libc.so.6\0" + glibc + b"\0"
    verneed = (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (1).to_bytes(4, "little") \
        + (16).to_bytes(4, "little") + (0).to_bytes(4, "little")                                  # Elf32_Verneed
    verneed += (0).to_bytes(4, "little") + (0).to_bytes(2, "little") + (2).to_bytes(2, "little") \
        + (11).to_bytes(4, "little") + (0).to_bytes(4, "little")                                  # Elf32_Vernaux
    ehdr = bytearray(52)
    ehdr[:4] = b"\x7fELF"
    ehdr[4], ehdr[5], ehdr[6] = elf_class, 1, 1              # 32-bit (unless a test says otherwise), little-endian, version 1
    ehdr[16:18] = (3).to_bytes(2, "little")                  # ET_DYN
    ehdr[18:20] = machine.to_bytes(2, "little")
    body = bytes(ehdr) + strtab + verneed
    shoff = len(body)
    ehdr[32:36] = shoff.to_bytes(4, "little")
    ehdr[46:48] = (40).to_bytes(2, "little")
    ehdr[48:50] = (3).to_bytes(2, "little")

    def shdr(sh_type, off, size, link):
        return (0).to_bytes(4, "little") + sh_type.to_bytes(4, "little") + (0).to_bytes(8, "little") \
            + off.to_bytes(4, "little") + size.to_bytes(4, "little") + link.to_bytes(4, "little") + bytes(12)
    shdrs = shdr(0, 0, 0, 0) + shdr(3, 52, len(strtab), 0) + shdr(0x6FFFFFFE, 52 + len(strtab), len(verneed), 1)
    open(path, "wb").write(bytes(ehdr) + strtab + verneed + shdrs)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def resum(self, zpath, suffix, fn):
        """Modify one member and fix SHA256SUMS, so only the check under test can object."""
        import hashlib
        out = zpath + ".r.zip"
        with zipfile.ZipFile(zpath) as zin:
            data = {i.filename: zin.read(i.filename) for i in zin.infolist()}
            infos = list(zin.infolist())
        for n in data:
            if n.endswith(suffix):
                data[n] = fn(data[n])
        top = infos[0].filename.split("/")[0]
        sums = "\n".join("%s  %s" % (hashlib.sha256(d).hexdigest(), n[len(top) + 1:]) for n, d in sorted(data.items())
                         if not n.endswith("/") and not n.endswith("SHA256SUMS")) + "\n"
        data[top + "/SHA256SUMS"] = sums.encode()
        with zipfile.ZipFile(out, "w") as zout:
            for i in infos:
                zout.writestr(i, data[i.filename])
        return out

    def build(self, version="1.2.0", machine=40, glibc=b"GLIBC_2.30", extra=(), elf_class=1, tui="{}"):
        t = self.tmp
        fake_so(os.path.join(t, "test_synth.so"), machine, glibc, elf_class)
        skin = os.path.join(t, "Acme - VST - Test Synth")
        os.makedirs(os.path.join(skin, "Plugin Skins"), exist_ok=True)
        open(os.path.join(skin, "version.xml"), "w").write("<v/>")
        open(os.path.join(skin, "Plugin Skins", "TUI.json"), "w").write(tui)
        open(os.path.join(t, "entry.xml"), "w").write(ENTRY)
        out = os.path.join(t, "dist")
        subprocess.check_call([sys.executable, os.path.join(HERE, "release.py"), "--so", os.path.join(t, "test_synth.so"),
                               "--skin", skin, "--entry", os.path.join(t, "entry.xml"), "--version", version,
                               "--repo", "acme/test-synth", "--license", "MIT", "-o", out, *extra],
                              stdout=subprocess.DEVNULL)
        return os.path.join(out, "Test-Synth-%s-mpc-%s.zip" % (version, "aarch64" if machine == 183 else "armv7"))

    def tamper(self, zpath, member_suffix, fn):
        out = zpath + ".t.zip"
        with zipfile.ZipFile(zpath) as zin, zipfile.ZipFile(out, "w") as zout:
            for i in zin.infolist():
                data = zin.read(i.filename)
                if i.filename.endswith(member_suffix):
                    data = fn(data)
                zout.writestr(i, data)
        return out


class OsCompatTest(Base):
    """Which MPC OS generations a version works on, worked out from its skin and library (docs/OS2_SKINS.md)."""

    def check(self, z):
        return catalog_check.check(z, catalog=True, expect_id="test-synth", expect_repo="acme/test-synth")

    def test_a_skin_the_checker_cannot_read_is_3x_only(self):
        z = self.build()                                   # the fake skin is "{}"
        errors, warnings, rec = self.check(z)
        self.assertEqual(errors, [])
        self.assertEqual(rec["os_compat"], ["3.x"])
        self.assertEqual(rec["os_compat_why"], ["TUI.json has no pageData"])
        self.assertEqual(rec["manifest"]["os_compat"], ["3.x"])

    def test_a_2x_shaped_skin_is_2x_and_3x(self):
        import json
        from test_skin_compat import tui_2x
        z = self.build(tui=json.dumps(tui_2x()))
        errors, warnings, rec = self.check(z)
        self.assertEqual(errors, [])
        self.assertEqual(rec["os_compat"], ["2.x", "3.x"])
        self.assertNotIn("os_compat_why", rec)
        self.assertEqual(rec["manifest"]["os_compat"], ["2.x", "3.x"])

    def test_a_release_made_before_the_field_is_still_classified(self):
        import json
        from test_skin_compat import tui_2x

        def drop(d):
            m = json.loads(d)
            m.pop("os_compat")
            return (json.dumps(m, indent=2) + "\n").encode()
        z = self.resum(self.build(tui=json.dumps(tui_2x())), "mpc-plugin.json", drop)
        errors, warnings, rec = self.check(z)
        self.assertEqual(errors, [])
        self.assertEqual(rec["os_compat"], ["2.x", "3.x"])

    def claim(self, value):
        import json

        def setv(d):
            m = json.loads(d)
            m["os_compat"] = value
            return (json.dumps(m, indent=2) + "\n").encode()
        return setv

    def test_claiming_2x_for_a_skin_that_is_not_is_an_error(self):
        z = self.resum(self.build(), "mpc-plugin.json", self.claim(["2.x", "3.x"]))
        errors, warnings, rec = self.check(z)
        self.assertTrue([e for e in errors if "claims 2.x" in e], errors)

    def test_a_developer_can_narrow_a_2x_skin_to_3x(self):
        import json
        from test_skin_compat import tui_2x
        z = self.resum(self.build(tui=json.dumps(tui_2x())), "mpc-plugin.json", self.claim(["3.x"]))
        errors, warnings, rec = self.check(z)
        self.assertEqual(errors, [])
        self.assertEqual(rec["os_compat"], ["3.x"])

    def test_a_bad_claim_is_an_error(self):
        for bad in (["2.x"], ["4.x"], "2.x", []):
            z = self.resum(self.build(), "mpc-plugin.json", self.claim(bad))
            errors, warnings, rec = self.check(z)
            self.assertTrue([e for e in errors if "os_compat must be" in e], (bad, errors))


class CatalogTest(Base):
    def test_good_package(self):
        z = self.build()
        errors, warnings, rec = catalog_check.check(z, catalog=True, expect_id="test-synth", expect_repo="acme/test-synth")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        m = rec["manifest"]
        self.assertEqual((m["id"], m["arch"], m["max_glibc"], m["param_compat"]), ("test-synth", "armv7", "2.30", 1))
        self.assertEqual(len(rec["sha256"]), 64)
        self.assertIs(rec["defer"], True)   # the current installer understands -n

    def test_an_installer_without_defer_is_flagged(self):
        z = self.resum(self.build(), "install.sh", lambda d: d.replace(b"DEFER=", b"OLD="))
        errors, warnings, rec = catalog_check.check(z, catalog=True)
        self.assertEqual(errors, [])
        self.assertIs(rec["defer"], False)
        self.assertTrue([w for w in warnings if "install.sh differs" in w])

    def test_plugin_folder_layout(self):
        eng = os.path.join(self.tmp, "engine")
        os.makedirs(eng)
        open(os.path.join(eng, "banks.bin"), "wb").write(b"data")
        z = self.build(extra=("--extra", eng + ":engine"))
        errors, warnings, rec = catalog_check.check(z, catalog=True)
        self.assertEqual((errors, warnings), ([], []))
        skin = "Acme - VST - Test Synth"
        m = rec["manifest"]
        self.assertEqual((m["layout"], m["folder"], m["extras"]), ("portable", "portable/" + skin, ["engine"]))
        self.assertNotIn("so_dir", m)
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            top = names[0].split("/")[0]
            meta = zf.read("%s/portable/%s/plugin-meta.xml" % (top, skin)).decode()
            self.assertIn('file="%%payload-path%%/%s/test_synth.so"' % skin, meta)
            self.assertNotIn("/sdcard", meta)
            for need in ("version.xml", "Plugin Skins/TUI.json", "test_synth.so", "engine/banks.bin"):
                self.assertIn("%s/portable/%s/%s" % (top, skin, need), names)
            self.assertFalse([n for n in names if "/payload/" in n or n.endswith("/plugin.xml")])   # one copy, one layout
            self.assertFalse([n for n in names if "install-portable" in n])

    def test_old_vst_prefix_of_extra_is_accepted(self):
        eng = os.path.join(self.tmp, "engine")
        os.makedirs(eng)
        open(os.path.join(eng, "a"), "w").write("x")
        z = self.build(extra=("--extra", eng + ":vst/engine"))
        self.assertEqual(catalog_check.check(z, catalog=True)[2]["manifest"]["extras"], ["engine"])

    def test_tampering_is_caught(self):
        z = self.build()
        bad = self.resum(z, "plugin-meta.xml", lambda d: d.replace(b"%payload-path%", b"/sdcard/vst"))
        e, _, _ = catalog_check.check(bad)
        self.assertTrue(any("plugin-meta.xml file=" in x for x in e), e)
        bad = self.resum(z, "test_synth.so", lambda d: b"not elf")
        e, _, _ = catalog_check.check(bad)
        self.assertTrue(any("not an ELF" in x for x in e), e)
        bad = self.resum(z, "plugin-meta.xml", lambda d: d.replace(b'name="Test Synth"', b'name="Other"'))
        e, _, _ = catalog_check.check(bad)
        self.assertTrue(any("name doesn't match" in x for x in e), e)

    def legacy_zip(self):
        """A release of the old layout (payload/, plugin.xml, no "layout" field), as earlier tool versions made them."""
        import hashlib
        skin = "Acme - VST - Test Synth"
        m = {"schema": 1, "id": "test-synth", "name": "Test Synth", "version": "1.0.0", "kind": "instrument", "uid": "1a2b3c4d",
             "manufacturer": "Acme", "so": "test_synth.so", "so_dir": "/sdcard/vst", "skin": skin, "extras": [], "portable": None,
             "user_data": [], "arch": "armv7", "max_glibc": "2.30", "param_compat": 1, "about": "", "requires": "",
             "source_repo": "acme/test-synth", "license": "MIT", "cpu": None}
        fake_so(os.path.join(self.tmp, "l.so"))
        files = {"payload/vst/test_synth.so": open(os.path.join(self.tmp, "l.so"), "rb").read(),
                 "payload/Synths/%s/version.xml" % skin: b"<v/>", "payload/Synths/%s/Plugin Skins/TUI.json" % skin: b"{}",
                 "plugin.xml": ENTRY.encode(), "install.sh": b"#!/bin/sh\n", "uninstall.sh": b"#!/bin/sh\n",
                 "plugin_list.awk": b"", "INSTALL.md": b"x", "mpc-plugin.json": json.dumps(m).encode()}
        files["SHA256SUMS"] = "".join("%s  %s\n" % (hashlib.sha256(d).hexdigest(), n) for n, d in sorted(files.items())).encode()
        out = os.path.join(self.tmp, "legacy.zip")
        with zipfile.ZipFile(out, "w") as z:
            for n, d in files.items():
                z.writestr("Test-Synth-1.0.0/" + n, d)
        return out

    def test_old_layout_releases_still_validate(self):
        e, w, rec = catalog_check.check(self.legacy_zip(), catalog=True)
        self.assertEqual(e, [])
        self.assertNotIn("layout", rec["manifest"])

    def test_wrong_arch_and_glibc(self):
        e, _, _ = catalog_check.check(self.build(machine=62))
        self.assertTrue(any("armv7" in x for x in e))
        e, _, _ = catalog_check.check(self.build(elf_class=2))   # ARM, but not the 32-bit class
        self.assertTrue(any("armv7" in x for x in e) and any("not a 32-bit ARM library" in x for x in e), e)
        e, _, _ = catalog_check.check(self.build(glibc=b"GLIBC_2.38"))
        self.assertTrue(any("GLIBC" in x for x in e))

    def test_aarch64_build_is_a_gen2_package(self):
        z = self.build(machine=183, elf_class=2)
        self.assertTrue(z.endswith("-mpc-aarch64.zip"), z)
        e, _, rec = catalog_check.check(z)
        self.assertEqual(e, [])
        self.assertEqual(rec["manifest"]["arch"], "aarch64")
        self.assertEqual(rec["manifest"]["os_compat"], ["3.x"])

    def test_aarch64_may_use_glibc_up_to_2_39(self):
        e, _, _ = catalog_check.check(self.build(machine=183, elf_class=2, glibc=b"GLIBC_2.38"))
        self.assertFalse([x for x in e if "GLIBC" in x], e)

    def test_manifest_arch_must_match_the_library(self):
        # a 32-bit ARM library in a package that says aarch64 (and the reverse) is refused
        import json, shutil, tempfile, zipfile
        z = self.build()
        t = tempfile.mkdtemp()
        out = os.path.join(t, "x-mpc-aarch64.zip")
        with zipfile.ZipFile(z) as zi, zipfile.ZipFile(out, "w") as zo:
            for n in zi.namelist():
                d = zi.read(n)
                zo.writestr(n, json.dumps(dict(json.loads(d), arch="aarch64")) if n.endswith("/mpc-plugin.json") else d)
        e, _, _ = catalog_check.check(out)
        self.assertTrue(any("not a 64-bit ARM library" in x for x in e), e)
        shutil.rmtree(t)

    def test_glibc_above_2_32_is_listed_as_3x_only_up_to_2_36(self):
        import json
        from test_skin_compat import tui_2x
        skin = json.dumps(tui_2x())
        for glibc, errors, gens in ((b"GLIBC_2.30", False, ["2.x", "3.x"]), (b"GLIBC_2.32", False, ["2.x", "3.x"]),
                                    (b"GLIBC_2.33", False, ["3.x"]), (b"GLIBC_2.34", False, ["3.x"]), (b"GLIBC_2.36", False, ["3.x"]),
                                    (b"GLIBC_2.37", True, None)):
            e, w, rec = catalog_check.check(self.build(glibc=glibc, tui=skin), catalog=True)
            self.assertEqual(bool(e), errors, (glibc, e))
            if errors:
                self.assertTrue(any("limit is 2.36" in x for x in e), e)
                continue
            self.assertEqual(rec["os_compat"], gens, glibc)
            self.assertEqual(any("listed as MPC OS 3.x only" in x for x in w), gens == ["3.x"], (glibc, w))
            if gens == ["3.x"]:
                self.assertTrue(any("needs glibc" in x for x in rec["os_compat_why"]), rec["os_compat_why"])

    def test_tampered_file_fails_checksum(self):
        z = self.tamper(self.build(), "portable/Acme - VST - Test Synth/test_synth.so", lambda d: d + b"x")
        e, _, _ = catalog_check.check(z)
        self.assertTrue(any("checksum mismatch" in x for x in e))

    def test_modified_installer_warns(self):
        z = self.build()
        # rebuild SHA256SUMS consistently so only the installer-template check can object
        import hashlib
        def mod(d): return d + b"\n# evil\n"
        z = self.tamper(z, "/install.sh", mod)
        z = self.tamper(z, "/SHA256SUMS", lambda d: "\n".join(
            l if "install.sh" not in l or "uninstall" in l else
            "%s  install.sh" % hashlib.sha256(self._install(zipfile.ZipFile(z))).hexdigest()
            for l in d.decode().splitlines()).encode() + b"\n")
        e, w, _ = catalog_check.check(z)
        self.assertEqual(e, [])
        self.assertTrue(any("install.sh differs" in x for x in w))

    @staticmethod
    def _install(zf):
        return [zf.read(n) for n in zf.namelist() if n.endswith("/install.sh")][0]

    def test_catalog_needs_repo_and_license(self):
        t = self.tmp
        z = self.build()
        z2 = self.tamper(z, "mpc-plugin.json", lambda d: json.dumps({**json.loads(d), "license": None}).encode())
        e, _, _ = catalog_check.check(z2, catalog=True)
        self.assertTrue(any("license" in x for x in e))

    def test_symlinks_inside_package_ok_outside_rejected(self):
        z = self.build()
        def add(target):
            out = z + "." + str(abs(hash(target))) + ".zip"
            with zipfile.ZipFile(z) as zin, zipfile.ZipFile(out, "w") as zout:
                for i in zin.infolist():
                    zout.writestr(i, zin.read(i.filename))
                top = zin.namelist()[0].split("/")[0]
                i = zipfile.ZipInfo(top + "/portable/Acme - VST - Test Synth/d1/l"); i.external_attr = 0o120777 << 16
                zout.writestr(i, target)
            return out
        e, _, _ = catalog_check.check(add("../d2/x"), catalog=True)
        self.assertFalse(any("symlink" in x for x in e))
        e, _, _ = catalog_check.check(add("../../../../etc/passwd"), catalog=True)
        self.assertTrue(any("symlink" in x for x in e))

    def test_id_mismatch_with_registry(self):
        e, _, _ = catalog_check.check(self.build(), expect_id="other")
        self.assertTrue(any("registry id" in x for x in e))



import catalog_build  # noqa: E402


class TilePresetTest(Base):
    """tools/xpl.py: the Instruments-browser tile and the Default preset ship inside the skin folder."""

    def test_tile_and_preset_ship_in_the_folder(self):
        import xpl
        import zlib
        skin = os.path.join(self.tmp, "Acme - VST - Test Synth")
        os.makedirs(skin)
        png = os.path.join(self.tmp, "tile.png")
        open(png, "wb").write(fake_png(270, 110))
        xpl.write_tile(png, skin)
        xpl.write_default_preset(skin, "Test Synth", "Acme", "TsSy", "test_synth.so")
        z = self.build()
        errors, warnings, rec = catalog_check.check(z, catalog=True)
        self.assertEqual((errors, warnings), ([], []))
        with zipfile.ZipFile(z) as zf:
            top = zf.namelist()[0].split("/")[0]
            base = "%s/portable/Acme - VST - Test Synth/" % top
            self.assertIn(base + "Plugin Skins/browser_images/soundsmode.png", zf.namelist())
            preset = zf.read(base + "Presets/0000-Default.xpl").decode()
            inst = zf.read(top + "/install.sh").decode()
        self.assertIn('file="%payload-path%/Acme - VST - Test Synth/test_synth.so"', preset)
        self.assertIn('uid="54735379"', preset)   # 'TsSy'
        self.assertIn("<preset>Default</preset>", preset)
        self.assertIn('Presets/*.xpl', inst)   # the installer fills in the placeholder
        state = preset.split("<state>")[1].split("</state>")[0]
        b = xpl.b64dec(state)
        self.assertEqual(b[:4] + b[8:12], b"CcnKFBCh")
        self.assertEqual(b[16:20], b"TsSy")
        self.assertEqual(b[-5:], b"\0\0\0\1\0")   # a 1-byte chunk: the empty state
        self.assertEqual(xpl.b64enc(b), state)
        self.assertEqual(xpl.b64dec(xpl.b64enc(bytes(range(256)))), bytes(range(256)))
        self.assertEqual(xpl.b64enc(b"\x01"), "1.A.")   # six-bit groups, least-significant bits first, as JUCE writes them
        open(png, "wb").write(fake_png(64, 64))
        with self.assertRaises(SystemExit):
            xpl.write_tile(png, skin)


def fake_png(w, h):
    import struct
    import zlib
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\0" + bytes(w * 3) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class LayoutWarningTest(unittest.TestCase):
    def test_hardcoded_data_path(self):
        import gen_vst
        old = {"name": "X", "defines": {"MODULE_DIR": '"/sdcard/vst/x"'}}
        self.assertEqual(len(gen_vst.layout_warnings(old)), 1)
        self.assertEqual(gen_vst.layout_warnings({"name": "X", "defines": {"MODULE_SUBDIR": '"x"', "MODULE_DIR": '"/sdcard/vst/x"'}}), [])
        self.assertEqual(gen_vst.layout_warnings({"name": "X", "defines": {"HAS_LFO_BPM": 1}}), [])
        self.assertEqual(gen_vst.layout_warnings({"name": "X"}), [])


class AddinTest(Base):
    """tools/release_addin.py packages an addin (a library MPC preloads) and catalog_check.py validates it."""
    MANIFEST = ('# a test addin\nADDIN_ID=test-addin\nADDIN_NAME="Test addin"   # shown\nADDIN_SO=libtest.so\n'
                'ADDIN_CONF=test.conf\nADDIN_FILES="helper"\nADDIN_DONE="Open it."\n')

    def build_addin(self, manifest=None, machine=40, version="1.2.0", repo="acme/mpc-addin-test"):
        d = os.path.join(self.tmp, "pkg")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "addin.manifest"), "w").write(manifest or self.MANIFEST)
        fake_so(os.path.join(d, "libtest.so"), machine)
        open(os.path.join(d, "test.conf"), "w").write("x=1\n")
        open(os.path.join(d, "helper"), "w").write("data\n")
        out = os.path.join(self.tmp, "dist")
        r = subprocess.run([sys.executable, os.path.join(HERE, "release_addin.py"), "--dir", d, "--version", version,
                            "--repo", repo, "--license", "MIT", "-o", out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.join(out, "Test-addin-%s-mpc-armv7.zip" % version)

    def rezip(self, zpath, fn):
        """Rewrite the package through fn({relative name: bytes}) and fix SHA256SUMS."""
        import hashlib
        with zipfile.ZipFile(zpath) as z:
            top = z.infolist()[0].filename.split("/")[0]
            data = {i.filename[len(top) + 1:]: z.read(i) for i in z.infolist()}
        fn(data)
        data["SHA256SUMS"] = "".join("%s  %s\n" % (hashlib.sha256(v).hexdigest(), k) for k, v in sorted(data.items())
                                     if k != "SHA256SUMS").encode()
        out = zpath + ".r.zip"
        with zipfile.ZipFile(out, "w") as z:
            for k, v in data.items():
                z.writestr(top + "/" + k, v)
        return out

    def errors(self, zpath):
        return catalog_check.check(zpath, catalog=True, expect_id="test-addin", expect_repo="acme/mpc-addin-test")[0]

    def test_good_addin(self):
        z = self.build_addin()
        errors, warnings, rec = catalog_check.check(z, catalog=True, expect_id="test-addin", expect_repo="acme/mpc-addin-test")
        self.assertEqual((errors, warnings), ([], []))
        m = rec["manifest"]
        self.assertEqual((m["kind"], m["layout"], m["so"], m["conf"], m["files"], m["user_data"]),
                         ("addin", "addin", "libtest.so", "test.conf", ["helper"], ["test.conf"]))
        self.assertTrue(rec["defer"])
        with zipfile.ZipFile(z) as zf:
            am = zf.read("Test-addin-1.2.0/addin.manifest").decode()
            for f in catalog_check.ADDIN_SCRIPTS:
                self.assertEqual(zf.read("Test-addin-1.2.0/" + f), open(os.path.join(HERE, "release", "addin", f), "rb").read())
                self.assertEqual(zf.getinfo("Test-addin-1.2.0/" + f).external_attr >> 16 & 0o777, 0o755)
        self.assertTrue(am.endswith("ADDIN_VERSION=1.2.0\n"), am)

    def test_a_64_bit_class_arm_library_is_refused(self):
        z = self.rezip(self.build_addin(), lambda f: f.update({"libtest.so": f["libtest.so"][:4] + b"\x02" + f["libtest.so"][5:]}))
        self.assertIn("libtest.so is not a 32-bit ARM library", self.errors(z))

    def test_release_refuses_bad_input(self):
        for bad in ("ADDIN_ID=Test_Addin\nADDIN_SO=libtest.so\n", "ADDIN_ID=t\nADDIN_SO=libtest.so\nADDIN_FILES=missing\n",
                    "ADDIN_ID=t\nADDIN_SO=$(reboot)\n", "ADDIN_ID=t\nADDIN_SO=libtest.so\nADDIN_CONF=install.sh\n"):
            shutil.rmtree(os.path.join(self.tmp, "pkg"), ignore_errors=True)
            d = os.path.join(self.tmp, "pkg"); os.makedirs(d)
            open(os.path.join(d, "addin.manifest"), "w").write(bad)
            fake_so(os.path.join(d, "libtest.so"))
            open(os.path.join(d, "install.sh"), "w").write("")
            r = subprocess.run([sys.executable, os.path.join(HERE, "release_addin.py"), "--dir", d, "--version", "1.0.0",
                                "-o", os.path.join(self.tmp, "o")], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, bad)

    def test_tampering_is_caught(self):
        z = self.build_addin()
        cases = [
            ("a manifest that runs code", lambda d: d.__setitem__("addin.manifest", d["addin.manifest"] + b"ADDIN_DONE=$(reboot)\n"),
             "not a plain assignment"),
            ("an unknown key", lambda d: d.__setitem__("addin.manifest", d["addin.manifest"] + b"LD_PRELOAD=/x.so\n"), "known key"),
            ("a manifest that disagrees", lambda d: d.__setitem__("addin.manifest", d["addin.manifest"].replace(b"libtest.so", b"other.so")),
             "ADDIN_SO"),
            ("an extra file", lambda d: d.__setitem__("payload.sh", b"x"), "unexpected file payload.sh"),
            ("a missing data file", lambda d: d.pop("helper"), "missing helper"),
            ("a library that is not ELF", lambda d: d.__setitem__("libtest.so", b"#!/bin/sh"), "not an ELF"),
            ("an x86 library", lambda d: d.__setitem__("libtest.so", d["libtest.so"][:18] + (62).to_bytes(2, "little") + d["libtest.so"][20:]),
             "32-bit ARM"),
            ("a plugin kind", lambda d: d.__setitem__("mpc-plugin.json", d["mpc-plugin.json"].replace(b'"kind": "addin"', b'"kind": "effect"')),
             "kind must be addin"),
            ("no installer library", lambda d: d.pop("addin-lib.sh"), "missing addin-lib.sh"),
        ]
        for what, fn, expect in cases:
            errors = self.errors(self.rezip(z, fn))
            self.assertTrue(any(expect in e for e in errors), "%s: %s" % (what, errors))

    def test_modified_installer_warns(self):
        z = self.rezip(self.build_addin(), lambda d: d.__setitem__("install.sh", d["install.sh"] + b"\n# changed\n"))
        errors, warnings, _ = catalog_check.check(z, catalog=True)
        self.assertEqual(errors, [])
        self.assertTrue(any("install.sh differs" in w for w in warnings), warnings)

    def test_registry_build_and_tsv(self):
        import catalog_build, catalog_site
        entry = {"id": "test-addin", "name": "Test addin", "author": "A", "repo": "acme/mpc-addin-test", "kind": "addin",
                 "license": "MIT", "summary": "s"}
        self.assertEqual(catalog_build.check_entry(entry), [])
        self.assertTrue(catalog_build.check_entry(dict(entry, distribution="build-yourself")))
        rel = lambda tag, aid: {"tag_name": tag, "prerelease": False, "draft": False, "published_at": "2026-10-02T00:00:00Z",
                                "body": "", "assets": [{"id": aid, "name": "x-mpc-armv7.zip", "browser_download_url": "https://x/a.zip"}]}
        gh = FakeGitHub({"acme/mpc-addin-test": [rel("v1.2.0", 1)]}, {1: self.build_addin()})
        cat, problems = catalog_build.build([entry], gh, os.path.join(self.tmp, "cache"), set())
        self.assertEqual(problems, [])
        self.assertEqual(cat["plugins"][0]["latest"], "1.2.0")
        row = catalog_site.tsv(cat, []).splitlines()[1].split("\t")
        self.assertEqual(row[:8], ["plugin", "test-addin", "1.2.0", "1", "addin", "Test addin", "-", "-"])
        self.assertEqual((row[12], row[13]), ("test.conf", "1"))
        self.assertEqual(row[14:16], ["-", row[15]])   # an addin has no skin, so no os_compat; max_glibc is whatever its library needs
        # an addin release listed under an instrument entry (or the reverse) is refused
        cat, problems = catalog_build.build([dict(entry, kind="instrument")], gh, os.path.join(self.tmp, "cache"), set())
        self.assertEqual(cat["plugins"][0]["versions"], [])
        self.assertIn("is an addin", problems[0]["error"])

    def test_installer_shell_tests(self):
        """tools/test_addin.sh: the LD_PRELOAD installer against scratch systemd trees."""
        r = subprocess.run(["bash", os.path.join(HERE, "test_addin.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])


class FakeGitHub:
    def __init__(self, releases, zips):
        self.releases, self.zips = releases, zips

    def list_releases(self, repo):
        if repo not in self.releases:
            raise RuntimeError("404")
        return self.releases[repo]

    def download(self, asset, dest):
        shutil.copy(self.zips[asset["id"]], dest)


class BuildTest(Base):
    ENTRY = {"id": "test-synth", "name": "Test Synth", "author": "A", "repo": "acme/test-synth", "kind": "instrument",
             "license": "MIT", "summary": "s"}

    def rel(self, tag, aid, pre=False, name="x-mpc-armv7.zip", at="2026-09-29T00:00:00Z"):
        return {"tag_name": tag, "prerelease": pre, "draft": False, "published_at": at, "body": "notes",
                "assets": [{"id": aid, "name": name, "browser_download_url": "https://x/" + name, "download_count": 3}]}

    def test_build_keeps_good_versions_and_reports_bad(self):
        good, newer = self.build("1.0.0"), self.build("1.1.0")
        bad = self.tamper(self.build("1.2.0"), "portable/Acme - VST - Test Synth/test_synth.so", lambda d: d + b"x")
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.2.0", 3), self.rel("v1.1.0", 2), self.rel("v1.0.0", 1),
                                              self.rel("v1.3.0-b", 4, pre=True, name="nope.txt")]},
                        {1: good, 2: newer, 3: bad})
        cat, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "cache"), {"test-synth@1.0.0"})
        p = cat["plugins"][0]
        self.assertEqual([v["version"] for v in p["versions"]], ["1.1.0", "1.0.0"])
        self.assertEqual(p["latest"], "1.1.0")
        self.assertTrue(p["versions"][1]["yanked"])
        self.assertEqual(p["downloads"], 9)   # all time: every published zip, including the yanked 1.0.0 and the invalid 1.2.0
        self.assertEqual(sorted((x["tag"] for x in problems)), ["v1.2.0", "v1.3.0-b"])

    def gen2_release(self, tag, a32, a64):
        r = self.rel(tag, a32)
        r["assets"].append({"id": a64, "name": "x-mpc-aarch64.zip", "browser_download_url": "https://x/x-mpc-aarch64.zip", "download_count": 1})
        return r

    def test_an_aarch64_asset_is_attached_to_the_same_version(self):
        z32, z64 = self.build("1.0.0"), self.build("1.0.0", machine=183, elf_class=2)
        gh = FakeGitHub({"acme/test-synth": [self.gen2_release("v1.0.0", 1, 2)]}, {1: z32, 2: z64})
        cat, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "cache"), set())
        self.assertEqual(problems, [])
        v = cat["plugins"][0]["versions"][0]
        self.assertTrue(v["gen2"])
        self.assertEqual(set(v["assets"]), {"armv7", "aarch64"})
        self.assertEqual(v["url"], v["assets"]["armv7"]["url"])   # schema-1 readers still get the armv7 zip
        self.assertEqual(v["assets"]["aarch64"]["url"], "https://x/x-mpc-aarch64.zip")
        self.assertNotEqual(v["assets"]["aarch64"]["sha256"], v["assets"]["armv7"]["sha256"])
        row = catalog_site.tsv(cat, []).splitlines()[1].split("\t")
        self.assertEqual(row[16:19], [str(v["assets"]["aarch64"]["size"]), v["assets"]["aarch64"]["sha256"], "https://x/x-mpc-aarch64.zip"])

    def test_a_version_without_an_aarch64_asset_has_no_gen2(self):
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.0.0", 1)]}, {1: self.build("1.0.0")})
        cat, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "cache"), set())
        v = cat["plugins"][0]["versions"][0]
        self.assertFalse(v.get("gen2"))
        self.assertEqual(list(v["assets"]), ["armv7"])
        self.assertEqual(catalog_site.tsv(cat, []).splitlines()[1].split("\t")[16:19], ["-", "-", "-"])

    def test_a_bad_aarch64_asset_is_reported_and_does_not_hide_the_gen1_release(self):
        z32 = self.build("1.0.0")
        wrong = self.build("1.1.0", machine=183, elf_class=2)   # a different version than the armv7 zip
        gh = FakeGitHub({"acme/test-synth": [self.gen2_release("v1.0.0", 1, 2)]}, {1: z32, 2: wrong})
        cat, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "cache"), set())
        v = cat["plugins"][0]["versions"][0]
        self.assertEqual(v["version"], "1.0.0")
        self.assertFalse(v.get("gen2"))
        self.assertEqual([x["tag"] for x in problems], ["v1.0.0"])
        self.assertIn("aarch64 asset", problems[0]["error"])

    def test_a_newest_release_without_the_pattern_asset_is_reported_unless_the_repo_is_shared(self):
        good = self.build("1.0.0")
        entry = dict(self.ENTRY, asset_pattern="Synth-*-mpc-armv7.zip")
        renamed = self.rel("v1.1.0", 2, name="synth-fixed.zip", at="2026-09-30T00:00:00Z")   # the author swapped the asset
        old = self.rel("v1.0.0", 1, name="Synth-1.0.0-mpc-armv7.zip")
        gh = FakeGitHub({"acme/test-synth": [renamed, old]}, {1: good})
        cat, problems = catalog_build.build([entry], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual([(x["tag"], x["error"]) for x in problems],
                         [("v1.1.0", "expected one asset matching Synth-*-mpc-armv7.zip, found 0")])
        # an older release from before the pattern existed stays silent
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.1.0", 1, name="Synth-1.1.0-mpc-armv7.zip", at="2026-09-30T00:00:00Z"),
                                              self.rel("v1.0.0", 2, name="legacy.zip")]}, {1: self.build("1.1.0")})
        self.assertEqual(catalog_build.build([entry], gh, os.path.join(self.tmp, "c2"), set())[1], [])
        # a repo shared by several entries: another plugin's release is not this one's problem
        other = dict(self.ENTRY, id="other-synth", asset_pattern="Other-*-mpc-armv7.zip")
        gh = FakeGitHub({"acme/test-synth": [renamed, old]}, {1: good})
        self.assertEqual(catalog_build.build([entry, other], gh, os.path.join(self.tmp, "c3"), set())[1], [])

    def test_each_version_carries_its_os_compat(self):
        import json
        from test_skin_compat import tui_2x
        old, new = self.build("1.0.0"), self.build("1.1.0", tui=json.dumps(tui_2x()))
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.1.0", 2), self.rel("v1.0.0", 1)]}, {1: old, 2: new})
        cat, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual(problems, [])
        by = {v["version"]: v for v in cat["plugins"][0]["versions"]}
        self.assertEqual(by["1.0.0"]["os_compat"], ["3.x"])
        self.assertEqual(by["1.0.0"]["os_compat_why"], ["TUI.json has no pageData"])
        self.assertEqual(by["1.1.0"]["os_compat"], ["2.x", "3.x"])
        self.assertNotIn("os_compat_why", by["1.1.0"])

    def test_a_failure_with_a_newer_passing_release_is_superseded(self):
        bad = lambda v: self.tamper(self.build(v), "portable/Acme - VST - Test Synth/test_synth.so", lambda d: d + b"x")
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.3.0", 4, at="2026-10-03T00:00:00Z"),
                                              self.rel("v1.2.0", 3, at="2026-10-02T12:00:00Z"),
                                              self.rel("v1.1.0", 2, at="2026-10-02T09:00:00Z"),
                                              self.rel("v1.0.0", 1, at="2026-10-01T00:00:00Z")]},
                        {1: bad("1.0.0"), 2: bad("1.1.0"), 3: self.build("1.2.0"), 4: bad("1.3.0")})
        _, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual({x["tag"]: x["superseded"] for x in problems}, {"v1.0.0": True, "v1.1.0": True, "v1.3.0": False})
        # the passing release is yanked: nothing it would supersede counts as fixed
        _, problems = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "c"), {"test-synth@1.2.0"})
        self.assertFalse(any(x["superseded"] for x in problems))

    def test_tested_json_attaches_to_matching_version(self):
        gh = FakeGitHub({"acme/test-synth": [self.rel("v1.0.0", 1)]}, {1: self.build("1.0.0")})
        gh.tested = lambda repo: [{"version": "v1.0.0", "device": "MPC Live II", "firmware": "3.6", "date": "2026-09-01"},
                                  {"version": "9.9.9", "device": "Force"}]
        cat, _ = catalog_build.build([self.ENTRY], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual(cat["plugins"][0]["versions"][0]["tested"],
                         [{"device": "MPC Live II", "firmware": "3.6", "date": "2026-09-01"}])

    def test_unreadable_repo_is_reported_not_fatal(self):
        cat, problems = catalog_build.build([self.ENTRY], FakeGitHub({}, {}), os.path.join(self.tmp, "c"), set())
        self.assertEqual(cat["plugins"][0]["versions"], [])
        self.assertIsNone(cat["plugins"][0]["latest"])
        self.assertIn("cannot list", problems[0]["error"])
        self.assertTrue(problems[0]["unreadable"])

    def test_registry_rules(self):
        self.assertEqual(catalog_build.check_entry(self.ENTRY, "x/test-synth.json"), [])
        self.assertTrue(catalog_build.check_entry({**self.ENTRY, "license": "Proprietary"}))
        self.assertTrue(catalog_build.check_entry(self.ENTRY, "x/other.json"))
        self.assertTrue(catalog_build.check_entry({**self.ENTRY, "repo": "nope"}))


import catalog_issues  # noqa: E402


class IssuesTest(unittest.TestCase):
    T = "Catalog: a %s failed validation"

    def test_plan_dedupes_and_skips_known_titles(self):
        pr = [{"id": "a", "tag": "v1", "error": "x"}, {"id": "a", "tag": "v1", "error": "y"},
              {"id": "a", "tag": "v2", "error": "z"}, {"id": "a", "tag": "v3", "error": "w"},
              {"id": "b", "tag": None, "error": "404"}]
        issues = [{"number": 1, "title": self.T % "v2", "state": "OPEN"}, {"number": 2, "title": self.T % "v3", "state": "CLOSED"}]
        got, close = catalog_issues.plan(pr, issues)
        self.assertEqual([t for t, _ in got], [self.T % "v1", "Catalog: b cannot be read"])   # v3 was closed: not reopened
        self.assertIn("- x", got[0][1]); self.assertIn("- y", got[0][1])
        self.assertEqual(close, [])

    def test_superseded_fixed_and_duplicate_issues_close(self):
        pr = [{"id": "a", "tag": "v1", "error": "x", "superseded": True}, {"id": "a", "tag": "v4", "error": "y"},
              {"id": "c", "tag": None, "error": "cannot list releases: 502", "unreadable": True}]
        issues = [{"number": n, "title": t, "state": st} for n, t, st in [
            (10, self.T % "v1", "OPEN"),             # superseded: closed
            (11, self.T % "v2", "OPEN"),             # no longer reported: closed
            (12, self.T % "v4", "OPEN"), (13, self.T % "v4", "OPEN"),   # still failing; 13 is a duplicate
            (14, "Catalog: c v1 failed validation", "OPEN"),   # c could not be read this time: left alone
            (15, "Catalog: add a plugin please", "OPEN"),       # not one of ours
            (16, self.T % "v3", "CLOSED")]]
        got, close = catalog_issues.plan(pr, issues)
        self.assertEqual([t for t, _ in got], ["Catalog: c cannot be read"])
        self.assertEqual([n for n, _ in close], [10, 11, 13])
        self.assertIn("newer release", close[0][1])

    def test_cannot_be_read_reopens_but_a_per_tag_title_never_does(self):
        # a tagless title's repo can go from unreadable to readable (closing its issue) and back to
        # unreadable (the problem returns): only an open issue protects it from reopening. A per-tag
        # title is different: a tag can't be rebuilt, so a closed issue is final.
        pr = [{"id": "a", "tag": "v1", "error": "x"}, {"id": "b", "tag": None, "error": "cannot list releases: 502",
                                                        "unreadable": True}]
        issues = [{"number": 1, "title": self.T % "v1", "state": "CLOSED"},
                  {"number": 2, "title": "Catalog: b cannot be read", "state": "CLOSED"}]
        got, close = catalog_issues.plan(pr, issues)
        self.assertEqual([t for t, _ in got], ["Catalog: b cannot be read"])
        self.assertEqual(close, [])


import catalog_site  # noqa: E402


class SiteTest(unittest.TestCase):
    def test_render_embeds_catalog_safely(self):
        cat = {"schema": 1, "generated": "x", "plugins": [{"id": "a", "name": "A </script><b>", "versions": []}]}
        html = catalog_site.render(cat)
        self.assertNotIn("/*CATALOG_JSON*/", html)
        data = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
        self.assertEqual(json.loads(data), cat)   # round-trips, and the embedded "</script>" can't end the block

    def test_atom_feed_skips_yanked_and_escapes(self):
        v = lambda ver, y: {"version": ver, "date": "2026-09-2%s" % ver[0], "url": "https://x/a?b=1&c=2", "yanked": y, "channel": "stable"}
        cat = {"schema": 1, "generated": "g", "plugins": [{"id": "a", "name": "A <&>", "author": "Z", "summary": "s",
                                                         "versions": [v("2.0", False), v("1.0", True)]}]}
        import xml.dom.minidom
        doc = xml.dom.minidom.parseString(catalog_site.atom(cat, "https://e.io/x/"))
        self.assertEqual(len(doc.getElementsByTagName("entry")), 1)
        self.assertIn("A <&>", doc.getElementsByTagName("title")[1].firstChild.data)

    def test_registry_style_and_source_available(self):
        e = dict(BuildTest.ENTRY, license="MAME license")
        self.assertTrue(catalog_build.check_entry(e))
        self.assertEqual(catalog_build.check_entry(dict(e, source_available=True, style="rompler", tags=["jv-880"])), [])
        self.assertTrue(catalog_build.check_entry(dict(BuildTest.ENTRY, style="Bad Style")))


import catalog_md  # noqa: E402


class PagesTest(unittest.TestCase):
    def test_markdown_subset_and_escaping(self):
        html = catalog_md.render("# T <b>\n\ntext with `a<b` and **bold** [x](https://e.io/a?b=1&c=2) [bad](javascript:alert(1))\n\n"
                                 "- one\n  wrapped\n- two\n\n1. a\n2. b\n\n```\n<x> & y\n```\n\n> note\n\n| h1 | h2 |\n|---|---|\n| a | b |\n")
        self.assertIn('<h1 id="t">T &lt;b&gt;</h1>', html)
        self.assertIn("<code>a&lt;b</code>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn('<a href="https://e.io/a?b=1&amp;c=2">x</a>', html)
        self.assertNotIn('href="javascript', html)
        self.assertIn("<li>one wrapped</li>", html)
        self.assertIn("<ol><li>a</li><li>b</li></ol>", html)
        self.assertIn("<pre><code>&lt;x&gt; &amp; y</code></pre>", html)
        self.assertIn("<blockquote>", html)
        self.assertIn("<th>h1</th>", html)
        self.assertNotIn("<b>", html)

    def test_install_page_is_for_installing_and_the_build_page_for_building(self):
        pages = catalog_site.load_pages(os.path.join(HERE, "..", "catalog", "pages"))
        by = {p["slug"]: p for p in pages}
        inst = catalog_site.render_page(by["install"], pages)
        build = catalog_site.render_page(by["build"], pages)
        # building (Docker, git, WSL, the build-yourself steps) lives on the Build page only
        self.assertIn('id="plugins-you-build-yourself"', build)
        self.assertIn("on <strong>your computer</strong>", build)
        for needle in ("Install Docker", "Install git and Python 3", "docker run --rm hello-world"):
            self.assertIn(needle, build)
            self.assertNotIn(needle, inst)
        self.assertNotIn('id="plugins-you-build-yourself"', inst)
        self.assertIn('href="build.html#plugins-you-build-yourself"', inst)   # a pointer, not the steps
        self.assertIn('id="with-termius-click-instead-of-type"', inst)
        self.assertIn('id="check-that-you-can-reach-your-device"', inst)
        self.assertNotIn("setup.html", inst + build)
        idx = catalog_site.render({"schema": 1, "generated": "x", "plugins": []}, pages)
        self.assertIn("Run this on your computer (needs Docker), not on the device.", idx)
        self.assertIn('build.html#plugins-you-build-yourself', idx)
        self.assertNotIn("setup.html", idx)

    def test_old_page_addresses_redirect(self):
        self.assertEqual(catalog_site.MOVED_PAGES["setup.html"], "build.html")
        html = catalog_site.redirect_page("build.html")
        self.assertIn('http-equiv="refresh" content="0; url=build.html"', html)
        self.assertIn('<a href="build.html">build.html</a>', html)

    def test_install_panel_gets_only_valid_hashes_and_ids_are_not_markup(self):
        good = "a" * 64
        html = catalog_site.render({"schema": 1, "generated": "x", "plugins": []}, (), {"mpc-store.sh": good, "sync.sh": "</script><b>", "x": 5})
        self.assertIn('{"mpc-store.sh": "%s"}' % good, html)
        self.assertNotIn("</script><b>", html)
        self.assertIn('id="inst"', html)
        self.assertEqual(html.count("/*STORE_JSON*/"), 0)

    def test_collapsible_sections(self):
        html = catalog_md.render("Intro\n\n::: details By hand <b>x</b>\nStep **one** `a<b`\n\n```\nssh root@x\n```\n:::\n\nAfter")
        self.assertIn('<details class="fold" id="by-hand-x"><summary>By hand &lt;b&gt;x&lt;/b&gt;</summary>', html)
        self.assertIn("<strong>one</strong>", html)
        self.assertIn("<pre><code>ssh root@x</code></pre>", html)
        self.assertNotIn("<b>", html)
        self.assertTrue(html.index("</details>") < html.index("After"))
        self.assertEqual(html.count("<details"), 1)

    def test_repo_pages_render_with_nav(self):
        pages = catalog_site.load_pages(os.path.join(HERE, "..", "catalog", "pages"))
        self.assertGreaterEqual(len(pages), 4)
        self.assertEqual([p["slug"] for p in pages], ["install", "build", "workflow", "add"])
        for p in pages:
            html = catalog_site.render_page(p, pages)
            self.assertIn('aria-current="page"', html)
            for marker in ("/*NAV*/", "/*TITLE*/", "/*DESC*/", "/*BODY*/", "/*SITE_CSS*/"):
                self.assertNotIn(marker, html)
        idx = catalog_site.render({"schema": 1, "generated": "x", "plugins": []}, pages)
        for p in pages:
            self.assertIn('href="%s.html"' % p["slug"], idx)
        self.assertNotIn("/*NAV*/", idx)

class FakeTags:
    """GitHub stand-in for build-yourself entries: tags, files per tag, releases, dates."""
    def __init__(self, tags=None, files=(), releases=None, tested=None):
        self.tags, self.files, self.releases, self._tested = tags or {}, set(files), releases or {}, tested or {}

    def list_tags(self, repo):
        if repo not in self.tags:
            raise RuntimeError("404 Not Found")
        return [{"name": n, "sha": "sha-" + n} for n in self.tags[repo]]

    def list_releases(self, repo):
        return self.releases.get(repo, [])

    def file_exists(self, repo, path, ref):
        return (repo, ref, path) in self.files

    def tag_date(self, repo, sha):
        return "2026-09-2" + str(len(sha) % 10)

    def tested(self, repo):
        return self._tested.get(repo, [])


BY_ENTRY = {
    "id": "fw-synth", "name": "Firmware Synth", "author": "A", "repo": "acme/fw-synth", "kind": "instrument", "license": "AGPL-3.0-only",
    "summary": "s", "distribution": "build-yourself",
    "requires_user_files": [{"name": "OS.syx", "description": "Your own OS file."}],
    "build": {"command": "release/build.sh <OS.syx> [-d <ip>]", "script": "release/build.sh", "docs_url": "https://github.com/acme/fw-synth/blob/{tag}/README.md", "needs": ["Docker"]},
    "components": [{"id": "fw-one", "name": "FW One", "kind": "instrument", "uid": "FwOn"}, {"id": "fw-fx", "name": "FW FX", "kind": "effect", "uid": "FwFx"}],
}


class BuildYourselfTest(Base):
    def entry(self, **kw):
        e = json.loads(json.dumps(BY_ENTRY))
        e.update(kw)
        return e

    def test_registry_accepts_a_valid_entry(self):
        self.assertEqual(catalog_build.check_entry(self.entry(), "x/fw-synth.json"), [])

    def test_registry_guardrails(self):
        bad = {
            "no user files": self.entry(requires_user_files=[]),
            "user file without description": self.entry(requires_user_files=[{"name": "x"}]),
            "no build": {k: v for k, v in self.entry().items() if k != "build"},
            "script outside the repo": self.entry(build=dict(BY_ENTRY["build"], script="../x.sh", command="../x.sh")),
            "absolute script": self.entry(build=dict(BY_ENTRY["build"], script="/x.sh", command="/x.sh")),
            "command does not run the script": self.entry(build=dict(BY_ENTRY["build"], command="make")),
            "http docs url": self.entry(build=dict(BY_ENTRY["build"], docs_url="http://x.io")),
            "not an open license": self.entry(license="MAME license"),
            "source_available is not enough": self.entry(license="MAME license", source_available=True),
            "asset_pattern makes no sense": self.entry(asset_pattern="*.zip"),
            "bad component": self.entry(components=[{"id": "Bad Id", "name": "x", "kind": "instrument"}]),
            "bad component uid": self.entry(components=[{"id": "a", "name": "x", "kind": "instrument", "uid": "toolong"}]),
            "duplicate component": self.entry(components=[{"id": "a", "name": "x", "kind": "instrument"}, {"id": "a", "name": "y", "kind": "effect"}]),
            "unknown distribution": self.entry(distribution="download"),
        }
        for why, e in bad.items():
            self.assertTrue(catalog_build.check_entry(e, "x/fw-synth.json"), why)

    def test_release_entries_cannot_carry_build_fields(self):
        e = dict(BuildTest.ENTRY, requires_user_files=BY_ENTRY["requires_user_files"])
        self.assertTrue(catalog_build.check_entry(e, "x/test-synth.json"))
        self.assertEqual(catalog_build.check_entry(dict(BuildTest.ENTRY, distribution="release"), "x/test-synth.json"), [])
        self.assertEqual(catalog_build.check_entry(BuildTest.ENTRY, "x/test-synth.json"), [])   # default distribution

    def test_component_ids_are_unique_across_the_registry(self):
        d = os.path.join(self.tmp, "reg")
        os.makedirs(d)
        a, b = self.entry(), self.entry(id="other", repo="acme/other")
        for e in (a, b):
            json.dump(e, open(os.path.join(d, e["id"] + ".json"), "w"))
        entries, problems = catalog_build.load_registry(d)
        self.assertEqual([e["id"] for e in entries], ["fw-synth"])
        self.assertTrue(any("component id" in m for _, m in problems))

    def test_versions_come_from_tags_and_need_the_script(self):
        e = self.entry()
        before = json.dumps(e, sort_keys=True)
        gh = FakeTags(tags={"acme/fw-synth": ["v0.9.0", "v0.9.1", "v1.0.0-rc1", "nightly"]},
                      files={("acme/fw-synth", "v0.9.1", "release/build.sh"), ("acme/fw-synth", "v0.9.1", "LICENSE"),
                             ("acme/fw-synth", "v0.9.0", "LICENSE")},
                      tested={"acme/fw-synth": [{"version": "0.9.1", "device": "Akai Force", "firmware": "3.9.1", "date": "2026-09-29"}]})
        cat, problems = catalog_build.build([e], gh, os.path.join(self.tmp, "c"), set())
        p = cat["plugins"][0]
        self.assertEqual([v["version"] for v in p["versions"]], ["0.9.1"])   # v0.9.0 has no script; rc and nightly are ignored
        self.assertEqual(p["latest"], "0.9.1")
        self.assertEqual(p["distribution"], "build-yourself")
        v = p["versions"][0]
        self.assertEqual((v["tag"], v["source_url"], v["tested"]), ("v0.9.1", "https://github.com/acme/fw-synth/tree/v0.9.1", [{"device": "Akai Force", "firmware": "3.9.1", "date": "2026-09-29"}]))
        for k in ("url", "sha256", "size", "param_compat", "manifest"):
            self.assertNotIn(k, v)   # nothing is published: no download, checksum or zip manifest
        self.assertEqual(v["warnings"], [])   # this tag has a LICENSE file
        self.assertEqual([c["id"] for c in p["components"]], ["fw-one", "fw-fx"])
        self.assertEqual(problems, [])   # the old tag v0.9.0 without the script is skipped quietly, not reported
        self.assertEqual(json.dumps(e, sort_keys=True), before)   # the registry entry is not mutated

    def test_only_the_newest_tag_missing_the_script_is_reported(self):
        files = {("acme/fw-synth", "v0.9.0", "release/build.sh"), ("acme/fw-synth", "v0.9.0", "LICENSE")}
        gh = FakeTags(tags={"acme/fw-synth": ["v0.9.0", "v0.9.1"]}, files=files)   # the newest tag lacks the script
        cat, problems = catalog_build.build([self.entry()], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual([v["version"] for v in cat["plugins"][0]["versions"]], ["0.9.0"])
        self.assertEqual([(x["tag"], "does not exist at this tag" in x["error"]) for x in problems], [("v0.9.1", True)])

    def test_license_file_missing_is_a_warning_on_the_version(self):
        gh = FakeTags(tags={"acme/fw-synth": ["v0.1.0"]}, files={("acme/fw-synth", "v0.1.0", "release/build.sh")})
        cat, problems = catalog_build.build([self.entry()], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual(cat["plugins"][0]["versions"][0]["warnings"], ["no LICENSE file at the root of this tag"])
        self.assertEqual(problems, [])

    def test_published_zip_is_reported_loudly_but_entry_stays(self):
        rel = {"tag_name": "v0.1.0", "draft": False, "assets": [{"id": 1, "name": "FW-0.1.0-mpc-armv7.zip", "browser_download_url": "https://x/z"}]}
        gh = FakeTags(tags={"acme/fw-synth": ["v0.1.0"]}, files={("acme/fw-synth", "v0.1.0", "release/build.sh")}, releases={"acme/fw-synth": [rel]})
        cat, problems = catalog_build.build([self.entry()], gh, os.path.join(self.tmp, "c"), set())
        self.assertEqual(cat["plugins"][0]["latest"], "0.1.0")
        self.assertEqual(len(problems), 1)
        self.assertIn("LICENCE RISK", problems[0]["error"])
        self.assertEqual(problems[0]["tag"], "v0.1.0")
        gh.releases["acme/fw-synth"][0]["draft"] = True   # a draft is not public
        self.assertEqual(catalog_build.build([self.entry()], gh, os.path.join(self.tmp, "c"), set())[1], [])

    def test_missing_repo_and_no_tags_are_reported(self):
        cat, problems = catalog_build.build([self.entry()], FakeTags(), os.path.join(self.tmp, "c"), set())
        self.assertEqual(cat["plugins"][0]["versions"], [])
        self.assertIsNone(cat["plugins"][0]["latest"])
        self.assertIn("cannot read the repo", problems[0]["error"])
        cat, problems = catalog_build.build([self.entry()], FakeTags(tags={"acme/fw-synth": ["nightly"]}), os.path.join(self.tmp, "c"), set())
        self.assertIn("no vX.Y.Z tag", problems[0]["error"])

    def test_yanked_tag_is_never_latest(self):
        gh = FakeTags(tags={"acme/fw-synth": ["v0.2.0", "v0.1.0"]},
                      files={("acme/fw-synth", t, "release/build.sh") for t in ("v0.2.0", "v0.1.0")} | {("acme/fw-synth", t, "LICENSE") for t in ("v0.2.0", "v0.1.0")})
        cat, _ = catalog_build.build([self.entry()], gh, os.path.join(self.tmp, "c"), {"fw-synth@0.2.0"})
        self.assertEqual(cat["plugins"][0]["latest"], "0.1.0")

    def test_release_entries_are_untouched_in_a_mixed_catalog(self):
        class Mixed(FakeTags):
            def download(self, asset, dest):
                shutil.copy(good, dest)
        good = self.build("1.0.0")
        rel = {"tag_name": "v1.0.0", "prerelease": False, "draft": False, "published_at": "2026-09-29T00:00:00Z", "body": "",
               "assets": [{"id": 1, "name": "x-mpc-armv7.zip", "browser_download_url": "https://x/x", "download_count": 3}]}
        gh = Mixed(tags={"acme/fw-synth": ["v0.1.0"]}, files={("acme/fw-synth", "v0.1.0", "release/build.sh")}, releases={"acme/test-synth": [rel]})
        cat, problems = catalog_build.build([BuildTest.ENTRY, self.entry()], gh, os.path.join(self.tmp, "c"), set())
        r = [p for p in cat["plugins"] if p["id"] == "test-synth"][0]
        self.assertEqual((r["distribution"], r["latest"], r["downloads"]), ("release", "1.0.0", 3))
        self.assertIn("sha256", r["versions"][0])
        self.assertIn("url", r["versions"][0])
        self.assertFalse([x for x in problems if x["id"] == "test-synth"])

    def test_site_shows_build_instructions_not_downloads(self):
        html = catalog_site.render({"schema": 1, "generated": "x", "plugins": []})
        self.assertIn("The result contains firmware-derived data: build it yourself, install it on your own devices only, never share it.", html)
        self.assertIn("How to build", html)
        cat = {"schema": 1, "generated": "x", "plugins": [{"id": "fw-synth", "name": "FW", "author": "A", "summary": "s", "versions": [
            {"version": "0.1.0", "tag": "v0.1.0", "date": "2026-09-29", "channel": "stable", "yanked": False, "source_url": "https://github.com/a/b/tree/v0.1.0"}]}]}
        self.assertIn("<link href=\"https://github.com/a/b/tree/v0.1.0\"/>", catalog_site.atom(cat))


SETTINGS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<PROPERTIES>
  <VALUE name="SynthContentLocations" val="/sdcard/Synths"/>
  <VALUE name="pluginList-arm">
    <KNOWNPLUGINS>
      <PLUGIN name="Other" format="VST" manufacturer="x" version="1.0" file="/sdcard/vst/other.so" uid="6f746872" isInstrument="1"/>
      <PLUGIN name="Test Synth" format="VST" manufacturer="Acme" version="1.0" file="/sdcard/vst/test_synth.so" uid="1a2b3c4d" isInstrument="1"/>
    </KNOWNPLUGINS>
  </VALUE>
</PROPERTIES>
"""


class InstallerTest(Base):
    """Runs the generated install.sh / uninstall.sh against a copy of MPC.settings (device checks skipped)."""
    SKIN = "Acme - VST - Test Synth"

    def setUp(self):
        super().setUp()
        import xml.etree.ElementTree  # noqa: F401  (used by settings())
        packaged = os.path.join(self.tmp, "packaged_banks")   # data the package ships (an extra) and the user adds to (user data)
        os.makedirs(packaged)
        open(os.path.join(packaged, "shipped.syx"), "w").write("shipped")
        engine = os.path.join(self.tmp, "engine_bin")          # data the package ships that is not the user's
        os.makedirs(engine)
        open(os.path.join(engine, "tool"), "w").write("tool")
        z = self.build(extra=("--user-data", "roms", "--user-data", "banks", "--extra", packaged + ":banks", "--extra", engine + ":engine/bin"))
        self.pkg = os.path.join(self.tmp, "pkg")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(self.pkg)
        self.top = os.path.join(self.pkg, os.listdir(self.pkg)[0])
        self.synths = os.path.join(self.tmp, "device", "Synths")
        self.legacy_root = os.path.join(self.tmp, "device", "root")
        self.settings_path = os.path.join(self.tmp, "MPC.settings")
        open(self.settings_path, "w").write(SETTINGS_XML)
        os.makedirs(os.path.join(self.legacy_root, "sdcard", "vst"))
        open(os.path.join(self.legacy_root, "sdcard", "vst", "test_synth.so"), "wb").write(b"old")

    def run_script(self, script, *args):
        self.ctl_log = os.path.join(self.tmp, "mpc_ctl.log")
        env = dict(os.environ, MPC_INSTALL_TEST="1", MPC_SETTINGS=self.settings_path, MPC_LEGACY_ROOT=self.legacy_root,
                   MPC_TEST_LOG=self.ctl_log)
        if os.environ.get("INSTALLER_TEST_PATH"):   # e.g. a folder of BusyBox applets, to imitate the device's userland
            env["PATH"] = os.environ["INSTALLER_TEST_PATH"]
        return subprocess.run(["sh", os.path.join(self.top, script), "-y", "-t", self.synths, *args], cwd=self.top, env=env,
                              capture_output=True, text=True)

    def entries(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(self.settings_path).getroot()
        return {e.get("name"): e.get("file") for e in root.iter("PLUGIN")}

    def test_fresh_and_legacy_upgrade(self):
        r = self.run_script("install.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(self.synths, self.SKIN)
        for f in ("test_synth.so", "plugin-meta.xml", "version.xml", os.path.join("Plugin Skins", "TUI.json")):
            self.assertTrue(os.path.exists(os.path.join(folder, f)), f)
        e = self.entries()
        self.assertEqual(e["Test Synth"], os.path.join(folder, "test_synth.so"))   # %payload-path% became the Synths folder
        self.assertEqual(e["Other"], "/sdcard/vst/other.so")                        # a neighbour is untouched
        self.assertEqual(len(e), 2)                                                 # replaced, not duplicated
        self.assertFalse(os.path.exists(os.path.join(self.legacy_root, "sdcard", "vst", "test_synth.so")))
        self.assertTrue([n for n in os.listdir(self.tmp) if n.startswith("MPC.settings.bak-")])

    def legacy(self, *parts):
        return os.path.join(self.legacy_root, "sdcard", "vst", *parts)

    def test_legacy_user_files_are_moved_and_packaged_data_removed(self):
        os.makedirs(self.legacy("roms")); open(self.legacy("roms", "mine.rom"), "w").write("my rom")      # user data, only there
        os.makedirs(self.legacy("banks")); open(self.legacy("banks", "mine.syx"), "w").write("my bank")   # user data next to shipped data
        open(self.legacy("banks", "shipped.syx"), "w").write("old shipped")
        os.makedirs(self.legacy("engine", "bin")); open(self.legacy("engine", "bin", "tool"), "w").write("old tool")   # packaged data
        os.makedirs(self.legacy("unrelated")); open(self.legacy("unrelated", "x"), "w").write("keep")
        r = self.run_script("install.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(self.synths, self.SKIN)
        self.assertEqual(open(os.path.join(folder, "roms", "mine.rom")).read(), "my rom")      # moved, not lost
        self.assertEqual(open(os.path.join(folder, "banks", "mine.syx")).read(), "my bank")    # merged over the shipped folder
        self.assertEqual(open(os.path.join(folder, "banks", "shipped.syx")).read(), "old shipped")
        self.assertEqual(open(os.path.join(folder, "engine", "bin", "tool")).read(), "tool")   # packaged data comes from the package
        self.assertFalse(os.path.exists(self.legacy("roms")))
        self.assertFalse(os.path.exists(self.legacy("banks")))
        self.assertFalse(os.path.exists(self.legacy("engine", "bin")))
        self.assertEqual(open(self.legacy("unrelated", "x")).read(), "keep")                   # anything else in /sdcard/vst stays
        self.assertFalse(os.path.exists(self.legacy("test_synth.so")))
        self.assertIn("moved your files", r.stdout)

    def test_legacy_data_is_left_alone_when_the_edit_fails(self):
        os.makedirs(self.legacy("roms")); open(self.legacy("roms", "mine.rom"), "w").write("my rom")
        open(self.settings_path, "w").write(SETTINGS_XML.replace("</PROPERTIES>", ""))
        self.assertNotEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(open(self.legacy("roms", "mine.rom")).read(), "my rom")
        self.assertTrue(os.path.exists(self.legacy("test_synth.so")))

    def test_files_next_to_no_legacy_install_are_not_touched(self):
        os.remove(self.legacy("test_synth.so"))       # no old install of this plugin: /sdcard/vst/roms is not ours to move
        os.makedirs(self.legacy("roms")); open(self.legacy("roms", "x"), "w").write("other")
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(open(self.legacy("roms", "x")).read(), "other")
        self.assertFalse(os.path.exists(os.path.join(self.synths, self.SKIN, "roms")))

    def test_second_run_keeps_what_the_first_moved(self):
        os.makedirs(self.legacy("roms")); open(self.legacy("roms", "mine.rom"), "w").write("my rom")
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(open(os.path.join(self.synths, self.SKIN, "roms", "mine.rom")).read(), "my rom")

    def test_lost_exec_bits_and_symlinks_are_restored(self):
        eng = os.path.join(self.tmp, "eng2")
        os.makedirs(os.path.join(eng, "py", "bin"))
        for f in ("yt-dlp", os.path.join("py", "bin", "python3.11")):
            open(os.path.join(eng, f), "w").write("#!/bin/sh\n"); os.chmod(os.path.join(eng, f), 0o755)
        os.symlink("python3.11", os.path.join(eng, "py", "bin", "python3"))
        open(os.path.join(eng, "data.txt"), "w").write("plain")
        z = self.build(version="1.2.1", extra=("--extra", eng + ":engine/bin"))
        pkg = os.path.join(self.tmp, "pkg2")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(pkg)   # like a Windows unzip: no exec bits, the symlink becomes a text file
        top = os.path.join(pkg, os.listdir(pkg)[0])
        eb = os.path.join(top, "portable", self.SKIN, "engine", "bin")
        self.assertFalse(os.path.islink(os.path.join(eb, "py", "bin", "python3")))
        self.assertFalse(os.access(os.path.join(eb, "yt-dlp"), os.X_OK))
        self.top = top
        r = self.run_script("install.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        ib = os.path.join(self.synths, self.SKIN, "engine", "bin")
        self.assertTrue(os.access(os.path.join(ib, "yt-dlp"), os.X_OK))
        self.assertTrue(os.access(os.path.join(ib, "py", "bin", "python3.11"), os.X_OK))
        self.assertEqual(os.readlink(os.path.join(ib, "py", "bin", "python3")), "python3.11")
        self.assertFalse(os.access(os.path.join(ib, "data.txt"), os.X_OK))

    def mpc_calls(self):
        return open(self.ctl_log).read().split() if os.path.exists(self.ctl_log) else []

    def test_install_and_uninstall_stop_and_start_mpc_once(self):
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(self.mpc_calls(), ["stop", "start"])
        os.remove(self.ctl_log)
        self.assertEqual(self.run_script("uninstall.sh").returncode, 0)
        self.assertEqual(self.mpc_calls(), ["stop", "start"])

    def test_defer_flag_leaves_mpc_alone_for_a_batch(self):
        r = self.run_script("install.sh", "-n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mpc_calls(), [])                                   # the caller owns stop/start
        self.assertIn("Test Synth", self.entries())                              # but the install itself happened
        r = self.run_script("uninstall.sh", "-n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.mpc_calls(), [])
        self.assertNotIn("Test Synth", self.entries())

    def test_a_failed_settings_edit_still_restarts_mpc_unless_deferred(self):
        open(self.settings_path, "w").write("not xml at all\n")                  # the edit finds nowhere to put the entry
        r = self.run_script("install.sh")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.mpc_calls(), ["stop", "start"])                    # MPC is never left stopped
        os.remove(self.ctl_log)
        r = self.run_script("install.sh", "-n")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.mpc_calls(), [])                                   # the batch caller decides what to do

    def test_reinstall_is_idempotent_and_keeps_user_files(self):
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        rom = os.path.join(self.synths, self.SKIN, "roms", "mine.rom")
        os.makedirs(os.path.dirname(rom))
        open(rom, "w").write("user data")
        open(os.path.join(self.synths, self.SKIN, "stale.txt"), "w").write("not shipped")
        r = self.run_script("install.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(rom).read(), "user data")                              # the user's files survive an upgrade
        self.assertFalse(os.path.exists(os.path.join(self.synths, self.SKIN, "stale.txt")))
        self.assertEqual(sorted(os.listdir(self.synths)), [self.SKIN])              # no .new/.old leftovers
        self.assertEqual(len(self.entries()), 2)

    def test_uninstall_removes_entry_and_folder_but_keeps_user_files(self):
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        rom = os.path.join(self.synths, self.SKIN, "roms", "mine.rom")
        os.makedirs(os.path.dirname(rom))
        open(rom, "w").write("user data")
        r = self.run_script("uninstall.sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(self.entries()), ["Other"])
        self.assertEqual(open(rom).read(), "user data")
        self.assertFalse(os.path.exists(os.path.join(self.synths, self.SKIN, "test_synth.so")))

    def test_uninstall_leaves_only_the_user_data_folders(self):
        self.assertEqual(self.run_script("install.sh").returncode, 0)
        self.assertEqual(self.run_script("uninstall.sh").returncode, 0)
        # "banks" is user data that the package also ships (kept whole); nothing else of the plugin stays
        self.assertEqual(os.listdir(self.synths), [self.SKIN])
        self.assertEqual(os.listdir(os.path.join(self.synths, self.SKIN)), ["banks"])

    def test_refuses_unsafe_target_and_missing_settings(self):
        r = self.run_script("install.sh", "-t", "/tmp/a&b")
        self.assertNotEqual(r.returncode, 0)
        os.remove(self.settings_path)
        self.assertNotEqual(self.run_script("install.sh").returncode, 0)

    def test_settings_untouched_when_the_edit_would_break_it(self):
        broken = SETTINGS_XML.replace("</PROPERTIES>", "")   # not valid XML to begin with: the check must refuse to replace it
        open(self.settings_path, "w").write(broken)
        r = self.run_script("install.sh")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(open(self.settings_path).read(), broken)




class SyncTest(Base):
    """tools/release/sync.sh: the plugin list follows the plugin folders (device checks skipped, MPC.settings is a copy)."""
    SKIN = "Acme - VST - Test Synth"
    ONLY_OTHER = SETTINGS_XML.replace(
        '      <PLUGIN name="Test Synth" format="VST" manufacturer="Acme" version="1.0" file="/sdcard/vst/test_synth.so" uid="1a2b3c4d" isInstrument="1"/>\n', "")

    def setUp(self):
        super().setUp()
        z = self.build()
        pkg = os.path.join(self.tmp, "pkg")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(pkg)
        self.top = os.path.join(pkg, os.listdir(pkg)[0])
        self.synths = os.path.join(self.tmp, "device", "Synths")
        os.makedirs(self.synths)
        shutil.copytree(os.path.join(self.top, "portable", self.SKIN), os.path.join(self.synths, self.SKIN))
        self.settings_path = os.path.join(self.tmp, "MPC.settings")
        self.log = os.path.join(self.tmp, "mpc_ctl.log")
        self.settings(self.ONLY_OTHER)

    def settings(self, text):
        open(self.settings_path, "w").write(text)

    def sync(self, *args, roots=None):
        env = dict(os.environ, MPC_INSTALL_TEST="1", MPC_SETTINGS=self.settings_path, MPC_TEST_LOG=self.log)
        if os.environ.get("INSTALLER_TEST_PATH"):
            env["PATH"] = os.environ["INSTALLER_TEST_PATH"]
        cmd = ["sh", os.path.join(HERE, "release", "sync.sh"), "-y", *args]
        for r in (roots or [self.synths]):
            cmd += ["-t", r]
        return subprocess.run(cmd, env=env, capture_output=True, text=True)

    def entries(self):
        import xml.etree.ElementTree as ET
        return {e.get("name"): e.get("file") for e in ET.parse(self.settings_path).getroot().iter("PLUGIN")}

    def calls(self):
        return open(self.log).read().split() if os.path.exists(self.log) else []

    def test_registers_an_unregistered_folder_and_touches_nothing_else(self):
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.entries()
        self.assertEqual(e["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))
        self.assertEqual(e["Other"], "/sdcard/vst/other.so")                     # not in a Synths folder: left alone
        self.assertEqual(self.calls(), ["stop", "start"])
        self.assertTrue([n for n in os.listdir(self.tmp) if n.startswith("MPC.settings.bak-sync-")])

    def test_second_run_does_nothing_and_does_not_restart_mpc(self):
        self.assertEqual(self.sync().returncode, 0)
        before = open(self.settings_path).read()
        os.remove(self.log)
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nothing to do", r.stdout)
        self.assertEqual(open(self.settings_path).read(), before)
        self.assertEqual(self.calls(), [])

    def test_removes_an_entry_whose_file_in_a_synths_folder_is_gone(self):
        gone = os.path.join(self.synths, "Gone - VST - X", "x.so")
        self.settings(self.ONLY_OTHER.replace("    </KNOWNPLUGINS>",
            '      <PLUGIN name="Gone" format="VST" manufacturer="x" version="1.0" file="%s" uid="deadbeef" isInstrument="1"/>\n    </KNOWNPLUGINS>' % gone))
        self.assertIn("Gone", self.entries())
        self.assertEqual(self.sync().returncode, 0)
        e = self.entries()
        self.assertNotIn("Gone", e)
        self.assertIn("Other", e)                                                # missing file, but not in a Synths folder: kept
        self.assertIn("Test Synth", e)

    def test_a_folder_without_its_so_is_not_registered_and_its_old_entry_goes(self):
        self.assertEqual(self.sync().returncode, 0)
        self.assertIn("Test Synth", self.entries())
        os.remove(os.path.join(self.synths, self.SKIN, "test_synth.so"))         # meta.xml stays, the plugin file is gone
        self.assertEqual(self.sync().returncode, 0)
        self.assertNotIn("Test Synth", self.entries())

    def test_an_old_layout_entry_with_the_same_uid_is_replaced(self):
        self.settings(SETTINGS_XML)                                              # Test Synth at /sdcard/vst/test_synth.so (not there)
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.entries()["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))
        self.assertEqual(len(self.entries()), 2)

    def test_dry_run_and_deferred_mode(self):
        before = open(self.settings_path).read()
        r = self.sync("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("add", r.stdout)
        self.assertEqual(open(self.settings_path).read(), before)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.sync("-n").returncode, 0)                          # -n: the caller stops and starts MPC
        self.assertEqual(self.calls(), [])
        self.assertIn("Test Synth", self.entries())

    def test_the_same_folder_through_two_roots_is_registered_once(self):
        alias = os.path.join(self.tmp, "device", "SynthsAlias")
        os.symlink(self.synths, alias)
        self.assertEqual(self.sync(roots=[self.synths, alias]).returncode, 0)
        self.assertEqual(len([n for n in self.entries() if n == "Test Synth"]), 1)
        self.assertEqual(self.entries()["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))   # first root wins

    def test_a_broken_settings_file_is_left_unchanged_and_mpc_is_restarted(self):
        self.settings("not xml at all\n")
        r = self.sync()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(open(self.settings_path).read(), "not xml at all\n")
        self.assertEqual(self.calls(), ["stop", "start"])

class StoreTest(Base):
    """tools/mpc-store.sh against a local fake catalog (catalog.tsv from catalog_site.tsv) and zips served over HTTP."""
    SKIN = "Acme - VST - Test Synth"

    def setUp(self):
        super().setUp()
        if not (os.environ.get("INSTALLER_TEST_PATH") or shutil.which("unzip")):
            self.skipTest("needs unzip (the device has it in BusyBox); or set INSTALLER_TEST_PATH to a folder of BusyBox applets")
        import http.server
        import threading
        import hashlib
        import catalog_site
        self.web = os.path.join(self.tmp, "web")
        os.makedirs(self.web)
        self.hashlib, self.catalog_site = hashlib, catalog_site
        self.versions = []
        for v in ("1.2.0", "1.3.0", "2.0.0"):
            z = self.build(version=v, extra=("--user-data", "roms"))
            shutil.copy(z, self.web)
            self.versions.append((v, os.path.join(self.web, os.path.basename(z))))
        for name, path in (("sync.sh", os.path.join(HERE, "release", "sync.sh")), ("plugin_list.awk", os.path.join(HERE, "release", "plugin_list.awk"))):
            shutil.copy(path, os.path.join(self.web, name))
        import functools

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=self.web))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.write_catalog(["1.2.0"])
        self.synths = os.path.join(self.tmp, "device", "Synths")
        self.settings_path = os.path.join(self.tmp, "MPC.settings")
        open(self.settings_path, "w").write(SyncTest.ONLY_OTHER)
        self.log = os.path.join(self.tmp, "mpc_ctl.log")

    def write_catalog(self, published, addins=(), gen2=None):
        vs = []
        for v, path in self.versions:
            if v not in published:
                continue
            rec = catalog_check.check(path, catalog=True)[2]
            m = rec["manifest"]
            vs.append({"version": v, "size": os.path.getsize(path), "sha256": self.hashlib.sha256(open(path, "rb").read()).hexdigest(),
                       "param_compat": int(v.split(".")[0]), "manifest": m, "channel": "stable", "yanked": False,
                       "os_compat": rec.get("os_compat"), "max_glibc": rec.get("max_glibc"),
                       "url": "http://127.0.0.1:%d/%s" % (self.port, os.path.basename(path))})
            if gen2 and v == "1.2.0":   # the aarch64 zip of the same version: assets{} as catalog_build.py writes them
                vs[-1]["assets"] = {"aarch64": {"size": os.path.getsize(gen2), "sha256": self.hashlib.sha256(open(gen2, "rb").read()).hexdigest(),
                                                "url": "http://127.0.0.1:%d/%s" % (self.port, os.path.basename(gen2))}}
        vs.sort(key=lambda x: [int(n) for n in x["version"].split(".")], reverse=True)
        cat = {"schema": 1, "plugins": [{"id": "test-synth", "name": "Test Synth", "kind": "instrument", "distribution": "release",
                                          "latest": vs[0]["version"], "versions": vs},
                                         {"id": "byo", "name": "Build Yourself", "kind": "instrument", "distribution": "build-yourself", "versions": []}]}
        avs = []
        for v in addins:   # (version, zip) of the test addin
            path = os.path.join(self.web, os.path.basename(v[1]))
            shutil.copy(v[1], path)
            avs.insert(0, {"version": v[0], "size": os.path.getsize(path), "sha256": self.hashlib.sha256(open(path, "rb").read()).hexdigest(),
                           "param_compat": int(v[0].split(".")[0]), "manifest": catalog_check.check(path, catalog=True)[2]["manifest"],
                           "channel": "stable", "yanked": False, "defer": True, "url": "http://127.0.0.1:%d/%s" % (self.port, os.path.basename(path))})
        if avs:
            cat["plugins"].append({"id": "test-addin", "name": "Test addin", "kind": "addin", "distribution": "release",
                                   "latest": avs[0]["version"], "versions": avs})
        helpers = [(n, os.path.join(self.web, n)) for n in ("sync.sh", "plugin_list.awk")]
        open(os.path.join(self.web, "catalog.tsv"), "w").write(self.catalog_site.tsv(cat, helpers))

    def store(self, *args, stdin="", env_extra=None):
        env = dict(os.environ, **(env_extra or {}), MPC_INSTALL_TEST="1", MPC_SETTINGS=self.settings_path, MPC_TEST_LOG=self.log, MPC_STORE_TMP=self.tmp,
                   MPC_LEGACY_ROOT=os.path.join(self.tmp, "nolegacy"),
                   ADDIN_INSTALL_TEST="1", SYSTEMD_ROOT=os.path.join(self.tmp, "root"), ADDIN_TEST_LOG=os.path.join(self.tmp, "addin.log"),
                   MPC_ADDINS=os.path.join(self.tmp, "addins"))
        if os.environ.get("INSTALLER_TEST_PATH"):
            env["PATH"] = os.environ["INSTALLER_TEST_PATH"]
        cmd = ["sh", os.path.join(HERE, "mpc-store.sh"), "-y", "-t", self.synths, "--url", "http://127.0.0.1:%d/catalog.tsv" % self.port, *args]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, input=stdin)

    def calls(self):
        return open(self.log).read().split() if os.path.exists(self.log) else []

    def entries(self):
        import xml.etree.ElementTree as ET
        return {e.get("name"): e.get("file") for e in ET.parse(self.settings_path).getroot().iter("PLUGIN")}

    def state(self):
        p = os.path.join(self.synths, ".mpc-store")
        return [l.split("\t") for l in open(p).read().splitlines()] if os.path.exists(p) else []

    def test_list_shows_downloadable_plugins_only(self):
        r = self.store("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("test-synth", r.stdout)
        self.assertNotIn("byo", r.stdout)
        os.makedirs(os.path.join(self.synths, self.SKIN))                        # a folder somebody copied there by hand
        self.assertIn("manual", self.store("list").stdout)

    def fake_libc(self, text=None, name="libc.so.6"):
        """A stand-in for the device's libc: an executable that prints what glibc prints when run, or (text=None) a plain file."""
        path = os.path.join(self.tmp, name)
        open(path, "w").write("#!/bin/sh\necho '%s'\n" % text if text else "x")
        os.chmod(path, 0o755 if text else 0o644)
        return {"MPC_STORE_LIBC": path}

    OLD_LIB = "GNU C Library (Buildroot 2021.02.12) stable release version 2.33."

    def test_a_3x_only_plugin_on_a_device_that_looks_like_2x_gets_a_note_and_still_installs(self):
        r = self.store("install", "test-synth", env_extra=self.fake_libc(self.OLD_LIB))   # the fake package's skin is "{}": 3.x only
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NOTE: Test Synth 1.2.0 is made for MPC OS 3.x", r.stdout)
        self.assertIn("glibc 2.33", r.stdout)
        self.assertEqual(self.calls(), ["stop", "start"])

    def test_no_note_on_a_3x_device_or_when_the_libc_cannot_be_found(self):
        for env in (self.fake_libc("GNU C Library (GNU libc) stable release version 2.39."),
                    {"MPC_STORE_LIBC": os.path.join(self.tmp, "nothing-here")}):
            r = self.store("install", "test-synth", env_extra=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("NOTE:", r.stdout)
            self.assertNotIn("WARNING:", r.stdout)
            shutil.rmtree(os.path.join(self.synths, self.SKIN), ignore_errors=True)

    def test_a_plugin_that_needs_a_newer_glibc_than_the_device_has_gets_a_warning(self):
        r = self.store("install", "test-synth", env_extra=self.fake_libc("GNU C Library stable release version 2.28."))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARNING: Test Synth 1.2.0 needs glibc 2.30 but this device has 2.28", r.stdout)
        self.assertNotIn("NOTE:", r.stdout)

    def test_older_glibc_is_read_from_the_library_file_name(self):
        r = self.store("install", "test-synth", env_extra=self.fake_libc(None, name="libc-2.32.so"))
        self.assertIn("NOTE: Test Synth 1.2.0 is made for MPC OS 3.x", r.stdout)
        self.assertIn("glibc 2.32", r.stdout)

    def test_list_marks_3x_only_plugins(self):
        self.assertIn("[MPC OS 3.x only]", self.store("list").stdout)

    def test_install_verifies_installs_and_restarts_mpc_once(self):
        r = self.store("install", "test-synth")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.synths, self.SKIN, "test_synth.so")))
        self.assertEqual(self.entries()["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))
        self.assertIn("Other", self.entries())
        self.assertEqual(self.calls(), ["stop", "start"])
        self.assertEqual(self.state(), [["test-synth", "1.2.0", self.SKIN, "1"]])

    def with_gen2(self):
        """Rewrite the catalog so 1.2.0 also has an aarch64 zip (the Gen2 build of the same version)."""
        z64 = self.build(version="1.2.0", machine=183, elf_class=2)
        shutil.copy(z64, self.web)
        self.write_catalog(["1.2.0"], gen2=os.path.join(self.web, os.path.basename(z64)))

    def test_a_gen2_device_installs_the_aarch64_zip(self):
        self.with_gen2()
        r = self.store("install", "test-synth", env_extra={"MPC_STORE_ARCH": "aarch64"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        so = open(os.path.join(self.synths, self.SKIN, "test_synth.so"), "rb").read(20)
        self.assertEqual(int.from_bytes(so[18:20], "little"), 183, "installed the armv7 library on a Gen2 device")

    def test_a_gen1_device_still_installs_the_armv7_zip(self):
        self.with_gen2()
        r = self.store("install", "test-synth", env_extra={"MPC_STORE_ARCH": "armv7l"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        so = open(os.path.join(self.synths, self.SKIN, "test_synth.so"), "rb").read(20)
        self.assertEqual(int.from_bytes(so[18:20], "little"), 40)

    def test_a_gen2_device_refuses_a_plugin_with_no_gen2_build(self):
        r = self.store("install", "test-synth", env_extra={"MPC_STORE_ARCH": "aarch64"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no Gen2", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.synths, self.SKIN)))

    def test_list_on_a_gen2_device_marks_plugins_without_a_gen2_build(self):
        r = self.store("list", env_extra={"MPC_STORE_ARCH": "aarch64"})
        self.assertIn("[no Gen2 build]", r.stdout)
        self.with_gen2()
        self.assertNotIn("[no Gen2 build]", self.store("list", env_extra={"MPC_STORE_ARCH": "aarch64"}).stdout)

    def test_an_old_installer_is_not_given_n_and_restarts_mpc_by_itself(self):
        import re
        v, path = self.versions[0]

        def old(data):   # what Dexed 1.0.1 and the other early releases look like: no -n option, no DEFER
            data = re.sub(rb"\n\s*-n\) DEFER=1;[^\n]*", b"", data)
            return data.replace(b"DEFER", b"XFER")
        new = self.resum(path, "install.sh", old)
        shutil.copy(new, path)
        self.write_catalog([v])
        r = self.store("install", "test-synth")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("restarts MPC by itself", r.stdout)
        self.assertEqual(self.entries()["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))
        self.assertEqual(self.calls(), ["stop", "start"])    # its own stop and start; the store adds none
        self.assertEqual(self.state()[0][:2], ["test-synth", v])

    MANIFEST = AddinTest.MANIFEST

    def addin_unit(self):
        d = os.path.join(self.tmp, "root", "usr", "lib", "systemd", "system")
        os.makedirs(d, exist_ok=True)
        self.unit = os.path.join(d, "acvs.service")
        open(self.unit, "w").write("[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\n")
        return os.path.join(self.tmp, "addins", "test-addin")

    def test_addins_install_with_plugins_in_one_restart_update_and_remove(self):
        folder = self.addin_unit()
        a1 = AddinTest.build_addin(self, version="1.2.0")
        self.write_catalog(["1.2.0"], addins=[("1.2.0", a1)])
        r = self.store("list")
        self.assertIn("Test addin (addin)", r.stdout)
        r = self.store("install", "test-synth", "test-addin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["stop", "start"])                        # one restart for the plugin and the addin
        self.assertNotIn("restart", open(os.path.join(self.tmp, "addin.log")).read())
        self.assertIn("LD_PRELOAD=/usr/lib/x.so:%s/libtest.so" % folder, open(self.unit).read())
        for f in ("libtest.so", "test.conf", "helper", "uninstall.sh", "addin-lib.sh", "addin.manifest"):
            self.assertTrue(os.path.exists(os.path.join(folder, f)), f)
        self.assertEqual([x[0] for x in self.state()], ["test-synth"])          # the addin's folder records its version
        self.assertRegex(self.store("list").stdout, r"test-addin\s+1\.2\.0\s+1\.2\.0")
        open(os.path.join(folder, "test.conf"), "w").write("mine\n")
        a2 = AddinTest.build_addin(self, version="1.3.0")
        self.write_catalog(["1.2.0"], addins=[("1.2.0", a1), ("1.3.0", a2)])
        r = self.store("update")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("test-addin: 1.2.0 -> 1.3.0", r.stdout)
        self.assertIn("ADDIN_VERSION=1.3.0", open(os.path.join(folder, "addin.manifest")).read())
        self.assertEqual(open(os.path.join(folder, "test.conf")).read(), "mine\n")   # the settings survive an update
        settings = open(self.settings_path).read()
        r = self.store("remove", "test-addin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(open(self.unit).read(), "[Service]\nEnvironment=LD_PRELOAD=/usr/lib/x.so\n")
        self.assertEqual(open(self.settings_path).read(), settings)                  # MPC.settings is not touched for an addin
        self.assertFalse([n for n in os.listdir(self.tmp) if ".bak-store" in n])
        self.assertEqual(self.calls()[-2:], ["stop", "start"])
        self.assertNotEqual(self.store("remove", "test-addin").returncode, 0)         # not installed any more

    def test_an_addin_folder_without_a_version_is_manual(self):
        folder = self.addin_unit()
        self.write_catalog(["1.2.0"], addins=[("1.2.0", AddinTest.build_addin(self))])
        os.makedirs(folder)
        open(os.path.join(folder, "addin.manifest"), "w").write("ADDIN_ID=test-addin\nADDIN_SO=libtest.so\n")
        self.assertRegex(self.store("list").stdout, r"test-addin\s+1\.2\.0\s+manual")
        self.assertIn("Nothing installed", self.store("update").stdout)

    def test_a_quoted_addin_version_is_read_without_its_quotes(self):
        folder = self.addin_unit()
        self.write_catalog(["1.2.0"], addins=[("1.2.0", AddinTest.build_addin(self))])
        os.makedirs(folder)
        open(os.path.join(folder, "addin.manifest"), "w").write('ADDIN_ID=test-addin\nADDIN_SO=libtest.so\nADDIN_VERSION="1.2.0"   # a note\n')
        self.assertRegex(self.store("list").stdout, r"test-addin\s+1\.2\.0\s+1\.2\.0")

    def test_prune_keeps_the_newest_backups_and_touches_nothing_else(self):
        base = self.settings_path
        for i in range(12):   # bak-...-01 is the oldest, -12 the newest
            f = "%s.bak-acid-20260101-%06d" % (base, i)
            open(f, "w").write("backup %d" % i)
            os.utime(f, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
        other = base + ".keep-me"
        open(other, "w").write("not a backup")
        before = open(base).read()
        left = lambda: sorted(n for n in os.listdir(self.tmp) if ".bak-" in n)
        self.assertEqual(self.store("prune", "--keep", "0").returncode, 1)               # the newest is never deleted
        self.assertEqual(self.store("prune", "--keep", "x").returncode, 1)
        self.assertEqual(len(left()), 12)
        r = self.store("--dry-run", "prune", "--keep", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deleting the 7 older ones", r.stdout)
        self.assertEqual(len(left()), 12)                                                  # a dry run deletes nothing
        r = self.store("prune", "--keep", "5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(left(), ["MPC.settings.bak-acid-20260101-%06d" % i for i in range(7, 12)])   # the five newest
        self.assertEqual(open(other).read(), "not a backup")
        self.assertEqual(open(base).read(), before)
        self.assertEqual(self.calls(), [])                                                 # MPC is never touched
        self.assertIn("nothing to delete", self.store("prune", "--keep", "5").stdout)

    def test_a_download_that_does_not_match_the_catalog_installs_nothing(self):
        path = self.versions[0][1]
        data = open(path, "rb").read()
        open(path, "wb").write(data[:-1] + bytes([data[-1] ^ 1]))
        r = self.store("install", "test-synth")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("sha256", r.stderr)
        self.assertFalse(os.path.exists(self.synths))
        self.assertEqual(self.calls(), [])                                       # MPC was never touched

    def test_unknown_and_build_yourself_ids_are_refused(self):
        for bad in ("nope", "byo"):
            r = self.store("install", bad)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(self.calls(), [])

    def test_update_takes_a_newer_version_and_holds_back_a_major_change(self):
        self.assertEqual(self.store("install", "test-synth").returncode, 0)
        os.remove(self.log)
        self.write_catalog(["1.2.0", "1.3.0"])
        r = self.store("update")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()[0][1], "1.3.0")
        os.remove(self.log)
        self.write_catalog(["1.2.0", "1.3.0", "2.0.0"])
        r = self.store("update")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("major", r.stdout)
        self.assertEqual(self.state()[0][1], "1.3.0")                            # held back
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.store("--major", "update").returncode, 0)
        self.assertEqual(self.state()[0][1], "2.0.0")

    def test_remove_deletes_the_folder_and_entry_but_keeps_user_files(self):
        self.assertEqual(self.store("install", "test-synth").returncode, 0)
        rom = os.path.join(self.synths, self.SKIN, "roms", "mine.rom")
        os.makedirs(os.path.dirname(rom))
        open(rom, "w").write("mine")
        os.remove(self.log)
        r = self.store("remove", "test-synth")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.synths, self.SKIN, "test_synth.so")))
        self.assertEqual(open(rom).read(), "mine")
        self.assertNotIn("Test Synth", self.entries())
        self.assertIn("Other", self.entries())
        self.assertEqual(self.state(), [])
        self.assertEqual(self.calls(), ["stop", "start"])

    def test_sync_command_uses_hash_checked_helpers(self):
        shutil.copytree(os.path.join(self.tmp, "web"), os.path.join(self.tmp, "keep"))
        self.assertEqual(self.store("install", "test-synth").returncode, 0)
        os.remove(self.log)
        gone = os.path.join(self.synths, self.SKIN, "test_synth.so")
        os.remove(gone)                                                          # the entry now points at a missing file
        r = self.store("sync")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Test Synth", self.entries())
        open(os.path.join(self.web, "sync.sh"), "a").write("\n# tampered\n")
        r = self.store("sync")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hash", r.stderr)


if __name__ == "__main__":
    unittest.main()
