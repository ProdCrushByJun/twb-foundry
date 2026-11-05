"""Bars along a date (date_level), a calc in its manual order (fields.<calc>.order), a KPI number with a unit
('40.2 h') in the outline and the reconciliation (decisions/090)."""
import copy
import csv
import functools
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import dates, expected, gate, html_outline, match, reconcile
from tbuilder.build import build, build_file
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, SPECS

SPEC = json.loads((SPECS / "bar_dates.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def built():
    """specs/bar_dates.json built once for the module: Xml, Golden and GateCatches read the same file."""
    return build_file(SPECS / "bar_dates.json", OUT / "bar_dates.twbx")
ROWS = list(csv.DictReader((ROOT / "data" / "sample" / "sales.csv").open(encoding="utf-8")))
ITSM = ROOT / "acceptance" / "itsm-incidents"

try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False


def size(r):
    s = float(r["Sales"])
    return "Large" if s >= 500 else "Medium" if s >= 200 else "Small"


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Expected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])

    def test_a_bar_per_month_and_category(self):
        want = defaultdict(float)
        for r in ROWS:
            want[f"{r['Order Date'][:7]} | {r['Category']}"] += float(r["Sales"])
        self.assertEqual({k: round(v, 2) for k, v in self.got["Sales by Month"].items()},
                         {k: round(v, 2) for k, v in want.items()})
        self.assertEqual(len({k[:7] for k in self.got["Sales by Month"]}), 12)

    def test_quarters_by_the_calc(self):
        want = defaultdict(float)
        for r in ROWS:
            want[f"{r['Order Date'][:4]}-Q{(int(r['Order Date'][5:7]) - 1) // 3 + 1} | {size(r)}"] += float(r["Sales"])
        self.assertEqual({k: round(v, 2) for k, v in self.got["Sales by Quarter"].items()},
                         {k: round(v, 2) for k, v in want.items()})

    def test_the_calc_in_its_manual_order(self):
        """Small, Medium, Large: the order asked for, not the alphabet (Large, Medium, Small)."""
        counts = defaultdict(int)
        for r in ROWS:
            counts[size(r)] += 1
        self.assertEqual(list(self.got["Orders by Size"]), ["Small", "Medium", "Large"])
        self.assertEqual(self.got["Orders by Size"], dict(counts))

    def test_null_date_is_a_member_of_its_own(self):
        """A discrete date: an empty date makes a 'Null' bar (decisions/056), unlike a continuous axis."""
        rows = [{"Order Date": "", "Category": "Tech", "Sales": "5"}, {"Order Date": "2025-01-03", "Category": "Tech",
                                                                         "Sales": "7"}]
        keys = [("Order Date", lambda r: expected._trunc(r["Order Date"], "month") if r["Order Date"] else None)]
        got = expected._grouped(rows, keys, lambda rs, v: sum(float(r["Sales"]) for r in rs))
        self.assertEqual(got, {"Null": 5.0, "2025-01": 7.0})


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(built())

    def test_discrete_month_on_columns(self):
        w = ws(self.root, "Sales by Month")
        ci = w.find("table/view/datasource-dependencies/column-instance[@name='[tmn:Order Date:ok]']")
        self.assertEqual((ci.get("derivation"), ci.get("type")), ("Month-Trunc", "ordinal"))
        self.assertTrue(w.findtext("table/cols").endswith(".[tmn:Order Date:ok]"))
        self.assertTrue(w.findtext("table/rows").endswith(".[sum:Sales:qk]"))
        self.assertEqual(w.find("table/panes/pane/mark").get("class"), "Bar")  # Automatic draws a line
        self.assertTrue(w.find("table/panes/pane/encodings/color").get("column").endswith(".[none:Category:nk]"))

    def test_month_headers_short(self):
        fmt = ws(self.root, "Sales by Month").find("table/style/style-rule[@element='label']/format")
        self.assertEqual((fmt.get("attr"), fmt.get("value")), ("text-format", "*mmm"))
        self.assertTrue(fmt.get("field").endswith(".[tmn:Order Date:ok]"))
        quarter = ws(self.root, "Sales by Quarter").find("table/style/style-rule[@element='label']")
        self.assertEqual([f.get("attr") for f in quarter], ["color", "font-size"])  # no text-format: 10pt (087)

    def test_label_format_by_years(self):
        self.assertEqual(dates.bar_label_format("month", ["2025-01-02", "2025-12-31"]), "*mmm")
        self.assertEqual(dates.bar_label_format("month", ["2024-12-02", "2025-01-31", ""]), "*mmm yyyy")
        self.assertIsNone(dates.bar_label_format("quarter", ["2025-01-02"]))

    def test_quarter_along_rows(self):
        w = ws(self.root, "Sales by Quarter")
        self.assertTrue(w.findtext("table/rows").endswith(".[tqr:Order Date:ok]"))
        self.assertEqual(w.find("table/panes/pane/mark").get("class"), "Bar")

    def test_calc_default_sort(self):
        ds = next(d for d in self.root.iter("datasource") if d.get("name", "").startswith("federated."))
        calc = next(c for c in ds.findall("column") if c.get("caption") == "Size")
        inst = f"[none:{calc.get('name')[1:-1]}:nk]"
        ms = ds.find("default-sorts/manual-sort")
        self.assertEqual(ms.get("column"), inst)
        self.assertEqual([b.text for b in ms.iter("bucket")], ['"Small"', '"Medium"', '"Large"'])
        self.assertIsNotNone(next((c for c in ds.findall("column-instance") if c.get("name") == inst), None))

    def test_bar_without_date_level_unchanged(self):
        w = ws(self.root, "Orders by Size")
        self.assertEqual(w.find("table/panes/pane/mark").get("class"), "Automatic")


