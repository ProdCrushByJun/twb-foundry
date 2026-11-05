"""Layout archetypes (todo 3.3): nested grid groups, stacked KPI tiles/cards, sidebar."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import design
from tbuilder.build import build
from test_roundtrip import SPECS

GOLDEN = json.loads((SPECS / "golden.json").read_text(encoding="utf-8"))
del GOLDEN["block_headers"]
CARDS = json.loads((SPECS / "cards.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent.parent / "out" / "layout_test.twbx"


def with_(base, fn):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def zones(root):
    """Sheet zones by name -> (x, y, w, h)."""
    return {z.get("name"): tuple(int(z.get(k)) for k in ("x", "y", "w", "h"))
            for z in root.iter("zone") if z.get("name") and "type-v2" not in z.attrib}


def kpi_left(spec):
    spec["dashboard"]["grid"] = [["KPI", {"rows": [["Bar"], ["Line", "Table"]], "width": 2,
                                          "row_heights": [3, 1]}]]
    spec["dashboard"]["width"] = 1200  # the line's plot holds 'Month of Order Date [2025]' (decisions/094)


class Groups(unittest.TestCase):
    def test_group_splits_its_cell(self):
        z = zones(built(with_(GOLDEN, kpi_left)))
        kx, ky, kw, kh = z["KPI"]
        bx, by, bw, bh = z["Bar"]
        lx, ly, lw, lh = z["Line"]
        tx, ty, tw, th = z["Table"]
        self.assertEqual(bx, kx + kw)  # the group starts where the KPI column ends
        self.assertEqual(by, ky)  # and spans the KPI column's full height
        self.assertEqual(ly + lh, ky + kh)
        self.assertEqual((ly, ty), (by + bh, by + bh))  # no gap between nested rows
        self.assertEqual((lx, lx + lw), (bx, tx))
        self.assertEqual(tx + tw, bx + bw)
        self.assertAlmostEqual(bh / lh, 3, delta=0.01)  # group row_heights
        self.assertAlmostEqual(bw / kw, 2, delta=0.01)  # group width weight

    def test_block_headers_inside_a_group(self):
        def f(s):
            kpi_left(s)
            sheet(s, "Line")["title"] = "Trend"
        root = built(with_(GOLDEN, f))
        z = zones(root)
        head = next(t for t in root.iter("zone") if t.get("type-v2") == "text")
        self.assertEqual((int(head.get("x")), int(head.get("y"))), z["Line"][:1] + (z["Bar"][1] + z["Bar"][3],))
        self.assertEqual(z["Line"][1], int(head.get("y")) + int(head.get("h")))
        self.assertEqual(z["Table"][1], int(head.get("y")))  # no header: full row height

    def test_errors(self):
        cases = [
            (lambda s: s["dashboard"].update(grid=[[{"rows": [[{"rows": [[{"rows": [["KPI"]]}]]}]]}, "Bar"],
                                                   ["Line", "Table"]]), "nested 4 levels"),
            (lambda s: s["dashboard"].update(grid=[["KPI", {"rows": [["Bar"], ["Line"]], "row_heights": [1]}],
                                                   ["Table"]]), "group's row_heights"),
            (lambda s: s["dashboard"].update(grid=[["KPI", {"rows": [["Bar"], ["KPI"]]}], ["Line", "Table"]]),
             "appears twice"),
        ]
        for fn, msg in cases:
            with self.subTest(msg=msg), self.assertRaisesRegex(ValueError, msg):
                build(with_(GOLDEN, fn), OUT, SPECS)


class Arrange(unittest.TestCase):
    def test_tiles_stacked(self):
        def f(s):
            sheet(s, "KPI").update(style="tiles", arrange="column")
            kpi_left(s)
        z = zones(built(with_(GOLDEN, f)))
        tiles = [z[f"KPI · {m}"] for m in ("Profit", "Quantity", "Sales")]
        self.assertEqual({t[0] for t in tiles}, {tiles[0][0]})  # one column
        self.assertEqual([t[1] for t in tiles[1:]], [t[1] + t[3] for t in tiles[:-1]])  # stacked, no gaps

    def test_cards_stacked_value_left_of_history(self):
        def f(s):
            sheet(s, "Monthly").update(arrange="column")
            s["dashboard"]["theme"] = "flat"
            s["dashboard"]["grid"] = [["Monthly", {"rows": [["Yearly"], ["Trend"]], "width": 2}]]
        z = zones(built(with_(CARDS, f)))
        v, h = z["Monthly · Sales"], z["Monthly · Sales · History"]
        self.assertEqual((v[1], v[3]), (h[1], h[3]))  # same row
        self.assertEqual(h[0], v[0] + v[2])
        self.assertEqual(v[2], round(design.CARD_VALUE_W_PX * 100000 / 1200))
        self.assertEqual(z["Monthly · Profit"][1], v[1] + v[3])  # next card below

    def test_card_value_fits_its_zone(self):
        """Entire View on the card text and its history: Desktop showed scrollbars around a stacked card's text
        and around a short history strip (3.7) without it."""
        root = built(copy.deepcopy(CARDS))
        dash = next(w for w in root.iter("window") if w.get("class") == "dashboard")
        fit = {vp.get("name"): vp.find("zoom") is not None for vp in dash.iter("viewpoint")}
        self.assertTrue(fit["Monthly · Sales"])
        self.assertTrue(fit["Monthly · Sales · History"])

    def test_stacked_card_too_short(self):
        def f(s):
            sheet(s, "Monthly").update(arrange="column", measures=[{"field": f} for f in
                                                                   ("Sales", "Profit", "Quantity")])
            s["dashboard"]["grid"] = [["Monthly", "Yearly"], ["Trend"]]
        with self.assertRaisesRegex(ValueError, "stacked KPI card needs"):
            build(with_(CARDS, f), OUT, SPECS)


class Sidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(with_(GOLDEN, lambda s: s["dashboard"].update(
            sidebar=True, title="**Sales** Overview", subtitle="Sample data")))
        cls.side = next(z for z in cls.root.iter("zone")
                        if z.get("type-v2") == "layout-flow" and z.get("param") == "vert")

    def test_panel_left_grey_fixed(self):
        st = {f.get("attr"): f.get("value") for f in self.side.findall("zone-style/format")}
        self.assertEqual((st["padding"], st["background-color"]),
                         (str(design.SPACE["panel_padding"]), design.COLOR["sidebar_bg"]))
        self.assertNotIn("margin", st)
        self.assertEqual(self.side.get("fixed-size"), str(design.SIDEBAR_PX))
        body = zones(self.root)
        sx, sw = int(self.side.get("x")), int(self.side.get("w"))
        self.assertEqual(min(z[0] for z in body.values()), sx + sw)  # sheets start right of the panel

    def test_title_filters_legends_inside(self):
        kinds = [z.get("type-v2") for z in self.side.findall("zone")]
        self.assertEqual(kinds, ["text", "filter", "color"])
        self.assertEqual(self.side.find("zone[@type-v2='filter']").get("mode"), "checkdropdown")
        ys = [int(z.get("y")) for z in self.side.findall("zone")]
        self.assertEqual(ys, sorted(ys))

    def test_no_header_row_no_right_panel(self):
        top = self.root.find("dashboards/dashboard/zones/zone")
        self.assertEqual([z.get("type-v2") for z in top.findall("zone")], ["layout-flow"])  # body flow only
        outside = [z for z in self.root.iter("zone") if z.get("type-v2") in ("filter", "color", "text")
                   and z not in self.side.findall("zone")]
        self.assertEqual(outside, [])

    def test_title_too_long_for_sidebar(self):
        with self.assertRaisesRegex(ValueError, "lines at 24pt"):
            build(with_(GOLDEN, lambda s: s["dashboard"].update(sidebar=True, title="Quarterly sales overview "
                                                                "for all regions")), OUT, SPECS)


if __name__ == "__main__":
    unittest.main()
