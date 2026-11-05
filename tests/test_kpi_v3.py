"""KPI card v3 (decisions/088, a reference): area sparkline, base value as a number, one points legend over the KPI
row, month letters under the sparkline."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import gate, kpi2
from tbuilder import spec as spec_mod
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from tbuilder.expected import compute
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS, canon, normalize, read_twbx

SPEC = json.loads((SPECS / "kpi_v3.json").read_text(encoding="utf-8"))
DATA = SPECS / SPEC["datasource"]["path"]
GOLDEN = ROOT / "golden" / "golden_kpi_v3_2025_1.twbx"
SALES, UNITS = "Monthly · Sales · History", "Yearly · Units · History"


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec=SPEC, name="kpi_v3_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def marks(pane):
    return {f.get("attr"): f.get("value") for f in pane.iterfind("style/style-rule[@element='mark']/format")}


class Area(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_points_layer_under_area(self):
        """With points: the first layer an Area (its stroke the line, the fill pale), the dots over it."""
        panes = ws(self.root, SALES).findall("table/panes/pane")
        self.assertEqual([p.find("mark").get("class") for p in panes], ["Area", "Area", "Circle"])
        f = marks(panes[1])
        self.assertEqual((f["has-stroke"], f["stroke-color"], f["mark-color"], f["mark-transparency"]),
                         ("true", COLOR["muted"], COLOR["muted"], kpi2.AREA_TRANSPARENCY))

    def test_single_area(self):
        """Without points: one Area pane in the accent, its labels the max and the last period as the line's."""
        panes = ws(self.root, UNITS).findall("table/panes/pane")
        self.assertEqual([p.find("mark").get("class") for p in panes], ["Area"])
        f = marks(panes[0])
        self.assertEqual((f["has-stroke"], f["stroke-color"], f["mark-color"]),
                         ("true", COLOR["accent"], COLOR["accent"]))
        self.assertEqual(f["mark-labels-show"], "true")

    def test_line_unchanged(self):
        """history 'line' keeps its Line layer without stroke or transparency."""
        root = built(mutate(lambda s: sheet(s, "Monthly").update(history="line")), "kpi_v3_line")
        panes = ws(root, SALES).findall("table/panes/pane")
        self.assertEqual(panes[1].find("mark").get("class"), "Line")
        self.assertNotIn("has-stroke", marks(panes[1]))


class MonthLetters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_discrete_month_with_letters(self):
        t = ws(self.root, SALES).find("table")
        self.assertTrue(t.findtext("cols").endswith("[tmn:Order Date:ok]"))
        ci = next(c for c in t.iter("column-instance") if c.get("name") == "[tmn:Order Date:ok]")
        self.assertEqual((ci.get("derivation"), ci.get("type")), ("Month-Trunc", "ordinal"))
        fmt = t.find("style/style-rule[@element='label']/format[@attr='text-format']")
        self.assertEqual((fmt.get("field").endswith("[tmn:Order Date:ok]]") or fmt.get("field").endswith(":ok]"),
                          fmt.get("value")), (True, kpi2.MONTH_LETTER))
        self.assertIsNotNone(t.find("style/style-rule[@element='worksheet']/format[@attr='display-field-labels']"))

    def test_header_shown_axis_hidden(self):
        """The month header stays (no display false on Columns), the measure axis stays hidden."""
        t = ws(self.root, SALES).find("table")
        hidden = [f.get("scope") for f in t.iterfind("style/style-rule[@element='axis']/format[@attr='display']")]
        self.assertNotIn("cols", hidden)
        self.assertIn("rows", hidden)

    def test_points_along_discrete_month(self):
        t = ws(self.root, SALES).find("table")
        along = {tc.get("ordering-field") for tc in t.iter("table-calc") if tc.get("ordering-type") == "Field"}
        self.assertTrue(along and all(a.endswith("[tmn:Order Date:ok]") for a in along), along)


class BaseValue(unittest.TestCase):
    def test_card_text(self):
        """'▲ 10.5% | $14.0K Last Month': the base calc in the text, muted, then its word; 'Last Year' vs a year."""
        root = built()
        for name, word in (("Monthly · Sales", " Last Month"), ("Yearly · Units", " Last Year")):
            runs = ws(root, name).findall(".//customized-label/formatted-text/run")
            texts = [r.text for r in runs]
            self.assertEqual(texts[-1], word)
            self.assertEqual(texts[-3], " | ")
            self.assertEqual(runs[-2].get("fontcolor"), COLOR["muted"])
            self.assertNotIn(" MoM", texts)

    def test_numbers(self):
        """The base value is the card's 'previous' (expected.py; pandas in golden/expected)."""
        got = compute(SPEC, DATA)
        self.assertEqual(round(got["Monthly"]["Sales"]["previous"], 2), 13995.54)
        self.assertEqual(got["Yearly"]["Units"]["previous"], 111)

    def test_pill_carries_it(self):
        root = built(mutate(lambda s: sheet(s, "Yearly").update(delta_style="pill")), "kpi_v3_pill")
        texts = [r.text for r in ws(root, "Yearly · Units · Delta").findall(".//customized-label//run")]
        self.assertEqual(texts[-1], " Last Year")


