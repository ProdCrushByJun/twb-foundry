"""Desktop re-save + diff (decisions/054): what Desktop silently drops.

Without Desktop: the diff and its COSMETIC allowlist on saved XML pairs, the hybrid goldens (generator output of a
spec vs the same workbook saved by Desktop 2025.1) and synthetic mutants; the Save As safety (no dialog -> nothing is
typed). The real run is opt-in like test_desktop_check: TBUILDER_DESKTOP=1 (and the Desktop queue).
"""
import gzip
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

from tbuilder import __main__ as cli
from tbuilder import desktop_check as dc
from tbuilder import resave as rs
from tbuilder.build import build_file
from test_desktop_check import _repack
from test_roundtrip import ROOT

FIXTURES = ROOT / "tests" / "fixtures" / "resave"
GOLDEN_NAME = re.compile(r"^golden(?:_(?P<name>[^.]+?))?_2025_1$")
# What is left after the allowlist on a golden pair and why it is not Desktop's rewrite
STALE = {}  # golden_charts lost its stale CSV separator when decisions/066 re-saved it
# Rules no golden pair needs any more: golden_charts (re-saved in 066) was the last golden saved with a dashboard's
# selected zone; the rule keeps its own test (DiffTest.test_ui_state)
UNUSED = {"active-zone"}


# ---- hybrid-golden pairs -----------------------------------------------------------------------------------------
def golden_pairs(root=ROOT):
    """[(spec, golden .twbx)] for every golden whose spec is there (the naming of tbuilder/regress.py)."""
    out = []
    for g in sorted((root / "golden").glob("golden*_2025_1.twbx")):
        m = GOLDEN_NAME.match(g.stem)
        if not m:
            continue
        name = m.group("name")
        for spec in ([root / "specs" / f"{name or 'golden'}.json"]
                     + ([root / "acceptance" / name.replace("_", "-") / "spec.json"] if name else [])):
            if spec.is_file():
                out.append((spec, g))
                break
    return out


def _ids(root):
    """{role: id} of the ids the generator draws at random on each build."""
    ids = {}
    for i, ds in enumerate(d for d in root.find("datasources") if d.get("name") != "Parameters"):
        ids[f"ds{i}"] = ds.get("name")
        for j, nc in enumerate(ds.iterfind(".//named-connection")):
            ids[f"ds{i}.conn{j}"] = nc.get("name")
        for j, ob in enumerate(ds.iterfind("object-graph/objects/object")):
            ids[f"ds{i}.obj{j}"] = ob.get("id")
    for sect in ("worksheets", "dashboards", "windows"):
        for el in root.find(sect) if root.find(sect) is not None else []:
            sid = el.find("simple-id")
            if sid is not None:
                ids[f"{sect}:{el.get('class', '')}:{el.get('name')}"] = sid.get("uuid")
    return ids


def align_ids(generated, golden):
    """The generated XML root with its random ids replaced by the golden's ones (the build before the save drew
    those), so that the diff shows only what Desktop rewrote."""
    a, b = _ids(generated), _ids(golden)
    text = ET.tostring(generated, encoding="unicode")
    for role, v in a.items():
        if v and b.get(role) and v != b[role]:
            text = text.replace(v, b[role])
    return ET.fromstring(text)


# ---- mutants -------------------------------------------------------------------------------------------------------
def palette_fields(root):
    """Fields of the palette maps in datasource styles."""
    return [e.get("field") for ds in root.iter("datasource")
            for e in ds.findall("style/style-rule[@element='mark']/encoding[@type='palette']")]


def drop_palette_instances(root):
    """decisions/013, 016: a palette map in datasource/style whose field has no column-instance in the datasource.
    Desktop opens it without a word and forgets the map (the bars get the default palette)."""
    for ds in root.iter("datasource"):
        fields = {e.get("field") for e in ds.findall("style/style-rule[@element='mark']/encoding[@type='palette']")}
        for ci in ds.findall("column-instance"):
            if ci.get("name") in fields:
                ds.remove(ci)


