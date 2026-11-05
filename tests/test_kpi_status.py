"""KPI status dot by thresholds and its legend line (decisions/062): a Circle colored by a status calc right of the
card text, the statuses named in a block or dashboard header."""
import copy
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import gate, kpi2
from tbuilder import spec as spec_mod
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from tbuilder.design_lint import lint
from tbuilder.expected import compute
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS, canon, normalize, read_twbx

SPEC = json.loads((SPECS / "kpi_status.json").read_text(encoding="utf-8"))
DATA = SPECS / SPEC["datasource"]["path"]
GOLDEN = ROOT / "golden" / "golden_kpi_status_2025_1.twbx"


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def measure(spec, name, label):
    return next(m for m in sheet(spec, name)["measures"] if m.get("label", m["field"]) == label)


def built(spec=SPEC, name="kpi_status_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def calc(root, caption):
    return next(c for c in root.find("datasources").iter("column") if c.get("caption") == caption)


def palette(root, caption):
    col = calc(root, caption).get("name")[1:-1]
    enc = next(e for e in root.iter("encoding") if e.get("field") == f"[usr:{col}:nk]")
    return {m.findtext("bucket"): m.get("to") for m in enc.findall("map")}


def zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name and not z.get("type-v2"))


def drawn(z, width=1250):
    """px a zone draws in: its width without its left and right margins."""
    f = {x.get("attr"): int(x.get("value")) for x in z.iter("format") if x.get("attr", "").startswith("margin")}
    return round(int(z.get("w")) * width / 100000) - f.get("margin-left", f["margin"]) - f.get("margin-right",
                                                                                                 f["margin"])


def legend_runs(text_zone):
    """[(glyph color, label)] of the legend line at the end of a header text zone."""
    runs = text_zone.findall("formatted-text/run")
    return [(r.get("fontcolor"), n.text.strip()) for r, n in zip(runs, runs[1:]) if r.text == kpi2.STATUS_GLYPH]


