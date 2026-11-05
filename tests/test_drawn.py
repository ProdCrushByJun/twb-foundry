"""What Desktop drew (decisions/076): numbers read off a Desktop capture against expected.compute."""
import json
import re
import tempfile
import unittest
import zipfile
from ctypes import wintypes
from pathlib import Path
from unittest import mock

from tbuilder import drawn, ocr, screenshot as sc
from tbuilder.ocr import Word
from test_roundtrip import ROOT

FIX = ROOT / "tests" / "fixtures" / "drawn"


def line(*texts, gap=6, h=12):
    """Words of one OCR line left to right, each 8 px per character, `gap` px apart."""
    out, x = [], 0
    for t in texts:
        out.append(Word(t, x, 0, 8 * len(t), h, 0))
        x += 8 * len(t) + gap
    return out


class Tokens(unittest.TestCase):
    def test_thousands_groups_join(self):
        self.assertEqual(drawn.tokens(line("$624", "628", "$1059", "080")), ["$624 628", "$1059 080"])

    def test_ocr_zero_and_percent_misreads(self):
        self.assertEqual(drawn.tokens(line("$25", "ooo")), ["$25 000"])
        self.assertEqual(drawn.tokens(line("25,10/0")), ["25,1%"])
        self.assertEqual(drawn.tokens(line("$110,OM")), ["$110,0M"])

    def test_decimals_split_at_the_point(self):
        self.assertEqual(drawn.tokens(line("($3,", "0M)")), ["($3,0M)"])

    def test_columns_apart_stay_apart(self):
        self.assertEqual(drawn.tokens(line("260", gap=200) + [Word("000", 260, 0, 24, 12, 0)]), ["260", "000"])
        self.assertEqual(drawn.tokens(line("$12,1M", "52%")), ["$12,1M", "52%"])  # a unit ends a number

    def test_words_are_not_numbers(self):
        self.assertEqual(drawn.tokens(line("Planning", "2026-06-09", "FY27")), [])


class Numbers(unittest.TestCase):
    def test_parse_at_displayed_precision(self):
        got = drawn.numbers(["$27,6M", "25,1%", "($5,8M)", "▲ 84,5%".split()[-1], "1 050"])
        self.assertEqual([round(v, 4) for v, _ in got], [27600000, 0.251, -5800000, 0.845, 1050])
        self.assertEqual([round(h, 6) for _, h in got], [50000, 0.0005, 50000, 0.0005, 0.5])

    def test_drawn_within_half_a_step(self):
        read = drawn.numbers(["$27,6M", "25,1%", "9 000"])
        self.assertTrue(drawn.drawn(27562659.56, read))
        self.assertTrue(drawn.drawn(0.2505696, read))
        self.assertTrue(drawn.drawn(-9000, read))  # ▼ / parentheses carry the sign
        self.assertFalse(drawn.drawn(27700000, read))
        self.assertFalse(drawn.drawn(9001, read))


class Groups(unittest.TestCase):
    def test_registry_by_column_without_tick_base_or_track(self):
        s = {"type": "registry", "columns": [
            {"measure": {"field": "Sales"}, "style": "text", "label": "Sales"},
            {"measure": {"field": "Sales"}, "style": "track", "label": "Of total"},
            {"measure": {"field": "Sales"}, "style": "tick", "label": "Vs PY", "base": {"field": "PY", "label": "2024"}}]}
        values = {"East": {"Sales": 1.0, "Of total": 0.2, "Vs PY": 3.0, "Vs PY · 2024": 2.0, "Note": "x"}}
        self.assertEqual(drawn.groups(s, values), {"Sales": [1.0], "Vs PY": [3.0]})

    def test_table_by_column_and_kpi_by_tile(self):
        t = drawn.groups({"type": "table"}, {"Identify | >60": 1, "Qualify | >60": 2, "Identify | <30": 3})
        self.assertEqual(t, {">60": [1.0, 2.0], "<30": [3.0]})
        k = drawn.groups({"type": "kpi"}, {"SUM(Sales)": 5, "Card": {"current": 1, "delta": 0.1}})
        self.assertEqual(k, {"SUM(Sales)": [5.0], "Card": [1.0, 0.1]})