def make_palette_mutant(src, dst):
    """A copy of the book without the column-instances of its palette maps -> the fields affected."""
    with zipfile.ZipFile(src) as z:
        twb = next(n for n in z.namelist() if n.endswith(".twb"))
        fields = palette_fields(ET.fromstring(z.read(twb)))
    _repack(src, dst, drop_palette_instances)
    return fields


def saved_pair(name):
    """A real pair saved from Desktop 2025.1 (2026-10-21): the book --resave opened and what Desktop wrote back."""
    return tuple(ET.fromstring(gzip.decompress((FIXTURES / f"{name}{x}.twb.gz").read_bytes()))
                 for x in ("", ".resaved"))


def reread(root):
    return ET.fromstring(ET.tostring(root))


def kinds(items):
    return {(i.kind, i.tag, i.attr) for i in items}


class GoldenPairsTest(unittest.TestCase):
    """Every hybrid golden is a Desktop re-save of the generator output: after the allowlist nothing is left."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.pairs = golden_pairs()

    def test_enough_pairs(self):
        self.assertGreaterEqual(len(self.pairs), 25)

    def test_nothing_left_on_any_golden(self):
        used = set()
        for spec, golden in self.pairs:
            with self.subTest(golden=golden.stem):
                gen = align_ids(rs.read_twb(build_file(spec, self.out / f"{golden.stem}.twbx")), rs.read_twb(golden))
                items = rs.diff(gen, rs.read_twb(golden))
                left = rs.explain(items)
                used |= {i.rule for i in items if i.rule}
                self.assertEqual(kinds(left), STALE.get(golden.stem, set()), "\n".join(map(str, left)))
        # every rule but pixel-snap (the generator writes Desktop's grid itself, tested below) is needed somewhere
        self.assertEqual(used, {r.name for r in rs.COSMETIC} - {"pixel-snap"} - UNUSED)

    def test_the_golden_is_its_own_resave(self):
        g = rs.read_twb(ROOT / "golden" / "golden_cards_2025_1.twbx")
        self.assertEqual(rs.diff(g, reread(g)), [])


class DiffTest(unittest.TestCase):
    GOLDEN = ROOT / "golden" / "golden_cards_2025_1.twbx"

    def setUp(self):
        self.root = rs.read_twb(self.GOLDEN)




    def test_space_run_dropped_does_not_shift_the_rest(self):
        """lessons: Desktop drops a <run> that is only a space; the runs after it still pair with themselves."""
        a = ET.fromstring("<formatted-text><run bold='true'>Sales</run><run> </run><run>x</run><run>y</run>"
                          "</formatted-text>")
        b = ET.fromstring("<formatted-text><run bold='true'>Sales</run><run>x</run><run>y</run></formatted-text>")
        self.assertEqual([(i.kind, i.path) for i in rs.diff(a, b)], [("dropped", "/formatted-text/run#2")])

    def test_attribute_order_crlf_declaration_are_not_differences(self):
        a = b"<?xml version='1.0' encoding='utf-8' ?>\n<w a='1' b='2'>\n  <x c='3'>t</x>\n</w>"
        b = b"<!-- build 20251.25.0313.2002 -->\r\n<w b='2' a='1'>\r\n    <x c='3'>  t </x>\r\n</w>"
        self.assertEqual(rs.diff(ET.fromstring(a), ET.fromstring(b)), [])

    def test_keyed_siblings_in_another_order_are_not_differences(self):
        a = ET.fromstring("<s><encoding field='[a]'/><encoding field='[b]'/></s>")
        b = ET.fromstring("<s><encoding field='[b]'/><encoding field='[a]'/></s>")
        self.assertEqual(rs.diff(a, b), [])

    def test_changed_value_is_one_change(self):
        a = ET.fromstring("<s><format attr='margin' value='4'/></s>")
        b = ET.fromstring("<s><format attr='margin' value='8'/></s>")
        self.assertEqual([str(i) for i in rs.diff(a, b)], ["changed /s/format[attr=margin] @value: '4' -> '8'"])

    def zone_change(self, attr, old, new, type_v2=None):
        z = ET.Element("zone", {"id": "7", attr: old, **({"type-v2": type_v2} if type_v2 else {})})
        return rs.Item(rs.CHANGED, "/x/zone", z, attr, old, new, size=(1200, 800))

    def test_pixel_snap(self):
        """card_lefts: 1 px of a 1200 px dashboard = 83.3 units; a rounding inside a pixel is Desktop's grid."""
        self.assertEqual(rs.explain([self.zone_change("x", "85000", "85042")]), [])
        self.assertEqual(len(rs.explain([self.zone_change("x", "85000", "85200")])), 1)  # 2.4 px: a real move
        self.assertEqual(rs.explain([self.zone_change("h", "11500", "11620")]), [])      # 0.96 px of 800
        it = self.zone_change("x", "85000", "85042")
        it.size = None  # not on a dashboard
        self.assertEqual(len(rs.explain([it])), 1)

    def test_card_heights_only_for_legends_and_filters(self):
        self.assertEqual(rs.explain([self.zone_change("h", "17250", "18875", "filter")]), [])
        self.assertEqual(len(rs.explain([self.zone_change("h", "17250", "18875")])), 1)  # a sheet zone
        self.assertEqual(len(rs.explain([self.zone_change("w", "17250", "18875", "color")])), 1)

    def test_ui_state(self):
        root = ET.fromstring("<workbook><windows><window class='worksheet' name='A'><viewpoint/></window>"
                             "<window class='worksheet' name='B'><viewpoint><zoom type='entire-view'/></viewpoint>"
                             "</window><window class='dashboard' name='D'><active id='-1'/></window></windows>"
                             "</workbook>")
        saved = ET.fromstring("<workbook><windows><window class='worksheet' name='A'/>"
                              "<window class='worksheet' name='B'><viewpoint/></window>"
                              "<window class='dashboard' name='D'><active id='12'/></window></windows>"
                              "<thumbnails><thumbnail name='A'/></thumbnails></workbook>")
        left = rs.explain(rs.diff(root, saved))
        # the fit of sheet B is a setting, not UI state: Desktop dropping it is reported
        self.assertEqual([(i.kind, i.tag) for i in left], [("dropped", "zoom")])

    def test_approx_count_is_desktops_own(self):
        """decisions/080, real pairs from the lab: Desktop overwrites a Hyper column's approx-count with its own
        estimate and drops one written on a CSV column that has values; both are Desktop's cache, not a loss."""
        book, saved = saved_pair("approx_hyper_wrong")  # every record exact + 100 -> Desktop's exact count
        items = rs.diff(book, saved)
        self.assertEqual(rs.explain(items), [])
        self.assertEqual(sorted({(i.kind, i.tag, i.rule) for i in items if i.tag == "approx-count"}),
                         [("changed", "approx-count", "approx-count")])
        self.assertEqual(sum(i.tag == "approx-count" for i in items), 7)

    def test_approx_count_only_in_a_column_record(self):
        rec = "<metadata-records><metadata-record class='{}'><aggregation>Count</aggregation>{}</metadata-record>" \
              "</metadata-records>"
        added = rs.diff(ET.fromstring(rec.format("column", "")),
                        ET.fromstring(rec.format("column", "<approx-count>1</approx-count>")))
        self.assertEqual([(i.kind, i.rule) for i in added if not rs.explain([i])], [("added", "approx-count")])
        other = rs.diff(ET.fromstring(rec.format("capability", "")),
                        ET.fromstring(rec.format("capability", "<approx-count>1</approx-count>")))
        self.assertEqual(len(rs.explain(other)), 1)  # not a column record: reported

    def test_report_text(self):
        r = rs.Report("a.twbx", "a.resaved.twbx", [rs.Item(rs.ADDED, "/w/thumbnails", ET.Element("thumbnails"))])
        r.left = rs.explain(r.items)
        self.assertTrue(r.clean)
        self.assertIn("nothing dropped or changed by meaning", r.text())


