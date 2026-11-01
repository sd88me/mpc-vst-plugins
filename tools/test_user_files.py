import json
import os
import unittest

from user_files import user_files_problems

HERE = os.path.dirname(os.path.abspath(__file__))
GOOD = [{"path": "osirus/roms", "label": "ROMs", "rules": [
    {"label": "Virus ROM", "ext": [".bin"], "size": 524288, "signature": "(C)ACCESS [", "versions": [{"prefix": "vc", "label": "Virus C"}]},
    {"label": "OS update", "ext": [".mid"], "size_min": 1, "size_max": 9, "header": "MThd", "unverified": True, "note": "the plugin checks it"}]}]


class UserFiles(unittest.TestCase):
    def test_a_good_spec_has_no_problems(self):
        self.assertEqual(user_files_problems(GOOD, ["osirus/roms"]), [])
        self.assertEqual(user_files_problems(GOOD, ["osirus"]), [])   # inside a kept folder is fine
        self.assertEqual(user_files_problems([], []), [])

    def test_a_folder_must_be_kept_on_upgrade(self):
        self.assertTrue(any("user_data" in p for p in user_files_problems(GOOD, ["banks"])))

    def test_bad_specs_are_named(self):
        def bad(mutate, word):
            g = json.loads(json.dumps(GOOD))
            mutate(g[0])
            probs = user_files_problems(g, ["osirus/roms"])
            self.assertTrue(any(word in p for p in probs), (word, probs))
        bad(lambda g: g.update(path="../etc"), "bad folder path")
        bad(lambda g: g.update(path="a b"), "bad folder path")
        bad(lambda g: g.update(rules=[]), "at least one rule")
        bad(lambda g: g.update(color="red"), "unknown field")
        bad(lambda g: g["rules"][0].update(ext=["bin"]), "ext")
        bad(lambda g: g["rules"][0].update(size=-5), "size")
        bad(lambda g: g["rules"][0].pop("signature"), "signature")
        bad(lambda g: g["rules"][1].pop("note"), "note")
        bad(lambda g: g["rules"][1].update(size_min=10), "size_min")
        self.assertTrue(user_files_problems({"x": 1}, []))
        bad(lambda g: g["rules"][0].update(header_hex="c0dz"), "header_hex")
        bad(lambda g: g["rules"][1].update(header_hex="c0de"), "not both")
        bad(lambda g: g["rules"][0].update(save_as="../rom.bin"), "save_as")
        bad(lambda g: g["rules"][0].update(save_as="rom.txt"), "save_as")
        bad(lambda g: g["rules"][0].update(names=[]), "non-empty")
        bad(lambda g: g["rules"][0].update(names=["a/b.bin"]), "names")
        bad(lambda g: g["rules"][0].update(name_contains=""), "name_contains")

    def test_name_rules_and_binary_headers(self):
        g = [{"path": "roms", "label": "ROMs", "rules": [
            {"label": "Program ROM", "ext": [".bin"], "size": 32768, "names": ["jv880_rom1.bin"], "save_as": "jv880_rom1.bin"},
            {"label": "Card", "ext": [".bin"], "size": 8388608, "name_contains": "SR-JV80"},
            {"label": "XT ROM", "ext": [".bin"], "size": 262144, "header_hex": "C0DE"}]}]
        self.assertEqual(user_files_problems(g, ["roms"]), [])


if __name__ == "__main__":
    unittest.main()
