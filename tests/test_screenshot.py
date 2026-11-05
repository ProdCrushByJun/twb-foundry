"""compare-shots (decisions/048): the metrics on synthetic pictures, the dashboard cut out of a fake Tableau window,
the .twb text zones; with Chrome, a case's against its dashboard captured from Desktop 2025.1 (no Desktop needed).
"""
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbuilder import desktop_check as dc
from tbuilder import html_outline
from tbuilder import screenshot as ss
from test_roundtrip import ROOT

try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False


WHITE, PAGE, INK, NAVY, BLUE, LIGHT = (255,) * 3, (243, 244, 246), (40, 44, 52), (47, 74, 109), (91, 141, 184), \
    (179, 195, 214)
DARK_BG, DARK_PANEL, DARK_INK = (14, 17, 23), (22, 27, 34), (230, 237, 243)


def _block(img, box, kind, ink, colors, seed):
    """A panel's content: text lines ('table') or stacked bars ('bars'), slightly jittered by seed (another renderer
    draws the same page a little differently)."""
    rnd = random.Random(seed)
    x, y, w, h = box
    img = ss.paint(img, (x + 8, y + 6, w // 3 + rnd.randint(-6, 6), 7), ink)  # the block's heading
    if kind == "bars":  # a few bars in the left half: sparse ink, unlike a table
        for i, share in enumerate((0.9, 0.5, 0.7)):
            bh = int((h - 40) * share) + rnd.randint(-3, 3)
            bx, bw = x + 12 + i * w // 7, w // 9
            for j, c in enumerate(colors):
                img = ss.paint(img, (bx, y + h - 8 - bh + j * bh // 3, bw, bh // 3), c)
    else:
        for r in range(y + 26, y + h - 8, 14):
            img = ss.paint(img, (x + 10, r, int(w * 0.8) + rnd.randint(-5, 5), 5), ink)
    return img


LAYOUT = {"a": ((20, 20, 380, 180), "bars"), "b": ((420, 20, 160, 180), "table"),
          "c": ((20, 220, 280, 160), "table"), "d": ((320, 220, 260, 160), "bars")}


def page(blocks=LAYOUT, theme="light", seed=0, w=600, h=400):
    bg, panel, ink = (PAGE, WHITE, INK) if theme == "light" else (DARK_BG, DARK_PANEL, DARK_INK)
    colors = (NAVY, BLUE, LIGHT) if theme == "light" else ((255, 179, 71), (255, 127, 80), (255, 216, 168))
    img = ss.solid(w, h, bg)
    for i, (box, kind) in enumerate(blocks.values()):
        img = ss.paint(img, box, panel)
        img = _block(img, box, kind, ink, colors, seed * 10 + i)
    return img


def anchors(blocks=LAYOUT, w=600, h=400):
    """The blocks' headings, normalized: the page's outline headings / the dashboard's header text zones."""
    return [{"text": f"Closures {k}", "box": [x / w, y / h, bw / w, 0.02]} for k, ((x, y, bw, _), _) in blocks.items()]


def swapped():
    """The same blocks, the two rows exchanged."""
    return {"a": ((20, 220, 380, 160), "bars"), "b": ((420, 220, 160, 160), "table"),
            "c": ((20, 20, 280, 180), "table"), "d": ((320, 20, 260, 180), "bars")}


class ImageBasics(unittest.TestCase):
    def test_resize_averages_areas(self):
        img = ss.paint(ss.solid(4, 2, (0, 0, 0)), (0, 0, 2, 2), (200, 100, 50))
        self.assertEqual(ss.resize(img, 2, 1).px, bytes([200, 100, 50, 0, 0, 0]))
        self.assertEqual(ss.resize(img, 1, 1).pixel(0, 0), (100, 50, 25))
        self.assertEqual(ss.resize(ss.solid(3, 3, (9, 8, 7)), 7, 5).px, bytes([9, 8, 7]) * 35)  # upscaling

    def test_crop_and_content_box(self):
        img = ss.paint(ss.solid(100, 80, PAGE), (30, 20, 40, 30), WHITE)
        x, y, w, h = ss.content_box(img)
        self.assertTrue(abs(x - 30) <= 2 and abs(y - 20) <= 2 and abs(w - 40) <= 4 and abs(h - 30) <= 4, (x, y, w, h))
        self.assertEqual(ss.crop(img, (30, 20, 40, 30)).px, bytes(WHITE) * 1200)
        self.assertEqual(ss.content_box(ss.solid(10, 10, PAGE)), (0, 0, 10, 10))  # nothing on it: the whole picture

    def test_png_round_trip(self):
        img = page(seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            ss.save_png(img, Path(tmp) / "x.png")
            self.assertEqual(ss.load_png(Path(tmp) / "x.png").px, img.px)


class Metrics(unittest.TestCase):
    def test_identical_pictures_score_one(self):
        r, _, _ = ss.compare(page(), page())
        self.assertEqual(r["scores"], {"structure": 1.0, "layout": 1.0, "color": 1.0})
        self.assertTrue(r["similar"])

    def test_same_page_drawn_differently_is_similar(self):
        r, _, _ = ss.compare(page(seed=0), page(seed=1), anchors(), anchors())
        self.assertTrue(r["similar"], r["scores"])
        self.assertEqual(r["parts"]["heading_anchors"], 1.0)

    def test_another_theme_fails_on_color_and_structure_not_layout(self):
        r, _, _ = ss.compare(page(), page(theme="dark"))
        self.assertFalse(r["similar"])
        self.assertLess(r["scores"]["color"], ss.THRESHOLDS["color"])
        self.assertLess(r["scores"]["structure"], ss.THRESHOLDS["structure"])
        self.assertGreater(r["parts"]["ink_correlation"], 0.8)  # edges do not care about the theme

    def test_swapped_blocks_fail_on_layout_not_color(self):
        r, _, _ = ss.compare(page(swapped(), seed=1), page(), anchors(swapped()), anchors())
        self.assertFalse(r["similar"])
        self.assertEqual(r["parts"]["heading_anchors"], 0.0)  # every heading is > 0.15 of the frame away
        self.assertLess(r["scores"]["layout"], ss.THRESHOLDS["layout"])
        self.assertGreater(r["scores"]["color"], 0.9)

    def test_ssim_of_inverted_picture_is_negative(self):
        a = page()
        b = ss.Image(a.w, a.h, bytes(255 - v for v in a.px))
        self.assertLess(ss.ssim(ss.resize(a, 24, 16), ss.resize(b, 24, 16), 4), 0)

    def test_correlation_of_a_flat_map_is_zero(self):
        self.assertEqual(ss.correlation([1, 1, 1], [1, 2, 3]), 0.0)
        self.assertAlmostEqual(ss.correlation([1, 2, 3], [2, 4, 6]), 1.0)

    def test_color_score_parts(self):
        same, whole, chroma = ss.color_score(page(), page(seed=2))
        self.assertGreater(same, 0.9)
        grey = ss.solid(600, 400, PAGE)
        _, _, chroma = ss.color_score(grey, grey)
        self.assertEqual(chroma, 1.0)  # neither has colored pixels: nothing differs
        _, _, chroma = ss.color_score(page(), grey)
        self.assertEqual(chroma, 0.0)

    def test_palette_lists_the_main_colors(self):
        pal = ss.palette(page())
        self.assertEqual(pal[0]["color"], "#fbfbfc")  # page grey and panel white share a bin: their mean
        self.assertIn("#2f4a6d", [p["color"] for p in pal])  # navy bars
        self.assertAlmostEqual(sum(p["share"] for p in pal), 1.0, delta=0.02)


class Headings(unittest.TestCase):
    ZONES = [{"text": "Closures by day resolved / completed date ■ Incidents", "box": [0.0, 0.2, 0.66, 0.05]},
             {"text": "Detail by analyst", "box": [0.33, 0.5, 0.66, 0.05]}]

    def test_matched_by_words_scored_by_distance(self):
        score, rows = ss.match_headings(
            [{"text": "Closures by day resolved / completed date", "box": [0.0, 0.2, 0.3, 0.02]},
             {"text": "Detail by analyst", "box": [0.5, 0.5, 0.2, 0.02]},
             {"text": "Closures by owner team", "box": [0.7, 0.2, 0.2, 0.02]}], self.ZONES)
        self.assertEqual([r["score"] for r in rows], [1.0, 0.0, 0.0])  # exact / 0.17 away / words not in any zone
        self.assertEqual(rows[1]["distance"], 0.17)
        self.assertIsNone(rows[2]["zone"])
        self.assertAlmostEqual(score, 1 / 3)

    def test_no_headings_leaves_layout_to_ink(self):
        self.assertEqual(ss.match_headings([], self.ZONES), (None, []))
        r, _, _ = ss.compare(page(), page())
        self.assertIsNone(r["parts"]["heading_anchors"])
        self.assertEqual(r["scores"]["layout"], r["parts"]["ink_correlation"])


TWB = """<?xml version='1.0' encoding='utf-8' ?>
<workbook><worksheets><worksheet name="By Day"><layout-options><title><formatted-text><run>Closures by day</run>
</formatted-text></title></layout-options></worksheet><worksheet name="Plain"/></worksheets>
<dashboards><dashboard name="Main"><size maxheight="600" maxwidth="1000" minheight="600" minwidth="1000"/><zones>
<zone h="100000" id="3" type-v2="layout-basic" w="100000" x="0" y="0">
  <zone h="10000" id="4" type-v2="text" w="50000" x="1000" y="2000"><formatted-text><run fontsize="14">Sales </run>
    <run bold="true">Report</run><run>Æ
</run><run fontcolor="#898989">North – Harbor</run></formatted-text></zone>
  <zone h="40000" id="5" name="By Day" w="50000" x="0" y="20000"/>
  <zone h="40000" id="6" name="Plain" w="50000" x="50000" y="20000"/>
  <zone h="40000" id="7" name="Hidden" show-title="false" w="50000" x="0" y="60000"/>
  <zone h="10000" id="8" name="Hidden" param="[x].[y]" type-v2="filter" w="10000" x="90000" y="0"/>
</zone></zones></dashboard></dashboards></workbook>"""


class Dashboard(unittest.TestCase):
    def test_text_zones_and_titled_sheets_in_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "b.twb"
            p.write_text(TWB, encoding="utf-8")
            name, w, h, zones = ss.dashboard_info(p)
        self.assertEqual((name, w, h), ("Main", 1000, 600))
        self.assertEqual([z["text"] for z in zones], ["Sales Report North – Harbor", "Closures by day", "Plain"])
        self.assertEqual(zones[0]["box"], [10.0, 12.0, 500.0, 60.0])

    def test_locate_dashboard_in_a_window(self):
        grey = (245, 245, 245)
        win = ss.solid(900, 700, grey)
        win = ss.paint(win, (0, 0, 900, 60), (230, 230, 230))     # toolbar
        win = ss.paint(win, (0, 60, 150, 600), WHITE)              # side pane
        win = ss.paint(win, (151, 60, 500, 400), WHITE)            # the dashboard
        win = ss.paint(win, (171, 80, 300, 20), INK)               # its content
        win = ss.paint(win, (0, 660, 900, 40), (230, 230, 230))    # sheet tabs, status bar
        self.assertEqual(ss.locate_dashboard(win, 500, 400), (151, 60, 500, 400))
        with self.assertRaisesRegex(RuntimeError, "does not fit"):
            ss.locate_dashboard(ss.paint(win, (151, 60, 500, 600), WHITE), 500, 700)

    def test_mutate_adds_css_to_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "p.html"
            src.write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")
            out = ss.mutate(src, ss.MUTANTS["dark"], Path(tmp) / "q.html")
            head = out.read_text(encoding="utf-8").split("</head>")[0]
            self.assertIn("<style>:root{--bg:#0e1117", head)
            self.assertIn(f'<base href="{Path(tmp).resolve().as_uri()}/">', head)


class DesktopHook(unittest.TestCase):
    """desktop_check.check(on_loaded=) runs the callback on OK only, before closing the process."""

    def _check(self, status):
        calls = []
        proc = mock.Mock(pid=4242)
        with mock.patch.object(dc, "_launch", return_value=proc), \
                mock.patch.object(dc, "watch", return_value=(status, "", 1.0)), \
                mock.patch.object(dc, "_close", side_effect=lambda p: calls.append("close") or "closed"), \
                mock.patch.object(dc, "ProcessLog"):
            r = dc.check("x.twbx", exe=Path("tableau.exe"), on_loaded=lambda pid: calls.append(pid))
        return r, calls

    def test_called_on_ok_before_close(self):
        r, calls = self._check(dc.OK)
        self.assertEqual((r.status, calls), (dc.OK, [4242, "close"]))

    def test_not_called_on_error(self):
        r, calls = self._check(dc.ERROR)
        self.assertEqual((r.status, calls), (dc.ERROR, ["close"]))




if __name__ == "__main__":
    unittest.main()
