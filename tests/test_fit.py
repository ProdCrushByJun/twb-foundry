"""Sheet fit on a dashboard (decisions/068): the rule, the builder's choice on the Desktop labs
(tests/fixtures/fit, pictures *.png), KPI tiles aligned alike, and the gate catching a wrong fit."""
import copy
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import fit, gate
from tbuilder.build import build

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "tests" / "fixtures" / "fit"
OUT = ROOT / "out" / "fit_test"
EV, FW, FH, STD = fit.EV, fit.FW, fit.FH, fit.STD


def lab(name):
    return json.loads((LAB / f"{name}.json").read_text(encoding="utf-8"))


def built(spec, base=LAB, name="book", crowded=False):
    """crowded=False: the lab dashboards are drawn crowded on purpose (decisions/093), the refusal is off."""
    keep = fit.crowded
    if not crowded:
        fit.crowded = lambda *a, **k: []
    try:
        out = build(copy.deepcopy(spec), OUT / f"{name}.twbx", base)
    finally:
        fit.crowded = keep
    return out, read(out)


def read(path):
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def zooms(root):
    return {vp.get("name"): fit.zoom_of(vp) for w in root.iter("window") if w.get("class") == "dashboard"
            for vp in w.iter("viewpoint")}


def repack(src, dst, fn):
    """Copy a .twbx with fn(root) applied to its XML."""
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.endswith(".twb"))
    root = etree.fromstring(items[twb])
    fn(root)
    items[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)
    return dst


def set_zoom(name, zoom):
    def fn(root):
        for w in root.iter("window"):
            for vp in w.iter("viewpoint"):
                if w.get("class") == "dashboard" and vp.get("name") == name:
                    for z in vp.findall("zoom"):
                        vp.remove(z)
                    if zoom != STD:
                        etree.SubElement(vp, "zoom", type=zoom)
    return fn


class Rule(unittest.TestCase):
    def side(self, n, unit=20, reserve=0, have=200, squeeze=1):
        return fit.Side(n, unit, reserve, have, squeeze)

    def test_four_fits(self):
        fits, short, none = self.side(5), self.side(20), self.side(0)
        self.assertEqual(fit.decide(fits, none), {EV})
        self.assertEqual(fit.decide(short, none), {FW})  # the rows do not fit: they keep their size and scroll
        self.assertEqual(fit.decide(none, short), {FH})
        self.assertEqual(fit.decide(short, short), {STD})

    def test_reserve_and_squeeze(self):
        self.assertEqual(fit.decide(self.side(9, reserve=30), self.side(0)), {FW})  # 180 + 30 > 200
        self.assertEqual(fit.decide(self.side(9, reserve=30, squeeze=0.8), self.side(0)), {EV})  # 144 + 30

    def test_unknown_count_allows_both(self):
        self.assertEqual(fit.decide(self.side(None), self.side(0)), {EV, FW})
        self.assertEqual(fit.decide(self.side(None), self.side(None)), {EV, FW, FH, STD})
        self.assertEqual(fit.pick({EV, FW}), EV)

    def test_combos_with_top_n(self):
        rows = [("a", "x"), ("a", "y"), ("b", "x"), ("c", "z"), ("", "x")]
        self.assertEqual(fit.combos(rows, [lambda r: r[0]], [None]), 4)  # '' is the Null member
        self.assertEqual(fit.combos(rows, [lambda r: r[0]], [2]), 2)
        self.assertEqual(fit.combos(rows, [lambda r: r[0], lambda r: r[1]], [None, None]), 5)


