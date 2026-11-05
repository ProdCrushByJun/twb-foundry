"""KPI v2 sparkline points (decisions/059): max / min / last dots as a second layer on the line's synchronized axis."""
import copy
import csv
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import gate, kpi2
from tbuilder import spec as spec_mod
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from tbuilder.design_lint import lint
from tbuilder.expected import compute
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS, canon, normalize, read_twbx

SPEC = json.loads((SPECS / "kpi_spark_points.json").read_text(encoding="utf-8"))
DATA = SPECS / SPEC["datasource"]["path"]
GOLDEN = ROOT / "golden" / "golden_kpi_spark_points_2025_1.twbx"
SALES = "Monthly · Sales · History"


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec=SPEC, name="spark_points_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def calc(root, caption):
    return next(c for c in root.find("datasources").iter("column") if c.get("caption") == caption)


def palette(root, caption):
    """{bucket: color} of the palette map on a calc."""
    col = calc(root, caption).get("name")[1:-1]
    enc = next(e for e in root.iter("encoding") if e.get("field") == f"[usr:{col}:nk]")
    return {m.findtext("bucket"): m.get("to") for m in enc.findall("map")}


class Numbers(unittest.TestCase):
    def test_marked_periods(self):
        """pandas over data/sample/sales_2y.csv: the months and values each sparkline marks."""
        got = compute(SPEC, DATA)
        self.assertEqual(got[f"{SALES} · Point Marks"], {
            "2024-07": {"point": "Min", "value": 5612.36}, "2025-03": {"point": "Max", "value": 17285.09},
            "2025-12": {"point": "Last", "value": 15462.12}})
        self.assertEqual(got["Monthly · Profit · History · Point Marks"], {
            "2024-06": {"point": "Min", "value": 347.44}, "2024-10": {"point": "Max", "value": 1903.65},
            "2025-12": {"point": "Last", "value": 825.38}})
        self.assertEqual(got["Monthly · Units · History · Point Marks"], {
            "2024-07": {"point": "Min", "value": 73.0}, "2024-11": {"point": "Max", "value": 139.0},
            "2025-12": {"point": "Last", "value": 104.0}})
        self.assertEqual(got["Latest · Units · History · Point Marks"], {
            "2024-07": {"point": "Min", "value": 73.0}, "2025-12": {"point": "Last", "value": 104.0}})

    def test_first_listed_kind_wins_and_ties_mark_every_period(self):
        card = {"history": "line", "history_points": ["last", "max"]}
        marks = {"a": 1, "b": 5, "c": 5, "d": 5}
        self.assertEqual(kpi2.point_marks(card, marks), {"b": {"point": "Max", "value": 5},
                                                         "c": {"point": "Max", "value": 5},
                                                         "d": {"point": "Last", "value": 5}})

    def test_colors_follow_good(self):
        self.assertEqual([kpi2.point_color(k, {}) for k in ("max", "min", "last")], ["good", "bad", "accent"])
        self.assertEqual([kpi2.point_color(k, {"good": "down"}) for k in ("max", "min", "last")],
                         ["bad", "good", "accent"])


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_calcs(self):
        v = calc(self.root, f"{SALES} · Point Value").find("calculation").get("formula")
        self.assertEqual(v, "IF SUM([Sales]) = WINDOW_MAX(SUM([Sales])) OR SUM([Sales]) = WINDOW_MIN(SUM([Sales])) "
                            "OR LAST() = 0 THEN SUM([Sales]) END")
        k = calc(self.root, "Latest · Units · History · Point").find("calculation").get("formula")
        self.assertEqual(k, 'IF LAST() = 0 THEN "Last" ELSEIF SUM([Quantity]) = WINDOW_MIN(SUM([Quantity])) '
                            'THEN "Min" END')
        self.assertEqual(calc(self.root, f"{SALES} · Point Value").get("datatype"), "real")
        self.assertEqual(calc(self.root, "Monthly · Units · History · Point Value").get("datatype"), "integer")
        captions = {c.get("caption") for c in self.root.iter("column")}
        self.assertNotIn(f"{SALES} · Label", captions)  # the labels are on the points now

    def test_two_layers_on_one_synchronized_axis(self):
        t = ws(self.root, SALES).find("table")
        fold = t.find("style/style-rule[@element='axis']/encoding[@fold='true']")
        self.assertEqual(fold.get("synchronized"), "true")
        pv = calc(self.root, f"{SALES} · Point Value").get("name")[1:-1]
        self.assertTrue(fold.get("field").endswith(f"[usr:{pv}:qk]"))
        self.assertRegex(t.findtext("rows"), r"^\(\[.+\]\.\[sum:Sales:qk\] \+ \[.+\]\.\[usr:" + pv + r":qk\]\)$")
        self.assertTrue(t.findtext("cols").endswith("[tmn:Order Date:qk]"))
        panes = t.findall("panes/pane")
        self.assertEqual([p.find("mark").get("class") for p in panes], ["Line", "Line", "Circle"])
        self.assertIsNotNone(panes[0].find("reference-line"))  # the average in the default pane (ER)
        line, dots = panes[1:]
        self.assertEqual(line.find("style/style-rule/format[@attr='mark-color']").get("value"), COLOR["muted"])
        self.assertTrue(dots.find("encodings/color").get("column").endswith(":nk]"))
        self.assertIsNotNone(dots.find("encodings/text"))
        hidden = {f.get("field").rsplit(".", 1)[1] for f in t.iter("format") if f.get("attr") == "display"}
        self.assertEqual(hidden, {"[sum:Sales:qk]", f"[usr:{pv}:qk]", "[tmn:Order Date:qk]"})
        self.assertEqual(t.find("style/style-rule[@element='table']/format").get("attr"), "show-null-value-warning")

    def test_points_computed_along_the_date(self):
        t = ws(self.root, SALES).find("table")
        for cap in (f"{SALES} · Point Value", f"{SALES} · Point"):
            name = calc(self.root, cap).get("name")[1:-1]
            ci = next(c for c in t.iter("column-instance") if c.get("column") == f"[{name}]")
            self.assertTrue(ci.find("table-calc").get("ordering-field").endswith("[tmn:Order Date:qk]"))
        kind = calc(self.root, f"{SALES} · Point").get("name")[1:-1]
        ds_ci = next(c for c in self.root.find("datasources").iter("column-instance")
                     if c.get("name") == f"[usr:{kind}:nk]")
        self.assertEqual(ds_ci.find("table-calc").get("ordering-type"), "Field")

    def test_palettes(self):
        null = {"%null%": COLOR["mark_muted"]}  # Desktop adds it on save (in its orange)
        self.assertEqual(palette(self.root, f"{SALES} · Point"),
                         {'"Max"': COLOR["good"], '"Min"': COLOR["bad"], '"Last"': COLOR["accent"], **null})
        self.assertEqual(palette(self.root, "Monthly · Units · History · Point"),  # good: down
                         {'"Max"': COLOR["bad"], '"Min"': COLOR["good"], '"Last"': COLOR["accent"], **null})
        self.assertEqual(palette(self.root, "Latest · Units · History · Point"),
                         {'"Min"': COLOR["good"], '"Last"': COLOR["accent"], **null})

    def test_dots_only(self):
        dots = ws(self.root, "Latest · Units · History").findall("table/panes/pane")[2]
        self.assertIsNone(dots.find("encodings/text"))
        self.assertEqual(dots.find("style/style-rule/format[@attr='mark-labels-show']").get("value"), "false")

    def test_sparkline_without_points_unchanged(self):
        """kpi_v2's sparkline (no history_points) stays one layer with its max / last label calc."""
        spec = json.loads((SPECS / "kpi_v2.json").read_text(encoding="utf-8"))
        root = built(spec, "spark_points_kpi_v2")
        t = ws(root, "Monthly · Sales · History").find("table")
        self.assertEqual(len(t.findall("panes/pane")), 1)
        self.assertIsNone(t.find(".//encoding[@fold='true']"))
        self.assertIn("Monthly · Sales · History · Label", {c.get("caption") for c in root.iter("column")})


