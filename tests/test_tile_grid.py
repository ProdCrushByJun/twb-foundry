"""Tile grid (decisions/154): a tile map from the data's row / column (reference), a wall by INDEX() % N in blocks by a
group (as in the reference); the gate's checks of the places."""
import csv
import json
import unittest
import zipfile
from collections import Counter

from lxml import etree

from tbuilder import expected, gate, spec as spec_mod
from tbuilder.build import build
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "tile_grid.json"
CSV = ROOT / "data" / "sample" / "sales_states.csv"


def spec():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    s["datasource"]["path"] = str((SPEC.parent / s["datasource"]["path"]).resolve().relative_to(ROOT))
    return s


def rows():
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def twb(path):
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def calc(root, caption):
    return next(c for c in root.iter("column") if c.get("caption") == caption)


def sheet(name, **kw):
    s = spec()
    x = next(x for x in s["sheets"] if x["name"] == name)
    x.update(kw)
    for k in [k for k, v in kw.items() if v is None]:
        x.pop(k)
    return s


class TileGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build(spec(), OUT / "tile_grid.twbx", base_dir=ROOT)  # passes the gate
        cls.root = twb(cls.path)
        cls.exp = expected.compute(spec(), CSV)
        cls.sales = Counter()
        for r in rows():
            cls.sales[r["State"]] += float(r["Sales"])

    def test_schema(self):
        spec_mod.validate(spec())
        for key in ("dimension", "measure", "layout"):
            bad = spec()
            bad["sheets"][0].pop(key)
            with self.assertRaises(ValueError):
                spec_mod.validate(bad)

    def test_tile_map(self):
        """Square tiles on bins of size 1 of the row / column columns, headers hidden, the code over the value."""
        w = ws(self.root, "State Tiles")
        self.assertEqual({m.get("class") for m in w.iter("mark")}, {"Square"})
        self.assertTrue(w.findtext(".//rows").endswith("[none:Tile Row (bin):ok]"))
        self.assertTrue(w.findtext(".//cols").endswith("[none:Tile Col (bin):ok]"))
        for name in ("Tile Row (bin)", "Tile Col (bin)"):
            c = next(c for c in self.root.iter("column") if c.get("name") == f"[{name}]")
            self.assertEqual((c.find("calculation").get("class"), c.find("calculation").get("size")), ("bin", "1"))
        hidden = {f.get("field").split("].", 1)[1] for f in w.iterfind(".//style-rule[@element='label']/format")}
        self.assertEqual(hidden, {"[none:Tile Row (bin):ok]", "[none:Tile Col (bin):ok]"})
        label = "".join(r.text for r in w.iterfind(".//customized-label//run"))
        self.assertIn("[none:Code:nk]>Æ\n<", label)
        self.assertEqual(w.find(".//encodings/color").get("column").split("].", 1)[1], "[sum:Sales:qk]")
        stroke = {f.get("attr"): f.get("value") for f in w.iterfind(".//pane/style/style-rule/format")}
        self.assertEqual((stroke["has-stroke"], stroke["mark-labels-cull"]), ("true", "false"))

    def test_tile_map_expected(self):
        """51 tiles at their CSV places, the numbers = the CSV's sums."""
        tiles = self.exp["State Tiles · Tiles"]
        self.assertEqual(len(tiles), 51)
        self.assertEqual(tiles["California"], {"row": 5, "col": 1})
        self.assertEqual(tiles["Maine"], {"row": 1, "col": 11})
        self.assertEqual(len({(t["row"], t["col"]) for t in tiles.values()}), 51)
        for state, v in self.exp["State Tiles"].items():
            self.assertAlmostEqual(v, self.sales[state], places=2)

    def test_wall(self):
        """COL / ROW by INDEX() along the state, sorted by sales DESC, (Region / COL) on Columns."""
        w = ws(self.root, "Region Wall")
        col, row = calc(self.root, "Region Wall · Column"), calc(self.root, "Region Wall · Row")
        self.assertEqual(col.find("calculation").get("formula"), "(INDEX() - 1) - 3 * INT((INDEX() - 1) / 3)")
        self.assertEqual(row.find("calculation").get("formula"), "INT((INDEX() - 1) / 3)")
        cs = w.find(".//computed-sort")
        self.assertEqual((cs.get("column").split("].", 1)[1], cs.get("direction"), cs.get("using").split("].", 1)[1]),
                         ("[none:State:nk]", "DESC", "[sum:Sales:qk]"))
        for ci in w.iterfind(".//column-instance"):
            if ci.get("column") in (col.get("name"), row.get("name")):
                self.assertEqual(ci.get("name")[-4:], ":ok]")
                walk = [o.get("field").split("].", 1)[1] for o in ci.find("table-calc").iter("order")]
                self.assertEqual(walk, ["[none:State:nk]", "[none:Code:nk]"])  # the code on Text: walked too
        self.assertRegex(w.findtext(".//cols"), r"^\(\[.+\]\.\[none:Region:nk\] / \[.+\]\.\[usr:Calculation_\d+:ok\]\)$")
        self.assertIsNotNone(self.root.find("document-format-change-manifest/SortTagCleanup"))

    def test_wall_expected(self):
        """In each region the states by sales descending, three to a row."""
        tiles = self.exp["Region Wall · Tiles"]
        self.assertEqual(Counter(t["group"] for t in tiles.values()),
                         {"South": 17, "Midwest": 12, "West": 13, "Northeast": 9})
        region = {r["State"]: r["Region"] for r in rows()}
        west = sorted((s for s in self.sales if region[s] == "West"), key=lambda s: -self.sales[s])
        self.assertEqual(tiles[west[0]], {"row": 1, "col": 1, "group": "West"})
        self.assertEqual(tiles[west[4]], {"row": 2, "col": 2, "group": "West"})
        self.assertEqual(tiles[west[-1]], {"row": 5, "col": 1, "group": "West"})  # 13th: row 5

    def test_label_fits_tile(self):
        """The map's 64px tiles keep code and value; the wall's 37px tiles the code alone ('$24.0K' drew '###')."""
        runs = {n: len(ws(self.root, n).findall(".//customized-label//run")) for n in ("State Tiles", "Region Wall")}
        self.assertEqual(runs, {"State Tiles": 3, "Region Wall": 1})
        s = spec()
        s["dashboard"]["grid"] = [["Region Wall"]]
        s["dashboard"]["width"] = 1300
        s["sheets"] = [x for x in s["sheets"] if x["name"] == "Region Wall"]
        wide = twb(build(s, OUT / "tile_grid_wide.twbx", base_dir=ROOT))
        self.assertEqual(len(ws(wide, "Region Wall").findall(".//customized-label//run")), 3)

    def test_refusals(self):
        bad = [sheet("State Tiles", layout={"row": "Tile Row"}),
               sheet("State Tiles", layout={"row": "Tile Row", "col": "Tile Col", "cols": 3}),
               sheet("State Tiles", group="Region"),
               sheet("State Tiles", layout={"row": "Tile Row", "col": "Code"}),
               sheet("State Tiles", dimension="Region")]  # a region at many places
        for s in bad:
            with self.subTest(sheet=s["sheets"][0]), self.assertRaises(ValueError):
                build(s, OUT / "tile_grid_bad.twbx", base_dir=ROOT)

    def test_shared_place_refused(self):
        """Two states on one tile: refused at build."""
        s = sheet("State Tiles", layout={"row": "Tile Row", "col": "Tile Row"})  # (5, 5): CA and MO's rows...
        with self.assertRaises(ValueError) as e:
            build(s, OUT / "tile_grid_bad.twbx", base_dir=ROOT)
        self.assertIn("share the place", str(e.exception))