class Judge(unittest.TestCase):
    def test_statuses(self):
        read = drawn.numbers(["10", "20"])
        status = lambda vals, dark, visible=True: drawn.judge("s", "g", vals, read, dark, visible).status  # noqa: E731
        self.assertEqual(status([10, 20], 0.02), drawn.OK)
        self.assertEqual(status([10, 30], 0.02), drawn.PARTIAL)
        self.assertEqual(status([30, 40], 0.0), drawn.FAIL)  # nothing drawn in its strip
        self.assertEqual(status([30, 40], 0.02), drawn.UNREAD)  # drawn, but OCR read none of it
        self.assertEqual(status([30, 40], 0.0, visible=False), drawn.UNCHECKED)

    def test_text_in_a_narrow_column_is_unread_not_fail(self):
        """A '#' column: its digits under INK_MIN of a wide strip; lines of text found there make it UNREAD."""
        self.assertEqual(drawn.judge("s", "#", [1, 2], [], 0.0025, True, text=True).status, drawn.UNREAD)
        self.assertEqual(drawn.judge("s", "#", [1, 2], [], 0.0025, True).status, drawn.FAIL)

    def test_ink(self):
        white = sc.solid(10, 10, (255, 255, 255))
        self.assertEqual(drawn.ink(white), 0.0)
        line_ = sc.paint(white, (0, 0, 10, 1), (51, 51, 51))  # a dark line: 10 % of the picture
        self.assertAlmostEqual(drawn.ink(line_), 0.1)
        self.assertEqual(drawn.ink(sc.solid(10, 10, (230, 230, 230))), 0.0)  # a registry's grey bar is no ink


class Cells(unittest.TestCase):
    """A strip's lines of text laid out on one line (decisions/098)."""

    def test_normalize_white_on_a_bar_and_dark_on_white(self):
        img = sc.paint(sc.solid(40, 10, (255, 255, 255)), (0, 0, 30, 10), (78, 121, 167))  # an accent bar
        img = sc.paint(sc.paint(img, (5, 3, 2, 4), (255, 255, 255)), (34, 3, 2, 4), (51, 51, 51))  # white on it, #333 off
        g = drawn.normalize(img)
        self.assertEqual((g[4 * 40 + 5], g[4 * 40 + 34]), (0, 51))  # both text dark
        self.assertEqual((g[4 * 40 + 15], g[4 * 40], g[4 * 40 + 29]), (255, 255, 255))  # the bar and its ends white

    def test_cells_are_lines_of_text_without_ticks(self):
        img = sc.solid(60, 100, (255, 255, 255))
        for y in (10, 50):
            img = sc.paint(img, (5, y, 12, 9), (51, 51, 51))  # two lines of 'text'
        img = sc.paint(img, (40, 0, 2, 100), (0, 0, 0))  # a tick down the strip: not text
        self.assertEqual(drawn.cells(drawn.normalize(img), 60, 100), [(5, 10, 12, 9), (5, 50, 12, 9)])
        self.assertIsNone(drawn.mosaic(sc.solid(60, 100, (255, 255, 255))))  # nothing drawn: no mosaic
        self.assertIsNone(drawn.mosaic(sc.paint(sc.solid(60, 100, (255, 255, 255)), (0, 0, 40, 100), (230,) * 3)))

    def test_mosaic_repeats_a_few_cells(self):
        img = sc.solid(30, 60, (255, 255, 255))
        for y in (10, 40):
            img = sc.paint(img, (5, y, 6, 9), (51, 51, 51))
        m = drawn.mosaic(img)
        self.assertGreater(m.w, 8 * 2 * 10)  # two cells laid 8 times, at twice their size
        self.assertLess(m.w, drawn.CELL_ROW_W + 100)

    def test_cell_words(self):
        words = [Word("1-2", 0, 0, 30, 12, 0), Word("47", 40, 0, 16, 12, 0), Word("811", 60, 0, 24, 12, 0)]
        self.assertEqual(drawn.tokens(drawn.cell_words(words)), ["1", "2", "47 811"])
        ru = [Word("1096", 0, 0, 30, 12, 0), Word("25,196", 40, 0, 40, 12, 0), Word("390/6", 90, 0, 40, 12, 0)]
        self.assertEqual(drawn.tokens(drawn.cell_words(ru, ru=True)), ["1096", "25,196", "10%", "25,1%", "39%"])


class Picture(unittest.TestCase):



    def test_parse_view(self):
        out = "SCROLL\t0\t225\t2270\t114\t21\t1276\r\nROOT\t271\t114\t1600\t1500\r\n"
        self.assertEqual(sc.parse_view(out), {"root": (271, 114, 1600, 1500), "scroll": (0, 225, 2270, 114, 21, 1276)})
        self.assertEqual(sc.parse_view("ROOT\t271,0\t114\t1280\t930\n")["scroll"], None)  # fits; a decimal comma
        self.assertIsNone(sc.parse_view("SCROLL\t0\t225\t1\t2\t3\t4\n"))  # no dashboard zone: not trusted



    def test_no_hover(self):
        """N8: the cursor leaves an active Tableau window for its title bar; anywhere else it stays."""
        class User32:
            def __init__(self, front, at):
                self.front, self.at, self.moved = front, at, None

            def GetForegroundWindow(self):
                return self.front

            def GetWindowRect(self, _, r):
                r._obj.left, r._obj.top, r._obj.right, r._obj.bottom = 100, 50, 500, 450

            def GetCursorPos(self, p):
                p._obj.x, p._obj.y = self.at

            def SetCursorPos(self, x, y):
                self.moved = (x, y)

        for front, at, moved in ((1, (300, 200), (300, 58)), (1, (50, 200), None), (2, (300, 200), None)):
            u = User32(front, at)
            with mock.patch.object(sc, "_win32", return_value=(u, None, wintypes)):
                sc._no_hover(1)
            self.assertEqual(u.moved, moved, (front, at))


