"""Registry width labs (decisions/064): what Desktop 2025.1 draws when a registry column, its title or a row header
is narrower than its text.

  python tests/fixtures/registry_widths/build_lab.py headers|labels|natural|natural2|fine <out_dir>

Writes <mode>.json / <mode>_arial.json next to this file and builds <out_dir>/<mode>.twbx (Tableau Book, the
default font) and <out_dir>/<mode>_arial.twbx (theme 'cards' with theme_font Arial). Data lab.csv, format number:
V: Central 7 777, East 66 666, South 501 240, West -1 234 567; X: 1, 22, 333, 4 444; Y: 7, 88, 9 999, 501 240;
Z, 2 decimals: 1,50 .. -1 234 567 890,12; W in the automatic format: 0.179293, 12.34567, 828.0712, 501239.8908. The widths are forced here, for the lab only
(the builder's width rules are bypassed), and each sheet still fills its zone exactly as a generated registry does.

headers: sheet <P> (T30 .. T85 text, B50 .. B80 bar): the row header (Region) and the tested column 'Revenue' are P
  px wide, a filler column 'All' first takes the rest of the cell. Shows the '..' of the row headers (9pt) and of the
  column titles (bold 9pt text zones).
labels: one column 'Revenue' P px wide (T40 .. T84 text, B60 .. B90 bar), the row header takes the rest of the cell;
  A120: the automatic-format column W.
natural: the cell is cut so that P px are left beside the row header for one column of field V / X / Y
  (natural: V66 .. V126, X66 .. X126; natural2: Y66 .. Y126, BV: a bar column), its bars drawn grey (#dddddd, not
  white) to see them. S1-S3 (last row): two and three columns of different label widths in a wide cell, the
  builder's own equal widths.
fine: F96 .. F102 (V, one column), L120 .. L150 (Z: '-1 234 567 890,12', a label longer than the narrowest pane),
  BV98 .. BV106 (bar), D96 / D100 / D104 (two columns, 2 x P beside the row header), S4 (the long Z
  and the short X side by side: equal panes or not); bars grey.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from tbuilder import build as build_mod, design, gate, registry, spacing  # noqa: E402

NATURAL_P = range(66, 132, 6)
LABS = {
    "headers": [f"T{p}" for p in range(30, 90, 5)] + [f"B{p}" for p in (50, 60, 70, 80)],
    "labels": [f"T{p}" for p in range(40, 88, 4)] + [f"B{p}" for p in (60, 70, 80, 90)] + ["A120"],
    "natural": [f"{f}{p}" for f in "VX" for p in NATURAL_P] + ["S1", "S2"],
    "natural2": [f"Y{p}" for p in NATURAL_P] + [f"BV{p}" for p in (96, 108, 120, 126)] + ["S3"],
    "fine": [f"F{p}" for p in range(96, 103)] + [f"L{p}" for p in range(120, 155, 5)]
    + [f"BV{p}" for p in range(98, 108, 2)] + ["D96", "D100", "D104", "S4"],
}
S_COLUMNS = {"S1": "XV", "S2": "VX", "S3": "XVX", "S4": "ZX"}


def column(field, style="text", label="Revenue"):
    fmt = {"W": {}, "Z": {"format": {"type": "number", "decimals": 2}}}.get(field, {"format": "number"})
    return {"measure": {"field": field, **fmt}, "style": style, "label": label}


def columns(mode, name):
    if mode == "headers":
        return [column("V", label="All"), column("V", "bar" if name[0] == "B" else "text")]
    if mode == "labels":
        return [column("W" if name[0] == "A" else "V", "bar" if name[0] == "B" else "text")]
    if mode == "fine" and name not in S_COLUMNS:
        if name[0] == "D":
            return [column("V", label="V0"), column("X", label="X1")]
        return {"F": [column("V")], "L": [column("Z")], "B": [column("V", "bar")]}[name[0]]
    if name in S_COLUMNS:
        return [column(f, label=f"{f}{i}") for i, f in enumerate(S_COLUMNS[name])]
    return [column(name[1], "bar")] if name.startswith("BV") else [column(name[0])]


def spec(mode, theme=False):
    names = LABS[mode]
    sheets = [{"name": n, "type": "registry", "rows": ["Region"], "columns": columns(mode, n)} for n in names]
    per = 4 if mode in ("headers", "labels") else 6
    last = [n for n in names if n in S_COLUMNS or (mode == "fine" and n[0] == "D")]
    cells = [n for n in names if n not in last]
    grid = [cells[i:i + per] for i in range(0, len(cells), per)]
    grid += [[n for n in last if n[0] == "D"], ["S4"]] if mode == "fine" else [last] if last else []
    dash = {"name": "Lab", "title": f"Registry {mode} lab" + (" (Arial)" if theme else ""), "width": 1366,
            "height": {"headers": 900, "labels": 1100, "natural": 1000, "natural2": 1000, "fine": 900}[mode], "grid": grid}
    if theme:
        dash.update(theme="cards", theme_font="Arial")
    return {"$schema": "../../../tbuilder/spec.schema.json", "version": 1,
            "datasource": {"type": "csv", "path": "lab.csv"}, "sheets": sheets, "dashboard": dash}


def main(mode, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cur = {}
    original_cell = build_mod.Builder._registry_cell
    original_widths = registry.widths

    def cell(self, basic, s, box, size, head=False):
        m = spacing.margins(box, box, self.block_headers, edge=self._edge())
        cur["content"] = box[2] * size[0] // 100000 - m["left"] - m["right"]
        cur["name"] = s["name"]
        cur["p"] = int("".join(c for c in s["name"] if c.isdigit()))
        return original_cell(self, basic, s, box, size, head)

    def header(chars):
        if mode == "headers":
            return cur["p"]
        if cur["name"] in S_COLUMNS:
            return 100
        return cur["content"] - cur["p"] * (2 if mode == "fine" and cur["name"][0] == "D" else 1)

    def widths(cols, px):
        if mode == "headers":
            return [px - cur["p"], cur["p"]]
        return original_widths(cols, px) if cur["name"] in S_COLUMNS else [cur["p"]] * len(cols)

    build_mod.Builder._registry_cell = cell
    registry.row_header_px = lambda b, d, s=None: header(None)
    registry.widths = widths
    registry.check_widths = lambda *a: None  # the lab draws what the builder and the gate refuse (decisions/064)
    gate.CHECKS.remove(gate.check_registry_widths)
    if mode != "headers" and mode != "labels":
        design.COLOR["cell_text"] = "#dddddd"  # the text column's bar, white in a registry
    for name, theme in ((mode, False), (f"{mode}_arial", True)):
        sp = spec(mode, theme)
        (HERE / f"{name}.json").write_text(json.dumps(sp, indent=1), encoding="utf-8")
        build_mod.build(copy.deepcopy(sp), out / f"{name}.twbx", base_dir=str(HERE))
        print(out / f"{name}.twbx")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
