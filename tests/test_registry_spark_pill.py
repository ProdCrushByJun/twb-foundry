"""Registry spark and pill (todo 7.5, decisions/096): a mini-trend of block glyphs and a status pill in a row."""
import copy
import csv
import json
import unittest
from lxml import etree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

from tbuilder import gate, registry
from tbuilder.build import build
from tbuilder.expected import compute
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry_spark_pill.json").read_text(encoding="utf-8"))
CSV = SPECS / SPEC["datasource"]["path"]
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_spark_pill_test.twbx"
GLYPHS = registry.SPARK_GLYPHS


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def column(spec, label):
    return next(c for c in spec["sheets"][0]["columns"] if registry.label(c) == label)


def csv_rows():
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def quarters():
    return [(2024 + i // 4, i % 4) for i in range(8)]


def glyphs(values):
    """An independent version of the scale: the glyph at (v - low) / (high - low) of the 8, the middle one if flat."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return GLYPHS[len(GLYPHS) // 2] * len(values)
    return "".join(GLYPHS[int((len(GLYPHS) - 1) * (v - lo) / (hi - lo) + 0.5)] for v in values)


class Numbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = compute(SPEC, CSV)["Regions"]

    def test_spark_is_the_quarterly_sums(self):
        by = defaultdict(float)
        for r in csv_rows():
            y, m, _ = r["Order Date"].split("-")
            by[(r["Region"], int(y), (int(m) - 1) // 3)] += float(r["Sales"])
        for region, row in self.got.items():
            self.assertEqual(row["Quarterly sales"], glyphs([by[(region, y, q)] for y, q in quarters()]), region)

    def test_pill_is_the_profit_level(self):
        tot = defaultdict(float)
        for r in csv_rows():
            tot[r["Region"]] += float(r["Profit"])
        want = {k: "High" if v >= 7000 else "OK" if v >= 5000 else "Low" for k, v in tot.items()}
        self.assertEqual({k: v["Profit"] for k, v in self.got.items()}, want)
        self.assertEqual(set(want.values()), {"Low", "OK", "High"})  # the sample covers every level

    def test_an_empty_period_counts_zero(self):
        spec = mutate(lambda s: column(s, "Quarterly sales")["spark"].update({"from": "2025-01-01", "count": 12}))
        spec["sheets"][0]["columns"][1]["spark"]["level"] = "quarter"  # 12 quarters: 2025Q1.. has no rows from 2026
        row = compute(spec, CSV)["Regions"]["East"]["Quarterly sales"]
        self.assertEqual(len(row), 12)
        self.assertEqual(row[4:], GLYPHS[0] * 8)  # nothing after 2025: the lowest glyph

    def test_flat_series_takes_the_middle_glyph(self):
        self.assertEqual(glyphs([5, 5, 5]), GLYPHS[4] * 3)


class Calcs(unittest.TestCase):
    def test_generated(self):
        got = {c["name"]: c["formula"] for c in registry.calcs(SPEC, set())}
        self.assertEqual(got["Regions · Quarterly sales · Period 1"],
                         "ZN(SUM(IF DATETRUNC('quarter', [Order Date]) = #2024-01-01# THEN [Sales] END))")
        self.assertIn("Regions · Quarterly sales · Period 8", got)
        self.assertEqual(got["Regions · Profit · Pill"],
                         'IF SUM([Profit]) >= 7000 THEN "High" ELSEIF SUM([Profit]) >= 5000 THEN "OK" '
                         'ELSE "Low" END')

    def test_spark_periods(self):
        dates = [d.isoformat() for d in registry.spark_periods(column(SPEC, "Quarterly sales"))]
        self.assertEqual(dates[:3] + dates[-1:], ["2024-01-01", "2024-04-01", "2024-07-01", "2025-10-01"])


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.ws = next(w for w in cls.root.iter("worksheet") if w.get("name") == "Regions")

    def panes(self):
        return [p for p in self.ws.findall("table/panes/pane") if p.get("id")]

    def test_pill_is_centred_and_colored_by_its_level(self):
        pill = self.panes()[-1]
        self.assertEqual(pill.find("style/style-rule[@element='cell']/format[@attr='text-align']").get("value"),
                         "center")
        self.assertEqual(pill.find("style/style-rule[@element='cell']/format[@attr='vertical-align']").get("value"),
                         "center")
        self.assertIsNotNone(pill.find("encodings/color"))
        self.assertIsNone(pill.find("style/style-rule[@element='mark']/format[@attr='mark-color']"))
        fills = {m.get("member"): m.text for m in self.root.iter("map")} if False else {}
        colors = {e.get("value") for e in self.root.iter("color") if e.get("value")}
        self.assertTrue(set(registry.pill_fill()[x["color"]] for x in column(SPEC, "Profit")["levels"]) <= colors
                        | {m.get("to") for m in self.root.iter("map")}, fills)

    def test_spark_stays_left_in_the_accent_color(self):
        spark = self.panes()[-2]
        self.assertEqual(spark.find("style/style-rule[@element='cell']/format[@attr='text-align']").get("value"),
                         "left")
        runs = [r.get("fontcolor") for r in spark.iter("run")]
        self.assertIn(registry.COLOR["accent"], runs)

    def test_pill_text_is_light_on_every_fill(self):
        from tbuilder import shell
        for fill in registry.pill_fill().values():
            self.assertGreaterEqual(shell.contrast(registry.COLOR["text"], fill), 4.5, fill)


class Errors(unittest.TestCase):
    def check(self, fn, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            build(mutate(fn), OUT, SPECS)

    def test_options_on_the_wrong_style(self):
        self.check(lambda s: column(s, "Sales").update(spark=column(s, "Quarterly sales")["spark"]), "applies to spark")
        self.check(lambda s: column(s, "Sales").update(levels=column(s, "Profit")["levels"]), "applies to pill")

    def test_style_needs_its_option(self):
        self.check(lambda s: column(s, "Quarterly sales").pop("spark"), "needs 'spark'")
        self.check(lambda s: column(s, "Profit").pop("levels"), "needs 'levels'")

    def test_spark_start_must_be_a_period_start(self):
        self.check(lambda s: column(s, "Quarterly sales")["spark"].update({"from": "2024-02-01"}), "start of a quarter")
        self.check(lambda s: column(s, "Quarterly sales")["spark"].update({"from": "2024-13-01"}), "not a date")

    def test_pill_levels(self):
        def lv(s):
            return column(s, "Profit")["levels"]
        self.check(lambda s: lv(s).__delitem__(slice(1, None)), "(at least 2|too short)")
        self.check(lambda s: lv(s)[0].update({"from": 1}), "lowest level has no")
        self.check(lambda s: lv(s)[2].update({"from": 4000}), "ascending")
        self.check(lambda s: lv(s)[2].update({"label": "OK"}), "distinct labels")

    def test_spark_of_an_aggregate_calc(self):
        def f(s):
            s["calcs"].append({"name": "Sales sum", "formula": "SUM([Sales])", "format": "number"})
            column(s, "Quarterly sales")["measure"] = {"field": "Sales sum"}
        self.check(f, "aggregate")


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))

    def issues(self, fn):
        root = copy.deepcopy(self.root)
        fn(root)
        return [i for c in gate.CHECKS if c is not gate.check_xsd for i in c(root)]

    def ws(self, root):
        return next(w for w in root.iter("worksheet") if w.get("name") == "Regions")

    def test_clean(self):
        self.assertEqual(self.issues(lambda r: None), [])

    def test_spark_label_field_not_on_its_pane(self):
        def f(root):
            enc = self.ws(root).findall("table/panes/pane")[-2].find("encodings")
            enc.remove(enc.findall("text")[0])
        self.assertTrue(any(i.check == "labels" for i in self.issues(f)))

    def pill(self, root):
        return self.ws(root).findall("table/panes/pane")[-1]

    def test_pill_without_its_color_or_label(self):
        for tag in ("color", "text"):
            def f(root, tag=tag):
                enc = self.pill(root).find("encodings")
                enc.remove(enc.find(tag))
            self.assertTrue(any(i.check == "registry" and "pill" in i.message for i in self.issues(f)), tag)

    def test_pill_without_its_palette(self):
        def f(root):
            for ds in root.find("datasources"):
                rule = ds.find("style/style-rule[@element='mark']")
                for e in list(rule) if rule is not None else []:
                    if e.tag == "encoding" and e.get("attr") == "color" and "nk" in e.get("field", ""):
                        rule.remove(e)
        self.assertTrue(any("palette map" in i.message for i in self.issues(f)))

    def test_pill_without_its_column_instance(self):
        def f(root):
            for ds in root.find("datasources"):
                for ci in ds.findall("column-instance"):
                    if ci.get("name", "").endswith(":nk]"):
                        ds.remove(ci)
        self.assertTrue(any("column-instance" in i.message or "references" in i.check or i.check == "references"
                            for i in self.issues(f)))

    def test_string_text_as_quantitative_instance(self):
        def f(root):
            table = self.ws(root).find("table")
            for ci in table.iterfind("view/datasource-dependencies/column-instance"):
                if ci.get("name").endswith(":nk]"):
                    ci.set("name", ci.get("name")[:-4] + ":qk]")
                    ci.set("derivation", "User")
            for text in table.iterfind("panes/pane/encodings/text"):
                if text.get("column").endswith(":nk]"):
                    text.set("column", text.get("column")[:-4] + ":qk]")
        self.assertTrue(any("draws no rows" in i.message for i in self.issues(f)))

    def test_count_of_a_string_field_is_a_number(self):
        def f(root):
            table = self.ws(root).find("table")
            for ci in table.iterfind("view/datasource-dependencies/column-instance"):
                if ci.get("name").endswith(":nk]"):
                    ci.set("name", ci.get("name")[:-4] + ":qk]")
                    ci.set("derivation", "Count")
            for text in table.iterfind("panes/pane/encodings/text"):
                if text.get("column").endswith(":nk]"):
                    text.set("column", text.get("column")[:-4] + ":qk]")
        self.assertFalse(any("draws no rows" in i.message for i in self.issues(f)))

    def test_spark_text_is_a_discrete_instance(self):
        table = self.ws(self.root).find("table")
        texts = [t.get("column") for t in table.iterfind("panes/pane/encodings/text")]
        self.assertTrue(len(texts) >= 2 and all(t.endswith(":nk]") for t in texts[-2:]), texts)


if __name__ == "__main__":
    unittest.main()
