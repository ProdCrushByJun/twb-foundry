"""Data-ink and spacing (todo 3.7): block margins from design.SPACE, level titles, labels that are not clipped,
tooltips without helper fields."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import design, ink, spacing
from tbuilder.build import build
from test_roundtrip import SPECS

OUT = Path(__file__).resolve().parent.parent / "out" / "spacing_test.twbx"
SP = design.SPACE


def load(name):
    return json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def margins(z):
    st = {f.get("attr"): int(f.get("value")) for f in z.findall("zone-style/format") if "margin" in f.get("attr")}
    return {s: st.get(f"margin-{s}", st.get("margin")) for s in spacing.SIDES}


def zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name and "type-v2" not in z.attrib)


def text(root, start):
    return next(z for z in root.iter("zone") if z.get("type-v2") == "text"
                and "".join(r.text or "" for r in z.iter("run")).startswith(start))


def worksheet(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


class Margins(unittest.TestCase):
    def test_sides_on_the_block_edge(self):
        cell = (0, 0, 100, 100)
        self.assertEqual(spacing.margins((0, 0, 50, 100), cell),
                         {"top": SP["block_margin"], "right": SP["zone_margin"], "bottom": SP["block_margin"],
                          "left": SP["block_margin"]})
        self.assertEqual(spacing.margins((0, 0, 100, 100), cell, under_header=True)["top"], 0)

    def test_early_goldens_keep_one_margin(self):
        self.assertEqual(set(spacing.margins((0, 0, 50, 50), (0, 0, 100, 100), block=False).values()),
                         {SP["zone_margin"]})

    def test_formats_most_frequent_side_first(self):
        self.assertEqual(spacing.formats({"top": 0, "right": 12, "bottom": 12, "left": 12}),
                         [("margin", 12), ("margin-top", 0)])
        self.assertEqual(spacing.formats(4), [("margin", 4)])


class Blocks(unittest.TestCase):
    """golden_colors: two rows of three blocks under a dashboard header."""

    @classmethod
    def setUpClass(cls):
        spec = load("colors")
        spec["dashboard"]["theme"] = "flat"  # the view without cards (decisions/168)
        cls.root = built(spec)

    def test_block_header_gap_and_sheet_under_it(self):
        head, sheet = text(self.root, "Sales"), zone(self.root, "Regions")
        self.assertEqual(margins(head), {s: SP["header_gap"] if s == "bottom" else SP["block_margin"]
                                         for s in spacing.SIDES})
        self.assertEqual(margins(sheet)["top"], 0)  # the header's margin-bottom is the gap (as in the reference)
        self.assertEqual(int(sheet.get("y")), int(head.get("y")) + int(head.get("h")))

    def test_blocks_24px_apart_and_20px_from_the_edge(self):
        a, b = zone(self.root, "Regions"), zone(self.root, "Managers")
        self.assertEqual(margins(a)["right"] + margins(b)["left"], 2 * SP["block_margin"])
        root_margin = int(self.root.find("dashboards/dashboard/zones/zone/zone-style/format[@attr='margin']")
                          .get("value"))
        self.assertEqual(root_margin + margins(a)["left"], 20)  # reference: dashboard padding 20

    def test_dashboard_title_aligned_with_block_titles(self):
        dash, block = text(self.root, "Color"), text(self.root, "Sales")
        self.assertEqual(dash.get("x"), block.get("x"))
        self.assertEqual(margins(dash)["left"], margins(block)["left"])


class LevelTitles(unittest.TestCase):
    def test_shorter_header_keeps_its_height_and_a_spacer_fills_the_band(self):
        """golden_registry: 'Categories' (title only) next to a title + subtitle: Tableau centers a text zone's
        lines, so a full-band zone put the short title lower than its neighbour's."""
        root = built(load("registry"))
        tall, short = text(root, "Region"), text(root, "Categories")
        self.assertEqual(tall.get("y"), short.get("y"))
        self.assertLess(int(short.get("h")), int(tall.get("h")))
        [spacer] = [z for z in root.iter("zone") if z.get("type-v2") == "empty"]
        self.assertEqual(int(spacer.get("y")) + int(spacer.get("h")), int(tall.get("y")) + int(tall.get("h")))


class Tiles(unittest.TestCase):
    def test_row_too_short_for_a_tile(self):
        spec = load("actions")
        spec["dashboard"]["row_heights"] = [1, 3, 3]  # 97px: Desktop showed scrollbars around the tile text
        with self.assertRaisesRegex(ValueError, "too short for a KPI tile"):
            build(spec, OUT, SPECS)


