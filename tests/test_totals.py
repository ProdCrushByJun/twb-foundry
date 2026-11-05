"""Grand totals, subtotals and the sheet's own tooltip (decisions/036): expected, the XML, refusals, gate mutations."""
import copy
import csv
import json
import unittest
from statistics import mean
from unittest import mock

from tbuilder import expected, gate, totals
from tbuilder.build import build, build_file
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "totals.json"
CSV = ROOT / "data" / "sample" / "sales.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def compute(s=None):
    return expected.compute(s or spec(), CSV)


def wrong_totals(exp):
    """Totals that differ from the measure over all the rows of their partition, computed straight from the CSV
    (independent of expected.py): [(sheet, key, got, want)]."""
    out = []

    def want(rows, how, field):
        xs = [float(r[field]) for r in rows]
        return {"sum": sum, "avg": mean, "countd": lambda v: len(set(v))}[how](xs)

    def check(name, key, got, rows, how, field):
        w = want(rows, how, field)
        if abs(got - w) > 1e-6:
            out.append((name, key, got, w))

    for name, field, how, lab in (("Sales", "Sales", "sum", "Total"), ("Avg Profit", "Profit", "avg", "All")):
        got = exp[name]
        for c in {r["Category"] for r in ROWS}:
            check(name, f"{lab} | {c}", got[f"{lab} | {c}"], [r for r in ROWS if r["Category"] == c], how, field)
        for r0 in {r["Region"] for r in ROWS}:
            check(name, f"{r0} | {lab}", got[f"{r0} | {lab}"], [r for r in ROWS if r["Region"] == r0], how, field)
        check(name, f"{lab} | {lab}", got[f"{lab} | {lab}"], ROWS, how, field)
    reg = exp["Registry"]
    for col, field, how in (("Sales", "Sales", "sum"), ("Avg profit", "Profit", "avg"),
                            ("Order sizes", "Quantity", "countd")):
        check("Registry", "Total", reg["Total"][col], ROWS, how, field)
        for r0 in {r["Region"] for r in ROWS}:
            check("Registry", f"{r0} | Total", reg[f"{r0} | Total"][col], [r for r in ROWS if r["Region"] == r0],
                  how, field)
    return out


