"""Validation gate: inspects a finished .twbx independently of the builder.

It reads only the packaged file, so it also catches bugs in the builder itself.
Every check returns Issues; any Issue fails the gate.
"""
import csv
import io
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from . import barinbar, design, formats, insight
from .design import CARD_BORDER_PX, COLOR, NAV_UNDERLINE_PX, PIE_PX_PER_SIZE, REGISTRY_ROW_NESTED_PX, REGISTRY_ROW_PX, SPACE

VENDOR = Path(__file__).parent / "vendor" / "tableau-document-schemas"
XSD_DEFAULT = "2026_1/twb_2026.1.0.xsd"
USER_NS = "http://www.tableausoftware.com/xml/user"
REF = re.compile(r"\[(federated\.[a-z0-9]+)\]\.(\[[^\]]+\])")
GEO_LAT, GEO_LON, GEO_GEOMETRY = "[Latitude (generated)]", "[Longitude (generated)]", "[Geometry (generated)]"
# fields Tableau generates for a geographic role: on shelves without a declaration (decisions/046)
SPECIAL_INSTANCES = {"[:Measure Names]", "[Multiple Values]", GEO_LAT, GEO_LON, GEO_GEOMETRY}
FULL = 100000

# Stubs for the two namespaces the official XSD imports without a schemaLocation.
_USER_STUB = f"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{USER_NS}">
  <xs:attributeGroup name="UserAttributes-AG"><xs:anyAttribute namespace="##targetNamespace" processContents="skip"/></xs:attributeGroup>
</xs:schema>"""
_XML_STUB = """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://www.w3.org/XML/1998/namespace">
  <xs:attribute name="base" type="xs:anyURI"/>
