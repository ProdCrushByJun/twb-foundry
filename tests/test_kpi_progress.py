"""KPI progress against a target (decisions/155, reference progress bars): the card text
'103% of $15.0K target' and a bar under it, the fill over a track as a dual axis on one fixed 0..1 axis."""
import copy
import csv
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

SPEC = json.loads((SPECS / "kpi_progress.json").read_text(encoding="utf-8"))
DATA = SPECS / SPEC["datasource"]["path"]
GOLDEN = ROOT / "golden" / "golden_kpi_progress_2025_1.twbx"
SALES, UNITS, THIN = "Monthly · Sales · Progress", "Monthly · Units · Progress", "Yearly · Sales · Progress"
PLAN = {  # a target from a column: Plan of the current month (sales_plan.csv)
    "version": 1, "datasource": {"type": "csv", "path": "../data/sample/sales_plan.csv"},
    "sheets": [{"name": "Plan", "type": "kpi", "style": "cards", "title": "Sales **against plan**",
                "date": {"field": "Month", "level": "month"},
                "measures": [{"field": "Sales", "format": "currency_k", "target": {"field": "Plan"}}]}],
    "dashboard": {"name": "Plan Dashboard", "title": "Plan", "theme": "cards", "width": 800, "height": 400,
                  "grid": [["Plan"]]}}


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec=SPEC, name="kpi_progress_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def marks(pane):
    return {f.get("attr"): f.get("value") for f in pane.iterfind("style/style-rule[@element='mark']/format")}


def calc(root, caption):
    return next(c for c in root.iter("column") if c.get("caption") == caption)


class Numbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = compute(SPEC, DATA)

    def test_constant_target(self):
        """Dec 2025: Sales 15 462 of 15 000 = 103 %, the fill full; Profit 825 of 1 200 = 69 %."""
        s, p = self.exp["Monthly"]["Sales"], self.exp["Monthly"]["Profit"]
        self.assertEqual(s["target"], 15000)
        self.assertAlmostEqual(s["progress"], 15462.12 / 15000)
        self.assertEqual(s["fill"], 1)
        self.assertAlmostEqual(p["progress"], 825.38 / 1200)
        self.assertAlmostEqual(p["fill"], p["progress"])

    def test_year(self):
        y = self.exp["Yearly"]
        self.assertAlmostEqual(y["Sales"]["progress"], 178561.65 / 200000)
        self.assertAlmostEqual(y["Profit"]["progress"], 14231.75 / 15000)

    def test_field_target(self):
        """target.field: the column over the current period, as the card's value."""
        path = SPECS / PLAN["datasource"]["path"]
        with open(path, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["Month"] == "2025-12-01"]
        sales, plan = (sum(float(r[k]) for r in rows) for k in ("Sales", "Plan"))
        got = compute(PLAN, path)["Plan"]["Sales"]
        self.assertAlmostEqual(got["target"], plan)
        self.assertAlmostEqual(got["progress"], sales / plan)


class Calcs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_formulas(self):
        f = lambda cap: calc(self.root, cap).find("calculation").get("formula")  # noqa: E731
        self.assertEqual(f("Monthly · Sales · Target"), "MIN(15000)")
        self.assertIn("MAX(MIN(", f("Monthly · Sales · Progress Fill"))
        self.assertIn(">= 1", f("Monthly · Sales · Target Met"))

    def test_field_target_formula(self):
        root = built(PLAN, "kpi_progress_plan")
        self.assertIn("IF [", calc(root, "Plan · Sales · Target").find("calculation").get("formula"))
        self.assertEqual(gate.check_kpi_progress(root), [])

    def test_card_text(self):
        """'103% of $15.0K target': the share bold, then the target."""
        runs = [r.text for r in ws(self.root, "Monthly · Sales").iter("run")]
        self.assertIn(" of ", runs)
        self.assertEqual(runs[-1], " target")
        bold = [r for r in ws(self.root, "Monthly · Sales").iter("run") if r.get("bold") == "true"]
        self.assertIn(calc(self.root, "Monthly · Sales · Progress").get("name")[1:-1], bold[-1].text)


