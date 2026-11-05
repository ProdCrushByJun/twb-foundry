"""Registry tables (todo 3.4): a pane per column, bar-in-cell / text cells, highlight, nested sort, titles."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import design, registry
from tbuilder.build import build
from tbuilder.expected import compute
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry.json").read_text(encoding="utf-8"))
SPEC["dashboard"]["theme"] = "flat"  # the view without cards (decisions/168)
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_test.twbx"


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


class Calcs(unittest.TestCase):
    def test_generated(self):
        got = {c["name"]: c["formula"] for c in registry.calcs(SPEC)}
        self.assertEqual(got["Registry · Profit · Flag"], "SUM([Profit]) < 1400")
        self.assertEqual(got["Registry · Units · Flag"], "SUM([Quantity]) > 250")
        self.assertEqual(got["Registry · Units · Cell"], "MIN(1)")
        self.assertNotIn("Registry · Sales · Cell", got)  # bar columns need no dummy axis

    def test_expected(self):
        got = compute(SPEC, SPECS / SPEC["datasource"]["path"])
        self.assertEqual(round(got["Registry"]["East | Office"]["Profit"]), 1378)
        self.assertEqual(got["Registry"]["South | Office"]["Units"], 317)
        self.assertEqual(round(got["By Category"]["Tech"]["Sales"]), 78575)


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.ws = {w.get("name"): w for w in cls.root.iter("worksheet")}

    def test_a_pane_per_column(self):
        table = self.ws["Registry"].find("table")
        panes = table.findall("panes/pane")
        self.assertEqual([p.get("id") for p in panes], [None, "1", "2", "3"])  # default pane first
        self.assertEqual({p.find("mark").get("class") for p in panes[1:]}, {"Bar"})
        self.assertEqual(table.findtext("cols").count(" + "), 2)
        self.assertTrue(table.findtext("rows").startswith("(") and " / " in table.findtext("rows"))
        text = panes[3]  # Units: a text cell labelled with the measure, flagged by color
        self.assertIn("sum:Quantity", text.find("encodings/text").get("column"))
        self.assertIn("usr:Calculation_", text.find("encodings/color").get("column"))
        self.assertTrue(text.find("encodings/color").get("column").endswith(":nk]"))
        hidden = [f for f in table.iter("format") if f.get("attr") == "display"]
        self.assertEqual(len(hidden), 3)

    def test_widths_match_titles(self):
        table = self.ws["Registry"].find("table")
        dims = [int(f.get("value")) for f in table.iter("format") if f.get("attr") == "width"]
        cols = {int(f.get("value")) for f in table.iter("format") if f.get("attr") == "minwidth"}
        self.assertEqual(len(dims), 2)
        self.assertEqual(len(cols), 1)  # columns share the width left after the row headers
        titles = [z for z in self.root.iter("zone") if z.get("type-v2") == "text"
                  and z.find("formatted-text/run").get("fontsize") == str(design.FONT["table_header"])]
        names = [z.find("formatted-text/run").text for z in titles]
        self.assertEqual(names[:5], ["Region", "Category", "Sales", "Profit", "Units"])
        w = [int(z.get("w")) for z in titles[:5]]
        px = [round(v * 1000 / 100000) for v in w]  # dashboard is 1000px wide
        self.assertEqual(px[:2], dims)
        self.assertTrue(all(abs(p - next(iter(cols))) <= 1 for p in px[2:]))

    def test_nested_sort_and_flags(self):
        view = self.ws["Registry"].find("table/view")
        s = view.find("shelf-sorts/shelf-sort-v2")
        self.assertEqual((s.get("direction"), s.get("is-on-innermost-dimension")), ("DESC", "true"))
        self.assertIn("none:Category", s.get("dimension-to-sort"))
        manifest = [c.tag for c in self.root.find("document-format-change-manifest")]
        self.assertIn("IntuitiveSorting_SP2", manifest)
        self.assertNotIn("SortTagCleanup", manifest)  # only a computed-sort needs it

    def test_single_dim_sort_is_computed(self):
        root = built(mutate(lambda s: sheet(s, "By Category").update(sort="asc")))
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "By Category")
        self.assertIsNotNone(ws.find("table/view/computed-sort"))

    def test_palettes(self):
        ds = self.root.find("datasources/datasource")
        maps = [[(m.get("to"), m.findtext("bucket")) for m in e] for e in ds.iter("encoding")]
        self.assertIn([(design.COLOR["cell_bar"], "false"), (design.COLOR["cell_bad"], "true")], maps)
        self.assertIn([(design.COLOR["cell_bad"], "true"), (design.COLOR["cell_text"], "false")], maps)


class RegistryErrors(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_repeated_bar_measure(self):
        self.assertRejects(mutate(lambda s: sheet(s, "By Category")["columns"].append(
            {"measure": {"field": "Sales"}, "label": "Sales again"})), "repeats a measure")

    def test_duplicate_labels(self):
        self.assertRejects(mutate(lambda s: sheet(s, "By Category")["columns"][1].update(label="Sales")),
                           "labels must be unique")

    def test_calc_column(self):
        """An aggregate calc in a column (decisions/039; 015 took CSV columns only): expected and the flag see it."""
        def f(s):
            s["calcs"] = [{"name": "Margin", "formula": "SUM([Profit]) / SUM([Sales])"}]
            sheet(s, "By Category")["columns"][1].update(measure={"field": "Margin"}, highlight={"below": 0.03})
        spec = mutate(f)
        built(spec)
        got = {c["name"]: c["formula"] for c in registry.calcs(spec, {"Margin"})}
        self.assertEqual(got["By Category · Margin · Flag"], "[Margin] < 0.03")
        exp = compute(spec, SPECS / spec["datasource"]["path"])["By Category"]["Tech"]
        base = compute(SPEC, SPECS / SPEC["datasource"]["path"])["By Category"]["Tech"]
        self.assertAlmostEqual(exp["Margin"], base["Profit"] / base["Sales"])

    def test_table_calc_column_not_yet(self):
        def f(s):
            s["calcs"] = [{"name": "Rank", "formula": "RANK(SUM([Sales]))", "compute_using": ["Category"]}]
            sheet(s, "By Category")["columns"][1]["measure"] = {"field": "Rank"}
        self.assertRejects(mutate(f), "table calculation")

    def test_numeric_rows(self):
        self.assertRejects(mutate(lambda s: sheet(s, "By Category").update(rows=["Quantity"])), "numeric")

    def test_too_narrow(self):
        self.assertRejects(mutate(lambda s: s["dashboard"].update(width=500)), "too narrow")


class ReferenceWidths(unittest.TestCase):
    def test_column_titles_tile_at_every_reference_width(self):
        """Column title edges come from a running total: rounded one by one they overlapped by a unit at 1100, 1400
        and 1900px and the gate refused the workbook (found by dashboard-designer on a case)."""
        from tbuilder.design_lint import WIDTHS
        for width in WIDTHS:
            with self.subTest(width=width):
                root = built(mutate(lambda s: s["dashboard"].update(width=width)))  # the gate runs inside build
                titles = [z for z in root.iter("zone") if z.get("type-v2") == "text"
                          and z.find("formatted-text/run").get("fontsize") == str(design.FONT["table_header"])]
                rows = {}
                for z in titles:
                    rows.setdefault(z.get("y"), []).append((int(z.get("x")), int(z.get("w"))))
                n_registries = sum(s["type"] == "registry" for s in SPEC["sheets"])  # side by side in one strip
                for strip in rows.values():
                    strip.sort()
                    pairs = list(zip(strip, strip[1:]))
                    self.assertTrue(all(x + w <= nx for (x, w), (nx, _) in pairs), strip)  # no overlap
                    self.assertLessEqual(sum(x + w != nx for (x, w), (nx, _) in pairs), n_registries - 1, strip)


if __name__ == "__main__":
    unittest.main()