</xs:schema>"""

# Strict-XSD findings that Tableau Desktop itself produces (golden_2025_1.twb fails the
# same way) and that do not affect opening. Matched exactly, nothing broader.
XSD_ALLOWLIST = [
    re.compile(r"^Element 'workbook': Missing child element\(s\)\. Expected is one of \("
               r"( ?(datagraph|thumbnails|external|referenced-extensions|explain-data),?)+ \)\.$"),
]


@dataclass
class Issue:
    check: str
    where: str
    message: str

    def __str__(self):
        return f"[{self.check}] {self.where}: {self.message}"


class GateError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("Gate failed:\n" + "\n".join(f"  - {i}" for i in issues))


# ---- package --------------------------------------------------------------------------
def check_package(names, root):
    issues = []
    twbs = [n for n in names if n.lower().endswith(".twb")]
    if len(twbs) != 1 or "/" in twbs[0]:
        issues.append(Issue("package", "zip", f"expected exactly one root-level .twb, got {twbs}"))
    for conn in root.iter("connection"):
        if conn.get("class") in ("textscan", "excel-direct", "hyper"):
            if conn.get("class") == "hyper":
                path = conn.get("dbname")
            elif conn.get("directory") is None:  # excel-direct: the packaged path is all in 'filename'
                path = conn.get("filename")
            else:
                path = f"{conn.get('directory')}/{conn.get('filename')}".lstrip("/")
            if path not in names:
                issues.append(Issue("package", conn.get("filename", "?"), f"data file '{path}' missing from package"))
    images = [z.get("param") for z in root.iter("zone") if z.get("type-v2") == "bitmap"]
    images += [e.text for e in root.iter("image-path")]  # a button drawn as a picture (ER, Admissions)
    for path in sorted(set(images)):
        if path not in names:
            issues.append(Issue("package", path, "dashboard image missing from package: Desktop shows an empty "
                                                 "frame"))
    return issues


def _column_letter(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


EXCEL_FILES = (".xlsx", ".xlsm", ".xls")
EXCEL_JOINS = ("inner", "left")  # join types checked in Desktop 2025.1 (decisions/050)
UNION_COLUMNS = ["Sheet", "Table Name"]  # Desktop's own columns of a union of sheets


def _excel_cells(name, data, sheet):
    """(sheet names, {(row, col): value} of the sheet's non-empty cells or None without that sheet) of a packaged
    Excel file: .xlsx/.xlsm through openpyxl, .xls through xlrd."""
    if name.lower().endswith(".xls"):
        import xlrd  # only an .xls source needs it
        book = xlrd.open_workbook(file_contents=data)
        if sheet not in book.sheet_names():
            return book.sheet_names(), None
        sh = book.sheet_by_name(sheet)
        return book.sheet_names(), {(r + 1, c + 1): sh.cell_value(r, c) for r in range(sh.nrows)
                                    for c in range(sh.ncols) if sh.cell_value(r, c) not in (None, "")}
    import openpyxl  # only an Excel source needs it
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            return wb.sheetnames, None
        return wb.sheetnames, {(r, c): v for r, row in enumerate(wb[sheet].iter_rows(values_only=True), 1)
                               for c, v in enumerate(row, 1) if v not in (None, "")}
    finally:
        wb.close()


def _excel_table(rel, name, data):
    """Issues of one relation reading a sheet: table '[<sheet>$]', the columns are the header row of the sheet's
    block of cells in order, gridOrigin is that block (from its header to the last non-empty row and column)."""
    sheet, where = rel.get("name"), f"relation '{rel.get('name')}'"
    issues = []
    if rel.get("table") != f"[{sheet}$]":
        issues.append(Issue("excel", where, f"table {rel.get('table')} is not the sheet [{sheet}$]"))
    sheets, cells = _excel_cells(name, data, sheet)
    if cells is None:
        return issues + [Issue("excel", where, f"no sheet '{sheet}' in the packaged file ({sheets})")]
    cols = rel.find("columns")
    names = [c.get("name") for c in cols.findall("column")]
    if not cells:
        return issues + [Issue("excel", where, "the sheet is empty")]
    top, left = min(r for r, _ in cells), min(c for _, c in cells)
    bottom, right = max(r for r, _ in cells), max(c for _, c in cells)
    header = [cells.get((top, c)) for c in range(left, right + 1)]
    if header != names:
        issues.append(Issue("excel", where, f"columns {names} are not the header row of the sheet {header}"))
    grid = f"{_column_letter(left)}{top}:{_column_letter(right)}{bottom}"
    if cols.get("gridOrigin") != f"{grid}:no:{grid}:0":
        issues.append(Issue("excel", where, f"gridOrigin {cols.get('gridOrigin')} does not cover the table {grid}"))
    return issues


def _relation_columns(rel):
    return [c.get("name") for c in rel.findall("columns/column")]


def _excel_union(rel):
    """A union of sheets (decisions/050): every sheet has the same columns, the union lists them, then Desktop's
    'Sheet' and 'Table Name'."""
    where, parts = f"union '{rel.get('name')}'", rel.findall("relation")
    if len(parts) < 2 or any(p.get("type") != "table" for p in parts):
        return [Issue("excel", where, "a union needs two or more sheets (table relations)")]
    first = _relation_columns(parts[0])
    issues = [Issue("excel", where, f"sheet '{p.get('name')}' has the columns {_relation_columns(p)}, "
                                    f"'{parts[0].get('name')}' {first}")
              for p in parts[1:] if sorted(_relation_columns(p)) != sorted(first)]
    if _relation_columns(rel) != first + UNION_COLUMNS:
        issues.append(Issue("excel", where, f"columns {_relation_columns(rel)} are not the sheets' columns and "
                                            f"{UNION_COLUMNS}"))
    return issues


def _excel_join(ds, rel):
    """A join of two sheets (decisions/050): a checked join type, the clause compares a column of each sheet, the
    field map points to the sheets' columns."""
    where, parts = "join", rel.findall("relation")
    if rel.get("join") not in EXCEL_JOINS:
        return [Issue("excel", where, f"join type {rel.get('join')!r} is not checked in Desktop ({EXCEL_JOINS})")]
    if len(parts) != 2 or any(p.get("type") != "table" for p in parts):
        return [Issue("excel", where, "a join of two sheets (table relations) is supported")]
    tables = {p.get("name"): set(_relation_columns(p)) for p in parts}
    ops = [e.get("op") for e in rel.findall("clause/expression/expression")]
    issues = []
    if rel.find("clause/expression") is None or rel.find("clause/expression").get("op") != "=" or len(ops) != 2:
        issues.append(Issue("excel", where, "the clause is not one equality of two columns"))
    seen = set()
    for op in ops:
        m = re.fullmatch(r"\[([^\]]+)\]\.\[([^\]]+)\]", op or "")
        if not m or m.group(1) not in tables or m.group(2) not in tables[m.group(1)]:
            issues.append(Issue("excel", where, f"clause operand {op} is not a column of a joined sheet"))
        else:
            seen.add(m.group(1))
    if len(seen) != 2 and not issues:
        issues.append(Issue("excel", where, f"the clause compares {ops}, not a column of each sheet"))
    maps = ds.findall("connection/cols/map")
    if not maps:
        issues.append(Issue("excel", where, "no field map (<cols>): Desktop cannot tell the sheets' columns apart"))
    for m in maps:
        t = re.fullmatch(r"\[([^\]]+)\]\.\[([^\]]+)\]", m.get("value") or "")
        if not t or t.group(1) not in tables or t.group(2) not in tables[t.group(1)]:
            issues.append(Issue("excel", where, f"field {m.get('key')} maps to {m.get('value')}, not a column of a "
                                                f"joined sheet"))
    return issues


def check_excel(root, files):
    """Each relation on an Excel connection reads a sheet of the packaged .xlsx/.xlsm/.xls: table '[<sheet>$]', the
    columns are the header row of the sheet's table in order, gridOrigin covers that table (decisions/025; a table
    from any cell, decisions/050). A union or a join of such sheets has the form Desktop 2025.1 saved (050)."""
    issues = []
    for ds in root.find("datasources"):
        conns = {nc.get("name"): nc.find("connection").get("filename")
                 for nc in ds.findall("connection/named-connections/named-connection")
                 if nc.find("connection") is not None and nc.find("connection").get("class") == "excel-direct"}
        if not conns:
            continue
        for rel in ds.iter("relation"):
            if rel.get("type") == "union":
                issues += _excel_union(rel)
            elif rel.get("type") == "join" and rel.getparent().tag == "connection":
                issues += _excel_join(ds, rel)
            if rel.get("connection") not in conns or conns[rel.get("connection")] not in files:
                continue  # a missing file is the package check's issue
            name = conns[rel.get("connection")]
            issues += _excel_table(rel, name, files[name])
    return issues


# ---- references -----------------------------------------------------------------------
def _source_columns(ds):
    """{'[Column]': datatype} of a datasource's table: the text file's relation columns, or for a table with no
    column list (a Hyper table, decisions/026) its column metadata-records."""
    cols = {f"[{c.get('name')}]": c.get("datatype") for c in ds.findall("connection/relation/columns/column")}
    if ds.find("connection/relation") is not None and ds.find("connection/relation/columns") is None:
        cols = {r.findtext("local-name"): r.findtext("local-type")
                for r in ds.findall("connection/metadata-records/metadata-record") if r.get("class") == "column"}
    return cols


def _datasource_columns(root):
    """{ds_name: set of '[Column]'} from each federated datasource's relation."""
    out = {}
    for ds in root.find("datasources"):
        cols = set(_source_columns(ds))
        cols |= {c.get("name") for c in ds.findall("column") if c.find("calculation") is not None}
        out[ds.get("name")] = cols
    return out


def _deps(scope, ds_cols, where):
    """Validate a datasource-dependencies block; return {ds: set(instance names)}."""
    issues, inst = [], {}
    for dep in scope.findall("datasource-dependencies"):
        ds = dep.get("datasource")
        if ds not in ds_cols:
            issues.append(Issue("refs", where, f"dependencies on unknown datasource {ds}"))
            continue
        declared = {c.get("name") for c in dep.findall("column")}
        for col in declared - ds_cols[ds]:
            issues.append(Issue("refs", where, f"column {col} not in datasource"))
        names = set()
        for ci in dep.findall("column-instance"):
            if ci.get("column") not in declared:
                issues.append(Issue("refs", where, f"instance {ci.get('name')} uses undeclared column {ci.get('column')}"))
            names.add(ci.get("name"))
        # a group is referenced as its column, with no instance (decisions/033)
        names |= {c.get("name") for c in dep.findall("column") if c.find("calculation[@class='categorical-bin']")
                  is not None}
        inst[ds] = names
    return issues, inst


PARAM_FIELD_ATTRS = ("source-field", "default-value-field")  # a column, not an instance: check_parameters (163)


def _refs_in(el):
    """All qualified [ds].[instance] references inside an element (attrs + text)."""
    found = []
    for node in el.iter():
        for v in [v for k, v in node.attrib.items() if k not in PARAM_FIELD_ATTRS] + [node.text or ""]:
            found += REF.findall(v)
    return found


def _resolve(refs, inst, where, check="refs"):
    issues = []
    for ds, name in refs:
        if name in SPECIAL_INSTANCES:
            continue
        if name not in inst.get(ds, set()):
            issues.append(Issue(check, where, f"reference {name} is not declared in this sheet's dependencies"))
    return issues


def check_references(root):
    issues = []
    ds_cols = _datasource_columns(root)
    sheet_inst = {}
    for ws in root.iter("worksheet"):
        where = f"worksheet '{ws.get('name')}'"
        view = ws.find("table/view")
        errs, inst = _deps(view, ds_cols, where)
        issues += errs + _resolve(_refs_in(ws.find("table")), inst, where)
        sheet_inst[ws.get("name")] = inst
    for sv in root.iter("shared-view"):
        where = f"shared-view '{sv.get('name')}'"
        errs, inst = _deps(sv, ds_cols, where)
        issues += errs + _resolve(_refs_in(sv), inst, where)
    for db in root.iter("dashboard"):
        where = f"dashboard '{db.get('name')}'"
        errs, _ = _deps(db, ds_cols, where)
        issues += errs
        for z in db.find("zones").iter("zone"):
            if z.get("type-v2") in ("color", "filter") and z.get("name") in sheet_inst:
                issues += _resolve(REF.findall(z.get("param", "")), sheet_inst[z.get("name")],
                                   f"{where} zone {z.get('id')}")
    for w in root.iter("window"):
        if w.get("class") == "worksheet" and w.get("name") in sheet_inst:
            for card in w.iter("card"):
                issues += _resolve(REF.findall(card.get("param", "")), sheet_inst[w.get("name")],
                                   f"window '{w.get('name')}' card {card.get('type')}")
    return issues


# ---- windows, names, ids --------------------------------------------------------------
def check_windows(root):
    issues = []
    sheets = [("worksheet", w.get("name")) for w in root.iter("worksheet")]
    dashes = [("dashboard", d.get("name")) for d in root.iter("dashboard")]
    objects = sheets + dashes
    for kind, name in objects:
        if objects.count((kind, name)) > 1:
            issues.append(Issue("names", name, f"duplicate {kind} name"))
    if {n for _, n in sheets} & {n for _, n in dashes}:
        issues.append(Issue("names", "workbook", "a dashboard shares its name with a worksheet"))
    windows = [(w.get("class"), w.get("name")) for w in root.find("windows")]
    for w in windows:
        if w not in objects:
            issues.append(Issue("windows", w[1], f"{w[0]} window without a matching {w[0]} (ghost tab)"))
        if windows.count(w) > 1:
            issues.append(Issue("windows", w[1], "duplicate window"))
    for o in objects:
        if o not in windows:
            issues.append(Issue("windows", o[1], f"{o[0]} has no window (hidden/unreachable)"))
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        if not (table.findtext("rows") or table.findtext("cols") or table.find("panes/pane/encodings") is not None):
            issues.append(Issue("content", ws.get("name"), "empty worksheet (nothing on rows, columns or marks)"))
    uuids = [s.get("uuid") for s in root.iter("simple-id")]
    for u in {u for u in uuids if uuids.count(u) > 1}:
        issues.append(Issue("ids", u, "duplicate simple-id uuid"))
    return issues


# ---- dashboard geometry ----------------------------------------------------------------
def _box(z):
    return tuple(int(z.get(k)) for k in ("x", "y", "w", "h"))


def check_dashboards(root):
    issues = []
    sheet_names = {w.get("name") for w in root.iter("worksheet")}
    dzv = _dzv_zones(root)
    for db in root.iter("dashboard"):
        where = f"dashboard '{db.get('name')}'"
        sid = db.find("simple-id")
        alternatives = dzv.get(sid.get("uuid") if sid is not None else None, set())  # one shows at a time (042)
        zones = db.find("zones")
        ids = [z.get("id") for z in zones.iter("zone")]
        for i in {i for i in ids if ids.count(i) > 1}:
            issues.append(Issue("layout", where, f"duplicate zone id {i}"))
        top = zones.findall("zone")
        if len(top) != 1 or _box(top[0]) != (0, 0, FULL, FULL):
            issues.append(Issue("layout", where, "root zone must be a single 0,0,100000,100000 container"))
        for z in zones.iter("zone"):
            zw = f"{where} zone {z.get('id')}"
            if "type-v2" not in z.attrib and z.get("name") not in sheet_names:
                issues.append(Issue("layout", zw, f"sheet zone points to unknown worksheet '{z.get('name')}'"))
            if z.get("type-v2") in ("color", "filter") and z.get("name") not in sheet_names:
                issues.append(Issue("layout", zw, f"{z.get('type-v2')} card bound to unknown worksheet '{z.get('name')}'"))
            x, y, w, h = _box(z)
            if w <= 0 or h <= 0:
                issues.append(Issue("layout", zw, "zero or negative size"))
            kids = z.findall("zone")
            for k in kids:
                kx, ky, kw, kh = _box(k)
                if kx < x or ky < y or kx + kw > x + w or ky + kh > y + h:
                    issues.append(Issue("layout", f"{where} zone {k.get('id')}", f"outside parent zone {z.get('id')}"))
            for i, a in enumerate(kids):
                for b in kids[i + 1:]:
                    if a.get("id") in alternatives and b.get("id") in alternatives:
                        continue  # views of a switch: dynamic zone visibility shows one of them
                    if "true" in (a.get("hidden-by-user"), b.get("hidden-by-user")) and \
                            any(_toggles(db, c) for c in (a, b)):
                        continue  # filter cards hidden at open behind a Show/Hide button (decisions/160)
                    ax, ay, aw, ah = _box(a)
                    bx, by, bw, bh = _box(b)
                    if _spark_over(a, b):
                        continue  # a separate KPI card's sparkline drawn on its text (decisions/178)
                    if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                        issues.append(Issue("layout", where, f"zones {a.get('id')} and {b.get('id')} overlap"))
    return issues


# ---- spacing -------------------------------------------------------------------------------
CONTAINERS = ("layout-basic", "layout-flow")
SIDES = ("top", "right", "bottom", "left")


def _style(z):
    return {f.get("attr"): f.get("value") for f in z.findall("zone-style/format")}


def _margins(st):
    """{side: px} of a zone style; None where neither margin-<side> nor margin is set."""
    values = {s: st.get(f"margin-{s}", st.get("margin")) for s in SIDES}
    return {s: None if v is None else int(v) for s, v in values.items()}


def _touching(a, b):
    """b sits right on top of a: b's bottom edge is a's top edge and they overlap horizontally."""
    ax, ay, aw, _ = _box(a)
    bx, by, bw, bh = _box(b)
    return by + bh == ay and bx < ax + aw and ax < bx + bw


def _is_card(z):
    """A card of the card theme (decisions/030): a container with a border, or with the card face and a padding
    and no border (card_border false, decisions/089)."""
    if z is None or z.get("type-v2") not in CONTAINERS:
        return False
    st = _style(z)
    return st.get("border-style", "none") != "none" or (st.get("background-color") == COLOR["card_bg"]
                                                         and "padding" in st)


def _on_card_edge(z, parent, side):
    """z's side lies on the edge of a card's content (the layout-basic inside a card): the card's padding is the
    distance there."""
    if parent.get("type-v2") != "layout-basic" or not _is_card(parent.getparent()) or \
            int(_style(parent.getparent()).get("padding", 0)) not in set(SPACE.values()):
        return False
    x, y, w, h = _box(z)
    px, py, pw, ph = _box(parent)
    return {"top": y == py, "right": x + w == px + pw, "bottom": y + h == py + ph, "left": x == px}[side]


def _spark_over(a, b):
    """A separate KPI card (decisions/178): the card's text zone '<sheet> · <measure>' and, after it, its sparkline
    '<sheet> · <measure> · History' inside the text's box, so Desktop draws the line on the text's right side."""
    ax, ay, aw, ah = _box(a)
    bx, by, bw, bh = _box(b)
    return (b.get("name") == f"{a.get('name')} · History" and ax <= bx and ay <= by
            and bx + bw <= ax + aw and by + bh <= ay + ah)


def _spark_seam(z, kids, side):
    """A registry and its line spark's sheet (decisions/153): one table split in two zones, margin 0 on the seam,
    the spark's name '<registry> · <column>' right of the registry's."""
    def edge(k, a):
        return int(k.get("x")) + (int(k.get("w")) if a == "right" else 0)
    name = z.get("name") or ""
    for k in kids:
        other = k.get("name") or ""
        if "type-v2" in k.attrib or "type-v2" in z.attrib or not other:
            continue
        if side == "right" and other.startswith(name + " · ") and edge(z, "right") == edge(k, "left"):
            return True
        if side == "left" and name.startswith(other + " · ") and edge(k, "right") == edge(z, "left"):
            return True
    return False


def check_spacing(root):
    """Nothing touches another object or the dashboard edge (the design rules): each side of every
    dashboard object has a margin from design.SPACE. Zero only where the references put it:
    - a registry's column title: a text zone with margin 0 right on top of its sheet;
    - the top of a zone right under a text or empty zone (a block header: its margin-bottom is the gap);
    - a side on the edge of a card's content: the card's padding keeps it off the border (decisions/030).
    Containers draw nothing and keep Desktop's default (no margin); one with a background needs a padding, and so
    does a text with its own background (decisions/070: inner = padding, painted by the zone's fill)."""
    tokens = set(SPACE.values())
    issues = []
    for db in root.iter("dashboard"):
        where = f"dashboard '{db.get('name')}'"
        roots = db.find("zones").findall("zone")
        for r in roots:
            m = _margins(_style(r))
            if any(v not in tokens for v in m.values()):
                issues.append(Issue("spacing", where, f"root zone margin {m} must be a design.SPACE token "
                                                      f"{sorted(tokens)} (dashboard edge)"))
        for parent in db.find("zones").iter("zone"):
            kids = parent.findall("zone")
            for z in kids:
                zw = f"{where} zone {z.get('id')} ({z.get('type-v2') or z.get('name')})"
                st = _style(z)
                pads = {k: int(v) for k, v in st.items() if k.startswith(("margin", "padding"))}
                if z.get("type-v2") in CONTAINERS:
                    bad = {k: v for k, v in pads.items() if v not in tokens | {0}}
                    if bad:
                        issues.append(Issue("spacing", zw, f"{bad} not a design.SPACE token {sorted(tokens)}"))
                    if "background-color" in st and int(st.get("padding", 0)) not in tokens:
                        issues.append(Issue("spacing", zw, "a container with a background needs a padding from "
                                                           "design.SPACE"))
                    continue
                m = _margins(st)
                for side, v in m.items():
                    if v is None:
                        issues.append(Issue("spacing", zw, f"no margin on the {side} (touches its neighbour)"))
                    elif v not in tokens | {0}:
                        issues.append(Issue("spacing", zw, f"margin-{side} {v} is not a design.SPACE token "
                                                           f"{sorted(tokens)}"))
                    elif v == 0:
                        column_title = z.get("type-v2") == "text" and set(m.values()) == {0} and any(
                            "type-v2" not in k.attrib and _touching(k, z) for k in kids)
                        under_header = side == "top" and any(  # also a nav tab's line under its button (040)
                            (k.get("type-v2") in ("text", "empty") or _goto(k) is not None
                             or (_margins(_style(k))["bottom"] or 0) > 0)  # an insight line keeps the gap (045)
                            and _touching(z, k) for k in kids)
                        if not (column_title or under_header or _on_card_edge(z, parent, side)
                                or _spark_seam(z, kids, side)):
                            issues.append(Issue("spacing", zw, f"margin-{side} 0: touches its neighbour (zero only "
                                                               f"for registry column titles, under a header and on "
                                                               f"a card's padding)"))
                bad = {k: v for k, v in pads.items() if k.startswith("padding") and v not in tokens | {0}}
                if bad:
                    issues.append(Issue("spacing", zw, f"{bad} not a design.SPACE token {sorted(tokens)}"))
                if z.get("type-v2") == "text" and "background-color" in st and \
                        not any(v in tokens for k, v in pads.items() if k.startswith("padding")):
                    # a band header or a filled column title: its fill is the zone, the padding keeps the text
                    # off the fill's edge, as in a container with a background (decisions/070)
                    issues.append(Issue("spacing", zw, "a text with its own background needs a padding from "
                                                       "design.SPACE"))
    return issues


# ---- dashboard shell (decisions/029) --------------------------------------------------------------
EXPORT = re.compile(r'^tabdoc:abstract-dashboard-button-export-wrapper dashboard-button-export-type="([a-z]+)" '
                    r'dashboarddoc-id="(\{[0-9A-F-]{36}\})"$')
EXPORT_TYPES = {"pdf", "powerpoint", "image"}


def check_buttons(root):
    """An export button exports its own dashboard: the action names an export type and the dashboard's
    simple-id (ER, Admissions); a button without an action does nothing when clicked."""
    issues = []
    for db in root.iter("dashboard"):
        own = db.find("simple-id")
        own = own.get("uuid") if own is not None else None
        for z in db.find("zones").iter("zone"):
            btn = z.find("button")
            if btn is None:
                continue
            where = f"dashboard '{db.get('name')}' zone {z.get('id')} button"
            export = btn.find("export-button-action")
            if export is None:
                if not btn.get("action") and btn.find("toggle-action") is None:
                    issues.append(Issue("buttons", where, "no action: the button does nothing"))
                continue
            m = EXPORT.match(export.text or "")
            if not m:
                issues.append(Issue("buttons", where, f"export action not in Desktop's form: {export.text!r}"))
                continue
            kind, target = m.groups()
            if kind not in EXPORT_TYPES or btn.get("button-click-action-metadata") != kind:
                issues.append(Issue("buttons", where, f"export type '{kind}' (metadata "
                                                      f"'{btn.get('button-click-action-metadata')}'): one of "
                                                      f"{sorted(EXPORT_TYPES)} in both"))
            if target != own:
                issues.append(Issue("buttons", where, f"exports dashboard {target}, not its own ({own}): no target"))
    return issues


# ---- navigation (decisions/040) -------------------------------------------------------------------------------
GOTO_ACTION = re.compile(r'^tabdoc:goto-sheet window-id="(\{[0-9A-F-]{36}\})"$')


def _goto(z):
    """The window uuid a goto button zone opens: '' for a goto action in another form, None for no goto button."""
    btn = z.find("button")
    if btn is None or not (btn.get("action") or "").startswith("tabdoc:goto-sheet"):
        return None
    m = GOTO_ACTION.match(btn.get("action"))
    return m.group(1) if m else ""


def _nav_line(z):
    """z is the line under a nav tab's button: an empty zone right after a goto button in its flow."""
    if z.get("type-v2") != "empty" or z.getparent() is None:
        return False
    kids = z.getparent().findall("zone")
    i = kids.index(z)
    return i > 0 and _goto(kids[i - 1]) is not None


def check_navigation(root):
    """Goto-sheet buttons between dashboards (decisions/040):
    - a button opens an existing window: its window-id is the simple-id of the target's <window> (Desktop's form);
    - no dead end: in a workbook with navigation every dashboard has a button to another one (the way back);
    - the current dashboard is marked: its button to its own window is bold and the others are not; the accent line
      of a tab (design.NAV_UNDERLINE_PX thick) is under the current one only."""
    windows = {w.find("simple-id").get("uuid"): (w.get("class"), w.get("name")) for w in root.find("windows")
               if w.find("simple-id") is not None}
    issues, away, any_goto = [], {}, False
    for db in root.iter("dashboard"):
        name = db.get("name")
        where_d = f"dashboard '{name}'"
        height = int(db.find("size").get("maxheight"))
        own = next((u for u, (c, n) in windows.items() if c == "dashboard" and n == name), None)
        away.setdefault(name, 0)
        for z in db.find("zones").iter("zone"):
            target = _goto(z)
            if target is None:
                continue
            any_goto = True
            where = f"{where_d} zone {z.get('id')} button"
            if target == "":
                issues.append(Issue("navigation", where, f"goto action not in Desktop's form: "
                                                         f"{z.find('button').get('action')!r}"))
                continue
            if target not in windows:
                issues.append(Issue("navigation", where, f"leads to window {target}: no dashboard or sheet has it "
                                                         f"(the target is missing)"))
                continue
            if target != own:
                away[name] += 1
            font = z.find("button/button-visual-state/button-caption-font-style")
            bold = font is not None and font.get("bold") == "true"
            if bold != (target == own):
                issues.append(Issue("navigation", where, f"goes to '{windows[target][1]}' and is "
                                                         f"{'bold' if bold else 'not bold'}: only the current "
                                                         f"dashboard's button is bold"))
            if target == own and z.getparent().get("param") == "vert":  # a tab: its line marks it
                kids = z.getparent().findall("zone")
                i = kids.index(z)
                line = kids[i + 1] if i + 1 < len(kids) and _nav_line(kids[i + 1]) else None
                if line is not None and "background-color" not in _style(line):
                    issues.append(Issue("navigation", where, "the current dashboard's tab has no accent line"))
        for z in db.find("zones").iter("zone"):
            st = _style(z)
            if not (_nav_line(z) and "background-color" in st):
                continue
            where = f"{where_d} zone {z.get('id')} (tab line)"
            kids = z.getparent().findall("zone")
            if _goto(kids[kids.index(z) - 1]) != own:
                issues.append(Issue("navigation", where, "the accent line is under the tab of another dashboard, "
                                                         "not the current one"))
            if st["background-color"] != COLOR["accent"]:
                issues.append(Issue("navigation", where, f"line color {st['background-color']} is not the accent "
                                                         f"token {COLOR['accent']}"))
            m = _margins(st)
            drawn = round(int(z.get("h")) * height / FULL) - (m["top"] or 0) - (m["bottom"] or 0)
            if drawn != NAV_UNDERLINE_PX:
                issues.append(Issue("navigation", where, f"line is {drawn}px thick inside its margins, not "
                                                         f"{NAV_UNDERLINE_PX}px"))
    if any_goto:
        for name, n in away.items():
            if not n:
                issues.append(Issue("navigation", f"dashboard '{name}'", "no button to another dashboard in a "
                                                                          "workbook with navigation: no way back"))
    return issues


def check_bands(root):
    """A band with a background on the root (the app top bar) stays between the dashboard's edge margins."""
    issues = []
    for db in root.iter("dashboard"):
        width = int(db.find("size").get("maxwidth"))
        for r in db.find("zones").findall("zone"):
            m = round(int(_margins(_style(r))["left"] or 0) * FULL / width)
            for z in r.findall("zone"):
                if "background-color" not in _style(z):
                    continue
                x, _, w, _ = _box(z)
                if x < m or x + w > FULL - m:
                    issues.append(Issue("layout", f"dashboard '{db.get('name')}' zone {z.get('id')}",
                                        f"band {x}..{x + w} is wider than the dashboard inside its edge margins "
                                        f"({m}..{FULL - m})"))
    return issues


FLOW_SIZED = ("dashboard-object", "bitmap", None)  # a button, a picture, a sheet (no type-v2): sized to content


def check_flow_sizes(root):
    """A button, a picture or a sheet in a layout flow next to another free item is resized by Desktop on Save As
    (decisions/092: Welcome 240 -> 60px "Wel..", a button 36 -> 52px, the logo to its picture's height): it is
    is-fixed, and its fixed-size is the zone along the flow inside its margins (Desktop draws fixed-size + margins).
    Free items all of one kind share the flow and keep their sizes (Citizen's tab button over its fixed underline,
    the shell's row of export buttons)."""
    issues = []
    for db in root.iter("dashboard"):
        size = db.find("size")
        if size is None or not size.get("maxwidth") or not size.get("maxheight"):
            continue
        dims = {"horz": int(size.get("maxwidth")), "vert": int(size.get("maxheight"))}
        for flow in db.iter("zone"):
            axis = flow.get("param")
            if flow.get("type-v2") != "layout-flow" or axis not in dims:
                continue
            kids = flow.findall("zone")
            free = [z for z in kids if z.get("is-fixed") != "true"]
            for z in kids:
                if z.get("type-v2") not in FLOW_SIZED or (z.get("type-v2") is None and not z.get("name")):
                    continue
                where = f"dashboard '{db.get('name')}' zone {z.get('id')} ({z.get('type-v2') or z.get('name')})"
                if z.get("is-fixed") != "true":
                    if any(f.get("type-v2") != z.get("type-v2") for f in free):  # another kind beside it
                        issues.append(Issue("layout", where, f"a free {z.get('type-v2') or 'sheet'} in a {axis} flow: "
                                            f"Desktop resizes it to its content on Save As; make it is-fixed with "
                                            f"fixed-size"))
                    continue
                m = _margins(_style(z))
                a, b = ("left", "right") if axis == "horz" else ("top", "bottom")
                extent = int(z.get("w" if axis == "horz" else "h")) * dims[axis] / FULL
                want = extent - (m[a] or 0) - (m[b] or 0)
                if abs(int(z.get("fixed-size", -99)) - want) > 1:
                    issues.append(Issue("layout", where, f"fixed-size {z.get('fixed-size')} px is not the zone inside "
                                        f"its margins ({want:.0f} px): Desktop redraws it at fixed-size + margins"))
    return issues


# ---- card theme (decisions/030) ----------------------------------------------------------------------------
def check_cards(root):
    """Borders, card faces, dividers and the canvas only from design tokens:
    - a border only on a card (a container): 1px solid card_border, face card_bg, margin card_margin, padding
      card_padding or card_padding_kpi (by the card's weight, decisions/070); on the canvas a container with the
      card face and no border is a borderless card (card_border false, decisions/089): the same face, margin,
      padding; with any card, the root zone's margin is theme_edge: edge and gap are one system (decisions/187);
    - an empty zone with a background is a divider: the rule color, drawn 1px thick inside its margins;
    - the dashboard's background is the canvas."""
    issues = []
    for db in root.iter("dashboard"):
        where = f"dashboard '{db.get('name')}'"
        width, height = (int(db.find("size").get(k)) for k in ("maxwidth", "maxheight"))
        for rule in db.findall("style/style-rule[@element='table']/format[@attr='background-color']"):
            if rule.get("value") != COLOR["canvas"]:
                issues.append(Issue("theme", where, f"dashboard background {rule.get('value')} is not the canvas "
                                                    f"token {COLOR['canvas']}"))
        canvas = any(r.get("value") == COLOR["canvas"]
                     for r in db.findall("style/style-rule[@element='table']/format[@attr='background-color']"))
        has_cards = False
        for z in db.find("zones").iter("zone"):
            zw = f"{where} zone {z.get('id')} ({z.get('type-v2') or z.get('name')})"
            st = _style(z)
            bordered = st.get("border-style", "none") != "none"
            face = (canvas and z.get("type-v2") in CONTAINERS and st.get("background-color") == COLOR["card_bg"]
                    and "padding" in st)
            if bordered or face:
                want = {"background-color": COLOR["card_bg"], "margin": str(SPACE["card_margin"])}
                if bordered:
                    want.update({"border-style": "solid", "border-color": COLOR["card_border"],
                                 "border-width": str(CARD_BORDER_PX)})
                if z.get("type-v2") not in CONTAINERS:
                    issues.append(Issue("theme", zw, "a border on a dashboard object: borders only on cards"))
                for attr, value in want.items():
                    if st.get(attr) != value:
                        issues.append(Issue("theme", zw, f"card {attr} {st.get(attr)} is not the token {value}"))
                pads = sorted({SPACE["card_padding"], SPACE["card_padding_kpi"]})
                if st.get("padding") not in map(str, pads):
                    issues.append(Issue("theme", zw, f"card padding {st.get('padding')} is not a card token {pads}"))
                if int(st.get("padding", 0)) < SPACE["card_margin"]:  # inner >= outer (decisions/070)
                    issues.append(Issue("theme", zw, f"card padding {st.get('padding')} is under half the gap between "
                                                     f"cards ({SPACE['card_margin']}): inner >= outer"))
                if z.get("type-v2") in CONTAINERS:
                    has_cards = True
            if z.get("type-v2") == "empty" and "background-color" in st and not _nav_line(z):  # 040 checks those
                m = _margins(st)
                drawn = (round(int(z.get("w")) * width / FULL) - (m["left"] or 0) - (m["right"] or 0),
                         round(int(z.get("h")) * height / FULL) - (m["top"] or 0) - (m["bottom"] or 0))
                if st["background-color"] != COLOR["rule"]:
                    issues.append(Issue("theme", zw, f"divider color {st['background-color']} is not the rule "
                                                     f"token {COLOR['rule']}"))
                if min(drawn) != 1:
                    issues.append(Issue("theme", zw, f"divider is {min(drawn)}px thick inside its margins, "
                                                     f"not 1px"))
        if has_cards:  # the edge and the gap are one system (decisions/187)
            for r in db.find("zones").findall("zone"):
                if _style(r).get("margin") != str(SPACE["theme_edge"]):
                    issues.append(Issue("theme", where, f"root zone margin {_style(r).get('margin')} is not the "
                                                        f"token {SPACE['theme_edge']}: the card edge is theme_edge + "
                                                        f"card_margin"))
    return issues


# ---- KPI v2 (decisions/037) --------------------------------------------------------------------------
FLAG_INSTANCE = re.compile(r"^\[[a-z]+:(.+):[a-z]+\]$")


def _flag_maps(ds):
    """{instance: [map colors]} of the palette maps in a datasource's style."""
    return {e.get("field"): [m.get("to") for m in e.findall("map")]
            for e in ds.iterfind("style/style-rule[@element='mark']/encoding[@attr='color']")}


SIGN_SHELF = re.compile(r"^\[[^\]]+\]\.\[usr:[^\]]+:qk\]$")


def _sign_sheets(root):
    """{worksheet: 'marker' | 'pill'}: one pane colored by one flag, no dimension, at most one constant measure on
    one shelf (decisions/063: MIN(1) on a fixed axis; a Square without shelves before it); a pill has a label, a
    marker only its color."""
    out = {}
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        panes = table.findall("panes/pane")
        shelves = [t for t in (table.findtext("rows"), table.findtext("cols")) if t]
        if len(panes) != 1 or len(shelves) > 1 or (shelves and not SIGN_SHELF.match(shelves[0])):
            continue
        mark = panes[0].find("mark")
        tags = [e.tag for e in panes[0].findall("encodings/*")]
        if mark is not None and mark.get("class") in ("Square", "Bar") and tags.count("color") == 1 \
                and "size" not in tags:  # a treemap: Square without shelves, sized (decisions/138)
            out[ws.get("name")] = "pill" if "text" in tags else "marker" if tags == ["color"] else None
    return {k: v for k, v in out.items() if v}


def _sign_fill(ws):
    """'' when a pill / marker sheet fills its zone, else why not: a Bar of a constant on a fixed axis (European
    Superstore 'Sales KPI YTD'); Desktop draws a Square without axes as a dot in the middle (decisions/061, 063)."""
    table = ws.find("table")
    shelf = next(((s, t) for s in ("rows", "cols") for t in [table.findtext(s)] if t), None)
    if table.find("panes/pane/mark").get("class") != "Bar" or shelf is None:
        return "is not a Bar on an axis: Desktop draws it as a dot in the middle of its zone, not a fill"
    scope, ref = shelf
    fixed = [e for e in table.iterfind("style/style-rule[@element='axis']/encoding")
             if e.get("field") == ref and e.get("scope") == scope and e.get("range-type") == "fixed"]
    if not fixed or float(fixed[0].get("min", "nan")) != 0 or float(fixed[0].get("max", "nan")) != 1:
        return f"bar axis {ref} is not fixed 0..1: the bar does not run the zone's length"
    return ""


def check_kpi(root):
    """- A boolean flag on Color has its palette map and its column-instance in the datasource: without either
      Desktop drops the map silently and paints Tableau's default palette (decisions/013, 028).
    - A pill / sign marker (a sheet colored by a flag) is a Bar on a fixed 0..1 axis, so it fills its zone
      (decisions/063); the marker is drawn design.MARKER_PX wide inside its margins.
    - A pill's fill is the pale good / bad token, so its bold text reads on it."""
    from .design import MARKER_PX
    issues = []
    datasources = {ds.get("name"): ds for ds in root.find("datasources").findall("datasource")}
    flags = {(name, c.get("name")) for name, ds in datasources.items() for c in ds.findall("column")
             if c.get("datatype") == "boolean" and c.find("calculation") is not None}
    signs = _sign_sheets(root)
    for ws in root.iter("worksheet"):
        where = f"worksheet '{ws.get('name')}'"
        why = _sign_fill(ws) if ws.get("name") in signs else ""
        if why:
            issues.append(Issue("kpi", where, f"{signs[ws.get('name')]} {why}"))
        for enc in ws.iterfind("table/panes/pane/encodings/color"):
            m = REF.match(enc.get("column", ""))
            if not m:
                continue
            ds_name, inst = m.groups()
            col = FLAG_INSTANCE.match(inst)
            if not col or (ds_name, f"[{col.group(1)}]") not in flags:
                continue
            ds = datasources.get(ds_name)
            maps = _flag_maps(ds)
            if inst not in maps:
                issues.append(Issue("kpi", where, f"color flag {inst} has no palette map in its datasource: Desktop "
                                                  f"paints its default palette"))
            elif not ds.findall(f"column-instance[@name='{inst}']"):
                issues.append(Issue("kpi", where, f"color flag {inst} has a palette map but no column-instance in "
                                                  f"the datasource: Desktop drops the map"))
            elif signs.get(ws.get("name")) == "pill":
                fills = {COLOR["good_fill"], COLOR["bad_fill"]}
                if set(maps[inst]) - fills:
                    issues.append(Issue("kpi", where, f"pill fill {sorted(set(maps[inst]) - fills)} is not a pale "
                                                      f"fill token {sorted(fills)}: its bold text does not read"))
    for db in root.iter("dashboard"):
        width = int(db.find("size").get("maxwidth"))
        for z in db.find("zones").iter("zone"):
            if signs.get(z.get("name")) != "marker" or z.get("type-v2"):  # its sheet zone, not a card named after it
                continue
            m = _margins(_style(z))
            drawn = round(int(z.get("w")) * width / FULL) - (m["left"] or 0) - (m["right"] or 0)
            if abs(drawn - MARKER_PX) > 1:
                issues.append(Issue("kpi", f"dashboard '{db.get('name')}' zone {z.get('id')} ({z.get('name')})",
                                    f"sign marker is {drawn}px wide inside its margins, not {MARKER_PX}px"))
    return issues


NARROW_MONTH = re.compile(r"^iL{5}$")  # 'J F M' (decisions/088: the reference's label text-format)
POINT_KINDS = ("Max", "Min", "Last", "Last Even")  # the sparkline point kinds (decisions/059)


def check_kpi_v3(root):
    """KPI card v3 (decisions/088):
    - month letters (label text-format iLLLLL) are on a discrete month (a [..:ok] instance) on the sheet's Columns:
      on a continuous date the axis keeps its own ticks and no letter is drawn;
    - an area sparkline (an Area with its measure axis hidden) has a pale fill (mark-transparency < 255): an opaque
      area hides its average line and reads as a bar;
    - a points legend line ('● Max') in a dashboard text names each kind in the color its sparklines paint it (the
      point kind's palette map); a kind no sparkline marks is a legend of nothing."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        cols = table.findtext("cols") or ""
        for f in table.iterfind("style/style-rule[@element='label']/format[@attr='text-format']"):
            if NARROW_MONTH.match(f.get("value", "")) and (not f.get("field", "").endswith(":ok]")
                                                           or f.get("field") not in cols):
                issues.append(Issue("kpi", where, f"month letters {f.get('value')} on {f.get('field')}: not a "
                                                  f"discrete month on Columns, Desktop draws no letters"))
        hidden = {f.get("field") for f in table.iterfind("style/style-rule[@element='axis']/format[@attr='display']")
                  if f.get("scope") == "rows" and f.get("value") == "false"}
        rows = table.findtext("rows") or ""
        if not any(r in rows for r in hidden):
            continue
        for pane in table.iterfind("panes/pane"):
            if pane.find("mark").get("class") != "Area" or not pane.findall("style/style-rule[@element='mark']"):
                continue
            t = pane.find("style/style-rule[@element='mark']/format[@attr='mark-transparency']")
            if t is None or int(t.get("value")) >= 255:
                issues.append(Issue("kpi", where, f"area sparkline pane {pane.get('id') or '(default)'} is opaque: "
                                                  f"its fill hides the average line, give it mark-transparency < 255"))
    painted = {}  # point kind -> colors its palette maps give it
    for ds in root.find("datasources").findall("datasource"):
        for e in ds.iterfind("style/style-rule[@element='mark']/encoding[@attr='color']"):
            for mp in e.findall("map"):
                kind = (mp.findtext("bucket") or "").strip('"')
                if kind in POINT_KINDS and "%null%" in [b.findtext("bucket") for b in e.findall("map")]:
                    painted.setdefault(kind, set()).add(mp.get("to", "").lower())
    for db in root.iter("dashboard"):
        for z in db.find("zones").iter("zone"):
            runs = z.findall("formatted-text/run")
            for glyph, lab in zip(runs, runs[1:]):
                kind = (lab.text or "").strip()
                if (glyph.text or "") != "● " or kind not in POINT_KINDS:
                    continue
                color = (glyph.get("fontcolor") or "").lower()
                if color not in painted.get(kind, set()):
                    issues.append(Issue("kpi", f"dashboard '{db.get('name')}' zone {z.get('id')}",
                                        f"points legend '● {kind}' in {color}, but the sparklines paint {kind} in "
                                        f"{sorted(painted.get(kind, [])) or 'no color: no sparkline marks it'}"))
    return issues


PROGRESS_SHELF = re.compile(r"^\((\[[^\[\]]+\]\.\[[a-z]+:([^\[\]:]+):qk\]) \+ (\[[^\[\]]+\]\.\[[a-z]+:([^\[\]:]+):qk\])\)$")
CONSTANT_ONE = re.compile(r"^\s*(MIN|MAX|AVG)\(\s*1(\.0)?\s*\)\s*$", re.I)


def check_kpi_progress(root):
    """KPI progress bar (decisions/155): a sheet without rows whose Columns are a dual axis of two Bars, one of them
    a constant 1 (the 100 % track, reference 'Normal Progress Chart'):
    - the constant is first on the shelf: the second layer is drawn over the first, a track over the fill hides the
      progress;
    - the track's axis is fixed 0..1, so 100 % is the zone's width, and the share's axis is folded onto it and
      synchronized: on its own automatic axis any share fills the whole zone."""
    issues = []
    consts = {c.get("name")[1:-1] for ds in root.find("datasources").findall("datasource")
              for c in ds.findall("column")
              if c.find("calculation") is not None and CONSTANT_ONE.match(c.find("calculation").get("formula", ""))}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        m = PROGRESS_SHELF.match(table.findtext("cols") or "")
        panes = table.findall("panes/pane")
        if not m or table.findtext("rows") or len(panes) != 3                 or any(p.find("mark").get("class") != "Bar" for p in panes):
            continue
        first, first_col, second, second_col = m.groups()
        if first_col not in consts:
            if second_col in consts and first_col not in consts:
                issues.append(Issue("kpi", where, f"progress track {second} is drawn over the fill {first}: put "
                                                  f"the constant first on Columns"))
            continue
        encs = {e.get("field"): e for e in table.iterfind("style/style-rule[@element='axis']/encoding")}
        a, f = encs.get(first), encs.get(second)
        if a is None or a.get("range-type") != "fixed" or float(a.get("min", "nan")) != 0                 or float(a.get("max", "nan")) != 1:
            issues.append(Issue("kpi", where, f"progress track axis {first} is not fixed 0..1: 100 % is not the "
                                              f"zone's width"))
        if f is None or f.get("fold") != "true" or f.get("synchronized") != "true":
            issues.append(Issue("kpi", where, f"progress fill axis {second} is not folded onto the track's and "
                                              f"synchronized: on its own axis any share fills the zone"))
    return issues


STATUS_BRANCH = re.compile(r'(IF|ELSEIF)\s+(.+?)\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s+THEN\s+'
                           r'"([^"]*)"\s*', re.I)


def _status_ladder(formula):
    """[(x, op, threshold, status)] of a formula that is only IF x op n THEN "s" ELSEIF ... END, else None."""
    out, pos = [], 0
    for m in STATUS_BRANCH.finditer(formula):
        if m.start() != pos or (m.group(1).upper() == "IF") != (pos == 0):
            return None
        out.append((m.group(2).strip(), m.group(3), float(m.group(4)), m.group(5)))
        pos = m.end()
    return out if out and formula[pos:].strip().upper() == "END" else None


def _ladder_disorder(ladder):
    """Why a threshold ladder hides a status ('' when ordered): one value compared, the thresholds strictly
    descending under >= / > (ascending under <= / <), a last branch only as the complement of the one before."""
    xs, ops = {x for x, *_ in ladder}, [op for _, op, _, _ in ladder]
    if len(xs) != 1:
        return f"compares {sorted(xs)}, not one value"
    down = ops[0] in (">=", ">")
    main = ladder
    if len(ladder) > 1 and (ops[-1] in (">=", ">")) != down:  # the last: the rest below (above) the last threshold
        main = ladder[:-1]
        if ladder[-1][2] != main[-1][2]:
            return f"its last branch at {ladder[-1][2]:g} is not the rest under {main[-1][2]:g}"
    if any((op in (">=", ">")) != down for _, op, _, _ in main):
        return "mixes >= and <= in its ladder"
    th = [t for _, _, t, _ in main]
    if any(a <= b if down else a >= b for a, b in zip(th, th[1:])):
        return f"thresholds {[f'{t:g}' for t in th]} are not {'descending' if down else 'ascending'}: a status " \
               f"after a wider branch never shows"
    return ""


def check_kpi_status(root):
    """A status dot (KPI cards, decisions/062): a sheet without rows and columns drawn as one Circle colored by a
    string calc that is a threshold ladder (IF [x] >= hi THEN "On track" ELSEIF [x] >= lo THEN ... END)
    - has its palette map and its column-instance in the datasource (else Desktop drops the map and paints its
      default palette, decisions/013) with a color for every status of the ladder;
    - its thresholds are ordered: each status can show."""
    issues = []
    datasources = {ds.get("name"): ds for ds in root.find("datasources").findall("datasource")}
    calcs = {(name, c.get("name")): c for name, ds in datasources.items() for c in ds.findall("column")
             if c.find("calculation") is not None and c.get("datatype") == "string"}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        panes = table.findall("panes/pane")
        if len(panes) != 1 or table.findtext("rows") or table.findtext("cols"):
            continue
        mark, encs = panes[0].find("mark"), panes[0].findall("encodings/*")
        if mark is None or mark.get("class") != "Circle" or [e.tag for e in encs] != ["color"]:
            continue
        m = REF.match(encs[0].get("column", ""))
        col = FLAG_INSTANCE.match(m.group(2)) if m else None
        calc = calcs.get((m.group(1), f"[{col.group(1)}]")) if col else None
        ladder = _status_ladder(calc.find("calculation").get("formula", "")) if calc is not None else None
        if not ladder:
            continue
        ds, inst = datasources[m.group(1)], m.group(2)
        maps = {e.get("field"): {b.text for b in e.iter("bucket")}
                for e in ds.iterfind("style/style-rule[@element='mark']/encoding[@attr='color']")}
        if inst not in maps:
            issues.append(Issue("kpi", where, f"status dot {inst} has no palette map in its datasource: Desktop paints "
                                              f"its default palette"))
        elif not ds.findall(f"column-instance[@name='{inst}']"):
            issues.append(Issue("kpi", where, f"status dot {inst} has a palette map but no column-instance in the "
                                              f"datasource: Desktop drops the map"))
        else:
            missing = sorted({s for *_, s in ladder} - {b.strip('"') for b in maps[inst]})
            if missing:
                issues.append(Issue("kpi", where, f"status dot {inst}: no palette color for status {missing}"))
        why = _ladder_disorder(ladder)
        if why:
            issues.append(Issue("kpi", where, f"status dot {calc.get('caption') or inst}: {why}"))
    return issues


POINT_FUNC = re.compile(r"\b(WINDOW_MAX|WINDOW_MIN|LAST)\s*\(", re.I)
AGG_INSTANCE = re.compile(r"^\[([a-z]+):(.+):[a-z]+\]$")


def _instance_expr(inst, derivations):
    """The formula text of a measure instance: [sum:Sales:qk] -> 'SUM([Sales])', [usr:Calc:qk] -> '[Calc]'."""
    m = AGG_INSTANCE.match(inst)
    if not m:
        return None
    return f"[{m.group(2)}]" if m.group(1) == "usr" else f"{derivations.get(m.group(1), m.group(1)).upper()}" \
                                                         f"([{m.group(2)}])"


def _points_of(code, line):
    """A points layer's formula: the max / min of the line's own measure, or its last mark (kpi2.point_formula); a
    window of another field (a slope's label positions, polish-26b) is not one."""
    return line in code and any(f.group(1).upper() == "LAST" or code[f.end():].lstrip().startswith(line)
                                for f in POINT_FUNC.finditer(code))


def check_spark_points(root):
    """Points on a line (KPI sparkline max / min / last, decisions/059): a dual-axis layer whose measure is a table calc
    of the line's own measure (WINDOW_MAX / WINDOW_MIN / LAST of it) shows values of the line, so
    - its axis is synchronized with the line's (else the max dot sits at the top of its own scale, not on the line);
    - on the sheet it is computed along the date axis on Columns (else the max of each period, a dot on every mark);
    - a table calc on its Color (the point kind) has a palette map and a column-instance with the same compute-using
      in the datasource (without it Desktop drops the map and paints its default palette, decisions/028)."""
    issues = []
    datasources = {ds.get("name"): ds for ds in root.find("datasources").findall("datasource")}
    formulas = {(name, c.get("name")): _formula_code(c.find("calculation").get("formula", ""))
                for name, ds in datasources.items() for c in ds.findall("column") if c.find("calculation") is not None}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        deps = {ci.get("name"): ci for ci in table.iterfind("view/datasource-dependencies/column-instance")}
        derivations = {ci.get("name").split(":")[0][1:]: ci.get("derivation") for ci in deps.values()}
        cols_text = table.findtext("cols") or ""
        for enc in table.iterfind("style/style-rule[@element='axis']/encoding[@fold='true']"):
            refs = DUAL_SHELF_REF.findall(table.findtext(enc.get("scope")) or "")
            field = enc.get("field", "")
            if field not in refs or refs.index(field) == 0:
                continue  # check_dual_axis reports it
            first = refs[refs.index(field) - 1]
            m, mf = REF.match(field), REF.match(first)
            if not m or not mf:
                continue
            ds_name, inst = m.groups()
            col = AGG_INSTANCE.match(inst)
            code = formulas.get((ds_name, f"[{col.group(2)}]")) if col else None
            line = _instance_expr(mf.group(2), derivations)
            if not code or not line or not _points_of(code, line):
                continue
            if enc.get("synchronized") != "true":
                issues.append(Issue("kpi", where, f"points {inst} on a line of {mf.group(2)} are not on a synchronized "
                                                  f"axis: the dots read against another scale than the line"))
            ci = deps.get(inst)
            along = [t.get("ordering-field") for t in (ci.findall("table-calc") if ci is not None else [])
                     if t.get("ordering-type") == "Field"]
            if not along or along[0] not in cols_text:
                issues.append(Issue("kpi", where, f"points {inst} are not computed along the date on Columns "
                                                  f"({along or 'no compute-using'}): every period would be its own max"))
            pane = next((p for p in table.iterfind("panes/pane") if p.get("y-axis-name", p.get("x-axis-name"))
                         == field), None)
            color = pane.find("encodings/color") if pane is not None else None
            cm = REF.match(color.get("column", "")) if color is not None else None
            if not cm:
                continue
            kind = cm.group(2)
            ds = datasources.get(cm.group(1))
            kcol = AGG_INSTANCE.match(kind)
            if not kcol or not TABLE_CALC_FUNC.search(formulas.get((cm.group(1), f"[{kcol.group(2)}]"), "")):
                continue
            ds_ci = ds.find(f"column-instance[@name='{kind}']")
            if kind not in _flag_maps(ds):
                issues.append(Issue("kpi", where, f"point kind {kind} has no palette map in its datasource: Desktop "
                                                  f"paints its default palette"))
            elif ds_ci is None or ds_ci.find("table-calc[@ordering-type='Field']") is None:
                issues.append(Issue("kpi", where, f"point kind {kind} has a palette map but no column-instance with "
                                                  f"its compute-using in the datasource: Desktop drops the map"))
    return issues


# ---- number formats (decisions/032) --------------------------------------------------------
NUMBER_TYPES = ("integer", "real")


def check_formats(root):
    """Every number format in the workbook is one tbuilder/formats.py writes (known currency symbol, 0-6 decimals,
    Desktop's own shape), and only numeric columns carry one."""
    issues = []
    found = [(c, c.get("default-format"), f"column {c.get('caption') or c.get('name')}")
             for c in root.iter("column") if c.get("default-format")]
    found += [(None, f.get("value"), f"style {f.getparent().get('element')} {f.get('id') or f.get('field') or ''}")
              for f in root.iter("format") if f.get("attr") == "text-format"]
    for col, text, where in found:
        if not text or text[0] not in "ncp":  # '*...' custom: the card's arrows and dates
            continue
        try:
            formats.parse(text)
        except formats.FormatError as e:
            issues.append(Issue("formats", where, str(e)))
        if col is not None and col.get("datatype") not in NUMBER_TYPES:
            issues.append(Issue("formats", where, f"number format '{text}' on a {col.get('datatype')} column"))
    return issues


# ---- dashboard actions -------------------------------------------------------------------
def check_actions(root):
    """Filter / highlight actions: the source and target sheets exist on their dashboards, at least one sheet is
    filtered, and every field of a filter link is a datasource column used by each target sheet."""
    acts = root.find("actions")
    if acts is None:
        return []
    ds_cols = _datasource_columns(root)
    issues, _ = _deps(acts, ds_cols, "actions")
    declared = {(d.get("datasource"), c.get("name")) for d in acts.findall("datasource-dependencies")
                for c in d.findall("column")}
    declared_names = {d.get("datasource"): {c.get("name") for c in d.findall("column")}
                      for d in acts.findall("datasource-dependencies")}
    sheet_ds = {w.get("name"): {d.get("name") for d in w.findall("table/view/datasources/datasource")}
                for w in root.iter("worksheet")}
    on_dash = {d.get("name"): [z.get("name") for z in d.find("zones").iter("zone")
                               if "type-v2" not in z.attrib and z.get("name")] for d in root.iter("dashboard")}
    instances = {(d.get("datasource"), ci.get("name")): ci.get("column") for d in acts.findall("datasource-dependencies")
                 for ci in d.findall("column-instance")}  # a period of a date: [tmn:Date:ok] (decisions/128)
    for a in acts.findall("action"):
        cmd = a.find("command")
        if cmd is None or cmd.get("command") not in ("tsc:tsl-filter", "tsc:brush"):
            continue
        where = f"action '{a.get('caption')}'"
        src = a.find("source")
        dash = src.get("dashboard")
        if dash is not None and dash not in on_dash:
            issues.append(Issue("actions", where, f"source dashboard '{dash}' does not exist"))
            continue
        src_sheets = on_dash[dash] if dash is not None else list(sheet_ds)
        for n in [src.get("worksheet")] + [e.get("name") for e in src.findall("exclude-sheet")]:
            if n is not None and n not in src_sheets:
                issues.append(Issue("actions", where, f"source sheet '{n}' is not on {dash or 'the workbook'}"))
        params = {p.get("name"): p.get("value") for p in cmd.findall("param")}
        target = params.get("target")
        if target in on_dash:
            excluded = [n for n in params.get("exclude", "").split(",") if n]
            for n in excluded:
                if n not in on_dash[target]:
                    issues.append(Issue("actions", where, f"excluded sheet '{n}' is not on dashboard '{target}'"))
            targets = [n for n in on_dash[target] if n not in excluded and n != src.get("worksheet")]
        elif target in sheet_ds:
            targets = [target]
        else:
            issues.append(Issue("actions", where, f"target '{target}' is neither a dashboard nor a worksheet"))
            continue
        if not targets:
            issues.append(Issue("actions", where, "filters no sheet: every target is excluded"))
        link = a.find("link")
        for ds, col in dict.fromkeys(REF.findall(unquote(link.get("expression"))) if link is not None else []):
            if (ds, col) in instances:
                if instances[ds, col] not in declared_names.get(ds, set()):
                    issues.append(Issue("actions", where, f"field {col} is an instance of undeclared column "
                                                          f"{instances[ds, col]}"))
            elif ":" in col and col not in ds_cols.get(ds, set()):
                issues.append(Issue("actions", where, f"field {col} is not declared in the actions' dependencies"))
            elif col not in ds_cols.get(ds, set()):
                issues.append(Issue("actions", where, f"field {col} is not in datasource {ds}"))
            elif (ds, col) not in declared:
                issues.append(Issue("actions", where, f"field {col} is not declared in the actions' dependencies"))
            for t in targets:
                if ds not in sheet_ds.get(t, set()):
                    issues.append(Issue("actions", where, f"target sheet '{t}' does not use datasource {ds} "
                                                          f"of field {col}"))
    return issues


# ---- actions v2: highlight fields, URL actions, parameter clear values, Show/Hide buttons (decisions/160) ------
FIELD_CAPTION = re.compile(r"[A-Z]+\((.+)\)")  # 'MONTH(Order Date)', 'ATTR(Company)'
URL_REF = re.compile(r"<\[([^\[\]<>]+)\]>")
URL_SCHEME = re.compile(r"(https?://|mailto:)\S+")
TOGGLE = re.compile(r'tabdoc:toggle-button-click-action window-id="([^"]*)" zone-id="([^"]*)" zone-ids=\[([0-9,]*)\]')
TOGGLE_FLAGS = ("BasicButtonObject", "CollapsiblePane")


def _toggles(db, zone):
    """A Show/Hide button of the dashboard toggles this zone."""
    return any(f"[{zone.get('id')}]" in t.text or f",{zone.get('id')}]" in t.text or f"[{zone.get('id')}," in t.text
               for t in db.iter("toggle-action") if t.text)


def check_actions_v2(root):
    """Highlight: every field caption names a column of the book (or a period / aggregate of one), else the action
    highlights nothing. URL: http(s) or mailto, its source sheet on its dashboard, every <[Field]> a column of a
    datasource the sheet uses. Parameter action: a fixed value on clearing is one of a list parameter's values.
    Show/Hide button: it names its own zone, its dashboard's window and zones of that dashboard outside itself; its
    visual state agrees with the container's visibility; the manifest flags."""
    issues = []
    ds_cols = _datasource_columns(root)
    captions = {n.strip("[]") for cols in ds_cols.values() for n in cols}
    captions |= {c.get("caption") for ds in root.find("datasources") for c in ds.findall("column") if c.get("caption")}
    captions.add("Measure Names")
    sheet_ds = {w.get("name"): {d.get("name") for d in w.findall("table/view/datasources/datasource")}
                for w in root.iter("worksheet")}
    on_dash = {d.get("name"): {z.get("name") for z in d.find("zones").iter("zone")
                               if "type-v2" not in z.attrib and z.get("name")} for d in root.iter("dashboard")}
    acts = root.find("actions")
    for a in acts.findall("action") if acts is not None else []:
        where = f"action '{a.get('caption')}'"
        cmd = a.find("command")
        if cmd is not None and cmd.get("command") == "tsc:brush":
            ps = {p.get("name"): p.get("value") for p in cmd.findall("param")}
            if "field-captions" not in ps and ps.get("special-fields") != "all":
                issues.append(Issue("actions", where, "highlight with neither field-captions nor all fields"))
            for f in [f for f in ps.get("field-captions", "").split(",") if f]:
                m = FIELD_CAPTION.fullmatch(f)
                if f not in captions and not (m and m.group(1) in captions):
                    issues.append(Issue("actions", where, f"highlight field '{f}' is no field of the workbook"))
            continue
        link = a.find("link")
        if cmd is not None or link is None or (link.get("expression") or "").startswith("tsl:"):
            continue
        expr = link.get("expression") or ""
        if not URL_SCHEME.match(expr):
            issues.append(Issue("actions", where, f"URL '{expr}' is not http(s):// or mailto:"))
        src = a.find("source")
        dash, name = src.get("dashboard"), src.get("worksheet")
        if dash not in on_dash or name not in on_dash[dash]:
            issues.append(Issue("actions", where, f"source sheet '{name}' is not on dashboard '{dash}'"))
            continue
        for f in URL_REF.findall(expr):
            if not any(f"[{f}]" in ds_cols.get(ds, set()) for ds in sheet_ds.get(name, set())):
                issues.append(Issue("actions", where, f"URL field [{f}] is no column of sheet '{name}'"))
    params = _param_columns(root)
    for a in root.iter("edit-parameter-action"):
        where = f"parameter action '{a.get('caption')}'"
        clear = a.find("clear-option")
        if clear is None or clear.get("type") != "assign-fixed-value":
            continue
        target = next((p.get("value") for p in a.iter("param") if p.get("name") == "target-parameter"), "")
        m = PARAM_REF.fullmatch(target)
        p = params.get(m.group(1)) if m else None
        if p is None or p.get("datatype") != "string" or p.get("param-domain-type") != "list":
            continue
        value = clear.get("value", "")
        if not value.startswith("s:LROOT:"):
            issues.append(Issue("actions", where, f"clear value {value!r} is not a string value (s:LROOT:...)"))
        elif f'"{value[len("s:LROOT:"):]}"' not in _members(p):
            issues.append(Issue("actions", where, f"clears to {value[len('s:LROOT:'):]!r}, which is not one of the "
                                                  f"values {_members(p)} of {m.group(1)}"))
    windows = {w.get("name"): w.find("simple-id").get("uuid") for w in root.iter("window")
               if w.get("class") == "dashboard" and w.find("simple-id") is not None}
    manifest = root.find("document-format-change-manifest")
    flags = {e.tag for e in manifest} if manifest is not None else set()
    toggles = 0
    for d in root.iter("dashboard"):
        zones = {z.get("id"): z for z in d.find("zones").iter("zone")}
        for z in zones.values():
            t = z.find("button/toggle-action")
            if t is None:
                continue
            toggles += 1
            where = f"Show/Hide button zone {z.get('id')} on '{d.get('name')}'"
            m = TOGGLE.fullmatch(t.text or "")
            if not m:
                issues.append(Issue("actions", where, f"toggle action {t.text!r} is not in Desktop's form"))
                continue
            window, own, ids = m.group(1), m.group(2), [i for i in m.group(3).split(",") if i]
            if window != windows.get(d.get("name")):
                issues.append(Issue("actions", where, f"window-id {window} is not the simple-id of the dashboard's "
                                                      f"window"))
            if own != z.get("id"):
                issues.append(Issue("actions", where, f"zone-id {own} is not the button's own zone"))
            if not ids:
                issues.append(Issue("actions", where, "toggles no zone"))
            for i in ids:
                c = zones.get(i)
                if c is None:
                    issues.append(Issue("actions", where, f"toggled zone {i} is not on the dashboard"))
                elif c is z or z in c.iter("zone"):
                    issues.append(Issue("actions", where, f"toggled zone {i} holds the button: it would hide itself"))
                else:
                    hidden = c.get("hidden-by-user") == "true"
                    state = z.find("button").get("active-visual-state-index", "0")
                    if state != ("1" if hidden else "0"):
                        issues.append(Issue("actions", where, f"visual state {state} but zone {i} is "
                                                              f"{'hidden' if hidden else 'shown'} at open"))
    if toggles:
        issues += [Issue("actions", "manifest", f"Show/Hide button without the {f} flag")
                   for f in TOGGLE_FLAGS if f not in flags]
    return issues


# ---- date filters -------------------------------------------------------------------------
DATE_LITERAL =re.compile(r"#(\d{4}-\d{2}-\d{2})( \d{2}:\d{2}:\d{2})?#")
INSTANCE = re.compile(r"\[(federated\.[a-z0-9]+)\]\.(\[[^\]]+\])")


def _date_literal(text, datatype):
    """'#2024-07-03#' for a date column, '#2024-07-03 00:00:00#' for a datetime one -> sortable str, else None."""
    m = DATE_LITERAL.fullmatch(text or "")
    if not m or bool(m.group(2)) != (datatype == "datetime"):
        return None
    if m.group(2) and int(m.group(2)[1:3]) > 23:  # Python 3.11+ reads 24:00:00 as the next midnight (decisions/055)
        return None
    try:
        return datetime.fromisoformat(m.group(1) + (m.group(2) or "")).isoformat()
    except ValueError:
        return None


def check_filters(root):
    """Date filters (relative-date, or quantitative on a date field or with date bounds): the field is a date or
    datetime column of its datasource, the bounds / anchor are valid dates in that column's form, min <= max."""
    types = {}
    for ds in root.find("datasources"):
        for name, datatype in _source_columns(ds).items():
            types[(ds.get("name"), name)] = datatype
        for c in ds.findall("column"):
            types.setdefault((ds.get("name"), c.get("name")), c.get("datatype"))
    issues = []
    scopes = [(f"shared-view '{sv.get('name')}'", sv) for sv in root.iter("shared-view")]
    scopes += [(f"worksheet '{ws.get('name')}'", ws.find("table/view")) for ws in root.iter("worksheet")]
    for where, scope in scopes:
        inst = {(d.get("datasource"), ci.get("name")): ci.get("column")
                for d in scope.findall("datasource-dependencies") for ci in d.findall("column-instance")}
        for flt in scope.findall("filter"):
            bounds = [flt.findtext(t) for t in ("min", "max") if flt.find(t) is not None]
            dated = flt.get("class") == "relative-date" or any((b or "").startswith("#") for b in bounds)
            m = INSTANCE.fullmatch(flt.get("column", ""))
            if not m or (m.group(1), m.group(2)) not in inst:
                if dated:
                    issues.append(Issue("filters", where, f"date filter on {flt.get('column')}: not a field of "
                                                          f"this sheet's datasource"))
                continue
            ds, name = m.groups()
            datatype = types.get((ds, inst[(ds, name)]))
            if datatype in ("date", "datetime"):
                dated = dated or flt.get("class") == "quantitative"
            if not dated:
                continue
            if datatype not in ("date", "datetime"):
                issues.append(Issue("filters", where, f"date filter on {name}: the field is {datatype}, not a date"))
                continue
            # bounds in the column's form; the anchor always as a datetime (Desktop writes it so on a date column too)
            literals = [(b, datatype) for b in bounds]
            if flt.get("class") == "relative-date":
                literals.append((flt.get("period-anchor"), "datetime"))
            parsed = [_date_literal(v, t) for v, t in literals]
            for (v, t), p in zip(literals, parsed):
                if p is None:
                    issues.append(Issue("filters", where, f"date filter on {name}: '{v}' is not a valid {t} "
                                                          f"literal (#YYYY-MM-DD#, datetime with HH:MM:SS)"))
            if len(bounds) == 2 and None not in parsed[:2] and parsed[0] > parsed[1]:
                issues.append(Issue("filters", where, f"date filter on {name}: min {bounds[0]} is after max {bounds[1]}"))
            if flt.get("class") == "relative-date" and not (
                    int(flt.get("first-period", "1")) <= int(flt.get("last-period", "0"))):
                issues.append(Issue("filters", where, f"relative date filter on {name}: first-period after "
                                                      f"last-period"))
            manifest = root.find("document-format-change-manifest")
            if flt.get("period-type-v2") and (manifest is None or manifest.find("ISO8601PeriodTypes") is None):
                # Desktop 2025.1 refuses the whole file: "attribute 'period-type-v2' is not declared"
                issues.append(Issue("filters", where, f"relative date filter on {name}: period-type-v2 needs "
                                                      f"<ISO8601PeriodTypes/> in the document-format-change-manifest"))
    return issues


SINGLE_CARDS = ("dropdown", "radiolist", "slider")  # filter card modes that show one value
APPLY_CARDS = (None, "checkdropdown", "checklist")  # cards with an Apply button: multiple values (decisions/162)
# a wildcard card (decisions/162): user:ui-pattern_type -> the function of the groupfilter's expression
PATTERN_FN = {"contains": "CONTAINS", "starts-with": "STARTSWITH"}


def _selection(flt, name):
    """(kind, members, problem) of a shared dimension filter in one of the states Desktop 2025.1 writes: kind 'all'
    (decisions/021), 'in' (one member, or a union of members) or 'out' (except: level-members minus a member or a
    union), members as written ('"West"'); problem: why it is none of them."""
    groups = flt.findall("groupfilter")
    if len(groups) != 1:
        return None, [], f"{len(groups)} groupfilters, expected one"
    g, enum = groups[0], groups[0].get(f"{{{USER_NS}}}ui-enumeration")

    def members(els):
        if not els or any(e.get("function") != "member" or e.get("level") != name or len(e) for e in els):
            return None
        return [e.get("member") for e in els]
    fn = g.get("function")
    if fn == "filter" and g.get(f"{{{USER_NS}}}ui-pattern_type") is not None:  # a wildcard (decisions/162)
        return _pattern(g, name)
    if fn == "level-members":
        if len(g) or g.get("level") != name:
            return None, [], f"level {g.get('level')} is not the filter's own declared instance (or has children)"
        return ("all", [], None) if enum == "all" else (None, [], "level-members without user:ui-enumeration='all'")
    if fn in ("member", "union"):
        ms = members([g] if fn == "member" else list(g))
        if ms is None or (fn == "union" and len(ms) < 2):
            return None, [], (f"{fn} without members of {name}: expected one level-members groupfilter (the (All) "
                              f"state) or the selected members")
        return ("in", ms, None) if enum == "inclusive" else (None, [], f"{fn} without ui-enumeration='inclusive'")
    if fn == "except":
        kids = list(g)
        head_ok = kids and kids[0].get("function") == "level-members" and kids[0].get("level") == name
        rest = kids[1:]
        ms = members(rest) if len(rest) == 1 and rest[0].get("function") == "member" else \
            members(list(rest[0])) if len(rest) == 1 and rest[0].get("function") == "union" else None
        if not head_ok or ms is None:
            return None, [], f"except: expected level-members of {name} and the members left out"
        return ("out", ms, None) if enum == "exclusive" else (None, [], "except without ui-enumeration='exclusive'")
    return None, [], (f"groupfilter function '{fn}': expected one level-members groupfilter (the (All) state) or "
                      f"the selected members")


def _pattern(g, name):
    """(kind 'match', [type, text], problem) of a wildcard filter as Desktop writes it (decisions/162): a filter
    groupfilter CONTAINS / STARTSWITH([field], 'text') over the (All) level-members of the instance."""
    u = lambda k: g.get(f"{{{USER_NS}}}{k}")  # noqa: E731
    ptype, text = u("ui-pattern_type"), u("ui-pattern_text")
    kids = list(g)
    field = "[" + name[1:-1].split(":")[1] + "]" if name.count(":") == 2 else name
    if ptype not in PATTERN_FN or not text:
        return None, [], f"wildcard: pattern type {ptype!r} / text {text!r} (contains, starts-with with a text)"
    if len(kids) != 1 or kids[0].get("function") != "level-members" or kids[0].get("level") != name or \
            kids[0].get(f"{{{USER_NS}}}ui-enumeration") != "all":
        return None, [], f"wildcard: expected the (All) level-members of {name} under the pattern"
    if g.get("expression") != f"{PATTERN_FN[ptype]}({field}, '{text}')":
        return None, [], (f"wildcard: expression {g.get('expression')!r} is not {PATTERN_FN[ptype]}({field}, "
                          f"'{text}') of its pattern text: the card shows one pattern, the sheets filter another")
    if u("ui-enumeration") != "inclusive" or u("ui-pattern-include-all-when-empty") != "true":
        return None, [], "wildcard: expected ui-enumeration inclusive and ui-pattern-include-all-when-empty true"
    return "match", [ptype, text], None


def _group_columns(el):
    """{[Group]: [Group]} for the groups (categorical-bin) declared under el: a group is filtered as its column."""
    return {c.get("name"): c.get("name") for d in el.iter("datasource-dependencies") for c in d.findall("column")
            if c.find("calculation") is not None and c.find("calculation").get("class") == "categorical-bin"}


def check_shared_filters(root, values=None):
    """Dimension filters applied to all sheets of a datasource (shared-view), in the states Desktop 2025.1 saves:
    (All) - one level-members groupfilter, no members (decisions/021); the values selected at open - a member or a
    union of members; exclude - except (decisions/035). Members are values of the data (values: _text_values;
    unchecked for Hyper / Excel), a selection of every value is the 021 bug (values added later filtered out).
    A single-value card shows one selected value. Every shared filter has its card: a filter (a context filter
    above all) the user cannot see or change hides data."""
    issues = []
    cards = {}
    for z in root.iter("zone"):
        if z.get("type-v2") == "filter":
            cards.setdefault(z.get("param"), []).append(z)
    switched = _switched(root)  # a period switch: its parameter is the control (decisions/042)
    for sv in root.iter("shared-view"):
        where = f"shared-view '{sv.get('name')}'"
        insts = {ci.get("name"): ci.get("column") for d in sv.findall("datasource-dependencies")
                 for ci in d.findall("column-instance")}
        insts.update(_group_columns(sv))  # a group filters as its column, no instance (decisions/151)
        for flt in sv.findall("filter"):
            m = INSTANCE.fullmatch(flt.get("column", ""))
            name = m.group(2) if m else flt.get("column")
            if flt.get("context") not in (None, "true"):
                issues.append(Issue("filters", where, f"filter on {name}: context='{flt.get('context')}'"))
            if flt.get("column") in switched:  # keeps the rows where the calc is true; no card
                kind, members, problem = _selection(flt, name)
                if problem or kind != "in" or members != ["true"]:
                    issues.append(Issue("filters", where, f"filter on {name}: a parameter switch keeps the rows where "
                                                          f"it is true (member true), got {problem or members}"))
                continue
            if flt.get("column") not in cards:
                issues.append(Issue("filters", where, f"{'context ' if flt.get('context') else ''}filter on {name} "
                                                      f"has no card on a dashboard: it hides data the user cannot "
                                                      f"see or change"))
            dtypes = {c.get("name"): c.get("datatype") for d in sv.findall("datasource-dependencies")
                      for c in d.findall("column")}
            for z in cards.get(flt.get("column"), []):
                if z.get("show-apply") is not None and (z.get("show-apply") != "true" or
                                                        z.get("mode") not in APPLY_CARDS):
                    issues.append(Issue("filters", where, f"filter on {name}: show-apply='{z.get('show-apply')}' on "
                                                          f"a {z.get('mode')} card (verified: true on a "
                                                          f"multiple-values card)"))
            if flt.get("class") == "quantitative" and dtypes.get(insts.get(name)) in ("integer", "real"):
                issues += _measure_range_issues(where, name, flt)
            if flt.get("class") != "categorical":
                continue
            if name not in insts:
                issues.append(Issue("filters", where, f"filter on {name}: {name} is not the filter's own declared "
                                                      f"instance (not in the shared-view's dependencies)"))
                continue
            kind, members, problem = _selection(flt, name)
            if problem:
                issues.append(Issue("filters", where, f"filter on {name}: {problem}"))
                continue
            if kind == "match":  # a wildcard: its card types the pattern (decisions/162)
                bad = [z.get("mode") for z in cards.get(flt.get("column"), []) if z.get("mode") != "pattern"]
                if bad:
                    issues.append(Issue("filters", where, f"filter on {name}: a wildcard pattern with {bad} cards: "
                                                          f"only a wildcard card (mode pattern) shows it"))
                continue
            data = (values or {}).get((m.group(1), insts[name])) if m else None
            issues += _member_issues(where, name, kind, members, dtypes.get(insts[name]), data)
            for z in cards.get(flt.get("column"), []):
                if z.get("mode") in SINGLE_CARDS and (kind == "out" or len(members) > 1):
                    issues.append(Issue("filters", where, f"filter on {name}: the single-value card ({z.get('mode')}) "
                                                          f"shows one value, the filter selects "
                                                          f"{'all but ' if kind == 'out' else ''}{len(members)}"))
    return issues


def _measure_range_issues(where, name, flt):
    """A dashboard range filter on a measure (decisions/162): the row-level [none:X:qk], in-range with numeric min
    and max, min <= max (Global Superstore)."""
    bounds = {t: flt.findtext(t) for t in ("min", "max") if flt.find(t) is not None}
    nums = {t: float(v) if v and NUMBER.fullmatch(v.strip()) else None for t, v in bounds.items()}
    if not name.startswith("[none:"):
        return [Issue("filters", where, f"measure range on {name}: a shared filter on a measure takes the row-level "
                                        f"[none:...:qk] (an aggregate depends on each sheet's marks)")]
    if flt.get("included-values") != "in-range" or set(bounds) != {"min", "max"}:
        return [Issue("filters", where, f"measure range on {name}: expected included-values 'in-range' with min "
                                        f"and max")]
    if None in nums.values():
        return [Issue("filters", where, f"measure range on {name}: bounds {bounds} are not numbers")]
    if nums["min"] > nums["max"]:
        return [Issue("filters", where, f"measure range on {name}: min {bounds['min']} is above max "
                                        f"{bounds['max']}")]
    return []


def check_filter_groups(root):
    """A filter of one dashboard (decisions/071): copies in the sheets' views tied by `filter-group` N. Every copy of
    N is the same filter (one column, one state); every dashboard showing a sheet that carries N has the filter's
    card, on a sheet that carries N - else the sheet is filtered by a card the user cannot see or change."""
    issues = []
    groups = {}
    for ws in root.iter("worksheet"):
        for flt in ws.findall("table/view/filter"):
            if flt.get("filter-group"):
                groups.setdefault(flt.get("filter-group"), []).append((ws.get("name"), flt))
    for n, copies in groups.items():
        where = f"filter-group {n}"
        first = etree.tostring(copies[0][1])
        for sheet, flt in copies[1:]:
            if etree.tostring(flt) != first:
                issues.append(Issue("filters", where, f"the copy in '{sheet}' differs from the one in "
                                                      f"'{copies[0][0]}': one filter, one state on every sheet"))
        carriers, column = {s for s, _ in copies}, copies[0][1].get("column")
        for db in root.iter("dashboard"):
            zones = list(db.iter("zone"))
            shown = {z.get("name") for z in zones if z.get("name") and z.get("type-v2") is None}
            cards = [z.get("name") for z in zones if z.get("type-v2") == "filter" and z.get("param") == column]
            if shown & carriers and not cards:
                issues.append(Issue("filters", f"dashboard '{db.get('name')}'",
                                    f"{where} on {column} filters {sorted(shown & carriers)} and has no card here"))
            for c in cards:
                if c not in carriers:
                    issues.append(Issue("filters", f"dashboard '{db.get('name')}'",
                                        f"the card of {column} is on '{c}', which does not carry {where}"))
    return issues


def _member_issues(where, name, kind, members, datatype, data):
    """Members of a filter of values: quoted text, or true / false on a boolean field (a public book: member='true');
    listed once; values of the data (text sources); not every value of the data (decisions/021)."""
    issues = []
    if kind == "match":  # a wildcard pattern, no members (decisions/162)
        return issues
    if datatype == "boolean":
        literal = [{"true": "true", "false": "false"}.get(v) for v in members]
        if None in literal:
            return [Issue("filters", where, f"filter on {name}: members {members} of a boolean field are not true / "
                                            f"false")]
        data = None  # a boolean calc: its values are not in the data file
    else:
        literal = [v[1:-1] if len(v) > 1 and v[0] == v[-1] == '"' else None for v in members]
        if None in literal:
            return [Issue("filters", where, f"filter on {name}: members {members} are not quoted text")]
    if len(set(literal)) != len(literal):
        issues.append(Issue("filters", where, f"filter on {name}: a member is listed twice: {literal}"))
    if data is not None and set(literal) - data:
        issues.append(Issue("filters", where, f"filter on {name} selects {sorted(set(literal) - data)}, values "
                                              f"the data does not have"))
    if data and kind == "in" and set(literal) == data:
        issues.append(Issue("filters", where, f"filter on {name} lists members: values added to the data later "
                                              f"are filtered out (it lists every value of the data); write "
                                              f"the (All) state"))
    return issues


AGG_PREFIXES = ("sum", "avg", "min", "max", "cnt", "ctd", "usr", "med", "attr")


def check_sheet_filters(root, values=None):
    """A worksheet's own filters (decisions/057), other than Measure Names and Top N: a filter of values in one of
    the states of a shared filter (_selection) on its own declared dimension instance, members as _member_issues;
    a measure filter: quantitative on an aggregate instance, included-values in-range with a numeric min and / or
    max, min <= max. The column is in the sheet's slices (Desktop lists every filter of the view there)."""
    issues = []
    for ws in root.iter("worksheet"):
        view = ws.find("table/view")
        if view is None:
            continue
        where = f"worksheet '{ws.get('name')}'"
        insts = {ci.get("name"): ci.get("column") for d in view.findall("datasource-dependencies")
                 for ci in d.findall("column-instance")}
        insts.update(_group_columns(view))
        dtypes = {c.get("name"): c.get("datatype") for d in view.findall("datasource-dependencies")
                  for c in d.findall("column")}
        slices = {c.text for c in view.findall("slices/column")}
        for flt in view.findall("filter"):
            m = INSTANCE.fullmatch(flt.get("column", ""))
            if not m or m.group(2) == "[:Measure Names]":
                continue
            name, groups = m.group(2), flt.findall("groupfilter")
            if groups and groups[0].get("function") == "end":  # Top N (check_parameters)
                continue
            if name[1:].split(":")[0] == "rank":  # Top N after the filters (check_rank_filters)
                continue
            agg = name[1:].split(":")[0] in AGG_PREFIXES
            if flt.get("class") == "categorical" and not agg:
                if name not in insts:
                    issues.append(Issue("filters", where, f"filter on {name}: not a declared instance of the sheet"))
                    continue
                kind, members, problem = _selection(flt, name)
                if problem:
                    issues.append(Issue("filters", where, f"filter on {name}: {problem}"))
                    continue
                data = (values or {}).get((m.group(1), insts[name]))
                issues += _member_issues(where, name, kind, members, dtypes.get(insts[name]), data)
            elif flt.get("class") == "quantitative" and agg:
                if name not in insts:
                    issues.append(Issue("filters", where, f"measure filter on {name}: not a declared instance"))
                    continue
                bounds = {t: flt.findtext(t) for t in ("min", "max") if flt.find(t) is not None}
                nums = {t: float(v) if v and NUMBER.fullmatch(v.strip()) else None for t, v in bounds.items()}
                if flt.get("included-values") != "in-range" or not bounds:
                    issues.append(Issue("filters", where, f"measure filter on {name}: expected included-values "
                                                          f"'in-range' with min and / or max"))
                elif None in nums.values():
                    issues.append(Issue("filters", where, f"measure filter on {name}: bounds {bounds} are not numbers"))
                elif len(nums) == 2 and nums["min"] > nums["max"]:
                    issues.append(Issue("filters", where, f"measure filter on {name}: min {bounds['min']} is above "
                                                          f"max {bounds['max']}"))
            else:
                continue  # date filters: check_filters
            if flt.get("column") not in slices:
                issues.append(Issue("filters", where, f"filter on {name} is not in the sheet's slices"))
    return issues


def _instance_names(root):
    """{spec field name (caption or column name): column name} of the data sources' columns."""
    out = {}
    for ds in root.find("datasources"):
        for c in ds.findall("column"):
            name = c.get("name", "")[1:-1]
            if c.find("calculation") is not None:  # a calc: the spec names it by its caption
                out.setdefault(c.get("caption") or name, name)
            else:  # a column of the data: the spec keeps its name whatever its caption (decisions/073)
                out.setdefault(name, name)
    return out


def _spec_member(v):
    return ("true" if v else "false") if isinstance(v, bool) else f'"{v}"'


MEASURE_PREFIX = {"sum": "sum", "avg": "avg", "min": "min", "max": "max", "count": "cnt", "countd": "ctd", "median": "med"}


# spec card mode -> the zone modes it may have (decisions/035, 162); others: (All)-style multiple values
CARD_MODE = {"single_dropdown": ("dropdown",), "single_list": ("radiolist",), "single_slider": ("slider",),
             "wildcard": ("pattern",)}


def check_filter_spec(root, spec):
    """The workbook opens in the filter state the spec asks for (decisions/035): the default selection (or (All)),
    exclude, context, only relevant values. Without it a lost default goes unnoticed: (All) is a valid state too.
    A sheet's own filters (decisions/057): in that sheet's view, in the state / range the spec asks for."""
    issues = []
    svs = list(root.iter("shared-view"))
    names = _instance_names(root)

    grouped = {n[1:-1] for n in _group_columns(root)}

    def inst_of(field):
        return f"[{field}]" if field in grouped else f"[none:{names.get(field, field)}:nk]"

    def find(filters, inst):
        return next((x for x in filters if INSTANCE.fullmatch(x.get("column", ""))
                     and INSTANCE.fullmatch(x.get("column")).group(2) == inst), None)

    def state(flt, f, inst, where):
        kind, members, problem = _selection(flt, inst)
        if problem:
            return  # check_shared_filters / check_sheet_filters report it
        want_kind = "all" if not f.get("default") else "out" if f.get("exclude") else "in"
        want = sorted(_spec_member(v) for v in f.get("default", []))
        if f.get("mode") == "wildcard" and f.get("pattern"):  # decisions/162
            want_kind = "match"
            want = sorted([{"starts_with": "starts-with"}.get(f.get("match"), "contains"), f["pattern"]])
        if (kind, sorted(members)) != (want_kind, want):
            issues.append(Issue("filters", where, f"the workbook opens with {kind} {sorted(members)}, the spec asks "
                                                  f"for {want_kind} {want}"))
    for f in spec.get("filters", []):
        if f.get("mode") == "range" and isinstance(f.get("min"), (int, float)):  # a measure range (decisions/162)
            where = f"filter '{f['field']}'"
            flt = find([x for sv in svs for x in sv.findall("filter")], f"[none:{names.get(f['field'], f['field'])}:qk]")
            if flt is None or flt.get("class") != "quantitative":
                issues.append(Issue("filters", where, "no shared range filter on the measure"))
                continue
            try:
                got = {t: float(flt.findtext(t)) for t in ("min", "max")}
            except (TypeError, ValueError):
                continue  # check_shared_filters reports it
            if any(abs(got[t] - f[t]) > 1e-9 * max(1, abs(f[t])) for t in got):
                issues.append(Issue("filters", where, f"the workbook keeps {got}, the spec asks for "
                                                      f"{ {t: f[t] for t in ('min', 'max')} }"))
            continue
        if f.get("mode", "values") in ("range", "relative"):
            continue
        inst, where = inst_of(f["field"]), f"filter '{f['field']}'"
        grouped = [x for ws in root.iter("worksheet") for x in ws.findall("table/view/filter")
                   if x.get("filter-group")]  # a dashboard's filter (decisions/071): check_filter_groups
        flt = find([x for sv in svs for x in sv.findall("filter")] + grouped, inst)
        if flt is None:
            issues.append(Issue("filters", where, "no shared filter on the field"))
            continue
        state(flt, f, inst, where)
        if (flt.get("context") == "true") != bool(f.get("context")):
            issues.append(Issue("filters", where, f"context is {flt.get('context') == 'true'}, the spec asks for "
                                                  f"{bool(f.get('context'))}"))
        zones = [z for z in root.iter("zone") if z.get("type-v2") == "filter" and z.get("param") == flt.get("column")]
        if any((z.get("values") == "relevant") != bool(f.get("relevant")) for z in zones):
            issues.append(Issue("filters", where, f"card values {[z.get('values') for z in zones]}, the spec asks "
                                                  f"for relevant={bool(f.get('relevant'))}"))
        want_mode = CARD_MODE.get(f.get("mode", "values"), (None, "checkdropdown"))
        if any(z.get("mode") not in want_mode for z in zones):  # decisions/162
            issues.append(Issue("filters", where, f"card modes {[z.get('mode') for z in zones]}, the spec asks for "
                                                  f"a {f.get('mode', 'values')} card"))
        if any((z.get("show-apply") == "true") != bool(f.get("apply")) for z in zones):
            issues.append(Issue("filters", where, f"card show-apply {[z.get('show-apply') for z in zones]}, the "
                                                  f"spec asks for apply={bool(f.get('apply'))}"))
    views = {ws.get("name"): ws.find("table/view") for ws in root.iter("worksheet")}
    for s in spec.get("sheets", []):
        for f in s.get("filters", []):
            where = f"sheet '{s['name']}', filter '{f['field']}'"
            flts = [x for n, v in views.items() if v is not None and (n == s["name"] or n.startswith(s["name"] + " · "))
                    for x in v.findall("filter")]  # a KPI's tiles: a worksheet each
            if "min" in f or "max" in f:
                col = names.get(f["field"], f["field"])
                prefixes = [MEASURE_PREFIX[f.get("agg", "sum")], "usr"]
                flt = next((x for p in prefixes for x in [find(flts, f"[{p}:{col}:qk]")] if x is not None), None)
                if flt is None or flt.get("class") != "quantitative":
                    issues.append(Issue("filters", where, "no measure filter on the field in the sheet"))
                    continue
                got = {t: flt.findtext(t) for t in ("min", "max") if flt.find(t) is not None}
                try:
                    same = set(got) == {t for t in ("min", "max") if t in f} and \
                        all(abs(float(got[t]) - f[t]) <= 1e-9 * max(1, abs(f[t])) for t in got)
                except ValueError:
                    same = False  # check_sheet_filters reports a bound that is no number
                if not same:
                    issues.append(Issue("filters", where, f"the sheet filters {got}, the spec asks for "
                                                          f"{ {t: f[t] for t in ('min', 'max') if t in f} }"))
                continue
            inst = inst_of(f["field"])
            flt = find(flts, inst)
            if flt is None:
                issues.append(Issue("filters", where, "no filter on the field in the sheet"))
                continue
            state(flt, f, inst, where)
    return issues


# ---- parameters ---------------------------------------------------------------------------
PARAM_REF = re.compile(r"\[Parameters\]\.(\[[^\[\]]+\])")
INT = re.compile(r"-?\d+")


def _texts(el):
    for node in el.iter():
        yield from node.attrib.values()
        yield node.text or ""


def _param_domain(c):
    """A parameter column: its value is its formula, a literal of its type, inside its domain."""
    name, value, issues = c.get("name"), c.get("value"), []
    where = f"parameter {name} ('{c.get('caption')}')"
    calc = c.find("calculation")
    if calc is None or calc.get("formula") != value:
        issues.append(Issue("params", where, "the value differs from its calculation formula"))
    dtype = c.get("datatype")
    parse = PARAM_LITERALS.get(dtype)
    if parse is None or parse(value) is None:
        issues.append(Issue("params", where, f"value {value!r} is not a {dtype} literal"))
        return issues
    want = "quantitative" if dtype in ("integer", "real", "date") else "nominal"
    if c.get("type") != want:  # Desktop: a date parameter is quantitative too (a public book), a boolean nominal
        issues.append(Issue("params", where, f"type {c.get('type')!r}: a {dtype} parameter is {want}"))
    domain = c.get("param-domain-type")
    if domain == "list" and c.get("source-field") is not None:  # the list is read at open (decisions/163)
        if c.find("members") is not None:
            issues.append(Issue("params", where, "a list from a field (source-field) keeps no members"))
    elif domain == "list":
        members = [m.get("value") for m in c.findall("members/member")]
        bad = [m for m in members if parse(m) is None]
        if bad:
            issues.append(Issue("params", where, f"members {bad} are not {dtype} literals"))
        if value not in members:
            issues.append(Issue("params", where, f"value {value} is not one of its members {members}"))
        shown = [m.get("alias") for m in c.findall("members/member") if m.get("alias") is not None]
        label = next((m.get("alias") for m in c.findall("members/member") if m.get("value") == value), None)
        if c.get("alias") != label:  # without it Desktop's card shows the first alias of the list (decisions/163)
            issues.append(Issue("params", where, f"column alias {c.get('alias')!r}: the value {value} shows as "
                                                 f"{label!r}"))
        if any(not x.strip() for x in shown) or len(set(shown)) != len(shown):  # decisions/148
            issues.append(Issue("params", where, f"aliases {shown} must be non-empty and differ from each other"))
        if dtype == "boolean" and sorted(members) != ["false", "true"]:
            issues.append(Issue("params", where, f"a boolean parameter's members are true and false, got {members}"))
    elif domain == "range":
        if dtype not in ("integer", "real", "date"):
            return issues + [Issue("params", where, f"a {dtype} parameter has no range")]
        rng = c.find("range")
        keys = ("min", "max") if dtype == "date" else ("min", "max", "granularity")
        bounds = [parse(rng.get(k)) if rng is not None and rng.get(k) is not None else None for k in keys]
        if None in bounds or (dtype == "date" and rng.get("granularity") is not None):
            return issues + [Issue("params", where, f"range needs {dtype} " + ", ".join(keys) +
                                   (" (no granularity)" if dtype == "date" else ""))]
        v = parse(value)
        lo, hi = bounds[:2]
        if dtype == "date":
            if not lo < hi or not lo <= v <= hi:
                issues.append(Issue("params", where, f"value {value} is not within the range {lo}..{hi}"))
            return issues
        step = bounds[2]
        n = (v - lo) / step if step > 0 else None
        if not (lo < hi and n is not None and lo <= v <= hi and abs(n - round(n)) < 1e-9):
            issues.append(Issue("params", where, f"value {v} is not a step of the range {lo}..{hi} by {step}"))
    return issues


def _field_type(ds, name):
    """Datatype of a datasource column: its <column>, else its metadata record."""
    col = next((c for c in ds.findall("column") if c.get("name") == name), None)
    if col is not None and col.get("datatype"):
        return col.get("datatype")
    rec = next((r for r in ds.iter("metadata-record") if r.get("class") == "column"
                and r.findtext("local-name") == name), None)
    return rec.findtext("local-type") if rec is not None else None


def _param_fields(root, declared):
    """A parameter read from a field when the workbook opens (decisions/163): source-field (its list) is a column of
    its type with a list domain; default-value-field (its value) is a calc of its type without parameters; both in
    a datasource of the workbook, declared by every worksheet that uses the parameter (as in every reference), and
    the manifest has ParameterDefaultValues (as every reference with them)."""
    issues, used = [], []
    sources = {ds.get("name"): ds for ds in root.find("datasources")}
    for name, c in declared.items():
        where = f"parameter {name} ('{c.get('caption')}')"
        for attr in PARAM_FIELD_ATTRS:
            ref = c.get(attr)
            if ref is None:
                continue
            m = re.fullmatch(r"\[([^\]]+)\]\.(\[[^\]]+\])", ref)
            ds = sources.get(m.group(1)) if m else None
            kind = _field_type(ds, m.group(2)) if ds is not None else None
            if kind is None:
                issues.append(Issue("params", where, f"{attr} {ref} is no column of a datasource in the workbook"))
                continue
            used.append((name, m.group(1), m.group(2)))
            if kind != c.get("datatype"):
                issues.append(Issue("params", where, f"{attr} {ref} is {kind}; the parameter is {c.get('datatype')}"))
            if attr == "source-field" and c.get("param-domain-type") != "list":
                issues.append(Issue("params", where, f"source-field gives a list; the domain is "
                                                     f"{c.get('param-domain-type')}"))
            if attr == "default-value-field":
                calc = next((x.find("calculation") for x in ds.findall("column") if x.get("name") == m.group(2)), None)
                if calc is None:
                    issues.append(Issue("params", where, f"default-value-field {ref} is not a calculated field"))
                elif "[Parameters]." in calc.get("formula", ""):
                    issues.append(Issue("params", where, f"default-value-field {ref} refers to a parameter: its "
                                                         f"value at open would depend on a parameter"))
    if used and root.find("document-format-change-manifest/ParameterDefaultValues") is None:
        issues.append(Issue("manifest", "workbook", "a parameter from a field when the workbook opens without the "
                                                    "manifest flag ParameterDefaultValues"))
    for ws in root.iter("worksheet"):
        view = ws.find("table/view")
        deps = {d.get("datasource"): {x.get("name") for x in d.findall("column")}
                for d in view.findall("datasource-dependencies")}
        for name, ds, col in used:
            if name in deps.get("Parameters", ()) and col not in deps.get(ds, ()):
                issues.append(Issue("params", f"worksheet '{ws.get('name')}'", f"uses parameter {name} without "
                                                                                f"declaring its field {col}"))
    return issues


def _real_literal(text):
    return float(text) if text and REAL.fullmatch(text) else None


def _date_param(text):
    p = _date_literal(text or "", "date")
    return datetime.fromisoformat(p) if p else None


PARAM_LITERALS = {  # datatype -> literal -> value (None: not a literal of that type)
    "string": lambda t: t if re.fullmatch(r'"[^"]*"', t or "") else None,
    "integer": lambda t: int(t) if INT.fullmatch(t or "") else None,
    "real": _real_literal,
    "date": _date_param,
    "boolean": lambda t: {"true": True, "false": False}.get(t),
}
REAL = re.compile(r"-?\d+\.\d*([eE][-+]?\d+)?")  # Desktop: 0.5, 2025.0, 1. (a real always has its point)


TOP_BY = re.compile(r"(?:(SUM|AVG|MIN|MAX|COUNT|COUNTD|MEDIAN)\()?(\[(?:[^\]]|\]\])+\])\)?")


def check_top_by(root):
    """The 'by field' of a Top N (decisions/067): AGG([column]) of a declared non-string column, or [calc] of a
    declared aggregate calc, in the dependencies of the filter's datasource on that sheet (Desktop declares a by
    field that is not on the sheet as its column, without an instance: a public book's State Wise (%))."""
    issues = []
    for ws in root.iter("worksheet"):
        view = ws.find("table/view")
        if view is None:
            continue
        where = f"worksheet '{ws.get('name')}'"
        for flt in view.findall("filter"):
            end = flt.find("groupfilter[@function='end']")
            order = end.find("groupfilter[@function='order']") if end is not None else None
            if order is None:
                continue
            if (end.get("end"), order.get("direction")) not in (("top", "DESC"), ("bottom", "DESC")):  # decisions/148
                issues.append(Issue("params", where, f"Top N end={end.get('end')!r} with direction "
                                                     f"{order.get('direction')!r}: both end values go with DESC (Desktop sorts, end picks the end)"))
            m = INSTANCE.fullmatch(flt.get("column", ""))
            expr = order.get("expression", "")
            e = TOP_BY.fullmatch(expr.strip())
            if not m or not e or bool(e.group(1)) != expr.strip().endswith(")"):
                issues.append(Issue("params", where, f"Top N by {expr!r}: neither AGG([column]) nor [calc]"))
                continue
            cols = {c.get("name"): c for d in view.findall("datasource-dependencies")
                    if d.get("datasource") == m.group(1) for c in d.findall("column")}
            col = cols.get(e.group(2))
            if col is None:
                issues.append(Issue("params", where, f"Top N by {expr}: {e.group(2)} is not declared in the sheet's "
                                                     f"dependencies"))
            elif e.group(1) is None and col.find("calculation") is None:
                issues.append(Issue("params", where, f"Top N by {expr}: a column without an aggregation"))
            elif e.group(1) in ("SUM", "AVG") and col.get("datatype") not in ("integer", "real"):
                issues.append(Issue("params", where, f"Top N by {expr}: {e.group(1)} of a {col.get('datatype')}"))
    return issues


RANK_DERIVATIONS = ("Sum", "Avg", "Min", "Max", "Count", "CountD", "User")


def check_rank_filters(root):
    """Top N after the filters (decisions/086): a categorical filter on a [rank:...:ok] instance. The instance is
    declared on the sheet as a discrete aggregate of a number (or an aggregate calc) with a Rank table calc
    (rank-options Competition / Dense / Modified / Unique, Ascending / Descending; its compute-using is
    check_table_calcs'); the members are the ranks 1..N as integers (a union, N >= 2), and the filter is in the
    slices. A rank member is a number, so check_sheet_filters (quoted text of the data) does not read it."""
    issues = []
    for ws in root.iter("worksheet"):
        view = ws.find("table/view")
        if view is None:
            continue
        where = f"worksheet '{ws.get('name')}'"
        insts = {ci.get("name"): ci for d in view.findall("datasource-dependencies")
                 for ci in d.findall("column-instance")}
        cols = {c.get("name"): c for d in view.findall("datasource-dependencies") for c in d.findall("column")}
        slices = {c.text for c in view.findall("slices/column")}
        for flt in view.findall("filter"):
            m = INSTANCE.fullmatch(flt.get("column", ""))
            ci = insts.get(m.group(2)) if m else None
            tc = ci.find("table-calc") if ci is not None else None
            is_rank = (m and m.group(2)[1:].split(":")[0] == "rank") or (tc is not None and tc.get("type") == "Rank")
            if not is_rank:
                continue
            name = m.group(2)
            if ci is None:
                issues.append(Issue("filters", where, f"rank filter on {name}: not a declared instance of the sheet"))
                continue
            opts = set((tc.get("rank-options") or "").split(",")) if tc is not None else set()
            col = cols.get(ci.get("column"))
            if tc is None or tc.get("type") != "Rank":
                issues.append(Issue("filters", where, f"rank filter on {name}: the instance has no Rank table calc"))
            elif len(opts & {"Competition", "Dense", "Modified", "Unique"}) != 1 or \
                    len(opts & {"Ascending", "Descending"}) != 1 or len(opts) != 2:
                issues.append(Issue("filters", where, f"rank filter on {name}: rank-options "
                                                      f"{tc.get('rank-options')!r} are not a kind and a direction"))
            if ci.get("type") != "ordinal" or ci.get("derivation") not in RANK_DERIVATIONS:
                issues.append(Issue("filters", where, f"rank filter on {name}: the instance is not a discrete "
                                                      f"aggregate (type {ci.get('type')}, {ci.get('derivation')})"))
            elif col is None or (ci.get("derivation") not in ("Count", "CountD", "User")
                                 and col.get("datatype") not in NUMBER_TYPES):
                issues.append(Issue("filters", where, f"rank filter on {name}: ranks {ci.get('column')}, not a "
                                                      f"declared number"))
            g = flt.find("groupfilter")
            members = [x.get("member") for x in g] if g is not None and g.get("function") == "union" and \
                all(x.get("function") == "member" for x in g) else None
            if flt.get("class") != "categorical" or not members:
                issues.append(Issue("filters", where, f"rank filter on {name}: expected a categorical union of "
                                                      f"members 1..N"))
            elif any(not (v or "").isdigit() for v in members) or \
                    sorted(int(v) for v in members) != list(range(1, len(members) + 1)) or len(members) < 2:
                issues.append(Issue("filters", where, f"rank filter on {name}: members {members} are not the ranks "
                                                      f"1..N (N >= 2)"))
            if flt.get("column") not in slices:
                issues.append(Issue("filters", where, f"rank filter on {name} is not in the sheet's slices"))
    return issues


def check_parameters(root):
    """Parameters: every [Parameters].[X] reference names a declared parameter whose value is in its domain; a
    worksheet that uses one lists the Parameters datasource and declares it; a Top N counts by a positive integer
    or an integer parameter; a parameter card on a dashboard is declared in its dependencies."""
    pds = [ds for ds in root.find("datasources") if ds.get("name") == "Parameters"]
    declared = {c.get("name"): c for ds in pds for c in ds.findall("column")}
    issues = [i for c in declared.values() for i in _param_domain(c)]
    for name in sorted({n for t in _texts(root) for n in PARAM_REF.findall(t)} - set(declared)):
        issues.append(Issue("params", "workbook", f"reference to parameter {name}, which is not declared"))
    scopes = [(f"worksheet '{ws.get('name')}'", ws.find("table/view"), ws.find("table"))
              for ws in root.iter("worksheet")]
    scopes += [(f"dashboard '{db.get('name')}'", db, db.find("zones")) for db in root.iter("dashboard")]
    for where, scope, body in scopes:
        used = {n for t in _texts(body) for n in PARAM_REF.findall(t)}
        if body.tag == "zones":  # a text zone may show a parameter without a dependency; a card needs one
            used = {n for z in body.iter("zone") if z.get("type-v2") == "paramctrl"
                    for n in PARAM_REF.findall(z.get("param", ""))}
        if not used:
            continue
        listed = {d.get("name") for d in scope.findall("datasources/datasource")}
        deps = {c.get("name") for d in scope.findall("datasource-dependencies") if d.get("datasource") == "Parameters"
                for c in d.findall("column")}
        if "Parameters" not in listed:
            issues.append(Issue("params", where, "uses parameters but does not list the Parameters datasource"))
        for name in sorted(used - deps):
            issues.append(Issue("params", where, f"uses parameter {name} without declaring it in its dependencies"))
    issues += _param_fields(root, declared)
    for gf in root.iter("groupfilter"):
        if gf.get("function") != "end":
            continue
        count = gf.get("count", "")
        m = PARAM_REF.fullmatch(count)
        if m and m.group(1) in declared and declared[m.group(1)].get("datatype") != "integer":
            issues.append(Issue("params", "top filter", f"count {count} is a {declared[m.group(1)].get('datatype')} "
                                                        f"parameter, not an integer"))
        elif not m and not (count.isdigit() and int(count) >= 1):
            issues.append(Issue("params", "top filter", f"count {count!r} is neither a positive integer nor a "
                                                        f"parameter"))
    return issues


# ---- reference lines (decisions/028) ---------------------------------------------------
NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")


REFLINE_ALIGN = {"text-align": ("left", "center", "right"), "vertical-align": ("top", "center", "bottom")}


def check_reference_lines(root):
    """A constant line has a value (a number, or a #date# on a date axis); a custom label has its text; a line's look
    in the sheet style is for a line of that sheet. Its fields and parameters are checked with every reference
    (check_references, check_parameters)."""
    issues = []
    for ws in root.iter("worksheet"):
        where, ids = f"worksheet '{ws.get('name')}'", set()
        for rl in ws.iter("reference-line"):
            rid = rl.get("id")
            if rid in ids:
                issues.append(Issue("reflines", where, f"two reference lines with id {rid}"))
            ids.add(rid)
            value = rl.get("value")
            if rl.get("formula") == "constant" and not (value and (NUMBER.fullmatch(value) or
                                                                    re.fullmatch(r"#[^#]+#", value))):
                issues.append(Issue("reflines", where, f"constant line {rid} has no value"
                                    + (f" (got {value!r})" if value else "")))
            if rl.get("label-type") == "custom" and not (rl.get("label") or "").strip():
                issues.append(Issue("reflines", where, f"line {rid} has a custom label without text"))
            if rl.get("tooltip-type") is not None:  # SOC's newer Desktop writes it; 2025.1 rejects it (043)
                issues.append(Issue("reflines", where, f"line {rid} has tooltip-type, which Desktop 2025.1 does "
                                                       f"not declare"))
            if value and value.startswith("#"):  # a date line (decisions/043): on a continuous date axis
                issues += _date_line_axis(ws, rl, where)
            if rl.get("scope") == "per-cell" and rl.get("value-column") not in _on_sheet(ws.find("table")):
                issues.append(Issue("reflines", where, f"per-cell line {rid} is at {rl.get('value-column')}, which is "
                                                       f"on no shelf of the sheet: Desktop drops it and the line "
                                                       f"(decisions/065)"))
        fills = {f.get("id") for f in ws.iterfind("table/style/style-rule[@element='refline']/format[@attr='fill-above']")
                 if f.get("value") not in (None, "#00000000")}
        hidden = {f.get("id") for f in ws.iterfind("table/style/style-rule[@element='refline']/format"
                                                   "[@attr='line-visibility']") if f.get("value") == "off"}
        no_axis = {f.get("field") for f in ws.iterfind("table/style/style-rule[@element='axis']/format"
                                                       "[@attr='display'][@value='false']")
                   if ws.get("name", "").endswith(" · History")}  # only a KPI card's sparkline
        for rl in ws.iter("reference-line"):  # a line without a label: a target per bar or a band edge (decisions/095)
            if (rl.get("label-type") == "none" and rl.get("scope") != "per-cell" and rl.get("id") not in fills
                    and rl.get("id") not in hidden  # an unseen line only makes room (a funnel's labels, 159)
                    and rl.get("value-column") not in no_axis):  # a sparkline's goal: its card names it (178)
                issues.append(Issue("reflines", where, f"line {rl.get('id')} across the sheet has no label: nobody "
                                                       f"can tell what it marks (label-type none is for a line per "
                                                       f"bar, a target, or a band edge)"))
        for f in ws.iterfind("table/style/style-rule[@element='refline']/format"):
            if f.get("id") is not None and f.get("id") not in ids:
                issues.append(Issue("reflines", where, f"refline format for {f.get('id')}, which is no line here"))
            allowed = REFLINE_ALIGN.get(f.get("attr"))
            if allowed and f.get("value") not in allowed:
                issues.append(Issue("reflines", where, f"line {f.get('id')}: {f.get('attr')} {f.get('value')!r} is "
                                                       f"none of {', '.join(allowed)} (decisions/184)"))
        issues += _band_edges(root, ws, where)
        issues += _target_zones(ws, where)
    return issues


def _target_zones(ws, where):
    """A bullet graph's zones (decisions/152): a per-cell distribution at percents of each bar's target, rising
    between 0 and 100, under a per-cell line at that target; zones without the line have nothing to be percents of
    on the plot."""
    issues = []
    targets = {rl.get("value-column") for rl in ws.iter("reference-line")
               if rl.get("scope") == "per-cell" and rl.get("percentage-bands") != "true"}
    for rl in ws.iter("reference-line"):
        if rl.get("percentage-bands") != "true":
            continue
        if rl.get("scope") == "per-table" and rl.get("value-column") == rl.get("axis-column"):
            continue  # percents of the sheet's own axis, not zones of a target: a funnel's label room (decisions/159)
        rid = rl.get("id")
        try:
            pcts = [float(v.get("percentage")) for v in rl.iterfind("reference-line-value")]
        except (TypeError, ValueError):
            pcts = None
        if not pcts or not all(0 < p < 100 for p in pcts) or pcts != sorted(set(pcts)):
            issues.append(Issue("reflines", where, f"zones {rid}: percents {pcts} are not rising between 0 and 100"))
        if rl.get("scope") != "per-cell" or rl.get("value-column") not in targets:
            issues.append(Issue("reflines", where, f"zones {rid} at {rl.get('value-column')} have no target line per "
                                                   f"bar at that measure"))
    return issues


def _date_line_axis(ws, rl, where):
    """A #date# constant stands on a continuous date axis of the sheet (a date trunc on Rows or Columns): on a
    measure axis Desktop has no place for a day."""
    axis = rl.get("axis-column", "")
    table = ws.find("table")
    shelves = {f"[{d}].{n}" for d, n in _shelf_refs(table)}
    inst = {ci.get("name"): ci for ci in table.iterfind("view/datasource-dependencies/column-instance")}
    m = REF.fullmatch(axis)
    ci = inst.get(m.group(2)) if m else None
    if ci is None or not (ci.get("derivation") or "").endswith("-Trunc") or axis not in shelves:
        return [Issue("reflines", where, f"date line {rl.get('id')} is not on a continuous date axis of the sheet "
                                         f"(axis {axis})")]
    return []


def _param_values(root):
    """{'[Parameters].[Parameter N]': current value as float} of the numeric parameters."""
    out = {}
    for ds in root.find("datasources"):
        if ds.get("name") != "Parameters":
            continue
        for c in ds.findall("column"):
            try:
                out[f"[Parameters].{c.get('name')}"] = float(c.get("value"))
            except (TypeError, ValueError):
                pass
    return out


def _band_edges(root, ws, where):
    """A reference band (decisions/043) is two lines without a stroke: the pale fill above its 'from' edge and the
    white fill above its 'to' edge, the next line in z-order. 'to' is above 'from', or the band is drawn empty (the
    white covers the pale)."""
    fills = {}
    for f in ws.iterfind("table/style/style-rule[@element='refline']/format[@attr='fill-above']"):
        fills[f.get("id")] = f.get("value", "")
    by_z = {rl.get("z-order"): rl for rl in ws.iter("reference-line")}
    params, issues = _param_values(root), []

    def value(rl):
        if rl.get("formula") == "constant" and rl.get("value") and NUMBER.fullmatch(rl.get("value")):
            return float(rl.get("value"))
        return params.get(rl.get("value-column")) if rl.get("formula") == "average" else None

    for rl in ws.iter("reference-line"):
        fill = fills.get(rl.get("id"), "").lower()
        if not fill or fill in ("#00000000", COLOR["card_bg"]):
            continue
        top = by_z.get(str(int(rl.get("z-order", "0")) + 1))
        if top is None or fills.get(top.get("id"), "").lower() != COLOR["card_bg"]:
            issues.append(Issue("reflines", where, f"band edge {rl.get('id')} has no 'to' edge after it"))
            continue
        lo, hi = value(rl), value(top)
        if lo is not None and hi is not None and not lo < hi:
            issues.append(Issue("reflines", where, f"band {rl.get('id')}..{top.get('id')}: 'from' {lo:g} is not "
                                                   f"below 'to' {hi:g}"))
    return issues



def check_sort_flags(root):
    """<manual-sort> and <computed-sort> in a view need the manifest flag SortTagCleanup: without it Desktop 2025.1
    reports "no declaration found for element 'manual-sort'" on open (check-desktop, decisions/043)."""
    if root.find("document-format-change-manifest/SortTagCleanup") is not None:
        return []
    return [Issue("manifest", f"worksheet '{ws.get('name')}'", f"<{el.tag}> without the manifest flag SortTagCleanup")
            for ws in root.iter("worksheet") for el in ws.iterfind("table/view/*")
            if el.tag in ("manual-sort", "computed-sort")] + [
        Issue("manifest", f"datasource '{ds.get('caption') or ds.get('name')}'",  # a field order (decisions/056)
              "<default-sorts><manual-sort> without the manifest flag SortTagCleanup")
        for ds in root.iterfind("datasources/datasource") if ds.find("default-sorts/manual-sort") is not None]


def check_sheet_background(root):
    """A transparent sheet (a colored card, decisions/194) needs its manifest flag: Desktop adds it on save."""
    if root.find("document-format-change-manifest/WorksheetBackgroundTransparency") is not None:
        return []
    return [Issue("manifest", f"worksheet '{ws.get('name')}'", "transparent background without the manifest flag "
                                                               "WorksheetBackgroundTransparency")
            for ws in root.iter("worksheet")
            if ws.find("table/style/style-rule[@element='table']/format[@attr='background-color'][@value='#00000000']") is not None]


# ---- selected vs benchmark (decisions/043) ----------------------------------------------------------------------
def check_benchmarks(root):
    """A benchmark calc ('<sheet> · Benchmark') is a FIXED LOD: computed before the dimension filters, so a filter
    on the compared field or the selected member does not move it. Without it the benchmark follows the filter."""
    issues = []
    for ds in root.find("datasources"):
        for c in ds.findall("column"):
            calc = c.find("calculation")
            if not (c.get("caption") or "").endswith(" · Benchmark") or calc is None:
                continue
            if not re.search(r"\{\s*FIXED\b", _formula_code(calc.get("formula") or ""), re.I):
                issues.append(Issue("benchmark", f"calc '{c.get('caption')}'", "the benchmark is no FIXED LOD: a "
                                    "filter on the compared field would change it"))
    return issues


# ---- table calculation functions (decisions/034) ------------------------------------------
TABLE_CALC_FUNC = re.compile(r"\b(RANK|RANK_DENSE|RANK_UNIQUE|RANK_MODIFIED|RANK_PERCENTILE|WINDOW_[A-Z]+|LOOKUP|"
                             r"PREVIOUS_VALUE|RUNNING_[A-Z]+|TOTAL|INDEX|FIRST|LAST|SIZE)\s*\(", re.I)


def _formula_code(formula):
    """A formula without its string literals and // comments (they may spell a function name)."""
    out = re.sub(r'"(?:[^"]|"")*"|\'(?:[^\']|\'\')*\'', '""', formula)
    return re.sub(r"//[^\n]*", "", out)


def _lod_spans(code):
    """The text of each top-level {...} LOD expression."""
    spans, depth, start = [], 0, 0
    for i, ch in enumerate(code):
        if ch == "{":
            depth += 1
            start = i if depth == 1 else start
        elif ch == "}" and depth:
            depth -= 1
            if not depth:
                spans.append(code[start:i + 1])
    return spans


def check_calc_dates(root):
    """Every #...# in a calculated field is a valid #YYYY-MM-DD# or #YYYY-MM-DD HH:MM:SS# (decisions/055): Desktop
    reads other forms by the workbook locale, and an impossible date breaks the calc."""
    issues = []
    for ds in root.find("datasources"):
        for c in ds.findall("column"):
            calc = c.find("calculation")
            for lit in re.findall(r"#[^#]*#", _formula_code(calc.get("formula") or "") if calc is not None else ""):
                if _date_literal(lit, "datetime" if " " in lit else "date") is None:
                    issues.append(Issue("formula", f"calc '{c.get('caption') or c.get('name')}'",
                                        f"{lit} is not a valid date literal (#YYYY-MM-DD# or #YYYY-MM-DD HH:MM:SS#)"))
            # DATEPARSE("pattern", ...): only the pattern letters the generator knows how to compute (decisions/149)
            from .formula import FormulaError, date_format
            for fmt in re.findall(r'DATEPARSE\s*\(\s*"((?:[^"]|"")*)"', calc.get("formula") or "" if calc is not None else "", re.I):
                try:
                    date_format(fmt.replace('""', '"'))
                except FormulaError as e:
                    issues.append(Issue("formula", f"calc '{c.get('caption') or c.get('name')}'", str(e)))
    return issues


# The type of a calc that is one table calc call (decisions/147): the formula decides, Desktop does not recompute it.
TABLE_CALC_TYPE = {**{f: "integer" for f in ("RANK", "RANK_DENSE", "RANK_UNIQUE", "INDEX", "FIRST", "LAST", "SIZE",
                                             "WINDOW_COUNT", "RUNNING_COUNT")},
                   **{f: "real" for f in ("WINDOW_AVG", "WINDOW_MEDIAN", "RUNNING_AVG")}}


def _whole_call(code):
    """The name of the function when the whole formula is one call NAME(...), else None."""
    m = re.match(r"\s*([A-Z_]+)\s*\(", code, re.I)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(code)):
        depth += (code[i] == "(") - (code[i] == ")")
        if not depth:
            return m.group(1).upper() if not code[i + 1:].strip() else None
    return None


def check_table_calcs(root):
    """A calc with table calc functions has none inside a LOD (Tableau rejects it); on every sheet its column-instance
    names its compute-using (Specific Dimensions: ordering-type Field with fields), so Desktop does not pick its own
    default direction; every compute-using field of a table calc (also a quick one) is on the sheet's rows, columns or
    marks."""
    issues, tc_cols = [], set()
    for ds in root.find("datasources"):
        for c in ds.findall("column"):
            calc = c.find("calculation")
            if calc is None or not calc.get("formula"):
                continue
            code = _formula_code(calc.get("formula"))
            if TABLE_CALC_FUNC.search(code):
                tc_cols.add(c.get("name"))
            want = TABLE_CALC_TYPE.get(_whole_call(code))
            if want and c.get("datatype") != want:
                issues.append(Issue("tablecalc", f"calc '{c.get('caption') or c.get('name')}'",
                                    f"datatype '{c.get('datatype')}', but {_whole_call(code)} returns {want}"))
            if any(TABLE_CALC_FUNC.search(span) for span in _lod_spans(code)):
                issues.append(Issue("tablecalc", f"calc '{c.get('caption') or c.get('name')}'",
                                    "a table calculation function inside a LOD expression {...}"))
    for ws in root.iter("worksheet"):
        where, table = f"worksheet '{ws.get('name')}'", ws.find("table")
        shelves = {f"[{d}].{n}" for el in (table.find("rows"), table.find("cols")) if el is not None
                   for d, n in REF.findall(el.text or "")}
        shelves |= {f"[{d}].{n}" for enc in table.iterfind("panes/pane/encodings/*")
                    for d, n in REF.findall(enc.get("column", ""))}
        for ci in table.iterfind("view/datasource-dependencies/column-instance"):
            tcs = [t for t in ci.findall("table-calc") if t.get("ordering-type") == "Field"]
            fields = [f for t in tcs for f in [t.get("ordering-field")] + [o.get("field") for o in t.iter("order")] if f]
            if ci.get("column") in tc_cols and not fields:
                issues.append(Issue("tablecalc", where, f"table calculation {ci.get('name')} has no compute-using "
                                    f"(<table-calc ordering-type='Field'> with its dimensions): Desktop would pick its "
                                    f"own default direction"))
            for f in fields:
                if f not in shelves:
                    issues.append(Issue("tablecalc", where, f"{ci.get('name')} is computed along {f}, which is not "
                                        f"on the sheet's rows, columns or marks"))
    return issues


# ---- official XSD ----------------------------------------------------------------------
@lru_cache(maxsize=4)
def _schema(rel=XSD_DEFAULT):
    xsd = (VENDOR / rel).read_bytes()
    stubs = {USER_NS: "_user.xsd", "http://www.w3.org/XML/1998/namespace": "_xml.xsd"}
    resolver_map = {"_user.xsd": _USER_STUB, "_xml.xsd": _XML_STUB}
    for ns, loc in stubs.items():
        xsd = xsd.replace(f'<xs:import namespace="{ns}"/>'.encode(),
                          f'<xs:import namespace="{ns}" schemaLocation="{loc}"/>'.encode())

    class Stubs(etree.Resolver):
        def resolve(self, url, pubid, ctx):
            name = url.rsplit("/", 1)[-1]
            return self.resolve_string(resolver_map[name], ctx) if name in resolver_map else None

    parser = etree.XMLParser()
    parser.resolvers.add(Stubs())
    return etree.XMLSchema(etree.fromstring(xsd, parser, base_url=str(VENDOR / rel)))


def check_xsd(root):
    schema = _schema()
    schema.validate(root)
    return [Issue("xsd", f"line {e.line}", e.message) for e in schema.error_log
            if not any(p.match(e.message) for p in XSD_ALLOWLIST)]


# ---- packaged Hyper data (decisions/026) -------------------------------------------------------
# Hyper column type -> (local-type, remote-type) a workbook column reading it must declare (Desktop 2025.1, out/hyper_lab).
HYPER_TYPES = {"DATE": ("date", "133"), "TIMESTAMP": ("datetime", "135"), "TEXT": ("string", "129"),
               "BIG_INT": ("integer", "20"), "DOUBLE": ("real", "5")}
_TABLE = re.compile(r"\[([^\]]+)\]\.\[([^\]]+)\]")


def _hyper_sources(root):
    """(datasource, .hyper path in the package, relation) of each datasource that reads a .hyper as its table."""
    for ds in root.find("datasources"):
        conns = {nc.get("name"): nc.find("connection")
                 for nc in ds.iterfind("connection/named-connections/named-connection")}
        rel = ds.find("connection/relation")
        conn = conns.get(rel.get("connection")) if rel is not None else None
        if conn is not None and conn.get("class") == "hyper":
            yield ds, conn.get("dbname"), rel


def check_hyper(twbx_path, names, root):
    """The packaged .hyper has the table the workbook reads, with exactly the columns and types of its
    metadata-records, in their order. A missing file is check_package's finding."""
    sources = [s for s in _hyper_sources(root) if s[1] in names]
    if not sources:
        return []
    from tableauhyperapi import Connection, HyperProcess, TableName, Telemetry
    issues = []
    with (tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(twbx_path) as z,
          HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""}) as hp):
        for i, (ds, dbname, rel) in enumerate(sources):
            where = f"{dbname}"
            m = _TABLE.fullmatch(rel.get("table", ""))
            if not m:
                issues.append(Issue("hyper", where, f"relation table {rel.get('table')!r} is not [schema].[table]"))
                continue
            path = Path(tmp) / f"{i}.hyper"
            path.write_bytes(z.read(dbname))
            with Connection(hp.endpoint, path) as con:
                table = TableName(*m.groups())
                if not con.catalog.has_table(table):
                    issues.append(Issue("hyper", where, f"no table {rel.get('table')} in the extract"))
                    continue
                got = [(c.name.unescaped, c.type.tag.name) for c in con.catalog.get_table_definition(table).columns]
            recs = sorted((r for r in ds.iterfind("connection/metadata-records/metadata-record")
                           if r.get("class") == "column" and r.findtext("parent-name") == f"[{rel.get('name')}]"),
                          key=lambda r: int(r.findtext("ordinal")))
            declared = {r.findtext("remote-name"): (r.findtext("local-type"), r.findtext("remote-type")) for r in recs}
            hyper = dict(got)
            for name in hyper.keys() - declared.keys():
                issues.append(Issue("hyper", where, f"column '{name}' in the extract is not in the workbook"))
            for name in declared.keys() - hyper.keys():
                issues.append(Issue("hyper", where, f"workbook column '{name}' is missing from the extract"))
            for name in declared.keys() & hyper.keys():
                want = HYPER_TYPES.get(hyper[name])
                if want is None:
                    issues.append(Issue("hyper", where, f"column '{name}': Hyper type {hyper[name]} not supported"))
                elif declared[name] != want:
                    issues.append(Issue("hyper", where, f"column '{name}' is {hyper[name]} in the extract, the "
                                        f"workbook declares {declared[name][0]} (remote-type {declared[name][1]}), "
                                        f"expected {want[0]} ({want[1]})"))
            if hyper.keys() == declared.keys() and [n for n, _ in got] != list(declared):
                issues.append(Issue("hyper", where, f"column order {[n for n, _ in got]} differs from the "
                                    f"workbook's ordinals {list(declared)}"))
    return issues