class Expected(unittest.TestCase):
    def test_totals_are_the_measure_over_the_rows(self):
        self.assertEqual(wrong_totals(compute()), [])

    def test_avg_and_countd_totals_are_not_the_cells_added_up(self):
        exp = compute()
        cells = [v for k, v in exp["Avg Profit"].items() if "All" not in k.split(" | ")]
        self.assertNotAlmostEqual(exp["Avg Profit"]["All | All"], mean(cells), places=3)
        self.assertNotEqual(exp["Registry"]["Total"]["Order sizes"],
                            sum(v["Order sizes"] for k, v in exp["Registry"].items() if " | " in k
                                and not k.endswith("Total")))
        self.assertAlmostEqual(exp["Sales"]["Total | Total"], 224709.68, places=2)  # SUM: the cells added up

    def test_mutant_avg_total_as_a_sum_of_cells_is_caught(self):
        """An expected.py that adds up the cells for every total: the AVG and COUNTD totals go wrong."""
        def summed(s, rows, keys, value, grouped):
            marks = grouped(rows, keys, value)
            out, lab = {}, totals.label(s)
            row, col = totals.grand(s)
            if row:
                for k, v in marks.items():
                    c = k.split(" | ")[1]
                    out[f"{lab} | {c}"] = out.get(f"{lab} | {c}", 0) + v
            if col:
                for k, v in marks.items():
                    r = k.split(" | ")[0]
                    out[f"{r} | {lab}"] = out.get(f"{r} | {lab}", 0) + v
            if row and col:
                out[f"{lab} | {lab}"] = sum(marks.values())
            return out

        with mock.patch.object(totals, "table", summed):
            bad = wrong_totals(compute())
        self.assertTrue(bad and all(name == "Avg Profit" for name, *_ in bad), bad)

    def test_no_totals_no_keys(self):
        s = spec()
        for x in s["sheets"]:
            x.pop("totals", None)
        exp = compute(s)
        self.assertFalse([k for k in exp["Sales"] if "Total" in k])
        self.assertFalse([k for k in exp["Registry"] if "Total" in k])


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lxml import etree
        import zipfile
        cls.path = build_file(SPEC, OUT / "totals_test.twbx")
        with zipfile.ZipFile(cls.path) as z:
            cls.root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))

    def test_shelves(self):
        t = ws(self.root, "Sales").find("table")
        self.assertEqual((t.find("rows").get("total"), t.find("cols").get("total")), ("true", "true"))
        r = ws(self.root, "Registry").find("table")
        self.assertEqual((r.find("rows").get("total"), r.find("cols").get("total")), ("true", None))
        self.assertEqual([c.text.split("].")[1] for c in r.findall("subtotals/column")], ["[none:Region:nk]"])
        self.assertIsNone(ws(self.root, "Regions").find("table/rows").get("total"))

    def test_look(self):
        st = ws(self.root, "Avg Profit").find("table/style")
        fmt = {(f.getparent().get("element"), f.get("attr"), f.get("field", "").split("].")[-1]): f.get("value")
               for f in st.iter("format") if f.get("data-class") == "total"}
        self.assertEqual(fmt, {("cell", "font-weight", ""): "bold",
                               ("header", "total-label", "[none:Region:nk]"): "All",
                               ("header", "font-weight", "[none:Region:nk]"): "bold",
                               ("header", "total-label", "[none:Category:nk]"): "All",
                               ("header", "font-weight", "[none:Category:nk]"): "bold",
                               ("pane", "background-color", ""): "#e6e6e6"})
        self.assertEqual([r.get("element") for r in st][:4], ["axis", "cell", "header", "pane"])

    def test_tooltip_runs(self):
        tip = ws(self.root, "Regions").find("table/panes/pane/customized-tooltip")
        runs = [(r.get("bold"), r.get("fontcolor"), r.text.split("].")[-1]) for r in tip.iter("run")]
        self.assertEqual(runs, [(None, "#898989", "Region: "), ("true", None, "[none:Region:nk]>"),
                                (None, None, "Æ\n"), (None, "#898989", "Sales: "), ("true", None, "[sum:Sales:qk]>"),
                                (None, None, "Æ\n"), (None, "#898989", "Profit: "),
                                ("true", None, "[sum:Profit:qk]>")])
        enc = [(e.tag, e.get("column").split("].")[-1]) for e in ws(self.root, "Regions").iter("tooltip")]
        self.assertEqual(enc, [("tooltip", "[sum:Profit:qk]")])  # Profit is not on the sheet: Tooltip shelf

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path), [])


def build_error(s):
    with unittest.TestCase().assertRaises(ValueError) as e:
        build(s, OUT / "totals_neg.twbx", SPEC.parent)
    return str(e.exception)


class Refusals(unittest.TestCase):
    def test_types(self):
        s = spec()
        s["sheets"].append({"name": "Heat", "type": "heatmap", "rows": "Region", "cols": "Category",
                            "measure": {"field": "Sales"}, "totals": {"grand": "rows"}})
        self.assertIn("totals", build_error(s))  # the schema has no totals on a heatmap
        with self.assertRaisesRegex(ValueError, "not a heatmap"):
            totals.check({"sheets": [s["sheets"][-1]]})

    def test_table_subtotals(self):
        s = spec()
        sheet(s, "Sales")["totals"] = {"sub": ["Region"]}
        self.assertIn("subtotals need two row dimensions", build_error(s))

    def test_registry(self):
        s = spec()
        sheet(s, "Registry")["totals"] = {"grand": "both"}
        self.assertIn("grand totals 'rows' only", build_error(s))
        s = spec()
        sheet(s, "Registry")["columns"][0].update(style="pill", levels=[{"label": "Low", "color": "bad"}, {"from": 1, "label": "High", "color": "good"}])  # rank / track / dot / tick /
        self.assertIn("drop the totals", build_error(s))  # highlight take a total (decisions/134)
        s = spec()
        sheet(s, "Registry")["columns"][0]["total"] = {"bar": True}  # a text column has no total bar
        self.assertIn("'total' (the total row's bar and format) applies to bar and bar_inside", build_error(s))
        s = spec()
        sheet(s, "Registry")["totals"] = {"sub": ["Category"]}
        self.assertIn("only the outer of two row dimensions", build_error(s))

    def test_table_calc(self):
        s = spec()
        sheet(s, "Sales")["measure"]["table_calc"] = {"type": "percent_of_total"}
        self.assertIn("totals of a table calculation", build_error(s))


