"""Parameters v2 (decisions/148): aliases of list values, Bottom N, Top N on line / table / heatmap / registry, a
parameter in a KPI tile heading, tie order, and the refusals of each."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tbuilder import params
from tbuilder.build import build_file
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT

SRC = ROOT / "specs" / "params_v2.json"
SPEC = json.loads(SRC.read_text(encoding="utf-8"))


def run(spec):
    d = Path(tempfile.mkdtemp())
    spec = copy.deepcopy(spec)
    spec["datasource"]["path"] = str((SRC.parent / spec["datasource"]["path"]).resolve())
    (d / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return build_file(d / "spec.json", d / "out.twbx")


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


class ParamsV2(unittest.TestCase):
    def test_builds_and_passes_the_gate(self):
        run(SPEC)

    def test_bottom_is_ascending_end_bottom(self):
        spec = copy.deepcopy(SPEC)
        for s in spec["sheets"]:
            if s.get("top") and s["top"].get("end") == "bottom":
                validate(spec)

    def test_ties_alphabetical_for_both_ends(self):
        rows = [{"k": k, "v": v} for k, v in [("D", 30), ("C", 30), ("F", 20), ("E", 20), ("B", 40), ("A", 50)]]
        key, val = (lambda r: r["k"]), (lambda g: sum(r["v"] for r in g))
        self.assertEqual(params.top_members(rows, key, val, 3, "t"), {"A", "B", "C"})
        self.assertEqual(params.top_members(rows, key, val, 2, "t", bottom=True), {"E", "F"})
        self.assertEqual(params.top_members(rows, key, val, 3, "t", bottom=True), {"C", "E", "F"})

    def test_bottom_with_ascending_refused_by_gate(self):
        import zipfile
        import xml.etree.ElementTree as ET
        from tbuilder import gate
        out = run(SPEC)
        out = out[0] if isinstance(out, tuple) else out
        with zipfile.ZipFile(out) as z:
            root = ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        self.assertEqual(gate.check_top_by(root), [])
        bottoms = [g for g in root.iter("groupfilter") if g.get("end") == "bottom"]
        self.assertTrue(bottoms)
        bottoms[0].find("groupfilter[@function='order']").set("direction", "ASC")
        self.assertTrue(any("DESC" in i.message for i in gate.check_top_by(root)))

    def test_alias_of_a_missing_value_refused(self):
        spec = copy.deepcopy(SPEC)
        spec["parameters"][0]["aliases"]["Mars"] = "Red planet"
        with self.assertRaises(ValueError):
            run(spec)

    def test_alias_on_a_range_refused(self):
        spec = copy.deepcopy(SPEC)
        spec["parameters"][2]["aliases"] = {"0.25": "Quarter"}
        with self.assertRaises(ValueError):
            run(spec)

    def test_duplicate_alias_refused(self):
        spec = copy.deepcopy(SPEC)
        spec["parameters"][0]["aliases"] = {"North": "Same", "South": "Same"}
        with self.assertRaises(Exception):
            run(spec)

    def test_wrong_default_type_refused(self):
        spec = copy.deepcopy(SPEC)
        spec["parameters"][1]["default"] = "three"
        with self.assertRaises((ValueError, SpecError)):
            run(spec)

    def test_bad_end_refused(self):
        spec = copy.deepcopy(SPEC)
        sheet(spec, "Top Bar")["top"]["end"] = "middle"
        with self.assertRaises(SpecError):
            validate(spec)

    def test_heading_with_a_parameter(self):
        spec = copy.deepcopy(SPEC)
        sheet(spec, "KPI")["measures"][0]["heading"] = "Sales in [Region pick]"
        run(spec)

    def test_top_on_other_sheet_types_has_an_expected_member_set(self):
        for name in ("Top Line", "Top Table", "Top Heat", "Top Registry"):
            with self.subTest(sheet=name):
                self.assertIn("n", sheet(SPEC, name)["top"])



class Golden(unittest.TestCase):
    def test_expected_matches_the_golden_json(self):
        from tbuilder import expected
        got = expected.compute(SPEC, ROOT / "data" / "sample" / "params_v2.csv")
        want = json.loads((ROOT / "golden" / "expected" / "golden_params_v2_2025_1.json").read_text(encoding="utf-8"))
        checked = 0
        for sheet, marks in got.items():
            if sheet not in want:
                continue
            for k, v in marks.items():
                self.assertIn(k, want[sheet], (sheet, k))
                w = want[sheet][k]
                if isinstance(w, dict):
                    continue
                self.assertTrue(abs(v - w) < 1e-3, (sheet, k, v, w))
                checked += 1
            self.assertEqual(set(marks), set(want[sheet]), sheet)
        self.assertGreater(checked, 10)


if __name__ == "__main__":
    unittest.main()