class HighlightAndPalette(unittest.TestCase):
    """A bar along a date: color {field, highlight} and the series colors from fields.<f>.color (decisions/111)."""

    @classmethod
    def setUpClass(cls):
        def f(s):
            sheet(s, "Sales by Month")["color"] = {"field": "Category", "highlight": ["Tech"]}
        spec = mutate(f)
        path = OUT / "bar_dates_highlight.twbx"
        build(spec, path, SPECS)
        cls.root = twb(path)
        cls.spec = spec

    def test_stacked_by_the_field_colored_by_the_flag(self):
        enc = ws(self.root, "Sales by Month").find("table/panes/pane/encodings")
        self.assertTrue(enc.find("color").get("column").split(".[")[-1].startswith("none:Calculation_"))
        self.assertTrue(enc.find("lod").get("column").endswith(".[none:Category:nk]"))
        self.assertEqual(ws(self.root, "Sales by Month").find("table/panes/pane/mark").get("class"), "Bar")

    def test_highlight_palette(self):
        maps = [m for r in self.root.iter("style-rule") if r.get("element") == "mark"
                for e in r.findall("encoding") if e.get("type") == "palette" and "Calculation_" in e.get("field", "")
                for m in e.findall("map")]
        self.assertEqual({m.findtext("bucket") for m in maps}, {"true", "false"})

    def test_expected_per_month_and_category(self):
        got = expected.compute(self.spec, SPECS / self.spec["datasource"]["path"])["Sales by Month"]
        self.assertEqual(len({k[:7] for k in got}), 12)
        self.assertTrue(all(k.split(" | ")[1] in ("Tech", "Furniture", "Office") for k in got))

    def test_series_palette_from_fields(self):
        """The colors of a stacked bar's series come from fields.<color field>.color, as on any bar (decisions/111)."""
        cats = {"Furniture": "#2f6fb5", "Office": "#e07b39", "Tech": "#999999"}
        spec = mutate(lambda s: s.update(fields={"Category": {"color": cats}}))
        path = OUT / "bar_dates_palette.twbx"
        build(spec, path, SPECS)
        root = twb(path)
        encs = [e for r in root.iter("style-rule") if r.get("element") == "mark"
                for e in r.findall("encoding") if e.get("field", "").endswith("[none:Category:nk]")]
        self.assertEqual({m.findtext("bucket").strip('"'): m.get("to") for e in encs for m in e.findall("map")}, cats)
        enc = ws(root, "Sales by Month").find("table/panes/pane/encodings")
        self.assertTrue(enc.find("color").get("column").endswith(".[none:Category:nk]"))


