"""analyze reads the colors of chart series from the legend and proposes them for fields.<f>.color (decisions/133).
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

CSV = """Ship Date,Carrier,Freight Cost
2024-01-05,RapidHaul,100
2024-02-05,BlueLine,200
2025-03-05,RapidHaul,300
2025-04-05,BlueLine,400
"""

SVG_YEARS = """<svg width="400" height="200" style="position:absolute;left:10px;top:10px">
<rect x="20" y="80" width="30" height="100" fill="#118DFF"/><rect x="52" y="60" width="30" height="120" fill="#12239E"/>
<g transform="translate(250,6)"><rect x="0" y="0" width="10" height="10" fill="#118DFF"/><text x="14" y="9">2024</text>
<rect x="56" y="0" width="10" height="10" fill="#12239E"/><text x="70" y="9">2025</text></g></svg>"""

HTML_CARRIERS = """<div style="position:absolute;left:10px;top:250px">
<span style="display:inline-block;width:10px;height:10px;background:#e07b39"></span> <span>RapidHaul</span>
<span style="display:inline-block;width:10px;height:10px;background:#2f6fb5;margin-left:12px"></span> <span>BlueLine</span></div>"""

SVG_BARS_ONLY = """<svg width="300" height="120" style="position:absolute;left:10px;top:10px">
<rect x="20" y="20" width="8" height="8" fill="#111111"/><text x="32" y="28">12</text>
<rect x="20" y="50" width="40" height="8" fill="#222222"/><text x="64" y="58">34</text></svg>"""


def run(body):
    with tempfile.TemporaryDirectory() as tmp:
        h, c = Path(tmp, "p.html"), Path(tmp, "d.csv")
        h.write_text(f"<html><head><title>t</title></head><body>{body}</body></html>", encoding="utf-8")
        c.write_text(CSV, encoding="utf-8")
        outline = html_outline.outline(h)
        return outline, [e for e in match(outline, c) if e["kind"] == "series_colors"]


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class SeriesColors(unittest.TestCase):
    def test_svg_legend_years(self):
        o, ev = run(SVG_YEARS)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["series"], {"2024": "#118DFF", "2025": "#12239E"})
        c = ev[0]["candidates"][0]
        self.assertEqual((c["field"], c["date_part"]), ("Ship Date", "year"))

    def test_html_legend_column_values(self):
        o, ev = run(HTML_CARRIERS)
        self.assertEqual(ev[0]["series"], {"RapidHaul": "#E07B39", "BlueLine": "#2F6FB5"})
        c = ev[0]["candidates"][0]
        self.assertEqual(c["field"], "Carrier")
        self.assertEqual(c["spec"], {"fields": {"Carrier": {"color": {"RapidHaul": "#E07B39", "BlueLine": "#2F6FB5"}}}})

    def test_caption_case_follows_the_data(self):
        o, ev = run(HTML_CARRIERS.replace("RapidHaul", "RAPIDHAUL"))
        self.assertEqual(list(ev[0]["candidates"][0]["color"]), ["RapidHaul", "BlueLine"])

    def test_bars_with_labels_are_not_a_legend(self):
        o, ev = run(SVG_BARS_ONLY)
        self.assertEqual(ev, [])


if __name__ == "__main__":
    unittest.main()
