"""Dashboard and block headers (todo 3.0b): text zones as the reference authors build them."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import design
from tbuilder.build import build
from test_roundtrip import SPECS

BASE = json.loads((SPECS / "golden.json").read_text(encoding="utf-8"))
del BASE["block_headers"]  # the default: block headers on
OUT = Path(__file__).resolve().parent.parent / "out" / "headers_test.twbx"


def spec_with(fn):
    spec = copy.deepcopy(BASE)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def runs(zone):
    return [(r.text, {k: v for k, v in r.attrib.items()}) for r in zone.find("formatted-text")]


def text_zones(root):
    return [z for z in root.iter("zone") if z.get("type-v2") == "text"]


def sheet_zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name and "type-v2" not in z.attrib)


class Tokens(unittest.TestCase):
    def test_header_heights(self):
        """Checked in Desktop 2025.1: a smaller line height clips the subtitle (Tableau Book is taller than Arial)."""
        self.assertEqual(design.header_px([(design.FONT["block_title"], 1), (design.FONT["block_subtitle"], 1)]), 61)
        self.assertEqual(design.header_px([(design.FONT["dash_title"], 1), (design.FONT["dash_subtitle"], 1)]), 86)

    def test_text_lines_wraps(self):
        self.assertEqual(design.text_lines("x" * 10, 14, 400), 1)
        self.assertEqual(design.text_lines("x" * 80, 14, 400), 3)


class BlockHeaders(unittest.TestCase):
    def test_title_and_subtitle(self):
        root = built(spec_with(lambda s: sheet(s, "Bar").update(title="**Sales** by Region",
                                                                    subtitle="click to filter")))
        [z] = text_zones(root)
        self.assertEqual(z.get("forceUpdate"), "true")
        self.assertEqual(runs(z), [("Sales", {"bold": "true", "fontsize": "14"}),
                                   (" by Region", {"fontsize": "14"}),
                                   ("Æ\n", {}),
                                   ("click to filter", {"fontcolor": "#898989", "fontsize": "9"})])
        bar = sheet_zone(root, "Bar")
        self.assertEqual(int(bar.get("y")), int(z.get("y")) + int(z.get("h")))  # sheet right under its header
        self.assertEqual((bar.get("x"), bar.get("w")), (z.get("x"), z.get("w")))

    def test_title_only_is_bold(self):
        [z] = text_zones(built(spec_with(lambda s: sheet(s, "Line").update(title="Monthly Sales"))))
        self.assertEqual(runs(z), [("Monthly Sales", {"bold": "true", "fontsize": "14"})])

    def test_subtitle_only(self):
        [z] = text_zones(built(spec_with(lambda s: sheet(s, "Table").update(subtitle="Sales by region"))))
        self.assertEqual(runs(z), [("Sales by region", {"fontcolor": "#898989", "fontsize": "9"})])

    def test_no_header_hides_sheet_title(self):
        root = built(copy.deepcopy(BASE))
        self.assertEqual(text_zones(root), [])
        sheets = [z for z in root.iter("zone") if z.get("name") and "type-v2" not in z.attrib]
        self.assertEqual({z.get("show-title") for z in sheets}, {"false"})
        self.assertIsNone(root.find("worksheets/worksheet/layout-options"))

    def test_title_goes_to_text_zone_not_worksheet(self):
        root = built(spec_with(lambda s: sheet(s, "Line").update(title="Monthly Sales")))
        self.assertIsNone(root.find("worksheets/worksheet/layout-options"))

    def test_sheets_in_a_row_start_level(self):
        def f(s):
            sheet(s, "Bar").update(title="Sales", subtitle="click to filter")  # row 1: KPI has no header
            sheet(s, "Line").update(title="Trend")  # row 2: one line each, different sizes
            sheet(s, "Table").update(subtitle="by region and category")
        root = built(spec_with(f))
        kpi, bar = sheet_zone(root, "KPI"), sheet_zone(root, "Bar")
        line, table = sheet_zone(root, "Line"), sheet_zone(root, "Table")
        bar_head = next(z for z in text_zones(root) if z.get("x") == bar.get("x") and z.get("y") == kpi.get("y"))
        self.assertEqual(int(bar.get("y")), int(kpi.get("y")) + int(bar_head.get("h")))
        self.assertEqual(int(kpi.get("h")), int(bar.get("h")) + int(bar_head.get("h")))  # no header: full height
        self.assertEqual(line.get("y"), table.get("y"))
        row2 = sorted((z for z in text_zones(root) if z.get("y") != kpi.get("y")), key=lambda z: int(z.get("x")))
        self.assertEqual(len({z.get("y") for z in row2}), 1)  # titles level: each header keeps its own height
        trend, hint = row2
        band_px = design.header_px([(design.FONT["block_title"], 1)], design.SPACE["block_margin"],
                                   design.SPACE["header_gap"])  # the taller of the two headers
        self.assertEqual(int(trend.get("h")), round(band_px * 100000 / 800))
        self.assertEqual(int(line.get("y")), int(trend.get("y")) + int(trend.get("h")))
        self.assertLess(int(hint.get("h")), int(trend.get("h")))
        [spacer] = [z for z in root.iter("zone") if z.get("type-v2") == "empty"]  # under the shorter header
        self.assertEqual((spacer.get("x"), spacer.get("w")), (hint.get("x"), hint.get("w")))
        self.assertEqual(int(spacer.get("y")), int(hint.get("y")) + int(hint.get("h")))
        self.assertEqual(int(spacer.get("y")) + int(spacer.get("h")), int(table.get("y")))


class DashboardHeader(unittest.TestCase):
    def test_header_on_top_and_body_below(self):
        def f(s):
            s["dashboard"].update(title="**Sales** Overview", subtitle="Sample data, 2023")
            del s["filters"]
        root = built(spec_with(f))
        top = root.find("dashboards/dashboard/zones/zone")
        head, flow = list(top.findall("zone"))
        self.assertEqual(head.get("type-v2"), "text")
        self.assertEqual(runs(head), [("Sales", {"bold": "true", "fontsize": "24"}),
                                      (" Overview", {"fontsize": "24"}),
                                      ("Æ\n", {}),
                                      ("Sample data, 2023", {"fontcolor": "#898989", "fontsize": "10"})])
        self.assertEqual(int(flow.get("y")), int(head.get("y")) + int(head.get("h")))
        self.assertEqual(int(flow.get("y")) + int(flow.get("h")), 100000 - int(head.get("y")))  # same 8px margin
        self.assertEqual(head.get("w"), flow.get("w"))

    def test_no_dashboard_title_no_header(self):
        top = built(copy.deepcopy(BASE)).find("dashboards/dashboard/zones/zone")
        self.assertEqual([z.get("type-v2") for z in top.findall("zone")], ["layout-flow"])

    def test_filters_move_into_header_row(self):
        """Reference: header = horizontal flow of the title text and fixed 142px dropdown filter cards at the right."""
        root = built(spec_with(lambda s: s["dashboard"].update(title="Sales Overview")))
        top = root.find("dashboards/dashboard/zones/zone")
        row, body = list(top.findall("zone"))
        self.assertEqual((row.get("type-v2"), row.get("param")), ("layout-flow", "horz"))
        text, card = list(row.findall("zone"))
        self.assertEqual(text.get("type-v2"), "text")
        self.assertEqual({k: card.get(k) for k in ("type-v2", "mode", "fixed-size", "is-fixed", "name")},
                         {"type-v2": "filter", "mode": "checkdropdown", "fixed-size": "142", "is-fixed": "true",
                          "name": "Table"})
        self.assertEqual(int(card.get("x")) + int(card.get("w")), int(row.get("x")) + int(row.get("w")))
        edge = design.SPACE["block_margin"]  # the header row is a block (tbuilder/spacing.py)
        row_px = max(design.header_px([(design.FONT["dash_title"], 1)], edge, edge),
                     design.HEADER_FILTER_H_PX - 2 * design.SPACE["zone_margin"] + 2 * edge)
        self.assertEqual(int(row.get("h")), round(row_px * 100000 / 800))
        side = [z for z in body.iter("zone") if z.get("type-v2") in ("filter", "color")]
        self.assertEqual([z.get("type-v2") for z in side], ["color"])  # the legend stays in the side panel

    def test_without_header_filters_stay_aside(self):
        root = built(copy.deepcopy(BASE))
        cards = [z for z in root.iter("zone") if z.get("type-v2") == "filter"]
        self.assertEqual([c.get("mode") for c in cards], [None])


class HeaderErrors(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_subtitle_needs_block_headers(self):
        def f(s):
            s["block_headers"] = False
            sheet(s, "Bar")["subtitle"] = "click to filter"
        self.assertRejects(spec_with(f), "subtitle needs block_headers")

    def test_unbalanced_bold_marks(self):
        self.assertRejects(spec_with(lambda s: sheet(s, "Bar").update(title="**Sales by Region")), "unbalanced")
        self.assertRejects(spec_with(lambda s: s["dashboard"].update(title="Sales **Overview")), "unbalanced")

    def test_too_many_header_filters(self):
        def f(s):
            s["dashboard"]["title"] = "Sales"
            s["filters"] = [{"field": c, "show_on": "Table"} for c in ("Region", "Category")] * 2
        self.assertRejects(spec_with(f), "less than half of the header")

    def test_title_too_long_for_block(self):
        self.assertRejects(spec_with(lambda s: sheet(s, "Bar").update(title="Sales " * 25)), "lines at 14pt")

    def test_row_too_short_for_header(self):
        def f(s):
            s["dashboard"].update(height=300, grid=[["KPI"], ["Bar"], ["Line", "Table"]])
            for name in ("Bar", "Line"):
                sheet(s, name).update(title="Title", subtitle="Subtitle")
        self.assertRejects(spec_with(f), "too short for its block headers")


class HeaderCardPlacement(unittest.TestCase):
    def test_left_edges_as_desktop_writes_them(self):
        """Card left edges Desktop 2025.1 wrote on Save As (golden benchmark, dates, filters_v2, folders, headers):
        a chain back from the right edge. An exact round or ceil from the left got 56572 and 66714 wrong at 1400."""
        from tbuilder.build import card_lefts
        self.assertEqual(card_lefts(99571, [150, 152], 1400), [78000, 88714])                # benchmark
        self.assertEqual(card_lefts(99571, [150, 250, 152], 1400), [60143, 70857, 88714])    # dates
        self.assertEqual(card_lefts(99571, [150, 150, 150, 152], 1400), [56572, 67286, 78000, 88714])
        self.assertEqual(card_lefts(99500, [150, 150, 152], 1200), [61834, 74334, 86834])    # folders
        self.assertEqual(card_lefts(99400, [152], 1000), [84200])                            # headers


if __name__ == "__main__":
    unittest.main()
