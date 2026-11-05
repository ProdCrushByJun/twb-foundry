"""Excel (.xlsx, .xlsm, .xls) as a datasource, on a par with CSV (decisions/025, 050).

A sheet is read (openpyxl; xlrd for .xls) into the same Profile the CSV profiler gives (tbuilder/profile.py). Values
become the strings a CSV would hold (plain numbers, ISO dates), so expected.py, formula.py and the date filters work
on them unchanged. Types are decided as Desktop 2025.1's Excel connector decided them on the reference files
(out/excel_lab): by the cell values, not by their number format —
  date cells all at midnight -> date, any time of day -> datetime; numbers all whole -> integer, else real;
  text -> string, also text that looks like a number or a date; a date in a 'General' cell is a number.
What Desktop would read as something else than the sheet shows (text in a number column became null) or what
has no checked pattern yet fails here with a message instead.

The table is the only block of cells on its sheet, from any cell: Desktop finds it and writes its range as the
grid origin (out/excel_v2_lab/ref_offset.twb: 'C4:H504'). A title or a note around it is refused: Desktop reads it
as the header row (F2, F3 ... columns), and its Data Interpreter is a heuristic this tool does not model (050).
Several sheets: 'union' appends sheets with the same columns (Desktop adds 'Sheet' and 'Table Name'), 'join' adds
the columns of a second sheet by a key (inner or left), both as one table object (ref_union.twb, ref-join-left.twb).

The XML is written as Desktop 2025.1 saved it (out/excel_lab/ref_excel.twbx, out/excel_v2_lab): connection class
excel-direct with the packaged path in 'filename' (the same for .xls and .xlsm), relation '<sheet>' on table
'[<sheet>$]' with the grid origin of the table, a capability record with that grid, column records with the Excel
remote types.
"""
import contextlib
import datetime as dt
import json
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .profile import Column, Profile, check_names, profile_csv

EXTENSIONS = (".xlsx", ".xlsm", ".xls")
# Excel connection, column records: remote-type and DebugRemoteType as Desktop 2025.1 wrote them
REMOTE = {"string": ("130", "WSTR"), "integer": ("20", "I8"), "real": ("5", "R8"),
          "date": ("7", "DATE"), "datetime": ("7", "DATE")}
AGGREGATION = {"string": "Count", "integer": "Sum", "real": "Sum", "date": "Year", "datetime": "Year"}
# a string column of the Excel connection (the CSV one has LRU_RRU / LEN_RUS): by the workbook's locale, as Desktop
# rewrites it on save (decisions/085)
STRING_COLLATION = {"ru_RU": "LRU_RRU_S2", "en_US": "LEN_RUS_S2"}
# <columns outcome>: Desktop 2025.1 recomputes it from the sheet on every open (its log shows the stored value, then
# its own; Save As writes its own) with a heuristic over the cells. A clean table gets 6 (golden_excel_2025_1);
# a whole number as text in a text column or a partly empty last row gave 2 (decisions/025; the same sheet saved
# as .xls gave 2, as .xlsm 6: decisions/050). A different stored value opens the same: it is not modelled.
OUTCOME = "6"
UNION_COLUMNS = ("Sheet", "Table Name")  # the columns Desktop adds to a union of sheets, the sheet's name in both
UNION_REMOTE = "129"  # their remote type (ref_union.twb)
JOINS = ("inner", "left")  # join types checked in Desktop (ref_join_inner.twb, ref-join-left.twb)
JOIN_KEYS = ("string", "integer")


@dataclass
class Table:
    """One sheet read as a table."""
    sheet: str
    grid: str  # the table's cells, 'C4:H504' (header row included)
    columns: list  # Column
    rows: list  # {name: text}


@dataclass
class Field:
    """A column of the datasource: its name in the workbook (local), on its sheet (remote)."""
    local: str
    sheet: str
    remote: str


@dataclass
class ExcelProfile(Profile):
    sheet: str = ""  # the first (or only) sheet: it names the relation, the table object and the caption
    grid: str = ""  # the first sheet's table
    kind: str = "table"  # table | union | join
    tables: list = field(default_factory=list)  # Table, in the relation's order
    fields: list = field(default_factory=list)  # Field per column of the profile, in its order
    how: str = ""  # join type
    on: str = ""  # join key, the same column name on both sheets


