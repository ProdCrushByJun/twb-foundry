"""Registry Top N with an explicit ranking measure (top.by, decisions/115): a first column without a bar and a field
name with a space (acceptance/echarts Top Products)."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tbuilder.build import build_file
from test_roundtrip import ROOT

SRC = ROOT / "acceptance" / "echarts" / "spec.json"
SPEC = json.loads(SRC.read_text(encoding="utf-8"))


def variant(fn):
    spec = copy.deepcopy(SPEC)
    sh = next(s for s in spec["sheets"] if s["name"] == "Top Products")
    fn(sh)
    return spec


def run(spec):
    d = Path(tempfile.mkdtemp())
    p = d / "spec.json"
    for k in ("path",):  # data path is relative to the spec: keep it absolute
        spec["datasource"][k] = str((SRC.parent / spec["datasource"][k]).resolve())
    p.write_text(json.dumps(spec), encoding="utf-8")
    return build_file(p, d / "out.twbx")


def swap(sh):  # a count of a text field first: the column ranks by it
    sh["columns"].insert(0, sh["columns"].pop(1))


class RegistryTopBy(unittest.TestCase):
    def test_default_unchanged(self):
        run(copy.deepcopy(SPEC))

    def test_count_of_spaced_field_first_column(self):
        run(variant(swap))  # [Order ID] with a space was read as [OrderID] by gate.check_top_by

    def test_by_explicit(self):
        def f(sh):
            swap(sh)
            sh["top"]["by"] = {"field": "Revenue K", "agg": "sum"}
        run(variant(f))

    def test_by_spaced_field(self):
        def f(sh):
            sh["top"]["by"] = {"field": "Order ID", "agg": "count"}
        run(variant(f))

    def test_by_unknown_field_named(self):
        def f(sh):
            sh["top"]["by"] = {"field": "Nope", "agg": "sum"}
        with self.assertRaises(Exception) as cm:
            run(variant(f))
        self.assertIn("Nope", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
