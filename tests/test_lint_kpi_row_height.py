"""D12 (decisions/122): a row of KPI cards too short for the build's check gets a lint warning with row_heights."""
import copy
import json
import re
import unittest
from pathlib import Path

from tbuilder.design_lint import lint

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "acceptance" / "table_kpi"


def d12(spec, base=CASE):
    return [f for f in lint(spec, base) if f.rule == "D12"]


class KpiRowHeightTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))

    def with_weights(self, weights, height=960):
        s = copy.deepcopy(self.spec)
        s["dashboard"].update(row_heights=weights, height=height)
        return s

    def test_authors_row_heights_are_clean(self):
        self.assertEqual(d12(self.spec), [])  # [4, 8]
        self.assertEqual(d12(self.with_weights([1, 1])), [])  # equal weights: the build accepts them at 960

    def test_light_kpi_row_is_flagged_with_the_weights(self):
        f = d12(self.with_weights([1, 3]))  # the build refuses this one: "too short for a KPI card"
        self.assertEqual([x.level for x in f], ["warn"])
        self.assertIn("row_heights [2, 3]", f[0].text)

    def test_advised_weights_are_clean(self):
        s = self.with_weights([1, 6])
        advice = re.search(r"row_heights (\[[^\]]*\])", d12(s)[0].text).group(1)
        self.assertEqual(d12(self.with_weights(json.loads(advice))), [])

    def test_short_dashboard_gets_a_heavier_row(self):
        f = d12(self.with_weights([1, 1], height=500))
        self.assertEqual(len(f), 1)
        self.assertIn("row_heights [2, 1]", f[0].text)

    def test_no_weight_helps_a_very_low_dashboard(self):
        f = d12(self.with_weights([1, 1], height=300))
        self.assertIn("more height", f[0].text)

    def test_existing_specs_are_clean(self):
        for path in sorted(ROOT.glob("specs/*.json")) + sorted(ROOT.glob("acceptance/*/spec.json")):
            with self.subTest(spec=path.relative_to(ROOT).as_posix()):
                self.assertEqual(d12(json.loads(path.read_text(encoding="utf-8")), path.parent), [])


if __name__ == "__main__":
    unittest.main()
