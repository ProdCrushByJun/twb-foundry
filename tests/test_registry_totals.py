"""A registry total under bar columns (decisions/081): the bar of a bar / bar_inside column is a calc guarded to the
rows, 0 on a total row, so the total does not stretch the column; the total's number is a label (its own format on
request); total.bar keeps a total's bar no longer than the rows'."""
import copy
import json
import unittest
from lxml import etree as ET  # gate walks getparent()
import zipfile
from pathlib import Path

from tbuilder import design, design_lint, gate, registry, spec as spec_mod
from tbuilder.build import build
from tbuilder.expected import compute, data_path
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry_totals.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_totals_test.twbx"


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def column(spec, sheet_name, label):
    return next(c for c in sheet(spec, sheet_name)["columns"] if registry.label(c) == label)


def calcs(spec=SPEC):
    return {c["name"]: c for c in registry.calcs(spec, {"Margin"})}


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def by_caption(root):
    """{caption: (column name, formula)} of the calculated columns."""
    return {c.get("caption"): (c.get("name"), c.find("calculation").get("formula"))
            for c in root.find("datasources").iter("column") if c.find("calculation") is not None}


class Calcs(unittest.TestCase):
    def test_bar_zero_on_a_total(self):
        got = calcs()
        self.assertEqual(got["Regions · Sales · Bar"]["formula"], "IF COUNTD([Region]) <= 1 THEN SUM([Sales]) ELSE 0 END")
        self.assertEqual(got["Categories · Sales · Bar"]["formula"],
                         "IF COUNTD([Region]) <= 1 AND COUNTD([Category]) <= 1 THEN SUM([Sales]) ELSE 0 END")

    def test_total_bar_within_the_rows(self):
        self.assertEqual(calcs()["Categories · Margin % · Bar"]["formula"],
                         "IF (COUNTD([Region]) <= 1 AND COUNTD([Category]) <= 1) OR [Margin] <= "
                         "MAX({INCLUDE [Region], [Category] : [Margin]}) THEN [Margin] ELSE 0 END")

    def test_zero_total_bar_in_the_total_shading(self):
        """decisions/164: a 0 bar on a total row drew a 1px line of the bar's color at the total's number; a fill
        calc colors it in the total's shading, a total that keeps its bar (total.bar) stays a row."""
        got = calcs()
        self.assertEqual(got["Regions · Sales · Fill"]["formula"],
                         'IF COUNTD([Region]) <= 1 THEN "Row" ELSE "Total" END')
        self.assertEqual(got["Categories · Margin % · Fill"]["formula"],
                         'IF (COUNTD([Region]) <= 1 AND COUNTD([Category]) <= 1) OR [Margin] <= '
                         'MAX({INCLUDE [Region], [Category] : [Margin]}) THEN "Row" ELSEIF COUNTD([Region]) <= 1 '
                         'THEN "Subtotal" ELSE "Total" END')  # a subtotal's row is not shaded: its 0 bar white
        self.assertNotIn("Regions · Units · Fill", got)  # a text cell: its white bar, the total shaded by 072
        s = sheet(SPEC, "Regions")
        self.assertEqual(registry.fill_buckets(s, column(SPEC, "Regions", "Margin")),
                         [('"Row"', registry.bar_color(s)), ('"Total"', design.COLOR["rule"])])
        self.assertEqual(registry.fill_buckets(s, column(SPEC, "Regions", "Sales"))[1], ('"Total"', design.COLOR["rule"]))
        self.assertEqual(registry.fill_buckets(sheet(SPEC, "Categories"), column(SPEC, "Categories", "Profit"))[1],
                         ('"Subtotal"', design.COLOR["cell_text"]))

    def test_bar_inside_labels_rows_only_and_the_total_its_own(self):
        got = calcs()
        inside, outside = got["Regions · Margin · Inside"], got["Regions · Margin · Outside"]
        self.assertTrue(inside["formula"].startswith("IF COUNTD([Region]) <= 1 AND [Regions · Margin · Bar] > 0"))
        self.assertIn("WINDOW_MAX([Regions · Margin · Bar])", inside["formula"])  # the rows' bars, not the total
        self.assertTrue(outside["formula"].startswith("IF COUNTD([Region]) <= 1 AND NOT ("))
        self.assertEqual(inside["format"], "pct0")
        total = got["Regions · Margin · Total"]
        self.assertEqual((total["formula"], total["format"]),
                         ("IF NOT (COUNTD([Region]) <= 1) THEN [Margin] END", "pct1"))
        self.assertNotIn("Regions · Margin · Row", got)

    def test_bar_with_a_total_format_splits_its_label(self):
        got = calcs()
        self.assertEqual(got["Categories · Profit · Row"]["formula"],
                         "IF COUNTD([Region]) <= 1 AND COUNTD([Category]) <= 1 THEN SUM([Profit]) END")
        self.assertEqual(got["Categories · Profit · Total"]["format"], "currency")
        self.assertNotIn("Regions · Sales · Total", got)  # a bar without a format: the measure is its label

    def test_without_totals_nothing_changes(self):
        plain = mutate(lambda s: [x.pop("totals") or [c.pop("total", None) for c in x["columns"]]
                                  for x in s["sheets"]])
        names = set(calcs(plain))
        self.assertFalse(any(n.endswith((" · Bar", " · Row", " · Total")) for n in names))
        self.assertEqual(calcs(plain)["Regions · Margin · Inside"]["formula"],
                         "IF [Margin] > 0 AND [Margin] >= 0.5 * WINDOW_MAX([Margin]) THEN [Margin] END")


