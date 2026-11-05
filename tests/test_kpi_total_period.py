"""acceptance/plotly KPI (decisions/131): the page shows whole-period totals with no comparison.
The 102 P2 "K1 only" debt is stale: the strip (106) already gives period totals; this pins it
on the worksheet: no date field on the sheet, captions and order from the spec, totals from the CSV."""
import csv
import json
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASE = ROOT / "acceptance" / "plotly"


class KpiTotalPeriod(unittest.TestCase):
    def test_plotly_kpi_is_period_total(self):
        spec = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
        kpi = next(s for s in spec["sheets"] if s["type"] == "kpi")
        self.assertEqual([m["label"] for m in kpi["measures"]], ["Hires", "Exits", "Net headcount change"])
        self.assertFalse(any("compare" in m or "per" in m for m in kpi["measures"]))
        out = build(spec, OUT / "kpi_total_period_plotly.twbx", CASE)
        with zipfile.ZipFile(out) as z:
            root = ET.fromstring(z.read(out.stem + ".twb"))
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "KPI")
        used = " ".join(c.get("column", "") for c in ws.iter("column-instance")) + " ".join(
            d.get("column", "") for d in ws.iter("datasource-dependencies"))
        self.assertNotIn("Event Date", ET.tostring(ws, encoding="unicode"))
        self.assertNotRegex(used, r"tmn|tyr|tqr")
        self.assertIn("Net Change", ET.tostring(ws, encoding="unicode"))

    def test_totals_match_csv(self):
        with (CASE / "hr_events.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        hires = sum(r["Event Type"] == "Hire" for r in rows)
        exits = sum(r["Event Type"] == "Exit" for r in rows)
        exp = json.loads((CASE / "expected.json").read_text(encoding="utf-8"))
        self.assertIn(str(hires - exits), json.dumps(exp))


if __name__ == "__main__":
    unittest.main()
