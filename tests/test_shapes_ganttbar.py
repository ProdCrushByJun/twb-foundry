"""Shapes and Gantt bars (decisions/139): the signed change of a tile note (▲ / ▼ in good / bad), the registry's
status mark (built-in filled shapes by the sign), the dumbbell (Gantt span + circle) and the waterfall (running sum,
Gantt bar sized by the negative step); the bullet is the bar's target line (decisions/095)."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import expected, spec as spec_mod
from tbuilder.build import build
from tbuilder.design import COLOR
from test_gate import ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "shapes_ganttbar.json"
CSV = ROOT / "data" / "sample" / "sales_plan.csv"


def spec():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    s["datasource"]["path"] = "data/sample/sales_plan.csv"
    return s


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def sheet(name):
    return next(s for s in spec()["sheets"] if s["name"] == name)


def by_manager():
    out = defaultdict(lambda: [0.0, 0.0])
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["Manager"]][0] += float(r["Sales"])
            out[r["Manager"]][1] += float(r["Plan"])
    return out


class ShapesGanttBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build(spec(), OUT / "shapes_ganttbar.twbx", base_dir=ROOT))  # passes the gate
        cls.cols = {c.get("caption"): c for c in cls.root.iter("column") if c.get("caption")}

    def test_schema(self):
        spec_mod.validate(spec())
        for edit in ({"type": "dumbbell", "from": None}, {"type": "waterfall", "rows": "Region"}):
            bad = spec()
            s = next(x for x in bad["sheets"] if x["type"] == edit["type"])
            for k, v in edit.items():
                s.pop(k) if v is None else s.update({k: v})
            with self.assertRaises(ValueError):
                spec_mod.validate(bad)

    def test_kpi_signed_note(self):
        """Two sides of the change, the arrows in the format, the runs in good / bad text colors."""
        good, bad = self.cols["Vs Plan · Good"], self.cols["Vs Plan · Bad"]
        self.assertEqual(good.get("default-format"), "*▲ 0.0%;▼ 0.0%")
        self.assertIn("&gt;= 0", ET.tostring(good.find("calculation"), encoding="unicode"))
        runs = list(self.root.iter("run"))
        names = (good.get("name").strip("[]"), bad.get("name").strip("[]"))
        colors = [r.get("fontcolor") for r in runs if any(n in (r.text or "") for n in names)]
        self.assertEqual(colors, [COLOR["good_text"], COLOR["bad_text"]])  # one side shows

    def test_registry_sign_shape(self):
        w = ws(self.root, "Managers")
        self.assertIn("Shape", [m.get("class") for m in w.iter("mark")])
        sign = self.cols["Managers · Status · Sign"].get("name").strip("[]")
        enc = next(e for e in self.root.iter("encoding") if e.get("attr") == "shape")
        self.assertIn(sign, enc.get("field"))
        self.assertEqual({m.get("to") for m in enc.iter("map")},
                         {":filled/triangle", ":filled/down-triangle", ":filled/circle"})
        bad = spec()
        next(s for s in bad["sheets"] if s["name"] == "Managers")["columns"][0]["shape"] = "sign"  # a text column
        with self.assertRaises(ValueError):
            build(bad, OUT / "shapes_bad.twbx", base_dir=ROOT)

    def test_dumbbell(self):
        w = ws(self.root, "Plan To Sales")
        marks = [m.get("class") for m in w.iter("mark")]
        self.assertEqual(marks[-2:], ["GanttBar", "Circle"])
        gantt = next(p for p in w.iter("pane") if p.get("id") == "1")
        self.assertIsNotNone(gantt.find("encodings/size"))
        fold = next(e for e in w.iter("encoding") if e.get("fold") == "true")
        self.assertEqual(fold.get("synchronized"), "true")  # one scale for both values
        exp = expected.compute(spec(), CSV)["Plan To Sales"]
        for k, (sales, plan) in by_manager().items():
            self.assertAlmostEqual(exp[k]["SUM(Sales)"], sales, 2)
            self.assertAlmostEqual(exp[k]["SUM(Plan)"], plan, 2)

    def test_waterfall(self):
        w = ws(self.root, "Gap Walk")
        self.assertEqual([m.get("class") for m in w.iter("mark")], ["GanttBar"])
        self.assertIn("RUNNING_SUM", ET.tostring(self.cols["Gap Walk · Running"], encoding="unicode"))
        self.assertIsNotNone(w.find(".//encodings/size"))
        exp = expected.compute(spec(), CSV)["Gap Walk"]
        for k, (sales, plan) in by_manager().items():
            self.assertAlmostEqual(exp[k], sales - plan, 2)
        self.assertAlmostEqual(sum(exp.values()), sum(s - p for s, p in by_manager().values()), 2)


if __name__ == "__main__":
    unittest.main()
