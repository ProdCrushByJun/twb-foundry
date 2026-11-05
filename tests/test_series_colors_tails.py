"""The tails of decisions/133 (decisions/135): the color of a single series, the ends of a color scale, a legend
whose only mark is the colored text. Needs Chrome; skipped otherwise."""
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

BARS = """<div><h3>Freight Cost by month</h3><div><svg width="300" height="120" style="position:absolute;left:10px;top:40px">
<rect x="20" y="60" width="30" height="50" fill="#e07b39"/><rect x="60" y="40" width="30" height="70" fill="#e07b39"/>
<rect x="100" y="20" width="30" height="90" fill="#e07b39"/><rect x="140" y="30" width="30" height="80" fill="#e07b39"/></svg></div></div>"""

GREENS = ["#f0f9e8", "#d3eec8", "#b4e2ae", "#8fd1a6", "#6bbfb0", "#4aa3b4", "#2f7fa8"]
HEAT = "<div><h3>Freight Cost heatmap</h3><svg width='300' height='60' style='position:absolute;left:10px;top:40px'>" + "".join(
    f"<rect x='{i * 40}' y='10' width='38' height='38' fill='{c}'/>" for i, c in enumerate(GREENS)) + "</svg></div>"

TEXT_LEGEND = """<div style="position:absolute;left:10px;top:200px"><span style="color:#e07b39;font-weight:bold">RapidHaul</span>
<span style="color:#2f6fb5;font-weight:bold;margin-left:12px">BlueLine</span></div>"""


def run(body, *kinds):
    with tempfile.TemporaryDirectory() as tmp:
        h, c = Path(tmp, "p.html"), Path(tmp, "d.csv")
        h.write_text(f"<html><head><title>t</title></head><body>{body}</body></html>", encoding="utf-8")
        c.write_text(CSV, encoding="utf-8")
        return [e for e in match(html_outline.outline(h), c) if e["kind"] in kinds]


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class SeriesColorsTails(unittest.TestCase):
    def test_single_series_color(self):
        ev = run(BARS, "measure_color", "series_colors")
        self.assertEqual([e["kind"] for e in ev], ["measure_color"])
        self.assertEqual(ev[0]["color"], "#E07B39")
        self.assertEqual([c["field"] for c in ev[0]["candidates"]], ["Freight Cost"])

    def test_color_scale_ends(self):
        ev = run(HEAT, "color_scale", "measure_color")
        self.assertEqual([e["kind"] for e in ev], ["color_scale"])
        self.assertEqual((ev[0]["low"], ev[0]["high"]), ("#F0F9E8", "#2F7FA8"))

    def test_text_only_legend(self):
        ev = run(TEXT_LEGEND, "series_colors")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["series"], {"RapidHaul": "#E07B39", "BlueLine": "#2F6FB5"})
        self.assertEqual(ev[0]["candidates"][0]["field"], "Carrier")


if __name__ == "__main__":
    unittest.main()