# ---- totals and tooltips (decisions/036) ----------------------------------------------------------------------
SHELF_INSTANCE = re.compile(r"\[(federated\.[a-z0-9]+)\]\.\[([a-z]+):(.+):([a-z]+)\](?::\d+)?")
CELL_CALCS = ("MIN(1)", "MIN(0)")  # a registry text cell: a dummy axis whose bar is the cell (015); 0, a delta (164)


def _calc_formulas(root):
    """{(ds, '[Column]'): formula} of the calculated columns."""
    return {(ds.get("name"), c.get("name")): c.find("calculation").get("formula")
            for ds in root.find("datasources") for c in ds.findall("column")
            if c.find("calculation") is not None}


def _shelf_refs(table):
    return [r for tag in ("rows", "cols") for r in REF.findall(table.findtext(tag) or "")]


def _row_dims(table):
    """'[column]' of each dimension on the sheet's rows (a registry's outer and inner)."""
    out = []
    for ds, name in REF.findall(table.findtext("rows") or ""):
        m = SHELF_INSTANCE.fullmatch(f"[{ds}].{name}")
        if m and m.group(4) != "qk":
            out.append(f"[{m.group(3)}]")
    return out


def row_guard(dims):
    """The condition true on a mark of one row and false on a total (registry.is_row, decisions/081)."""
    return " AND ".join(f"COUNTD({d}) <= 1" for d in dims)


