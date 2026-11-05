"""KPI card compare for a ratio measure (decisions/110): `per` makes SUM(field) / SUM(per) of a period and its change
is in percentage points ('+1.6 pp'). Found in the table_kpi acceptance case (103)."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import cards
from tbuilder.build import build
from test_roundtrip import OUT, ROOT

FOLDER = ROOT / "acceptance" / "table_kpi"


def spec_of():
    return json.loads((FOLDER / "spec.json").read_text(encoding="utf-8"))


def card(spec):
    return next(s for s in spec["sheets"] if s["type"] == "kpi")


def margin(spec):
    return next(m for m in card(spec)["measures"] if cards.is_ratio(m))


def plain(spec):
    return next(m for m in card(spec)["measures"] if not cards.is_ratio(m))


def built(spec):
    out = build(spec, OUT / "kpi_ratio.twbx", FOLDER)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


class KpiRatio(unittest.TestCase):
    def test_calcs_are_ratios_and_change_is_pp(self):
        spec = spec_of()
        got = {c["name"]: c for c in cards.calcs(spec)}
        n = cards.names(card(spec), margin(spec))
        cur = got[n["current"]]["formula"]
        self.assertEqual(cur.count("SUM(IF"), 2)
        self.assertIn("[Profit]", cur)
        self.assertIn("[Sales]", cur)
        self.assertIn(") / SUM(", cur)
        self.assertEqual(got[n["delta"]]["formula"], f"([{n['current']}] - [{n['previous']}]) * 100")
        self.assertEqual(got[n["good"]]["format"], "delta_pp")
        self.assertEqual(got[n["bad"]]["format"], "delta_pp")

    def test_plain_measure_keeps_relative_change(self):
        spec = spec_of()
        got = {c["name"]: c for c in cards.calcs(spec)}
        n = cards.names(card(spec), plain(spec))
        self.assertEqual(got[n["delta"]]["formula"], f"([{n['current']}] - [{n['previous']}]) / ABS([{n['previous']}])")
        self.assertEqual(got[n["delta"]]["format"], "percent")
        self.assertEqual(got[n["good"]]["format"], "delta")

    def test_expected_change_in_pp(self):
        ref = json.loads((FOLDER / "expected.json").read_text(encoding="utf-8"))["spec.json"]["KPI"]["Profit margin"]
        self.assertAlmostEqual(ref["delta"], (ref["current"] - ref["previous"]) * 100, places=6)
        self.assertAlmostEqual(ref["delta"], 1.6, delta=0.05)

    def test_builds_with_pp_format(self):
        root = built(spec_of())
        fmts = [c.get("default-format") for c in root.find("datasources").iter("column")
                if c.get("caption", "").startswith("KPI · Profit margin · Change ")]
        self.assertEqual(len(fmts), 2)
        self.assertTrue(all(f == cards.DELTA_PP_FORMAT for f in fmts), fmts)

    def test_abs_pct_is_refused_for_a_ratio(self):
        spec = spec_of()
        card(spec)["delta"] = "abs_pct"
        with self.assertRaises(Exception):
            built(spec)

    def test_per_must_be_a_number_column(self):
        spec = spec_of()
        margin(spec)["per"] = "Region"
        with self.assertRaises(Exception):
            built(spec)

    def test_ratio_needs_sum(self):
        spec = spec_of()
        margin(spec)["agg"] = "avg"
        with self.assertRaises(Exception):
            built(spec)


if __name__ == "__main__":
    unittest.main()