def is_excel(path):
    return Path(path).suffix.lower() in EXTENSIONS


_cache = None  # {(file, mtime, size, sheet/union/join): Profile} while cached() is on


@contextlib.contextmanager
def cached():
    """Within it load() profiles each file once: rebuild checks one data file some 60 times (_fit). A profile is
    read-only for its users; a file changed on disk (mtime, size) is profiled again."""
    global _cache
    outer = _cache
    _cache = {} if outer is None else outer
    try:
        yield
    finally:
        _cache = outer


def load(path, source=None):
    """The profile of a datasource file: a CSV, or an Excel table. source: the sheet name, or the spec's datasource
    (its 'sheet', 'union', 'join')."""
    ds = source if isinstance(source, dict) else ({} if source is None else {"sheet": source})
    if _cache is None:
        return _load(path, ds)
    st = Path(path).stat()
    key = (str(Path(path).resolve()), st.st_mtime_ns, st.st_size,
           json.dumps({k: ds.get(k) for k in ("sheet", "union", "join")}, sort_keys=True, default=str))
    if key not in _cache:
        _cache[key] = _load(path, ds)
    return _cache[key]


def _load(path, ds):
    if is_excel(path):
        return profile_excel(path, ds.get("sheet"), ds.get("union"), ds.get("join"))
    for key in ("sheet", "union", "join"):
        if ds.get(key) is not None:
            raise ValueError(f"{Path(path).name}: '{key}' applies to an Excel file only")
    return profile_csv(path)


def _letter(col):
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def _kind(v):
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, dt.date):  # a datetime, or a date for some number formats
        return "datetime"
    if isinstance(v, (dt.time, dt.timedelta)):
        return "time"
    if isinstance(v, (int, float)):
        return "number"
    return "string"


def _second(v):
    """A date cell to the nearest second (Excel keeps fractions of a day)."""
    if not isinstance(v, dt.datetime):
        v = dt.datetime(v.year, v.month, v.day)
    return (v + dt.timedelta(microseconds=500_000)).replace(microsecond=0)


# ---- reading a sheet ----------------------------------------------------------------------------------------------
@dataclass
class _Cells:
    """A sheet's non-empty cells {(row, col): value} (1-based) and what the reader found wrong in it."""
    cells: dict
    merged: list  # [(coordinate 'A1:B1', first row)]
    error: tuple = None  # (coordinate, error text) of the first error cell
    no_value: str = ""  # coordinate of the first formula without a saved value


class _Book:
    """An .xlsx/.xlsm (openpyxl) or .xls (xlrd) workbook: its sheets, read once each."""

    def __init__(self, path):
        self.path = path
        self.xls = path.suffix.lower() == ".xls"
        errors = (zipfile.BadZipFile, KeyError, OSError, ValueError)
        try:
            if self.xls:
                import xlrd  # only an .xls source needs it
                errors += (xlrd.XLRDError,)
                self.book = xlrd.open_workbook(path, formatting_info=True)
                self.names = self.book.sheet_names()
            else:
                import openpyxl  # only an Excel source needs it
                self.book = openpyxl.load_workbook(path, data_only=True)
                self.formulas = openpyxl.load_workbook(path, data_only=False)
                self.names = self.book.sheetnames
        except errors as e:
            raise ValueError(f"{path.name}: not a readable {path.suffix} file ({e})") from None

    def visible(self, sheet):
        if self.xls:
            return self.book.sheet_by_name(sheet).visibility == 0
        return self.book[sheet].sheet_state == "visible"

    def read(self, sheet):
        return self._read_xls(sheet) if self.xls else self._read_xlsx(sheet)

    def _read_xlsx(self, sheet):
        ws, fs = self.book[sheet], self.formulas[sheet]
        out = _Cells({}, [(r.coord, r.min_row) for r in ws.merged_cells.ranges])
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "e":
                    out.error = out.error or (c.coordinate, c.value)
                elif c.value is not None and c.value != "":
                    out.cells[(c.row, c.column)] = c.value
        for row in fs.iter_rows():
            for f in row:
                if f.data_type == "f" and ws.cell(f.row, f.column).value is None and not out.no_value:
                    out.no_value = f.coordinate  # "" is a saved empty result
        return out

    def _read_xls(self, sheet):
        import xlrd
        sh = self.book.sheet_by_name(sheet)
        out = _Cells({}, [(f"{_letter(c0 + 1)}{r0 + 1}:{_letter(c1)}{r1}", r0 + 1)
                          for r0, r1, c0, c1 in sh.merged_cells])
        for r in range(sh.nrows):
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                where = f"{_letter(c + 1)}{r + 1}"
                if cell.ctype == xlrd.XL_CELL_ERROR:
                    out.error = out.error or (where, xlrd.error_text_from_code.get(cell.value, "#ERROR"))
                elif cell.ctype == xlrd.XL_CELL_DATE:
                    out.cells[(r + 1, c + 1)] = (xlrd.xldate_as_datetime(cell.value, self.book.datemode)
                                                 if cell.value >= 1 else dt.time())  # a time of day: refused
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    out.cells[(r + 1, c + 1)] = bool(cell.value)
                elif cell.ctype == xlrd.XL_CELL_NUMBER:
                    out.cells[(r + 1, c + 1)] = cell.value
                elif cell.ctype == xlrd.XL_CELL_TEXT and cell.value != "":
                    out.cells[(r + 1, c + 1)] = cell.value
        return out


