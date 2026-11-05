"""Everything that stops a build, in one list, before the first build (decisions/198): tbuilder/trial.py. Found in the
victory_retail case: 8 errors came one at a time, 7 builds in a row."""
import copy
import csv
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tbuilder import design_lint, regress, trial, user_profile
from tbuilder.build import build

ROOT = Path(__file__).resolve().parent.parent
GOOD = {"version": 1, "datasource": {"type": "csv", "path": "d.csv"},
        "sheets": [{"name": "Trend", "type": "bar", "dimension": "Region", "measure": {"field": "Sales"}, "title": "**Sales**"},
                   {"name": "Top", "type": "registry", "rows": ["Region"], "title": "**Top**", "columns": [{"measure": {"field": "Sales"}, "style": "text", "label": "Sales"}]},
                   {"name": "KPI", "type": "kpi", "style": "cards", "date": {"field": "Day", "level": "month"}, "measures": [{"field": "Sales"}]}],
        "dashboard": {"name": "D", "title": "**Sales**", "subtitle": "All", "width": 1200, "height": 800, "row_heights": [1, 2],
                      "grid": [["KPI"], ["Trend", "Top"]]}}


def bad_spec():
    """Three of the case's mistakes, each in its own block, none of which the design rules see."""
    spec = copy.deepcopy(GOOD)
    trend, top, kpi = spec["sheets"]
    top["subtitle"] = "Rise in {good:green}"  # a colored word the block does not draw
    kpi["separate_cards"] = True  # no sparkline to the right of the number
    trend["measure"]["field"] = "Nope"
    return spec


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        with (self.tmp / "d.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Region", "Day", "Sales"])
            w.writerows([("North", "2024-01-05", 10), ("South", "2024-01-06", 20), ("North", "2024-02-05", 30), ("South", "2024-02-06", 40)])
        self.root = self.tmp / "profiles"
        shutil.copytree(ROOT / "profiles" / "house", self.root / "house")
        for p in (mock.patch.object(user_profile, "ROOT", self.root), mock.patch.object(user_profile, "forced", None), mock.patch.dict(os.environ)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(user_profile.ENV, None)

    def zero_padding(self):
        """The profile copy-style used to write from a book with floating blocks: the gate refuses it, the rules do not."""
        (self.root / "p").mkdir()
        (self.root / "p" / "profile.yaml").write_text(yaml.safe_dump(
            {"profile_version": 1, "theme": "cards", "tokens": {"space": {"card_margin": 10, "card_padding": 0, "card_padding_kpi": 0}}}), encoding="utf-8")


class OneList(Base):
    def test_a_good_spec_has_none(self):
        self.assertEqual(trial.problems(GOOD, self.tmp), [])

    def test_the_build_itself_stops_at_one(self):
        with self.assertRaises(ValueError) as e:
            build(bad_spec(), self.tmp / "b.twbx", self.tmp)
        self.assertEqual(sum(w in str(e.exception) for w in ("colored words", "separate_cards", "Nope")), 1)

    def test_each_block_says_its_own(self):
        got = "\n".join(trial.problems(bad_spec(), self.tmp))
        for word in ("colored words", "separate_cards", "Nope"):
            self.assertIn(word, got)

    def test_the_gate_comes_in_the_same_list(self):
        self.zero_padding()
        spec = {**bad_spec(), "profile": "p"}
        got = "\n".join(trial.problems(spec, self.tmp))
        for word in ("colored words", "separate_cards", "Nope", "card padding 0"):
            self.assertIn(word, got)

    def test_nothing_is_said_about_a_block_set_aside(self):
        got = trial.problems(bad_spec(), self.tmp)
        self.assertEqual(len(got), 3, got)

    def test_the_spec_is_not_touched(self):
        spec = bad_spec()
        before = copy.deepcopy(spec)
        trial.problems(spec, self.tmp)
        self.assertEqual(spec, before)

    def test_a_missing_file_is_one_line(self):
        spec = {**GOOD, "datasource": {"type": "csv", "path": "no.csv"}}
        got = trial.problems(spec, self.tmp)
        self.assertEqual(len(got), 1)
        self.assertIn("no.csv", got[0])

    def test_no_hyper_is_made(self):
        spec = {**GOOD, "datasource": {**GOOD["datasource"], "hyper": True}}
        with mock.patch("tbuilder.hyper.write", side_effect=AssertionError("a trial writes no extract")):
            self.assertEqual(trial.problems(spec, self.tmp), [])


class Lint(Base):
    def test_lint_with_build_lists_them_as_errors(self):
        got = [f for f in design_lint.lint(bad_spec(), self.tmp, build=True) if f.rule == "BUILD"]
        self.assertEqual(len(got), 3)
        self.assertTrue(all(f.level == "error" for f in got))

    def test_lint_alone_builds_nothing(self):
        """regress and the unit tests lint hundreds of specs: only the command and the check ask for the build."""
        with mock.patch.object(trial, "problems", side_effect=AssertionError("built")):
            design_lint.lint(GOOD, self.tmp)


class BuildRows(Base):
    def test_a_failed_build_shows_the_whole_list(self):
        import json
        path = self.tmp / "s.json"
        path.write_text(json.dumps(bad_spec()), encoding="utf-8")
        book, rows = regress.build_rows(regress.Case("s", path), self.tmp)
        self.assertIsNone(book)
        for word in ("colored words", "separate_cards", "Nope"):
            self.assertIn(word, rows[0].reason)


if __name__ == "__main__":
    unittest.main()