class TileGridGate(unittest.TestCase):
    """Mutations of the built book the gate catches."""

    @classmethod
    def setUpClass(cls):
        cls.path = build(spec(), OUT / "tile_grid_gate.twbx", base_dir=ROOT)

    def caught(self, text, **kw):
        issues = [str(i) for i in gate.run(repack(source=self.path, **kw)) if i.check == "tilegrid"]
        self.assertTrue(any(text in i for i in issues), issues)

    def test_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_no_sort(self):
        def drop(root):
            cs = ws(root, "Region Wall").find(".//computed-sort")
            cs.getparent().remove(cs)
        self.caught("INDEX() walks the members alphabetically", mutate_xml=drop)

    def test_wrap_mismatch(self):
        def four(root):
            for c in root.iter("column"):
                if c.get("caption") == "Region Wall · Column":
                    c.find("calculation").set("formula", "(INDEX() - 1) - 4 * INT((INDEX() - 1) / 4)")
        self.caught("tiles overlap or leave holes", mutate_xml=four)

    @staticmethod
    def _drop_code(root, captions):
        """The wall's table calcs of these captions no longer walk the Code (only the State)."""
        w = ws(root, "Region Wall")
        for cap in captions:
            col = calc(root, cap).get("name")
            ci = next(ci for ci in w.iter("column-instance") if ci.get("column") == col)
            tc = ci.find("table-calc")
            code = next(o for o in tc.iter("order") if o.get("field").endswith("[none:Code:nk]"))
            tc.remove(code)

    def test_walks_differ(self):
        self.caught("the wall's row walks", mutate_xml=lambda r: self._drop_code(r, ["Region Wall · Column"]))

    def test_label_not_walked(self):
        """The code on the marks but not in the INDEX() walk: every code a wall of its own (snapshot, 154)."""
        self.caught("each of its members starts the wall again",
                    mutate_xml=lambda r: self._drop_code(r, ["Region Wall · Column", "Region Wall · Row"]))

    def test_bin_size(self):
        def two(root):
            for c in root.iter("column"):
                if c.get("name") == "[Tile Row (bin)]":
                    c.find("calculation").set("size", "2")
        self.caught("needs size 1", mutate_xml=two)

    def test_shared_place_in_data(self):
        with zipfile.ZipFile(self.path) as z:
            name = next(n for n in z.namelist() if n.endswith("sales_states.csv"))
            text = z.read(name).decode("utf-8")
        lines = text.splitlines()
        i = next(i for i, x in enumerate(lines) if ",Texas,TX," in x)
        lines[i] = lines[i].replace(",8,4,", ",5,1,")  # Texas on California's tile
        self.caught("share the tile at row 5, column 1",
                    replace={name: ("\n".join(lines) + "\n").encode("utf-8")})


if __name__ == "__main__":
    unittest.main()