class Numbers(unittest.TestCase):
    def test_statuses(self):
        """pandas-free: expected.compute over sales_2y.csv (make_expected.kpi_status computes them with pandas)."""
        got = compute(SPEC, DATA)
        self.assertEqual({k: v["status"] for k, v in got["Monthly"].items()},
                         {"Sales": "On track", "Profit": "Off track", "Units": "At risk"})
        self.assertEqual({k: v["status"] for k, v in got["Yearly"].items()}, {"Sales": "Healthy", "Profit": "Warning"})
        self.assertAlmostEqual(got["Monthly"]["Sales"]["current"], 15462.12)  # >= 15000
        self.assertAlmostEqual(got["Monthly"]["Units"]["delta"], 0.0196, 4)  # good down: 0 < 2 % <= 5 %
        self.assertAlmostEqual(got["Yearly"]["Profit"]["current"], 825.38)  # 500 <= 825 < 1000

    def test_boundaries(self):
        """At a threshold the better status (>= / <=), as the calc; a missing value has no status."""
        s = {"name": "K", "type": "kpi", "style": "cards"}
        m = {"field": "Sales", "status": {"on": "value", "thresholds": [10, 20]}}
        self.assertEqual(kpi2.status_formula(s, m),
                         'IF [K · Sales · Current] >= 20 THEN "On track" ELSEIF [K · Sales · Current] >= 10 THEN '
                         '"At risk" ELSEIF [K · Sales · Current] < 10 THEN "Off track" END')
        down = {"field": "Days", "good": "down", "status": {"on": "change", "thresholds": [-0.05, 0.1]}}
        self.assertEqual(kpi2.status_formula(s, down),
                         'IF [K · Days · Change] <= -0.05 THEN "On track" ELSEIF [K · Days · Change] <= 0.1 THEN '
                         '"At risk" ELSEIF [K · Days · Change] > 0.1 THEN "Off track" END')
        one = {"field": "Sales", "status": {"on": "change", "thresholds": [0]}}
        self.assertEqual(kpi2.status_formula({**s, "status_labels": ["Up", "Flat", "Down"]}, one),
                         'IF [K · Sales · Change] >= 0 THEN "Up" ELSEIF [K · Sales · Change] < 0 THEN "Down" END')


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_dot_sheet(self):
        t = ws(self.root, "Monthly · Sales · Status").find("table")
        self.assertFalse(t.findtext("rows") or t.findtext("cols"))
        pane = t.find("panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Circle")
        self.assertEqual(pane.find("mark-sizing").get("mark-sizing-setting"), "marks-scaling-off")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["color"])
        self.assertTrue(pane.find("encodings/color").get("column").endswith(":nk]"))
        self.assertEqual(pane.find("customized-tooltip/formatted-text").findall("run"), [])
        self.assertEqual(pane.find("style/style-rule[@element='mark']/format").attrib,
                         {"attr": "size", "value": kpi2.STATUS_SIZE})
        self.assertEqual([c.tag for c in pane], ["view", "mark", "mark-sizing", "encodings", "customized-tooltip",
                                                 "style"])

    def test_calc(self):
        c = calc(self.root, "Monthly · Units · Status")
        self.assertEqual((c.get("datatype"), c.get("role")), ("string", "measure"))
        change = calc(self.root, "Monthly · Units · Change").get("name")
        self.assertEqual(c.find("calculation").get("formula"),
                         f'IF {change} <= 0 THEN "On track" ELSEIF {change} <= 0.05 THEN "At risk" ELSEIF {change} > '
                         f'0.05 THEN "Off track" END')

    def test_palettes(self):
        self.assertEqual(palette(self.root, "Monthly · Sales · Status"),
                         {'"On track"': COLOR["good"], '"At risk"': COLOR["warn"], '"Off track"': COLOR["bad"]})
        self.assertEqual(palette(self.root, "Yearly · Sales · Status"),  # one threshold: two statuses
                         {'"Healthy"': COLOR["good"], '"Critical"': COLOR["bad"]})
        self.assertEqual(palette(self.root, "Yearly · Profit · Status"),
                         {'"Healthy"': COLOR["good"], '"Warning"': COLOR["warn"], '"Critical"': COLOR["bad"]})

    def test_dot_left_of_the_text_level_with_the_number(self):
        """A row of cards and stacked cards: the dot's zone left of the text, its top cut so its middle is the
        value line's (Desktop centers both), STATUS_PX inside its margins."""
        for card in ("Monthly · Sales", "Yearly · Profit"):
            with self.subTest(card):
                text, dot = zone(self.root, card), zone(self.root, f"{card} · Status")
                self.assertEqual(int(dot.get("x")) + int(dot.get("w")), int(text.get("x")))
                self.assertEqual(int(dot.get("y")) + int(dot.get("h")), int(text.get("y")) + int(text.get("h")))
                self.assertGreater(int(dot.get("y")), int(text.get("y")))
                self.assertLessEqual(abs(drawn(dot) - 16), 1)

    def test_offset(self):
        """period 9pt, name 11pt, value 24pt, change 10pt (card theme): the value line's middle 11px under the text's."""
        self.assertAlmostEqual(kpi2.dot_offset_px([(9, 1), (11, 1), (24, 1), (10, 1)]), 11.3, 0)

    def test_stacked_text_keeps_its_width(self):
        plain = built(mutate(lambda s: [m.pop("status") for m in sheet(s, "Yearly")["measures"]]
                             and [sheet(s, "Yearly").pop(k) for k in ("status_labels", "status_legend")]),
                      "kpi_status_plain")
        self.assertLessEqual(abs(drawn(zone(self.root, "Yearly · Sales")) - drawn(zone(plain, "Yearly · Sales"))), 1)

    def test_legend_lines(self):
        texts = [z for z in self.root.iter("zone") if z.get("type-v2") == "text"]
        block = next(z for z in texts if "month" in "".join(r.text or "" for r in z.iter("run")))
        self.assertEqual(legend_runs(block), [(COLOR["good"], "On track"), (COLOR["warn"], "At risk"),
                                              (COLOR["bad"], "Off track")])
        head = next(z for z in texts if "Sample data" in "".join(r.text or "" for r in z.iter("run")))
        self.assertEqual(legend_runs(head), [(COLOR["good"], "Healthy"), (COLOR["warn"], "Warning"),
                                             (COLOR["bad"], "Critical")])
        yearly = next(z for z in texts if "last year" in "".join(r.text or "" for r in z.iter("run")))
        self.assertEqual(legend_runs(yearly), [])  # its legend is in the dashboard header

    def test_no_color_legend_card(self):
        self.assertEqual([z for z in self.root.iter("zone") if z.get("type-v2") == "color"], [])