def _waterfall_run(table, formula):
    """A waterfall's running sum with its total column (decisions/144, reference <cols total='true'>): Gantt bars only,
    the total on Columns only, the axis a RUNNING_SUM calc: the total mark is the sum, the axis is meant to reach it."""
    return ((formula or "").startswith("RUNNING_SUM(") and table.find("rows").get("total") != "true"
            and table.find("cols").get("total") == "true"
            and all(m.get("class") == "GanttBar" for m in table.iter("mark")))


def _row_guarded_bar(formula, dims):
    """A registry bar under a total row (decisions/081): 'IF <guard> THEN a ELSE 0 END', 0 on the total so it does
    not stretch the column; or the total keeps its bar when it is within the rows':
    'IF (<guard>) OR a <= MAX({INCLUDE <row dims> : a}) THEN a ELSE 0 END'."""
    m = re.fullmatch(r"IF (.+) THEN (.+) ELSE 0 END", formula or "", re.S)
    if not m or not dims:
        return False
    cond, a, guard = m.group(1), m.group(2), row_guard(dims)
    if cond == guard:
        return True
    inc = re.fullmatch(re.escape(f"({guard})") + r" OR (.+) <= MAX\(\{INCLUDE (.+?) : (.+)\}\)", cond, re.S)
    return bool(inc) and inc.group(1) == inc.group(3) == a and [d.strip() for d in inc.group(2).split(",")] == dims