class Labs(unittest.TestCase):
    """The builder's fit on the lab dashboards, as the pictures show it right (lists_rule.png, charts_rule.png,
    squeeze_entire-view.png)."""

    @classmethod
    def setUpClass(cls):
        cls.lists = zooms(built(lab("lists"), name="lists")[1])
        cls.charts = zooms(built(lab("charts"), name="charts")[1])
        cls.squeeze = zooms(built(lab("squeeze"), name="squeeze")[1])

    def test_short_lists_fill_the_zone(self):
        for name in ("Bar5", "Bar5v", "Reg6"):
            self.assertEqual(self.lists[name], EV, name)

    def test_long_lists_scroll_at_full_width(self):
        self.assertEqual(self.lists["Bar20"], FW)  # in Entire View 20 bars of 9px overlap their labels
        self.assertEqual(self.lists["Reg20"], FW)

    def test_a_table_wider_than_its_zone_fills_the_height(self):
        self.assertEqual(self.lists["Table"], FH)  # Entire View squeezed its numbers to '####'
        self.assertEqual(self.charts["Heat"], FH)  # and the heatmap's to '##'

    def test_charts_fill_the_zone(self):
        for name in ("Line", "Area", "Combo", "Lolli", "HeatM", "HeatM · Row Totals", "HeatM · Column Totals"):
            self.assertEqual(self.charts[name], EV, name)

    def test_tiles_fill_their_zones(self):
        self.assertEqual({v for k, v in self.lists.items() if k.startswith("KPI · ")}, {EV})

    def test_squeeze(self):
        """Bars of 16px read (Bar13 since the card inset lost 8px, decision 187), narrower touch (Bar14); registry rows (theme 30px, numbers on the marks)
        keep their size: 8 fit since the card inset lost 8px (decision 187), 9 do not."""
        self.assertEqual([self.squeeze[f"Bar{n}"] for n in (11, 13, 14, 15, 17)], [EV, EV, FW, FW, FW])
        self.assertEqual([self.squeeze[f"Reg{n}"] for n in (7, 8, 9, 10, 12)], [EV, EV, FW, FW, FW])


class Tiles(unittest.TestCase):
    """Every tile of a KPI sheet: one fit and one alignment, whatever its field's type (ITSM: right, right, centre,
    right, left in Standard)."""

    def test_itsm(self):
        spec = json.loads((ROOT / "acceptance" / "itsm-incidents" / "spec.json").read_text(encoding="utf-8"))
        _, root = built(spec, ROOT / "acceptance" / "itsm-incidents", "itsm")
        z = zooms(root)
        tiles = [w for w in root.iter("worksheet") if w.get("name").startswith("KPI · ")]
        self.assertEqual(len(tiles), 5)
        for ws in tiles:
            self.assertEqual(z[ws.get("name")], EV)
            self.assertEqual(gate._alignment(ws)[:2], ("left", "center"), ws.get("name"))
        self.assertEqual({z[n] for n in ("By Category", "MTTR By Priority", "Assignment Groups")}, {EV})


class DonutLegend(unittest.TestCase):
    def test_legend_parts_fill_their_zones(self):
        """A donut's dots and legend text stay in entire-view row for row with each other (decisions/069), even with
        more members than Standard rows fit: 20 items in a 560px dashboard (in 420px the legend rows overlap: refused,
        decisions/093, tests/test_fit_tails.py)."""
        spec = lab("lists")
        spec["sheets"] = [{"name": "Mix", "type": "donut", "title": "**Mix**", "dimension": "Item",
                           "measure": {"field": "Sales"}}]
        spec["dashboard"].update(grid=[["Mix"]], height=560)
        spec["dashboard"].pop("row_heights")
        out, root = built(spec, name="donut", crowded=True)
        z = zooms(root)
        self.assertEqual((z["Mix"], z["Mix · Dots"], z["Mix · Legend"]), (EV, EV, EV))
        self.assertEqual(gate.run(out), [])


