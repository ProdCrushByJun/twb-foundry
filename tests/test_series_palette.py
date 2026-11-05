"""Item 130: the series palette of the page (fields.<dimension>.color) reaches the .twb for every chart with a color
dimension: clustered and horizontal bar, bar along a date, multi-series line and area (decisions/130)."""
import copy
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASE = ROOT / "acceptance" / "bi_export"
SPEC = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
PAL = {"2024": "#118DFF", "2025": "#12239E"}
WANT = {k: v.lower() for k, v in PAL.items()}


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def maps(root, caption):
    """The palette map of the field with this caption (a calc is referenced by its internal Calculation_ name)."""
    column = next((c.get("name")[1:-1] for c in root.iter("column") if c.get("caption") == caption), caption)
    return {m.findtext("bucket").strip('"'): m.get("to").lower() for r in root.iter("style-rule")
            if r.get("element") == "mark" for e in r.findall("encoding")
            if e.get("type") == "palette" and e.get("field", "").endswith(f"[none:{column}:nk]")
            for m in e.findall("map")}


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def variant(name, edit, palette=True):
    spec = copy.deepcopy(SPEC)
    spec["fields"] = {"Year": {"color": PAL}} if palette else {}
    edit(spec)
    path = OUT / f"series_palette_{name}.twbx"
    build(spec, path, CASE)
    return twb(path)


class SeriesPalette(unittest.TestCase):
    def test_clustered_bar(self):
        self.assertEqual(maps(variant("bar", lambda s: None), "Year"), WANT)

    def test_without_fields_color_tableau_palette(self):
        self.assertEqual(maps(variant("bar_default", lambda s: None, palette=False), "Year"), {})

    def test_horizontal_bar(self):
        def edit(s):
            sheet(s, "By Carrier")["orientation"] = "horizontal"
        self.assertEqual(maps(variant("hbar", edit), "Year"), WANT)

    def test_bar_along_a_date(self):
        def edit(s):
            b = sheet(s, "By Carrier")
            b["dimension"], b["date_level"] = "Ship Date", "quarter"
            b.pop("sort", None)
        self.assertEqual(maps(variant("datebar", edit), "Year"), WANT)

    def test_multi_series_line(self):
        def edit(s):
            sheet(s, "By Month")["color"] = "Year"
        self.assertEqual(maps(variant("line", edit), "Year"), WANT)

    def test_multi_series_area(self):
        def edit(s):
            b = sheet(s, "By Month")
            b["type"], b["color"] = "area", "Year"
        self.assertEqual(maps(variant("area", edit), "Year"), WANT)

    def test_color_leaves_out_a_value(self):
        spec = copy.deepcopy(SPEC)
        spec["fields"] = {"Year": {"color": {"2024": "#118DFF"}}}
        with self.assertRaisesRegex(ValueError, "color leaves out"):
            build(spec, OUT / "series_palette_refused.twbx", CASE)

    def test_color_of_an_aggregate_calc_refused(self):
        spec = copy.deepcopy(SPEC)
        spec["fields"] = {"On-time Rate": {"color": {"x": "#118DFF"}}}
        with self.assertRaisesRegex(ValueError, "row-level text"):
            build(spec, OUT / "series_palette_refused.twbx", CASE)


if __name__ == "__main__":
    unittest.main()
