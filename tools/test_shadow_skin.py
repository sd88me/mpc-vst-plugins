#!/usr/bin/env python3
"""Offline unit tests for shadow_skin geometry/invariants that don't need the art toolchain or a device:
seg_rects honouring sw=, the talign= defaults, the two filmstrip frame-count conventions, and html_art's inlined
SVGs keeping their ids and classes apart. No device: python3 tools/test_shadow_skin.py"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shadow_skin  # noqa: E402
import html_art  # noqa: E402


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


class QLinkBounds(unittest.TestCase):
    TAB = {"widgets": [{"kind": "knob", "key": k, "cx": 100 + 150 * i, "cy": 300, "r": 30}
                       for i, k in enumerate("abcdefgh")]}

    def tearDown(self):
        shadow_skin.apply_theme([])

    def test_outlines_are_opt_in(self):
        shadow_skin.apply_theme([])
        self.assertFalse(shadow_skin.QLINK_COLUMNS)
        shadow_skin.apply_theme(["qlink_bounds=column"])
        self.assertTrue(shadow_skin.QLINK_COLUMNS)
        shadow_skin.apply_theme([])
        self.assertFalse(shadow_skin.QLINK_COLUMNS)

    def test_one_rect_per_column_empty_slots_skipped(self):
        rects = shadow_skin.qlink_column_bounds(self.TAB, list("abcd") + ["-"] * 4 + list("efgh"))
        self.assertEqual(len(rects), 3)
        self.assertEqual(rects[1], "0 0 0 0")
        x0 = [int(r.split()[0]) for r in (rects[0], rects[2])]
        self.assertLess(x0[0], x0[1])
        self.assertEqual(len(shadow_skin.qlink_column_bounds(self.TAB, list("abcd") + ["-"] * 4)), 1)


class StudioPreviewTabs(unittest.TestCase):
    """studio.preview must read a skin in either shape: release.sh previews whatever the build wrote."""

    def test_tab_components_reads_both_shapes(self):
        import studio
        kids = [{"componentData": {"type": "Image"}}]
        named = {"tabName": "A", "componentName": "A|A"}
        inline = {"tabName": "A", "componentDefinition": {"componentsData": kids}}
        self.assertEqual(studio.tab_components(named, {"A|A": {"componentsData": kids}}), kids)
        self.assertEqual(studio.tab_components(inline, {}), kids)

    def test_a_generated_2x_skin_previews_like_a_3x_one(self):
        tui = _gen_like_tui()
        defs = {d["key"]: d["value"] for d in tui["pageData"]["componentDefinitions"]["localComponentDefinitions"]}
        import studio
        before = studio.tab_components(tui["pageData"]["tabs"][0], defs)
        shadow_skin.to_mpc2x(tui)
        after = studio.tab_components(tui["pageData"]["tabs"][0], {})
        self.assertEqual([c["componentData"]["type"] for c in before], [c["componentData"]["type"] for c in after])


class TextAlignDefaults(unittest.TestCase):
    """Readouts centre their text unless talign= says otherwise (skins built before talign= existed keep their look);
    list rows start at the left."""

    def test_readouts_default_to_centred(self):
        self.assertEqual(shadow_skin.live_text({}, 26.0, "ffffff", shadow_skin.READOUT_JUST)[2],
                         "horizontallyCentred verticallyCentred")

    def test_list_rows_default_to_left(self):
        self.assertEqual(shadow_skin.live_text({}, 24.0, "ffffff", shadow_skin.ROW_JUST)[2], "left verticallyCentred")

    def test_talign_overrides_the_default(self):
        self.assertEqual(shadow_skin.live_text({"talign": "left"}, 26.0, "ffffff", shadow_skin.READOUT_JUST)[2],
                         "left verticallyCentred")

class ListOrder(unittest.TestCase):
    W = {"key": "slot", "cols": 2, "rows": 3}

    def keys(self, **kw):
        return [k.split("_")[-1] for k in shadow_skin.list_keys(dict(self.W, **kw))]

    def test_default_numbers_across_each_row(self):
        self.assertEqual(self.keys(), ["1", "2", "3", "4", "5", "6"])

    def test_pads_number_from_the_bottom(self):
        self.assertEqual(self.keys(order="pads"), ["5", "6", "3", "4", "1", "2"])

    def test_cols_number_down_each_column_first(self):
        # tiles are laid out row by row (left, right, left, right ...): the left column holds 1..rows, the right the next rows
        self.assertEqual(self.keys(order="cols"), ["1", "4", "2", "5", "3", "6"])
        self.assertEqual(sorted(self.keys(order="cols")), sorted(self.keys()))   # the same keys, only placed differently

    def test_cols_with_three_columns(self):
        w = {"key": "s", "cols": 3, "rows": 2, "order": "cols"}
        self.assertEqual([k.split("_")[-1] for k in shadow_skin.list_keys(w)], ["1", "3", "5", "2", "4", "6"])


class FilmStripFrames(unittest.TestCase):
    def test_rotary_knob_is_one_fewer_than_strip(self):
        self.assertEqual(shadow_skin.ROT_FRAMES, shadow_skin.FRAMES - 1)

    def test_slider_and_meter_equal_strip_length(self):
        # the (l)sstrip generator emits exactly FRAMES frames for sliders and meters, so their FilmStrip
        # numFrames must match it; FRAMES-1 here is the second-thumb bug.
        self.assertEqual(shadow_skin.STRIP_FRAMES, shadow_skin.FRAMES)


class BuildAttrs(unittest.TestCase):
    """banks= (controls per Q-Link sub-page) and ns=/vs=/bw= (text sizes, touch width), built with a stub renderer."""
    PARAMS = [{"key": k, "name": k.upper(), "min": 0, "max": 1} for k in ("a", "b", "c", "d")]

    def build(self, layout):
        d = tempfile.mkdtemp()
        lp, art = os.path.join(d, "layout.conf"), os.path.join(d, "art.sh")
        open(lp, "w").write(layout)
        open(art, "w").write("#!/bin/sh\ncat >/dev/null\n")
        os.chmod(art, 0o755)
        comps, tabs, _ = shadow_skin.build(lp, self.PARAMS, d, art, lambda a, b: None)
        defs = {c["key"]: c["value"] for c in comps} if isinstance(comps, list) else comps
        return defs, tabs

    def tearDown(self):
        shadow_skin.apply_theme([])

    def page(self, defs, title):
        return [c["componentData"]["name"] for c in defs["T|" + title]["componentsData"]]

    def test_banks_limit_a_control_to_its_sub_pages(self):
        defs, _ = self.build('[tab T]\nknob cx=200 cy=300 r=30 key=a banks="ONE"\nknob cx=400 cy=300 r=30 key=b\n'
                             'frame x=600 y=200 w=200 h=200 title="X" banks="TWO"\n'
                             'qlinks "ONE" = a,b\nqlinks "TWO" = b\n')
        one, two = self.page(defs, "ONE"), self.page(defs, "TWO")
        self.assertEqual(sorted(one), ["Background", "a", "b"])
        self.assertEqual(sorted(two), ["Background", "Mode", "b"])   # the frame's own image, TWO only

    def test_banks_must_name_a_qlinks_page(self):
        with self.assertRaises(SystemExit):
            self.build('[tab T]\nknob cx=200 cy=300 r=30 key=a banks="NOPE"\nqlinks "ONE" = a\n')

    def knob_def(self, defs, prefix="shKnob"):
        return [v for k, v in defs.items() if k.startswith(prefix)][0]

    def test_knob_text_sizes_and_width(self):
        defs, _ = self.build("[tab T]\nknob cx=200 cy=300 r=30 key=a ns=0 vs=40 bw=90\n")
        kd = self.knob_def(defs)
        names = [c["componentData"]["name"] for c in kd["componentsData"]]
        self.assertNotIn("Name", names)
        value = [c for c in kd["componentsData"] if c["componentData"]["name"] == "Value"][0]
        self.assertEqual(value["componentData"]["data"]["textStyle"]["font"]["height"], 40.0)
        self.assertEqual(int(value["bounds"]["bounds"].split()[2]), 90)

    def test_side_knob_puts_the_value_beside_the_picture(self):
        defs, _ = self.build("[tab T]\nknob cx=300 cy=300 r=20 key=a lay=side bw=240 bh=60 vs=40\n")
        kd = self.knob_def(defs, "shKnobSide")
        names = [c["componentData"]["name"] for c in kd["componentsData"]]
        self.assertEqual(names, ["Focus", "Knob", "Value"])
        value = kd["componentsData"][2]
        self.assertEqual(value["bounds"]["bounds"].split(), ["54", "0", "182", "60"])

    def test_toggle_bw_and_no_name(self):
        defs, _ = self.build("[tab T]\ntoggle cx=300 cy=300 key=a bw=70\ntoggle cx=500 cy=300 key=b ns=0\n")
        tg = {k: v for k, v in defs.items() if k.startswith("shToggle")}
        self.assertEqual(len(tg), 2)
        nn = [v for k, v in tg.items() if "_ns0" in k][0]
        self.assertNotIn("Name", [c["componentData"]["name"] for c in nn["componentsData"]])
        narrow = [v for k, v in tg.items() if "_bw70" in k][0]
        self.assertEqual(narrow["componentsData"][0]["bounds"]["bounds"].split()[2], "70")

    def test_enum_v_honours_sh(self):
        w = {"kind": "enum_v", "options": ["A", "B"], "cx": 100, "cy": 100, "sh": 44}
        self.assertEqual({r[3] for r in shadow_skin.seg_rects(w)}, {44})

    def slider_texts(self, layout):
        defs, _ = self.build(layout)
        sd = [v for k, v in defs.items() if k.startswith("shSlider")][0]
        out = {}
        for c in sd["componentsData"]:
            if c["componentData"]["name"] in ("Name", "Value"):
                out[c["componentData"]["name"]] = (c["componentData"]["data"]["textStyle"]["font"]["height"],
                                                   int(c["bounds"]["bounds"].split()[2]))
        return out

    def test_plain_slider_text_unchanged(self):
        t = self.slider_texts("[tab T]\nslider_v cx=500 cy=350 w=40 h=200 key=a\n")
        self.assertEqual(t, {"Name": (17.0, 130), "Value": (22.0, 130)})

    def test_label_scale_alone_leaves_slider_text(self):
        t = self.slider_texts("label_scale=1.3\n[tab T]\nslider_v cx=500 cy=350 w=40 h=200 key=a\n")
        self.assertEqual(t, {"Name": (17.0, 130), "Value": (22.0, 130)})

    def test_scale_names_scales_slider_text(self):
        t = self.slider_texts("scale_names=1\nlabel_scale=1.3\n[tab T]\nslider_v cx=500 cy=350 w=40 h=200 key=a\n")
        self.assertAlmostEqual(t["Name"][0], 21.0 * 1.3)
        self.assertAlmostEqual(t["Value"][0], 22.0 * 1.3)
        self.assertEqual(t["Name"][1], round(130 * 1.3))

    def test_slider_ns_vs_override_under_scale_names(self):
        t = self.slider_texts("scale_names=1\n[tab T]\nslider_v cx=500 cy=350 w=40 h=200 key=a ns=30 vs=36\n")
        self.assertEqual((t["Name"][0], t["Value"][0]), (30.0, 36.0))

    def test_plain_knob_unchanged(self):
        defs, _ = self.build("[tab T]\nknob cx=200 cy=300 r=30 key=a\n")
        self.assertEqual([k for k in defs if k.startswith("shKnob")], ["shKnob30_ls%g" % shadow_skin.LABEL_SCALE])


class StockStrips(unittest.TestCase):
    """Slider and meter filmstrips as stock skins lay them out: frames of the widget's own size, numFrames = the count,
    the strip under MAX_STRIP px (docs/NOTES.md 2026-10-07)."""

    def test_short_widgets_keep_128_frames(self):
        self.assertEqual(shadow_skin.strip_frames(40), shadow_skin.FRAMES)

    def test_tall_widgets_get_fewer_frames(self):
        n = shadow_skin.strip_frames(200)
        self.assertEqual(n, 61)
        self.assertLessEqual(n * 200, shadow_skin.MAX_STRIP)

    def test_a_meter_keeps_its_own_frame_count(self):
        self.assertEqual(shadow_skin.strip_frames(86, 3), 3)

    def test_slider_bounds_are_its_own_size(self):
        b = BuildAttrs()
        defs, _ = b.build("[tab T]\nslider_v cx=500 cy=350 w=40 h=200 key=a\n")
        sd = [v for k, v in defs.items() if k.startswith("shSlider")][0]
        strip = [c for c in sd["componentsData"] if c["componentData"]["type"] == "Knob"][0]
        self.assertEqual(strip["componentData"]["data"]["numFrames"], 61)
        self.assertEqual(strip["bounds"]["bounds"].split()[2:], ["40", "200"])


class SkinCheck(unittest.TestCase):
    """tools/skin_check.py on a stub-built skin: overlapping touch boxes, boxes past the edge, stray Q-Links."""
    PARAMS = [{"key": k, "name": k.upper(), "min": 0, "max": 1} for k in "abcd"]

    def findings(self, layout):
        import json
        import skin_check
        d = tempfile.mkdtemp()
        lp, art = os.path.join(d, "layout.conf"), os.path.join(d, "art.sh")
        open(lp, "w").write(layout)
        open(art, "w").write("#!/bin/sh\ncat >/dev/null\n")
        os.chmod(art, 0o755)
        comps, tabs, qmap = shadow_skin.build(lp, self.PARAMS, d, art, lambda a, b: None)
        json.dump({"pageData": {"componentDefinitions": {"localComponentDefinitions": comps}, "tabs": tabs}},
                  open(os.path.join(d, "TUI.json"), "w"))
        json.dump({"Screen Mode Q-Links": {"map": qmap}}, open(os.path.join(d, "Q-Links.json"), "w"))
        return [f.split()[1] for f in skin_check.check(d)]

    def tearDown(self):
        shadow_skin.apply_theme([])

    def test_a_clean_page_has_no_findings(self):
        self.assertEqual(self.findings("[tab T]\nknob cx=200 cy=300 r=30 key=a\nknob cx=400 cy=300 r=30 key=b\n"), [])

    def test_each_problem_is_found(self):
        f = self.findings('[tab T]\nknob cx=200 cy=300 r=30 key=a\nknob cx=260 cy=300 r=30 key=b\n'
                          'knob cx=1260 cy=300 r=30 key=c\nknob cx=600 cy=300 r=30 key=d banks="ONE"\n'
                          'qlinks "ONE" = a,b,c,d\nqlinks "TWO" = a,b,c,d\n')
        self.assertEqual(sorted(f), ["EDGE", "EDGE", "QLINK", "TOUCH", "TOUCH"])

    def test_option_segments_are_complete(self):
        self.PARAMS = [{"key": "a", "name": "A", "options": ["X", "Y", "Z"]}]
        self.assertEqual(self.findings("[tab T]\nenum_h cx=400 cy=300 key=a\n"), [])

    def test_narrow_bw_clears_the_overlap(self):
        self.assertEqual(self.findings("[tab T]\nknob cx=200 cy=300 r=30 key=a bw=74\nknob cx=280 cy=300 r=30 key=b bw=74\n"), [])


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

    action = {"version": 2, "onAction": "Mouse Down", "handler": "Q-Link", "handleName": "Data",
              "additionalData": "", "handle remapping": {"version": 1, "map": []}}

    def definition(kids):
        return {"version": 4, "actions": [dict(action)], "backgroundData": bg, "ignoreMousePresses": False,
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

    def test_actions_are_version_1_without_handle_remapping(self):
        acts = self.pd["tabs"][0]["componentDefinition"]["actions"]
        self.assertEqual(acts, [{"version": 1, "onAction": "Mouse Down", "handler": "Q-Link", "handleName": "Data",
                                 "additionalData": ""}])

    def test_a_tab_pointing_at_a_missing_definition_is_an_error(self):
        t = _gen_like_tui()
        t["pageData"]["tabs"][0]["componentName"] = "nope"
        with self.assertRaises(SystemExit):
            shadow_skin.to_mpc2x(t)


class InlinedSvgs(unittest.TestCase):
    SVG = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'id="root" width="10" height="10" viewBox="0 0 10 10"><style>.cls-1{fill:url(#g)}</style>'
           '<defs><linearGradient id="g"><stop offset="0" stop-color="%s"/></linearGradient></defs>'
           '<rect class="cls-1" width="10" height="10"/><circle id="c" r="2" fill="url(\'#g\')"/>'
           '<use xlink:href="#c"/><use href="#c"/></svg>')

    def test_two_svgs_sharing_ids_and_classes_stay_apart(self):
        with tempfile.TemporaryDirectory() as d:
            art = html_art.Art()
            for i, colour in enumerate(("red", "blue")):
                path = os.path.join(d, "%d.svg" % i)
                open(path, "w").write(self.SVG % colour)
                art.images[path] = "img%d" % i
            defs = art.image_defs()
        ids = re.findall(r'\sid="([^"]+)"', defs)
        self.assertEqual(len(ids), len(set(ids)), ids)
        for iid, colour in (("img0", "red"), ("img1", "blue")):
            part = defs[defs.index('id="%s"' % iid):]
            part = part[:part.index("</svg>")]
            self.assertIn('id="%s-g"><stop offset="0" stop-color="%s"' % (iid, colour), part)
            self.assertIn(".%s-cls-1{fill:url(#%s-g)}" % (iid, iid), part)
            self.assertIn('class="%s-cls-1"' % iid, part)
            self.assertIn("url('#%s-g')" % iid, part)
            self.assertEqual(part.count('href="#%s-c"' % iid), 2)
            self.assertNotRegex(part, r'(url\(\s*[\'"]?#|href="#)(g|c)\b')


class HtmlArtBoxButton(unittest.TestCase):
    """A layout `button ... w= h=` line becomes the `boxbtn` draw op. html_art had no branch for it, so every
    art:html build with a sized button failed (found porting MPC DJ FX 2, 2026-10-27); these tests keep the
    emit, the draw and the device's geometry in step."""

    PARAMS = [{"key": "panic", "name": "PANIC", "min": 0, "max": 1}]
    LAYOUT = ('[tab T]\nbutton cx=640 cy=300 w=136 h=40 key=panic label="PANIC"\nqlinks "T" = panic\n')

    def tearDown(self):
        shadow_skin.apply_theme([])

    def ops(self, layout=LAYOUT):
        """Run shadow_skin against a capture stub, so the draw script it would pipe to the art tool is readable."""
        d = tempfile.mkdtemp()
        lp, cap, art = os.path.join(d, "layout.conf"), os.path.join(d, "ops.txt"), os.path.join(d, "art.sh")
        open(lp, "w").write(layout)
        open(art, "w").write("#!/bin/sh\ncat > '%s'\n" % cap)
        os.chmod(art, 0o755)
        shadow_skin.build(lp, self.PARAMS, d, art, lambda a, b: None)
        return open(cap).read().splitlines()

    def svg(self, op):
        art = html_art.Art()
        art.run(op)
        return "".join(art.ops)

    def test_sized_button_reaches_the_browser_renderer(self):
        box = [o for o in self.ops() if o.startswith("boxbtn|")]
        self.assertTrue(box, "a button with w= and h= must emit boxbtn")
        svg = self.svg(box[0])
        self.assertIn('class="button"', svg)
        self.assertIn('width="136"', svg)
        self.assertIn('height="40"', svg)
        self.assertIn('rx="8"', svg)          # h/8 = 5, clamped up to the device's minimum
        self.assertIn("PANIC", svg)

    def test_radius_follows_the_device_rule(self):
        # shadow_art.c: fill_rr(x, y, w, h, clamp(h / 8, 8, 18))
        self.assertIn('rx="8"', self.svg("boxbtn|10|10|400|40|aabbcc|PANIC|1"))      # 5 -> 8
        self.assertIn('rx="15"', self.svg("boxbtn|10|10|120|120|aabbcc|PLAY|1"))     # 15, in range
        self.assertIn('rx="18"', self.svg("boxbtn|10|10|200|200|aabbcc|PLAY|1"))     # 25 -> 18

    def test_label_the_device_drops_is_dropped_here_too(self):
        # dot_label() returns early above 16 characters, so nothing is drawn inside the box
        svg = self.svg("boxbtn|10|10|300|60|aabbcc|ABCDEFGHIJKLMNOPQ|1")
        self.assertIn('class="button"', svg)
        self.assertNotIn("ABCDEFGHIJKLMNOPQ", svg)

    def test_no_sheen_or_inset_on_a_sized_button(self):
        # the device fills one rounded rectangle; the sheen belongs to the fixed-size `button` op only
        svg = self.svg("boxbtn|10|10|136|40|aabbcc|PANIC|1")
        self.assertNotIn("button-sheen", svg)
        self.assertIn('<rect class="button-bg" x="10" y="10" width="136" height="40" rx="8"/>', svg)


if __name__ == "__main__":
    unittest.main()
