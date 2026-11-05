"""Two registries side by side in one row (decisions/129): each one's columns are sized from its own cell, not from the
page; acceptance/table_kpi (6 + 4 columns) builds at 1600 with the panes inside their cells and is refused, naming the
registry, where the pair cannot fit (1280, the HTML's width: 10 panes of >= 100 px do not fit)."""
import copy
import json
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design
from tbuilder.build import build

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "acceptance" / "table_kpi"
SPEC = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "registry_side_by_side_test.twbx"


def with_grid(width, left=7, right=4):
    spec = copy.deepcopy(SPEC)
    spec["dashboard"]["width"] = width
    spec["dashboard"]["grid"][1] = [{"sheet": "Region Category", "width": left}, {"sheet": "Top Products", "width": right}]
    return spec


def panes_and_heads(spec, name):
    out = build(spec, OUT, CASE)
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read(out.stem + ".twb"))
    ws = next(w for w in root.iter("worksheet") if w.get("name") == name)
    panes = [int(f.get("value")) for f in ws.iterfind(
        "table/panes/pane/style/style-rule[@element='pane']/format[@attr='minwidth']")]
    heads = [int(f.get("value")) for f in ws.iterfind("table/style/style-rule[@element='header']/format[@attr='width']")]
    return panes, heads


class SideBySide(unittest.TestCase):
    def test_acceptance_case_is_the_narrowest_reference_size_that_fits(self):
        self.assertEqual(SPEC["dashboard"]["width"], 1600)
        for name in ("Region Category", "Top Products"):
            panes, _ = panes_and_heads(SPEC, name)
            self.assertGreaterEqual(min(panes), design.REGISTRY_PANE_MIN_PX, name)

    def test_panes_stay_inside_their_own_cell(self):
        """The cell is the page share of the sheet, less margins: the panes, the row headers and the bar never
        add up to more than that share of the page (a page-wide sum would be ~1600)."""
        for name, share in (("Region Category", 7 / 11), ("Top Products", 4 / 11)):
            panes, heads = panes_and_heads(SPEC, name)
            self.assertLessEqual(sum(panes) + sum(heads), 1600 * share, name)

    def test_columns_follow_the_cell_not_the_page(self):
        """Same page, weights 7:4 against 3:2: the wider cell gives wider panes to that registry only."""
        wide_left, _ = panes_and_heads(with_grid(1900, 7, 4), "Region Category")
        narrow_left, _ = panes_and_heads(with_grid(1900, 3, 2), "Region Category")
        self.assertGreater(wide_left[0], narrow_left[0])
        wide_right, _ = panes_and_heads(with_grid(1900, 3, 2), "Top Products")
        narrow_right, _ = panes_and_heads(with_grid(1900, 7, 4), "Top Products")
        self.assertGreater(wide_right[0], narrow_right[0])

    def test_html_width_is_refused_naming_the_registry(self):
        with self.assertRaises(ValueError) as e:
            panes_and_heads(with_grid(1280, 2, 1), "Region Category")
        self.assertIn("Registry '", str(e.exception))
        self.assertIn("too narrow", str(e.exception))


if __name__ == "__main__":
    unittest.main()