class SaveAsTest(unittest.TestCase):
    """Save As blind is dangerous (lessons): nothing is typed unless the common file dialog is there."""

    def setUp(self):
        self.target = Path(tempfile.mkdtemp()) / "book.resaved.twbx"
        self.sent = []

    def run_save(self, dialog, kind_text="Tableau Packaged Workbooks (*.twbx)", invoked=True):
        texts = {}
        with mock.patch.object(rs, "menu", return_value=([("Save As...", True)], invoked)), \
                mock.patch.object(rs, "file_dialog", return_value=dialog), \
                mock.patch.object(rs, "get_text", side_effect=lambda h: kind_text if h == 3 else texts.get(h, "")), \
                mock.patch.object(rs, "set_text", side_effect=lambda h, t: texts.__setitem__(h, t)) as set_text, \
                mock.patch.object(rs, "command", side_effect=lambda h, c: self.sent.append((h, c))), \
                mock.patch.object(rs, "_problem", return_value=""), \
                mock.patch.object(rs, "DIALOG_WAIT_S", 0.3), mock.patch.object(rs, "SAVE_TIMEOUT_S", 0.5), \
                mock.patch.object(dc, "process_windows", return_value=[dc.Window(100, "Tableau - book", 0),
                                                                       dc.Window(2, "Save As", 100)]):
            try:
                rs.save_as(1, 100, self.target)
            finally:
                self.typed = [c.args for c in set_text.call_args_list]

    def test_no_menu_item_no_typing(self):
        with self.assertRaisesRegex(rs.ResaveError, "File > Save As... not reached"):
            self.run_save(None, invoked=False)
        self.assertEqual(self.typed, [])

    def test_no_dialog_no_typing(self):
        with self.assertRaisesRegex(rs.ResaveError, "the Save As dialog did not open"):
            self.run_save(None)
        self.assertEqual((self.typed, self.sent), ([], []))

    def test_not_a_packaged_workbook_is_cancelled(self):
        with self.assertRaisesRegex(rs.ResaveError, "not a packaged workbook"):
            self.run_save((2, 5, 3), kind_text="Tableau Workbooks (*.twb)")
        self.assertEqual((self.typed, self.sent), ([], [(2, rs.IDCANCEL)]))

    def test_name_typed_then_ok(self):
        with self.assertRaisesRegex(rs.ResaveError, "the Save As dialog is still up"):  # the fake never saves
            self.run_save((2, 5, 3))
        self.assertEqual((self.typed, self.sent), ([(5, str(self.target.resolve()))], [(2, rs.IDOK)]))