def _share_track(table, formulas):
    """A registry track under a total (decisions/134): Measure Values of a FIXED share and its rest on a fixed 0..1
    axis; the total's share is its own (100 % on the grand total), nothing rescales."""
    members = [REF.findall(g.get("member", "").strip('"'))
               for f in table.iterfind("view/filter") if f.get("column", "").endswith("[:Measure Names]")
               for g in f.iter("groupfilter") if g.get("member")]
    fixed = [e for e in table.iterfind("style/style-rule/encoding")
             if e.get("field", "").endswith("[Multiple Values]") and e.get("range-type") == "fixed"
             and e.get("min") == "0.0" and e.get("max") == "1.0"]
    if not members or not fixed:
        return False
    for ref in members:
        m = SHELF_INSTANCE.fullmatch(f"[{ref[0][0]}].{ref[0][1]}") if ref else None
        f = formulas.get((ref[0][0], f"[{m.group(3)}]")) if m else None
        share = re.fullmatch(r"(1 - )?(.+) / MAX\(\{FIXED : (.+)\}\)", f or "", re.S)
        if not share or share.group(2) != share.group(3):
            return False
    return True


def _row_guarded_color(formula, dims):
    """A registry dot under a total (decisions/134): 'IF <guard> THEN a END', NULL on the total, so the total keeps
    its number but takes no color and does not stretch the scale."""
    m = re.fullmatch(r"IF (.+?) THEN (.+) END", formula or "", re.S)
    return bool(m) and bool(dims) and m.group(1) == row_guard(dims) and " ELSE " not in m.group(2)


INSTANCE_AGG = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "cnt": "COUNT", "ctd": "COUNTD",
                "med": "MEDIAN"}
FUNNEL_START = re.compile(r"-(.+) / 2")


def _instance_expr_of(ref):
    """'[ds].[sum:Users:qk]' -> 'SUM([Users])', '[ds].[usr:Calculation_1:qk]' -> '[Calculation_1]' (a calc's own
    aggregation), None for others."""
    m = SHELF_INSTANCE.fullmatch(ref or "")
    if not m:
        return None
    if m.group(2) == "usr":
        return f"[{m.group(3)}]"
    return f"{INSTANCE_AGG[m.group(2)]}([{m.group(3)}])" if m.group(2) in INSTANCE_AGG else None


def check_funnel(root):
    """A funnel (decisions/159): Gantt bars starting at -value / 2 on Columns run by the value on Size, so each bar
    is centered; another size than the start's value shifts the bars off center. Its stages on Rows are in a fixed
    order (a computed-sort or the field's manual order): the conversion's LOOKUP takes the stage drawn above."""
    issues, formulas = [], _calc_formulas(root)
    sorted_cols = {f"[{ds.get('name')}].{ms.get('column')}" for ds in root.find("datasources")
                   for ms in ds.iterfind("default-sorts/manual-sort")}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        cols = (table.findtext("cols") or "").strip()
        m = SHELF_INSTANCE.fullmatch(cols)
        start = FUNNEL_START.fullmatch(formulas.get((m.group(1), f"[{m.group(3)}]")) or "") if m else None
        if not start or not all(k.get("class") == "GanttBar" for k in table.iter("mark")):
            continue
        sizes = [e.get("column") for e in table.iterfind("panes/pane/encodings/size")]
        if [_instance_expr_of(r) for r in sizes] != [start.group(1)]:
            issues.append(Issue("funnel", where, f"the bars start at -{start.group(1)} / 2 but run by "
                                                 f"{sizes or 'no size'}: they are not centered"))
        rows = (table.findtext("rows") or "").strip()
        computed = {c.get("column") for c in table.iterfind("view/computed-sort")}
        if rows not in computed and rows not in sorted_cols:
            issues.append(Issue("funnel", where, f"the stages {rows} have no fixed order (computed-sort or manual "
                                                 f"order): the conversion would compare stages by name"))
    return issues


def check_totals(root):
    """Totals only on a text table: no continuous axis (a total bar rescales its axis), except a registry's text
    cells (MIN(1)) and its bars guarded to the rows (0 on the total, decisions/081), no continuous color (the total
    rescales a heatmap's color); a subtotal is an outer dimension of a shelf."""
    issues, formulas = [], _calc_formulas(root)
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        sub = table.find("subtotals")
        if not (any(table.find(t) is not None and table.find(t).get("total") == "true" for t in ("rows", "cols"))
                or sub is not None):
            continue
        dims = _row_dims(table)
        for ds, name in _shelf_refs(table):
            m = SHELF_INSTANCE.fullmatch(f"[{ds}].{name}")
            f = formulas.get((ds, f"[{m.group(3)}]")) if m else None
            if (name == "[Multiple Values]" and not _share_track(table, formulas)) or (
                    m and m.group(4) == "qk" and f not in CELL_CALCS
                                               and not _row_guarded_bar(f, dims) and not _waterfall_run(table, f)):
                issues.append(Issue("totals", where, f"totals on a sheet with the axis {name}: the total mark "
                                                     f"rescales it (text tables, registry text cells and registry "
                                                     f"bars 0 on the total row only, decisions/081)"))
        for enc in table.iterfind("panes/pane/encodings/color"):
            c = SHELF_INSTANCE.fullmatch(enc.get("column", ""))
            if enc.get("column", "").endswith(":qk]") and not (
                    c and _row_guarded_color(formulas.get((c.group(1), f"[{c.group(3)}]")), dims)):
                issues.append(Issue("totals", where, f"totals on a sheet colored by {enc.get('column')}: the total "
                                                     f"rescales its color"))
        if sub is not None:
            for tag in ("rows", "cols"):
                refs = REF.findall(table.findtext(tag) or "")
                inner = {f"[{ds}].{n}" for ds, n in refs[-1:]}
                for col in sub.iterfind("column"):
                    if col.text in inner:
                        issues.append(Issue("totals", where, f"subtotal of the innermost dimension {col.text}: "
                                                             f"it equals its cells"))
            on = {f"[{ds}].{n}" for ds, n in _shelf_refs(table)}
            for col in sub.iterfind("column"):
                if col.text not in on:
                    issues.append(Issue("totals", where, f"subtotal of {col.text}, which is not on rows or columns"))
    return issues


def check_tooltips(root):
    """Every field of a customized tooltip is on the sheet: rows, columns, a mark encoding (the Tooltip shelf
    included) or a measure of Measure Values."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        on = set(_shelf_refs(table))
        for enc in table.iterfind("panes/pane/encodings/*"):
            on |= set(REF.findall(enc.get("column", "")))
        for f in table.iterfind("view/filter"):
            if f.get("column", "").endswith("[:Measure Names]"):
                for g in f.iter("groupfilter"):
                    on |= set(REF.findall(g.get("member", "")))
        for tip in table.iterfind("panes/pane/customized-tooltip"):
            for ds, name in REF.findall(" ".join(_texts(tip))):
                if name not in SPECIAL_INSTANCES and (ds, name) not in on:
                    issues.append(Issue("tooltips", where, f"tooltip field {name} is not on the sheet (rows, columns, "
                                                           f"marks or the Tooltip shelf)"))
    return issues


def check_mark_labels(root):
    """Every field of a pane's own label is on the sheet for that pane: rows, columns or the pane's encodings.
    Desktop shows nothing for one that is not (the "(230)" of a registry share cell, decisions/039)."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        shelves = {f"[{ds}].{n}" for ds, n in _shelf_refs(table)}
        for pane in table.iterfind("panes/pane"):
            on = shelves | {e.get("column") for e in pane.iterfind("encodings/*")}
            label = pane.find("customized-label")
            for ds, name in REF.findall(" ".join(_texts(label)) if label is not None else ""):
                if f"[{ds}].{name}" not in on:
                    issues.append(Issue("labels", where, f"label field {name} of pane {pane.get('id') or '(default)'} "
                                                         f"is not on the sheet (rows, columns or the pane's marks)"))
    return issues


NESTED_ROWS = re.compile(r"^\(\[[^\]]+\]\.\[[^\]]+\] / (\[[^\]]+\]\.\[[^\]]+\])\)$")


def check_registry_cells(root):
    """A two-dimension registry (rows '(outer / inner)') with labelled marks sets its rows at least
    REGISTRY_ROW_NESTED_PX high (cell height on the inner field, decisions/075): Desktop 2025.1 draws no label on a
    mark alone in its outer group at the automatic height, so a group of one row (one opportunity per group, or a
    filter leaving one member) shows an empty cell."""
    issues = []
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        m = NESTED_ROWS.match(table.findtext("rows") or "")
        if not m:
            continue
        labelled = [p.get("id") for p in table.iterfind("panes/pane")  # a registry's column panes: a bar's or a
                    if p.get("id") and p.find("mark") is not None  # dot's value is its label (a text table's is its
                    and p.find("mark").get("class") in ("Bar", "Circle")  # mark, drawn in any row)
                    and p.find("style/style-rule[@element='mark']/format[@attr='mark-labels-show'][@value='true']")
                    is not None]
        if not labelled:
            continue
        h = next((f.get("value") for f in table.iterfind("style/style-rule[@element='cell']/format[@attr='height']")
                  if f.get("field") == m.group(1)), None)
        if h is None or not h.isdigit() or int(h) < REGISTRY_ROW_NESTED_PX:
            issues.append(Issue("registry", f"worksheet '{ws.get('name')}'",
                                f"rows {h or 'at the automatic height'} under {REGISTRY_ROW_NESTED_PX}px: Desktop "
                                f"draws no label on a mark alone in its outer group (panes {labelled})"))
    return issues


def _pane_width(pane):
    return pane.find("style/style-rule[@element='pane']/format[@attr='maxwidth']")


def _single_registry(table):
    """A one-column registry (decisions/099): its only pane is id 1 without x-axis-name, the row headers have widths."""
    panes = table.findall("panes/pane")
    return (len(panes) == 1 and panes[0].get("id") is not None and not panes[0].get("x-axis-name")
            and table.find("style/style-rule[@element='header']/format[@attr='width']") is not None)


def registry_columns(table):
    """How many column panes a registry sheet has: its panes with a width (decisions/064), 1 for a one-column
    registry, whose single pane fills the sheet with no width of its own (099). 0: not a registry."""
    n = sum(_pane_width(p) is not None for p in table.iterfind("panes/pane"))
    return n or int(_single_registry(table))


def check_single_axis_pane(root):
    """One axis on Columns, one pane (decisions/099): a sheet whose only layer pane names its x axis next to the
    default pane is what Desktop folds on save - it drops the default pane (and the reference lines, tooltip and
    mark in it), the x-axis-name and the layer pane's width. Desktop's own form is that pane alone."""
    issues = []
    for ws in root.iter("worksheet"):
        panes = ws.findall("table/panes/pane")
        layers = [p for p in panes if p.get("id") is not None]
        if len(layers) != 1:
            continue
        p, where = layers[0], f"worksheet '{ws.get('name')}'"
        if p.get("x-axis-name") and len(panes) > 1:
            issues.append(Issue("panes", where, f"pane {p.get('id')} on axis {p.get('x-axis-name')} is the only layer "
                                                f"next to the default pane: Desktop drops the default pane and the "
                                                f"x-axis-name on save (decisions/099)"))
        elif _pane_width(p) is not None:
            issues.append(Issue("panes", where, f"the sheet's only pane {p.get('id')} has a width: Desktop drops it on "
                                                f"save, the pane fills the sheet (decisions/099)"))
    return issues


def check_registry_widths(root):
    """A registry (panes with minwidth / maxwidth) is no narrower than Desktop draws it (decisions/064):
    - its panes are equal: Desktop draws them so whatever the widths say, and the column titles above stand on the
      widths written here;
    - each pane, in its dashboard zone after the margins and the row headers, is at least REGISTRY_PANE_MIN_PX:
      Desktop widens a narrower one, the sheet scrolls sideways and its numbers are cut without '..';
    - each column title (a one-line text zone right above the sheet) fits its zone: else Desktop shows 'Sales C..'.
    The numbers of each column are checked when the builder sizes it (registry.check_widths); here only what the XML
    alone tells."""
    from .design import REGISTRY_PANE_MIN_PX, TITLE_PAD_PX, text_px
    issues = []
    sheets = {}
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        widths = [int(f.get("value")) for pane in table.iterfind("panes/pane")
                  for f in pane.iterfind("style/style-rule[@element='pane']/format[@attr='maxwidth']")]
        n = registry_columns(table)  # a one-column registry has no width: its pane fills the sheet (099)
        if not n:
            continue
        where = f"worksheet '{ws.get('name')}'"
        if len(set(widths)) > 1:
            issues.append(Issue("registry", where, f"column widths {widths} differ: Desktop draws the panes of one "
                                                   f"sheet equally wide, the titles above would stand off their "
                                                   f"columns"))
        headers = sum(int(f.get("value")) for f in table.iterfind("style/style-rule[@element='header']"
                                                                     "/format[@attr='width']"))
        sheets[ws.get("name")] = (headers, n)
    for db in root.iter("dashboard"):
        width = int(db.find("size").get("maxwidth"))
        zones = list(db.find("zones").iter("zone"))
        for z in zones:
            if z.get("name") not in sheets or z.get("type-v2"):
                continue
            headers, n = sheets[z.get("name")]
            m = _margins(_style(z))
            x, y, w, _ = _box(z)
            px = (round(w * width / FULL) - (m["left"] or 0) - (m["right"] or 0) - headers) // n
            where = f"dashboard '{db.get('name')}' registry '{z.get('name')}'"
            if px < REGISTRY_PANE_MIN_PX:
                issues.append(Issue("registry", where, f"{px}px per column: Desktop widens a pane narrower than "
                                                       f"{REGISTRY_PANE_MIN_PX}px, the sheet scrolls sideways and its "
                                                       f"numbers are cut"))
            for t in zones:  # the column titles: one-line text zones standing right on the sheet
                tx, ty, tw, th = _box(t) if t.get("type-v2") == "text" else (0, 0, 0, 0)
                if not tw or ty + th != y or tx < x or tx + tw > x + w:
                    continue
                pad = int(_style(t).get("padding", 0))  # a title on a band: its padding each side (079)
                for run in t.iterfind("formatted-text/run"):
                    need = text_px(run.text or "", int(run.get("fontsize", "9")), run.get("bold") == "true") \
                        + TITLE_PAD_PX
                    have = round(tw * width / FULL) - 2 * pad
                    if need > have:
                        issues.append(Issue("registry", where, f"column title '{run.text}' needs {need}px, its zone "
                                                               f"is {have}px: Desktop cuts it to '..'"))
    return issues


def check_text_fill(root):
    """A text zone on its own fill (a registry's header band, decisions/079) reads: each run's color has a WCAG
    contrast of at least TEXT_FILL_CONTRAST with the fill (design-rules C8). A run without a color is Desktop's
    default black."""
    from .design import MIN_CONTRAST as TEXT_FILL_CONTRAST
    from .shell import contrast
    issues = []
    for db in root.iter("dashboard"):
        for z in db.find("zones").iter("zone"):
            fill = _style(z).get("background-color")
            if z.get("type-v2") != "text" or not fill:
                continue
            for run in z.iterfind("formatted-text/run"):
                fg = run.get("fontcolor", "#000000")
                ratio = contrast(fg, fill)
                if (run.text or "").strip() and ratio < TEXT_FILL_CONTRAST:
                    issues.append(Issue("contrast", f"dashboard '{db.get('name')}' zone {z.get('id')}",
                                        f"text '{run.text.strip()}' {fg} on its fill {fill} has contrast "
                                        f"{ratio:.1f}:1 (min {TEXT_FILL_CONTRAST})"))
    return issues