class Refusals(unittest.TestCase):
    def build(self, spec):
        return build(spec, OUT / "bar_dates_refused.twbx", SPECS)

    def test_date_level_on_text(self):
        with self.assertRaisesRegex(ValueError, "date_level needs a date dimension"):
            self.build(mutate(lambda s: sheet(s, "Sales by Month").update(dimension="Region")))

    def test_options_that_need_members(self):
        for key, value in (("top", {"n": 3}), ("plan", {"field": "Profit"}),
                           ("color", {"good": "up"}), ("color", {"scale": "sequential"})):
            def f(s):
                sheet(s, "Sales by Month").pop("color")
                sheet(s, "Sales by Month")[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "along a date .date_level. is not supported"):
                self.build(mutate(f))

    def test_highlight_needs_a_field(self):
        def f(s):
            sheet(s, "Sales by Month")["color"] = {"highlight": ["Tech"]}
        with self.assertRaisesRegex(ValueError, "must be a text dimension"):
            self.build(mutate(f))

    def test_date_without_date_level(self):
        with self.assertRaisesRegex(ValueError, "is a date"):
            self.build(mutate(lambda s: sheet(s, "Sales by Month").pop("date_level")))

    def test_calc_order_must_list_every_value(self):
        with self.assertRaisesRegex(ValueError, r"order leaves out \['Large'\]"):
            self.build(mutate(lambda s: s["fields"]["Size"].update(order=["Small", "Medium"])))

    def test_calc_order_names_values_of_the_calc(self):
        with self.assertRaisesRegex(ValueError, "not values of the field"):
            self.build(mutate(lambda s: s["fields"]["Size"].update(order=["Small", "Medium", "Large", "Huge"])))

    def test_calc_order_twice(self):
        with self.assertRaisesRegex(ValueError, "non-unique"):  # the schema's uniqueItems, as for a column
            self.build(mutate(lambda s: s["fields"]["Size"].update(order=["Small", "Small", "Medium", "Large"])))

    def test_calc_other_properties(self):  # aliases of a row-level calc are supported since decisions/151
        self.build(mutate(lambda s: s["fields"]["Size"].update(aliases={"Small": "S"})))

    def test_calc_order_on_a_number(self):
        def f(s):
            s["calcs"].append({"name": "Double", "formula": "[Sales] * 2"})
            s["fields"]["Double"] = {"order": ["1", "2"]}
        with self.assertRaisesRegex(ValueError, "order and color apply to a row-level text calculation"):
            self.build(mutate(f))


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """golden_bar_dates_2025_1: specs/bar_dates.json re-saved by Desktop 2025.1 (resave CLEAN, 3/3 sheets,
        check-drawn 19/19 marks) = the generator's output."""
        import difflib
        from test_roundtrip import canon, normalize, read_twbx
        got, names = read_twbx(built())
        want, _ = read_twbx(ROOT / "golden" / "golden_bar_dates_2025_1.twbx")
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = built()

    def assertCaught(self, fn, kind, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith(f"[{kind}]") and text in i for i in issues), issues)

    @staticmethod
    def month(r):
        return next(c for c in ws(r, "Sales by Month").iter("column-instance") if c.get("name") == "[tmn:Order Date:ok]")

    @staticmethod
    def sort(r):
        return next(r.iter("manual-sort"))

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_automatic_mark_draws_a_line(self):
        self.assertCaught(lambda r: ws(r, "Sales by Month").find("table/panes/pane/mark").set("class", "Automatic"),
                          "dates", "draws a line along the dates")

    def test_discrete_name_continuous_type(self):
        self.assertCaught(lambda r: self.month(r).set("type", "quantitative"), "dates", "is not named by its derivation")

    def test_derivation_not_the_name(self):
        self.assertCaught(lambda r: self.month(r).set("derivation", "Year-Trunc"), "dates",
                          "is not named by its derivation")

    def test_trunc_of_text(self):
        self.assertCaught(lambda r: self.month(r).set("column", "[Category]"), "dates", "a string column")

    def test_calc_order_of_a_number(self):
        def f(r):
            ds = next(d for d in r.iter("datasource") if d.get("name", "").startswith("federated."))
            calc = next(c for c in ds.findall("column") if c.get("caption") == "Size")
            calc.set("datatype", "integer")
        self.assertCaught(f, "fields", "an order sorts the members of a text dimension")

    def test_calc_order_twice(self):
        def f(r):
            d = self.sort(r).find("dictionary")
            d.append(copy.deepcopy(d[0]))
        self.assertCaught(f, "fields", "listed more than once")

    def test_calc_order_undeclared(self):
        self.assertCaught(lambda r: self.sort(r).set("column", "[none:Calculation_1:nk]"), "fields",
                          "is not a column-instance of the datasource")


