"""The KPI table (strip) under the spec's own captions, in the spec's order, with whole sums shown whole
(decisions/106): found in the echarts and plotly acceptance cases."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASES = {n: (ROOT / "acceptance" / n) for n in ("echarts", "plotly")}


def built(case, spec=None):
    folder = CASES[case]
    spec = spec or json.loads((folder / "spec.json").read_text(encoding="utf-8"))
    out = build(spec, OUT / f"kpi_strip_{case}.twbx", folder)
    with zipfile.ZipFile(out) as z:
        return spec, ET.fromstring(z.read(out.stem + ".twb"))


def kpi_sheet(spec):
    return next(s for s in spec["sheets"] if s["type"] == "kpi")


def member(inst):
    """'[ds].[sum:Revenue:qk]' -> the instance name."""
    return inst.split(".", 1)[1]


class KpiStrip(unittest.TestCase):
    def test_captions_are_the_spec_labels(self):
        for case in CASES:
            spec, root = built(case)
            col = next(c for c in root.find("datasources").iter("column") if c.get("name") == "[:Measure Names]")
            got = [a.get("value") for a in col.iter("alias")]
            self.assertEqual(sorted(got), sorted(m["label"] for m in kpi_sheet(spec)["measures"]), case)

    def test_columns_in_spec_order(self):
        for case in CASES:
            spec, root = built(case)
            ws = next(w for w in root.iter("worksheet") if w.get("name") == kpi_sheet(spec)["name"])
            sort = next(m for m in ws.iter("manual-sort") if m.get("column").endswith("[:Measure Names]"))
            order = [b.text.strip('"') for b in sort.iter("bucket")]
            col = next(c for c in root.find("datasources").iter("column") if c.get("name") == "[:Measure Names]")
            label = {a.get("key").strip('"'): a.get("value") for a in col.iter("alias")}
            self.assertEqual([label[k] for k in order], [m["label"] for m in kpi_sheet(spec)["measures"]], case)

    def test_whole_sum_has_no_fraction(self):
        spec, root = built("plotly")
        formats = {c.get("caption", c.get("name")): c.get("default-format")
                   for c in root.find("datasources").iter("column")}
        self.assertEqual(formats["Hire Flag"], "n#,##0;-#,##0")
        self.assertEqual(formats["Exit Flag"], "n#,##0;-#,##0")

    def test_spec_format_wins_and_averages_stay_fractional(self):
        spec, root = built("echarts")
        cols = {c.get("caption", c.get("name")): c.get("default-format") for c in root.find("datasources").iter("column")}
        cols["Revenue"] = next(c.get("default-format") for c in root.find("datasources").iter("column")
                               if c.get("name") == "[Revenue]")
        self.assertTrue(cols["Revenue"].startswith("c"))  # its own currency format, not the whole number
        self.assertNotEqual(cols.get("Avg Order Value"), "n#,##0;-#,##0")

    def test_duplicate_labels_are_refused(self):
        spec = copy.deepcopy(json.loads((CASES["plotly"] / "spec.json").read_text(encoding="utf-8")))
        ms = kpi_sheet(spec)["measures"]
        ms[1]["label"] = ms[0]["label"]
        with self.assertRaises(ValueError):
            built("plotly", spec)


if __name__ == "__main__":
    unittest.main()