def check_registry_inside(root):
    """A registry bar with its value inside in white (bar_inside) holds only the values that fit (decisions/077):
    Desktop clips a label inside a bar at the bar's end, so a short bar showed '7(' of 7%. The white label shows a
    calc that keeps a value only from a share of WINDOW_MAX up, and a second layer of the same axis (x-index 1) labels
    the rest outside."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        panes = list(table.iterfind("panes/pane"))
        if not registry_columns(table):
            continue  # not a registry
        formulas = {c.get("name"): c.find("calculation").get("formula", "") for c in ws.iter("column")
                    if c.find("calculation") is not None}
        for p in panes:
            if p.find("mark[@class='Bar']") is None:
                continue
            white = [r for r in p.iterfind("customized-label/formatted-text/run")
                     if (r.get("fontcolor") or "").lower() == "#ffffff"]
            for ds, name in REF.findall(" ".join(r.text or "" for r in white)):
                if "WINDOW_MAX(" not in formulas.get(_dual_column(f"[{ds}].{name}"), ""):
                    issues.append(Issue("registry", where, f"pane {p.get('id')}: white label {name} on a bar shows "
                                                           f"every value: Desktop clips it at a short bar's end "
                                                           f"(the inside / outside calcs, decisions/077)"))
            if white and not any(o.get("x-axis-name") == p.get("x-axis-name") and o.get("x-index") == "1"
                                 and o.find("customized-label") is not None for o in panes):
                issues.append(Issue("registry", where, f"pane {p.get('id')}: a bar with its value inside has no "
                                                       f"second layer (x-index 1) labelling the short bars outside "
                                                       f"(decisions/077)"))
    return issues


def check_registry_pill(root):
    """A registry pill (decisions/096: a pane whose cells are centred vertically) is its level's label on a bar colored
    by that level: its pane has the label (text) and the color on one discrete field, and the datasource holds that
    field's palette map and column-instance - else Desktop paints a white bar or its default palette."""
    issues = []
    datasources = {ds.get("name"): ds for ds in root.find("datasources").findall("datasource")}
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        if not registry_columns(table):
            continue
        for pane in table.iterfind("panes/pane"):
            if pane.find("style/style-rule[@element='cell']/format[@attr='vertical-align']") is None:
                continue
            where = f"worksheet '{ws.get('name')}' pane {pane.get('id')}"
            color, text = pane.find("encodings/color"), pane.find("encodings/text")
            if color is None or text is None or color.get("column") != text.get("column"):
                issues.append(Issue("registry", where, "pill has no label and color on one field"))
                continue
            m = REF.match(color.get("column"))
            ds = datasources.get(m.group(1)) if m else None
            inst = m.group(2) if m else ""
            if ds is None or inst not in _flag_maps(ds):
                issues.append(Issue("registry", where, "pill color has no palette map in its datasource: Desktop "
                                                       "paints its default palette"))
            elif not ds.findall(f"column-instance[@name='{inst}']"):
                issues.append(Issue("registry", where, "pill color has a palette map but no column-instance: Desktop "
                                                       "drops the map"))
    return issues


def check_registry_spark_line(root):
    """A registry's line spark (decisions/153): a sheet '<registry> · <column>' whose measure axis has an independent
    range per row. Its rows stand level with the registry's, so it repeats the registry's row dimension and sort (else
    each line sits beside another row's name); its dot is folded onto the line's axis, synchronized (else the last
    period floats on a scale of its own); its periods are a filter (else the line runs over all the data); the
    axes and the row names hidden; its panes as tall as a registry row."""
    issues = []
    sheets = {ws.get("name"): ws for ws in root.iter("worksheet")}
    for name, ws in sheets.items():
        table = ws.find("table")
        axis = table.find("style/style-rule[@element='axis']")
        line = None if axis is None else axis.find("encoding[@range-type='independent']")
        reg = next((sheets[n] for n in sheets if name.startswith(n + " · ")), None)
        if line is None or reg is None or not registry_columns(reg.find("table")):
            continue
        where = f"worksheet '{name}'"
        m = line.get("field")
        rows = table.findtext("rows") or ""
        reg_rows = (reg.find("table").findtext("rows") or "").strip("()")
        if not rows.startswith(f"({reg_rows} * ({m} + "):
            issues.append(Issue("registry", where, f"line spark rows '{rows}' are not the registry's row dimension "
                                                   f"'{reg_rows}' * (measure + last)"))
            continue
        last = rows[len(f"({reg_rows} * ({m} + "):].rstrip(")")
        fold = axis.find(f"encoding[@field='{last}'][@fold='true']")
        if fold is None or fold.get("synchronized") != "true":
            issues.append(Issue("registry", where, "the last period's dot is not on the line's axis (fold, "
                                                   "synchronized): it floats on a scale of its own"))
        hidden = {f.get("field") for f in axis.findall("format[@attr='display'][@value='false']")}
        cols = table.findtext("cols") or ""
        for f in (m, last, cols):
            if f not in hidden:
                issues.append(Issue("registry", where, f"axis {f} shown: a spark has no axes"))
        if table.find(f"style/style-rule[@element='label']/format[@attr='display'][@field='{reg_rows}']"
                      "[@value='false']") is None:
            issues.append(Issue("registry", where, f"row names {reg_rows} shown: the registry names the rows"))
        view = table.find("view")
        if not any(g.get("member") == "true" for f in view.findall("filter[@class='categorical']")
                   for g in f.iter("groupfilter")):
            issues.append(Issue("registry", where, "no periods filter: the line runs over all the data"))

        def sort(v):
            s = v.find("computed-sort")
            return None if s is None else (s.get("column"), s.get("direction"), s.get("using"))
        if sort(view) != sort(reg.find("table/view")):
            issues.append(Issue("registry", where, f"sort {sort(view)} is not the registry's "
                                                   f"{sort(reg.find('table/view'))}: lines beside other rows' names"))
        cell = reg.find(f"table/style/style-rule[@element='cell']/format[@attr='height'][@field='{reg_rows}']")
        row_px = cell.get("value") if cell is not None else str(REGISTRY_ROW_PX)
        for pane in table.iterfind("panes/pane[@id]"):
            h = pane.find("style/style-rule[@element='pane']/format[@attr='maxheight']")
            if h is None or h.get("value") != row_px:
                issues.append(Issue("registry", where, f"pane {pane.get('id')} height "
                                                       f"{None if h is None else h.get('value')} is not the "
                                                       f"registry's row {row_px}px: rows drift apart"))
    return issues


def check_registry_string_text(root):
    """A registry column's text that is a string calc (a spark's glyphs, a pill's level) is a discrete instance
    ([usr:...:nk]): Desktop leaves a :qk one empty - the whole registry draws no rows (decisions/096)."""
    issues = []
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        if not registry_columns(table):
            continue
        dep = table.find("view/datasource-dependencies")
        if dep is None:
            continue
        strings = {c.get("name") for c in dep.findall("column") if c.get("datatype") == "string"}
        # COUNT / COUNTD of a string field is a number, not a string (acceptance/echarts: [cnt:Order ID:qk])
        quant = {ci.get("name"): ci.get("column") for ci in dep.findall("column-instance")
                 if ci.get("derivation") not in ("Count", "CountD")}
        for pane in table.iterfind("panes/pane"):
            for text in pane.iterfind("encodings/text"):
                m = REF.match(text.get("column") or "")
                if m and m.group(2).endswith(":qk]") and quant.get(m.group(2)) in strings:
                    issues.append(Issue("registry", f"worksheet '{ws.get('name')}' pane {pane.get('id')}",
                                        f"the text {m.group(2)} is a string calc as a quantitative instance: "
                                        f"Desktop draws no rows (it must be :nk)"))
    return issues


def check_registry_total(root):
    """A registry bar under a total row (decisions/081) is 0 on the total, so the total's number must come from a
    label: some text of the column's panes is not guarded to the rows ('IF <guard> AND/THEN ...' shows nothing on a
    total), and no white label shows on the total (white on a 0 bar or past a short total bar is not seen)."""
    issues, formulas = [], _calc_formulas(root)
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        if not (table.find("rows") is not None and table.find("rows").get("total") == "true"
                or table.find("subtotals") is not None):
            continue
        dims = _row_dims(table)
        guard = row_guard(dims) if dims else None

        def formula(ref):
            m = REF.fullmatch(ref or "")
            return formulas.get((m.group(1), _dual_column(ref)), "") if m else ""

        def row_only(ref):
            f = formula(ref)
            return bool(guard) and (f.startswith(f"IF {guard} THEN ") or f.startswith(f"IF {guard} AND "))
        panes = list(table.iterfind("panes/pane"))
        cols = (table.findtext("cols") or "").strip() if _single_registry(table) else None

        def axis_of(p):  # a one-column registry's pane names no axis: it is the one on Columns (decisions/099)
            return p.get("x-axis-name") or cols
        for axis in dict.fromkeys(axis_of(p) for p in panes if axis_of(p)):
            if not _row_guarded_bar(formula(axis), dims):
                continue
            mine = [p for p in panes if axis_of(p) == axis]
            texts = [e.get("column") for p in mine for e in p.iterfind("encodings/text")]
            if not texts or all(row_only(t) for t in texts):
                issues.append(Issue("totals", where, f"the bar {axis} is 0 on the total row and no label of its "
                                                     f"column shows the total's number (decisions/081)"))
            for p in mine:
                if p.get("x-index") == "1" and not all(row_only(e.get("column"))
                                                       for e in p.iterfind("encodings/text")):
                    issues.append(Issue("totals", where, f"pane {p.get('id')}: the total's number on the second layer "
                                                         f"(labels outside the bars): Desktop keeps room for it right "
                                                         f"of every bar and shortens them all (decisions/081)"))
                for r in p.iterfind("customized-label/formatted-text/run"):
                    if (r.get("fontcolor") or "").lower() != "#ffffff":
                        continue
                    for ds, name in REF.findall(r.text or ""):
                        if not row_only(f"[{ds}].{name}"):
                            issues.append(Issue("totals", where, f"pane {p.get('id')}: white label {name} shows on "
                                                                 f"the total row, where the bar is 0 or short "
                                                                 f"(guard it to the rows, decisions/081)"))
    return issues


def _on_sheet(table):
    """References on the sheet's rows, columns and pane encodings."""
    refs = {f"[{d}].{n}" for d, n in _shelf_refs(table)}
    return refs | {f"[{d}].{n}" for enc in table.iterfind("panes/pane/encodings/*")
                   for d, n in REF.findall(enc.get("column", ""))}


def _table_calc_key(ci):
    """The compute-using of a column-instance: (ordering-type, fields) of its <table-calc>, None without one."""
    tc = ci.find("table-calc") if ci is not None else None
    if tc is None:
        return None
    return tc.get("ordering-type"), tuple(f for f in [tc.get("ordering-field")] + [o.get("field") for o in
                                                                                   tc.iter("order")] if f)


def check_measure_values(root):
    """[Multiple Values] on a shelf comes with a Measure Names filter: without it Desktop puts every measure of the
    data on the axis (a registry track would stack them all, decisions/039). A Measure Names palette maps a table calc
    measure through a datasource column-instance with the sheet's compute-using: an instance without it is the default
    (Rows) one, and Desktop renames the sheet's to [...:qk:1], which the palette does not map (decisions/065)."""
    issues = []
    datasources = {ds.get("name"): ds for ds in root.find("datasources").findall("datasource")}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        if not any(n == "[Multiple Values]" for _, n in _shelf_refs(table)):
            continue
        filters = [f for f in table.iterfind("view/filter") if f.get("column", "").endswith("[:Measure Names]")]
        if not filters:
            issues.append(Issue("measures", where, "Measure Values on a shelf without a Measure Names filter"))
            continue
        deps = {ci.get("name"): ci for ci in table.iterfind("view/datasource-dependencies/column-instance")}
        for g in filters[0].iter("groupfilter"):
            m = REF.fullmatch((g.get("member") or "").strip('"'))
            if not m or _table_calc_key(deps.get(m.group(2))) is None:
                continue
            ds = datasources.get(m.group(1))
            maps = ds.iterfind("style/style-rule[@element='mark']/encoding[@attr='color']"
                               "[@field='[:Measure Names]']/map/bucket") if ds is not None else []
            if f'"{m.group(0)}"' not in {b.text for b in maps}:
                continue
            if _table_calc_key(ds.find(f"column-instance[@name='{m.group(2)}']")) != _table_calc_key(deps[m.group(2)]):
                issues.append(Issue("measures", where, f"{m.group(2)} in the Measure Names palette has no "
                                                       f"column-instance with the sheet's compute-using in the "
                                                       f"datasource: Desktop renames it to :qk:1 and paints its "
                                                       f"default colors (decisions/065)"))
    return issues


# ---- continuous color scales (decisions/041) ------------------------------------------------------------------
HEX_COLOR = re.compile(r"#[0-9a-f]{6}")
INTERPOLATED = ("interpolated", "custom-interpolated")


def _color_scales(root):
    """(worksheet, encoding, {attr: float | None | 'bad'}) of each continuous color scale in a worksheet style."""
    for ws in root.iter("worksheet"):
        for e in ws.findall("table/style/style-rule[@element='mark']/encoding[@attr='color']"):
            if e.get("type") not in INTERPOLATED:
                continue
            nums = {}
            for k in ("min", "max", "center"):
                try:
                    nums[k] = None if e.get(k) is None else float(e.get(k))
                except ValueError:
                    nums[k] = "bad"
            yield ws, e, nums


def check_color_scales(root):
    """A continuous color scale is drawn: its measure is on the sheet's Color (else Desktop drops the scale and
    draws its default palette), its colors are #rrggbb, a diverging scale has a center inside its range, min is below
    max."""
    issues = []
    for ws, e, nums in _color_scales(root):
        where = f"worksheet '{ws.get('name')}'"
        on_color = {c.get("column") for c in ws.findall("table/panes/pane/encodings/color")}
        if e.get("field") not in on_color:
            issues.append(Issue("colors", where, f"color scale of {e.get('field')}, which is not on Color"))
        bad = sorted(k for k, v in nums.items() if v == "bad")
        if bad:
            issues.append(Issue("colors", where, f"color scale {bad} is not a number"))
            continue
        pal = e.find("color-palette")
        if e.get("type") == "custom-interpolated":
            colors = [c.text or "" for c in pal.findall("color")] if pal is not None else []
            if len(colors) < 2 or not all(HEX_COLOR.fullmatch(c) for c in colors):
                issues.append(Issue("colors", where, f"custom color scale needs #rrggbb colors, got {colors}"))
        lo, hi, ctr = nums["min"], nums["max"], nums["center"]
        if pal is not None and pal.get("type") == "ordered-diverging" and ctr is None:
            issues.append(Issue("colors", where, "diverging color scale without a center: its neutral color "
                                                 "lands at the data's midpoint, not at a value that means 'even'"))
        if lo is not None and hi is not None and lo >= hi:
            issues.append(Issue("colors", where, f"color scale min {lo} is not below max {hi}"))
        if ctr is not None and ((lo is not None and ctr <= lo) or (hi is not None and ctr >= hi)):
            issues.append(Issue("colors", where, f"color scale center {ctr} is outside its range {lo}..{hi}"))
    return issues


def check_color_ranges(root, expected):
    """A fixed range or center of a color scale lies within the numbers the sheet shows (expected.py, computed from
    the data, not the XML): a range past the data leaves its ends unused and flattens the marks into one shade; a
    center outside it draws a diverging scale one-sided."""
    from .maps import color_record
    issues = []
    for ws, e, nums in _color_scales(root):
        name = ws.get("name")  # a map colored by a second measure: that measure's numbers (decisions/137)
        values = [v for v in expected.get(color_record(name), expected.get(name, {})).values()
                  if isinstance(v, (int, float))]
        if not values or "bad" in nums.values():
            continue
        lo, hi = min(values), max(values)
        tol = 1e-9 * max(1.0, abs(lo), abs(hi))
        where = f"worksheet '{ws.get('name')}'"
        for k, v in nums.items():
            if v is not None and not lo - tol <= v <= hi + tol:
                issues.append(Issue("colors", where, f"color scale {k} {v:g} is outside the marks' values "
                                                     f"{lo:g}..{hi:g}"))
    return issues


# ---- entry point -------------------------------------------------------------------------
# ---- interactivity (decisions/042) ---------------------------------------------------------------------------------
PARAM_EQ = re.compile(r'\[Parameters\]\.(\[[^\[\]]+\]) = ("[^"]*")')  # a view switch's flag calc
STRING_LITERAL = re.compile(r'"[^"]*"')
PARAM_ACTION_FLAGS = ("ParameterAction", "ParameterActionClearSelection")
DZV_FLAGS = ("DatagraphCoreV1", "DatagraphNodeDashboardZoneVisibilityV1", "DatagraphNodeSingleValueFieldV1",
             "ZoneVisibilityControl")
PARAM_CARD_MODES = ("compact", "slider", "list", "type_in", "datetime")  # Desktop's paramctrl modes in the references; datetime: a date range (057)


def _param_columns(root):
    return {c.get("name"): c for ds in root.find("datasources") if ds.get("name") == "Parameters"
            for c in ds.findall("column")}


def _calc_columns(root):
    """{(datasource, '[Calculation_…]'): column} of every calculated field."""
    return {(ds.get("name"), c.get("name")): c for ds in root.find("datasources") for c in ds.findall("column")
            if c.find("calculation") is not None}


def _set_by_user(root):
    """Parameters the user can change: a card on a dashboard or the target of a parameter action."""
    out = {n for z in root.iter("zone") if z.get("type-v2") == "paramctrl" for n in PARAM_REF.findall(z.get("param", ""))}
    out |= {n for a in root.iter("edit-parameter-action") for p in a.iter("param")
            if p.get("name") == "target-parameter" for n in PARAM_REF.findall(p.get("value", ""))}
    return out


def _switched(root):
    """Shared filters on a boolean calc of parameters the user sets (a period switch): {filter column: params}."""
    calcs, user, out = _calc_columns(root), _set_by_user(root), {}
    for sv in root.iter("shared-view"):
        for d in sv.findall("datasource-dependencies"):
            for ci in d.findall("column-instance"):
                col = calcs.get((d.get("datasource"), ci.get("column")))
                if col is None or col.get("datatype") != "boolean":
                    continue
                used = set(PARAM_REF.findall(col.find("calculation").get("formula", "")))
                if used and used <= user:
                    out[f"[{d.get('datasource')}].{ci.get('name')}"] = used
    return out


def _dzv_zones(root):
    """{dashboard simple-id: zone ids} under dynamic zone visibility."""
    out = {}
    for n in root.iter("dashboard-zone-visibility-node"):
        out.setdefault(n.get("dashboard-identifier"), set()).add(n.get("zone-id"))
    return out


def _members(p):
    return [m.get("value") for m in p.findall("members/member")]


def check_interactivity(root):
    """Parameter actions: the target parameter is declared; the source sheet is on the source dashboard and carries
    the source field on its marks; a constant source field is one of the parameter's values (a button that sets a
    value the list does not have). Zone visibility: the node names a zone of a dashboard by its simple-id, a boolean
    field drives it, a flag [Parameter] = "value" names a value of the parameter (else the zone never shows), and
    hidden-by-user agrees with the value at open. Parameter cards in a mode Desktop writes; the manifest flags."""
    issues = []
    params, calcs = _param_columns(root), _calc_columns(root)
    sheets = {ws.get("name"): ws for ws in root.iter("worksheet")}
    on_dash = {d.get("name"): {z.get("name") for z in d.find("zones").iter("zone")
                               if "type-v2" not in z.attrib and z.get("name")} for d in root.iter("dashboard")}
    manifest = root.find("document-format-change-manifest")
    flags = {e.tag for e in manifest} if manifest is not None else set()
    for z in root.iter("zone"):
        if z.get("type-v2") == "paramctrl" and z.get("mode") not in PARAM_CARD_MODES:
            issues.append(Issue("interact", f"zone {z.get('id')}", f"parameter card mode {z.get('mode')!r} is not "
                                                                   f"one of {PARAM_CARD_MODES}"))
    acts = list(root.iter("edit-parameter-action"))
    if acts:
        issues += [Issue("interact", "manifest", f"parameter actions without the {f} flag")
                   for f in PARAM_ACTION_FLAGS if f not in flags]
    for a in acts:
        where = f"parameter action '{a.get('caption')}'"
        ps = {p.get("name"): p.get("value") for p in a.iter("param")}
        m = PARAM_REF.fullmatch(ps.get("target-parameter", ""))
        if not m or m.group(1) not in params:
            issues.append(Issue("interact", where, f"target parameter {ps.get('target-parameter')} is not declared"))
            continue
        p = params[m.group(1)]
        src = a.find("source")
        dash, name = src.get("dashboard"), src.get("worksheet")
        if dash not in on_dash or name not in on_dash[dash]:
            issues.append(Issue("interact", where, f"source sheet '{name}' is not on dashboard '{dash}'"))
            continue
        table = sheets[name].find("table")
        declared = {(d.get("datasource"), ci.get("name")): ci.get("column")
                    for d in table.find("view").findall("datasource-dependencies") for ci in d.findall("column-instance")}
        shown = set(_refs_in(table.find("panes"))) if table.find("panes") is not None else set()
        for shelf in ("rows", "cols"):
            shown |= set(REF.findall(table.findtext(shelf) or ""))
        fm = INSTANCE.fullmatch(ps.get("source-field", ""))
        key = (fm.group(1), fm.group(2)) if fm else None
        if key not in declared or key not in shown:
            issues.append(Issue("interact", where, f"source field {ps.get('source-field')} is not on the marks of "
                                                   f"sheet '{name}': a click there has no value to set"))
            continue
        col = calcs.get((key[0], declared[key]))
        formula = col.find("calculation").get("formula") if col is not None else ""
        if STRING_LITERAL.fullmatch(formula or "") and p.get("param-domain-type") == "list" and \
                formula not in _members(p):
            issues.append(Issue("interact", where, f"sets {m.group(1)} ('{p.get('caption')}') to {formula}, which "
                                                   f"is not one of its values {_members(p)}"))
    graph = root.find("datagraph/graph")
    nodes = graph.findall("nodes/dashboard-zone-visibility-node") if graph is not None else []
    if nodes:
        issues += [Issue("interact", "manifest", f"zone visibility without the {f} flag")
                   for f in DZV_FLAGS if f not in flags]
    dashes = {d.find("simple-id").get("uuid"): d for d in root.iter("dashboard") if d.find("simple-id") is not None}
    fields = {n.get("value-output-guid"): n for n in graph.iter("single-value-field-node")} if nodes else {}
    edges = {e.get("to"): e.get("from") for e in graph.iter("edge")} if nodes else {}
    for n in nodes:
        where = f"zone visibility of zone {n.get('zone-id')}"
        db = dashes.get(n.get("dashboard-identifier"))
        if db is None:
            issues.append(Issue("interact", where, f"dashboard {n.get('dashboard-identifier')} is no dashboard's "
                                                   f"simple-id"))
            continue
        zone = next((z for z in db.find("zones").iter("zone") if z.get("id") == n.get("zone-id")), None)
        if zone is None:
            issues.append(Issue("interact", where, f"dashboard '{db.get('name')}' has no zone {n.get('zone-id')}"))
            continue
        field = fields.get(edges.get(n.get("visibility-input-guid")))
        if field is None:
            issues.append(Issue("interact", where, "no field drives its visibility (no edge from a field node)"))
            continue
        fname, visible = field.get("fieldname", ""), None
        pm = re.fullmatch(r"\[Parameters\]\.(\[[^\[\]]+\])", fname)
        fm = INSTANCE.fullmatch(fname)
        col = params.get(pm.group(1)) if pm else calcs.get((fm.group(1), fm.group(2))) if fm else None
        if col is None:
            issues.append(Issue("interact", where, f"field {fname} is neither a parameter nor a calculated field"))
            continue
        if col.get("datatype") != "boolean":
            issues.append(Issue("interact", where, f"field {fname} is {col.get('datatype')}; visibility needs a "
                                                   f"boolean"))
            continue
        if pm:
            visible = col.get("value") == "true"
        eq = PARAM_EQ.fullmatch(col.find("calculation").get("formula", "")) if not pm else None
        if eq:
            p = params.get(eq.group(1))
            if p is None:
                issues.append(Issue("interact", where, f"field {fname} compares undeclared parameter {eq.group(1)}"))
                continue
            if p.get("param-domain-type") == "list" and eq.group(2) not in _members(p):
                issues.append(Issue("interact", where, f"shown when {eq.group(1)} ('{p.get('caption')}') is "
                                                       f"{eq.group(2)}, which is not one of its values "
                                                       f"{_members(p)}: the zone never shows"))
                continue
            visible = eq.group(2) == p.get("value")
        if visible is not None and (zone.get("hidden-by-user") == "true") == visible:
            issues.append(Issue("interact", where, f"hidden-by-user is {zone.get('hidden-by-user') or 'unset'} but "
                                                   f"the field is {str(visible).lower()} when the workbook opens"))
    issues += _switch_containers(root, nodes, dashes)
    return issues


def _switch_containers(root, nodes, dashes):
    """A zone-visibility container shows or hides as a whole (decisions/082):
    - every zone in it is hidden-by-user as the container is: Desktop saves the zones of a hidden container hidden,
      and a zone hidden inside a shown one stays hidden;
    - a registry in it has its column titles in it too (text zones standing right on the sheet, decisions/064): a
      title outside every switch container stays on the dashboard when the switch hides its registry. Titles in
      another container of the switch are the other view's, drawn over the same place."""
    issues = []
    registries = {ws.get("name") for ws in root.iter("worksheet") if registry_columns(ws.find("table"))}
    by_dash = {}
    for n in nodes:
        db = dashes.get(n.get("dashboard-identifier"))
        if db is not None:
            by_dash.setdefault(db, set()).add(n.get("zone-id"))
    for db, ids in by_dash.items():
        parent = {c: p for p in db.find("zones").iter("zone") for c in p.findall("zone")}

        def container(z):
            while z is not None and z.get("id") not in ids:
                z = parent.get(z)
            return z
        zones = list(db.find("zones").iter("zone"))
        for c in (z for z in zones if z.get("id") in ids):
            hidden = c.get("hidden-by-user") == "true"
            for z in c.iter("zone"):
                if z is not c and (z.get("hidden-by-user") == "true") != hidden and container(z) is c:
                    issues.append(Issue("interact", f"dashboard '{db.get('name')}' zone {z.get('id')}",
                                        f"hidden-by-user is {z.get('hidden-by-user') or 'unset'} inside switch "
                                        f"container {c.get('id')}, which is {'hidden' if hidden else 'shown'}: a "
                                        f"view's zones show and hide together"))
            for s in (z for z in c.iter("zone") if z.get("name") in registries and not z.get("type-v2")):
                x, y, w, _ = _box(s)
                for t in zones:
                    if t.get("type-v2") != "text":
                        continue
                    tx, ty, tw, th = _box(t)
                    if ty + th != y or tx < x or tx + tw > x + w or container(t) is not None:
                        continue
                    text = "".join(r.text or "" for r in t.iterfind("formatted-text/run")).strip()
                    issues.append(Issue("interact", f"dashboard '{db.get('name')}' zone {t.get('id')}",
                                        f"column title '{text}' of registry '{s.get('name')}' is outside its switch "
                                        f"container {c.get('id')}: it stays when the switch hides the registry"))
    return issues


# ---- dual axis (decisions/044) -------------------------------------------------------------------------------------
DUAL_INSTANCE = re.compile(r"^\[[a-z0-9]+:(.+):[a-z]+\]$")  # [sum:Sales:qk] -> Sales
DUAL_SHELF_REF = re.compile(r"(?:\[[^\]]+\]\.)*\[[^\]]+\]")  # a field on a shelf: [ds].[instance], [Parameters].[P]


def _dual_column(ref):
    inst = "[" + ref.rsplit("].[", 1)[-1].lstrip("[")
    m = DUAL_INSTANCE.match(inst)
    return f"[{m.group(1)}]" if m else inst


def check_dual_axis(root):
    """Each fold (axis encoding fold='true') is a complete dual axis, as Desktop writes one (SuperMart, ER Operation,
    E-Commerce): '(A + B)' on its shelf, a pane per layer naming its axis (the second occurrence of A with index 1),
    each layer with its own mark class; one unit (the same field, or the same explicit number format) on both
    axes means synchronized ones; a donut (two Pie layers) shows its total on the inner layer, its ring inside its
    panel; a combo's bar values at their ends, a lollipop's clear of its circle (_dual_labels)."""
    issues, rings = [], {}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        formats_of = {c.get("name"): c.get("default-format") for c in ws.iter("column")}
        for enc in table.iterfind("style/style-rule[@element='axis']/encoding[@fold='true']"):
            scope, xy = enc.get("scope"), "y" if enc.get("scope") == "rows" else "x"
            field = enc.get("field", "")
            # the shelf's fields in order ('(A + (B + C))' too, Reports Usage); class = the folded field's occurrence
            refs = DUAL_SHELF_REF.findall(table.findtext(scope) or "")
            at = [i for i, r in enumerate(refs) if r == field]
            k = int(enc.get("class", "0")) if enc.get("class", "0").isdigit() else -1
            if not 0 <= k < len(at) or at[k] == 0:
                issues.append(Issue("dual-axis", where, f"fold of {field} (class {enc.get('class')}) has no measure "
                                                        f"before it on {scope} to fold onto ('(A + B)')"))
                continue
            first = refs[at[k] - 1]
            same = first == field
            layers = []
            n_first = refs[:at[k] - 1].count(first)  # a pane names an occurrence after the first by its index
            for ref, index in ((first, str(n_first) if n_first else None), (field, str(k) if k else None)):
                pane = next((p for p in table.iterfind("panes/pane") if p.get(f"{xy}-axis-name") == ref
                             and p.get(f"{xy}-index") == index), None)
                if pane is None:
                    issues.append(Issue("dual-axis", where, f"no pane for the layer on {ref}"
                                                            f"{' (index 1)' if index else ''}"))
                    continue
                mark = pane.find("mark")
                if mark is None or mark.get("class", "Automatic") == "Automatic":
                    issues.append(Issue("dual-axis", where, f"layer pane {pane.get('id')} has no mark class of its "
                                                            f"own (Automatic draws both layers alike)"))
                layers.append(pane)
            cols = [_dual_column(r) for r in (first, field)]
            fmts = [formats_of.get(c) for c in cols]
            one_unit = same or cols[0] == cols[1] or (fmts[0] is not None and fmts[0] == fmts[1])
            if one_unit and enc.get("synchronized") != "true":
                issues.append(Issue("dual-axis", where, f"both axes measure one unit ({', '.join(cols)}) but are not "
                                                        f"synchronized: the second layer reads against another scale"))
            if len(layers) == 2:
                issues += _dual_labels(where, layers, same)
            if len(layers) == 2 and all(p.find("mark[@class='Pie']") is not None for p in layers):
                inner = layers[1]
                if inner.find("encodings/text") is None or inner.find("customized-label") is None:
                    issues.append(Issue("dual-axis", where, "a donut without its total: the inner layer needs the "
                                                            "measure on Text and a label"))
                size = layers[0].find("style/style-rule[@element='mark']/format[@attr='size']")
                if layers[0].find("mark-sizing[@mark-sizing-setting='marks-scaling-off']") is not None \
                        and size is not None:
                    rings[ws.get("name")] = float(size.get("value")) * PIE_PX_PER_SIZE
    return issues + _rings_fit(root, rings)


