"""Blocks of workbooks (decisions/196): the sheets' statuses, a dashboard as rows and columns, picks and a layout in a spec."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from lxml import etree

from tbuilder import refs_catalog, spec as spec_mod, user_profile

ROOT = Path(__file__).resolve().parent.parent
DS = "[ds]"


def sheet(name, rows="", cols="", marks=("Automatic",), enc=(), fold=False):
    axis = "" if len(marks) == 1 else " y-axis-name='[ds].[sum:M:qk]'"
    encodings = "".join(f"<{e} column='[ds].[sum:M:qk]'/>" for e in enc)
    panes = "".join(f"<pane{axis}><mark class='{m}'/><encodings>{encodings}</encodings></pane>" for m in marks)
    style = "<style><style-rule element='axis'><encoding attr='space' fold='true'/></style-rule></style>" if fold else ""
    return f"<worksheet name='{name}'><table>{style}<panes>{panes}</panes><rows>{rows}</rows><cols>{cols}</cols></table></worksheet>"


def status(xml, calcs=None, formula_of=None):
    return refs_catalog.classify(etree.fromstring(xml), calcs, formula_of)


def m(field, agg="sum"):
    return f"{DS}.[{agg}:{field}:qk]"


def d(field):
    return f"{DS}.[none:{field}:nk]"


DATE = f"{DS}.[tmn:Date:qk]"


class Forms(unittest.TestCase):
    def check(self, xml, form, spec_type, state="covered", calcs=None, formula_of=None):
        got = status(xml, calcs, formula_of)
        self.assertEqual((got["form"], got["spec_type"], got["status"]), (form, spec_type, state))
        return got

    def test_the_generator_has_these(self):
        self.check(sheet("s", d("A"), m("X"), ("Bar",)), "bar", "bar")
        self.check(sheet("s", m("X"), DATE, ("Line",)), "line", "line")
        self.check(sheet("s", m("X"), DATE, ("Automatic",)), "line", "line")
        self.check(sheet("s", m("X"), DATE, ("Area",)), "area", "area")
        self.check(sheet("s", enc=("text",)), "KPI", "kpi")
        self.check(sheet("s", enc=("size", "text")), "treemap", "treemap")
        self.check(sheet("s", m("Y"), m("X"), ("Circle",)), "scatter", "scatter")
        self.check(sheet("s", d("A"), f"({m('X')} + {m('Y')})", ("Pie", "Pie"), ("wedge-size",), fold=True), "donut", "donut")
        self.check(sheet("s", d("A"), d("B"), ("Square",), ("color",)), "heatmap", "heatmap")

    def test_side_by_side_measures_are_a_table_a_fold_is_one_axis(self):
        self.check(sheet("s", d("A"), f"({m('X')} + ({m('Y')} + {m('Z')}))", ("Bar", "Bar", "Bar")), "table of measures", "registry")
        self.check(sheet("s", f"({m('X')} + {m('Y')})", d("A"), ("Bar", "Line"), fold=True), "combo bar + line", "combo")

    def test_a_fold_of_the_same_measure_is_a_total_label(self):
        self.check(sheet("s", f"({m('X')} + {m('X')})", d("A"), ("Bar", "GanttBar"), fold=True), "stacked bar with totals", "bar")
        self.check(sheet("s", f"({m('X')} + {m('Y')})", d("A"), ("Bar", "GanttBar"), fold=True), "bar + target", "bar")

    def test_a_ranked_line_with_badges_is_a_bump(self):
        self.check(sheet("s", f"({m('R', 'usr')} + {m('R2', 'usr')})", DATE, ("Line", "Shape"), fold=True), "bump", "bump", calcs={"R": "RANK(SUM([X]))"})
        self.check(sheet("s", f"({DS}.[rank:sum:X:qk:2] + {DS}.[rank:sum:X:qk:3])", DATE, ("Line", "Shape"), fold=True), "bump", "bump")

    def test_bar_in_bar_is_only_vertical_in_the_generator(self):
        self.check(sheet("s", f"({m('X')} + {m('Y')})", d("A"), ("Bar", "Bar"), fold=True), "bar in bar", "bar")
        self.check(sheet("s", d("A"), f"({m('X')} + {m('Y')})", ("Bar", "Bar"), fold=True), "bar in bar", "bar", "partial")

    def test_partial_says_what_is_missing(self):
        got = self.check(sheet("s", d("A"), m("X"), ("Pie",)), "pie", "donut", "partial")
        self.assertTrue(got["missing"])

    def test_not_covered(self):
        self.check(sheet("s", d("A"), m("X"), ("Polygon",)), "custom geometry", None, "not supported yet")
        self.check(sheet("s", m("Y"), m("X"), ("Circle",)), "custom geometry", None, "not supported yet", calcs={"x": "COS([a]) * 2"})
        self.check(sheet("s", d("A"), m("X"), ("Line",), ("path",)), "custom path", None, "not supported yet")
        self.check(sheet("s", d("A"), m("X"), ("Density",)), "density", None, "not supported yet")
        self.check(sheet("s", d("A"), m("X"), ("Sankey",)), "viz extension", None, "not supported yet")

    def test_a_label_on_a_constant_axis_is_a_helper(self):
        got = status(sheet("s", m("One", "usr"), d("A"), ("Bar",)), formula_of={"One": "MIN(1)"})
        self.assertEqual(got["role"], "helper")
        got = status(sheet("s", d("B"), f"{d('A')} / {m('One', 'usr')}", ("Bar",)), formula_of={"One": "MIN(1)"})
        self.assertEqual((got["spec_type"], got["status"]), ("registry", "partial"))
        self.assertEqual(status(sheet("s", marks=("Shape",)))["role"], "helper")
        self.assertEqual(status(sheet("s", marks=("Polygon",)))["role"], "helper")


def zone(name=None, box=(0, 0, 100000, 100000), kids="", kind=None, fill=None, param=None):
    attrs = "".join(f" {k}='{v}'" for k, v in zip("xywh", box))
    attrs += f" name='{name}'" if name else ""
    attrs += f" type-v2='{kind}'" if kind else ""
    attrs += f" param='{param}'" if param else ""
    style = f"<zone-style><format attr='background-color' value='{fill}'/></zone-style>" if fill else ""
    return f"<zone{attrs}>{kids}{style}</zone>"


def flow(box, kids, fill=None, param="vert"):
    return zone(box=box, kids=kids, kind="layout-flow", fill=fill, param=param)


def bar(name):
    return sheet(name, d("A"), m("X"), ("Bar",))


def kpi(name):
    return sheet(name, enc=("text",))


def book(sheets, zones, name="One", size=(1400, 800)):
    return (f"<workbook source-build='2025.1.0'><worksheets>{''.join(sheets)}</worksheets><dashboards>"
            f"<dashboard name='{name}'><size maxheight='{size[1]}' maxwidth='{size[0]}'/><zones>{zones}</zones></dashboard>"
            "</dashboards></workbook>")


def write(folder, xml, file="book.twb"):
    path = Path(folder) / file
    path.write_text(xml, encoding="utf-8")
    return path


GRID = zone(kind="layout-basic", kids=(
    zone(box=(0, 0, 100000, 10000), kind="text")
    + flow((0, 10000, 100000, 20000), zone("K1", (0, 10000, 50000, 20000)) + zone("K2", (50000, 10000, 50000, 20000)), param="horz")
    + flow((0, 30000, 100000, 70000), zone("A", (0, 30000, 70000, 70000))
           + flow((70000, 30000, 30000, 70000), zone("B", (70000, 30000, 30000, 25000)) + zone("C", (70000, 55000, 30000, 45000))), param="horz")))
GRID_SHEETS = [kpi("K1"), kpi("K2"), bar("A"), bar("B"), bar("C")]


class Layouts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def layout(self, sheets, zones):
        return refs_catalog.read_book(write(self.dir, book(sheets, zones)))["dashboards"][0]["layout"]

    def test_rows_and_columns_in_proportion(self):
        lt = self.layout(GRID_SHEETS, GRID)
        self.assertEqual(lt["status"], "covered")
        self.assertEqual(lt["shape"], "1 / 1 + [1 / 1]")
        self.assertEqual(lt["row_heights"], [2, 7])
        self.assertEqual(lt["grid"][0][0]["sheet"], "S1")
        cols = lt["grid"][1]
        self.assertEqual([c["width"] for c in cols], [7, 3])
        self.assertEqual(cols[1]["row_heights"], [5, 9])
        self.assertLess(lt["error_pct"], 3)

    def test_kpi_cards_in_a_row_are_one_slot(self):
        slots = self.layout(GRID_SHEETS, GRID)["slots"]
        self.assertEqual((slots[0]["kind"], slots[0]["kpi_cards"], slots[0]["sheets"]), ("kpi", 2, ["K1", "K2"]))

    def test_a_floating_dashboard_is_not_covered(self):
        zones = zone(kind="bitmap") + zone("A", (0, 0, 50000, 100000)) + zone("B", (50000, 0, 50000, 100000))
        lt = self.layout([bar("A"), bar("B")], zones)
        self.assertEqual(lt["status"], "not supported yet")
        self.assertEqual(lt["floating_share"], 1)
        self.assertNotIn("grid", lt)

    def test_floating_sheets_over_a_tiled_root_are_not_covered(self):
        zones = zone(kind="layout-basic", kids=zone("A", (0, 0, 100000, 50000))) + zone("B", (0, 50000, 100000, 50000))
        self.assertEqual(self.layout([bar("A"), bar("B")], zones)["status"], "not supported yet")

    def test_floating_decoration_is_left_out(self):
        zones = zone(kind="layout-basic", kids=zone("A", (0, 0, 100000, 100000))) + zone(box=(90000, 0, 2000, 3000), kind="bitmap")
        lt = self.layout([bar("A")], zones)
        self.assertEqual(lt["status"], "partial")
        self.assertIn("left out", lt["why"][0])

    def test_a_floating_zone_is_not_covered_in_the_zone_list(self):
        zones = zone(kind="layout-basic", kids=zone("A", (0, 0, 100000, 100000))) + zone("B", (90000, 0, 1000, 1000))
        book_ = refs_catalog.read_book(write(self.dir, book([bar("A"), bar("B")], zones)))
        by_name = {z["name"]: z for z in book_["dashboards"][0]["zones"]}
        self.assertEqual((by_name["A"]["status"], by_name["B"]["status"]), ("covered", "not supported yet"))

    def test_a_card_of_several_sheets_is_one_block(self):
        card = flow((0, 0, 40000, 50000), zone("K", (0, 0, 40000, 10000)) + zone("A", (0, 10000, 40000, 40000)), fill="#eeeeee")
        zones = zone(kind="layout-basic", kids=card + zone("B", (40000, 0, 60000, 50000)))
        slots = self.layout([kpi("K"), bar("A"), bar("B")], zones)["slots"]
        self.assertEqual([s["sheets"] for s in slots], [["K", "A"], ["B"]])

    def test_table_columns_side_by_side_are_one_block(self):
        cols = "".join(zone(n, (i * 30000, 0, 30000, 100000)) for i, n in enumerate("ABC"))
        zones = zone(kind="layout-basic", kids=flow((0, 0, 90000, 50000), cols, param="horz"))
        slots = self.layout([bar(n) for n in "ABC"], zones)["slots"]
        self.assertEqual((len(slots), slots[0]["kind"]), (1, "registry"))

    def test_too_many_cells_is_not_covered_and_says_why(self):
        cells = "".join(zone(f"S{i}", (i * 12000, 0, 12000, 100000)) for i in range(8))
        lt = self.layout([bar(f"S{i}") for i in range(8)], zone(kind="layout-basic", kids=cells))
        self.assertEqual(lt["status"], "not supported yet")
        self.assertIn("8 blocks", lt["why"][0])

    def test_overlapping_tiled_zones_are_not_covered(self):
        zones = zone(kind="layout-basic", kids=zone("A", (0, 0, 60000, 60000)) + zone("B", (40000, 40000, 60000, 60000)))
        self.assertEqual(self.layout([bar("A"), bar("B")], zones)["status"], "not supported yet")

    def test_weights_stay_in_the_schema(self):
        self.assertEqual(refs_catalog._weights([1, 1, 1]), [1, 1, 1])
        self.assertTrue(all(1 <= w <= 12 for w in refs_catalog._weights([1, 500, 90000])))


class Picks(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.src = self.dir / "src"
        self.src.mkdir()
        self.out = self.dir / "acme"
        self.todo = self.out / "requests.md"
        sheets = GRID_SHEETS + [sheet("Radial", d("A"), m("X"), ("Polygon",)), sheet("Pie", d("A"), m("X"), ("Pie",))]
        self.book = write(self.src, book(sheets, GRID), "good.twb")
        refs_catalog.make([self.book], self.out, {"url": "https://public.tableau.com/app/x"})

    def cat(self):
        return json.loads((self.out / "refs" / "catalog.json").read_text(encoding="utf-8"))

    def number(self, name):
        return next(str(s["id"]) for b in self.cat()["books"] for s in b["sheets"] if s["name"] == name)

    def pick(self, *refs):
        return refs_catalog.pick(self.out, list(refs), "2026-11-03")

    def profile(self):
        return yaml.safe_load((self.out / "profile.yaml").read_text(encoding="utf-8"))

    def test_catalog_finds_the_book_and_writes_the_gallery(self):
        b = self.cat()["books"][0]
        self.assertEqual(b["url"], "https://public.tableau.com/app/x")
        self.assertEqual([x["name"] for x in b["dashboards"]], ["One"])
        self.assertEqual(len(b["sheets"]), 7)
        self.assertEqual({z["kind"] for z in b["dashboards"][0]["zones"]}, {"sheet", "text"})
        gallery = (self.out / "refs" / "gallery.md").read_text(encoding="utf-8")
        self.assertIn("| L1 | One | 1400x800 | covered |", gallery)
        self.assertIn("| not supported yet |", gallery)

    def test_a_new_book_keeps_the_numbers(self):
        before = self.number("Radial")
        other = write(self.src, book([bar("Z")], zone(kind="layout-basic", kids=zone("Z"))), "other.twb")
        refs_catalog.make([other], self.out)
        self.assertEqual(self.number("Radial"), before)
        self.assertEqual(self.cat()["books"][0]["url"], "https://public.tableau.com/app/x")
        self.assertEqual(len(self.cat()["books"]), 2)

    def test_covered_goes_to_prefer_and_the_profile_stays_valid(self):
        out = self.pick(self.number("A"))
        raw = self.profile()
        self.assertEqual(raw["prefer"], {"comparison": "bar"})
        self.assertEqual(user_profile.problems(raw), [])
        self.assertEqual(raw["sources"][0]["picked"], ["A"])
        self.assertEqual(out["requests"], [])
        self.assertIn("covered", (self.out / "refs.md").read_text(encoding="utf-8"))

    def test_partial_goes_to_prefer_with_its_gap_in_refs_md(self):
        self.pick(self.number("Pie"))
        self.assertEqual(self.profile()["prefer"], {"part_to_whole": "donut"})
        self.assertIn("a whole pie", (self.out / "refs.md").read_text(encoding="utf-8"))

    def test_not_covered_goes_to_the_plan_once(self):
        n = self.number("Radial")
        self.assertEqual(len(self.pick(n)["requests"]), 1)
        self.assertEqual(self.pick(n)["requests"], [])
        text = self.todo.read_text(encoding="utf-8")
        self.assertEqual(text.count("`Radial`"), 1)
        self.assertIn("https://public.tableau.com/app/x", text)
        self.assertNotIn("prefer", self.profile())

    def test_a_sheet_gets_its_reading(self):
        out = self.pick(self.number("A"))
        text = Path(out["read"][0]).read_text(encoding="utf-8")
        self.assertIn("## Mechanics", text)
        self.assertIn("Layer 1**: Bar", text)

    def test_a_second_pick_replaces_prefer_and_says_so(self):
        n = self.number("A")
        self.pick(n)
        raw = self.profile()
        raw["prefer"]["comparison"] = "bullet"
        (self.out / "profile.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
        self.assertIn("bullet -> bar", self.pick(n)["moved"][0])
        rows = [r for r in (self.out / "refs.md").read_text(encoding="utf-8").splitlines() if r.startswith(f"| {n} |")]
        self.assertEqual(len(rows), 1)

    def test_a_whole_book_prefers_what_it_uses_most(self):
        out = self.pick("B1")
        self.assertEqual(out["whole_books"], ["good.twb"])
        self.assertEqual(out["prefer"], {"comparison": "bar", "kpi": "cards"})
        self.assertEqual(out["requests"], [])

    def test_a_layout_pick_and_a_floating_one(self):
        self.assertEqual(self.pick("L1")["layout"], {"file": "refs/good.twb", "dashboard": "One"})
        floating = write(self.src, book([bar("Q")], zone(kind="bitmap") + zone("Q"), "Floaty"), "fl.twb")
        refs_catalog.make([floating], self.out)
        with self.assertRaisesRegex(refs_catalog.SourceError, "not supported yet"):
            self.pick("L2")

    def test_a_wrong_number(self):
        with self.assertRaisesRegex(refs_catalog.SourceError, "no such number"):
            self.pick("99")

    def spec(self):
        return {"version": 1, "datasource": {"type": "csv", "path": "x.csv"},
                "sheets": [{"name": n, "type": "bar", "dimension": "A", "measure": {"field": "X"}} for n in ("N1", "N2", "N3", "N4")],
                "dashboard": {"name": "D", "title": "T", "grid": [["N1"]]}}

    def test_a_layout_goes_in_a_spec(self):
        lt = self.cat()["books"][0]["dashboards"][0]["layout"]
        out = refs_catalog.apply_layout(lt, {"S1": "N1", "S2": "N2", "S3": "N3", "S4": "N4"}, self.spec())
        dash = out["dashboard"]
        self.assertEqual((dash["width"], dash["height"], dash["title"]), (1400, 800, "T"))
        self.assertEqual(dash["grid"][0], [{"sheet": "N1", "width": 1}])
        self.assertEqual(dash["grid"][1][1]["rows"][1][0]["sheet"], "N4")
        spec_mod.validate(out)

    def test_every_slot_is_filled_by_a_sheet_of_the_spec(self):
        lt = self.cat()["books"][0]["dashboards"][0]["layout"]
        with self.assertRaisesRegex(refs_catalog.SourceError, "Not filled: S4"):
            refs_catalog.apply_layout(lt, {"S1": "N1", "S2": "N2", "S3": "N3"}, self.spec())
        with self.assertRaisesRegex(refs_catalog.SourceError, "Not sheets of the spec: Nope"):
            refs_catalog.apply_layout(lt, {"S1": "Nope", "S2": "N2", "S3": "N3", "S4": "N4"}, self.spec())

    def test_cli(self):
        run = subprocess.run([sys.executable, "-m", "tbuilder", "pick-layout", str(self.out), "L1"], capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["shape"], "1 / 1 + [1 / 1]")
        run = subprocess.run([sys.executable, "-m", "tbuilder", "pick-charts", str(self.out), "--pick", "99"], capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
        self.assertEqual(run.returncode, 1)
        self.assertIn("no such number", run.stderr)


if __name__ == "__main__":
    unittest.main()