class SheetsTest(unittest.TestCase):
    """Every sheet: a copy per sheet not shown at open, with that sheet shown (no UI, decisions/054)."""

    def test_windows_of(self):
        self.assertEqual(rs.windows_of(rs.read_twb(ROOT / "golden" / "golden_2025_1.twbx")),
                         (["KPI", "Bar", "Line", "Table", "Overview"], "Overview"))

    def test_sheet_copies(self):
        d = Path(tempfile.mkdtemp())
        book = ROOT / "golden" / "golden_tablecalcs_2025_1.twbx"
        names, shown = rs.windows_of(rs.read_twb(book))
        copies = rs.sheet_copies(book, d)
        self.assertEqual([n for n, _ in copies], [n for n in names if n != shown])
        with zipfile.ZipFile(book) as z:
            members = sorted(z.namelist())
        for name, path in copies:
            root = rs.read_twb(path)
            self.assertEqual(rs.windows_of(root), (sorted(names, key=lambda n: n == name), name))
            self.assertEqual([w.get("name") for w in root.find("windows") if w.get("maximized")], [name])
            with zipfile.ZipFile(path) as z:
                self.assertEqual(sorted(z.namelist()), members)  # the data goes along
            # nothing else changed: the diff is the window order and the maximized flags
            self.assertEqual({(i.kind, i.tag, i.attr) for i in rs.diff(rs.read_twb(book), root)},
                             {("changed", "window", "maximized")})

    def test_resave_opens_each_copy(self):
        """resave(): Save As in the first process, then check() of each copy; a sheet that fails is reported."""
        d = Path(tempfile.mkdtemp())
        book = ROOT / "golden" / "golden_2025_1.twbx"
        calls = []

        def check(path, exe=None, timeout=None, logs=None, on_loaded=None):
            calls.append(Path(path).name)
            if on_loaded:
                on_loaded(7)
            bad = Path(path).name == "golden_2025_1.sheet2.twbx"
            return dc.Result(str(path), dc.CRASH if bad else dc.OK, "crash dump X" if bad else "")

        def save_as(pid, main, target, start, logs):
            target.write_bytes(book.read_bytes())
            return target

        with mock.patch.object(dc, "check", check), mock.patch.object(rs, "save_as", save_as), \
                mock.patch.object(dc, "process_windows", return_value=[dc.Window(100, "Tableau - golden_2025_1", 0)]):
            r = rs.resave(book, d)
        self.assertEqual(calls, ["golden_2025_1.twbx"] + [f"golden_2025_1.sheet{i}.twbx" for i in range(1, 5)])
        self.assertEqual(r.status, dc.OK)
        self.assertTrue(r.report.clean)
        self.assertEqual([(s, x.status) for s, x in r.bad_sheets], [("Bar", dc.CRASH)])
        self.assertFalse(r.clean)
        self.assertIn("sheet 'Bar': CRASH crash dump X", r.text())
        self.assertIn("every sheet shown at open: 3/4 OK", r.text())