def _dual_labels(where, layers, same):
    """A combo's bar values at the bars' ends (decisions/165, the user's choice over 084's 'inside at the base':
    cell vertical-align top, or none, Desktop's default above the bar); a lollipop's circle unlabelled, its value a
    header (decisions/084, reference 'Lollipop': the label of a circle at the pane's edge stands on the circle)."""
    def labelled(p):
        return p.find("style/style-rule[@element='mark']/format[@attr='mark-labels-show'][@value='true']") is not None

    marks = [p.find("mark").get("class") if p.find("mark") is not None else None for p in layers]
    bar, other = (layers[0], marks[1]) if marks[0] == "Bar" else (layers[1], marks[0]) if marks[1] == "Bar" else \
        (None, None)
    if bar is None:
        return []
    if other == "Line" and not same and labelled(bar):
        align = bar.find("style/style-rule[@element='cell']/format[@attr='vertical-align']")
        if align is not None and align.get("value") != "top":
            return [Issue("dual-axis", where, f"the bars' values stand off their ends (cell vertical-align "
                                              f"{align.get('value')}): label them at the end (vertical-align top, "
                                              f"decisions/165)")]
    if other == "Circle" and same:
        circle = layers[1] if bar is layers[0] else layers[0]
        if labelled(circle):
            return [Issue("dual-axis", where, "a lollipop's circle is labelled: at the pane's edge its label stands "
                                              "on the circle; show the value as a header (rows Dim / M:ok)")]
    return []


# ---- Pareto (decisions/157) ----------------------------------------------------------------------------------------
PARETO_RUN = re.compile(r"^\s*RUNNING_SUM\s*\((.+)\)\s*/\s*TOTAL\s*\(\1\)\s*$", re.I | re.S)
PARETO_VITAL = re.compile(r"^\s*RUNNING_SUM\s*\((.+)\)\s*-\s*\1\s*<\s*(" + NUMBER.pattern + r")\s*\*\s*TOTAL\s*\(\1\)\s*$",
                          re.I | re.S)


def _squash(code):
    return re.sub(r"\s+", "", code)


def check_pareto(root):
    """A running share on a dual axis (RUNNING_SUM(X) / TOTAL(X), reference 'Advanced Pareto Chart') is a Pareto's line
    over bars of X: the bars are X, the members sorted by X descending (the running sum follows the sort: ascending
    or unsorted, the line is not the 80/20 curve), the share computed along the dimension on the other shelf, a
    threshold line a share between 0 and 1, and the vital flag on the bars' color at the same threshold."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        deps = {ci.get("name"): ci for ci in table.iterfind("view/datasource-dependencies/column-instance")}
        cols = {c.get("name"): c for c in table.iterfind("view/datasource-dependencies/column")}
        derivations = {n.split(":")[0][1:]: ci.get("derivation") for n, ci in deps.items()}

        def formula(ref):
            ci = deps.get("[" + ref.rsplit("].[", 1)[-1].lstrip("["))
            c = cols.get(ci.get("column")) if ci is not None else None
            calc = c.find("calculation") if c is not None else None
            return _formula_code(calc.get("formula") or "") if calc is not None else None

        for enc in table.iterfind("style/style-rule[@element='axis']/encoding[@fold='true']"):
            run_ref, scope = enc.get("field", ""), enc.get("scope")
            m = PARETO_RUN.match(formula(run_ref) or "")
            if not m:
                continue
            x = _squash(m.group(1))
            refs = DUAL_SHELF_REF.findall(table.findtext(scope) or "")
            bars = refs[0] if refs else ""
            inst = "[" + bars.rsplit("].[", 1)[-1].lstrip("[")
            if _squash(_instance_expr(inst, derivations) or "") != x:
                issues.append(Issue("pareto", where, f"the running share is of {m.group(1)}, the bars show {inst}: "
                                                     f"the line does not add up the bars"))
            other = table.findtext("cols" if scope == "rows" else "rows") or ""
            dims = DUAL_SHELF_REF.findall(other)
            dim = dims[-1] if dims else None
            sort = next((el for el in table.iterfind("view/computed-sort") if el.get("column") == dim), None)
            sort = sort if sort is not None else next(
                (el for el in table.iterfind("view/shelf-sorts/shelf-sort-v2") if el.get("dimension-to-sort") == dim),
                None)
            using = None if sort is None else sort.get("using") or sort.get("measure-to-sort-by")
            if sort is None or sort.get("direction") != "DESC" or using != bars:
                issues.append(Issue("pareto", where, f"the members are not sorted by the bars ({inst}) descending: "
                                                     f"the running share is a Pareto curve only largest first"))
            run_ci = deps.get("[" + run_ref.rsplit("].[", 1)[-1].lstrip("["))
            along = [t.get("ordering-field") for t in run_ci.findall("table-calc")] if run_ci is not None else []
            if dim not in along:
                issues.append(Issue("pareto", where, f"the running share runs along {along or 'nothing'}, not along "
                                                     f"the members {dim}"))
            lines = [rl for rl in table.iter("reference-line") if rl.get("axis-column") == run_ref]
            values = []
            for rl in lines:
                try:
                    v = float(rl.get("value", ""))
                except ValueError:
                    continue
                values.append(v)
                if not 0 < v < 1:
                    issues.append(Issue("pareto", where, f"threshold line {rl.get('id')} at {rl.get('value')} on the "
                                                         f"share's axis, which runs 0..1"))
            for col in table.iterfind("panes/pane/encodings/color"):
                v = PARETO_VITAL.match(formula(col.get("column", "")) or "")
                if v and _squash(v.group(1)) == x and values and float(v.group(2)) not in values:
                    issues.append(Issue("pareto", where, f"the vital few are colored at {v.group(2)}, the threshold "
                                                         f"line is at {values[0]}"))
    return issues


def _rings_fit(root, rings):
    """A donut's ring (a fixed-size Pie, decisions/069) fits its dashboard zone after the margins: Desktop cuts a
    larger one at the pane's edges (ITSM: a 208px ring in a 132px pane)."""
    issues = []
    for db in root.iter("dashboard"):
        size = db.find("size")
        if not rings or size is None or not (size.get("maxwidth") and size.get("maxheight")):
            continue  # an automatic size: its zones have no px to check
        width, height = int(size.get("maxwidth")), int(size.get("maxheight"))
        for z in db.find("zones").iter("zone"):
            if z.get("name") not in rings or z.get("type-v2"):
                continue
            m = {s: v or 0 for s, v in _margins(_style(z)).items()}
            _, _, w, h = _box(z)
            panel = min(round(w * width / FULL) - m["left"] - m["right"], round(h * height / FULL) - m["top"]
                        - m["bottom"])
            if rings[z.get("name")] > panel:
                issues.append(Issue("dual-axis", f"dashboard '{db.get('name')}' donut '{z.get('name')}'",
                                    f"its ring is {rings[z.get('name')]:.0f}px across, the panel {panel}px: Desktop "
                                    f"cuts the ring at the panel's edges"))
    return issues


# ---- maps (decisions/046) ------------------------------------------------------------------------------------------
GEO_PLACE_ROLES = ("[Country].[Name]", "[Country].[ISO3166_2]", "[State].[Name]", "[County].[Name]",
                   "[City].[Name]")  # roles of place names
GEO_NO_POLYGON = ("[City].[Name]",)  # Tableau draws a city as a point: it has no polygon to fill
GEO_COORDS = ("[Geographical].[Latitude]", "[Geographical].[Longitude]")  # the data's own coordinates


def check_name_roles(root):
    """A data source without any geographic role gets one from Desktop on Save As for every column whose name says
    City / State / Country ... (decisions/092: ITSM's incident State, filters_v2's City): the workbook writes them."""
    from types import SimpleNamespace
    from .maps import name_role
    issues = []
    for ds in root.find("datasources"):
        if ds.get("name") == "Parameters" or any(c.get("semantic-role") for c in ds.findall("column")):
            continue
        for rec in ds.iterfind(".//metadata-record[@class='column']"):
            name, typ = rec.findtext("local-name", ""), rec.findtext("local-type", "")
            role = name_role(SimpleNamespace(name=name.strip("[]"), datatype=typ))
            if role:
                issues.append(Issue("maps", f"column {name}", f"no geographic role in its data source: Desktop gives "
                                    f"it {role} by its name on Save As; write the role"))
    return issues


def check_maps(root):
    """A place-name role sits on a text column; a sheet on the generated latitude / longitude is a map Desktop can
    draw: latitude on Rows and longitude on Columns, a field with a geographic role on its marks, a map source the
    workbook declares; a filled map (Multipolygon) has its geometry and no role without polygons (a city)."""
    issues = []
    for col in root.iter("column"):
        if col.get("semantic-role") in GEO_PLACE_ROLES and col.get("datatype") != "string":
            issues.append(Issue("maps", f"column {col.get('name')}", f"geographic role {col.get('semantic-role')} on "
                                f"a {col.get('datatype')} field: place names are text"))
        if col.get("semantic-role") in GEO_COORDS and col.get("datatype") not in NUMBER_TYPES:
            issues.append(Issue("maps", f"column {col.get('name')}", f"{col.get('semantic-role')} on a "
                                f"{col.get('datatype')} field: a coordinate is a number"))
    sources = {m.get("name") for m in root.findall("mapsources/mapsource")}
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        rows, cols = table.findtext("rows") or "", table.findtext("cols") or ""
        view = table.find("view")
        role_of = {}
        for dep in view.findall("datasource-dependencies"):
            col_role = {c.get("name"): c.get("semantic-role") for c in dep.findall("column")}
            for ci in dep.findall("column-instance"):
                if col_role.get(ci.get("column")):
                    role_of[f"[{dep.get('datasource')}].{ci.get('name')}"] = col_role[ci.get("column")]
        shelf_roles = {s: {role_of.get(f"[{d}].{i}") for d, i in REF.findall(t)} for s, t in (("rows", rows),
                                                                                             ("cols", cols))}
        coords = set(GEO_COORDS) & (shelf_roles["rows"] | shelf_roles["cols"])  # a map on the data's lat / lon
        if not coords and not any(g in rows + cols for g in (GEO_LAT, GEO_LON)):
            continue
        if coords and (GEO_COORDS[0] not in shelf_roles["rows"] or GEO_COORDS[1] not in shelf_roles["cols"]):
            issues.append(Issue("maps", where, "a map needs the latitude column on Rows and the longitude one on "
                                               "Columns"))
        if not coords and (GEO_LAT not in rows or GEO_LON not in cols):
            issues.append(Issue("maps", where, "a map needs latitude (generated) on Rows and longitude (generated) "
                                               "on Columns"))
        for pane in table.iterfind("panes/pane"):
            enc = pane.find("encodings")
            geo = [role_of[e.get("column")] for e in (enc if enc is not None else []) if e.get("column") in role_of]
            if not geo and not coords:
                issues.append(Issue("maps", where, f"pane {pane.get('id', 'default')}: no field with a geographic "
                                                   f"role on its marks; Tableau has nothing to place"))
            if pane.find("mark[@class='Multipolygon']") is not None:
                if enc is None or not any(GEO_GEOMETRY in (e.get("column") or "") for e in enc.iter("geometry")):
                    issues.append(Issue("maps", where, "filled map without its geometry (generated)"))
                for r in sorted(set(geo) & set(GEO_NO_POLYGON)):
                    issues.append(Issue("maps", where, f"filled map by {r}: Tableau has no polygons for it, "
                                                       f"only points"))
        named = {m.get("name") for m in view.findall("mapsources/mapsource")}
        if not named:
            issues.append(Issue("maps", where, "no map source in the sheet's view"))
        for n in sorted(named - sources):
            issues.append(Issue("maps", where, f"map source '{n}' is not declared in the workbook's mapsources"))
    return issues


def _measure_column(view, ref):
    """The spec field name (a calc's caption) behind a '[ds].[instance]' of the sheet's dependencies, else None."""
    for dep in view.findall("datasource-dependencies"):
        cols = {c.get("name"): c.get("caption") or c.get("name")[1:-1] for c in dep.findall("column")}
        for ci in dep.findall("column-instance"):
            if f"[{dep.get('datasource')}].{ci.get('name')}" == ref:
                return cols.get(ci.get("column"), ci.get("column")[1:-1])
    return None


def check_map_colors(root, spec):
    """A map's marks are colored as the spec asks (decisions/137): with a scale (color, or a filled map), its
    measure is on the pane's Color and is the scale's field, the palette is the map scale of maps.palette (type and
    colors, the book's accent); a symbol map without one paints its circles the book's accent; the size encoding is
    there unless size: false."""
    from . import maps, nav
    issues = []
    sheets = {ws.get("name"): ws for ws in root.iter("worksheet")}
    for s in nav.primary(spec)["sheets"]:
        ws = sheets.get(s["name"])
        if not maps.is_map(s) or ws is None:
            continue
        where, view = f"worksheet '{s['name']}'", ws.find("table/view")
        encs = ws.find("table/panes/pane/encodings")
        on = {e.tag: e.get("column") for e in (encs if encs is not None else [])}
        want = maps.color_measure(s)
        if (want is None) != ("color" not in on):
            issues.append(Issue("maps", where, f"marks {'colored' if 'color' in on else 'not colored'} by a measure; "
                                               f"the spec asks {want['field'] if want else 'the accent'}"))
            continue
        if maps.sized(s) != ("size" in on):
            issues.append(Issue("maps", where, f"size encoding {'present' if 'size' in on else 'missing'}; the spec "
                                               f"has size {maps.sized(s)}"))
        if want is None:
            mark = ws.find("table/panes/pane/style/style-rule[@element='mark']/format[@attr='mark-color']")
            if mark is None or mark.get("value") != COLOR["accent"]:
                issues.append(Issue("maps", where, f"circles {None if mark is None else mark.get('value')}, not the "
                                                   f"book's accent {COLOR['accent']}"))
            continue
        if _measure_column(view, on["color"]) != want["field"]:
            issues.append(Issue("maps", where, f"Color is {on['color']}, not the measure {want['field']}"))
        scale = ws.find(f"table/style/style-rule[@element='mark']/encoding[@attr='color'][@field='{on['color']}']")
        pal = None if scale is None else scale.find("color-palette")
        kind, colors = maps.palette(maps.color(s))
        got = None if pal is None else (pal.get("type"), [c.text for c in pal.findall("color")])
        if got != (kind, colors):
            issues.append(Issue("maps", where, f"color scale {got} is not the map's {kind} scale {colors}"))
    return issues


# ---- scatter (decisions/047) ---------------------------------------------------------------------------------------
def _instances(view):
    """{'[ds].[instance]': column-instance} of a sheet's dependencies."""
    return {f"[{dep.get('datasource')}].{ci.get('name')}": ci for dep in view.findall("datasource-dependencies")
            for ci in dep.findall("column-instance")}


def check_scatter(root):
    """Lines stand on an axis of the sheet, and a scatter has points:
    - a reference line's axis-column is a field on Rows or Columns: a line on another field has no axis to cross;
    - a trend line fits Rows over Columns: both hold a continuous field;
    - a scatter (Circle marks, one measure on Rows and one on Columns, no dimension on a shelf) has a dimension on
      its marks (NovaCart: the product on Detail); without one the sheet is a single aggregate point."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        shelves = {t: table.findtext(t) or "" for t in ("rows", "cols")}
        inst = _instances(table.find("view"))
        for rl in table.iter("reference-line"):
            axis = rl.get("axis-column", "")
            if axis and axis not in shelves["rows"] + shelves["cols"]:
                issues.append(Issue("scatter", where, f"reference line {rl.get('id')} is on {axis}, which is on "
                                                      f"neither Rows nor Columns: it has no axis to cross"))

        def continuous(text):  # any datasource name (a reference book's is not federated.*)
            return "[Multiple Values]" in text or any(r in text and ci.get("type") == "quantitative"
                                                      for r, ci in inst.items())

        if table.find("panes/pane/trendline") is not None and not (continuous(shelves["rows"])
                                                                    and continuous(shelves["cols"])):
            issues.append(Issue("scatter", where, "trend line without a continuous axis on both Rows and Columns"))
        refs = {t: [f"[{d}].{n}" for d, n in REF.findall(text)] for t, text in shelves.items()}
        measure = [len(r) == 1 and r[0] in inst and inst[r[0]].get("type") == "quantitative"
                   and not (inst[r[0]].get("derivation") or "").endswith("-Trunc") for r in refs.values()]
        if not all(measure) or table.find("panes/pane/mark[@class='Circle']") is None:
            continue
        marks = [e.get("column") for p in table.iterfind("panes/pane") for e in p.iterfind("encodings/*")]
        if not any(c in inst and inst[c].get("type") == "nominal" for c in marks):
            issues.append(Issue("scatter", where, "a measure on each axis and no dimension on the marks: the scatter "
                                                  "is one aggregate point"))
    return issues


def _geo_shown(root, tables):
    """{(datasource, '[Column]'): values} the map sheets draw at open (decisions/067): the rows of a text-file source
    (tables: _text_tables) kept by the filters of members the sheet shows, its own and the shared ones in its slices.
    A filter of another kind is not applied: more values are checked, never fewer."""
    shared, cols = {}, {}
    for sv in root.iter("shared-view"):
        shared.update({f.get("column"): f for f in sv.findall("filter")})
        cols.update({(d.get("datasource"), ci.get("name")): ci.get("column") for d in sv.findall("datasource-dependencies")
                     for ci in d.findall("column-instance")})
    out = {}
    for ws in root.iter("worksheet"):
        table, view = ws.find("table"), ws.find("table/view")
        if view is None or "[Latitude (generated)]" not in (table.findtext("rows") or ""):
            continue
        inst = cols | {(d.get("datasource"), ci.get("name")): ci.get("column")
                       for d in view.findall("datasource-dependencies") for ci in d.findall("column-instance")}
        flts = view.findall("filter") + [shared[c.text] for c in view.findall("slices/column") if c.text in shared]
        for lod in table.iter("lod"):
            m = INSTANCE.fullmatch(lod.get("column", ""))
            col = inst.get((m.group(1), m.group(2))) if m else None
            if col is None or m.group(1) not in tables or col[1:-1] not in tables[m.group(1)][0]:
                continue
            header, rows = tables[m.group(1)]
            conds = []
            for f in flts:
                fm = INSTANCE.fullmatch(f.get("column", ""))
                fcol = inst.get((fm.group(1), fm.group(2))) if fm and fm.group(1) == m.group(1) else None
                if fcol is None or fcol[1:-1] not in header:
                    continue
                kind, members, _ = _selection(f, fm.group(2))
                if kind in ("in", "out"):
                    conds.append((header.index(fcol[1:-1]), {_unquote(v) for v in members}, kind == "out"))
            i = header.index(col[1:-1])
            out.setdefault((m.group(1), col), set()).update(
                r[i] for r in rows if r[i] and all((r[j] in vals) != out_ for j, vals, out_ in conds))
    return out


def check_geo_names(root, values, tables=None):
    """Every value of a country / state field is a name Desktop's geocoding knows (a state: in the datasource's
    country context). An unknown one is left off the map ('N unknown'): the map does not show the data. values:
    _text_values (text-file sources only); tables: _text_tables, then a field on a map is checked by the values the
    map draws after its filters (_geo_shown, decisions/067). Only a field on a map: Desktop gives a role by the
    column's name too (decisions/092: ITSM's incident State), and nothing is geocoded off a map."""
    from .maps import unknown
    kinds = {"[Country].[Name]": "country", "[State].[Name]": "state"}
    issues = []
    shown = _geo_shown(root, tables) if tables else {}
    on_map = {(dep.get("datasource"), c.get("name")) for v in root.iterfind("worksheets/worksheet/table/view")
              if v.find("mapsources") is not None for dep in v.findall("datasource-dependencies")
              for c in dep.findall("column")}
    for ds in root.find("datasources"):
        ctx = ds.find("semantic-values/semantic-value[@key='[Country].[Name]']")
        country = _unquote(ctx.get("value")) if ctx is not None else None
        for col in ds.findall("column"):
            key = (ds.get("name"), col.get("name"))
            kind, data = kinds.get(col.get("semantic-role")), shown.get(key, values.get(key))
            if kind is None or data is None or key not in on_map:
                continue
            bad = unknown(kind, sorted(data), country)
            if bad:
                issues.append(Issue("maps", f"column {col.get('name')}", f"{len(bad)} value(s) Tableau does not "
                                    f"geocode as a {kind}{' of ' + country if kind == 'state' else ''}: {bad[:10]}"))
    return issues


def _data_stem(ds):
    """The stem of a datasource's data file: a text file's, an Excel workbook's, a Hyper extract's."""
    c = ds.find("connection/named-connections/named-connection/connection")
    f = None if c is None else (c.get("filename") or c.get("dbname"))
    return Path(f).stem if f else None


def check_folders(root, spec=None):
    """Field folders of the Data pane (decisions/146): a folder item names a column of its own datasource, a field
    sits in one folder, folder names do not repeat; with a spec every calcs[].folder / fields.<name>.folder is in
    each datasource that has the field (a calc by its caption, a column of the data by its name)."""
    issues = []
    for ds in root.find("datasources"):
        where = f"datasource '{ds.get('caption') or ds.get('name')}'"
        cols = set(_source_columns(ds)) | {c.get("name") for c in ds.findall("column")}
        seen, names = {}, set()
        for folder in ds.findall("folders-common/folder"):
            name = folder.get("name")
            if not name or name in names:
                issues.append(Issue("folders", where, f"folder {name!r} is named twice or has no name"))
            names.add(name)
            for item in folder.findall("folder-item"):
                col = item.get("name")
                if item.get("type") != "field":
                    issues.append(Issue("folders", where, f"folder '{name}': item {col} of type {item.get('type')!r}; "
                                                          f"only fields are verified"))
                if col not in cols:
                    issues.append(Issue("folders", where, f"folder '{name}' names {col}, not a column of the "
                                                          f"datasource"))
                if col in seen:
                    issues.append(Issue("folders", where, f"{col} is in folder '{seen[col]}' and in '{name}'; a field "
                                                          f"is in one folder"))
                seen.setdefault(col, name)
        if not spec:
            continue
        want = {c["name"]: c["folder"] for c in spec.get("calcs", []) if "folder" in c}
        want |= {n: p["folder"] for n, p in (spec.get("fields") or {}).items() if "folder" in p}
        by_caption = {c.get("caption"): c.get("name") for c in ds.findall("column")
                      if c.find("calculation") is not None and c.get("caption")}
        for field, folder in sorted(want.items()):
            col = by_caption.get(field) or (f"[{field}]" if f"[{field}]" in _source_columns(ds) else None)
            if col and seen.get(col) != folder:
                issues.append(Issue("folders", where, f"'{field}' belongs in folder '{folder}' by the spec, the "
                                                      f"workbook has it in {seen.get(col)!r}"))
    return issues


def check_sources(root, spec=None):
    """Data sources (decisions/083): every list of datasources, dependencies block and shared view names a datasource
    of the workbook; a worksheet takes one data source besides Parameters (no blending) and refers to no other; with a
    spec of several datasources each sheet stands on the data file of its spec source."""
    issues = []
    books = {ds.get("name"): ds for ds in root.find("datasources")}
    for el in root.iter():
        if el.tag == "datasources" and el is not root.find("datasources"):
            for d in el.findall("datasource"):
                if d.get("name") not in books:
                    issues.append(Issue("sources", el.getparent().tag, f"datasource {d.get('name')} is not in the "
                                                                        f"workbook"))
        if el.tag == "shared-view" and el.get("name") not in books:
            issues.append(Issue("sources", "shared-view", f"shared view of {el.get('name')}, not in the workbook"))
    of_sheet = {}
    for ws in root.iter("worksheet"):
        where, view = f"worksheet '{ws.get('name')}'", ws.find("table/view")
        listed = [d.get("name") for d in view.findall("datasources/datasource") if d.get("name") != "Parameters"]
        if len(listed) != 1:
            issues.append(Issue("sources", where, f"takes {len(listed)} data sources {listed}; a sheet takes one "
                                                  f"(no blending)"))
            continue
        of_sheet[ws.get("name")] = ds = listed[0]
        other = sorted({d for d, _ in _refs_in(ws.find("table")) if d not in (ds, "Parameters")} |
                       {d.get("datasource") for d in view.findall("datasource-dependencies")
                        if d.get("datasource") not in (ds, "Parameters")})
        if other:
            issues.append(Issue("sources", where, f"refers to {other}, not to its data source {ds}"))
    if spec and "datasources" in spec:
        stems = {name: _data_stem(ds) for name, ds in books.items()}
        first = spec["datasources"][0]["name"]
        want = {d["name"]: Path(d["path"]).stem for d in spec["datasources"]}
        for s in spec["sheets"]:
            src = s.get("datasource", first)
            for name, ds in of_sheet.items():
                if (name == s["name"] or name.startswith(s["name"] + " · ")) and stems.get(ds) != want.get(src):
                    issues.append(Issue("sources", f"worksheet '{name}'", f"stands on the data of {stems.get(ds)}, the "
                                                                         f"spec gives it source '{src}'"))
    return issues


TRUNC_PREFIX = {"Year-Trunc": "tyr", "Quarter-Trunc": "tqr", "Month-Trunc": "tmn", "Week-Trunc": "twk",
                "Day-Trunc": "tdy"}
TRUNC_SUFFIX = {"ordinal": "ok", "quantitative": "qk"}
TRUNC_INSTANCE = re.compile(r"^\[([a-z]+):(.+):([a-z]{2})(?::\d+)?\]$")


def check_date_truncs(root):
    """A date truncation on a sheet (decisions/090): its instance is named by its derivation and type ([tmn:<date>:ok]
    Month-Trunc ordinal: a header per month; [tmn:<date>:qk] quantitative: an axis) over a date column. A discrete
    one on Rows or Columns against a measure axis with the Automatic mark: Desktop draws a line along it, not bars
    (ITSM By Month, 090), so a bar along a date sets the mark Bar."""
    issues = []
    for ws in root.iter("worksheet"):
        where, table = f"worksheet '{ws.get('name')}'", ws.find("table")
        discrete = set()
        for dep in table.iterfind("view/datasource-dependencies"):
            cols = {c.get("name"): c for c in dep.findall("column")}
            for ci in dep.findall("column-instance"):
                d = ci.get("derivation")
                if d not in TRUNC_PREFIX:
                    continue
                m, name = TRUNC_INSTANCE.match(ci.get("name", "")), ci.get("name")
                if not m or m.group(1) != TRUNC_PREFIX[d] or m.group(3) != TRUNC_SUFFIX.get(ci.get("type")):
                    issues.append(Issue("dates", where, f"instance {name} is not named by its derivation {d} and type "
                                                        f"{ci.get('type')}: [{TRUNC_PREFIX[d]}:<date>:"
                                                        f"{TRUNC_SUFFIX.get(ci.get('type'), '?')}]"))
                col = cols.get(ci.get("column"))
                if col is not None and col.get("datatype") not in ("date", "datetime"):
                    issues.append(Issue("dates", where, f"{d} of {ci.get('column')}, a {col.get('datatype')} column"))
                if ci.get("type") == "ordinal":
                    discrete.add(f"[{dep.get('datasource')}].{name}")
        shelves = [f"[{d}].{n}" for d, n in _shelf_refs(table)]
        axis = any(r.endswith(":qk]") or r.endswith("[Multiple Values]") for r in shelves if r not in discrete)
        marks = [m.get("class") for m in table.iterfind("panes/pane/mark")]
        if discrete & set(shelves) and axis and "Automatic" in marks:
            issues.append(Issue("dates", where, "a discrete date on the shelves, a measure axis and the Automatic "
                                                "mark: Desktop draws a line along the dates, not bars (mark Bar)"))
    return issues


INTERPOLATIONS = ("linear", "step", "jump")  # Desktop's Line 'Path' options
STEP_MARKS = ("Line", "Automatic")  # a line sheet's mark stays Automatic; an Area keeps it but is drawn linear (158)
DAY_LEVELS = {"tdy": 1, "twk": 7, "tmn": 28, "tqr": 90, "tyr": 365}  # the shortest period of a truncated date, days


def check_interpolation(root):
    """A step line (decisions/144): line-interpolation is one of Desktop's path options, in the mark rule of a pane
    whose marks are a line (an Area keeps the format and draws it linear, a bar has no path), and the sheet's Columns end
    in a continuous axis (a step holds a value until the next point along it).
    A step area (158): Bars as wide as their period on a continuous date, from the date to the right: the width at least
    the period's shortest length in days (narrower bars leave gaps in the area), aligned left (centred, half a period
    before the date)."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        cols = (table.findtext("cols") or "").rstrip(")")
        for pane in table.iterfind("panes/pane"):
            mark = pane.find("mark")
            cls = mark.get("class") if mark is not None else "Automatic"
            for rule in pane.iterfind("style/style-rule"):
                for f in rule.iterfind("format[@attr='line-interpolation']"):
                    v = f.get("value")
                    if rule.get("element") != "mark":
                        issues.append(Issue("marks", where, f"line-interpolation in a '{rule.get('element')}' rule, "
                                                            f"not the pane's mark rule"))
                    elif v not in INTERPOLATIONS:
                        issues.append(Issue("marks", where, f"line-interpolation '{v}' (Desktop: {', '.join(INTERPOLATIONS)})"))
                    elif v != "linear" and cls not in STEP_MARKS:
                        issues.append(Issue("marks", where, f"line-interpolation '{v}' on {cls} marks: Desktop draws "
                                                            f"only a line stepped (a step area is Bars, decisions/158)"))
                    elif v != "linear" and not cols.endswith((":qk]", "[Multiple Values]")):  # Measure Values: an axis (197)
                        issues.append(Issue("marks", where, f"line-interpolation '{v}' without a continuous axis on Columns"))
            ms = pane.find("mark-sizing")
            level = re.search(r"\[(t\w\w):[^\]]*:qk\]$", cols)
            if cls != "Bar" or ms is None or ms.get("use-custom-mark-size") != "true" or not level                     or level.group(1) not in DAY_LEVELS:
                continue
            need, size = DAY_LEVELS[level.group(1)], float(ms.get("custom-mark-size-in-axis-units", "0"))
            if size < need:
                issues.append(Issue("marks", where, f"bars {size:g} days wide on a {level.group(1)} axis: gaps in the "
                                                    f"step area (at least {need})"))
            if ms.get("mark-alignment") != "mark-alignment-left":
                issues.append(Issue("marks", where, f"bars of a period wide not aligned left: each step starts half a "
                                                    f"period before its date"))
    return issues

