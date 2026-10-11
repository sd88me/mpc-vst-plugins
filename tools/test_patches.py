#!/usr/bin/env python3
"""Tests for the device patches (docs/PATCHES.md): the contract of tools/mpc_patch/mpc-drum-pad-patch.sh (status prints a STATE line,
install --confirmed skips the question, other firmware is refused) on a synthetic stand-in for the MPC binary, and tools/patch_check.py.
No Akai file is needed: the test rewrites the script's two checksums to those of a sparse dummy file and its patched twin.

  python3 tools/test_patches.py
"""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import patch_check  # noqa: E402

SCRIPT = os.path.join(ROOT, "tools", "mpc_patch", "mpc-drum-pad-patch.sh")
SH = shutil.which("dash") or shutil.which("sh")


class ScriptContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        src = open(SCRIPT).read()
        regs = [l.split() for l in re.search(r"PATCH_DATA='(.*?)'\n", src, re.S).group(1).splitlines() if l.strip()]
        size = max(int(o, 16) + len(h) // 2 for o, h in regs) + 64
        stock = bytearray(size)
        patched = bytearray(stock)
        for o, h in regs:
            patched[int(o, 16):int(o, 16) + len(h) // 2] = bytes.fromhex(h)
        cls.stock_md5 = hashlib.md5(bytes(stock)).hexdigest()
        cls.patched_md5 = hashlib.md5(bytes(patched)).hexdigest()
        s = re.sub(r"^STOCK_MD5=\S+", "STOCK_MD5=" + cls.stock_md5, src, flags=re.M)
        s = re.sub(r"^PATCHED_MD5=\S+", "PATCHED_MD5=" + cls.patched_md5, s, flags=re.M)
        cls.script = os.path.join(cls.dir, "script.sh")
        open(cls.script, "w").write(s)
        cls.stock = os.path.join(cls.dir, "stock")
        open(cls.stock, "wb").write(bytes(stock))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.work = os.path.join(self.dir, "work-" + self.id().split(".")[-1])
        self.bk = self.work + "-bk"
        shutil.copy(self.stock, self.work)

    def run_script(self, *args, target=None):
        env = dict(os.environ, MPC_PATCH_TEST=target or self.work, MPC_PATCH_BACKUP=self.bk)
        r = subprocess.run([SH, self.script, *args], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr

    def md5(self, p):
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def state(self, target=None):
        code, out = self.run_script("status", target=target)
        self.assertEqual(code, 0, out)
        lines = [l for l in out.splitlines() if l.startswith("STATE ")]
        self.assertEqual(len(lines), 1, out)
        self.assertEqual(out.splitlines()[-1], lines[0], "the STATE line must be last")
        return dict(kv.split("=") for kv in lines[0].split()[1:])

    def test_status_reports_each_state_and_changes_nothing(self):
        self.assertEqual(self.state(), {"state": "stock", "supported": "1", "backup": "0", "checksum": self.stock_md5})
        self.assertEqual(self.md5(self.work), self.stock_md5)
        bad = os.path.join(self.dir, "bad.bin")
        open(bad, "wb").write(b"not an MPC")
        self.assertEqual(self.state(bad), {"state": "unsupported", "supported": "0", "backup": "0", "checksum": self.md5(bad)})

    def test_confirmed_install_needs_no_typed_word_then_undo(self):
        code, out = self.run_script("install", "--confirmed")  # stdin is empty: a prompt would cancel
        self.assertEqual(code, 0, out)
        self.assertEqual(self.md5(self.work), self.patched_md5)
        self.assertEqual(self.state(), {"state": "patched", "supported": "1", "backup": "1", "checksum": self.patched_md5})
        code, out = self.run_script("uninstall")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.md5(self.work), self.stock_md5)

    def test_plain_install_still_asks(self):
        code, out = self.run_script("install")
        self.assertNotEqual(code, 0)
        self.assertIn("cancelled", out)
        self.assertEqual(self.md5(self.work), self.stock_md5)

    def test_other_firmware_is_refused_even_when_confirmed(self):
        bad = os.path.join(self.dir, "bad2.bin")
        open(bad, "wb").write(b"not an MPC")
        code, out = self.run_script("install", "--confirmed", target=bad)
        self.assertNotEqual(code, 0)
        self.assertIn("Refusing", out)
        self.assertEqual(open(bad, "rb").read(), b"not an MPC")

    # an unknown build (say an earlier development version of the patch) with the full backup of the stock program saved by an install
    def unknown_build(self, backup_content="stock"):
        with open(self.work, "r+b") as f:
            f.seek(100)
            f.write(b"some other build")
        self.assertNotIn(self.md5(self.work), (self.stock_md5, self.patched_md5))
        os.makedirs(self.bk, exist_ok=True)
        if backup_content == "stock":
            shutil.copy(self.stock, os.path.join(self.bk, "MPC-3.9.1.2.orig"))
        elif backup_content == "wrong":
            shutil.copy(self.work, os.path.join(self.bk, "MPC-3.9.1.2.orig"))

    def test_status_of_an_unknown_build_names_its_checksum_and_the_way_back(self):
        self.unknown_build()
        st = self.state()
        self.assertEqual((st["state"], st["supported"], st["backup"], st["checksum"]), ("unsupported", "0", "1", self.md5(self.work)))
        _, out = self.run_script("status")
        self.assertIn("uninstall", out)

    def test_install_still_refuses_an_unknown_build(self):
        self.unknown_build()
        before = self.md5(self.work)
        code, out = self.run_script("install", "--confirmed")
        self.assertNotEqual(code, 0)
        self.assertIn("Refusing", out)
        self.assertEqual(self.md5(self.work), before)

    def test_uninstall_restores_an_unknown_build_from_a_verified_backup(self):
        self.unknown_build()
        code, out = self.run_script("uninstall", "--confirmed")
        self.assertEqual(code, 0, out)
        self.assertIn("restored stock MPC from the full backup", out)
        self.assertEqual(self.md5(self.work), self.stock_md5)

    def test_that_restore_asks_for_the_typed_word_first(self):
        self.unknown_build()
        before = self.md5(self.work)
        code, out = self.run_script("uninstall")  # empty stdin: cancelled
        self.assertNotEqual(code, 0)
        self.assertIn("cancelled", out)
        self.assertEqual(self.md5(self.work), before)

    def test_a_backup_that_is_not_stock_is_never_copied_over_the_program(self):
        self.unknown_build("wrong")
        before = self.md5(self.work)
        code, out = self.run_script("uninstall", "--confirmed")
        self.assertNotEqual(code, 0)
        self.assertIn("not the stock MPC", out)
        self.assertEqual(self.md5(self.work), before)

    def test_no_backup_means_nothing_is_touched(self):
        self.unknown_build(None)
        before = self.md5(self.work)
        code, out = self.run_script("uninstall", "--confirmed")
        self.assertNotEqual(code, 0)
        self.assertIn("no full backup", out)
        self.assertEqual(self.md5(self.work), before)

    def test_unknown_flag_is_refused(self):
        code, _ = self.run_script("install", "--nope")
        self.assertEqual(code, 1)
        self.assertEqual(self.md5(self.work), self.stock_md5)


class ManifestCheck(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "catalog", "patches.json")) as f:
            self.doc = json.load(f)

    def errors(self, doc=None):
        return patch_check.check(doc or self.doc)[0]

    def test_the_real_manifest_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_a_stale_hash_fails(self):
        d = copy.deepcopy(self.doc)
        d["patches"][0]["script"]["sha256"] = "0" * 64
        self.assertTrue(any("does not match" in e for e in self.errors(d)))

    def test_a_branch_url_fails(self):
        d = copy.deepcopy(self.doc)
        d["patches"][0]["script"]["url"] = "https://example.org/main/p.sh"
        self.assertTrue(any("pinned" in e for e in self.errors(d)))

    def test_plain_http_fails(self):
        d = copy.deepcopy(self.doc)
        d["patches"][0]["script"]["url"] = "http://example.org/abc/p.sh"
        self.assertTrue(any("https" in e for e in self.errors(d)))

    def test_irreversible_and_missing_fields_fail(self):
        d = copy.deepcopy(self.doc)
        d["patches"][0]["reversible"] = False
        self.assertTrue(any("uninstall" in e for e in self.errors(d)))
        d = copy.deepcopy(self.doc)
        del d["patches"][0]["modifies"]
        self.assertTrue(any("missing" in e for e in self.errors(d)))

    def test_duplicate_ids_and_path_escape_fail(self):
        d = copy.deepcopy(self.doc)
        d["patches"].append(copy.deepcopy(d["patches"][0]))
        self.assertTrue(any("duplicate" in e for e in self.errors(d)))
        d = copy.deepcopy(self.doc)
        d["patches"][0]["script"]["url"] = "https://raw.githubusercontent.com/sd88me/mpc-vst-plugins/" + "a" * 40 + "/../x.sh"
        self.assertTrue(any("escapes" in e for e in self.errors(d)))


class SitePublishesManifest(unittest.TestCase):
    def build(self, patches):
        out = tempfile.mkdtemp()
        cat = os.path.join(out, "catalog.json")
        with open(cat, "w") as f:
            json.dump({"schema": 1, "plugins": []}, f)
        r = subprocess.run([sys.executable, os.path.join(HERE, "catalog_site.py"), "--catalog", cat, "--out", os.path.join(out, "site"),
                            "--patches", patches], capture_output=True, text=True, timeout=60, cwd=ROOT)
        return out, r

    def test_the_manifest_is_published_next_to_catalog_json(self):
        src = os.path.join(ROOT, "catalog", "patches.json")
        out, r = self.build(src)
        self.addCleanup(shutil.rmtree, out, True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(src, "rb") as a, open(os.path.join(out, "site", "patches.json"), "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_every_patch_has_a_listed_card_and_a_guide_page_out_of_the_menu(self):
        src = os.path.join(ROOT, "catalog", "patches.json")
        out, r = self.build(src)
        self.addCleanup(shutil.rmtree, out, True)
        self.assertEqual(r.returncode, 0, r.stderr)
        site = os.path.join(out, "site")
        with open(src) as f:
            doc = json.load(f)
        overview = open(os.path.join(site, "patches.html"), encoding="utf-8").read()
        index = open(os.path.join(site, "index.html"), encoding="utf-8").read()
        self.assertIn('href="patches.html"', index)
        for p in doc["patches"]:
            self.assertIn(p["script"]["sha256"], overview)
            self.assertIn('href="patch-%s.html"' % p["id"], overview)
            self.assertTrue(os.path.isfile(os.path.join(site, "patch-%s.html" % p["id"])))
            self.assertNotIn('href="patch-%s.html"' % p["id"], index.split("<main")[0])   # guides are not in the menu
            self.assertIn('href="patch-%s.html"' % p["id"], index)   # but the Device patches tab on the catalog page links them

    def test_an_invalid_manifest_fails_the_site_build(self):
        bad = os.path.join(tempfile.mkdtemp(), "patches.json")
        with open(bad, "w") as f:
            json.dump({"schema": 1, "patches": [{"id": "x"}]}, f)
        out, r = self.build(bad)
        self.addCleanup(shutil.rmtree, out, True)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(out, "site", "patches.json")))


if __name__ == "__main__":
    unittest.main()
