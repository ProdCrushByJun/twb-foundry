"""Rows of a bar list in its zone (decisions/166): a Top N after the filters counts N rows, a bar along a date counts
its periods, a row keeps its header labels apart; lint D13."""
import json
import unittest

from tbuilder import design_lint, fit, gate

from test_fit import ROOT, built, repack, set_zoom, zooms

SPECS = ROOT / "specs"


def spec(name):
    return json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))


def builder(s):
    from tbuilder.build import Builder
    return Builder(s, SPECS / s["datasource"]["path"])


def fit_issues(path):
    return [i for i in gate.run(path) if i.check == "fit"]


class TopAfter(unittest.TestCase):
    """golden_top_after: 5 (3) bars of 16 products after the filters fill the zone; Desktop drew them at the top of a
    fit-width zone with room for all 16 (golden-debt 2026-10-31, N5)."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.root = built(spec("top_after"), base=SPECS, name="rows_top_after", crowded=True)

    def test_rank_filter_caps_the_rows(self):
        ws = next(w for w in self.root.iter("worksheet") if w.get("name") == "Top 5 in Region")
        ds = next(d.get("datasource") for d in ws.iter("datasource-dependencies"))
        self.assertEqual(fit._top(ws, ds, "none:Product:nk", {}), 5)
        self.assertIsNone(fit._top(ws, ds, "none:Region:nk", {}))  # not ranked along the region

    def test_entire_view(self):
        z = zooms(self.root)
        self.assertEqual((z["Top 5 in Region"], z["Busiest Small Sellers"], z["Top 5 Overall"]), (fit.EV,) * 3)

    def test_gate_reads_the_cap_too(self):
        self.assertEqual(fit_issues(self.path), [])
        bad = self.path.with_name("rows_top_after_fw.twbx")
        repack(self.path, bad, set_zoom("Top 5 in Region", fit.FW))  # the golden before 166
        self.assertEqual([i.where for i in fit_issues(bad)], ["dashboard 'Top After' sheet 'Top 5 in Region'"])


class Periods(unittest.TestCase):
    """golden_actions_v2 Monthly Sales: 12 months as rows; the counter did not read [tmn:Order Date:ok], so the
    builder took Entire View blind and squeezed 10pt labels into ~12px rows (N6)."""

    def test_months_counted(self):
        old = spec("actions_v2")
        old["dashboard"].update(height=800, row_heights=[4, 8, 8])  # the layout before 166
        _, root = built(old, base=SPECS, name="rows_actions_old")
        self.assertEqual(zooms(root)["By Month"], fit.FW)
        _, root = built(spec("actions_v2"), base=SPECS, name="rows_actions", crowded=True)
        self.assertEqual(zooms(root)["By Month"], fit.EV)

    def test_counter(self):
        count = fit.builder_counter(builder(spec("actions_v2")))
        cols = [("[Order Date]", "Month-Trunc")]
        self.assertEqual(count(None, cols, [None], periods=True), 12)
        self.assertIsNone(count(None, cols, [None]))  # columns: a year heatmap's narrow tail stays unjudged
        self.assertIsNone(count(None, [("[Order Date]", "Month")], [None], periods=True))  # a date part: unknown

    def test_date_filter_leaves_it_unknown(self):
        s = spec("actions_v2")
        s["filters"].append({"field": "Order Date", "mode": "relative", "last": 3, "period": "month"})
        self.assertIsNone(fit.builder_counter(builder(s))(None, [("[Order Date]", "Month-Trunc")], [None], periods=True))


class LabelRow(unittest.TestCase):
    """A row of header labels in Entire View keeps the font's px and a fifth: 16px at 10pt (= SQUEEZE), more over."""

    def test_floor(self):
        _, root = built(spec("actions_v2"), base=SPECS, name="rows_floor", crowded=True)
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "By Month")
        zone = next(z for z in root.iter("zone") if z.get("name") == "By Month")
        rows, _ = fit.sides(ws, zone, (1000, 960), lambda *a, **k: 12, {})
        self.assertEqual(rows.squeeze, fit.SQUEEZE)  # 10pt
        rule = ws.find("table/style/style-rule[@element='label']")
        next(f for f in rule.findall("format") if f.get("attr") == "font-size").set("value", "14")
        rows, _ = fit.sides(ws, zone, (1000, 960), lambda *a, **k: 12, {})
        self.assertAlmostEqual(rows.squeeze, 14 * fit.LABEL_ROW / fit.ROW_PX)
        self.assertGreater(rows.need(), 12 * 22)


class LintD13(unittest.TestCase):
    def d13(self, s):
        return [f for f in design_lint.lint(s, str(SPECS)) if f.rule == "D13"]

    def test_short_cell_warns(self):
        old = spec("actions_v2")
        old["dashboard"].update(height=800, row_heights=[4, 8, 8])
        found = self.d13(old)
        self.assertEqual([f.where for f in found], ["sheet 'By Month'"])
        self.assertIn("12 bars", found[0].text)

    def test_quiet(self):
        self.assertEqual(self.d13(spec("actions_v2")), [])
        self.assertEqual(self.d13(spec("top_after")), [])


class LintF2(unittest.TestCase):
    """golden_top_after Busiest: AVG(Quantity) on the axis showed '9.4167' (N5)."""

    def f2(self, s):
        return [(f.where, f.text) for f in design_lint.lint(s, str(SPECS)) if f.rule == "F2"]

    def test_average_without_format(self):
        s = spec("top_after")
        s["sheets"][2]["measure"].pop("format")
        found = self.f2(s)
        self.assertEqual([w for w, _ in found], ["sheet 'Busiest Small Sellers'"])
        self.assertIn("AVG of 'Quantity'", found[0][1])
        self.assertEqual(self.f2(spec("top_after")), [])

    def test_tables_and_table_calcs_not_judged(self):
        s = spec("top_after")
        s["sheets"][2]["measure"].pop("format")
        s["sheets"][2]["measure"]["table_calc"] = {"type": "percent_of_total"}
        self.assertEqual(self.f2(s), [])
        s["sheets"][2] = {"name": "T", "type": "table", "rows": "Product", "measure": {"field": "Quantity", "agg": "avg"}}
        self.assertEqual(self.f2(s), [])


if __name__ == "__main__":
    unittest.main()
