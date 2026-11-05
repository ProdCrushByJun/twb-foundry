"""A column's own name in the workbook (decisions/073): `fields.<column>.caption`, Desktop's rename of a field -
`caption` on the column, in the datasource and in each sheet's dependencies (a case's improved.twb: caption='Diff'
name='[diff]'); the references [none:x:nk] stay. Tableau shows it in table headers and filter cards; the texts the
builder writes itself (registry column titles) show it too."""
import copy
import unittest
import zipfile

from lxml import etree

from tbuilder import design_lint, expected, gate
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import OUT, SPECS

CSV = SPECS / "../data/sample/sales.csv"
SPEC = {
    "$schema": "../tbuilder/spec.schema.json", "version": 1,
    "datasource": {"type": "csv", "path": "../data/sample/sales.csv"},
    "fields": {"Region": {"caption": "Sales Region"}, "Sales": {"caption": "Revenue"}},
    "sheets": [
        {"name": "By Region", "type": "bar", "dimension": "Region", "measure": {"field": "Sales"}, "sort": "desc"},
        {"name": "Table", "type": "registry", "rows": ["Region"],
         "columns": [{"measure": {"field": "Sales"}, "style": "text", "label": "Sales"}]}
    ],
    "filters": [{"field": "Region", "show_on": "By Region"}],
    "dashboard": {"name": "D", "title": "Captions", "width": 1000, "height": 700, "grid": [["By Region", "Table"]]}
}


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def built(spec, name="field_caption"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return out, etree.fromstring(z.read(out.stem + ".twb"))


class Schema(unittest.TestCase):
    def test_valid(self):
        validate(SPEC)

    def test_empty_caption(self):
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: s["fields"]["Region"].update(caption="")))


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.root = built(SPEC)

    def test_caption_on_the_column_everywhere(self):
        cols = [c for c in self.root.iter("column") if c.get("name") in ("[Region]", "[Sales]")
                and c.get("datatype") != "table"]
        self.assertGreater(len(cols), 2)  # the datasource and the sheets' dependencies
        for c in cols:
            self.assertEqual(c.get("caption"), {"[Region]": "Sales Region", "[Sales]": "Revenue"}[c.get("name")])
            self.assertEqual(list(c.attrib)[:2], ["caption", "datatype"])  # Desktop's attribute order

    def test_references_unchanged(self):
        rows = next(w for w in self.root.iter("worksheet") if w.get("name") == "By Region").findtext("table/rows")
        self.assertIn("[none:Region:nk]", rows)

    def test_registry_title_shows_the_caption(self):
        texts = {z.findtext("formatted-text/run") for z in self.root.iter("zone") if z.get("type-v2") == "text"}
        self.assertIn("Sales Region", texts)
        self.assertNotIn("Region", texts)

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.out, SPEC), [])

    def test_numbers_unchanged(self):
        spec = copy.deepcopy(SPEC)
        spec["datasource"]["path"] = str(CSV.resolve())
        plain = copy.deepcopy(spec)
        plain.pop("fields")
        self.assertEqual(expected.compute(spec, CSV), expected.compute(plain, CSV))


class Refusals(unittest.TestCase):
    def test_numeric_column_takes_a_caption(self):
        built(mutate(lambda s: s["fields"].update(Quantity={"caption": "Units"})), "field_caption_num")

    def test_calc_or_unknown(self):
        with self.assertRaisesRegex(ValueError, "no such column"):
            built(mutate(lambda s: s["fields"].update(Nope={"caption": "X"})), "field_caption_bad")
        with self.assertRaisesRegex(ValueError, "row-level text calculation"):  # aliases of an aggregate calc (151)
            built(mutate(lambda s: s.update(calcs=[{"name": "Margin", "formula": "SUM([Profit])/SUM([Sales])"}])
                         or s["fields"].update(Margin={"aliases": {"a": "b"}})), "field_caption_bad")

    def test_caption_of_another_field(self):
        with self.assertRaisesRegex(ValueError, "already"):
            built(mutate(lambda s: s["fields"].update(Category={"caption": "Profit"})), "field_caption_bad")




class Lint(unittest.TestCase):
    def f1(self, spec, base_dir):
        return sorted(f.text.split("'")[1] for f in design_lint.lint(spec, base_dir) if f.rule == "F1")


    def test_readable_names_pass(self):
        self.assertEqual(self.f1(mutate(lambda s: s.pop("fields")), SPECS), [])  # Region, Sales
