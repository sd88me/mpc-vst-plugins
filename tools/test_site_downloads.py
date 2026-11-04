#!/usr/bin/env python3
"""Tests for tools/site_downloads.py (no network: a stand-in fetch)."""
import hashlib, io, json, os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_downloads as sd  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.data = b"PK zip bytes"
        self.lst = os.path.join(self.d, "l.json")
        self.entry = {"id": "pm-gen2", "file": "a.zip", "version": "1", "url": "https://github.com/o/r/releases/download/t/a.zip", "sha256": hashlib.sha256(self.data).hexdigest()}
        self.write([self.entry])

    def write(self, files):
        json.dump({"files": files}, open(self.lst, "w"))

    def test_publishes_checked_files(self):
        out = os.path.join(self.d, "site")
        pub = sd.build(self.lst, out, get=lambda u: self.data)
        self.assertEqual(open(os.path.join(out, "dl", "a.zip"), "rb").read(), self.data)
        self.assertEqual(pub["pm-gen2"]["path"], "dl/a.zip")
        self.assertEqual(json.load(open(os.path.join(out, "dl", "downloads.json")))["pm-gen2"]["sha256"], self.entry["sha256"])

    def test_mismatch_fails(self):
        with self.assertRaises(SystemExit):
            sd.build(self.lst, os.path.join(self.d, "s"), get=lambda u: b"other")

    def test_unreleased_is_skipped(self):
        def nf(u):
            raise urllib.error.HTTPError(u, 404, "nf", {}, io.BytesIO())
        self.assertEqual(sd.build(self.lst, os.path.join(self.d, "s"), get=nf), {})

    def test_bad_entries_refused(self):
        for bad in ({"url": "https://evil.example/a.zip"}, {"file": "../a.zip"}, {"sha256": "x"}):
            self.write([dict(self.entry, **bad)])
            with self.assertRaises(SystemExit):
                sd.build(self.lst, os.path.join(self.d, "s"), get=lambda u: self.data)

    def test_repo_list_and_stick_pin(self):
        es = {e["id"]: e for e in sd.entries(os.path.join(sd.ROOT, "catalog", "downloads.json"))}
        pin = json.load(open(os.path.join(sd.ROOT, "tools", "desktop", "g2stick-pin.json")))
        self.assertEqual(es["pm-stick"]["sha256"], pin["sha256"])
        self.assertEqual(set(es), {"pm-stick"})


if __name__ == "__main__":
    unittest.main()
