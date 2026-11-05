"""Insight line, tile notes, inline legend, a table's two row fields and its sort by the row total (decisions/045):
expected from the CSV, the XML, refusals, reconcile next to the phrase, a gate mutation."""
import copy
import csv
import json
import unittest
import zipfile
from collections import defaultdict

from lxml import etree

from tbuilder import expected, gate, insight
from tbuilder.build import build
from test_gate import repack
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "insight.json"
CSV = ROOT / "data" / "sample" / "sales_stores.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    s["datasource"]["path"] = str(CSV)
    return s


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def built(s=None, name="insight"):
    out = build(s or spec(), OUT / "insight_test" / f"{name}.twbx")
    with zipfile.ZipFile(out) as z:
        return out, etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Phrase(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(insight.tokens("Busiest: **[Day] ([N])**; weekend [W]."),
                         [("Busiest: ", False, False), ("Day", True, True), (" (", True, False), ("N", True, True),
                          (")", True, False), ("; weekend ", False, False), ("W", False, True), (".", False, False)])
        self.assertEqual(insight.refs("[A] and [A] or [B]"), ["A", "B"])

    def test_words_next_to_each_number(self):
        values = {"Day": "Thu", "N": 82, "W": 8}
        got = insight.adjacency("Busiest day: **[Day] ([N])**; weekend adds only [W].", values)
        self.assertEqual(got, {"N": (["busiest", "day", "thu"], []), "W": (["weekend", "adds", "only"], [])})

    def test_next_to(self):
        f = {"text": "Busiest day: Thu (82); weekend adds only 8.", "number": "8", "start": 41}
        self.assertTrue(insight.next_to(f, (["weekend", "adds", "only"], [])))
        self.assertFalse(insight.next_to(f, (["per", "analyst"], [])))
        g = {"text": "1 analyst below 60% of average", "number": "60%", "start": 16}
        self.assertFalse(insight.next_to(g, ([], ["of", "total"])))  # 'of' alone is not 'of total'
        self.assertTrue(insight.next_to({"text": "44% of total", "number": "44%", "start": 0}, ([], ["of", "total"])))


class Expected(unittest.TestCase):
    def test_values_from_the_csv(self):
        exp = expected.compute(spec(), CSV)
        by_region = defaultdict(float)
        for r in ROWS:
            by_region[r["Region"]] += float(r["Sales"])
        top = max(by_region, key=by_region.get)
        total = sum(by_region.values())
        got = exp["By Region · Insight"]
        self.assertEqual(got["Top Region"], top)
        self.assertAlmostEqual(got["Top Region Share"], int(by_region[top]) / total)  # INT() in the key
        self.assertEqual(got["City Count"], len({r["City"] for r in ROWS}))
        notes = exp["KPI · Notes"]
        self.assertAlmostEqual(notes["Sales"]["Avg Order"], total / len(ROWS))
        self.assertAlmostEqual(notes["Profit"]["Margin"], sum(float(r["Profit"]) for r in ROWS) / total)

    def test_two_row_fields_and_their_totals(self):
        exp = expected.compute(spec(), CSV)["Detail"]
        cell = sum(float(r["Sales"]) for r in ROWS if r["City"] == "Boston" and r["Channel"] == "Online")
        self.assertAlmostEqual(exp["Boston | East | Online"], cell)
        self.assertAlmostEqual(exp["Boston | East | Total"], sum(float(r["Sales"]) for r in ROWS
                                                                 if r["City"] == "Boston"))
        self.assertAlmostEqual(exp["Total | Online"], sum(float(r["Sales"]) for r in ROWS if r["Channel"] == "Online"))
        self.assertAlmostEqual(exp["Total | Total"], sum(float(r["Sales"]) for r in ROWS))


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.root = built()

    def ws(self, name):
        return next(w for w in self.root.iter("worksheet") if w.get("name") == name)

    def test_insight_sheet(self):
        w = self.ws("By Region · Insight")
        self.assertIsNone(w.find(".//rows").text)
        texts = w.findall(".//encodings/text")
        self.assertEqual(len(texts), 3)
        self.assertTrue(texts[0].get("column").endswith(":nk]"))  # the text calc: discrete (decisions/031)
        runs = w.findall(".//customized-label/formatted-text/run")
        self.assertEqual([r.text for r in runs[1:4:2]], [" leads with ", " of sales; "])
        self.assertEqual((runs[0].get("bold"), runs[0].get("fontcolor")), ("true", "#333333"))
        self.assertEqual({r.get("fontalignment") for r in runs}, {"0"})
        self.assertIsNotNone(w.find(".//customized-tooltip"))  # no tooltip: all on the mark
        vp = next(v for v in self.root.iter("viewpoint") if v.get("name") == "By Region · Insight")
        self.assertEqual(vp.find("zoom").get("type"), "entire-view")

    def test_insight_zone_under_the_header(self):
        zones = list(self.root.iter("zone"))
        z = next(z for z in zones if z.get("name") == "By Region · Insight")
        sheet = next(z for z in zones if z.get("name") == "By Region" and "type-v2" not in z.attrib)
        self.assertEqual(int(z.get("y")) + int(z.get("h")), int(sheet.get("y")))
        style = {f.get("attr"): f.get("value") for f in z.find("zone-style")}
        self.assertEqual((style.get("margin-top", style["margin"]), style.get("margin-bottom", style["margin"])), ("0", "12"))

    def test_tile_note(self):
        runs = self.ws("KPI · Profit").findall(".//customized-label/formatted-text/run")
        self.assertEqual(runs[3].text, "Æ\n")
        self.assertEqual((runs[4].get("bold"), runs[4].get("fontsize")), ("true", "9"))
        self.assertEqual(runs[5].text, " margin")
        self.assertEqual(len(self.ws("KPI · Profit").findall(".//encodings/text")), 2)

    def test_inline_legend(self):
        head = next(z for z in self.root.iter("zone") if z.get("type-v2") == "text"
                    and any(r.text == "Online    " for r in z.iter("run")))
        runs = [(r.text, r.get("fontcolor")) for r in head.iter("run")][-6:]
        self.assertEqual(runs, [("■ ", "#2f4a6d"), ("Online    ", "#898989"), ("■ ", "#5b8db8"),
                                ("Retail    ", "#898989"), ("■ ", "#b3c3d6"), ("Partner", "#898989")])
        self.assertEqual([z for z in self.root.iter("zone") if z.get("type-v2") == "color"], [])  # no legend card

    def test_table_rows_and_sort(self):
        w = self.ws("Detail")
        self.assertRegex(w.find(".//rows").text, r"^\(\[federated\.\w+\]\.\[none:City:nk\] / "
                                                 r"\[federated\.\w+\]\.\[none:Region:nk\]\)$")
        s = w.find(".//computed-sort")
        self.assertEqual((s.get("column").split(".")[-1], s.get("direction"), s.get("using").split(".")[-1]),
                         ("[none:City:nk]", "DESC", "[sum:Sales:qk]"))
        widths = {f.get("field").split(".")[-1]: f.get("value")
                  for f in w.findall(".//style-rule[@element='header']/format[@attr='width']")}
        self.assertEqual(set(widths), {"[none:City:nk]", "[none:Region:nk]"})  # Desktop clipped 'Analyst ..'
        man = self.root.find("document-format-change-manifest")
        self.assertIsNotNone(man.find("SortTagCleanup"))  # Desktop reads computed-sort only under it

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path), [])


