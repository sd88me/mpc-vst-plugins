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


def fake_so(path, machine=40, glibc=b"GLIBC_2.30"):
    hdr = bytearray(b"\x7fELF" + bytes(16))
    hdr[18:20] = machine.to_bytes(2, "little")
    open(path, "wb").write(bytes(hdr) + b"\0" + glibc + b"\0")


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

    def build(self, version="1.2.0", machine=40, glibc=b"GLIBC_2.30", extra=()):
        t = self.tmp
        fake_so(os.path.join(t, "test_synth.so"), machine, glibc)
        skin = os.path.join(t, "Acme - VST - Test Synth")
        os.makedirs(os.path.join(skin, "Plugin Skins"), exist_ok=True)
        open(os.path.join(skin, "version.xml"), "w").write("<v/>")
        open(os.path.join(skin, "Plugin Skins", "TUI.json"), "w").write("{}")
        open(os.path.join(t, "entry.xml"), "w").write(ENTRY)
        out = os.path.join(t, "dist")
        subprocess.check_call([sys.executable, os.path.join(HERE, "release.py"), "--so", os.path.join(t, "test_synth.so"),
                               "--skin", skin, "--entry", os.path.join(t, "entry.xml"), "--version", version,
                               "--repo", "acme/test-synth", "--license", "MIT", "-o", out, *extra],
                              stdout=subprocess.DEVNULL)
        return os.path.join(out, "Test-Synth-%s-mpc-armv7.zip" % version)

    def tamper(self, zpath, member_suffix, fn):
        out = zpath + ".t.zip"
        with zipfile.ZipFile(zpath) as zin, zipfile.ZipFile(out, "w") as zout:
            for i in zin.infolist():
                data = zin.read(i.filename)
                if i.filename.endswith(member_suffix):
                    data = fn(data)
                zout.writestr(i, data)
        return out


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
        e, _, _ = catalog_check.check(self.build(glibc=b"GLIBC_2.38"))
        self.assertTrue(any("GLIBC" in x for x in e))

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

    def rel(self, tag, aid, pre=False, name="x-mpc-armv7.zip"):
        return {"tag_name": tag, "prerelease": pre, "draft": False, "published_at": "2026-09-29T00:00:00Z", "body": "notes",
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

    def test_registry_rules(self):
        self.assertEqual(catalog_build.check_entry(self.ENTRY, "x/test-synth.json"), [])
        self.assertTrue(catalog_build.check_entry({**self.ENTRY, "license": "Proprietary"}))
        self.assertTrue(catalog_build.check_entry(self.ENTRY, "x/other.json"))
        self.assertTrue(catalog_build.check_entry({**self.ENTRY, "repo": "nope"}))


import catalog_issues  # noqa: E402


class IssuesTest(unittest.TestCase):
    def test_plan_dedupes_and_skips_open(self):
        pr = [{"id": "a", "tag": "v1", "error": "x"}, {"id": "a", "tag": "v1", "error": "y"},
              {"id": "a", "tag": "v2", "error": "z"}, {"id": "b", "tag": None, "error": "404"}]
        got = catalog_issues.plan(pr, {"Catalog: a v2 failed validation"})
        self.assertEqual([t for t, _ in got], ["Catalog: a v1 failed validation", "Catalog: b cannot be read"])
        self.assertIn("- x", got[0][1]); self.assertIn("- y", got[0][1])


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


if __name__ == "__main__":
    unittest.main()


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

    def write_catalog(self, published):
        vs = []
        for v, path in self.versions:
            if v not in published:
                continue
            m = catalog_check.check(path, catalog=True)[2]["manifest"]
            vs.append({"version": v, "size": os.path.getsize(path), "sha256": self.hashlib.sha256(open(path, "rb").read()).hexdigest(),
                       "param_compat": int(v.split(".")[0]), "manifest": m, "channel": "stable", "yanked": False,
                       "url": "http://127.0.0.1:%d/%s" % (self.port, os.path.basename(path))})
        vs.sort(key=lambda x: [int(n) for n in x["version"].split(".")], reverse=True)
        cat = {"schema": 1, "plugins": [{"id": "test-synth", "name": "Test Synth", "kind": "instrument", "distribution": "release",
                                          "latest": vs[0]["version"], "versions": vs},
                                         {"id": "byo", "name": "Build Yourself", "kind": "instrument", "distribution": "build-yourself", "versions": []}]}
        helpers = [(n, os.path.join(self.web, n)) for n in ("sync.sh", "plugin_list.awk")]
        open(os.path.join(self.web, "catalog.tsv"), "w").write(self.catalog_site.tsv(cat, helpers))

    def store(self, *args, stdin=""):
        env = dict(os.environ, MPC_INSTALL_TEST="1", MPC_SETTINGS=self.settings_path, MPC_TEST_LOG=self.log, MPC_STORE_TMP=self.tmp,
                   MPC_LEGACY_ROOT=os.path.join(self.tmp, "nolegacy"))
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

    def test_install_verifies_installs_and_restarts_mpc_once(self):
        r = self.store("install", "test-synth")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.synths, self.SKIN, "test_synth.so")))
        self.assertEqual(self.entries()["Test Synth"], os.path.join(self.synths, self.SKIN, "test_synth.so"))
        self.assertIn("Other", self.entries())
        self.assertEqual(self.calls(), ["stop", "start"])
        self.assertEqual(self.state(), [["test-synth", "1.2.0", self.SKIN, "1"]])

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