def _check_sheet(book, sheet):
    path = book.path
    if sheet not in book.names:
        raise ValueError(f"{path.name}: no sheet '{sheet}'. Sheets: {book.names}")
    if any(ch in sheet for ch in "[]'\"<>&$"):
        raise ValueError(f"{path.name}: sheet name '{sheet}' contains XML/Tableau-unsafe characters")
    if not book.visible(sheet):
        raise ValueError(f"{path.name}: sheet '{sheet}' is hidden (not checked in Desktop): unhide it")


TITLE_HINT = ("a title or a note next to the table is not supported: keep the table alone on its sheet (Desktop "
              "would read the title as the header; its Data Interpreter is not supported, decisions/050)")


def _table(book, sheet) -> Table:
    """One sheet as a table: the only block of cells on the sheet, its first row the header, one row per record."""
    _check_sheet(book, sheet)
    where = f"{book.path.name}, sheet '{sheet}'"
    read = book.read(sheet)
    if read.error:
        raise ValueError(f"{where}: cell {read.error[0]} holds the error {read.error[1]}")
    cells = read.cells
    if not cells:
        raise ValueError(f"{where}: the sheet is empty")
    top, left = min(r for r, _ in cells), min(c for _, c in cells)
    bottom, right = max(r for r, _ in cells), max(c for _, c in cells)
    for coord, first in read.merged:  # only the top-left cell keeps the value: the rest would read as nulls
        part = "header" if first <= top else "data"
        raise ValueError(f"{where}: merged cells {coord} in the {part}: unmerge them, one value per cell "
                         f"and one header row")
    if read.no_value:
        raise ValueError(f"{where}: formula in {read.no_value} has no saved value (the file was written "
                         f"by a script, not Excel): open it in Excel and save, or write values")
    for r in range(top + 1, bottom + 1):
        if not any((r, c) in cells for c in range(left, right + 1)):
            raise ValueError(f"{where}: row {r} is empty and more data is below: several tables or a title above "
                             f"the table are not supported (keep one table on the sheet, or one per sheet)")
    for c in range(left, right + 1):
        if (top, c) in cells:
            continue
        if not any((r, c) in cells for r in range(top + 1, bottom + 1)):
            raise ValueError(f"{where}: column {_letter(c)} is empty and more data is to the right: several "
                             f"tables on one sheet are not supported (keep one table, or one per sheet)")
        raise ValueError(f"{where}: column {_letter(c)} has data but an empty header ({_letter(c)}{top}); "
                         f"{TITLE_HINT}")
    names = []
    for c in range(left, right + 1):
        h = cells[(top, c)]
        if not isinstance(h, str) or not h.strip():
            raise ValueError(f"{where}: header cell {_letter(c)}{top} is {h!r}: column names must be text")
        names.append(h)
    check_names(where, names)

    rows = [{} for _ in range(top + 1, bottom + 1)]
    cols = []
    for c, name in zip(range(left, right + 1), names):
        raw = [cells.get((r, c)) for r in range(top + 1, bottom + 1)]
        kinds = {}
        for r, v in enumerate(raw, top + 1):
            if v is not None:
                kinds.setdefault(_kind(v), f"{_letter(c)}{r} = {v!r}")
        datatype, text = _column_type(where, name, kinds, [v for v in raw if v is not None])
        for i, v in enumerate(raw):
            rows[i][name] = "" if v is None else text(v)
        cols.append(Column(name, datatype))
    return Table(sheet, f"{_letter(left)}{top}:{_letter(right)}{bottom}", cols, rows)