class Itsm(unittest.TestCase):
    def test_by_month_is_a_stacked_bar(self):
        spec = json.loads((ITSM / "spec.json").read_text(encoding="utf-8"))
        s = sheet(spec, "By Month")
        self.assertEqual((s["type"], s["date_level"], s["color"]), ("bar", "month", "Priority"))
        got = expected.compute(spec, ITSM / "incidents.csv")["By Month"]
        self.assertEqual(sorted({k.split(" | ")[0] for k in got}),
                         ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"])
        self.assertEqual(sum(got.values()), 2742)

    @unittest.skipUnless(HAVE_CHROME, "Chrome is needed for the outline")
    def test_reconcile_pairs_the_unit_tile(self):
        """'40.2 h' is the tile 'Mean time to resolve, h', not Resolved (2 724) nor the donut total; nothing accepted
        for it (decisions/090: 4 accepts per state gone, matched 67 -> 68)."""
        spec = json.loads((ITSM / "spec.json").read_text(encoding="utf-8"))
        r = reconcile.check(spec, ITSM, html_outline.outline(ITSM / "itsm-incidents.html"),
                            reconcile.load_case(ITSM / "reconcile.json"), "spec.json")
        self.assertTrue(r["ok"], reconcile.problems(r))
        self.assertGreaterEqual(r["summary"]["matched"], 68)
        f = next(f for f in r["facts"] if f["number"] == "40.2" and "40.2 h" in f["text"])
        self.assertEqual((f["status"], f["workbook"]), ("matched", "KPI = 40.1987"))
        self.assertEqual(f["unit"], "h")


class Units(unittest.TestCase):
    def test_unit_suffix(self):
        for text, unit in (("40.2 h", "h"), ("40.2h", "h"), ("35 min", "min"), ("2.4x", "x"), ("+1.2 pp", "pp"),
                           ("120 ms", "ms"), ("3 d", "d"), ("1,234 h", "h"), ("12 MW", None), ("74.8%", None),
                           ("12 hours", None), ("$1.2M", None), ("40.2", None)):
            self.assertEqual(match.unit_suffix(text), unit, text)
        self.assertEqual(match.parse_number("40.2 h"), (40.2, 0.1, "", False))  # the value as is: no scale

    def test_label_unit(self):
        self.assertEqual(match.label_unit("Mean time to resolve, h"), ("Mean time to resolve", "h"))
        self.assertEqual(match.label_unit("MTTR (h)"), ("MTTR", "h"))
        self.assertEqual(match.label_unit("Resolved"), ("Resolved", None))
        self.assertEqual(match.label_unit("Sales, k"), ("Sales, k", None))  # k is a scale, not a unit

    def test_outline_block(self):
        raw = {"title": "", "page": [100, 100], "palette": {}, "fonts": {}, "headings": [], "svgs": [], "canvases": [],
               "bar_groups": [], "tables": [], "lists": [], "images": [], "controls": [],
               "numbers": [{"text": "40.2 h", "label": "Mean time to resolve", "box": [0, 0, 50, 30]},
                           {"text": "2,724", "label": "Resolved", "box": [60, 0, 50, 30]}]}
        blocks = html_outline.build_outline(raw)["blocks"]
        self.assertEqual([(b["text"], b.get("unit")) for b in blocks], [("40.2 h", "h"), ("2,724", None)])

    def test_kpi_evidence_unit(self):
        from tbuilder.excel import load
        outline = {"blocks": [{"id": "b1", "kind": "kpi", "text": "40.2 h", "label": "Mean time to resolve"}]}
        got = match.match(outline, ITSM / "incidents.csv")
        self.assertEqual(got[0]["unit"], "h")
        self.assertIsNotNone(load(ITSM / "incidents.csv"))

    def test_reconcile_unit_tile(self):
        """Synthetic tiles: the unit and the label without it pick the tile; a number without a unit as before."""
        ents = [reconcile._entry("KPI", "", ["Resolved", "Resolved"], 2724),
                reconcile._entry("KPI", "", ["Mean time to resolve, h", "Resolve Hours"], 40.1987)]
        page = {"texts": [{"text": "40.2 h", "box": [0, 0, 1, 1],
                           "up": ["40.2 h", "Mean time to resolve 40.2 h hours, resolved incidents"]}]}
        f = reconcile.facts(page)[0]
        names = reconcile._Names({}, ents)
        cands, _ = reconcile._candidates(f, ents, names)
        self.assertEqual([e["value"] for e in cands], [40.1987])
        f2 = dict(f, unit=None)
        self.assertEqual({e["value"] for e in reconcile._candidates(f2, ents, names)[0]}, {2724})


if __name__ == "__main__":
    unittest.main()
