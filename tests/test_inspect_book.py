"""inspect (decisions/188): read-only listing of golden books; Hyper warning of patch on golden_hyper."""
import subprocess
import sys
import unittest
from pathlib import Path

from tbuilder import inspect_book, patch
from tbuilder.restyle import read_twb

ROOT = Path(__file__).resolve().parent.parent
G = ROOT / "golden"


class Inspect(unittest.TestCase):
    def test_actions_golden(self):
        t = inspect_book.inspect_text(G / "golden_actions_2025_1.twbx")
        for s in ("DATASOURCES (1):", "WORKSHEETS (5):", "  - By Region", "DASHBOARDS (1):", "  - Actions",
                  "name: [Calculation_6747044442003939108]", "= MIN(1)", "TOTAL calculated fields: 1"):
            self.assertIn(s, t)
        self.assertNotIn("PARAMETERS", t)

    def test_params_book(self):
        t = inspect_book.inspect_text(G / "golden_params_2025_1.twbx")
        self.assertIn("PARAMETERS (3):", t)
        self.assertIn("  - Top N  (current=8)", t)
        self.assertIn("CALCULATED FIELDS in [sales_products] (2):", t)  # the 3 parameters are not listed as calcs
        self.assertIn("TOTAL calculated fields: 2", t)

    def test_twb_and_cli(self):
        twb = G / "golden_actions_2025_1.twb"
        self.assertIn("WORKSHEETS (5):", inspect_book.inspect_text(twb))
        r = subprocess.run([sys.executable, "-m", "tbuilder", "inspect", str(twb)], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DASHBOARDS (1):", r.stdout)

    def test_read_only(self):
        p = G / "golden_actions_2025_1.twbx"
        before = p.read_bytes()
        inspect_book.inspect_text(p)
        self.assertEqual(p.read_bytes(), before)


class HyperWarnings(unittest.TestCase):
    """golden_hyper: the data is a .hyper source. XML cannot add data to it (decisions/188)."""

    @classmethod
    def setUpClass(cls):
        cls.raw = read_twb(G / "golden_hyper_2025_1.twbx")

    def test_calc_on_existing_column_ok(self):
        _, rep = patch.patch_xml(self.raw, [{"op": "add_calc", "name": "Dbl", "formula": "SUM([Sales]) * 2"}])
        self.assertEqual(rep.warnings, [])

    def test_calc_on_missing_column_refused(self):
        with self.assertRaises(ValueError):
            patch.patch_xml(self.raw, [{"op": "add_calc", "name": "Ghost", "formula": "SUM([No Such Column])"}])

    def test_sql_has_nothing_to_edit(self):
        with self.assertRaisesRegex(ValueError, "no Custom SQL"):
            patch.patch_xml(self.raw, [{"op": "sql", "sql": "select 1"}])

    def test_rename_is_caption_only(self):
        _, rep = patch.patch_xml(self.raw, [{"op": "rename", "field": "Sales", "to": "Revenue"}])
        self.assertEqual(rep.warnings, [])