def _column_type(where, name, kinds, values):
    """-> (datatype, cell value -> the string a CSV would hold)."""
    col = f"{where}: column '{name}'"
    if len(kinds) > 1:
        seen = "; ".join(f"{k} (e.g. {e})" for k, e in sorted(kinds.items()))
        raise ValueError(f"{col} mixes {seen}. Desktop types a column by its cells and reads the others as null "
                         f"(text in a number column became null): make the column one type")
    kind = next(iter(kinds), "string")
    if kind == "boolean":
        raise ValueError(f"{col} is TRUE/FALSE: boolean columns are not supported yet (no golden pattern); "
                         f"write them as text")
    if kind == "time":
        raise ValueError(f"{col} holds times of day or durations without a date: not supported")
    if kind == "number":
        if all(float(v).is_integer() for v in values):
            return "integer", lambda v: str(int(v))
        return "real", lambda v: repr(float(v))
    if kind == "datetime":
        if all(_second(v).time() == dt.time() for v in values):
            return "date", lambda v: _second(v).date().isoformat()
        return "datetime", lambda v: _second(v).isoformat(sep=" ")
    return "string", str


# ---- the datasource: one sheet, a union, a join -------------------------------------------------------------------
def _with_distinct(cols, rows):
    return [Column(c.name, c.datatype, sorted({r[c.name] for r in rows if r[c.name] != ""})
                   if c.datatype == "string" else []) for c in cols]


def profile_excel(path, sheet, union=None, join=None) -> ExcelProfile:
    path = Path(path)
    book = _Book(path)
    if sheet is None:
        raise ValueError(f"{path.name}: choose the sheet with the data ('sheet' in the datasource, --sheet in the "
                         f"CLI): {book.names}")
    if union is not None and join is not None:
        raise ValueError(f"{path.name}: 'union' and 'join' together are not supported yet (no Desktop pattern)")
    first = _table(book, sheet)
    if union is not None:
        return _union(path, [first] + [_table(book, s) for s in union])
    if join is not None:
        return _join(path, first, _table(book, join["sheet"]), join["how"], join["on"])
    cols = _with_distinct(first.columns, first.rows)
    return ExcelProfile(path, cols, first.rows, sheet=sheet, grid=first.grid, tables=[first],
                        fields=[Field(c.name, sheet, c.name) for c in cols])


def _union(path, tables):
    """Sheets one under another (ref_union.twb). The same columns with the same types on every sheet: Desktop
    matches them by name, a column missing on a sheet or typed otherwise is not checked in Desktop."""
    names = [t.sheet for t in tables]
    where = f"{path.name}, union {names}"
    if len(set(names)) != len(names):
        raise ValueError(f"{where}: a sheet is listed twice")
    base = {c.name: c.datatype for c in tables[0].columns}
    for extra in UNION_COLUMNS:
        if extra in base:
            raise ValueError(f"{where}: sheet '{tables[0].sheet}' has a column '{extra}': Desktop adds its own "
                             f"'{extra}' to a union (rename the column)")
    for t in tables[1:]:
        types = {c.name: c.datatype for c in t.columns}
        if set(types) != set(base):
            raise ValueError(f"{where}: sheet '{t.sheet}' has the columns {sorted(types)}, sheet "
                             f"'{tables[0].sheet}' {sorted(base)}: a union needs the same columns on every sheet")
        for n, typ in types.items():
            if typ != base[n]:
                raise ValueError(f"{where}: column '{n}' is {base[n]} on sheet '{tables[0].sheet}' and {typ} on "
                                 f"'{t.sheet}': a union needs one type per column")
    rows = [{**r, **{extra: t.sheet for extra in UNION_COLUMNS}} for t in tables for r in t.rows]
    cols = _with_distinct(tables[0].columns + [Column(n, "string") for n in UNION_COLUMNS], rows)
    union_name = f"{tables[0].sheet}+"
    return ExcelProfile(path, cols, rows, sheet=tables[0].sheet, grid=tables[0].grid, kind="union", tables=tables,
                        fields=[Field(c.name, union_name, c.name) for c in cols])


