"""Funnel (decisions/159): a Gantt bar per stage centered on zero (start -value / 2, the value on Size), the stages
in a fixed order, the conversion a table calc along them; expected against the CSV, the gate's mutations."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

from tbuilder import expected, gate, spec as spec_mod
from tbuilder.build import build
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "funnel.json"
CSV = ROOT / "data" / "sample" / "funnel.csv"
STAGES = ["Visit", "Sign-up", "Trial", "Purchase", "Renewal"]


def spec():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    s["datasource"]["path"] = "data/sample/funnel.csv"
    return s


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def users(channel=None):
    out = Counter()
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if channel in (None, r["Channel"]):
                out[r["Stage"]] += int(r["Users"])
    return out


class Funnel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build(spec(), OUT / "funnel.twbx", base_dir=ROOT)  # passes the gate
        cls.root = twb(cls.path)
        cls.cols = {c.get("caption"): c for c in cls.root.iter("column") if c.get("caption")}
        cls.exp = expected.compute(spec(), CSV)

    def test_schema(self):
        spec_mod.validate(spec())
        for edit in ({"measure": None}, {"sort": "asc"}, {"conversion": "total"}, {"rows": "Stage"}):
            bad = spec()
            s = bad["sheets"][0]
            for k, v in edit.items():
                s.pop(k) if v is None else s.update({k: v})
            with self.assertRaises(ValueError):
                spec_mod.validate(bad)

    def test_centered_gantt(self):
        w = ws(self.root, "Funnel")
        self.assertEqual([m.get("class") for m in w.iter("mark")], ["GanttBar"])
        self.assertEqual(self.cols["Funnel · Start"].find("calculation").get("formula"), "-SUM([Users]) / 2")
        self.assertTrue(w.find(".//encodings/size").get("column").endswith("[sum:Users:qk]"))
        self.assertTrue(w.findtext("table/cols").endswith(
            f"[usr:{self.cols['Funnel · Start'].get('name')[1:-1]}:qk]"))
        self.assertTrue(w.findtext("table/rows").endswith("[none:Stage:nk]"))
        hidden = [f for f in w.iter("format") if f.get("attr") == "display" and f.get("scope") == "cols"]
        self.assertEqual([f.get("value") for f in hidden], ["false"])  # the start's axis says nothing

    def test_order(self):
        sort = ws(self.root, "Funnel").find("table/view/computed-sort")
        self.assertEqual(sort.get("direction"), "DESC")
        self.assertTrue(sort.get("using").endswith("[sum:Users:qk]"))
        self.assertIsNone(ws(self.root, "Social Funnel").find("table/view/computed-sort"))  # the manual order
        buckets = [b.text for b in self.root.iter("manual-sort") if b.get("column") == "[none:Stage:nk]"
                   for b in b.iter("bucket")]
        self.assertEqual(buckets, [f'"{s}"' for s in STAGES])

    def test_conversion_calcs(self):
        prev, first = self.cols["Funnel · Conversion"], self.cols["Social Funnel · Conversion"]
        self.assertEqual(prev.find("calculation").get("formula"), "SUM([Users]) / LOOKUP(SUM([Users]), -1)")
        self.assertEqual(first.find("calculation").get("formula"),
                         "SUM([Users]) / WINDOW_SUM(SUM([Users]), FIRST(), FIRST())")
        self.assertEqual((prev.get("default-format"), first.get("default-format")), ("p0%", "p0.0%"))
        for name in ("Funnel", "Social Funnel"):  # computed along the stages
            tcs = [t for t in ws(self.root, name).iter("table-calc") if t.get("ordering-type") == "Field"]
            self.assertTrue(tcs and all(t.get("ordering-field", "").endswith("[none:Stage:nk]") for t in tcs))

    def test_expected_previous(self):
        u, exp = users(), self.exp["Funnel"]
        order = sorted(u, key=lambda k: -u[k])
        self.assertEqual(list(exp), order)
        for i, k in enumerate(order):
            self.assertEqual(exp[k]["value"], u[k])
            want = u[k] / u[order[i - 1]] if i else None
            self.assertEqual(exp[k]["conversion"] is None, want is None)
            if want is not None:
                self.assertAlmostEqual(exp[k]["conversion"], want, 9)

    def test_expected_first(self):
        u, exp = users("Social"), self.exp["Social Funnel"]
        self.assertEqual(list(exp), STAGES)  # the field's order, not by value or name
        for k in STAGES:
            self.assertEqual(exp[k]["value"], u[k])
            self.assertAlmostEqual(exp[k]["conversion"], u[k] / u["Visit"], 9)

    def test_refusals(self):
        bad = spec()
        bad.pop("fields")
        with self.assertRaisesRegex(ValueError, "process order"):
            build(bad, OUT / "funnel_bad.twbx", base_dir=ROOT)
        bad = spec()
        bad["sheets"][0]["measure"]["table_calc"] = {"type": "running_total"}
        with self.assertRaisesRegex(ValueError, "computes its own conversion"):
            build(bad, OUT / "funnel_bad.twbx", base_dir=ROOT)

    def test_gate_clean(self):
        self.assertEqual([i for i in gate.run(self.path) if i.check == "funnel"], [])

    def _caught(self, mutate, text):
        issues = [i for i in gate.run(repack(mutate, source=self.path)) if i.check == "funnel"]
        self.assertTrue(any(text in i.message for i in issues), issues)

    def test_gate_size_off_center(self):
        def m(root):
            e = next(w for w in root.iter("worksheet") if w.get("name") == "Funnel").find(".//encodings/size")
            e.set("column", e.get("column").replace("[sum:Users:qk]", "[avg:Users:qk]"))
        self._caught(m, "not centered")

    def test_gate_no_size(self):
        def m(root):
            enc = next(w for w in root.iter("worksheet") if w.get("name") == "Funnel").find(".//encodings")
            enc.remove(enc.find("size"))
        self._caught(m, "not centered")

    def test_gate_unsorted(self):
        """Neither the computed-sort nor the field's manual order: both funnels compare stages by name."""
        def m(root):
            view = next(w for w in root.iter("worksheet") if w.get("name") == "Funnel").find("table/view")
            view.remove(view.find("computed-sort"))
            for ds in root.iter("datasource"):
                for s in ds.findall("default-sorts"):
                    ds.remove(s)
        issues = [i for i in gate.run(repack(m, source=self.path)) if i.check == "funnel"]
        self.assertEqual(sorted(i.where for i in issues if "no fixed order" in i.message),
                         ["worksheet 'Funnel'", "worksheet 'Social Funnel'"])

    def test_gate_manual_order_dropped(self):
        """The field's manual order gone: the sorted funnel keeps its computed-sort, the process one has none."""
        def m(root):
            for ds in root.iter("datasource"):
                for s in ds.findall("default-sorts"):
                    ds.remove(s)
        issues = [i for i in gate.run(repack(m, source=self.path)) if i.check == "funnel"]
        self.assertEqual([i.where for i in issues if "no fixed order" in i.message], ["worksheet 'Social Funnel'"])


    def test_gate_room_line_shown(self):
        """The room line made visible marks nothing nameable: the gate wants a label again (decisions/095)."""
        def m(root):
            w = next(w for w in root.iter("worksheet") if w.get("name") == "Funnel")
            for f in w.iterfind("table/style/style-rule[@element='refline']/format[@attr='line-visibility']"):
                f.set("value", "on")
        issues = gate.run(repack(m, source=self.path))
        self.assertTrue(any(i.check == "reflines" and "Funnel" in i.where and "no label" in i.message
                            for i in issues), issues)

if __name__ == "__main__":
    unittest.main()
