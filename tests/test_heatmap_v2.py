"""Heatmap v2 (decisions/041): the color scale, marginal totals, refusals, lint, gate mutations."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from statistics import mean

from tbuilder import expected, gate, heatmap
from tbuilder.build import build, build_file
from tbuilder.design import COLOR, HEATMAP_HEADER_PX, row_header_px
from tbuilder.design_lint import lint
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "heatmap_v2.json"
CSV = ROOT / "data" / "sample" / "sales_2y.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))
SEASON, CHANGE, PROFIT = "Seasonality", "Change", "Profit"
ROW_TOTALS, COL_TOTALS = f"{SEASON} · Row Totals", f"{SEASON} · Column Totals"
WIDTH, HEIGHT = 1400, 960


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name)


def margins(z):
    st = {f.get("attr"): int(f.get("value")) for f in z.findall("zone-style/format") if "margin" in f.get("attr")}
    return {s: st.get(f"margin-{s}", st.get("margin")) for s in ("top", "right", "bottom", "left")}


def fmt(root, sheet_name, element, attr, field_part):
    """The value of a worksheet style format (by element, attr and a part of its field), or None."""
    for f in ws(root, sheet_name).findall(f"table/style/style-rule[@element='{element}']/format[@attr='{attr}']"):
        if field_part in (f.get("field") or ""):
            return f.get("value")
    return None


class Scale(unittest.TestCase):
    def test_sequential_from_light_grey_to_the_accent(self):
        kind, colors = heatmap.palette({"scale": "sequential"})
        self.assertEqual(kind, "ordered-sequential")
        self.assertEqual((len(colors), colors[0], colors[-1]), (11, COLOR["scale_low"], COLOR["accent"]))

    def test_diverging_bad_grey_good_and_good_down_swaps(self):
        kind, colors = heatmap.palette({"scale": "diverging", "center": 0})
        self.assertEqual(kind, "ordered-diverging")
        self.assertEqual((len(colors), colors[0], colors[6], colors[-1]),
                         (13, COLOR["bad"], COLOR["scale_mid"], COLOR["good"]))
        _, down = heatmap.palette({"scale": "diverging", "center": 0, "good": "down"})
        self.assertEqual((down[0], down[-1]), (COLOR["good"], COLOR["bad"]))


class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "heatmap_v2_test.twbx")
        cls.root = twb(cls.path)

    def enc(self, name):
        return ws(self.root, name).find("table/style/style-rule[@element='mark']/encoding[@attr='color']")

    def test_sequential_scale_on_the_measure(self):
        e = self.enc(SEASON)
        self.assertEqual(e.get("type"), "custom-interpolated")
        self.assertTrue(e.get("field").endswith("[sum:Sales:qk]"))
        self.assertEqual(e.find("color-palette").get("type"), "ordered-sequential")
        self.assertNotIn("center", e.attrib)

    def test_diverging_scale_has_its_center(self):
        e = self.enc(CHANGE)
        self.assertEqual((e.get("center"), e.find("color-palette").get("type")), ("0.0", "ordered-diverging"))
        self.assertEqual(list(e.attrib)[:3], ["attr", "center", "field"])  # Desktop's attribute order

    def test_bar_colored_by_its_measure_in_steps(self):
        e = self.enc(PROFIT)
        self.assertEqual(e.get("num-steps"), "4")
        colors = [c.get("column") for c in ws(self.root, PROFIT).findall("table/panes/pane/encodings/color")]
        self.assertEqual(colors, [e.get("field")])

    def test_margins_are_bar_sheets_of_the_same_measure(self):
        for name, shelf in ((ROW_TOTALS, "cols"), (COL_TOTALS, "rows")):
            self.assertTrue(ws(self.root, name).find(f"table/{shelf}").text.endswith("[sum:Sales:qk]"))
            self.assertIsNotNone(ws(self.root, name).find("table/panes/pane/reference-line[@formula='average']"))
            self.assertEqual(fmt(self.root, name, "axis", "display", "[sum:Sales:qk]"), "false")

    def test_rows_and_columns_have_the_same_sizes(self):
        self.assertEqual(fmt(self.root, SEASON, "cell", "height", "Calculation_"),
                         fmt(self.root, ROW_TOTALS, "cell", "height", "Calculation_"))
        self.assertEqual(fmt(self.root, SEASON, "cell", "width", "[none:Region:nk]"),
                         fmt(self.root, COL_TOTALS, "cell", "width", "[none:Region:nk]"))
        self.assertEqual(fmt(self.root, ROW_TOTALS, "label", "display", "Calculation_"), "false")  # month names
        self.assertEqual(fmt(self.root, SEASON, "label", "display", "[none:Region:nk]"), "false")  # on the margin

    def test_zones_line_up_with_the_cells(self):
        heat, right, top = (zone(self.root, n) for n in (SEASON, ROW_TOTALS, COL_TOTALS))
        hm, rm, tm = margins(heat), margins(right), margins(top)
        px = lambda z, k, size: int(z.get(k)) * size / 100000  # noqa: E731
        # rows: the first bar on the first row of cells (the heatmap's column header is hidden)
        self.assertAlmostEqual(px(heat, "y", HEIGHT) + hm["top"], px(right, "y", HEIGHT) + rm["top"], delta=1)
        self.assertEqual(int(right.get("x")), int(heat.get("x")) + int(heat.get("w")))
        # columns: the first bar over the first column of cells, after the row headers
        row_w = int(fmt(self.root, SEASON, "header", "width", "Calculation_"))  # by the text metric (decisions/066)
        self.assertGreaterEqual(row_w, row_header_px(len("01 Jan")))
        self.assertAlmostEqual(px(heat, "x", WIDTH) + hm["left"] + row_w, px(top, "x", WIDTH) + tm["left"], delta=1)
        cells = 4 * int(fmt(self.root, SEASON, "cell", "width", "[none:Region:nk]"))
        self.assertGreaterEqual(px(top, "w", WIDTH) - tm["left"] - tm["right"], cells - 1)

    def test_gaps_are_empty_zones(self):
        heat = zone(self.root, SEASON)
        block = [z for z in self.root.iter("zone") if z.get("type-v2") == "empty"
                 and int(z.get("y")) < int(heat.get("y")) and int(z.get("x")) in
                 (int(heat.get("x")), int(heat.get("x")) + int(heat.get("w")))]
        self.assertEqual(len(block), 2)  # left of the column totals, the corner over the row totals

    def test_rows_only_keeps_the_column_header_and_offsets_the_bars(self):
        s = spec()
        sheet(s, SEASON)["margins"] = {"rows": "bar"}
        root = twb(build(s, OUT / "heatmap_v2_rows.twbx", SPEC.parent))
        self.assertEqual(fmt(root, SEASON, "header", "height", "[none:Region:nk]"), str(HEATMAP_HEADER_PX))
        self.assertIsNone(fmt(root, SEASON, "label", "display", "[none:Region:nk]"))
        heat, right = zone(root, SEASON), zone(root, ROW_TOTALS)
        hm, rm = margins(heat), margins(right)
        y = lambda z, m: int(z.get("y")) * HEIGHT / 100000 + m["top"]  # noqa: E731
        self.assertAlmostEqual(y(heat, hm) + HEATMAP_HEADER_PX, y(right, rm), delta=1)
        self.assertNotIn(COL_TOTALS, {w.get("name") for w in root.iter("worksheet")})


class Expected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = expected.compute(spec(), CSV)

    def test_margin_totals_are_the_measure_over_each_row(self):
        by_region = defaultdict(float)
        for r in ROWS:
            by_region[r["Region"]] += float(r["Sales"])
        for k, v in by_region.items():
            self.assertAlmostEqual(self.exp[COL_TOTALS][k], v, places=6)
        self.assertAlmostEqual(self.exp[f"{COL_TOTALS} · Reference"]["Average"], mean(by_region.values()), places=6)

    def test_avg_totals_are_not_the_cells_averaged(self):
        s = spec()
        sheet(s, SEASON)["measure"] = {"field": "Profit", "agg": "avg"}
        exp = expected.compute(s, CSV)
        east = [float(r["Profit"]) for r in ROWS if r["Region"] == "East"]
        self.assertAlmostEqual(exp[COL_TOTALS]["East"], mean(east), places=6)
        cells = [v for k, v in exp[SEASON].items() if k.endswith("| East")]
        self.assertNotAlmostEqual(exp[COL_TOTALS]["East"], mean(cells), places=3)

    def test_change_has_both_signs_around_its_center(self):
        values = list(self.exp[CHANGE].values())
        self.assertLess(min(values), 0)
        self.assertGreater(max(values), 0)


class Refusals(unittest.TestCase):
    def assertRefused(self, edit, text):
        s = spec()
        edit(s)
        with self.assertRaises(ValueError) as cm:
            build(s, OUT / "heatmap_v2_refused.twbx", SPEC.parent)
        self.assertIn(text, str(cm.exception))

    def test_diverging_without_center(self):
        self.assertRefused(lambda s: sheet(s, CHANGE)["color"].pop("center"), "needs 'center'")

    def test_palette_of_the_other_scale(self):
        self.assertRefused(lambda s: sheet(s, SEASON)["color"].update(palette="good_bad"), "takes palette 'accent'")

    def test_center_on_a_sequential_scale(self):
        self.assertRefused(lambda s: sheet(s, SEASON)["color"].update(center=0), "belong to a diverging scale")

    def test_min_not_below_max(self):
        self.assertRefused(lambda s: sheet(s, SEASON)["color"].update(min=5, max=5), "is not below max")

    def test_center_outside_min_max(self):
        self.assertRefused(lambda s: sheet(s, CHANGE)["color"].update(min=0.1, max=0.5), "outside min..max")

    def test_margins_of_a_table_calc(self):
        self.assertRefused(lambda s: sheet(s, SEASON)["measure"].update(table_calc={"type": "running_total"}),
                           "marginal totals of a table calculation")

    def test_range_past_the_data_fails_the_gate(self):
        self.assertRefused(lambda s: sheet(s, CHANGE)["color"].update(min=-5), "color scale min -5")


class Lint(unittest.TestCase):
    def found(self, s):
        return {(f.rule, f.level) for f in lint(s, SPEC.parent)}

    def test_clean(self):
        self.assertFalse({r for r, _ in self.found(spec())} & {"C10", "C11"})

    def test_heatmap_without_a_scale_warns(self):
        s = spec()
        sheet(s, CHANGE).pop("color")
        self.assertIn(("C10", "warn"), self.found(s))

    def test_diverging_without_center_is_an_error(self):
        s = spec()
        sheet(s, CHANGE)["color"].pop("center")
        self.assertIn(("C11", "error"), self.found(s))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "heatmap_v2_gate.twbx")
        cls.exp = expected.compute(spec(), CSV)

    def enc(self, r, name):
        return ws(r, name).find("table/style/style-rule[@element='mark']/encoding[@attr='color']")

    def assertCaught(self, fn, text, exp=None):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path), expected=exp)]
        self.assertTrue(any(i.startswith("[colors]") and text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path, expected=self.exp), [])

    def test_scale_of_a_field_not_on_color(self):
        def f(r):
            enc = ws(r, SEASON).find("table/panes/pane/encodings")
            enc.remove(enc.find("color"))
        self.assertCaught(f, "which is not on Color")

    def test_diverging_without_center(self):
        self.assertCaught(lambda r: self.enc(r, CHANGE).attrib.pop("center"), "without a center")

    def test_center_outside_the_range(self):
        self.assertCaught(lambda r: self.enc(r, CHANGE).attrib.update({"min": "0.1", "max": "0.5"}),
                          "outside its range")

    def test_range_past_the_data(self):
        self.assertCaught(lambda r: self.enc(r, SEASON).set("max", "100000.0"), "color scale max 100000",
                          self.exp)

    def test_center_outside_the_data(self):
        self.assertCaught(lambda r: self.enc(r, CHANGE).set("center", "2.0"), "color scale center 2", self.exp)

    def test_bad_color(self):
        self.assertCaught(lambda r: self.enc(r, SEASON).find("color-palette/color").__setattr__("text", "blue"),
                          "#rrggbb")


if __name__ == "__main__":
    unittest.main()