class HeatmapNull(unittest.TestCase):
    def test_null_is_a_row_of_its_own(self):
        """The heatmap's cell sizes count the Null member (5 regions, 4 categories with Null): the cells fit their
        zone, so the heatmap and its margins fill their zones alike (nulls_more.png)."""
        spec = json.loads((ROOT / "acceptance" / "nulls" / "spec_more.json").read_text(encoding="utf-8"))
        _, root = built(spec, ROOT / "acceptance" / "nulls", "nulls_more")
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "Heat")
        heights = [int(f.get("value")) for f in ws.iterfind("table/style/style-rule[@element='cell']/format")
                   if f.get("attr") == "height"]
        self.assertEqual(len(heights), 1)
        z = next(z for z in root.iter("zone") if z.get("name") == "Heat" and not z.get("type-v2"))
        size = next(root.iter("dashboard")).find("size")
        _, have = fit.zone_px(z, (int(size.get("maxwidth")), int(size.get("maxheight"))))
        self.assertLessEqual(5 * heights[0], have)
        self.assertEqual({v for k, v in zooms(root).items() if k.startswith("Heat")}, {EV})

    def test_total_rows_count(self):
        """Subtotals and the grand total are rows too: 19 regions x categories + 5 subtotals + 1 total."""
        spec = json.loads((ROOT / "acceptance" / "nulls" / "spec_more.json").read_text(encoding="utf-8"))
        out, root = built(spec, ROOT / "acceptance" / "nulls", "nulls_more")
        with zipfile.ZipFile(out) as z:
            tables = gate._text_tables(z, set(z.namelist()), root)
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "Subtotals")
        self.assertEqual(fit.members(ws, "rows", fit.table_counter(tables), {}), 25)


class GateCatchesFit(unittest.TestCase):
    """Mutations of the lists lab book: the gate names a wrong fit and a tile out of step with its siblings."""

    @classmethod
    def setUpClass(cls):
        cls.book, _ = built(lab("lists"), name="lists_gate")
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def issues(self, fn):
        return [str(i) for i in gate.run(repack(self.book, self.tmp / "m.twbx", fn)) if i.check == "fit"]

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def test_short_bars_in_standard(self):
        got = self.issues(set_zoom("Bar5", STD))
        self.assertTrue(any("'Bar5'" in i and "fit standard" in i for i in got), got)

    def test_long_list_squeezed(self):
        got = self.issues(set_zoom("Bar20", EV))
        self.assertTrue(any("'Bar20'" in i and "squeezes" in i for i in got), got)
        self.assertTrue(self.issues(set_zoom("Reg20", EV)))

    def test_short_registry_fit_width(self):
        self.assertTrue(any("'Reg6'" in i for i in self.issues(set_zoom("Reg6", FW))))

    def test_table_fit_width(self):
        """The gate cannot size the table's columns (no numbers in the XML) but its 6 rows fit: not fit-width."""
        self.assertTrue(any("'Table'" in i for i in self.issues(set_zoom("Table", FW))))

    def test_one_tile_in_standard(self):
        got = self.issues(set_zoom("KPI · Margin", STD))
        self.assertTrue(any("'KPI · Margin'" in i and "fit standard" in i for i in got), got)
        self.assertTrue(any("KPI 'KPI'" in i and "differ" in i for i in got), got)

    def test_one_tile_aligned_right(self):
        def fn(root):
            ws = next(w for w in root.iter("worksheet") if w.get("name") == "KPI · Units")
            f = next(f for f in ws.iter("format") if f.get("attr") == "text-align")
            f.set("value", "right")
        got = self.issues(fn)
        self.assertTrue(any("KPI 'KPI'" in i and "'KPI · Units' entire-view ('right'" in i for i in got), got)


class Goldens(unittest.TestCase):
    """Every golden's dashboard sheets have the rule's fit (the goldens are re-saved by Desktop with it)."""

    def test_goldens(self):
        for g in sorted((ROOT / "golden").glob("golden*_2025_1.twbx")):
            if ".twbx" in g.stem:  # a duplicate save with a mangled name, git-ignored (golden/README.md)
                continue
            with self.subTest(g.stem), zipfile.ZipFile(g) as z:
                root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
                self.assertEqual([str(i) for i in gate.check_fit(root, gate._text_tables(z, set(z.namelist()), root))],
                                 [])


if __name__ == "__main__":
    unittest.main()