class Tooltip(unittest.TestCase):
    def tip(self, text, name="Regions"):
        s = spec()
        sheet(s, name)["tooltip"] = text
        return s

    def test_dimension_not_on_the_sheet(self):
        self.assertIn("<Category> is not on the sheet", build_error(self.tip("<Category>: <SUM(Sales)>")))

    def test_aggregate_calc_named_as_agg(self):
        s = self.tip("<SUM(Margin)>")
        s["calcs"] = [{"name": "Margin", "formula": "SUM([Profit]) / SUM([Sales])"}]
        self.assertIn("write <AGG(Margin)>", build_error(s))
        sheet(s, "Regions")["tooltip"] = "Margin <AGG(Margin)>"
        build(s, OUT / "totals_tip.twbx", SPEC.parent)

    def test_plain_name_and_no_field(self):
        s = self.tip("<Sales>")
        sheet(s, "Regions")["measure"] = {"field": "Sales"}
        build(s, OUT / "totals_tip.twbx", SPEC.parent)  # one Sales measure on the sheet: <Sales> is it
        self.assertIn("does not match", build_error(self.tip("plain text, no field")))  # the schema wants a field
        self.assertIn("is not an aggregate calculation", build_error(self.tip("<AGG(Sales)>")))

    def test_not_on_a_kpi(self):
        with self.assertRaisesRegex(ValueError, "not a kpi"):
            from tbuilder import tooltips
            tooltips.check({"sheets": [{"name": "K", "type": "kpi", "tooltip": "<SUM(Sales)>"}]})

    def test_spaces_between_fields_stay_in_the_field_run(self):
        from lxml import etree
        import zipfile
        s = self.tip("<Region> <SUM(Sales)>")
        p = build(s, OUT / "totals_tip.twbx", SPEC.parent)
        with zipfile.ZipFile(p) as z:
            root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        runs = [r.text for r in ws(root, "Regions").iter("run")]
        self.assertEqual(len(runs), 2)
        self.assertTrue(runs[0].endswith("> "), runs)  # Desktop drops a run of spaces alone


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "totals_gate.twbx")

    def assertCaught(self, fn, check, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith(f"[{check}]") and text in i for i in issues), issues)

    def test_totals_on_a_bar(self):
        self.assertCaught(lambda r: ws(r, "Regions").find("table/rows").set("total", "true"), "totals",
                          "the total mark rescales it")

    def test_totals_on_a_registry_bar(self):
        def f(r):
            cols = ws(r, "Registry").find("table/cols")
            cols.text = cols.text.replace("[usr:Calculation_", "[sum:Sales:qk] + [usr:Calculation_", 1)
        self.assertCaught(f, "totals", "[sum:Sales:qk]")

    def test_totals_on_a_continuous_color(self):
        def f(r):
            enc = ws(r, "Sales").find("table/panes/pane/encodings")
            enc.insert(0, copy.deepcopy(enc.find("text")))
            enc[0].tag = "color"
        self.assertCaught(f, "totals", "rescales its color")

    def test_subtotal_of_the_innermost_dimension(self):
        def f(r):
            col = ws(r, "Registry").find("table/subtotals/column")
            col.text = col.text.replace("Region", "Category")
        self.assertCaught(f, "totals", "innermost dimension")

    def test_tooltip_field_not_on_the_sheet(self):
        def f(r):
            enc = ws(r, "Regions").find("table/panes/pane/encodings")
            enc.remove(enc.find("tooltip"))
        self.assertCaught(f, "tooltips", "[sum:Profit:qk] is not on the sheet")


if __name__ == "__main__":
    unittest.main()