class Spec(unittest.TestCase):
    def test_schema(self):
        spec_mod.validate(SPEC)
        with self.assertRaises(Exception):
            spec_mod.validate(mutate(lambda s: column(s, "Regions", "Sales").update(total={})))
        with self.assertRaises(Exception):
            spec_mod.validate(mutate(lambda s: column(s, "Regions", "Sales").update(total={"bar": "yes"})))

    def test_refusals(self):
        cases = [(lambda s: column(s, "Regions", "Units").update(total={"bar": True}), "applies to bar and bar_inside"),
                 (lambda s: sheet(s, "Regions").pop("totals"), "of a registry with 'totals'"),
                 (lambda s: column(s, "Regions", "Margin").update(total={"bar": True}), "a bar_inside total shows"),
                 (lambda s: column(s, "Regions", "Sales").update(style="pill", levels=[{"label": "Low", "color": "bad"}, {"from": 1, "label": "High", "color": "good"}]),
                  "is pill: .*drop the totals")]  # track / highlight take a total since decisions/134
        for fn, msg in cases:
            with self.subTest(msg=msg), self.assertRaisesRegex(ValueError, msg):
                build(mutate(fn), OUT, SPECS)


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.calcs = by_caption(cls.root)

    def ref(self, caption):
        return self.calcs[caption][0]

    def test_gate_passes(self):
        self.assertEqual([i for c in gate.CHECKS if c is not gate.check_xsd for i in c(self.root)], [])

    def test_zero_bar_colored_by_its_fill(self):
        panes = ws(self.root, "Regions").findall("table/panes/pane")
        color = panes[1].find("encodings/color").get("column")
        self.assertIn(self.ref("Regions · Sales · Fill")[1:-1], color)
        self.assertTrue(color.endswith(":nk]"))
        ds = ET.tostring(self.root.find("datasources"), encoding="unicode")
        self.assertIn(design.COLOR["rule"], ds)  # the palette's Total bucket

    def test_bars_on_the_guarded_calcs(self):
        cols = ws(self.root, "Regions").findtext("table/cols")
        self.assertIn(f"[usr:{self.ref('Regions · Sales · Bar')[1:-1]}:qk]", cols)
        self.assertEqual(cols.count(f"[usr:{self.ref('Regions · Margin · Bar')[1:-1]}:qk]"), 2)  # dual axis
        self.assertNotIn("[sum:Sales:qk]", cols)

    def test_labels(self):
        panes = ws(self.root, "Regions").findall("table/panes/pane")
        sales = [e.get("column") for e in panes[1].iterfind("encodings/text")]
        self.assertEqual([c.rsplit(".", 1)[-1] for c in sales], ["[sum:Sales:qk]"])  # the total's number too

        def shown(pane):
            return [e.get("column").split(":")[1] for e in pane.iterfind("encodings/text")]
        # the total's number on the first layer, dark at its 0 bar: on the second, Desktop shortened every bar by its
        # width (124 -> 81px on a case)
        self.assertEqual(shown(panes[2]), [self.ref("Regions · Margin · Inside")[1:-1],
                                           self.ref("Regions · Margin · Total")[1:-1]])
        runs = panes[2].findall("customized-label/formatted-text/run")
        self.assertEqual([r.get("fontcolor") for r in runs], [design.COLOR["cell_text"], design.COLOR["text"]])
        self.assertEqual(shown(panes[3]), [self.ref("Regions · Margin · Outside")[1:-1]])

    def test_expected_total_is_the_ratio_of_the_sums(self):
        got = compute(SPEC, (SPECS / SPEC["datasource"]["path"]).resolve())
        self.assertAlmostEqual(got["Regions"]["TOTAL"]["Margin"], 23550.4 / 224709.68, places=3)
        self.assertAlmostEqual(got["Categories"]["East | Total"]["Sales"], 52353.59, places=2)




