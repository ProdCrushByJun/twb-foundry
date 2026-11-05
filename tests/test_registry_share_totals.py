"""decisions/109: a registry share is the part of the whole source (a FIXED LOD), not of the visible top N; delta and
share (and a guarded rank) take a registry total; track / dot / tick / highlight too since decisions/134."""
import copy
import json
import unittest
from pathlib import Path

from tbuilder import registry
from tbuilder.build import build
from tbuilder.expected import compute, data_path
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry_totals.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_share_totals_test.twbx"


def variant(top=None, totals=True, extra=()):
    spec = copy.deepcopy(SPEC)
    sh = spec["sheets"][0]
    sh["columns"] = [{"measure": {"field": "Sales"}, "style": "text", "label": "Sales"},
                     {"measure": {"field": "Sales"}, "style": "share", "label": "Share"}] + list(extra)
    if top:
        sh["top"] = {"n": top}
        sh["sort"] = "desc"
    if not totals:
        sh.pop("totals")
    return spec


def calcs(spec):
    return {c["name"]: c for c in registry.calcs(spec, {"Sales", "Profit"})}


def regions(spec):
    return compute(spec, data_path(spec, SPECS))["Regions"]


class ShareDenominator(unittest.TestCase):
    def test_formula_is_fixed_and_not_a_table_calc(self):
        share = calcs(variant(top=2))["Regions · Share · Share"]
        self.assertEqual(share["formula"], "[Sales] / MAX({FIXED : [Sales]})")
        self.assertNotIn("compute_using", share)

    def test_top_n_keeps_the_grand_total_denominator(self):
        full = regions(variant(totals=False))
        top = regions(variant(top=2, totals=False))
        whole = sum(r["Sales"] for r in full.values())
        self.assertEqual(len(top), 2)
        self.assertLess(sum(r["Sales"] for r in top.values()), whole)
        for k, row in top.items():
            self.assertAlmostEqual(row["Share"], full[k]["Share"])
            self.assertAlmostEqual(row["Share"], row["Sales"] / whole)

    def test_shares_of_all_rows_sum_to_one(self):
        self.assertAlmostEqual(sum(r["Share"] for r in regions(variant(totals=False)).values()), 1.0)


class TotalsTakeNewColumns(unittest.TestCase):
    def test_share_total_is_100_percent(self):
        self.assertAlmostEqual(regions(variant())["TOTAL"]["Share"], 1.0)

    def test_delta_builds_under_totals(self):
        delta = {"measure": {"field": "Sales"}, "style": "delta", "label": "Change", "base": {"field": "Profit"}}
        self.assertTrue(build(variant(extra=[delta]), OUT, SPECS).exists())

    def test_rank_track_and_highlight_build_under_totals(self):  # decisions/134
        for extra in [{"measure": {"field": "Sales"}, "style": "rank", "label": "R"},
                      {"measure": {"field": "Sales"}, "style": "track", "label": "T"},
                      {"measure": {"field": "Sales"}, "style": "bar", "label": "B", "highlight": {"above": 1}}]:
            with self.subTest(style=extra["style"]):
                self.assertTrue(build(variant(extra=[extra]), OUT, SPECS).exists())

    def test_pill_stays_refused(self):
        pill = {"measure": {"field": "Sales"}, "style": "pill", "label": "P", "levels": [{"label": "Low", "color": "bad"}, {"from": 1, "label": "High", "color": "good"}]}
        with self.assertRaisesRegex(ValueError, "is pill: .*drop the totals"):
            build(variant(extra=[pill]), OUT, SPECS)


if __name__ == "__main__":
    unittest.main()