class Legend(unittest.TestCase):
    def test_one_line_in_block_header(self):
        """'● Max ● Min' once under the block's title, each dot in the color of its kind."""
        root = built()
        runs = [(r.get("fontcolor"), r.text) for z in root.iter("zone") for r in z.findall("formatted-text/run")]
        i = runs.index((COLOR["good"].lower(), "● "))
        self.assertEqual(runs[i + 1][1].strip(), "Max")
        self.assertEqual(runs[i + 2], (COLOR["bad"].lower(), "● "))
        self.assertEqual(runs[i + 3][1].strip(), "Min")
        self.assertEqual(sum(1 for _, t in runs if t and t.strip() == "Max"), 1)

    def test_no_legend_without_key(self):
        root = built(mutate(lambda s: sheet(s, "Monthly").pop("history_points_legend")), "kpi_v3_nolegend")
        self.assertFalse([r for r in root.iter("run") if (r.text or "").strip() == "Max"])


class Rejects(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as e:
            built(mutate(fn), "kpi_v3_bad")
        self.assertIn(text, str(e.exception))

    def test_letters_need_sparkline(self):
        self.assertRejected(lambda s: sheet(s, "Yearly").update(history="bar"), "history_months")

    def test_letters_need_month(self):
        self.assertRejected(lambda s: sheet(s, "Yearly")["date"].update(level="week"), "history_months")

    def test_legend_needs_points(self):
        self.assertRejected(lambda s: sheet(s, "Monthly").pop("history_points"), "history_points_legend")

    def test_legend_one_good(self):
        self.assertRejected(lambda s: sheet(s, "Monthly")["measures"][1].update(good="down"), "differ in 'good'")

    def test_legend_needs_title(self):
        self.assertRejected(lambda s: sheet(s, "Monthly").pop("title"), "under the block's title")

    def test_schema(self):
        bad = mutate(lambda s: sheet(s, "Monthly").update(history_months="short"))
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate(bad)


class GateCatchesV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "kpi_v3.json", OUT / "kpi_v3_gate.twbx")

    def assertCaught(self, mutation, text):
        issues = gate.run(repack(mutation, source=self.src))
        hits = [i for i in issues if i.check == "kpi" and text in str(i)]
        self.assertTrue(hits, f"expected [kpi] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def table(r, name=SALES):
        return next(w for w in r.iter("worksheet") if w.get("name") == name).find("table")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_letters_on_continuous_month(self):
        def m(r):
            f = self.table(r).find("style/style-rule[@element='label']/format[@attr='text-format']")
            f.set("field", f.get("field").replace(":ok]", ":qk]"))
        self.assertCaught(m, "month letters")

    def test_opaque_area(self):
        def m(r):
            t = self.table(r, UNITS).find("panes/pane/style/style-rule[@element='mark']/format[@attr='mark-transparency']")
            t.set("value", "255")
        self.assertCaught(m, "is opaque")

    def test_area_without_transparency(self):
        def m(r):
            rule = self.table(r).find("panes/pane[@id='1']/style/style-rule[@element='mark']")
            rule.remove(rule.find("format[@attr='mark-transparency']"))
        self.assertCaught(m, "is opaque")

    def test_legend_color_lies(self):
        def m(r):
            run = next(x for x in r.iter("run") if x.text == "● " and x.get("fontcolor") == COLOR["good"].lower())
            run.set("fontcolor", COLOR["bad"].lower())
        self.assertCaught(m, "points legend '● Max'")

    def test_legend_of_nothing(self):
        def m(r):
            run = next(x for x in r.iter("run") if (x.text or "").strip() == "Min")
            run.text = "Last"
        self.assertCaught(m, "no sparkline marks it")


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """The workbook Desktop 2025.1 re-saved (decisions/054) = the generator's output."""
        import difflib
        out = build_file(SPECS / "kpi_v3.json", OUT / "roundtrip_kpi_v3.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(GOLDEN)
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))

    def test_golden_passes_gate(self):
        self.assertEqual(gate.run(GOLDEN), [])


if __name__ == "__main__":
    unittest.main()