def _join(path, left, right, how, on):
    """Columns of a second sheet by a key column of the same name (ref-join-left.twb): as SQL joins them, every pair
    of rows with equal keys; with 'left' a row without a match keeps empty right columns. A right column named like
    a left one is '<name> (<right sheet>)', the key too."""
    where = f"{path.name}, join '{left.sheet}' + '{right.sheet}'"
    if how not in JOINS:
        raise ValueError(f"{where}: join type '{how}' is not supported (checked in Desktop: {list(JOINS)})")
    if left.sheet == right.sheet:
        raise ValueError(f"{where}: a sheet joined to itself is not supported")
    lt, rt = ({c.name: c.datatype for c in t.columns} for t in (left, right))
    for t, types in ((left, lt), (right, rt)):
        if on not in types:
            raise ValueError(f"{where}: no key column '{on}' on sheet '{t.sheet}'. Columns: {list(types)}")
    if lt[on] != rt[on]:
        raise ValueError(f"{where}: key '{on}' is {lt[on]} on '{left.sheet}' and {rt[on]} on '{right.sheet}'")
    if lt[on] not in JOIN_KEYS:
        raise ValueError(f"{where}: key '{on}' is {lt[on]}: a join key must be text or a whole number")
    keys = {}  # Desktop compares text in a case-insensitive collation (LRU_RRU_S2): keys differing in case refused
    for t in (left, right):
        for r in t.rows:
            k = r[on]
            if k != k.strip():
                raise ValueError(f"{where}: key '{on}' = {k!r} on sheet '{t.sheet}' has spaces around it: not "
                                 f"checked how Desktop matches it, trim the keys")
            keys.setdefault(k.casefold(), set()).add(k)
    for variants in keys.values():
        if len(variants) > 1:
            raise ValueError(f"{where}: keys {sorted(variants)} differ only in case: Desktop matches them as one "
                             f"key (case-insensitive collation), make them the same")
    fields = [Field(c.name, left.sheet, c.name) for c in left.columns]
    for c in right.columns:
        local = f"{c.name} ({right.sheet})" if c.name in lt else c.name
        if local in lt:
            raise ValueError(f"{where}: column '{c.name}' of '{right.sheet}' would be named '{local}', which "
                             f"'{left.sheet}' already has")
        fields.append(Field(local, right.sheet, c.name))
    check_names(where, [f.local for f in fields])
    by_key = {}
    for r in right.rows:
        if r[on] != "":  # an empty key matches nothing
            by_key.setdefault(r[on], []).append(r)
    right_fields = fields[len(left.columns):]
    rows = []
    for r in left.rows:
        matches = by_key.get(r[on], []) if r[on] != "" else []
        if not matches and how == "left":
            matches = [{f.remote: "" for f in right_fields}]
        rows += [{**r, **{f.local: m[f.remote] for f in right_fields}} for m in matches]
    types = {**lt, **{f.local: rt[f.remote] for f in right_fields}}
    cols = _with_distinct([Column(f.local, types[f.local]) for f in fields], rows)
    return ExcelProfile(path, cols, rows, sheet=left.sheet, grid=left.grid, kind="join", tables=[left, right],
                        fields=fields, how=how, on=on)


# ---- XML (decisions/025: out/excel_lab/ref_excel.twbx; 050: out/excel_v2_lab, Desktop 2025.1 Save As) -------------
def caption(prof):
    """Datasource caption: Desktop names it '<sheet> (<file name>)', '<first sheet>+ (<file name>)' for a union or a
    join."""
    return f"{prof.sheet}{'+' if prof.kind != 'table' else ''} ({prof.path.stem})"


def connection(named, b):
    """The Excel connection inside the named connection; the file is the packaged one, path in 'filename'."""
    ET.SubElement(named, "connection", {"class": "excel-direct", "cleaning": "no", "compat": "no",
                                        "dataRefreshTime": "", "filename": f"{b.data_dir}/{b.csv_path.name}",
                                        "interpretationMode": "0", "password": "", "server": "", "validate": "no"})


