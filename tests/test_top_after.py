"""Top N after the filters: a RANK table calc filtered to 1..N (top.after = "filters", decisions/086)."""
import copy
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import expected, filters, gate
from tbuilder.build import build, build_file
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, SPECS

SPEC = json.loads((SPECS / "top_after.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_products.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))
WEST = [r for r in ROWS if r["Region"] == "West"]


def sums(field, rows):
    out = defaultdict(float)
    for r in rows:
        out[r["Product"]] += float(r[field])
    return out


def top(values, n):
    return set(sorted(values, key=lambda k: -values[k])[:n])


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Expected(unittest.TestCase):
    """Region = West: the rank sees the West rows; the Top N filter of 020 the whole data."""

    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])

    def test_ranked_after_the_filters(self):
        west = sums("Sales", WEST)
        self.assertEqual({k: round(v, 2) for k, v in self.got["Top 5 in Region"].items()},
                         {k: round(west[k], 2) for k in top(west, 5)})

    def test_before_the_filters_is_another_list(self):
        overall, west = sums("Sales", ROWS), sums("Sales", WEST)
        self.assertEqual(set(self.got["Top 5 Overall"]), top(overall, 5))
        self.assertNotEqual(set(self.got["Top 5 Overall"]), set(self.got["Top 5 in Region"]))
        self.assertEqual(round(self.got["Top 5 Overall"]["Cobalt"], 2), round(west["Cobalt"], 2))

    def test_after_the_measure_filter(self):
        """Tableau: the measure filter (SUM(Sales) <= 3 800) before the table calc filter."""
        west, q, n = sums("Sales", WEST), sums("Quantity", WEST), defaultdict(int)
        for r in WEST:
            n[r["Product"]] += 1
        avg = {k: q[k] / n[k] for k in q if west[k] <= 3800}
        self.assertEqual(set(self.got["Busiest Small Sellers"]), top(avg, 3))
        self.assertNotEqual(top(avg, 3), top({k: q[k] / n[k] for k in q}, 3))  # the filter changes the list

    def test_ties_at_the_n_th_place_are_kept(self):
        """Competition rank (1, 2, 2, 4): every member tied at the N-th place has rank <= N."""
        groups = {"a": [5], "b": [4], "c": [4], "d": [3], "e": [None]}
        value = lambda rs: rs[0]  # noqa: E731
        self.assertEqual(filters.rank_members(groups, value, 2), {"a", "b", "c"})
        self.assertEqual(filters.rank_members(groups, value, 3), {"a", "b", "c"})
        self.assertEqual(filters.rank_members(groups, value, 4), {"a", "b", "c", "d"})  # Null has no rank


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPECS / "top_after.json", OUT / "top_after.twbx"))

    def view(self, name):
        return ws(self.root, name).find("table/view")

    def test_rank_instance_and_members(self):
        view = self.view("Top 5 in Region")
        ci = view.find("datasource-dependencies/column-instance[@name='[rank:sum:Sales:ok]']")
        self.assertEqual((ci.get("column"), ci.get("derivation"), ci.get("type")), ("[Sales]", "Sum", "ordinal"))
        tc = ci.find("table-calc")
        self.assertEqual((tc.get("type"), tc.get("rank-options"), tc.get("ordering-type")),
                         ("Rank", "Competition,Descending", "Field"))
        self.assertTrue(tc.get("ordering-field").endswith(".[none:Product:nk]"))
        flt = next(f for f in view.findall("filter") if f.get("column").endswith(".[rank:sum:Sales:ok]"))
        self.assertEqual([g.get("member") for g in flt.find("groupfilter")], ["1", "2", "3", "4", "5"])
        self.assertEqual(view.findall("slices/column")[-1].text, flt.get("column"))
        # not on a shelf: the bars are Product x SUM(Sales)
        self.assertNotIn("rank:", ws(self.root, "Top 5 in Region").findtext("table/rows") +
                         ws(self.root, "Top 5 in Region").findtext("table/cols"))

    def test_average(self):
        names = [c.get("name") for c in self.view("Busiest Small Sellers").iter("column-instance")]
        self.assertIn("[rank:avg:Quantity:ok]", names)

    def test_before_unchanged(self):
        view = self.view("Top 5 Overall")
        self.assertIsNotNone(view.find("filter/groupfilter[@function='end']"))
        self.assertFalse([c for c in view.iter("column-instance") if c.get("name").startswith("[rank:")])


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """golden_top_after_2025_1: specs/top_after.json re-saved by Desktop 2025.1 (resave CLEAN, 3/3 sheets) = the
        generator's output: Desktop kept the rank instance off the shelves, its filter and slice."""
        import difflib
        from test_roundtrip import canon, normalize, read_twbx
        got, names = read_twbx(build_file(SPECS / "top_after.json", OUT / "roundtrip_top_after.twbx"))
        self.assertIn("Data/sample/sales_products.csv", names)
        want, _ = read_twbx(ROOT / "golden" / "golden_top_after_2025_1.twbx")
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))

    def test_rebuild_reads_the_rank(self):
        """The golden read as a foreign book: the rank filter becomes top.after, the Top N stays a Top N."""
        import tempfile
        from pathlib import Path
        from tbuilder import rebuild
        with tempfile.TemporaryDirectory() as tmp:
            r = rebuild.rebuild(ROOT / "golden" / "golden_top_after_2025_1.twbx", Path(tmp) / "spec.json")
            got = json.loads((Path(tmp) / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(r.skipped, [])
        tops = {s["name"]: s["top"] for s in got["sheets"]}
        self.assertEqual(tops, {"Top 5 in Region": {"n": 5, "after": "filters"}, "Top 5 Overall": {"n": 5},
                                "Busiest Small Sellers": {"n": 3, "after": "filters"}})


class Refusals(unittest.TestCase):
    def build(self, spec):
        return build(spec, OUT / "top_after_refused.twbx", SPECS)

    def test_parameter_n(self):
        def f(s):
            s["parameters"] = [{"name": "N", "type": "integer", "values": [3, 5], "default": 5}]
            sheet(s, "Top 5 in Region")["top"]["n"] = "N"
        with self.assertRaisesRegex(ValueError, "a number from 2"):
            self.build(mutate(f))

    def test_n_one(self):
        with self.assertRaisesRegex(ValueError, "a number from 2"):
            self.build(mutate(lambda s: sheet(s, "Top 5 in Region")["top"].update(n=1)))

    def test_by(self):
        with self.assertRaisesRegex(ValueError, "'by' is not supported"):
            self.build(mutate(lambda s: sheet(s, "Top 5 in Region")["top"].update(by={"field": "Profit"})))

    def test_color_split(self):
        with self.assertRaisesRegex(ValueError, "a bar of one dimension"):
            self.build(mutate(lambda s: sheet(s, "Top 5 in Region").update(color="Region")))

    def test_schema_only_filters(self):
        with self.assertRaisesRegex(ValueError, "after"):
            self.build(mutate(lambda s: sheet(s, "Top 5 in Region")["top"].update(after="context")))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPECS / "top_after.json", OUT / "top_after_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith("[filters]") and text in i for i in issues), issues)

    @staticmethod
    def rank(r, name="Top 5 in Region"):
        view = ws(r, name).find("table/view")
        ci = next(c for c in view.iter("column-instance") if c.get("name").startswith("[rank:"))
        flt = next(f for f in view.findall("filter") if f.get("column").endswith(ci.get("name")))
        return view, ci, flt

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_member_gap(self):
        def f(r):
            g = self.rank(r)[2].find("groupfilter")
            g.remove(g[2])
        self.assertCaught(f, "are not the ranks 1..N")

    def test_member_quoted(self):
        self.assertCaught(lambda r: self.rank(r)[2].find("groupfilter")[0].set("member", '"1"'),
                          "are not the ranks 1..N")

    def test_no_rank_table_calc(self):
        def f(r):
            ci = self.rank(r)[1]
            ci.remove(ci.find("table-calc"))
        self.assertCaught(f, "has no Rank table calc")

    def test_rank_options(self):
        self.assertCaught(lambda r: self.rank(r)[1].find("table-calc").set("rank-options", "Descending"),
                          "are not a kind and a direction")

    def test_continuous_instance(self):
        self.assertCaught(lambda r: self.rank(r)[1].set("type", "quantitative"), "not a discrete aggregate")

    def test_rank_of_text(self):
        self.assertCaught(lambda r: self.rank(r)[1].set("column", "[Product]"), "not a declared number")

    def test_not_declared(self):
        def f(r):
            view, ci, _ = self.rank(r)
            ci.getparent().remove(ci)
        self.assertCaught(f, "not a declared instance")

    def test_not_in_slices(self):
        def f(r):
            view, _, flt = self.rank(r)
            sl = view.find("slices")
            sl.remove(next(c for c in sl if c.text == flt.get("column")))
        self.assertCaught(f, "is not in the sheet's slices")

    def test_along_a_field_off_the_sheet(self):
        """check_table_calcs: the rank's compute-using is on the sheet."""
        def f(r):
            tc = self.rank(r)[1].find("table-calc")
            tc.set("ordering-field", tc.get("ordering-field").replace("[none:Product:nk]", "[none:Region:nk]"))
        issues = [str(i) for i in gate.run(repack(f, source=self.path))]
        self.assertTrue(any("is not on the sheet's rows, columns or marks" in i for i in issues), issues)


if __name__ == "__main__":
    unittest.main()
