#!/usr/bin/env python3
"""Offline tests for tools/make_skinset.py: the folder layout it writes, the path rewriting, and the switch.

No Pillow, no art tool, no device: three fake skins with a TUI.json, a Q-Link bank and a png each.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_skinset  # noqa: E402


def fake_skin(root, name, colour):
    """A minimal built skin: TUI.json with bare image names, one Q-Link file, one png."""
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    tui = {
        "pageData": {
            "tabs": [{"tabName": name.upper(), "fnKeyIndex": 0, "fnKeySubIndex": 0}],
            "componentDefinitions": {
                "version": 2,
                "importFiles": ["/usr/share/Akai/Content/Synths/Generic/Generic Knob Overlay.json"],
                "localComponentDefinitions": [
                    {"key": name + "|bg", "value": {"backgroundData": {"image": "bg.png"}}},
                    {"key": name + "|knob", "value": {"image": "knob.png", "imageOff": "knob.png",
                                                       "note": "bg.png stays text here"}},
                ],
            },
        }
    }
    json.dump(tui, open(os.path.join(d, "TUI.json"), "w"))
    json.dump({"version": 4, "Screen Mode Q-Links": {"map": []}},
              open(os.path.join(d, "Q-Links.json"), "w"))
    open(os.path.join(d, "bg.png"), "wb").write(b"\x89PNG\r\n\x1a\n" + colour)
    open(os.path.join(d, "knob.png"), "wb").write(b"\x89PNG\r\n\x1a\n" + colour)
    return d


class Skinset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = [fake_skin(self.tmp, n, c) for n, c in (("studio", b"S"), ("classic", b"C"), ("rack", b"R"))]
        self.out = os.path.join(self.tmp, "out", "Plugin Skins")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_specs(self, specs, active=None):
        argv = ["make_skinset.py", "-o", self.out]
        if active:
            argv += ["--active", active]
        argv += specs
        old, sys.argv = sys.argv, argv
        try:
            make_skinset.main()
        finally:
            sys.argv = old

    def run_tool(self, active=None, order=("studio", "classic", "rack")):
        self.run_specs(["%s=%s" % (n, os.path.join(self.tmp, n)) for n in order], active)
        return json.load(open(os.path.join(self.out, "TUI.json")))

    def test_each_interface_gets_its_own_subfolder_with_its_files(self):
        self.run_tool()
        for n in ("studio", "classic", "rack"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, n, "TUI.json")), n)
            self.assertTrue(os.path.isfile(os.path.join(self.out, n, "bg.png")), n)
            self.assertTrue(os.path.isfile(os.path.join(self.out, n, "Q-Links.json")), n)

    def test_image_paths_are_prefixed_and_absolute_paths_are_left_alone(self):
        self.run_tool()
        tui = json.load(open(os.path.join(self.out, "classic", "TUI.json")))
        defs = {d["key"]: d["value"] for d in tui["pageData"]["componentDefinitions"]["localComponentDefinitions"]}
        self.assertEqual(defs["classic|bg"]["backgroundData"]["image"], "classic/bg.png")
        self.assertEqual(defs["classic|knob"]["image"], "classic/knob.png")
        # prose that happens to name a file is not a path
        self.assertEqual(defs["classic|knob"]["note"], "bg.png stays text here")
        # an absolute import is untouched
        imports = tui["pageData"]["componentDefinitions"]["importFiles"]
        self.assertEqual(imports, ["/usr/share/Akai/Content/Synths/Generic/Generic Knob Overlay.json"])

    def test_the_first_interface_is_active_by_default(self):
        tui = self.run_tool()
        self.assertEqual(tui["pageData"]["tabs"][0]["tabName"], "STUDIO")
        self.assertEqual(open(os.path.join(self.out, "ui.txt")).read().strip(), "studio")

    def test_active_picks_the_top_level_copy_and_keeps_every_interface(self):
        tui = self.run_tool(active="rack")
        self.assertEqual(tui["pageData"]["tabs"][0]["tabName"], "RACK")
        self.assertEqual(open(os.path.join(self.out, "ui.txt")).read().strip(), "rack")
        defs = {d["key"]: d["value"] for d in tui["pageData"]["componentDefinitions"]["localComponentDefinitions"]}
        self.assertEqual(defs["rack|bg"]["backgroundData"]["image"], "rack/bg.png")
        for n in ("studio", "classic"):            # switching later must not need a rebuild
            self.assertTrue(os.path.isfile(os.path.join(self.out, n, "TUI.json")), n)

    def test_switching_rewrites_only_the_small_files(self):
        self.run_tool()
        before = {n: open(os.path.join(self.out, n, "bg.png"), "rb").read() for n in ("studio", "classic", "rack")}
        self.run_tool(active="classic")
        after = {n: open(os.path.join(self.out, n, "bg.png"), "rb").read() for n in ("studio", "classic", "rack")}
        self.assertEqual(before, after)            # no image is touched, so a running instance is safe
        self.assertEqual(json.load(open(os.path.join(self.out, "TUI.json")))["pageData"]["tabs"][0]["tabName"], "CLASSIC")

    def test_unknown_active_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_tool(active="nope")

    def test_a_source_without_tui_is_refused(self):
        os.remove(os.path.join(self.tmp, "rack", "TUI.json"))
        with self.assertRaises(SystemExit):
            self.run_tool()

    def test_a_name_that_is_not_one_plain_folder_is_refused(self):
        # The name becomes the subfolder and is rmtree()d on every rebuild: a name like '..' or '../x' would
        # delete outside the skin folder. Refused before anything is created or removed.
        sentinel = os.path.join(self.tmp, "keep.txt")
        open(sentinel, "w").write("x")
        src = os.path.join(self.tmp, "studio")
        for bad in ("", ".", "..", "../evil", "studio/../rack", "/tmp/evil", "a\\b", "x\0y"):
            with self.assertRaises(SystemExit, msg=bad):
                self.run_specs(["%s=%s" % (bad, src)])
        self.assertTrue(os.path.isfile(sentinel))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out")))

    def test_duplicate_names_are_refused(self):
        with self.assertRaises(SystemExit):
            self.run_specs(["studio=%s" % os.path.join(self.tmp, "studio"),
                            "studio=%s" % os.path.join(self.tmp, "classic")])


if __name__ == "__main__":
    unittest.main()
