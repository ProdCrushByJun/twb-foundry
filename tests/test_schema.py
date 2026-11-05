"""spec.schema.json: real specs pass, structural mistakes are rejected with a precise path."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tbuilder import spec as spec_mod
from tbuilder.build import build
from test_roundtrip import OUT, SPECS

GOLDEN = json.loads((SPECS / "golden.json").read_text(encoding="utf-8"))


def mutate(fn):
    s = copy.deepcopy(GOLDEN)
    fn(s)
    return s


class ValidSpecs(unittest.TestCase):
    def test_all_spec_files_validate(self):
        files = sorted(SPECS.glob("*.json"))
        self.assertGreaterEqual(len(files), 2)
        for f in files:
            with self.subTest(spec=f.name):
                spec_mod.load(f)

    def test_minimal_spec(self):
        spec_mod.validate({
            "version": 1,
            "datasource": {"type": "csv", "path": "x.csv"},
            "sheets": [{"name": "A", "type": "kpi", "measures": [{"field": "Sales"}]}],
            "dashboard": {"name": "D", "grid": [["A"]]},
        })

    def test_headers_on_every_sheet_type(self):
        def f(s):
            s["dashboard"].update(title="**Sales** Overview", subtitle="Data updated: 2023-12-31")
            for sh in s["sheets"]:
                sh.update(title="Block **Title**", subtitle="click to filter")
        spec_mod.validate(mutate(f))


class InvalidSpecs(unittest.TestCase):
    def assertInvalid(self, spec, where, msg=""):
        with self.assertRaises(spec_mod.SpecError) as cm:
            spec_mod.validate(spec)
        text = str(cm.exception)
        self.assertIn(f"- {where}:", text)
        self.assertIn(msg, text)

    def test_missing_version(self):
        self.assertInvalid(mutate(lambda s: s.pop("version")), "(root)", "'version' is a required property")

    def test_wrong_version(self):
        self.assertInvalid(mutate(lambda s: s.update(version=2)), "version")

    def test_unknown_top_level_key(self):
        self.assertInvalid(mutate(lambda s: s.update(theme={})), "(root)", "'theme' was unexpected")

    def test_typo_in_sheet_property(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1].update(colour="Category")), "sheets/1", "'colour' was unexpected")

    def test_property_of_other_sheet_type(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][0].update(dimension="Region")), "sheets/0", "'dimension' was unexpected")

    def test_kpi_without_measures(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][0].pop("measures")), "sheets/0", "'measures' is a required property")

    def test_kpi_empty_measures(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][0].update(measures=[])), "sheets/0/measures")

    def test_line_without_date(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][2].pop("date")), "sheets/2", "'date' is a required property")

    def test_bad_agg(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1]["measure"].update(agg="stdev")), "sheets/1/measure/agg")

    def test_bad_date_level(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][2]["date"].update(level="hour")), "sheets/2/date/level")

    def test_bad_orientation(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1].update(orientation="diagonal")), "sheets/1/orientation")

    def test_unknown_sheet_type(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1].update(type="pie")), "sheets/1/type")

    def test_unsafe_name(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][0].update(name="Bob's KPI")), "sheets/0/name")

    def test_empty_grid_row(self):
        self.assertInvalid(mutate(lambda s: s["dashboard"]["grid"].append([])), "dashboard/grid/2")

    def test_dashboard_too_small(self):
        self.assertInvalid(mutate(lambda s: s["dashboard"].update(width=100)), "dashboard/width")

    def test_non_csv_datasource(self):
        self.assertInvalid(mutate(lambda s: s["datasource"].update(path="data.xlsx")), "datasource/path")

    def test_reports_all_errors_at_once(self):
        def bad(s):
            s.pop("version")
            s["sheets"][1]["measure"]["agg"] = "stdev"
            s["dashboard"]["width"] = 1
        with self.assertRaises(spec_mod.SpecError) as cm:
            spec_mod.validate(mutate(bad))
        self.assertEqual(str(cm.exception).count("\n  - "), 3)

    def test_sort_only_on_bar(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][2].update(sort="desc")), "sheets/2")

    def test_style_only_on_kpi(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1].update(style="tiles")), "sheets/1")

    def test_unsafe_subtitle(self):
        self.assertInvalid(mutate(lambda s: s["sheets"][1].update(subtitle="a < b")), "sheets/1/subtitle")

    def test_block_headers_is_boolean(self):
        self.assertInvalid(mutate(lambda s: s.update(block_headers="yes")), "block_headers")

    def test_grid_cell_width_bounds(self):
        self.assertInvalid(mutate(lambda s: s["dashboard"]["grid"][0].append({"sheet": "X", "width": 0})),
                           "dashboard/grid/0/2")


class BuildGate(unittest.TestCase):
    def test_invalid_spec_writes_nothing(self):
        out = OUT / "should_not_exist.twbx"
        out.unlink(missing_ok=True)
        with self.assertRaises(spec_mod.SpecError):
            build(mutate(lambda s: s.update(theme={})), out, SPECS)
        self.assertFalse(out.exists())

    def test_missing_csv(self):
        with self.assertRaisesRegex(spec_mod.SpecError, "Datasource not found"):
            build(mutate(lambda s: s["datasource"].update(path="nope.csv")), OUT / "x.twbx", SPECS)

    def test_invalid_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.json"
            p.write_text("{ not json", encoding="utf-8")
            with self.assertRaisesRegex(spec_mod.SpecError, "not valid JSON"):
                spec_mod.load(p)



if __name__ == "__main__":
    unittest.main()
