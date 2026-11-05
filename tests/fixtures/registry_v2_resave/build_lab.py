"""Lab of decisions/065: variants of the registry_v2 book (track palette, tick base) for Desktop 2025.1 re-save.

usage: python build_lab.py <generated golden_registry_v2.twbx> <out dir>
Writes lab_<variant>.twbx; each is opened and re-saved by `python -m tbuilder check-desktop --resave`.

Track (sheet Regions): the share and rest calcs on Measure Values are computed along Region (Specific Dimensions)
on the sheet; the datasource declares their instances for the Measure Names palette.
  b   - datasource instances :qk carry the sheet's compute-using (ordering-field Region) and Region is declared in the
        datasource (the reference's form of a table-calc color flag, reflines.instance_table_calc);
  a   - the sheet and the palette use :qk:1, the datasource declares :qk:1 with the sheet's compute-using (no :qk).
Tick (sheet Categories): the per-cell line's value column (Sales 2024) is on no shelf.
  lod - the base on Detail of the tick's pane;
  tip - the base on Tooltip of the tick's pane.
With --after (input built by the generator after 065):
  nolod - the line in the default pane as Desktop moves it, the base on no shelf.
"""
import re
import sys
import zipfile
from pathlib import Path

SHARE = "Regions · Of total · Share"
REST = "Regions · Of total · Track"
BASE = "Sales 2024"
TICK = "Sales vs PY"


def calc_id(twb, caption):
    return re.search(rf'caption="{re.escape(caption)}"[^>]*name="\[(Calculation_\d+)\]"', twb).group(1)


def track_b(twb, ds, ids):
    region = f'<column datatype="string" name="[Region]" role="dimension" type="nominal" />'
    head, rest = twb.split("<worksheets>", 1)
    head = head.replace('<column caption="sales_2y.csv"', region + '\n      <column caption="sales_2y.csv"', 1)
    first = '<column-instance '
    inst = '<column-instance column="[Region]" derivation="None" name="[none:Region:nk]" pivot="key" type="nominal" />'
    head = head.replace(first, inst + "\n      " + first, 1)
    for i in ids:
        tag = (f'<column-instance column="[{i}]" derivation="User" name="[usr:{i}:qk]" pivot="key" '
               f'type="quantitative" />')
        assert tag in head, tag
        head = head.replace(tag, tag[:-3] + f'><table-calc ordering-field="[{ds}].[none:Region:nk]" '
                                            f'ordering-type="Field" /></column-instance>', 1)
    return head + "<worksheets>" + rest


def track_a(twb, ds, ids):
    twb = track_b(twb, ds, ids)
    for i in ids:  # every reference: datasource instance, palette buckets, sheet instance, filter, manual sort
        twb = twb.replace(f"[usr:{i}:qk]", f"[usr:{i}:qk:1]")
    return twb


def tick(twb, ds, base_id, tag):
    """The base on the tick pane's Detail (lod) or Tooltip."""
    m = re.search(r'(<reference-line [^>]*scope="per-cell"[^>]*/>)', twb)
    line = m.group(1)
    enc = f'<encodings><{tag} column="[{ds}].[usr:{base_id}:qk]" /></encodings>'
    return twb.replace(line, enc + "\n            " + line, 1)


def main(src, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        twb_name = next(n for n in names if n.endswith(".twb"))
        twb = z.read(twb_name).decode("utf-8")
        files = {n: z.read(n) for n in names if n != twb_name}
    ds = re.search(r'<datasource caption="[^"]*"[^>]*name="(federated\.[a-z0-9]+)"', twb).group(1)
    ids = [calc_id(twb, SHARE), calc_id(twb, REST)]
    base = calc_id(twb, BASE)
    if "--after" in sys.argv:  # the generator after 065 (track b, the line in the default pane, base on Detail)
        variants = {"nolod": re.sub(r'<encodings>\s*<lod column="[^"]*" />\s*</encodings>\s*', "", twb, count=1)}
    else:  # the generator before 065
        variants = {
            "b_lod": tick(track_b(twb, ds, ids), ds, base, "lod"),
            "a_tip": tick(track_a(twb, ds, ids), ds, base, "tooltip"),
        }
    for name, text in variants.items():
        p = out / f"lab_{name}.twbx"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"lab_{name}.twb", text.encode("utf-8"))
            for n, data in files.items():
                z.writestr(n, data)
        print(p)


if __name__ == "__main__":
    main(*sys.argv[1:3])