ITSM = ROOT / "acceptance" / "itsm-incidents" / "spec.json"


class Marks(unittest.TestCase):
    """Bars, lines, areas (decisions/078): their colors from the book, looked for in the sheet's zone."""

    def test_mark_count(self):
        self.assertEqual(drawn.mark_count({"type": "bar"}, {"A": 3, "B": 0, "C": None, "D | x": 1, "D | y": 2}), 2)
        self.assertEqual(drawn.mark_count({"type": "bar"}, {"A": {"Fact": 1, "Plan": 2}, "B": {"Fact": 0}}), 1)
        self.assertEqual(drawn.mark_count({"type": "line"}, {"2025-01": 0, "2025-02": 4, "2025-03": None}), 2)


    def test_of_color_over_the_background(self):
        blue, white = drawn._rgb("#4e79a7"), (255, 255, 255)
        self.assertTrue(drawn.of_color(blue, [blue], white))
        self.assertTrue(drawn.of_color(drawn._rgb("#92adc8"), [blue], white))  # an area: ~62% over white
        self.assertFalse(drawn.of_color(drawn._rgb("#d3dde9"), [blue], white))  # 20%: an edge, not the mark
        self.assertFalse(drawn.of_color((150, 150, 150), [blue], white))  # grey text
        self.assertFalse(drawn.of_color(white, [blue], white))

    def test_look_counts_bars_and_spans_lines(self):
        img = sc.solid(200, 100, (255, 255, 255))
        for i in range(5):  # 5 vertical bars, 10 px wide, 6 px apart
            img = sc.paint(img, (10 + 16 * i, 40, 10, 50), (78, 121, 167))
        img = sc.paint(img, (0, 30, 200, 2), (78, 121, 167))  # a 2 px line across: not a bar
        got = drawn.look(img, ["#4e79a7"], horizontal=False)
        self.assertEqual(got["bars"], 5)
        line = sc.paint(sc.paint(sc.solid(200, 50, (255, 255, 255)), (10, 20, 80, 3), (78, 121, 167)),
                        (110, 20, 80, 3), (78, 121, 167))  # a line with a 20 px gap
        self.assertTrue(0.85 < drawn.look(line, ["#4e79a7"])["cover"] < drawn.LINE_COVER)
        thick = sc.solid(200, 100, (255, 255, 255))
        for i in range(4):  # 4 bars covering most of the zone: the background is still white (golden_multi_source)
            thick = sc.paint(thick, (20, 4 + 24 * i, 170, 20), (78, 121, 167))
        got = drawn.look(thick, ["#4e79a7"])
        self.assertEqual((got["visible"], got["bars"]), (["#4e79a7"], 4))

    def test_judge_marks(self):
        def status(kind, want, **seen):
            base = {"visible": ["#4e79a7"], "solid": 500, "share": 0.1, "bars": want, "cover": 1.0}
            return drawn.judge_marks("s", kind, want, {**base, **seen}).status
        self.assertEqual(status("bar", 6), drawn.OK)
        self.assertEqual(status("bar", 6, bars=5), drawn.OK)  # a bar too short to see
        self.assertEqual(status("bar", 6, bars=2), drawn.PARTIAL)
        self.assertEqual(status("bar", 6, solid=0, share=0.0, bars=0), drawn.FAIL)  # empty
        self.assertEqual(status("bar", 6, visible=[]), drawn.FAIL)  # white bars on white
        self.assertEqual(status("line", 12, cover=0.8), drawn.PARTIAL)
        self.assertEqual(drawn.judge_marks("s", "line", 12, None).status, drawn.UNCHECKED)  # a color ramp
        self.assertEqual(drawn.judge_marks("s", "bar", 6, None, visible=False).status, drawn.UNCHECKED)




    def run_on(self, book, picture):
        def capture(b, name, out):
            img = sc.load_png(picture)
            return img, (0, 0, img.w, img.h)
        return drawn.check(book, ITSM, Path(tempfile.mkdtemp()), capture_fn=capture, ocr_fn=lambda paths, **_: {})

    def marks(self, report):
        return {g["sheet"]: g for g in report["groups"] if g["kind"] == "marks"}




def _ocr_works():
    try:
        ocr.words([FIX / "ok_revenue.png"])
        return True
    except (RuntimeError, OSError):
        return False