class Labels(unittest.TestCase):
    def test_plural_names_the_field(self):
        """'Categories' says Category: its label and the Sales axis title go (golden_actions: 'Cate..' clipped)."""
        ws = worksheet(built(load("actions")), "By Category")
        attrs = {(f.get("attr"), f.get("scope")) for f in ws.iter("format")}
        self.assertIn(("display-field-labels", "rows"), attrs)
        self.assertIn(("title", "cols"), attrs)

    def test_hidden_row_label_takes_no_width(self):
        spec = load("actions")
        next(s for s in spec["sheets"] if s["name"] == "By Category").update(title="Sales", subtitle="Sum")
        ws = worksheet(built(spec), "By Category")
        [w] = [f for f in ws.iter("format") if f.get("attr") == "width"]
        self.assertTrue(w.get("field").endswith("[none:Category:nk]"))
        # the label and its sort indicator are gone on a horizontal bar (decision 183): only the values need room
        self.assertLess(int(w.get("value")), design.field_label_px("Category", design.SORT_ICON_PX))

    def test_table_labels_and_column_width(self):
        """golden_headers: 'Sales by region and category' names both fields; 'Furniture' was clipped to 'Furnit..'."""
        spec = load("headers")
        spec["dashboard"]["theme"] = "flat"
        ws = worksheet(built(spec), "Table")
        self.assertEqual({f.get("scope") for f in ws.iter("format") if f.get("attr") == "display-field-labels"},
                         {"rows", "cols"})
        [cell] = ws.findall("table/style/style-rule[@element='cell']/format")
        self.assertEqual(int(cell.get("value")), design.row_header_px(len("Furniture")))


class AxisWidth(unittest.TestCase):
    def test_tick_characters(self):
        self.assertEqual(ink.tick_chars(35353, False), 3)  # '50K' (true top tick 40K)
        self.assertEqual(ink.tick_chars(3400, False), 4)  # '5,0K'
        self.assertEqual(ink.tick_chars(-1343, False), 5)  # '-2,0K'
        self.assertEqual(ink.tick_chars(0.35, True), 5)  # '50,0%'
        self.assertEqual(ink.tick_chars(1.2, True), 6)  # '200,0%'

    def test_wider_than_five_characters(self):
        self.assertEqual(design.axis_px(5), design.AXIS_LABEL_W_PX)
        self.assertEqual(design.axis_px(3), design.AXIS_LABEL_W_PX)
        self.assertGreater(design.axis_px(6), design.AXIS_LABEL_W_PX)

    def test_percent_axis_over_100(self):
        spec = load("colors")
        spec["calcs"].append({"name": "Plan Share", "formula": "SUM([Sales]) / SUM([Plan])", "format": "percent"})
        trend = next(s for s in spec["sheets"] if s["name"] == "Trend")
        trend.pop("color")
        trend.update(measure={"field": "Plan Share"}, title="Monthly **plan share**", subtitle="Sales against plan")
        ws = worksheet(built(spec), "Trend")
        [w] = [f for f in ws.iter("format") if f.get("attr") == "width"]
        self.assertEqual(int(w.get("value")), design.axis_px(6))  # '200,0%'


class Tooltips(unittest.TestCase):
    def test_registry_tooltip_is_empty(self):
        ws = worksheet(built(load("registry")), "Registry")
        tips = ws.findall("table/panes/pane/customized-tooltip")
        self.assertEqual(len(tips), len(ws.findall("table/panes/pane")))  # reference: every pane
        self.assertTrue(all(t.get("show-buttons") == "false" and not list(t.find("formatted-text")) for t in tips))

    def test_highlight_flag_not_in_tooltip(self):
        """golden_colors: the tooltip said 'Regions · Highlight: True' over 'Region: East / Sales: 35 353'."""
        ws = worksheet(built(load("colors")), "Regions")
        runs = [r.text for r in ws.iter("run")]
        self.assertEqual([r for r in runs if r.endswith(":\t")], ["Region:\t", "Sales:\t"])
        self.assertFalse([r for r in runs if "Highlight" in r])

    def test_card_value_without_tooltip_and_history_without_flags(self):
        root = built(load("cards"))
        value = worksheet(root, "Monthly · Sales").find("table/panes/pane/customized-tooltip/formatted-text")
        self.assertEqual(list(value), [])
        runs = [r.text for r in worksheet(root, "Monthly · Sales · History").iter("run")]
        self.assertEqual([r for r in runs if r.endswith(":\t")], ["Order Date:\t", "Sales:\t"])

    def test_plain_sheets_keep_tableaus_tooltip(self):
        ws = worksheet(built(load("headers")), "Line")
        self.assertIsNone(ws.find("table/panes/pane/customized-tooltip"))


if __name__ == "__main__":
    unittest.main()
