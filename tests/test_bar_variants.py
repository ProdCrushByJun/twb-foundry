"""Variants of a bar from a Bar Chart Menu (decisions/095): a target line per bar with color below target, the
stack total at the bar end, the value as a row header on the left. Refusals of the spec, the XML forms, the gate's
checks with their mutations, the count of the bars below target."""
import json
import unittest
from pathlib import Path

from tbuilder import barlabels, design_lint, expected, gate
from tbuilder.build import build
from test_bar_labels import built, formats, labelled, axis_hidden, repack, ws
from test_roundtrip import SPECS

ROOT = Path(__file__).resolve().parent.parent


def load():
    return json.loads((SPECS / "bar_variants.json").read_text(encoding="utf-8"))


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def reflines(w):
    return w.findall("table/panes/pane/reference-line")


class Refused(unittest.TestCase):
    def refused(self, name, change, why):
        spec = load()
        s = sheet(spec, name)
        for k, v in change.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        with self.assertRaisesRegex(ValueError, why):
            build(spec, ROOT / "out" / "bar_variants_refused.twbx", SPECS)

    def test_target(self):
        self.refused("Target", {"reference": {"type": "target"}}, "needs 'measure'")
        self.refused("Target", {"reference": {"type": "target", "measure": {"field": "Plan"}, "label": "Plan"}},
                     "has no label")
        self.refused("Target", {"color": "Region", "subtitle": None}, "not stacked")
        self.refused("Target", {"reference": None}, "color.below 'target' needs")

    def test_total_end(self):
        self.refused("Totals", {"color": None}, "stack total of a stacked horizontal bar")
        self.refused("Totals", {"reference": {"type": "avg"}}, "does not go with a reference line")

    def test_value_column(self):
        self.refused("Values", {"color": "Region"}, "value_column 'left' is for a horizontal bar of members")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(load(), ROOT / "out" / "bar_variants_test.twbx")  # its own file: modules run in parallel

    def test_target_per_bar_no_label(self):
        w = ws(self.root, "Target")
        [r] = reflines(w)
        self.assertEqual((r.get("scope"), r.get("label-type"), r.get("formula")), ("per-cell", "none", "total"))
        self.assertIn("sum:Plan:qk", r.get("value-column"))
        self.assertFalse(axis_hidden(w))
        color = w.find("table/panes/pane/encodings/color").get("column")
        calc = next(c for c in self.root.iter("column") if c.find("calculation") is not None
                    and c.get("name").strip("[]") in color)
        self.assertEqual(calc.find("calculation").get("formula"), "SUM([Sales]) < SUM([Plan])")

    def test_total_at_the_bar_end(self):
        w = ws(self.root, "Totals")
        [r] = reflines(w)
        self.assertEqual((r.get("scope"), r.get("label-type"), r.get("formula")), ("per-cell", "value", "total"))
        fmt = {f.get("attr"): f.get("value") for f in formats(w, "refline") if f.get("id") == r.get("id")}
        self.assertEqual((fmt.get("line-visibility"), fmt.get("text-align")), ("off", "right"))
        self.assertEqual(fmt.get("vertical-align"), "center")  # the row's middle, not its foot (decisions/165)
        self.assertTrue(axis_hidden(w))
        self.assertFalse(labelled(w))

    def test_value_column_left(self):
        w = ws(self.root, "Values")
        self.assertRegex(w.find("table/rows").text, r"^\(\[.*none:Manager:nk\] / \[.*sum:Sales:ok\]\)$")
        self.assertTrue(axis_hidden(w))
        self.assertFalse(labelled(w))
        widths = [int(f.get("value")) for f in formats(w, "header") if f.get("attr") == "width"]
        self.assertEqual(len(widths), 2)
        self.assertGreaterEqual(min(widths), barlabels.VALUE_PX)  # the value column: 52px at the least
        aligns = [f for f in formats(w, "label") if f.get("attr") == "text-align" and f.get("value") == "right"]
        self.assertEqual(len(aligns), 1)
        # the tooltip names Sales once: Desktop's default listed the value header too (golden-debt pass, 2026-10-31)
        runs = [r.text or "" for r in w.iterfind("table/panes/pane/customized-tooltip/formatted-text/run")]
        self.assertEqual(([t for t in runs if t.startswith("Sales:")], any("sum:Sales:ok" in t for t in runs)),
                         (["Sales:\t"], False))

    def test_lint_i2_quiet(self):
        self.assertEqual([f for f in design_lint.lint(load(), str(SPECS)) if f.rule == "I2"], [])


class Numbers(unittest.TestCase):
    def test_below_target_and_stack_totals(self):
        spec = load()
        got = expected.compute(spec, expected.data_path(spec, SPECS))
        self.assertEqual(got["Target · Reference"], {"below target": 4})
        east = got["Totals"]["East | Anna"] + got["Totals"]["East | Boris"]
        self.assertAlmostEqual(east, 35352.62, places=2)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = build(load(), ROOT / "out" / "bar_variants_gate.twbx", SPECS)

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def test_unlabelled_line_across_the_sheet(self):
        def fn(root):
            reflines(ws(root, "Target"))[0].set("scope", "per-table")
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "reflines"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("across the sheet has no label", got[0])

    def test_hidden_axis_without_total_or_value(self):
        def no_total(root):
            r = reflines(ws(root, "Totals"))[0]
            r.getparent().remove(r)

        def no_value(root):
            rows = ws(root, "Values").find("table/rows")
            rows.text = rows.text.split(" / ")[0].lstrip("(")
        for fn, name in ((no_total, "Totals"), (no_value, "Values")):
            got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "bar-labels"]
            self.assertEqual(len(got), 1, (name, got))
            self.assertIn(f"worksheet '{name}': its measure axis is hidden and its bars have no labels", got[0])


if __name__ == "__main__":
    unittest.main()