class LabelWidths(unittest.TestCase):
    def test_total_in_its_format_and_not_in_the_inside_share(self):
        class B:  # the builder's surface label_runs reads
            expected = {"Regions": {"East": {"Margin": 0.0931}, "TOTAL": {"Margin": 0.1048}}}

            def _measure(self, m):
                return type("F", (), {"col": type("C", (), {"name": m["field"]})()})()

            def number_format(self, col):
                return "pct0"
        s, c = sheet(SPEC, "Regions"), column(SPEC, "Regions", "Margin")
        texts = [line[0][0] for lines in registry.label_runs(B(), s, c) for line in lines]
        self.assertEqual(texts, ["9%", "10.5%"])  # the workbook's numbers in its locale, en_US (decisions/085)
        self.assertEqual(len(registry.label_runs(B(), s, c, rows_only=True)), 1)


class Lint(unittest.TestCase):
    def i8(self, spec):
        return [f.text for f in design_lint.lint(spec, SPECS) if f.rule == "I8"]

    def test_ratio_total_bar_is_clean(self):
        self.assertEqual(self.i8(SPEC), [])

    def test_sum_total_bar_warns(self):
        spec = mutate(lambda s: column(s, "Regions", "Sales").update(total={"bar": True}))
        self.assertTrue(any("'Sales'" in t and "'TOTAL'" in t for t in self.i8(spec)))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.calcs = by_caption(cls.root)

    def issues(self, fn):
        root = copy.deepcopy(self.root)
        fn(root)
        return [i for c in gate.CHECKS if c is not gate.check_xsd for i in c(root)]

    def set_formula(self, root, caption, fn):
        name = self.calcs[caption][0]
        for c in root.iter("column"):
            if c.get("name") == name and c.find("calculation") is not None:
                calc = c.find("calculation")
                calc.set("formula", fn(calc.get("formula")))

    def test_measure_bar_under_a_total(self):  # the total's bar stretches the column
        self.assertTrue(any(i.check == "totals" for i in self.issues(lambda r: self.set_formula(
            r, "Regions · Sales · Bar", lambda f: "SUM([Sales])"))))

    def test_guard_missing_a_row_dimension(self):  # a subtotal is drawn as a bar
        self.assertTrue(any(i.check == "totals" for i in self.issues(lambda r: self.set_formula(
            r, "Categories · Sales · Bar", lambda f: f.replace(" AND COUNTD([Category]) <= 1", "")))))

    def test_null_bar_on_the_total(self):  # no mark: no label on the total row
        self.assertTrue(any(i.check == "totals" for i in self.issues(lambda r: self.set_formula(
            r, "Regions · Sales · Bar", lambda f: f.replace(" ELSE 0 END", " END")))))

    def test_total_number_dropped(self):
        def f(root):
            enc = ws(root, "Regions").findall("table/panes/pane")[2].find("encodings")
            enc.remove(enc.findall("text")[1])
        self.assertTrue(any(i.check == "totals" and "no label" in i.message for i in self.issues(f)))

    def test_total_number_on_the_second_layer(self):  # Desktop shortened every bar of a case's from 124 to 81px
        def f(root):
            panes = ws(root, "Regions").findall("table/panes/pane")
            total = panes[2].find("encodings").findall("text")[1]
            panes[2].find("encodings").remove(total)
            panes[3].find("encodings").append(total)
        self.assertTrue(any(i.check == "totals" and "second layer" in i.message for i in self.issues(f)))

    def test_white_label_on_the_total(self):
        self.assertTrue(any(i.check == "totals" and "white label" in i.message for i in self.issues(
            lambda r: self.set_formula(r, "Regions · Margin · Inside",
                                       lambda f: f.replace("IF COUNTD([Region]) <= 1 AND ", "IF ")))))


if __name__ == "__main__":
    unittest.main()
