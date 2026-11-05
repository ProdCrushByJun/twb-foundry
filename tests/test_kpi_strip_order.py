"""The echarts KPI strip, end to end on the sheet XML (decisions/117): the 097 P1 finding
(captions ignored, alphabetical tiles) was closed by 106; this pins it on the worksheet itself:
filter members, manual order and aliases agree with the spec for all four tiles, calcs included."""
import json
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASE = ROOT / "acceptance" / "echarts"


class KpiStripOrder(unittest.TestCase):
    def test_echarts_sheet_follows_spec(self):
        spec = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
        out = build(spec, OUT / "kpi_strip_order_echarts.twbx", CASE)
        with zipfile.ZipFile(out) as z:
            root = ET.fromstring(z.read(out.stem + ".twb"))
        labels = [m["label"] for s in spec["sheets"] if s["type"] == "kpi" for m in s["measures"]]
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "KPI")
        sort = [b.text.strip('"') for b in next(ws.iter("manual-sort")).iter("bucket")]
        members = [re.sub(r'^"|"$', "", m.get("member")) for m in ws.iter("groupfilter") if m.get("function") == "member"]
        col = next(c for c in root.find("datasources").iter("column") if c.get("name") == "[:Measure Names]")
        alias = {a.get("key").strip('"'): a.get("value") for a in col.iter("alias")}
        self.assertEqual([alias[k] for k in sort], labels)
        self.assertEqual(members, sort)


if __name__ == "__main__":
    unittest.main()