class Options(unittest.TestCase):
    def test_refused(self):
        cases = [
            (lambda s: measure(s, "Monthly", "Sales")["status"].update(thresholds=[15000, 13000]), "not ascending"),
            (lambda s: measure(s, "Monthly", "Sales")["status"].update(thresholds=[1, 1]), "not ascending"),
            (lambda s: sheet(s, "Monthly").pop("title"), "give the sheet a title"),
            (lambda s: s["dashboard"].pop("title") and s["dashboard"].pop("subtitle"), "give the dashboard a title"),
            (lambda s: [m.pop("status") for m in sheet(s, "Yearly")["measures"]], "give a measure a 'status'"),
            (lambda s: s["sheets"].append({"name": "Plain", "type": "kpi", "measures": [
                {"field": "Sales", "status": {"on": "value", "thresholds": [1]}}]}), "applies to KPI cards"),
        ]
        for fn, text in cases:
            with self.subTest(text):
                with self.assertRaisesRegex(ValueError, text):
                    built(mutate(fn), "kpi_status_refused")

    def test_schema(self):
        bad = [lambda s: measure(s, "Monthly", "Sales")["status"].update(thresholds=[1, 2, 3]),
               lambda s: measure(s, "Monthly", "Sales")["status"].update(on="target"),
               lambda s: sheet(s, "Yearly").update(status_labels=["A", "B"]),
               lambda s: sheet(s, "Yearly").update(status_legend="side")]
        for i, fn in enumerate(bad):
            with self.subTest(i):
                with self.assertRaises(Exception):
                    spec_mod.validate(mutate(fn))
        spec_mod.validate(SPEC)


class Lint(unittest.TestCase):
    def k4(self, spec):
        return [f for f in lint(spec, SPECS) if f.rule == "K4"]

    def test_clean(self):
        self.assertEqual(self.k4(SPEC), [])

    def test_no_legend(self):
        got = self.k4(mutate(lambda s: sheet(s, "Yearly").update(status_legend="none")))
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0].level, "error")
        self.assertIn("Healthy", got[0].text)

    def test_legend_of_another_block(self):
        """'none' when the other block's legend names the same statuses."""
        def fn(s):
            sheet(s, "Yearly").update(status_legend="none")
            sheet(s, "Yearly").pop("status_labels")
        self.assertEqual(self.k4(mutate(fn)), [])


class GateCatchesStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "kpi_status.json", OUT / "kpi_status_gate.twbx")

    def assertCaught(self, mutation, text):
        issues = gate.run(repack(mutation, source=self.src))
        hits = [i for i in issues if i.check == "kpi" and text in str(i)]
        self.assertTrue(hits, f"expected [kpi] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def inst(r, name="Monthly · Sales · Status"):
        t = next(w for w in r.iter("worksheet") if w.get("name") == name).find("table")
        return t.find("panes/pane/encodings/color").get("column").split("].", 1)[1]

    @staticmethod
    def ds_palette(r, inst):
        return next(e for e in r.find("datasources").iter("encoding") if e.get("field") == inst)

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_without_palette(self):
        def m(r):
            e = self.ds_palette(r, self.inst(r))
            e.getparent().remove(e)
        self.assertCaught(m, "has no palette map")

    def test_without_column_instance(self):
        def m(r):
            inst = self.inst(r)
            ci = next(c for c in r.find("datasources").iter("column-instance") if c.get("name") == inst)
            ci.getparent().remove(ci)
        self.assertCaught(m, "no column-instance")

    def test_palette_without_a_status(self):
        def m(r):
            e = self.ds_palette(r, self.inst(r))
            e.remove(next(x for x in e.findall("map") if x.findtext("bucket") == '"At risk"'))
        self.assertCaught(m, "no palette color for status ['At risk']")

    def test_thresholds_out_of_order(self):
        def m(r):
            col = self.inst(r).split(":")[1]
            c = next(c for c in r.find("datasources").iter("column") if c.get("name") == f"[{col}]")
            f = c.find("calculation")
            f.set("formula", f.get("formula").replace(">= 15000", ">= 12000"))
        self.assertCaught(m, "are not descending")


class OptIn(unittest.TestCase):
    """Without 'status' nothing changes: no trace of the dot in the other specs' books. The byte-for-byte check against
    the tree before decisions/062 runs with TB_STATUS_BASE=<commit> (git archive of that commit, ids seeded)."""
    SPECS_OLD = sorted(SPECS.glob("kpi_v2*.json")) + sorted(
        p for p in (SPECS / f"{g.name.split('_2025_1')[0].removeprefix('golden_') or 'golden'}.json"
                    for g in (ROOT / "golden").glob("golden*_2025_1.twbx")) if p.is_file() and p.stem != "kpi_status")

    def test_no_trace(self):
        for p in self.SPECS_OLD:
            with self.subTest(p.stem):
                twbx = build_file(p, OUT / f"optin_{p.stem}.twbx")
                with zipfile.ZipFile(twbx) as z:
                    text = z.read(next(n for n in z.namelist() if n.endswith(".twb"))).decode("utf-8")
                self.assertNotIn("· Status", text)
                if "history_points_legend" not in p.read_text(encoding="utf-8"):  # the same dot names points (088)
                    self.assertNotIn(kpi2.STATUS_GLYPH, text)
                self.assertNotIn(COLOR["warn"], text)

    @unittest.skipUnless(os.environ.get("TB_STATUS_BASE"), "set TB_STATUS_BASE=<commit before decisions/062>")
    def test_same_bytes_as_before(self):
        base = Path(tempfile.mkdtemp())
        tar = subprocess.run(["git", "archive", os.environ["TB_STATUS_BASE"]], cwd=ROOT, capture_output=True,
                             check=True).stdout
        with tarfile.open(fileobj=__import__("io").BytesIO(tar)) as t:
            t.extractall(base, filter="data")
        script = (
            "import random, sys, uuid, zipfile; from pathlib import Path\n"
            "root, out = Path(sys.argv[1]), Path(sys.argv[2]); sys.path.insert(0, str(root))\n"
            "from tbuilder.build import build_file\n"
            "for p in sys.argv[3:]:\n"
            "    rng = random.Random(p); random.seed(p)\n"
            "    uuid.uuid4 = lambda: uuid.UUID(int=rng.getrandbits(128), version=4)\n"
            "    b = build_file(root / 'specs' / p, out / (p + '.twbx'))\n"
            "    with zipfile.ZipFile(b) as z:\n"
            "        n = next(x for x in z.namelist() if x.endswith('.twb'))\n"
            "        (out / (p + '.twb')).write_bytes(z.read(n))\n")
        names = [p.name for p in self.SPECS_OLD]
        outs = []
        for tree in (base, ROOT):
            out = Path(tempfile.mkdtemp())
            subprocess.run([sys.executable, "-c", script, str(tree), str(out), *names], check=True,
                           env={**os.environ, "PYTHONUTF8": "1"})
            outs.append(out)
        for n in names:
            with self.subTest(n):
                self.assertEqual((outs[0] / f"{n}.twb").read_bytes(), (outs[1] / f"{n}.twb").read_bytes())


@unittest.skipUnless(GOLDEN.is_file(), "golden_kpi_status not snapped yet")
class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """The workbook Desktop 2025.1 re-saved (decisions/054) = the generator's output."""
        import difflib
        out = build_file(SPECS / "kpi_status.json", OUT / "roundtrip_kpi_status.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(GOLDEN)
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))


if __name__ == "__main__":
    unittest.main()
