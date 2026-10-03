#!/usr/bin/env python3
"""Offline unit tests for shadow_skin geometry/invariants that don't need the art toolchain or a device:
seg_rects honouring sw=, and the two filmstrip frame-count conventions. No device: python3 tools/test_shadow_skin.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shadow_skin  # noqa: E402


class SegRects(unittest.TestCase):
    def widths(self, w):
        return {r[2] for r in shadow_skin.seg_rects(w)}

    def test_enum_v_defaults_to_135(self):
        w = {"kind": "enum_v", "options": ["A", "B", "C"], "cx": 100, "cy": 100}
        self.assertEqual(self.widths(w), {135})

    def test_enum_v_honours_sw(self):
        w = {"kind": "enum_v", "options": ["A", "B", "C"], "cx": 100, "cy": 100, "sw": 56}
        self.assertEqual(self.widths(w), {56})

    def test_enum_h_defaults_to_117(self):
        w = {"kind": "enum_h", "options": ["A", "B"], "cx": 100, "cy": 100}
        self.assertEqual(self.widths(w), {117})

    def test_enum_h_honours_sw(self):
        w = {"kind": "enum_h", "options": ["A", "B"], "cx": 100, "cy": 100, "sw": 68}
        self.assertEqual(self.widths(w), {68})


class FilmStripFrames(unittest.TestCase):
    def test_rotary_knob_is_one_fewer_than_strip(self):
        self.assertEqual(shadow_skin.ROT_FRAMES, shadow_skin.FRAMES - 1)

    def test_slider_and_meter_equal_strip_length(self):
        # the (l)sstrip generator emits exactly FRAMES frames for sliders and meters, so their FilmStrip
        # numFrames must match it; FRAMES-1 here is the second-thumb bug.
        self.assertEqual(shadow_skin.STRIP_FRAMES, shadow_skin.FRAMES)


def _gen_like_tui():
    """A TUI.json shaped like write_skin's output (MPC OS 3.x): one tab pointing at a local page definition, one
    widget definition holding a Knob and a Button, version 4 definitions, tab 3, Knob 5, Button 2."""
    def child(ctype, data):
        return {"version": 2, "componentData": {"version": 1, "name": ctype, "type": ctype, "data": data},
                "handle remapping": {"version": 1, "map": []},
                "bounds": {"version": 2, "acceptsHWFocus": "No", "showWhenDataModelInvalid": "Show",
                           "whenVisible": "Always", "boundsType": "Absolute", "bounds": "0 0 10 10",
                           "additionalInvalidatingHandles": []}}
    bg = {"version": 1, "focussed": {"version": 1, "colour": "0", "image": ""},
          "unfocussed": {"version": 1, "colour": "0", "image": ""}}

    def definition(kids):
        return {"version": 4, "actions": [], "backgroundData": bg, "ignoreMousePresses": False,
                "disableCoarseDataWheel": False, "repeats": False, "hideQLinkBounds": False, "componentsData": kids}
    widget = definition([
        child("Knob", {"version": 5, "knobType": "FilmStrip", "filmStrip": "k.png", "numFrames": 127,
                       "invert": False, "dragOrientation": "Vertical", "handleName": "Data"}),
        child("Button", {"version": 2, "onImage": "a.png", "offImage": "b.png", "buttonId": 1,
                         "numButtonsInGroup": 1, "handleName": "Data", "gestureBehaviour": "Instant"}),
        child("Label", {"version": 1, "type": "Value", "handleName": "Data"})])
    return {"pageData": {"version": 1, "info": {"version": 1, "type": "CompleteDescription"},
            "componentDefinitions": {"version": 2, "importFiles": ["/x/Generic Knob Overlay.json"],
                                     "localComponentDefinitions": [
                                         {"key": "wKnob", "value": widget},
                                         {"key": "GLOBAL|GLOBAL", "value": definition([child("Image", {
                                             "version": 2, "imageType": "Regular", "colour": "0", "image": "bg.png"}),
                                             child("wKnob", {"version": 1, "handleName": "Data"})])}]},
            "tabs": [{"version": 3, "tabName": "GLOBAL", "fnKeyIndex": 0, "fnKeySubIndex": 0,
                      "qlinkBoundsData": ["0 0 0 0"], "componentName": "GLOBAL|GLOBAL",
                      "initialSize": "0 0 1280 628", "scale": 1.0}]}}


def _versions(o, out=None):
    out = [] if out is None else out
    if isinstance(o, dict):
        if "version" in o:
            out.append(o["version"])
        for x in o.values():
            _versions(x, out)
    elif isinstance(o, list):
        for x in o:
            _versions(x, out)
    return out


class ToMpc2x(unittest.TestCase):
    """The MPC OS 2.15.1 shape (docs/NOTES.md, 2026-10-03). Experimental: not yet confirmed on a device."""

    def setUp(self):
        self.tui = shadow_skin.to_mpc2x(_gen_like_tui())
        self.pd = self.tui["pageData"]

    def test_nothing_above_version_2_remains(self):
        self.assertLessEqual(max(_versions(self.tui)), 2)

    def test_tab_is_version_1_with_the_page_inline(self):
        t = self.pd["tabs"][0]
        self.assertEqual(sorted(t), ["componentDefinition", "fnKeyIndex", "fnKeySubIndex", "qlinkBoundsData",
                                     "tabName", "version"])
        self.assertEqual(t["version"], 1)
        self.assertEqual(t["componentDefinition"]["version"], 2)
        self.assertEqual(t["componentDefinition"]["componentsData"][1]["componentData"]["type"], "wKnob")

    def test_inlined_page_leaves_the_local_definitions(self):
        keys = [d["key"] for d in self.pd["componentDefinitions"]["localComponentDefinitions"]]
        self.assertEqual(keys, ["wKnob"])

    def test_definitions_are_version_2_without_the_newer_fields(self):
        for d in [self.pd["componentDefinitions"]["localComponentDefinitions"][0]["value"],
                  self.pd["tabs"][0]["componentDefinition"]]:
            self.assertEqual(d["version"], 2)
            self.assertNotIn("repeats", d)
            self.assertNotIn("hideQLinkBounds", d)
            self.assertIn("disableCoarseDataWheel", d)

    def test_knob_and_button_data_are_version_1(self):
        kids = self.pd["componentDefinitions"]["localComponentDefinitions"][0]["value"]["componentsData"]
        knob, button = kids[0]["componentData"]["data"], kids[1]["componentData"]["data"]
        self.assertEqual(knob, {"version": 1, "knobType": "FilmStrip", "filmStrip": "k.png", "numFrames": 127,
                                "handleName": "Data"})
        self.assertEqual(button, {"version": 1, "onImage": "a.png", "offImage": "b.png", "buttonId": 1,
                                  "numButtonsInGroup": 1, "handleName": "Data"})

    def test_a_tab_pointing_at_a_missing_definition_is_an_error(self):
        t = _gen_like_tui()
        t["pageData"]["tabs"][0]["componentName"] = "nope"
        with self.assertRaises(SystemExit):
            shadow_skin.to_mpc2x(t)


if __name__ == "__main__":
    unittest.main()