def _grid_origin(table):
    return f"{table.grid}:no:{table.grid}:0"


def _table_relation(parent, b, t):
    rel = ET.SubElement(parent, "relation", connection=b.conn, name=t.sheet, table=f"[{t.sheet}$]", type="table")
    cols = ET.SubElement(rel, "columns", gridOrigin=_grid_origin(t), header="yes", outcome=OUTCOME)
    for i, c in enumerate(t.columns):
        ET.SubElement(cols, "column", datatype=c.datatype, name=c.name, ordinal=str(i))
    return rel


def relation(parent, b):
    p = b.prof
    if p.kind == "union":
        rel = ET.SubElement(parent, "relation", {"all": "true", "name": f"{p.sheet}+", "type": "union"})
        cols = ET.SubElement(rel, "columns", header="yes")
        for c in p.columns:
            ET.SubElement(cols, "column", datatype=c.datatype, name=c.name)
    elif p.kind == "join":
        rel = ET.SubElement(parent, "relation", {"join": p.how, "type": "join"})
        eq = ET.SubElement(ET.SubElement(rel, "clause", type="join"), "expression", op="=")
        for t in p.tables:
            ET.SubElement(eq, "expression", op=f"[{t.sheet}].[{p.on}]")
    else:
        return _table_relation(parent, b, p.tables[0])
    for t in p.tables:
        _table_relation(rel, b, t)
    return rel


def cols(parent, b):
    """A join's map from each field to its sheet's column, sorted by field as Desktop writes it."""
    if b.prof.kind != "join":
        return
    el = ET.SubElement(parent, "cols")
    for f in sorted(b.prof.fields, key=lambda f: f"[{f.local}]"):
        ET.SubElement(el, "map", key=f"[{f.local}]", value=f"[{f.sheet}].[{f.remote}]")


def _capability(recs, parent, table=None):
    cap = ET.SubElement(recs, "metadata-record", {"class": "capability"})
    for tag, text in [("remote-name", None), ("remote-type", "0"), ("parent-name", parent), ("remote-alias", None),
                      ("aggregation", "Count"), ("contains-null", "true")]:
        ET.SubElement(cap, tag).text = text
    if table is None:  # a union: no reading options of its own
        return
    attrs = ET.SubElement(cap, "attributes")
    for datatype, name, text in [("integer", "context", "0"), ("string", "gridOrigin", f'"{_grid_origin(table)}"'),
                                 ("boolean", "header", "true"), ("integer", "outcome", OUTCOME)]:
        ET.SubElement(attrs, "attribute", datatype=datatype, name=name).text = text


def metadata(recs, b):
    """Capability records (each sheet's grid; one bare record for a union) and one record per column, in Desktop's
    element order. A union's column records have neither precision nor DebugRemoteType (ref_union.twb)."""
    p = b.prof
    union = p.kind == "union"
    if union:
        _capability(recs, f"[{p.sheet}+]")
    else:
        for t in p.tables:
            _capability(recs, f"[{t.sheet}]", t)
    for i, (c, f) in enumerate(zip(p.columns, p.fields)):
        r = ET.SubElement(recs, "metadata-record", {"class": "column"})
        remote, debug = REMOTE[c.datatype]
        if union and c.name in UNION_COLUMNS:
            remote = UNION_REMOTE
        for tag, text in [("remote-name", f.remote), ("remote-type", remote), ("local-name", f"[{f.local}]"),
                          ("parent-name", f"[{f.sheet}]"), ("remote-alias", f.remote), ("ordinal", str(i)),
                          ("local-type", c.datatype), ("aggregation", AGGREGATION[c.datatype])]:
            ET.SubElement(r, tag).text = text
        if c.datatype == "real" and not union:
            ET.SubElement(r, "precision").text = "15"
        ET.SubElement(r, "contains-null").text = "true"
        if c.datatype == "string":
            ET.SubElement(r, "collation", flag="1", name=STRING_COLLATION[b.locale])
        if not union:
            ET.SubElement(ET.SubElement(r, "attributes"), "attribute", datatype="string",
                          name="DebugRemoteType").text = f'"{debug}"'
        ET.SubElement(r, "object-id").text = f"[{b.obj_id}]"