CHECKS = [check_references, check_windows, check_dashboards, check_spacing, check_actions, check_actions_v2, check_filters,
          check_parameters, check_top_by, check_rank_filters, check_reference_lines, check_buttons, check_navigation, check_bands, check_flow_sizes, check_cards, check_kpi,
          check_kpi_status, check_kpi_v3, check_kpi_progress,
          check_formats, check_table_calcs, check_totals, check_tooltips, check_mark_labels, check_measure_values,
          check_registry_widths, check_registry_cells, check_registry_inside, check_registry_total, check_registry_pill, check_registry_string_text, check_registry_spark_line, check_text_fill,
          check_single_axis_pane,
          check_color_scales, check_interactivity, check_benchmarks, check_sort_flags, check_sheet_background, check_dual_axis, check_pareto, check_spark_points,
          check_maps, check_name_roles, barinbar.gate,
          check_scatter, check_calc_dates, check_date_truncs, check_funnel, check_interpolation,
          check_xsd]


# ---- tile grid (decisions/154) -------------------------------------------------------------------------------------
TILE_N = re.compile(r"/\s*(\d+)\s*\)|(\d+)\s*\*")


def _tile_shelves(table):
    """(rows ref, cols ref) of a sheet whose Square tiles sit on a discrete integer on each shelf, else None."""
    marks = {m.get("class") for m in table.iterfind("panes/pane/mark")}
    rows, cols = (REF.findall(table.findtext(t) or "") for t in ("rows", "cols"))
    if marks != {"Square"} or not rows or not cols or not rows[-1][1].endswith(":ok]") \
            or not cols[-1][1].endswith(":ok]"):
        return None
    return rows[-1], cols[-1]


def check_tile_grids(root, tables):
    """A tile grid's places (decisions/154). A wall (INDEX() table calcs on Rows and Columns): the row and the column
    wrap at the same N, walk the same member, and a computed-sort orders that member (else INDEX() walks it
    alphabetically). A tile map (bins on Rows and Columns): bins of size 1 (a tile per row / column number), and in
    the data one member per place (two would draw on one tile). tables: _text_tables."""
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        shelves = _tile_shelves(table)
        if shelves is None:
            continue
        cols, insts, ds = {}, {}, shelves[0][0]
        for dep in table.iterfind("view/datasource-dependencies"):
            cols.update({c.get("name"): c for c in dep.findall("column")})
            insts.update({f"[{dep.get('datasource')}].{ci.get('name')}": ci for ci in dep.findall("column-instance")})
        pair = [insts.get(f"[{d}].{n}") for d, n in shelves]
        if None in pair:
            continue  # check_references' finding
        calc = [cols.get(ci.get("column")) for ci in pair]
        calc = [c.find("calculation") if c is not None else None for c in calc]
        formulas = [c.get("formula", "") if c is not None else "" for c in calc]
        if all("INDEX()" in f for f in formulas):
            ns = [{int(a or b) for a, b in TILE_N.findall(f)} for f in formulas]
            if ns[0] != ns[1]:
                issues.append(Issue("tilegrid", where, f"the wall's row wraps at {sorted(ns[0])}, its column at "
                                                       f"{sorted(ns[1])}: tiles overlap or leave holes"))
            along = [[f for t in ci.findall("table-calc") for f in [t.get("ordering-field")]
                      + [o.get("field") for o in t.iter("order")] if f] for ci in pair]
            if along[0] != along[1]:
                issues.append(Issue("tilegrid", where, f"the wall's row walks {along[0]}, its column {along[1]}"))
            sorts = {s.get("column") for s in table.iterfind("view/computed-sort")}
            if along[0] and not sorts & set(along[0]):
                issues.append(Issue("tilegrid", where, f"no computed-sort of {along[0][0]}: INDEX() walks the "
                                                       f"members alphabetically, not by the measure"))
            lods = {e.get("column") for e in table.iterfind("panes/pane/encodings/*")
                    if e.get("column", "").endswith(":nk]") and e.tag in ("lod", "text")}
            for f in sorted(lods - set(along[0])):
                issues.append(Issue("tilegrid", where, f"{f} is on the marks but the wall's INDEX() does not walk "
                                                       f"it: each of its members starts the wall again"))
        elif all(c is not None and c.get("class") == "bin" for c in calc):
            for c in calc:
                if c.get("size") != "1":
                    issues.append(Issue("tilegrid", where, f"a tile map's bin of {c.get('formula')} has size "
                                                           f"{c.get('size')}: a tile per number needs size 1"))
            header, data = tables.get(ds, ([], []))
            src = [c.get("formula", "").strip("[]") for c in calc]
            members = [insts[e.get("column")].get("column", "").strip("[]")
                       for e in table.iterfind("panes/pane/encodings/lod") if e.get("column") in insts]
            if not data or not all(x in header for x in src + members) or not members:
                continue
            at, seen = [header.index(x) for x in src], {}
            for r in data:
                place, m = tuple(r[i] for i in at), tuple(r[header.index(x)] for x in members)
                if "" in place or seen.setdefault(place, m) == m:
                    continue
                issues.append(Issue("tilegrid", where, f"{seen[place]} and {m} share the tile at row {place[0]}, "
                                                       f"column {place[1]}"))
                seen[place] = m
    return issues


# ---- field properties (decisions/033) ------------------------------------------------------------------------------
def _text_tables(z, names, root):
    """{datasource: (header, rows)} of each text-file source in the package, values trimmed as the text connector
    reads them, short rows padded. Hyper and Excel sources are not read."""
    out = {}
    for ds in root.find("datasources"):
        for conn in ds.iter("connection"):
            if conn.get("class") != "textscan":
                continue
            path = f"{conn.get('directory')}/{conn.get('filename')}".lstrip("/")
            if path not in names:
                continue  # check_package's finding
            rows = csv.reader(io.StringIO(z.read(path).decode("utf-8-sig")))
            header = next(rows, [])
            out[ds.get("name")] = (header, [[v.strip() for v in r[:len(header)]] + [""] * (len(header) - len(r))
                                            for r in rows])
    return out


def _text_values(tables):
    """{(datasource, '[Column]'): set of values} of each text-file source (_text_tables): their field values;
    Hyper and Excel sources go unchecked."""
    out = {}
    for ds, (header, rows) in tables.items():
        out.update({(ds, f"[{h}]"): {r[i] for r in rows if r[i]} for i, h in enumerate(header)})
    return out


def _unquote(bucket):
    return bucket[1:-1] if bucket and len(bucket) > 1 and bucket[0] == bucket[-1] == '"' else None


def check_fields(root, values):
    """Aliases, manual orders and groups of the datasource columns: every alias names a value of the data and no two
    values show the same label; a manual order lists every value once; a member is in one bin of a group. values:
    _text_values (the data of a text-file source)."""
    issues = []
    for ds in root.find("datasources"):
        name = ds.get("name")
        groups = {}
        for col in ds.findall("column"):
            cname, where = col.get("name"), f"column {col.get('name')}"
            if name == "Parameters" and col.get("datatype") != "string":  # keys are its literals: 4 (decisions/163)
                continue  # its aliases are checked with the parameter (check_parameters)
            data = values.get((name, cname))
            keys = [a.get("key") for a in col.findall("aliases/alias")]
            labels = [a.get("value") for a in col.findall("aliases/alias")]
            for k in keys:
                v = _unquote(k)
                if v is None:
                    issues.append(Issue("fields", where, f"alias key {k} is not a quoted text value"))
                elif data is not None and v not in data:
                    issues.append(Issue("fields", where, f"alias for {k}, a value the data does not have"))
            shown = labels + sorted((data or set()) - {_unquote(k) for k in keys})
            dup = sorted(s for s, n in Counter(shown).items() if n > 1)
            if dup:
                issues.append(Issue("fields", where, f"labels {dup} show more than one value"))
            calc = col.find("calculation[@class='categorical-bin']")
            if calc is None:
                continue
            src = values.get((name, calc.get("column")))
            src_col = next((c for c in ds.findall("column") if c.get("name") == calc.get("column")), None)
            numeric = src_col is not None and src_col.get("datatype") in ("integer", "real")  # decisions/151
            seen, bins = {}, []
            for b in calc.findall("bin"):
                bins.append(_unquote(b.get("value")))
                for v in b.findall("value"):
                    m = _unquote(v.text)
                    if m is None and numeric and re.fullmatch(r"-?\d+", v.text or ""):
                        m = v.text  # a number's literal is unquoted
                    elif m is None or numeric:
                        issues.append(Issue("fields", where, f"member {v.text} of bin {b.get('value')} is "
                                            f"{'quoted' if numeric else 'not quoted'}: a "
                                            f"{'number' if numeric else 'text'} source takes "
                                            f"{'unquoted integers' if numeric else 'quoted text'}"))
                    if m in seen:
                        issues.append(Issue("fields", where, f"member {v.text} is in bins {seen[m]} and "
                                                             f"{b.get('value')}"))
                    seen[m] = b.get("value")
                    if src is not None and m not in src:
                        issues.append(Issue("fields", where, f"bin {b.get('value')} groups {v.text}, a value the "
                                                             f"data does not have"))
            other = _unquote(calc.get("default", ""))
            if keys:  # Desktop drops the aliases of a group: it is renamed through its bins (decisions/151)
                issues.append(Issue("fields", where, "aliases on a group; rename the bins instead"))
            if src is not None:
                rest = src - set(seen)
                groups[cname] = set(bins) | ({other} if other and rest else set() if other else rest)
        bins = {c.get("name") for c in ds.findall("column") if c.find("calculation[@class='categorical-bin']")
                is not None}
        for ci in root.iter("column-instance"):  # Desktop 2025.1 warns on load: 'Warnings occurred while loading'
            p = ci.getparent()
            if ci.get("column") in bins and (p.get("datasource") if p.tag == "datasource-dependencies"
                                             else p.get("name")) == name:
                issues.append(Issue("fields", f"instance {ci.get('name')}", f"group {ci.get('column')} goes on a "
                                    f"shelf as its column [{name}].{ci.get('column')}, not through an instance"))
        instances = {ci.get("name"): ci.get("column") for ci in ds.findall("column-instance")}
        for ms in ds.findall("default-sorts/manual-sort"):
            ref, where = ms.get("column"), f"default sort of {ms.get('column')}"
            col = instances.get(ref) or (ref if ref in groups or ds.find(f"column[@name='{ref}']") is not None
                                         else None)
            if col is None:
                issues.append(Issue("fields", where, f"{ref} is not a column-instance of the datasource"))
                continue
            calc = next((c for c in ds.findall("column") if c.get("name") == col), None)
            if calc is not None and calc.find("calculation[@class='tableau']") is not None and \
                    (calc.get("datatype"), calc.get("role")) != ("string", "dimension"):  # decisions/090
                issues.append(Issue("fields", where, f"manual order of calc {calc.get('caption') or col}, a "
                                                     f"{calc.get('datatype')} {calc.get('role')}: an order sorts the "
                                                     f"members of a text dimension"))
            buckets = [_unquote(b.text) for b in ms.findall("dictionary/bucket")]
            dup = sorted(b for b, n in Counter(buckets).items() if n > 1)
            if dup:
                issues.append(Issue("fields", where, f"values {dup} listed more than once"))
            data = groups.get(col) if col in groups else values.get((name, col))
            if data is not None:
                if set(buckets) - data:
                    issues.append(Issue("fields", where, f"lists {sorted(set(buckets) - data)}, values the data "
                                                         f"does not have"))
                if data - set(buckets):
                    issues.append(Issue("fields", where, f"leaves out {sorted(data - set(buckets))}: their place "
                                                         f"is Tableau's guess, not the order asked for"))
    return issues


# ---- sheet fit (decisions/068) -------------------------------------------------------------------------------------
def _text_part(ws):
    """A sheet of text alone (a KPI tile, a card's value text): no rows, no columns, a label of runs."""
    table = ws.find("table")
    return not (table.findtext("rows") or table.findtext("cols")) and ws.find(".//customized-label") is not None


def _alignment(ws):
    cell = {f.get("attr"): f.get("value") for f in ws.iterfind(".//pane/style/style-rule[@element='cell']/format")}
    runs = sorted({r.get("fontalignment") or "" for r in ws.iterfind(".//customized-label/formatted-text/run")})
    return cell.get("text-align"), cell.get("vertical-align"), tuple(runs)


def check_fit(root, tables):
    """Each sheet on a dashboard has the fit of tbuilder/fit.py: Entire View unless its rows (columns) at Desktop's
    Standard size do not fit its zone: then Fit Width (Fit Height), Standard when neither. Counts come from the
    packaged text data; a count the gate cannot read allows either outcome of that side. The text parts of one KPI
    sheet ('<sheet> · <label>': its tiles, its cards' value texts, side by side in a row or stacked in a column)
    share their fit and their alignment."""
    from . import fit
    issues = []
    allowed = fit.dashboard_fits(root, fit.table_counter(tables))
    sheets = {w.get("name"): w for w in root.iter("worksheet")}
    zones = {(db.get("name"), z.get("name")): _box(z) for db in root.iter("dashboard")
             for z in db.find("zones").iter("zone") if not z.get("type-v2") and z.get("name")}
    for win in root.find("windows"):
        if win.get("class") != "dashboard":
            continue
        dash, groups = win.get("name"), {}
        for vp in win.iter("viewpoint"):
            name, zoom = vp.get("name"), fit.zoom_of(vp)
            ok = allowed.get((dash, name))
            if ok is not None and zoom not in ok:
                issues.append(Issue("fit", f"dashboard '{dash}' sheet '{name}'",
                                    f"fit {zoom}, the rule gives {' or '.join(sorted(ok))}: in {zoom} Desktop "
                                    + {fit.STD: "leaves its rows and text at the top of the zone and their size its own",
                                       fit.EV: "squeezes rows or columns that do not fit (overlapping labels, '##')",
                                       fit.FW: "keeps rows at their own height: a short list does not fill the zone",
                                       fit.FH: "keeps columns at their own width"}.get(zoom, "draws it otherwise")))
            ws, box = sheets.get(name), zones.get((dash, name))
            if ws is not None and box and " · " in name and _text_part(ws):
                x, y, w, h = box
                for key in (("row", y, h), ("column", x, w)):
                    groups.setdefault((name.split(" · ")[0], *key), []).append((name, zoom, _alignment(ws)))
        for (prefix, *_), parts in groups.items():
            if len({(z, a) for _, z, a in parts}) > 1:
                issues.append(Issue("fit", f"dashboard '{dash}' KPI '{prefix}'",
                                    "its parts differ in fit or text alignment: "
                                    + "; ".join(f"'{n}' {z} {a}" for n, z, a in parts)))
    return issues


def check_legend_below(root):
    """The legend under a block shows every label whole (decisions/185): a text zone that starts with its swatches is
    read back into lines by the build's own wrap; a label wider than the zone, or lines taller than it, Desktop cuts
    to '..' without a word."""
    issues = []
    for db in root.iter("dashboard"):
        size = db.find("size")
        if size is None or not size.get("maxwidth") or not size.get("maxheight"):
            continue
        for z in db.iter("zone"):
            runs = z.findall("formatted-text/run")
            paragraphs = "".join(r.text or "" for r in runs).split("\u00c6\n")
            if z.get("type-v2") != "text" or "\u25a0" not in paragraphs[0]:
                continue
            m = _margins(_style(z)) or {}
            pt = next(int(r.get("fontsize")) for r in runs if r.get("fontsize"))
            w = int(z.get("w")) * int(size.get("maxwidth")) // FULL - (m.get("left") or 0) - (m.get("right") or 0)
            h = int(z.get("h")) * int(size.get("maxheight")) // FULL - (m.get("top") or 0) - (m.get("bottom") or 0)
            tokens = [[tok for tok in re.split("(?=\u25a0)", para) if tok.strip()] for para in paragraphs]
            where = f"dashboard '{db.get('name')}' zone {z.get('id')}"
            wide = [tok for line in tokens for tok in insight.too_wide(line, pt, w)]
            if wide:
                issues.append(Issue("legend-below", where, f"legend label {wide[0]!r} does not fit in {w}px: "
                                                           "widen the block or shorten the label"))
            need = sum(len(insight.legend_wrap(line, pt, w)) for line in tokens) * design.line_px(pt)
            if need > h + 1:
                issues.append(Issue("legend-below", where, f"legend needs {need}px of height, the zone has {h}px: "
                                                           "Desktop cuts the last label to '..'"))
    return issues


def check_chart_height(root):
    """A chart with a vertical axis on a dashboard has the height tbuilder/fit.py says Desktop needs to draw it: its
    axes, titles and fit.PLOT_MIN_PX of plot (decisions/101; a public book Weekly Sales Trend drew blank at 60px)."""
    from . import fit
    return [Issue("chart-height", f"dashboard '{dash}' sheet '{name}'",
                  f"{have}px high inside its margins, {need}px needed: Desktop draws its axes without marks, or nothing at all")
            for dash, name, have, need in fit.short_charts(root)]


CROWDED = {"fat": "its bars stretch to {have}px a row (over {limit}px): a few bars in a tall cell become slabs",
           "legend": "the legend rows are {have}px each (under {limit}px): Entire View squeezes the text over its dots",
           "narrow": "its columns need {limit}px, the cell leaves {have}px: Fit Height would scroll it sideways"}


def check_crowded(root, tables):
    """The fit rule's outcome must draw cleanly (decisions/093): no fat bars in a tall cell, no squeezed donut legend,
    no table or heatmap wider than its cell."""
    from . import fit
    return [Issue("fit-crowded", f"dashboard '{dash}' sheet '{name}'", CROWDED[kind].format(have=have, limit=limit))
            for kind, dash, name, have, limit in fit.crowded(root, fit.table_counter(tables))]


def check_heat_margins(root):
    """A heatmap's row totals stay level with its cells (decisions/186): the same Rows shelf, the same fixed row
    height and the same gap between the groups. A difference moves each bar off its row with no error in Desktop."""
    from .heatmap import MARGIN_SUFFIX

    def height(ws):
        return [(f.get("field"), f.get("value")) for f in ws.findall("table/style/style-rule[@element='cell']/format")
                if f.get("attr") == "height"]

    def gap(ws):
        return sorted((f.get("attr"), f.get("value"))
                      for f in ws.findall("table/style/style-rule[@element='table-div']/format")
                      if f.get("scope") == "rows")

    sheets = {ws.get("name"): ws for ws in root.iter("worksheet")}
    tail = f" · {MARGIN_SUFFIX['rows']}"
    issues = []
    for name, ws in sheets.items():
        heat = sheets.get(name[:-len(tail)]) if name.endswith(tail) else None
        if heat is None:
            continue
        where = f"worksheet '{name}'"
        if ws.findtext("table/rows") != heat.findtext("table/rows"):
            issues.append(Issue("margins", where, f"its rows differ from the heatmap's: {ws.findtext('table/rows')}"))
        if height(ws) != height(heat):
            issues.append(Issue("margins", where, f"row height {height(ws)} is not the heatmap's {height(heat)}"))
        if gap(ws) != gap(heat):
            issues.append(Issue("margins", where, f"the gap between groups {gap(ws)} is not the heatmap's {gap(heat)}"))
    return issues


def check_header_widths(root, values):
    """A heatmap or a text table with one row field and one column field draws its headers whole (decisions/066,
    094): a row header width under a shown field label holds the label (bold metric), and without a width the
    label's ink fits what the values need (Desktop sizes the header by the values: 'Paid Mon..'); a column width
    holds the widest column value ('Furnit..'). Values come from the packaged text data (a raw column without
    aliases); a calculation's or an aliased column's values go unchecked, its label does not."""
    from . import fit
    from .design import FONT, TABLE_CELL_PAD_PX, field_label_px, row_header_fit_px, text_px
    pt = FONT["table_header"]
    issues = []
    columns = {(ds.get("name"), c.get("name")): c for ds in root.find("datasources") for c in ds.findall("column")}
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        mark = table.find("panes/pane/mark")
        if mark is None or mark.get("class") not in ("Square", "Text", "Automatic"):  # a heatmap, a text table
            continue
        rows_t, cols_t = table.findtext("rows") or "", table.findtext("cols") or ""
        rows, cols = fit.refs(rows_t), fit.refs(cols_t)
        if len(rows) != 1 or len(cols) != 1 or not all(fit.discrete(ws, i) for _, i in rows + cols) \
                or cols[0][1] == ":Measure Names":
            continue
        where = f"worksheet '{ws.get('name')}'"

        def field(ds, inst):
            col, derivation = fit._instance(ws, ds, inst)
            c = columns.get((ds, col))
            caption = c.get("caption") if c is not None and c.get("caption") else col[1:-1]
            raw = derivation == "None" and (c is None or (c.find("calculation") is None and c.find("aliases") is None))
            return f"[{ds}].[{inst}]", caption, sorted(values.get((ds, col), ())) if raw else None

        def width(element, ref, unscoped=False):
            for f in ws.findall(f"table/style/style-rule[@element='{element}']/format"):
                if f.get("attr") == "width" and (f.get("field") == ref or (unscoped and f.get("field") is None)):
                    return int(f.get("value"))
            return None

        ref, caption, vals = field(*rows[0])
        hidden = any(f.get("attr") == "display-field-labels" and f.get("scope") == "rows" and f.get("value") == "false"
                     for f in ws.findall("table/style/style-rule[@element='worksheet']/format"))
        if not hidden:
            w, need = width("header", ref), field_label_px(caption)
            if w is not None and w < need:
                issues.append(Issue("widths", where, f"row header {w}px cuts its field label '{caption}' (needs "
                                                     f"{need}px)"))
            elif w is None and vals and text_px(caption, pt, bold=True) > row_header_fit_px(vals, ""):
                issues.append(Issue("widths", where, f"no row header width: Desktop sizes it by the values and "
                                                     f"cuts the field label '{caption}' (needs {need}px)"))
        ref, caption, vals = field(*cols[0])
        w = width("cell", ref, unscoped=True)
        if w is not None and vals:
            need = max(text_px(v, pt) + TABLE_CELL_PAD_PX for v in vals)
            if w < need:
                issues.append(Issue("widths", where, f"columns of {w}px cut the column header "
                                                     f"'{max(vals, key=lambda v: text_px(v, pt))}' (needs {need}px)"))
    return issues


def check_bar_labels(root):
    """A bar of members (discrete rows, one measure axis on Columns, one pane, no fixed axis range) says its values
    (decisions/087): an axis hidden without labels on its marks shows bars nobody can read; with labels at the bar
    ends instead of the axis, the row headers have a width set and each dashboard zone leaves a pane of at least
    BAR_LABEL_FLOOR_PX beside them (the room Desktop keeps right of the longest bar and a bar; the generator checks
    the widest label from the expected numbers)."""
    from . import barlabels, fit
    issues = []
    sheets = {}
    for ws in root.iter("worksheet"):
        table = ws.find("table")
        panes = table.findall("panes/pane")
        rows, cols = fit.refs(table.findtext("rows")), fit.refs(table.findtext("cols"))
        if (len(panes) != 1 or len(cols) != 1 or cols[0][1] == "Multiple Values" or fit.discrete(ws, cols[0][1])
                or not rows or not all(fit.discrete(ws, i) for _, i in rows)
                or panes[0].find("mark").get("class") not in ("Automatic", "Bar")
                or table.find("style/style-rule[@element='axis']/encoding[@attr='space']") is not None):
            continue
        ref = "[{}].[{}]".format(*cols[0])
        hidden = any(f.get("attr") == "display" and f.get("field") == ref and f.get("value") == "false"
                     for f in table.findall("style/style-rule[@element='axis']/format"))
        labels = panes[0].find("style/style-rule[@element='mark']/format[@attr='mark-labels-show'][@value='true']")
        where = f"worksheet '{ws.get('name')}'"
        beside = (cols[0][0], cols[0][1].rsplit(":", 1)[0] + ":ok") in rows  # value_column left (decisions/095)
        totals = any(r.get("scope") == "per-cell" and r.get("label-type") == "value" and r.get("value-column") == ref
                     for r in panes[0].findall("reference-line"))  # a stack's total at the bar end (decisions/095)
        if hidden and (beside or totals):
            continue
        if hidden and labels is None:
            issues.append(Issue("bar-labels", where, "its measure axis is hidden and its bars have no labels: no "
                                                     "value can be read (labels at the bar ends, or the axis back)"))
        elif hidden:
            heads = {f.get("field") for f in table.findall("style/style-rule[@element='header']/format")
                     if f.get("attr") == "width"}
            if not {"[{}].[{}]".format(*r) for r in fit._shown(ws, rows)} <= heads:  # hidden headers: no width
                issues.append(Issue("bar-labels", where, "values at the bar ends without a row header width: the "
                                                         "room for the labels is not known"))
            else:
                sheets[ws.get("name")] = ws
    for db in root.iter("dashboard"):
        size = db.find("size")
        dims = (int(size.get("maxwidth") or size.get("minwidth")), int(size.get("maxheight") or size.get("minheight")))
        for z in db.find("zones").iter("zone"):
            ws = sheets.get(z.get("name"))
            if ws is None or z.get("type-v2"):
                continue
            have = barlabels.pane_px(ws, z, dims)
            if have < barlabels.FLOOR_PX:
                issues.append(Issue("bar-labels", f"dashboard '{db.get('name')}' sheet '{z.get('name')}'",
                                    f"{have}px of bars beside the row headers, {barlabels.FLOOR_PX}px at the least: "
                                    f"the values at the bar ends are cut or pushed over the bars"))
    return issues


def run(twbx_path, spec=None, expected=None):
    """Return a list of Issues for a packaged workbook (empty list == pass). spec: the spec it was built from, for
    the checks of what the spec asks that the file alone cannot tell (the filter state at open). expected: the
    numbers of each sheet (expected.py), for the ranges of the color scales."""
    with design.book_accent(spec):  # the accent the book was built with (decisions/137)
        return _run(twbx_path, spec, expected)


def _run(twbx_path, spec, expected):
    try:
        z = zipfile.ZipFile(twbx_path)
    except zipfile.BadZipFile as e:  # truncated download, not a .twbx at all
        return [Issue("package", "zip", f"not a zip archive: {e}")]
    with z:
        bad = z.testzip()
        names = set(z.namelist())
        if bad:
            return [Issue("package", bad, "corrupt zip member")]
        twbs = [n for n in names if n.lower().endswith(".twb")]
        if not twbs:
            return [Issue("package", "zip", "no .twb inside")]
        try:
            root = etree.fromstring(z.read(twbs[0]))
        except etree.XMLSyntaxError as e:
            return [Issue("xml", twbs[0], str(e))]
        workbooks = {n: z.read(n) for n in names if n.lower().endswith(EXCEL_FILES)}
        tables = _text_tables(z, names, root)
        values = _text_values(tables)
    issues = check_package(names, root) + check_excel(root, workbooks) + check_fields(root, values)
    issues += check_geo_names(root, values, tables)  # decisions/046, a map after its filters (067)
    issues += check_shared_filters(root, values) + (check_filter_spec(root, spec) if spec else [])
    issues += check_sheet_filters(root, values) + check_filter_groups(root)  # decisions/057, 071
    issues += check_sources(root, spec)  # decisions/083
    issues += check_folders(root, spec)  # decisions/146
    issues += check_fit(root, tables)  # decisions/068
    issues += check_chart_height(root)  # decisions/101
    issues += check_legend_below(root)  # decisions/185
    issues += check_crowded(root, tables)  # decisions/093
    issues += check_header_widths(root, values)  # decisions/094
    issues += check_heat_margins(root)  # decisions/186
    issues += check_bar_labels(root)  # decisions/087
    issues += check_tile_grids(root, tables)  # decisions/154
    for check in CHECKS:
        issues += check(root)
    issues += check_color_ranges(root, expected) if expected else []
    issues += check_map_colors(root, spec) if spec else []  # decisions/137
    return issues + check_hyper(twbx_path, names, root)


def enforce(twbx_path, spec=None, expected=None):
    issues = run(twbx_path, spec, expected)
    if issues:
        raise GateError(issues)
