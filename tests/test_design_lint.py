import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tbuilder.design_lint import lint

ROOT = Path(__file__).resolve().parent.parent
CSV = "Region,Manager,Day,Month,Sales\n" + "".join(
    f"{r},{m},{d},2025-0{i % 9 + 1}-01,{i * 10}\n"
    for i, (r, m, d) in enumerate([(r, m, d) for r in ("East", "West", "North", "South", "Central", "Far")
                                   for m in ("Ann", "Bob") for d in ("19 Mon", "20 Tue")]))
BASE = {
    "version": 1,
    "datasource": {"type": "csv", "path": "data.csv"},
    "sheets": [
        {"name": "KPI", "type": "kpi", "style": "cards", "date": {"field": "Month", "level": "month"},
         "measures": [{"field": "Sales"}]},
        {"name": "Bar", "type": "bar", "title": "Sales **by region**", "dimension": "Manager",
         "measure": {"field": "Sales"}, "sort": "desc"},
    ],
    "dashboard": {"name": "D", "theme": "flat", "title": "**Sales** Overview", "subtitle": "Sample data", "width": 1200, "height": 800,
                  "grid": [["KPI"], ["Bar"]]},
}


class DesignLintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "data.csv").write_text(CSV, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def rules(self, change=None):
        spec = copy.deepcopy(BASE)
        if change:
            change(spec)
        return [(f.rule, f.level) for f in lint(spec, self.dir)]

    def test_clean_spec_has_no_findings(self):
        # C9 info: the cards' change in good / bad is lighter than the text floor without the card theme
        self.assertEqual(self.rules(), [("C9", "info"), ("C9", "info")])
        self.assertEqual(self.rules(lambda s: s["dashboard"].update(theme="cards")), [])

    def test_size_outside_references(self):
        self.assertIn(("D1", "warn"), self.rules(lambda s: s["dashboard"].update(width=1350, height=850)))
        self.assertNotIn(("D1", "warn"), self.rules(lambda s: s["dashboard"].update(width=1600, height=1200)))

    def test_sizes_of_reference_set_3(self):
        for w, h in [(1250, 960), (1280, 800), (1450, 940), (1500, 820), (1666, 1450), (1200, 1450)]:
            self.assertNotIn(("D1", "warn"), self.rules(lambda s: s["dashboard"].update(width=w, height=h)), (w, h))
        for w, h in [(1700, 1200), (1666, 1500), (1100, 1200)]:
            self.assertIn(("D1", "warn"), self.rules(lambda s: s["dashboard"].update(width=w, height=h)), (w, h))

    def test_text_contrast(self):
        def words(s):
            s["sheets"][1]["subtitle"] = "{good:East} grows, {accent:West} flat"
            s["sheets"].pop(0)
            s["dashboard"]["grid"] = [["Bar"]]
        found = [f for f in lint(self._spec(words), self.dir) if f.rule == "C9"]
        self.assertEqual([("info", "'good'" in f.text) for f in found], [("info", True)])  # accent is dark enough
        self.assertEqual([f for f in lint(self._spec(words, theme=True), self.dir) if f.rule == "C9"], [])

    def _spec(self, change, theme=False):
        spec = copy.deepcopy(BASE)
        change(spec)
        if theme:
            spec["dashboard"]["theme"] = "cards"
        return spec

    def test_kpi_not_top_or_left(self):
        found = self.rules(lambda s: s["dashboard"].update(grid=[["Bar", {"rows": [["Bar"], ["KPI"]]}]]))
        self.assertIn(("D2", "warn"), found)
        self.assertNotIn(("D2", "warn"), self.rules(lambda s: s["dashboard"].update(grid=[["KPI", "Bar"]])))

    def test_registry_not_at_bottom(self):
        def change(s):
            s["sheets"].append({"name": "Reg", "type": "registry"})
            s["dashboard"]["grid"] = [["KPI"], ["Reg"], ["Bar"]]
        self.assertIn(("D3", "warn"), self.rules(change))

    def test_too_many_blocks(self):
        def change(s):
            s["dashboard"]["grid"] = [["KPI"], ["Bar"] * 4, ["Bar"] * 3]
        self.assertIn(("D4", "warn"), self.rules(change))

    def test_dashboard_header(self):
        self.assertIn(("T1", "error"), self.rules(lambda s: s["dashboard"].pop("title")))
        self.assertIn(("T1", "warn"), self.rules(lambda s: s["dashboard"].pop("subtitle")))

    def test_bold_key_word(self):
        self.assertIn(("T2", "info"), self.rules(lambda s: s["sheets"][1].update(title="Sales by region")))

    def test_interaction_hint_needs_an_action(self):
        self.assertIn(("T4", "error"), self.rules(lambda s: s["sheets"][1].update(subtitle="Click a bar to filter")))

        def with_action(s):
            s["sheets"][1]["subtitle"] = "Click a bar to filter"
            s["dashboard"]["actions"] = [{"source": "Bar"}]
        self.assertNotIn(("T4", "error"), self.rules(with_action))

    def test_palette_size(self):
        self.assertIn(("C2", "warn"), self.rules(lambda s: s["sheets"][1].update(color="Region")))
        self.assertIn(("C4", "info"), self.rules(lambda s: s["sheets"][1].update(color="Manager")))

    def test_legend_note_once_per_field(self):
        def change(s):
            s["sheets"][1]["color"] = "Manager"
            s["sheets"].append(s["sheets"][1] | {"name": "Bar 2"})
            s["dashboard"]["grid"].append(["Bar 2"])
        self.assertEqual(self.rules(change).count(("C4", "info")), 1)

    def test_block_headers_off(self):
        self.assertIn(("T7", "warn"), self.rules(lambda s: s.update(block_headers=False)))

    def test_spaghetti_lines(self):
        def change(s):
            s["sheets"][1] = {"name": "Bar", "type": "line", "title": "Monthly **sales**",
                              "date": {"field": "Month", "level": "month"}, "measure": {"field": "Sales"},
                              "color": "Region"}
        self.assertIn(("C3", "warn"), self.rules(change))

    def test_declutter_off(self):
        self.assertIn(("I1", "warn"), self.rules(lambda s: s.update(declutter=False)))

    def test_unsorted_bars(self):
        self.assertIn(("I3", "warn"), self.rules(lambda s: s["sheets"][1].pop("sort")))

    def test_ordinal_bars_need_no_sort(self):
        def change(s):
            s["sheets"][1].pop("sort")
            s["sheets"][1]["dimension"] = "Day"
        self.assertNotIn(("I3", "warn"), self.rules(change))

    def test_too_many_bars(self):
        csv = "Item,Sales\n" + "".join(f"Item {i:02},{i}\n" for i in range(13))
        (self.dir / "many.csv").write_text(csv, encoding="utf-8")

        def change(s):
            s["datasource"]["path"] = "many.csv"
            s["sheets"] = [s["sheets"][1] | {"dimension": "Item"}]
            s["dashboard"]["grid"] = [["Bar"]]
        self.assertIn(("I4", "warn"), self.rules(change))

    def test_plain_table(self):
        def change(s):
            s["sheets"].append({"name": "T", "type": "table", "rows": "Region", "measure": {"field": "Sales"}})
            s["dashboard"]["grid"].append(["T"])
        self.assertIn(("I5", "info"), self.rules(change))

    def test_kpi_cards_when_there_is_a_date(self):
        self.assertIn(("K1", "info"), self.rules(lambda s: s["sheets"][0].update(style="tiles")))

    def test_errors_come_first(self):
        spec = copy.deepcopy(BASE)
        spec["dashboard"].pop("title")
        spec["declutter"] = False
        levels = [f.level for f in lint(spec, self.dir)]
        self.assertEqual(levels, sorted(levels, key=["error", "warn", "info"].index))

    def test_cli_fails_on_errors(self):
        spec = copy.deepcopy(BASE)
        spec["dashboard"].pop("title")
        path = self.dir / "bad.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "tbuilder", "lint", str(path)], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("T1", r.stdout)

    def test_t9_long_title_warns_short_title_with_subtitle_is_silent(self):
        """A block title over 4 words warns (the explanation goes to the subtitle); 1-4 words and a unit do not."""
        spec = copy.deepcopy(BASE)
        bar = spec["sheets"][1]
        bar["title"] = "**Heavy** delays, over 120 min: a dot = a delivery"
        found = [f for f in lint(spec, self.dir) if f.rule == "T9"]
        self.assertEqual([(f.level, f.where) for f in found], [("warn", "sheet 'Bar'")])
        self.assertIn("subtitle", found[0].text)
        for title in ("**Heavy** delays", "Sales **by region**, %", "**When**"):
            bar["title"], bar["subtitle"] = title, "over 120 min, a dot = a delivery"
            self.assertNotIn("T9", [f.rule for f in lint(spec, self.dir)], title)






if __name__ == "__main__":
    unittest.main()