class Bar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_dual_axis(self):
        """The constant first (the track under), the fill folded onto its fixed 0..1 axis, both hidden."""
        t = ws(self.root, SALES).find("table")
        self.assertFalse(t.findtext("rows"))
        self.assertTrue(t.findtext("cols").startswith("(") and " + " in t.findtext("cols"))
        enc = t.findall("style/style-rule[@element='axis']/encoding")
        self.assertEqual((enc[0].get("range-type"), enc[0].get("min"), enc[0].get("max")), ("fixed", "0", "1"))
        self.assertEqual((enc[1].get("fold"), enc[1].get("synchronized")), ("true", "true"))
        hidden = [f for f in t.iterfind("style/style-rule[@element='axis']/format[@attr='display']")]
        self.assertEqual([f.get("value") for f in hidden], ["false", "false"])

    def test_layers(self):
        panes = ws(self.root, SALES).findall("table/panes/pane")
        self.assertEqual([p.find("mark").get("class") for p in panes], ["Bar"] * 3)
        track, fill = marks(panes[1]), marks(panes[2])
        self.assertEqual((track["mark-color"], track["size"]), (COLOR["track"], kpi2.BAR_SIZE))
        self.assertEqual(fill["size"], kpi2.BAR_SIZE)
        self.assertIsNotNone(panes[2].find("encodings/color"))

    def test_thin(self):
        track = marks(ws(self.root, THIN).findall("table/panes/pane")[1])
        self.assertEqual(track["size"], kpi2.TRACK_SIZE["thin"])

    def test_palette(self):
        """Met: good, bad for good 'down' (Units over 100 is an overrun); short of it: the accent."""
        maps = {}
        for e in self.root.iterfind("datasources/datasource/style/style-rule[@element='mark']/encoding"):
            maps[e.get("field")] = {m.findtext("bucket"): m.get("to") for m in e.findall("map")}
        sales = next(v for k, v in maps.items() if calc(self.root, "Monthly · Sales · Target Met").get("name")[1:-1]
                     in k)
        units = next(v for k, v in maps.items() if calc(self.root, "Monthly · Units · Target Met").get("name")[1:-1]
                     in k)
        self.assertEqual((sales["true"], sales["false"]), (COLOR["good"], COLOR["accent"]))
        self.assertEqual(units["true"], COLOR["bad"])

    def test_zone_under_text(self):
        """The bar's zone under the value text, as wide as it, PROGRESS_PX inside its margins."""
        db = next(self.root.iter("dashboard"))
        z = {e.get("name"): e for e in db.iter("zone") if e.get("name")}
        text, bar = z["Monthly · Sales"], z[SALES]
        self.assertEqual((text.get("x"), text.get("w")), (bar.get("x"), bar.get("w")))
        self.assertEqual(int(text.get("y")) + int(text.get("h")), int(bar.get("y")))
        self.assertEqual(round(int(bar.get("h")) * 800 / 100000), kpi2.PROGRESS_PX + 8)

    def test_no_legend(self):
        """The met flag is no color legend: the card text names the target."""
        cards = [c for c in self.root.iter("card") if c.get("type") == "color"]
        self.assertFalse([c for c in cards if "Target Met" in (c.get("param") or "")])


class OptIn(unittest.TestCase):
    def test_without_target_no_progress(self):
        def off(s):
            for x in s["sheets"]:
                x.pop("progress", None)
                for m in x["measures"]:
                    m.pop("target")
        root = built(mutate(off), "kpi_progress_off")
        self.assertFalse([w for w in root.iter("worksheet") if w.get("name").endswith("· Progress")])
        self.assertFalse([c for c in root.iter("column") if "Target" in (c.get("caption") or "")])


class Rejects(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as e:
            built(mutate(fn), "kpi_progress_bad")
        self.assertIn(text, str(e.exception))

    def test_every_measure(self):
        self.assertRejected(lambda s: sheet(s, "Monthly")["measures"][1].pop("target"), "give every measure")

    def test_progress_needs_target(self):
        self.assertRejected(lambda s: [m.pop("target") for m in sheet(s, "Yearly")["measures"]],
                            "give the measures a 'target'")

    def test_not_with_pill(self):
        self.assertRejected(lambda s: sheet(s, "Monthly").update(delta_style="pill"), "pill and the progress bar")

    def test_field_not_number(self):
        self.assertRejected(lambda s: sheet(s, "Monthly")["measures"][0].update(target={"field": "Region"}),
                            "is not a number")

    def test_only_cards(self):
        self.assertRejected(lambda s: s["sheets"].append(
            {"name": "Tiles", "type": "kpi", "style": "tiles", "measures": [{"field": "Sales", "target":
                                                                             {"value": 1}}]}), "KPI cards measures")

    def test_schema(self):
        for fn in (lambda s: sheet(s, "Monthly")["measures"][0].update(target={"value": 0}),
                   lambda s: sheet(s, "Monthly")["measures"][0].update(target={"value": 5, "agg": "sum"}),
                   lambda s: sheet(s, "Yearly").update(progress="ring")):
            with self.assertRaises(spec_mod.SpecError):
                spec_mod.validate(mutate(fn))


class GateCatchesProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "kpi_progress.json", OUT / "kpi_progress_gate.twbx")

    def assertCaught(self, mutation, text):
        issues = gate.run(repack(mutation, source=self.src))
        hits = [i for i in issues if i.check == "kpi" and text in str(i)]
        self.assertTrue(hits, f"expected [kpi] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def table(r, name=SALES):
        return next(w for w in r.iter("worksheet") if w.get("name") == name).find("table")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_track_over_fill(self):
        def m(r):
            cols = self.table(r).find("cols")
            a, b = cols.text[1:-1].split(" + ")
            cols.text = f"({b} + {a})"
        self.assertCaught(m, "is drawn over the fill")

    def test_free_track_axis(self):
        def m(r):
            e = self.table(r).find("style/style-rule[@element='axis']/encoding")
            for k in ("range-type", "min", "max"):
                del e.attrib[k]
        self.assertCaught(m, "is not fixed 0..1")

    def test_fill_on_own_axis(self):
        def m(r):
            e = self.table(r, UNITS).findall("style/style-rule[@element='axis']/encoding")[1]
            del e.attrib["synchronized"]
        self.assertCaught(m, "not folded onto the track's")

    def test_met_without_palette(self):
        def m(r):
            name = next(c for c in r.iter("column") if c.get("caption") == "Monthly · Sales · Target Met").get("name")
            for ds in r.iterfind("datasources/datasource"):
                for rule in ds.iterfind("style/style-rule[@element='mark']"):
                    for e in list(rule):
                        if name[1:-1] in (e.get("field") or ""):
                            rule.remove(e)
        self.assertCaught(m, "no palette map")


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """The workbook Desktop 2025.1 re-saved (resave CLEAN) = the generator's output."""
        import difflib
        out = build_file(SPECS / "kpi_progress.json", OUT / "roundtrip_kpi_progress.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(GOLDEN)
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))

    def test_golden_passes_gate(self):
        self.assertEqual(gate.run(GOLDEN), [])


if __name__ == "__main__":
    unittest.main()
