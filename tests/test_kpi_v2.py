"""KPI v2 (todo 8.2, decisions/037): abs | % change, pill, sparkline, sign marker, period line, Data as of."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import gate, kpi2, reconcile
from tbuilder.build import build, build_file
from tbuilder.design import COLOR, MARKER_PX
from tbuilder.expected import compute
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS, canon, normalize, read_twbx

SPEC = json.loads((SPECS / "kpi_v2.json").read_text(encoding="utf-8"))
DATA = SPECS / SPEC["datasource"]["path"]


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec=SPEC, name="kpi_v2_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name and not z.get("type-v2"))


def calc(root, caption):
    return next(c for c in root.find("datasources").iter("column") if c.get("caption") == caption)


def run_texts(w, tag="customized-label"):
    return [r.text for r in w.iter("run") if r in list(w.find(f".//{tag}/formatted-text"))]


class Calcs(unittest.TestCase):
    def test_generated_formulas(self):
        got = {c["name"]: c for c in kpi2.calcs(SPEC)}
        self.assertEqual(got["Monthly · Sales · Diff"]["formula"],
                         "[Monthly · Sales · Current] - [Monthly · Sales · Previous]")
        self.assertEqual(got["Monthly · Sales · Diff Good"]["format"], '*▲ "$"#,##0,.0K;▼ "$"#,##0,.0K')
        self.assertEqual(got["Monthly · Profit · Diff Bad"]["format"], "*▲ #,##0;▼ #,##0")
        self.assertIn("<= 0", got["Monthly · Units · Diff Good"]["formula"])  # good: down
        self.assertEqual(got["Monthly · Units · Good Sign"]["formula"], "[Monthly · Units · Change] <= 0")
        self.assertIn("Yearly · Sales · Good Fill", got)
        self.assertNotIn("Yearly · Sales · Diff", got)  # Yearly keeps the percent change
        self.assertEqual(got["Monthly · Base Period"]["formula"],
                         "DATEADD('month', -1, DATETRUNC('month', [Last Order Date]))")
        self.assertEqual(got["Data as of Order Date"]["formula"], "{FIXED : MAX([Order Date])}")

    def test_expected_numbers(self):
        """Hand-checked on data/sample/sales_2y.csv: Dec 2025 against Nov 2025 and Dec 2024."""
        got = compute(SPEC, DATA)
        m = got["Monthly"]
        self.assertAlmostEqual(m["Sales"]["diff"], 1466.58, places=2)  # 15 462,12 - 13 995,54
        self.assertAlmostEqual(m["Profit"]["diff"], -432.15, places=2)
        self.assertEqual(m["Units"]["diff"], 2)  # 104 - 102
        self.assertNotIn("diff", got["Yearly"]["Sales"])
        self.assertEqual(got["Monthly · Sales · History · Points"],
                         {"max": 17285.09, "min": 5612.36, "last": 15462.12})
        self.assertEqual(got["Monthly · Units · History · Points"], {"max": 139.0, "min": 73.0, "last": 104.0})
        self.assertEqual(got["Monthly · Period Line"], {"period": "2025-12-01", "base": "2025-11-01"})
        self.assertEqual(got["KPI v2 · Data as of"], "2025-12-31")

    def test_reconcile_shows_diff_and_history_points(self):
        ents = reconcile.entries(SPEC, compute(SPEC, DATA))
        parts = {(e["sheet"], e["tags"][0], e.get("part")): e["value"] for e in ents}
        self.assertAlmostEqual(parts[("Monthly", "Sales", "diff")], 1466.58, places=2)
        self.assertEqual(parts[("Monthly", "Sales", "history max")], 17285.09)
        self.assertEqual(parts[("Monthly", "Sales", "history last")], 15462.12)
        self.assertNotIn(("Monthly", "Sales", "history min"), parts)  # not labelled on the sparkline


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_abs_pct_change_line(self):
        texts = run_texts(ws(self.root, "Monthly · Sales"))
        self.assertIn(" | ", texts)
        self.assertEqual(texts[-1], " MoM")
        self.assertEqual(calc(self.root, "Monthly · Sales · Change Good").get("default-format"), "*0.0%;0.0%")
        self.assertEqual(calc(self.root, "Yearly · Sales · Change Good").get("default-format"), "*▲ 0.0%;▼ 0.0%")

    def test_pill(self):
        value = run_texts(ws(self.root, "Yearly · Sales"))
        self.assertFalse(any(t and "vs PY" in t for t in value))  # the change left the value text
        pill = ws(self.root, "Yearly · Sales · Delta")
        self.assertBarFills(pill, "cols")
        cell = {f.get("attr"): f.get("value") for f in pill.findall(".//pane/style/style-rule[@element='cell']/format")}
        self.assertEqual(cell, {"text-align": "center", "vertical-align": "center"})  # the text in the bar's middle
        runs = list(pill.find(".//customized-label/formatted-text"))
        self.assertTrue(all(r.get("bold") == "true" for r in runs))
        self.assertEqual([r.get("fontcolor") for r in runs[:2]], [COLOR["good_text"], COLOR["bad_text"]])
        color = pill.find(".//encodings/color").get("column").split("].", 1)[1]
        maps = {m.get("to") for e in self.root.iter("encoding") if e.get("field") == color for m in e.iter("map")}
        self.assertEqual(maps, {COLOR["good_fill"], COLOR["bad_fill"]})
        # the pill fits its text and the rest of its row is an empty zone
        z = zone(self.root, "Yearly · Sales · Delta")
        self.assertLess(int(z.get("w")), int(zone(self.root, "Yearly · Sales").get("w")))

    def test_marker_4px(self):
        width = SPEC["dashboard"]["width"]
        for name in ("Monthly · Sales · Marker", "Monthly · Profit · Marker", "Yearly · Profit · Marker"):
            z = zone(self.root, name)
            st = {f.get("attr"): int(f.get("value")) for f in z.findall("zone-style/format")
                  if f.get("attr").startswith("margin")}
            left, right = st.get("margin-left", st["margin"]), st.get("margin-right", st["margin"])
            self.assertEqual(round(int(z.get("w")) * width / 100000) - left - right, MARKER_PX, name)
            self.assertBarFills(ws(self.root, name), "rows")

    def assertBarFills(self, w, shelf):
        """decisions/063: a Bar of MIN(1) on a fixed, hidden 0..1 axis, at the reference's size (a Square without
        axes is a dot in Desktop)."""
        table = w.find("table")
        self.assertEqual(w.find(".//mark").get("class"), "Bar")
        self.assertEqual(w.find(".//mark-sizing").get("mark-sizing-setting"), "marks-scaling-off")
        ref = table.findtext(shelf)
        self.assertIsNone(table.find("cols" if shelf == "rows" else "rows").text)
        inst = ref.split("].", 1)[1][1:-1].split(":")[1]
        self.assertEqual(next(c for c in self.root.find("datasources").iter("column")
                              if c.get("name") == f"[{inst}]").find("calculation").get("formula"), "MIN(1)")
        axis = table.find("style/style-rule[@element='axis']")
        enc = axis.find("encoding")
        self.assertEqual((enc.get("field"), enc.get("scope"), enc.get("range-type"), enc.get("min"), enc.get("max")),
                         (ref, shelf, "fixed", "0", "1"))  # an integer axis: as Desktop saves it
        self.assertEqual(axis.find(f"format[@attr='display'][@field='{ref}']").get("value"), "false")
        self.assertEqual(w.find(".//pane/style/style-rule[@element='mark']/format[@attr='size']").get("value"),
                         kpi2.BAR_SIZE)

    def test_sparkline(self):
        w = ws(self.root, "Monthly · Sales · History")
        self.assertEqual(w.find(".//mark").get("class"), "Automatic")
        self.assertIsNone(w.find(".//mark-sizing"))
        self.assertIsNone(w.find(".//label-data"))
        self.assertIsNone(w.find(".//format[@attr='mark-labels-mode']"))
        label = calc(self.root, "Monthly · Sales · History · Label")
        self.assertEqual(label.find("calculation").get("formula"),
                         "IF SUM([Sales]) = WINDOW_MAX(SUM([Sales])) OR LAST() = 0 THEN SUM([Sales]) END")
        self.assertEqual(calc(self.root, "Monthly · Units · History · Label").get("datatype"), "integer")
        ci = [c for c in w.iter("column-instance") if c.get("column") == label.get("name")]
        self.assertEqual(ci[0].find("table-calc").get("ordering-field").split("].", 1)[1], "[tmn:Order Date:qk]")
        self.assertIsNotNone(w.find(".//reference-line"))  # history_reference avg over the line

    def test_period_line_and_data_as_of(self):
        texts = run_texts(ws(self.root, "Monthly · Period Line"))
        self.assertEqual(texts[1], " compared to ")
        z = zone(self.root, "Data As Of")
        self.assertEqual((z.get("fixed-size"), z.get("is-fixed")), ("200", "true"))
        self.assertEqual(run_texts(ws(self.root, "Data As Of"))[0], "Data as of ")
        self.assertEqual(calc(self.root, "Data as of Order Date").get("default-format"), "*dd mmm yyyy")
        # the period line is under the header row, across the dashboard
        head = next(z for z in self.root.iter("zone") if z.get("type-v2") == "layout-flow" and z.get("param") == "horz")
        line = zone(self.root, "Monthly · Period Line")
        self.assertEqual(int(line.get("y")), int(head.get("y")) + int(head.get("h")))

    def test_no_legend_for_sign_flags(self):
        self.assertFalse([z for z in self.root.iter("zone") if z.get("type-v2") == "color"])


class Options(unittest.TestCase):
    def test_refused(self):
        cases = [
            (lambda s: sheet(s, "Monthly").update(history_color="change"), "line history has one color"),
            (lambda s: sheet(s, "Yearly").update(period_line=True), "spelled once"),
            (lambda s: s["dashboard"].update(data_as_of="Region"), "not a date column"),
            (lambda s: [s["dashboard"].pop(k) for k in ("title", "subtitle")], "dashboard header row"),
        ]
        for fn, text in cases:
            with self.subTest(text):
                with self.assertRaisesRegex(ValueError, text):
                    built(mutate(fn), "kpi_v2_refused")

    def test_only_on_cards(self):
        spec = mutate(lambda s: sheet(s, "Yearly").update(style="tiles"))
        for k in ("date", "compare"):
            sheet(spec, "Yearly").pop(k)
        with self.assertRaisesRegex(ValueError, "only apply to style 'cards'"):
            built(spec, "kpi_v2_refused")

    def test_plain_card_without_options(self):
        """Without the options a card is the card of decisions/013: four lines, bars, no extra sheets."""
        spec = mutate(lambda s: [sheet(s, "Yearly").pop(k) for k in ("delta_style", "marker")])
        root = built(spec, "kpi_v2_plain")
        names = [w.get("name") for w in root.iter("worksheet") if w.get("name").startswith("Yearly")]
        self.assertEqual(names, ["Yearly · Sales", "Yearly · Sales · History", "Yearly · Profit",
                                 "Yearly · Profit · History"])
        self.assertEqual(ws(root, "Yearly · Sales · History").find(".//mark").get("class"), "Bar")


class GateCatchesKpi(unittest.TestCase):
    """Mutations of the KPI v2 workbook."""

    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "kpi_v2.json", OUT / "kpi_v2_gate.twbx")

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def flag(r, sheet):
        w = next(w for w in r.iter("worksheet") if w.get("name") == sheet)
        return w.find(".//encodings/color").get("column").split("].", 1)[1]

    @staticmethod
    def palette(r, inst):
        return next(e for e in r.iter("encoding") if e.get("field") == inst and e.get("attr") == "color")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_flag_without_palette(self):
        def m(r):
            e = self.palette(r, self.flag(r, "Monthly · Sales · Marker"))
            e.getparent().remove(e)
        self.assertCaught(repack(m, source=self.src), "kpi", "has no palette map")

    def test_flag_without_column_instance(self):
        def m(r):
            inst = self.flag(r, "Monthly · Sales · Marker")
            ds = self.palette(r, inst).getparent().getparent().getparent()
            ds.remove(next(c for c in ds.findall("column-instance") if c.get("name") == inst))
        self.assertCaught(repack(m, source=self.src), "kpi", "no column-instance")

    def test_pill_in_full_colors(self):
        def m(r):
            e = self.palette(r, self.flag(r, "Yearly · Sales · Delta"))
            for mp in e.findall("map"):
                mp.set("to", COLOR["good"] if mp.findtext("bucket") == "true" else COLOR["bad"])
        self.assertCaught(repack(m, source=self.src), "kpi", "is not a pale fill token")

    def test_marker_too_wide(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("name") == "Monthly · Profit · Marker")
            z.set("w", str(int(z.get("w")) * 3))
        self.assertCaught(repack(m, source=self.src), "kpi", "sign marker is")

    def test_sparkline_label_without_compute_using(self):
        def m(r):
            w = next(w for w in r.iter("worksheet") if w.get("name") == "Monthly · Sales · History")
            for ci in w.iter("column-instance"):
                for tc in ci.findall("table-calc"):
                    ci.remove(tc)
        self.assertCaught(repack(m, source=self.src), "tablecalc", "has no compute-using")

    def test_pill_as_a_square_without_axes(self):
        """The form of decisions/037 that Desktop draws as a dot in the middle of the zone (061, 063)."""
        def m(r):
            w = next(w for w in r.iter("worksheet") if w.get("name") == "Yearly · Sales · Delta")
            w.find(".//mark").set("class", "Square")
            w.find("table/cols").text = None
        self.assertCaught(repack(m, source=self.src), "kpi", "pill is not a Bar on an axis")

    def test_marker_on_a_free_axis(self):
        def m(r):
            w = next(w for w in r.iter("worksheet") if w.get("name") == "Monthly · Sales · Marker")
            axis = w.find("table/style/style-rule[@element='axis']")
            axis.remove(axis.find("encoding"))
        self.assertCaught(repack(m, source=self.src), "kpi", "is not fixed 0..1")

    def test_as_of_zone_of_a_missing_sheet(self):
        def m(r):
            next(z for z in r.iter("zone") if z.get("name") == "Data As Of").set("name", "Data As Of 2")
        self.assertTrue(gate.run(repack(m, source=self.src)))


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """golden_kpi_v2 (decisions/063): the full spec with the pill and the marker bars, re-saved by Desktop 2025.1
        (decisions/054) = the generator's output."""
        import difflib
        out = build_file(SPECS / "kpi_v2.json", OUT / "roundtrip_kpi_v2.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(ROOT / "golden" / "golden_kpi_v2_2025_1.twbx")
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))


if __name__ == "__main__":
    unittest.main()
