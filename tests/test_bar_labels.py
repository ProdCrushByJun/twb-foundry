"""Values at the bar ends instead of the axis (decisions/087): which bars get them by default, the XML ('Labels
on the End': mark-labels-show, the measure's axis display false, row headers 10pt #333333 with a width), the zero line
of a bar with a sign, the generator's refusal of a cell too narrow for the labels, the gate's check with its
mutations and lint I9."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import barlabels, design, design_lint, gate
from tbuilder.build import build
from test_roundtrip import SPECS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "bar_labels_test.twbx"


def load(name):
    return json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))


def built(spec, out=OUT):
    out = build(spec, out, SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def formats(w, element):
    return w.findall(f"table/style/style-rule[@element='{element}']/format")


def labelled(w):
    return w.find("table/panes/pane/style/style-rule[@element='mark']/format[@attr='mark-labels-show']") is not None


def axis_hidden(w):
    return any(f.get("attr") == "display" and f.get("value") == "false" for f in formats(w, "axis"))


def repack(src, fn):
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.endswith(".twb"))
    root = etree.fromstring(items[twb])
    fn(root)
    items[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    path = Path(tempfile.mkdtemp()) / "mutant.twbx"
    with zipfile.ZipFile(path, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)
    return path


class Mode(unittest.TestCase):
    def test_default_end_only_for_a_plain_horizontal_bar(self):
        bar = {"type": "bar", "dimension": "Region", "measure": {"field": "Sales"}}
        self.assertEqual(barlabels.mode(bar), "end")
        self.assertEqual(barlabels.mode({**bar, "color": {"highlight": ["East"]}}), "end")  # one bar a row
        self.assertEqual(barlabels.mode({**bar, "color": "Region"}), "end")  # its own dimension: not stacked
        for other in ({"color": "Category"}, {"orientation": "vertical"}, {"date_level": "month"},
                      {"plan": {"field": "Plan"}}, {"reference": {"type": "target", "measure": {"field": "Plan"}}},
                      {"labels": "none"}):
            self.assertEqual(barlabels.mode({**bar, **other}), "none", other)
        target = {"type": "target", "measure": {"field": "Plan"}}
        self.assertEqual(barlabels.mode({**bar, "reference": target, "labels": "end"}), "end")
        # decisions/165: a line across all the bars has its own label; the bars keep theirs, the axis goes
        for ref in ({"type": "avg"}, {"type": "const", "value": 1}, [{"type": "median"}, {"type": "avg"}]):
            self.assertEqual(barlabels.mode({**bar, "reference": ref}), "end", ref)
            self.assertTrue(barlabels.no_axis({**bar, "reference": ref}), ref)
        self.assertFalse(barlabels.no_axis({**bar, "reference": target}))
        self.assertIsNone(barlabels.mode({"type": "line"}))

    def test_end_refused_where_a_label_per_bar_does_not_fit(self):
        for other, why in (({"color": "Category"}, "a stacked bar"), ({"orientation": "vertical"}, "a vertical bar"),
                           ({"date_level": "month"}, "a bar along a date"), ({"plan": {"field": "Plan"}}, "a plan")):
            s = {"name": "B", "type": "bar", "dimension": "Region", "measure": {"field": "Sales"}, "labels": "end",
                 **other}
            with self.assertRaisesRegex(ValueError, why):
                barlabels.check({"sheets": [s]})


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(load("colors"))

    def test_labels_and_hidden_axis(self):
        for name in ("Regions", "Gap"):
            w = ws(self.root, name)
            self.assertTrue(labelled(w), name)
            [f] = [f for f in formats(w, "axis") if f.get("attr") == "display"]
            self.assertEqual((f.get("scope"), f.get("value")), ("cols", "false"))
            self.assertIn("Sales" if name == "Regions" else "Calculation_", f.get("field"))

    def test_stack_and_plan_keep_their_axis(self):
        for name in ("Managers", "Plan"):
            w = ws(self.root, name)
            self.assertFalse(labelled(w), name)
            self.assertFalse(axis_hidden(w), name)

    def test_row_headers_10pt_text_color_with_a_width(self):
        for name in ("Regions", "Managers", "Plan", "Gap"):
            got = {f.get("attr"): f.get("value") for f in formats(ws(self.root, name), "label")}
            self.assertEqual(got, {"color": "#333333", "font-size": str(design.FONT["bar_header"])}, name)
        widths = [f for f in formats(ws(self.root, "Gap"), "header") if f.get("attr") == "width"]
        self.assertEqual(len(widths), 1)

    def test_zero_line_solid_only_with_a_sign(self):
        gap = {(f.get("attr"), f.get("scope")): f.get("value") for f in formats(ws(self.root, "Gap"), "zeroline")}
        self.assertEqual(gap, {("line-visibility", "cols"): "on", ("line-visibility", "rows"): "off",
                               ("line-pattern-only", "cols"): "solid"})
        regions = {(f.get("attr"), f.get("scope")): f.get("value") for f in formats(ws(self.root, "Regions"), "zeroline")}
        self.assertEqual(regions[("line-visibility", None)], "off")

    def test_labels_none_brings_the_axis_back(self):
        spec = load("colors")
        next(s for s in spec["sheets"] if s["name"] == "Regions")["labels"] = "none"
        w = ws(built(spec), "Regions")
        self.assertFalse(labelled(w))
        self.assertFalse(axis_hidden(w))


class Room(unittest.TestCase):
    def test_too_narrow_refused(self):
        """'36,570' + 20 + 40 beside 60px of headers: a 100px cell is refused, naming the sheet."""
        spec = load("colors")
        d = spec["dashboard"]
        regions = next(s for s in spec["sheets"] if s["name"] == "Regions")
        regions["title"] = "Sales"  # a header short enough for the narrow cell
        del regions["subtitle"]
        d["grid"][0] = [{"sheet": "Regions", "width": 1}, {"sheet": "Managers", "width": 5}, {"sheet": "Plan", "width": 5}]
        with self.assertRaisesRegex(ValueError, r"Sheet 'Regions': the cell is too narrow for the values at the bar "
                                                r"ends \(-?\d+px of bars beside the row headers"):
            built(spec)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = build(load("colors"), ROOT / "out" / "bar_labels_gate.twbx", SPECS)

    def test_clean(self):
        self.assertEqual([i for i in gate.run(self.book) if i.check == "bar-labels"], [])

    def test_hidden_axis_without_labels(self):
        def fn(root):
            w = ws(root, "Regions")
            for f in w.iter("format"):
                if f.get("attr") == "mark-labels-show":
                    f.getparent().remove(f)
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "bar-labels"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("worksheet 'Regions': its measure axis is hidden and its bars have no labels", got[0])

    def test_labels_without_room(self):
        def fn(root):
            w = ws(root, "Gap")
            head = next(f for f in formats(w, "header") if f.get("attr") == "width")
            z = next(z for z in root.iter("zone") if z.get("name") == "Gap")
            px = int(z.get("w")) * 1200 // 100000
            head.set("value", str(px - 50))  # 50px of bars left for '-1,343' and '2,051'
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "bar-labels"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("sheet 'Gap'", got[0])
        self.assertIn(f"{barlabels.FLOOR_PX}px at the least", got[0])

    def test_labels_without_a_header_width(self):
        def fn(root):
            w = ws(root, "Regions")
            for f in formats(w, "header"):
                if f.get("attr") == "width":
                    f.getparent().remove(f)
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "bar-labels"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("without a row header width", got[0])


class Lint(unittest.TestCase):
    def test_i9_on_labels_none(self):
        spec = load("colors")
        next(s for s in spec["sheets"] if s["name"] == "Regions")["labels"] = "none"
        found = [f for f in design_lint.lint(copy.deepcopy(spec), str(SPECS)) if f.rule == "I9"]
        self.assertEqual([f.where for f in found], ["sheet 'Regions'"])
        self.assertEqual([f for f in design_lint.lint(load("colors"), str(SPECS)) if f.rule == "I9"], [])


if __name__ == "__main__":
    unittest.main()