class Refusals(unittest.TestCase):
    def fails(self, mutate, text):
        s = spec()
        mutate(s)
        with self.assertRaises(ValueError) as e:
            build(s, OUT / "insight_test" / "refused.twbx")
        self.assertIn(text, str(e.exception))

    def test_refusals(self):
        def set_(name, **kw):
            return lambda s: sheet(s, name).update(kw)
        self.fails(set_("By Region", insight="[Nope] here"), "must be an aggregate calc")
        self.fails(set_("By Region", insight="no calc at all"), "names no [Calc]")
        self.fails(set_("By Region", insight="**[Margin] open"), "unbalanced **")
        self.fails(lambda s: s["calcs"].append({"name": "Row", "formula": "[Sales] * 2"}) or
                   sheet(s, "By Region").update(insight="[Row] rows"), "must be an aggregate calc")
        self.fails(lambda s: [sheet(s, "By Region").pop(k) for k in ("title", "subtitle")],
                   "stands under the block header")
        self.fails(lambda s: sheet(s, "By Region").update(measure={"field": "Sales", "note": "[Margin]"}),
                   "a line under a KPI tile")
        self.fails(lambda s: s["fields"]["Channel"].pop("color"), "fields.Channel.color")
        self.fails(lambda s: sheet(s, "Detail").update(rows=["City", "Channel"]), "must be different fields")


class GateCatches(unittest.TestCase):
    def test_sheet_touching_the_insight_line(self):
        """The sheet under an insight line has margin-top 0: the line's margin-bottom keeps the gap."""
        path, _ = built(name="gate_src")

        def mutate(root):
            z = next(z for z in root.iter("zone") if z.get("name") == "By Region · Insight")
            etree.SubElement(z.find("zone-style"), "format", attr="margin-bottom", value="0")
        issues = gate.run(repack(mutate, source=path))
        self.assertTrue(any("margin-top 0" in str(i) and "By Region" in str(i) for i in issues), issues)


class Reconcile(unittest.TestCase):
    def test_phrase_numbers_win_next_to_their_words(self):
        from tbuilder import reconcile
        s = spec()
        exp = expected.compute(s, CSV)
        ents = reconcile.entries(s, exp)
        share = exp["By Region · Insight"]["Top Region Share"]
        page = {"texts": [{"text": f"East leads with {share * 100:.1f}% of sales; 12 cities in view.",
                           "box": [0, 0, 10, 10], "up": []}]}
        r = reconcile.check(copy.deepcopy(s), CSV.parent, page)
        st = {f["number"]: (f["status"], f.get("workbook", "")) for f in r["facts"]}
        self.assertEqual(st[f"{share * 100:.1f}%"][0], "matched", st)
        self.assertIn("By Region insight", st["12"][1])
        self.assertTrue(any("phrase" in e for e in ents))


if __name__ == "__main__":
    unittest.main()
