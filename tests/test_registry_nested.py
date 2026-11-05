"""Registry cells Desktop 2025.1 really draws (decisions/072, 075): a label on a mark alone in its outer group of a
two-dimension registry is drawn only when the rows are set at least 22px high (a registry of one row per
group, every number empty at the automatic height and at 20-21px); a total row's shading is not covered by the white
bars of text cells."""
import copy
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from tbuilder.design import REGISTRY_ROW_NESTED_PX, TABLE_ROW_CARDS_PX
from test_gate import repack
from test_roundtrip import OUT, SPECS

TOTALS = json.loads((SPECS / "totals.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((SPECS / "registry.json").read_text(encoding="utf-8"))
TOTALS["dashboard"]["theme"] = REGISTRY["dashboard"]["theme"] = "flat"  # the rows without cards (decisions/168)
CARDS = json.loads((SPECS / "theme_cards.json").read_text(encoding="utf-8"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return out, etree.fromstring(z.read(out.stem + ".twb"))


def sheet(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def column_panes(root, name):
    """[(mark class, {mark rule attr: value})] of a registry's columns."""
    return [(p.find("mark").get("class"),
             {f.get("attr"): f.get("value") for f in p.iterfind("style/style-rule[@element='mark']/format")})
            for p in sheet(root, name).iterfind("table/panes/pane") if p.get("id")]


def row_height(root, name):
    """{field: height} of the registry's cell heights."""
    return {f.get("field").split(".")[-1]: f.get("value")
            for f in sheet(root, name).iterfind("table/style/style-rule[@element='cell']/format[@attr='height']")}


def one_dimension(spec):
    spec = copy.deepcopy(spec)
    reg = next(s for s in spec["sheets"] if s["type"] == "registry")
    reg["rows"] = reg["rows"][:1]
    reg.get("totals", {}).pop("sub", None)
    return spec


class Nested(unittest.TestCase):
    def test_rows_set_high_enough_for_every_label(self):
        for spec, name in ((TOTALS, "registry_nested_totals"), (REGISTRY, "registry_nested_bars")):
            _, root = built(spec, name)
            self.assertEqual(row_height(root, "Registry"), {"[none:Category:nk]": str(REGISTRY_ROW_NESTED_PX)})

    def test_values_stay_labels_on_bars(self):
        _, root = built(TOTALS, "registry_nested_totals")
        self.assertEqual({m for m, _ in column_panes(root, "Registry")}, {"Bar"})
        self.assertTrue(all(r.get("mark-labels-show") == "true" for _, r in column_panes(root, "Registry")))

    def test_theme_rows_keep_their_height(self):
        _, root = built(CARDS, "registry_nested_cards")
        reg = next(s["name"] for s in CARDS["sheets"] if s["type"] == "registry")
        self.assertEqual(set(row_height(root, reg).values()), {str(TABLE_ROW_CARDS_PX)})

    def test_one_dimension_keeps_the_automatic_height(self):
        _, root = built(one_dimension(TOTALS), "registry_flat_totals")
        self.assertEqual(row_height(root, "Registry"), {})


class TotalRow(unittest.TestCase):
    def test_white_cells_let_the_total_shading_through(self):
        _, root = built(one_dimension(TOTALS), "registry_flat_totals")
        for _, rule in column_panes(root, "Registry"):
            self.assertEqual((rule.get("mark-color"), rule.get("mark-transparency")), ("#ffffff", "0"))

    def test_no_total_no_transparency(self):
        spec = one_dimension(TOTALS)
        next(s for s in spec["sheets"] if s["type"] == "registry").pop("totals")
        _, root = built(spec, "registry_flat")
        self.assertTrue(all("mark-transparency" not in rule for _, rule in column_panes(root, "Registry")))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, _ = built(TOTALS, "registry_nested_src")

    def test_built_book_passes(self):
        self.assertEqual(gate.run(self.out, TOTALS), [])

    def test_rows_at_the_automatic_height(self):
        def drop(root):
            for f in sheet(root, "Registry").iterfind("table/style/style-rule[@element='cell']/format[@attr='height']"):
                f.getparent().remove(f)
        issues = gate.run(repack(drop, source=self.out))
        self.assertTrue(any("alone in its outer group" in i.message for i in issues), issues)

    def test_rows_too_low(self):
        def low(root):
            for f in sheet(root, "Registry").iterfind("table/style/style-rule[@element='cell']/format[@attr='height']"):
                f.set("value", "21")
        issues = gate.run(repack(low, source=self.out))
        self.assertTrue(any("21 under 22px" in i.message for i in issues), issues)
