"""HTML -> outline -> evidence on the synthetic fixture (needs Chrome; skipped otherwise)."""
import unittest

from tbuilder import html_outline
from tbuilder.match import match
from test_roundtrip import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "sales_dashboard.html"
CSV = ROOT / "data" / "sample" / "sales.csv"

try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False


class StyleProfile(unittest.TestCase):
    def test_reads_the_css_block(self):
        self.assertEqual(html_outline.style_profile("<style>/* tb profile-css my_style */\n:root {}</style>"), "my_style")
        self.assertIsNone(html_outline.style_profile("<style>:root {}</style>"))


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class FixtureOutline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.o = html_outline.outline(FIXTURE)
        cls.ev = {e["id"]: e for e in match(cls.o, CSV) if e["id"] != "control"}
        cls.controls = [e for e in match(cls.o, CSV) if e["id"] == "control"]
        cls.by_kind = {}
        for b in cls.o["blocks"]:
            cls.by_kind.setdefault(b["kind"], []).append(b)

    def test_blocks(self):
        self.assertEqual({k: len(v) for k, v in self.by_kind.items()},
                         {"kpi": 3, "bars": 1, "svg": 1, "table": 1})
        self.assertEqual(sorted(b["text"] for b in self.by_kind["kpi"]), ["2,610", "224,710", "23,550"])
        self.assertEqual(self.by_kind["bars"][0]["orientation"], "horizontal")

    def test_layout(self):
        kind = {b["id"]: b["kind"] for b in self.o["blocks"]}
        rows = self.o["layout"]["rows"]
        self.assertEqual([kind[i] for i in rows[0]["cols"]], ["kpi", "kpi", "kpi"])
        self.assertEqual([kind[i] for i in rows[1]["cols"]], ["bars", "svg"])
        self.assertEqual(kind[rows[2]], "table")

    def test_headings(self):
        self.assertEqual(self.by_kind["bars"][0]["heading"], "SALES BY REGION")
        self.assertEqual(self.by_kind["svg"][0]["heading"], "MONTHLY SALES TREND")

    def test_palette(self):
        self.assertEqual(self.o["palette"]["--accent"], "#4FB3FF")

    def test_kpi_evidence(self):
        got = {}
        for b in self.by_kind["kpi"]:
            top = self.ev[b["id"]]["candidates"][0]
            got[b["text"]] = (top["field"], top["agg"])
        self.assertEqual(got, {"224,710": ("Sales", "sum"), "23,550": ("Profit", "sum"), "2,610": ("Quantity", "sum")})

    def test_bar_evidence(self):
        e = self.ev[self.by_kind["bars"][0]["id"]]
        self.assertEqual(e["candidates"][0]["field"], "Region")
        n, cands = e["value_candidates"][0]
        self.assertEqual((cands[0]["field"], cands[0]["agg"], cands[0]["where"]), ("Sales", "sum", "Region = South"))

    def test_table_evidence(self):
        e = self.ev[self.by_kind["table"][0]["id"]]
        self.assertEqual(e["row_candidates"][0]["field"], "Region")
        self.assertEqual(e["col_candidates"][0]["field"], "Category")
        cell, cands = e["cell_candidates"][0]
        self.assertEqual(cands[0]["where"], "Region = East AND Category = Furniture")

    def test_axis_evidence(self):
        e = self.ev[self.by_kind["svg"][0]["id"]]
        self.assertEqual(e["candidates"], [{"field": "Order Date", "level": "month"}])

    def test_control_evidence(self):
        self.assertEqual(self.controls[0]["candidates"][0]["field"], "Region")
        sel = next(c for c in self.o["controls"] if c["kind"] == "select")  # the state at load (decisions/038)
        self.assertEqual((sel["selected"], sel["multiple"]), (["All"], False))

    def test_spec_reproduces_every_html_number(self):
        """End to end: numbers printed in the HTML == what the spec's sheets will show."""
        from tbuilder import expected, spec
        from tbuilder.match import parse_number
        s = spec.load(ROOT / "specs" / "fixture_sales.json")
        e = expected.compute(s, CSV)
        shown = lambda t: parse_number(t)[0]
        kpi = {round(v) for v in e["Sales Pulse 2025"].values()}
        self.assertEqual({shown(b["text"]) for b in self.by_kind["kpi"]}, kpi)
        bars = {k: round(v) for k, v in e["Sales by Region"].items()}
        for label in self.by_kind["bars"][0]["labels"]:
            region, number = label.split(" ", 1)
            self.assertEqual(bars[region], shown(number))
        table = self.by_kind["table"][0]
        cells = {k: round(v) for k, v in e["Sales by Region and Category"].items()}
        for row in table["sample"]:
            for i, c in enumerate(row[1:], 1):
                self.assertEqual(cells[f"{row[0]} | {table['headers'][i]}"], shown(c))


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class AbsoluteLayout(unittest.TestCase):
    """acceptance/bi_export: every visual is an absolutely positioned div (decisions/108)."""

    @classmethod
    def setUpClass(cls):
        cls.o = html_outline.outline(ROOT / "acceptance" / "bi_export" / "bi-export.html")

    def test_blocks_per_visual(self):
        kinds = sorted(b["kind"] for b in self.o["blocks"])
        self.assertEqual(kinds, ["kpi"] * 4 + ["svg", "svg", "table"])

    def test_no_overlap(self):
        bl = self.o["blocks"]
        for i, a in enumerate(bl):
            for b in bl[i + 1:]:
                ax, ay, aw, ah = a["box"]
                bx, by, bw, bh = b["box"]
                self.assertFalse(ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah, (a["id"], b["id"]))
        self.assertNotIn("overlap", str(self.o["layout"]))

    def test_wrapper_with_visuals_is_not_bars(self):
        raw = dict(self.o, svgs=[{"box": [10, 10, 50, 50]}], canvases=[], tables=[], lists=[], images=[], numbers=[],
                   headings=[], bar_groups=[{"box": [0, 0, 100, 100]}, {"box": [0, 200, 100, 50]}])
        blocks = html_outline.build_outline(raw)["blocks"]
        self.assertEqual(sorted(b["kind"] for b in blocks), ["bars", "svg"])
        self.assertEqual([b["box"] for b in blocks if b["kind"] == "bars"], [[0, 200, 100, 50]])


if __name__ == "__main__":
    unittest.main()