class HelpersTest(unittest.TestCase):
    def test_parse_menu(self):
        out = "ITEM\tTrue\tSave\nITEM\tTrue\tSave As...\nITEM\tFalse\tRevert to Saved\nINVOKED\n"
        self.assertEqual(rs.parse_menu(out), [("Save", True), ("Save As...", True), ("Revert to Saved", False)])

    def test_find_log_prefers_the_slot_written_last(self):
        d = Path(tempfile.mkdtemp())
        (d / "log_1.txt").write_text('{"pid":42,"k":"x"}\n')
        (d / "log.txt").write_text('{"pid":42,"k":"x"}\n')
        os.utime(d / "log_1.txt", (1, 1))  # an old process with the same PID
        (d / "log_2_bk.txt").write_text('{"pid":42,"k":"x"}\n')
        self.assertEqual(rs.find_log(42, d).name, "log.txt")
        self.assertIsNone(rs.find_log(7, d))

    def test_launch_falls_back_to_a_child_process(self):
        with mock.patch.object(dc, "wmi_start", return_value=None), \
                mock.patch.object(dc, "_popen", return_value="child") as popen:
            self.assertEqual(dc._launch("tableau.exe", "a.twbx"), "child")
        popen.assert_called_once()

    def test_cli_dispatch(self):
        a = Namespace(twbx=[Path("a.twbx")], timeout=None, resave=True, out_dir=Path("o"), no_sheets=True)
        with mock.patch.object(rs, "main", return_value=0) as m, self.assertRaises(SystemExit):
            cli._check_desktop(a)
        self.assertEqual(m.call_args.args[0], ["a.twbx", "-d", "o", "--no-sheets"])


@unittest.skipUnless(dc.find_tableau() and os.environ.get("TBUILDER_DESKTOP") == "1",
                     "real Desktop run is opt-in: TBUILDER_DESKTOP=1 (needs tableau.exe)")
class DesktopResaveTest(unittest.TestCase):
    """Real Desktop 2025.1 (~20 s a book + ~12 s a sheet): a generated book re-saves clean, the palette mutant loses
    its maps."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.book = build_file(ROOT / "specs" / "registry.json", cls.dir / "registry.twbx")

    def test_generated_book_is_clean(self):
        r = rs.resave(self.book, self.dir / "out")
        self.assertTrue(r.clean, r.text())
        self.assertEqual(len(r.sheets), len(rs.windows_of(rs.read_twb(self.book))[0]) - 1)

    def test_palette_without_column_instance_is_dropped(self):
        book = build_file(ROOT / "specs" / "cards.json", self.dir / "cards.twbx")
        fields = make_palette_mutant(book, self.dir / "cards_palette_mutant.twbx")
        r = rs.resave(self.dir / "cards_palette_mutant.twbx", self.dir / "out", sheets=False)
        self.assertEqual(r.status, dc.OK, r.text())
        gone = {e.get("field") for i in r.report.left if i.kind == rs.DROPPED for e in i.el.iter("encoding")}
        self.assertEqual(gone, set(fields), r.text())


if __name__ == "__main__":
    unittest.main()
