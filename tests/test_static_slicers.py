"""Static slicers (caption + value(s) in plain markup) are controls when the data backs them (decisions/112).
Needs Chrome; skipped otherwise."""
import tempfile
import unittest
from pathlib import Path

from tbuilder import html_outline
from tbuilder.match import match

try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False

CSV = """Ship Date,Region,Carrier,Freight Cost
2024-01-05,Northeast,RapidHaul,100
2024-02-05,Midwest,BlueLine,200
2025-03-05,Southwest,RapidHaul,300
2025-04-05,Northeast,BlueLine,400
"""

CSS = """<style>body{font-family:Arial} .sl{position:absolute;top:10px;height:44px;width:200px;background:#2b4c7a;color:#fff}
.sl .a{position:absolute;right:10px;top:14px;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid #fff}
.row{position:absolute;top:80px;left:10px}.row span{margin-right:8px;padding:4px}</style>"""


def run(body):
    with tempfile.TemporaryDirectory() as tmp:
        h, c = Path(tmp, "p.html"), Path(tmp, "d.csv")
        h.write_text(f"<html><head><title>t</title>{CSS}</head><body>{body}</body></html>", encoding="utf-8")
        c.write_text(CSV, encoding="utf-8")
        outline = html_outline.outline(h)
        return outline, [e for e in match(outline, c) if e["id"] == "control"]


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class StaticSlicers(unittest.TestCase):
    def test_bi_export_like_slicers(self):
        o, ev = run('<div class="sl" style="left:10px"><div>Year</div><div>2024 - 2025</div><div class="a"></div></div>'
                    '<div class="sl" style="left:230px"><div>Region</div><div>All</div><div class="a"></div></div>')
        self.assertEqual([c["kind"] for c in o["controls"]], ["slicer", "slicer"])
        self.assertEqual([c["selected"] for c in o["controls"]], [["2024 - 2025"], ["All"]])
        self.assertEqual(ev[0]["candidates"][0]["field"], "Ship Date")  # a date part over the one date column
        self.assertEqual(ev[1]["candidates"][0]["field"], "Region")

    def test_chips_match_column_values(self):
        o, ev = run('<div class="row"><b>Carrier</b><span>RapidHaul</span><span>BlueLine</span></div>')
        self.assertEqual(o["controls"][0]["options"], ["RapidHaul", "BlueLine"])
        self.assertEqual(ev[0]["candidates"][0]["field"], "Carrier")

    def test_legend_gets_no_candidate(self):
        o, ev = run('<div class="row"><b>Legend</b><span>Alpha</span><span>Beta</span></div>')
        self.assertTrue(all(not e["candidates"] for e in ev))

    def test_kpi_card_is_not_a_slicer(self):
        o, ev = run('<div class="sl" style="left:10px"><div>Freight Cost</div><div style="font-size:30px">1,000</div></div>')
        self.assertEqual([c for c in o["controls"] if c["kind"] == "slicer"], [])


if __name__ == "__main__":
    unittest.main()