class Options(unittest.TestCase):
    def test_refused(self):
        cases = [
            (lambda s: sheet(s, "Monthly").pop("history"), "set history 'line'"),
            (lambda s: sheet(s, "Latest").pop("history_points"), "labels the points"),
        ]
        for fn, text in cases:
            with self.subTest(text):
                with self.assertRaisesRegex(ValueError, text):
                    built(mutate(fn), "spark_points_refused")

    def test_schema(self):
        for bad in (["max", "max"], ["first"], []):
            with self.subTest(bad):
                with self.assertRaises(Exception):
                    spec_mod.validate(mutate(lambda s: sheet(s, "Monthly").update(history_points=bad)))
        spec_mod.validate(SPEC)


class Lint(unittest.TestCase):
    def test_clean(self):
        self.assertEqual([f for f in lint(SPEC, SPECS) if f.rule == "K3"], [])

    def test_ties_mark_more_than_three(self):
        d = Path(tempfile.mkdtemp())
        with open(d / "tie.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Order Date", "Sales"])
            for day, v in (("2025-01-05", 10), ("2025-02-05", 30), ("2025-03-05", 30), ("2025-04-05", 20)):
                w.writerow([day, v])
        spec = {"version": 1, "datasource": {"type": "csv", "path": "tie.csv"},
                "sheets": [{"name": "Cards", "type": "kpi", "style": "cards", "date": {"field": "Order Date"},
                            "history": "line", "history_points": ["max", "min", "last"],
                            "measures": [{"field": "Sales"}]}],
                "dashboard": {"name": "D", "title": "**T**", "subtitle": "s", "grid": [["Cards"]]}}
        k3 = [f for f in lint(spec, d) if f.rule == "K3"]
        self.assertEqual(len(k3), 1, k3)
        self.assertIn("4 periods", k3[0].text)


class GateCatchesPoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "kpi_spark_points.json", OUT / "spark_points_gate.twbx")

    def assertCaught(self, mutation, check, text):
        issues = gate.run(repack(mutation, source=self.src))
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def table(r):
        return next(w for w in r.iter("worksheet") if w.get("name") == SALES).find("table")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_unsynchronized(self):
        def m(r):
            del self.table(r).find(".//encoding[@fold='true']").attrib["synchronized"]
        self.assertCaught(m, "kpi", "not on a synchronized axis")

    def test_points_along_another_field(self):
        def m(r):
            t = self.table(r)
            fold = t.find(".//encoding[@fold='true']").get("field")
            for ci in t.iter("column-instance"):
                if fold.endswith(ci.get("name")):
                    ci.find("table-calc").set("ordering-field", fold.rsplit(".", 1)[0] + ".[none:Region:nk]")
        self.assertCaught(m, "kpi", "not computed along the date")

    def test_points_without_compute_using(self):
        def m(r):
            t = self.table(r)
            fold = t.find(".//encoding[@fold='true']").get("field")
            for ci in t.iter("column-instance"):
                if fold.endswith(ci.get("name")):
                    ci.remove(ci.find("table-calc"))
        self.assertCaught(m, "kpi", "no compute-using")
        self.assertCaught(m, "tablecalc", "has no compute-using")

    def test_kind_without_palette(self):
        def m(r):
            inst = self.table(r).findall("panes/pane")[2].find("encodings/color").get("column").split("].", 1)[1]
            e = next(e for e in r.iter("encoding") if e.get("field") == inst and e.get("attr") == "color")
            e.getparent().remove(e)
        self.assertCaught(m, "kpi", "has no palette map")

    def test_kind_instance_without_compute_using(self):
        def m(r):
            inst = self.table(r).findall("panes/pane")[2].find("encodings/color").get("column").split("].", 1)[1]
            ci = next(c for c in r.find("datasources").iter("column-instance") if c.get("name") == inst)
            ci.remove(ci.find("table-calc"))
        self.assertCaught(m, "kpi", "no column-instance with its compute-using")


@unittest.skipUnless(GOLDEN.is_file(), "golden_kpi_spark_points not snapped yet")
class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """The workbook Desktop 2025.1 re-saved (decisions/054) = the generator's output."""
        import difflib
        out = build_file(SPECS / "kpi_spark_points.json", OUT / "roundtrip_spark_points.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(GOLDEN)
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))


if __name__ == "__main__":
    unittest.main()
