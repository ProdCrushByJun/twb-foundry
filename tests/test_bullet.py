"""Bullet graph (decisions/152, reference 'Target Practice'): a bar with its target line and zones at percents of the
target under it. Refusals of the spec, the XML forms, the counts per zone, the gate's checks with their mutations, the
golden round trip."""
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tbuilder import design, expected, gate, reflines
from tbuilder.build import build
from test_bar_labels import built, formats, repack, ws
from test_roundtrip import SPECS, canon, normalize, read_twbx

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "golden_bullet_2025_1"


def load():
    return json.loads((SPECS / "bullet.json").read_text(encoding="utf-8"))


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def lines(w):
    return w.findall("table/panes/pane/reference-line")


class Refused(unittest.TestCase):
    def refused(self, ref, why):
        spec = load()
        sheet(spec, "Regions")["reference"] = ref
        with self.assertRaisesRegex(ValueError, why):
            build(spec, ROOT / "out" / "bullet_refused.twbx", SPECS)

    def test_bands(self):
        plan = {"field": "Plan"}
        for bands in ([95, 80], [80, 80], [50, 100], [0, 50], [20, 40, 60, 80]):
            self.refused({"type": "target", "measure": plan, "bands": bands},  # the schema or the generator
                         "rising, each above 0 and below 100|is not valid")
        self.refused({"type": "avg", "bands": [50]}, r"'avg' does not take \['bands'\]")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(load(), ROOT / "out" / "bullet_test.twbx")

    def test_zones_under_the_target_line(self):
        w = ws(self.root, "Managers")
        zones, line = lines(w)
        self.assertEqual((zones.get("percentage-bands"), zones.get("scope"), zones.get("fill-above"),
                          zones.get("fill-below"), zones.get("label-type")), ("true", "per-cell", "true", "true", "none"))
        self.assertEqual([v.get("percentage") for v in zones.iterfind("reference-line-value")], ["80", "95"])
        self.assertEqual((line.get("formula"), line.get("scope")), ("total", "per-cell"))
        self.assertEqual(zones.get("value-column"), line.get("value-column"))
        self.assertLess(int(zones.get("z-order")), int(line.get("z-order")))
        band = {f.get("attr"): f.get("value") for f in formats(w, "refband") if f.get("id") == zones.get("id")}
        self.assertEqual(band.get("reverse-palette"), "false")
        self.assertNotIn(zones.get("id"), {f.get("id") for f in formats(w, "refline")})

    def test_thin_bar_white_rows(self):
        for name in ("Managers", "Regions"):
            w = ws(self.root, name)
            size = w.find("table/panes/pane/style/style-rule[@element='mark']/format[@attr='size']")
            self.assertEqual(size.get("value"), reflines.BULLET_BAR_SIZE)
            div = {f.get("attr"): f.get("value") for f in formats(w, "table-div") if f.get("scope") == "rows"}
            self.assertEqual((div["line-visibility"], div["stroke-size"], div["stroke-color"]),
                             ("on", reflines.BULLET_GAP_PX, design.COLOR["card_bg"]))

    def test_bars_on_target_in_the_accent(self):
        """Not the muted gray of 095: it would be lost on the gray zones."""
        flag = ws(self.root, "Managers").find("table/panes/pane/encodings/color").get("column").split("].[")[1]
        enc = next(e for e in self.root.iter("encoding") if e.get("attr") == "color" and e.get("field") == f"[{flag}")
        self.assertEqual({m.find("bucket").text: m.get("to") for m in enc.iter("map")},
                         {"true": design.COLOR["bad"], "false": design.COLOR["accent"]})

    def test_value_column_formatted(self):
        """The header width is measured for whole numbers: Desktop draws them so ('36,570', not '36,57..')."""
        w = ws(self.root, "Regions")
        fmt = [f for f in formats(w, "label") if f.get("attr") == "text-format" and "sum:Sales:ok" in f.get("field")]
        self.assertEqual([f.get("value") for f in fmt], ["n#,##0;-#,##0"])


class Numbers(unittest.TestCase):
    def test_counts_per_zone(self):
        spec = load()
        got = expected.compute(spec, expected.data_path(spec, SPECS))
        self.assertEqual(got["Managers · Reference"], {"below target": 4, "below 80% of target": 0,
                                                       "below 95% of target": 2})
        self.assertEqual(got["Regions · Reference"]["below target"], 3)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = build(load(), ROOT / "out" / "bullet_gate.twbx", SPECS)

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def caught(self, fn, text):
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "reflines"]
        self.assertEqual(len(got), 1, got)
        self.assertIn(text, got[0])

    def test_percents_not_rising(self):
        def fn(root):
            vals = lines(ws(root, "Managers"))[0].findall("reference-line-value")
            vals[0].set("percentage", "120")
        self.caught(fn, "are not rising between 0 and 100")

    def test_zones_without_target_line(self):
        def fn(root):
            pane = ws(root, "Managers").find("table/panes/pane")
            line = lines(ws(root, "Managers"))[1]
            for f in ws(root, "Managers").findall("table/style/style-rule[@element='refline']/format"):
                if f.get("id") == line.get("id"):
                    f.getparent().remove(f)
            pane.remove(line)
        self.caught(fn, "have no target line per bar")


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        out = build(load(), ROOT / "out" / "bullet_roundtrip.twbx", SPECS)
        golden = ET.parse(GOLDEN.with_suffix(".twb")).getroot()
        self.assertEqual(canon(normalize(golden)), canon(normalize(read_twbx(out)[0])))

    def test_expected_equals_golden_json(self):
        spec = load()
        want = json.loads((ROOT / "golden" / "expected" / f"{GOLDEN.name}.json").read_text(encoding="utf-8"))
        want = {k: v for k, v in want.items() if not k.startswith("_")}
        self.assertEqual(expected.compute(spec, expected.data_path(spec, SPECS)), want)


if __name__ == "__main__":
    unittest.main()
