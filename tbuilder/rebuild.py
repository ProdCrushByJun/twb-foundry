"""Rebuild a workbook into our archetype: its structure -> spec.json -> the generator (todo 6.2, decisions/053).

  python -m tbuilder rebuild <in.twbx|.twb> -o <spec.json> [--data <file.csv>]

The .twb is only read. Every worksheet our spec schema can draw with the same numbers becomes a sheet of a new
spec.json: the mark, the shelves (rows / columns / color / text / detail), the aggregations, the filters, the
calculated fields with their formulas, the parameters, the dashboard zones as a grid. The data becomes a CSV next to
the spec: the extract (.hyper) or the text file packaged with the book; an Excel file is copied. A live source with no
extract is an error. Our design system replaces the book's look (fonts, colors, number formats, tooltips).

"The same numbers" is the rule for a sheet: everything that decides its marks (dimensions, date levels, measures,
filters, Top N, calcs, parameters) must have a place in the schema. A sheet with anything else is not rebuilt; what
does not change the numbers (labels, a color by its own measure, sorting by another field, actions, panels drawn as
colors) is dropped from a rebuilt sheet. Both are listed in the report ("not rebuilt"), never dropped silently.

Archetypes (the sheet's shelves after the instance of each field is read from its column-instance):
  kpi       no dimension, no axis: the measures on Text (or Measure Values with the Measure Names filter)
  bar       one dimension against one aggregated measure axis; a dimension on Color splits the bars; Top N, sort
  line/area a truncated date (or YEAR) against one measure axis; a dimension on Color or as panels is the series
  table     dimensions on Rows (1-2) and Columns (1), one measure as text; heatmap: square marks colored by it
  registry  dimensions on one shelf, measures as text (several via Measure Values)
  map       generated Latitude / Longitude, one geographic dimension on Detail: filled by Color, symbol by Size
"""
import csv
import decimal
import json
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import excel, expected, registry, spec as spec_mod

AGG = {"Sum": "sum", "Avg": "avg", "Min": "min", "Max": "max", "Count": "count", "CountD": "countd"}
LABEL = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "count": "COUNT", "countd": "COUNTD"}
# continuous truncations and the discrete YEAR: one mark per period, the keys expected.py gives a date level
LEVEL = {"Year-Trunc": "year", "Quarter-Trunc": "quarter", "Month-Trunc": "month", "Week-Trunc": "week",
         "Day-Trunc": "day", "Year": "year"}
# the builder declares weeks from Monday (formula.START_OF_WEEK); a week sheet keeps its numbers only if the book's
# weeks start on Monday too: explicit date-options, or a locale whose weeks start on Monday (en_US: Sunday)
MONDAY_LOCALES = ("ru", "de", "fr", "it", "es_ES", "en_GB", "en_IE", "nl", "pl", "sv", "fi", "da", "nb", "cs", "uk",
                  "pt_PT", "tr", "hu", "ro", "sk", "sl", "hr", "sr", "bg", "lt", "lv", "et", "el")
FILE_SOURCES = {"textscan", "excel-direct", "hyper", "dataengine"}
GEO_ROLES = {"[State].[Name]": "state", "[Country].[ISO3166_2]": "country", "[Country].[Name]": "country",
             "[City].[Name]": "city"}
UNSAFE = re.compile(r"[\[\]'\"<>&]")  # objectName / CSV header: no XML- or Tableau-reference-unsafe characters
_SHELF_REF = re.compile(r"\[(?:[^\]]|\]\])*\]\.\[(?:[^\]]|\]\])*\]")
_FORMULA_TOKEN = re.compile(r"""("(?:[^"]|"")*"|'(?:[^']|'')*')|(//[^\n]*)|(\[Parameters\]\.\[(?:[^\]]|\]\])+\])"""
                            r"""|(\[(?:[^\]]|\]\])+\])""")
GRID_MAX = 6  # rows of a grid, cells of a row (spec.schema.json)
CHECK_ERRORS = (ValueError, KeyError, TypeError)  # what the builder / expected.py raise on a spec they cannot take


class RebuildError(ValueError):
    """The book cannot be rebuilt at all (live source, no data file, no sheet the schema covers)."""

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class Skip(Exception):
    """A sheet the schema cannot draw with the same numbers: the reason."""


@dataclass
class Report:
    source: str
    rebuilt: list = field(default_factory=list)  # (sheet, what it became)
    skipped: list = field(default_factory=list)  # (sheet, reason): not rebuilt
    lost: list = field(default_factory=list)  # (where, what): rebuilt without it
    spec_path: Path = None
    data_path: Path = None
    rows: int = 0

    def text(self):
        n = len(self.rebuilt) + len(self.skipped)
        out = [f"{self.source}: {len(self.rebuilt)} of {n} sheets rebuilt"
               + (f" -> {self.spec_path}, data {self.data_path} ({self.rows} rows)" if self.spec_path else "")]
        out += [f"  rebuilt  {s}: {what}" for s, what in self.rebuilt]
        if self.skipped or self.lost:
            out.append("not rebuilt:")
            out += [f"  sheet '{s}': {why}" for s, why in self.skipped]
            out += [f"  {where}: {what}" for where, what in self.lost]
        return "\n".join(out)


# ---- the book ------------------------------------------------------------------------------------------------------
@dataclass
class Fld:
    key: str  # local name as the XML writes it: [Sales], [Calculation_1]
    name: str  # name in the spec (caption or local name, made safe)
    datatype: str = "string"
    role: str = "dimension"
    formula: str = None  # a calculated field's formula (book names)
    calc_class: str = None  # tableau | categorical-bin | bin | ...
    table: str = None  # a data column's table (metadata-record parent-name)
    remote: str = None  # a data column's name in that table
    semantic: str = None

    @property
    def is_calc(self):
        return self.calc_class is not None


@dataclass
class Par:
    key: str  # [Parameter 1]
    name: str
    spec: dict = None  # the spec parameter, or None with the reason
    reason: str = ""


def _unbracket(key):
    return key[1:-1].replace("]]", "]")


def _attr_text(el):
    return "".join(r.text or "" for r in el.iter("run"))


class Book:
    def __init__(self, path, tmp):
        self.path, self.tmp = Path(path), Path(tmp)
        if self.path.suffix.lower() == ".twbx":
            self.zip = zipfile.ZipFile(self.path)
            twbs = [n for n in self.zip.namelist() if n.lower().endswith(".twb") and "/" not in n]
            if len(twbs) != 1:
                raise RebuildError(f"{self.path.name}: expected one .twb in the package root, found {twbs}")
            self.root = ET.fromstring(self.zip.read(twbs[0]))
        elif self.path.suffix.lower() == ".twb":
            self.zip = None
            self.root = ET.parse(self.path).getroot()
        else:
            raise RebuildError(f"{self.path.name}: not a .twb or .twbx")
        sources = [d for d in self.root.findall("datasources/datasource") if d.get("name") != "Parameters"]
        if not sources:
            raise RebuildError(f"{self.path.name}: the book has no data source")
        used = Counter(d.get("name") for w in self.root.findall("worksheets/worksheet")
                       for d in w.findall("table/view/datasources/datasource") if d.get("name") != "Parameters")
        self.ds = max(sources, key=lambda d: used.get(d.get("name"), 0))  # the one most sheets use
        self.ds_name = self.ds.get("name")
        self.others = [d.get("caption") or d.get("name") for d in sources if d is not self.ds]
        self.extract = self.ds.find("extract[@enabled='true']")
        self.params = self._params()
        self.fields = self._fields()

    # the files of the book
    def file(self, name):
        """A file the XML names (package member, or next to a .twb / absolute): its local path, or None."""
        name = name.replace("\\", "/")
        if self.zip is not None:
            members = {m.replace("\\", "/"): m for m in self.zip.namelist()}
            member = members.get(name) or next((m for k, m in members.items()
                                                if name.endswith("/" + k) or k.endswith("/" + name)), None)
            return Path(self.zip.extract(member, self.tmp)) if member else None
        for p in (self.path.parent / name, Path(name)):
            if p.is_file():
                return p
        return None

    def _params(self):
        out = {}
        ds = self.root.find("datasources/datasource[@name='Parameters']")
        for c in ds.findall("column") if ds is not None else []:
            out[c.get("name")] = _param(c)
        return out

    def _fields(self):
        out = {}
        conn = self.extract.find("connection") if self.extract is not None else self.ds.find("connection")
        for r in conn.iter("metadata-record") if conn is not None else []:
            if r.get("class") != "column" or r.findtext("local-name") is None:
                continue
            key = r.findtext("local-name")
            parent = r.findtext("parent-name")
            out[key] = Fld(key, _unbracket(key), r.findtext("local-type") or "string",
                           table=_unbracket(parent) if parent else None, remote=r.findtext("remote-name"))
        columns = list(self.ds.findall("column"))
        for w in self.root.findall("worksheets/worksheet"):  # calcs typed on a shelf live in the sheet only
            for d in w.findall("table/view/datasource-dependencies"):
                if d.get("datasource") == self.ds_name:
                    columns += [c for c in d.findall("column") if c.find("calculation") is not None
                                and c.get("name") not in out]
        for c in columns:
            key = c.get("name")
            if key is None or key.startswith("[__tableau_internal") or key == "[:Measure Names]":
                continue
            f = out.setdefault(key, Fld(key, _unbracket(key)))
            f.datatype = c.get("datatype", f.datatype)
            f.role = c.get("role", f.role)
            f.semantic = c.get("semantic-role", f.semantic)
            if c.get("caption"):
                f.name = c.get("caption")
            calc = c.find("calculation")
            if calc is not None:
                f.calc_class, f.formula = calc.get("class", "tableau"), calc.get("formula")
        taken = {p.name for p in self.params.values()}
        self.renamed = []
        for f in out.values():  # spec names: safe, unique (parameters included: [Name] must not be ambiguous)
            name = UNSAFE.sub("_", f.name).strip() or "Field"
            base, i = name, 2
            while name in taken:
                name, i = f"{base} ({i})", i + 1
            if name != f.name:
                self.renamed.append((f.name, name))
            f.name = name
            taken.add(name)
        return out

    def by_name(self):
        return {f.name: f for f in self.fields.values()}

    # calculated fields
    def translate(self, formula):
        """A book formula with the spec's names: [Calculation_1] -> [Profit Ratio], [Parameters].[Parameter 1] ->
        [Parameters].[Year]; comments dropped."""
        def sub(m):
            s, comment, par, ref = m.groups()
            if s:
                return s
            if comment:
                return ""
            if par:
                p = self.params.get(par[len("[Parameters]."):])
                return f"[Parameters].[{p.name}]" if p else par
            f = self.fields.get(ref)
            return f"[{f.name}]" if f else ref
        return _FORMULA_TOKEN.sub(sub, formula).strip()

    def refs(self, f):
        """(fields, parameter keys) a calculated field's formula names directly."""
        flds, pars = [], []
        for m in _FORMULA_TOKEN.finditer(f.formula or ""):
            s, comment, par, ref = m.groups()
            if par:
                pars.append(par[len("[Parameters]."):])
            elif ref and ref in self.fields:
                flds.append(self.fields[ref])
        return flds, pars

    def closure(self, flds):
        """The fields with every field their formulas need (transitively), and the parameter keys."""
        seen, pars, todo = {}, set(), list(flds)
        while todo:
            f = todo.pop()
            if f.key in seen:
                continue
            seen[f.key] = f
            if f.is_calc:
                sub, ps = self.refs(f)
                todo += sub
                pars |= set(ps)
        return list(seen.values()), pars

    def derived(self, name, formula, datatype):
        """A calculated field rebuild writes itself (decisions/060): a unique safe spec name, the formula in the
        book's names (translate gives the spec's). The same name gives the same field."""
        key = f"[rebuild:{name}]"
        if key not in self.fields:
            taken = {f.name for f in self.fields.values()} | {p.name for p in self.params.values()}
            new, i = name, 2
            while new in taken:
                new, i = f"{name} ({i})", i + 1
            self.fields[key] = Fld(key, new, datatype, formula=formula, calc_class="tableau")
        return self.fields[key]

    def week_start(self):
        opts = self.ds.find("date-options")
        if opts is not None and opts.get("start-of-week"):
            return opts.get("start-of-week")
        locale = next((c.get("author-locale") for c in self.ds.iter("connection") if c.get("author-locale")),
                      self.root.get("locale") or "")
        return "monday" if locale.startswith(MONDAY_LOCALES) else "sunday"

    def fiscal_start(self):
        opts = self.ds.find("date-options")
        return int(opts.get("fiscal-year-start", "1")) if opts is not None else 1


def _literal(v):
    """A Tableau literal of a parameter or a filter member: "East" / 'East' -> East, #2015-12-31# -> date text."""
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1].replace(v[0] * 2, v[0])
    if len(v) >= 2 and v[0] == v[-1] == "#":
        return v[1:-1]
    return v


def _param(c):
    key, name = c.get("name"), UNSAFE.sub("_", c.get("caption") or _unbracket(c.get("name"))).strip()
    p = Par(key, name)
    datatype, domain = c.get("datatype"), c.get("param-domain-type")
    default = _literal(c.get("value"))
    members = [_literal(m.get("value")) for m in c.findall("members/member")]
    # string / integer / real / date values and ranges, boolean true / false (decisions/020, 057)
    typed = {"string": str, "integer": lambda v: int(float(v)), "real": float, "date": lambda v: v[:10],
             "boolean": lambda v: v == "true"}.get(datatype)
    r = c.find("range")
    if typed is None or (datatype == "date" and any(len(v) > 10 for v in [default] + members)):
        p.reason = f"a {datatype} parameter (the schema: string, integer, real, date, boolean)"
    elif any(m.get("alias") for m in c.findall("members/member")) or c.find("aliases/alias") is not None:
        p.reason = "a list with aliases (the schema shows the values)"
    elif datatype == "boolean":
        p.spec = {"name": name, "type": "boolean", "default": typed(default)}
    elif domain == "list" and datatype != "boolean":
        p.spec = {"name": name, "type": datatype, "values": [typed(m) for m in members], "default": typed(default)}
    elif domain == "range" and datatype in ("integer", "real", "date") and r is not None:
        if r.get("min") is None or r.get("max") is None:
            p.reason = "a range without min or max"
        elif datatype == "real" and r.get("granularity") is None:
            p.reason = "a real range without a step (the schema's real range has one)"
        else:
            rng = {"min": typed(_literal(r.get("min"))), "max": typed(_literal(r.get("max")))}
            if datatype != "date":
                rng["step"] = typed(r.get("granularity") or 1)
            p.spec = {"name": name, "type": datatype, "default": typed(default), "range": rng}
    else:
        p.reason = f"{datatype} with a {domain or 'free'} domain (the schema: a list of values or a range)"
    return p


# ---- data ----------------------------------------------------------------------------------------------------------
def _source_kind(book):
    """('hyper', path, table names) | ('csv', path, connection) | ('excel', path, sheet); live -> RebuildError."""
    if book.extract is not None:
        conn = book.extract.find("connection")
        name = conn.get("dbname") if conn is not None else None
        path = book.file(name) if name else None
        if path is None:
            raise RebuildError(f"the extract {name!r} is not in the package")
        return "hyper", path, None
    named = [c for c in book.ds.findall("connection/named-connections/named-connection/connection")] or \
        [c for c in book.ds.findall("connection") if c.get("class") != "federated"]
    classes = sorted({c.get("class") for c in named})
    live = [c for c in classes if c not in FILE_SOURCES]
    if live or not named:
        raise RebuildError(f"live source {', '.join(live) or 'without a connection'} is not supported: the rebuild "
                           f"needs the data as a file (an extract or a CSV / Excel / Hyper file in the package)")
    if len(named) > 1:
        raise RebuildError(f"{len(named)} connections in one data source (a join or union of files) are not "
                           f"supported")
    c = named[0]
    cls, rel = c.get("class"), book.ds.find(".//relation[@table]")
    name = c.get("dbname") if cls in ("hyper", "dataengine") else \
        "/".join(x for x in (c.get("directory"), c.get("filename")) if x)
    path = book.file(name) or (book.file(c.get("filename")) if c.get("filename") else None)
    if path is None:
        raise RebuildError(f"the data file {name!r} is not in the package")
    if cls == "textscan":
        return "csv", path, c
    if cls == "excel-direct":
        return "excel", path, _unbracket(rel.get("table")).rstrip("$") if rel is not None else None
    return "hyper", path, None


def _hyper_tables(path):
    """{table name (no schema): (columns [(name, type)], rows [tuple])} of a .hyper file."""
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    out = {}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""}) as hp:
        with Connection(hp.endpoint, str(path)) as con:
            for schema in con.catalog.get_schema_names():
                for t in con.catalog.get_table_names(schema):
                    cols = con.catalog.get_table_definition(t).columns
                    rows = con.execute_list_query(f"SELECT * FROM {t}")
                    out[t.name.unescaped] = ([(c.name.unescaped, str(c.type)) for c in cols], rows)
    return out


def _cell(v):
    """A Hyper value as CSV text the profiler reads back with the same type (dates ISO, reals not in e-notation)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return format(decimal.Decimal(repr(v)), "f")
    if isinstance(v, (int, str, decimal.Decimal)):
        return str(v)
    if hasattr(v, "to_datetime"):  # tableauhyperapi Timestamp
        return v.to_datetime().isoformat(sep=" ")
    if hasattr(v, "to_date"):  # tableauhyperapi Date
        return v.to_date().isoformat()
    raise TypeError(type(v).__name__)


def _choose_table(book, report, plans):
    """The one table the rebuilt sheets read: the table most sheets take data columns from (then: most columns). A
    sheet with columns of another table (a relationship or a join) is not rebuilt."""
    tables = {name: {f.table for f in flds if not f.is_calc and f.table} for name, (flds, _) in plans.items()}
    sheets = Counter(t for ts in tables.values() for t in ts)
    columns = Counter(f.table for flds, _ in plans.values() for f in {x.key: x for x in flds}.values()
                      if not f.is_calc and f.table)
    main = max(sheets, key=lambda t: (sheets[t], columns[t])) if sheets else None
    for name, ts in tables.items():
        if ts - {main}:
            other = sorted({f"{f.name} ({_table_name(f.table)})" for f in plans[name][0]
                            if not f.is_calc and f.table not in (None, main)})
            plans.pop(name)
            report.skipped.append((name, f"{', '.join(other)} beside {_table_name(main)}: related tables are one "
                                         f"table in the schema"))
    return main


def _table_name(t):
    """A logical table's name without the object id Tableau appends ('Orders.csv_011D63...')."""
    return re.sub(r"_[0-9A-F]{32}$", "", t or "")


def write_data(book, report, main, out):
    """The data as a file next to the spec: (path, spec datasource). main: the table of the rebuilt sheets."""
    kind, path, extra = _source_kind(book)
    if kind == "excel":  # copied as it is: the header row gives the names
        dest = out.with_suffix(".xlsx")
        dest.write_bytes(path.read_bytes())
        return dest, {"type": "excel", "path": None, "sheet": extra or main}
    by_remote = {}
    if kind == "hyper":
        tables = _hyper_tables(path)
        table = main if main in tables else next(iter(tables)) if len(tables) == 1 else None
        if table is None:
            raise RebuildError(f"cannot tell which of the extract's tables {sorted(tables)} is the data")
        columns, rows = tables[table]
        for f in book.fields.values():
            if not f.is_calc and f.remote and (f.table in (None, table) or len(tables) == 1):
                by_remote.setdefault(f.remote, f)
        header = [by_remote[c].name if c in by_remote else UNSAFE.sub("_", c) for c, _ in columns]
        lost = [(c, t) for c, t in columns if t.startswith("GEOGRAPHY")]
        if lost:
            report.lost.append(("data", f"geography columns {[c for c, _ in lost]}"))
        keep = [i for i, (c, t) in enumerate(columns) if not t.startswith("GEOGRAPHY")]
        text_rows = [[_cell(r[i]) for i in keep] for r in rows]
        header = [header[i] for i in keep]
    else:  # a text file: re-written with a comma, the header in the spec's names
        sep = {"\\t": "\t", "": ","}.get(extra.get("separator", ","), extra.get("separator", ","))
        with open(path, encoding=extra.get("charset") or "utf-8-sig", newline="") as fh:
            src = list(csv.reader(fh, delimiter=sep))
        for f in book.fields.values():
            if not f.is_calc and f.remote:
                by_remote.setdefault(f.remote, f)
        header = [by_remote[c].name if c in by_remote else UNSAFE.sub("_", c) for c in src[0]]
        text_rows = src[1:]
    dest = out.with_suffix(".csv")
    with open(dest, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(text_rows)
    _data_notes(report, header, text_rows)
    return dest, {"type": "csv", "path": None}


def _data_notes(report, header, rows):
    """Values a CSV reads differently from the book's source: spaces around text (the text connector trims them),
    members that differ only in letter case (an extract's case-insensitive collation groups them)."""
    spaced, cased = [], []
    for i, h in enumerate(header):
        values = {r[i] for r in rows if r[i]}
        if any(v != v.strip(" ") for v in values):
            spaced.append(h)
        if len({v.casefold() for v in values}) < len(values):
            cased.append(h)
    if spaced:
        report.lost.append(("data", f"spaces around the text values of {spaced}: the text connector trims them"))
    if cased:
        report.lost.append(("data", f"values of {cased} that differ only in letter case: the book may group them, "
                                    f"the CSV keeps them apart"))


# ---- worksheets ----------------------------------------------------------------------------------------------------
@dataclass
class Item:
    kind: str  # dim | date | measure | names | values | geo | param | other
    fld: Fld = None
    agg: str = None  # measure: sum ... countd; None = an aggregate calc
    level: str = None  # date
    tc: str = None  # a quick table calc on the measure
    ref: str = ""
    tcx: object = None  # its <table-calc> element (a Rank's options and direction: decisions/086)

    def measure(self):
        m = {"field": self.fld.name}
        if self.agg in ("sum", "avg", "min", "max") and self.fld.datatype not in ("integer", "real"):
            raise Skip(f"{self.ref}: an aggregate of a {self.fld.datatype} (the schema's measures are numbers)")
        if self.agg and self.agg != "sum":
            m["agg"] = self.agg
        elif self.agg is None and not self.fld.is_calc:
            raise Skip(f"{self.ref}: an aggregate without a function")
        return m

    def label(self):
        return f"AGG({self.fld.name})" if self.agg is None else f"{LABEL[self.agg]}({self.fld.name})"

    def same(self, other):
        return other is not None and (self.kind, self.fld and self.fld.key, self.agg, self.level) == \
            (other.kind, other.fld and other.fld.key, other.agg, other.level)


class Sheet:
    """A worksheet's shelves, marks and filters, each field read through its column-instance."""

    def __init__(self, book, ws):
        self.book, self.ws, self.name = book, ws, ws.get("name")
        self.view = ws.find("table/view")
        self.lost = []
        self.params = set()  # parameter keys the sheet uses outside its fields' formulas (a Top N's N)
        self.instances = {}
        for d in self.view.findall("datasource-dependencies"):
            for ci in d.findall("column-instance"):
                self.instances[(d.get("datasource"), ci.get("name"))] = ci
        ds = {d.get("name") for d in self.view.findall("datasources/datasource")} - {"Parameters"}
        self.foreign = sorted(ds - {book.ds_name})

    def item(self, ref):
        m = re.match(r"^\[((?:[^\]]|\]\])*)\]\.\[((?:[^\]]|\]\])*)\]$", ref)
        if not m:
            return Item("other", ref=ref)
        ds, inst = m.group(1).replace("]]", "]"), f"[{m.group(2)}]"
        if ds == "Parameters":
            return Item("param", ref=ref)
        if inst == "[:Measure Names]":
            return Item("names", ref=ref)
        if inst == "[Multiple Values]":
            return Item("values", ref=ref)
        if inst in ("[Latitude (generated)]", "[Longitude (generated)]", "[Geometry (generated)]"):
            return Item("geo", ref=inst)
        ci = self.instances.get((ds, inst))
        f = self.book.fields.get(ci.get("column")) if ci is not None else None
        if f is None:
            return Item("other", ref=_unbracket(inst))
        der, qk = ci.get("derivation"), ci.get("type") == "quantitative"
        tc = ci.find("table-calc")
        label = f"{der.upper()}({f.name})" if der not in (None, "None", "User") else f.name
        if tc is not None:  # a quick table calc: percent of total, rank, running total ... of the aggregate
            kind = tc.get("type") or "table calculation"
            return Item("measure", f, AGG.get(der), tc=kind, ref=f"{label} ({kind})", tcx=tc)
        if der in AGG:
            return Item("measure", f, AGG[der], ref=label)
        if der == "User":
            return Item("measure", f, None, ref=f.name)
        if der in LEVEL:
            return Item("date", f, level=LEVEL[der], ref=label)
        if der == "None":
            if f.datatype in ("date", "datetime"):  # the exact date (a datetime's exact time: no level)
                return Item("date", f, level="day" if f.datatype == "date" else None, ref=f.name)
            if f.is_calc and f.formula and not self.book.closure([f])[0][1:] and self.book.closure([f])[1] \
                    and f.datatype in ("integer", "real"):
                # a calc of parameters only ([Year Parameter]-1): one value on every mark = its MAX (decisions/057)
                self.lost.append(f"{f.name}: a calc of parameters, drawn as MAX({f.name}) (the same value)")
                return Item("measure", f, "max", ref=f"MAX({f.name})")
            if qk or f.role == "measure":
                return Item("other", f, ref=f"{f.name} (not aggregated)")
            return Item("dim", f, ref=f.name)
        return Item("other", f, ref=label)

    def shelf(self, tag):
        text = self.ws.findtext(f"table/{tag}") or ""
        return [self.item(r) for r in _SHELF_REF.findall(text)], "+" in _SHELF_REF.sub("", text)

    def panes(self):
        out = []
        for p in self.ws.findall("table/panes/pane"):
            mark = p.find("mark")
            enc = {}
            for e in p.findall("encodings/*"):
                enc.setdefault(e.tag, []).append(self.item(e.get("column")))
            out.append((mark.get("class") if mark is not None else "Automatic", enc))
        return out


def _groupfilter_members(g):
    """('all' | 'members' | 'except' | 'other', [members]) of a categorical filter's groupfilter tree."""
    fn = g.get("function")
    if fn == "level-members":
        return "all", []
    if fn == "member":
        return "members", [_literal(g.get("member"))]
    if fn == "union" and all(c.get("function") == "member" for c in g):
        return "members", [_literal(c.get("member")) for c in g]
    if fn == "except" and len(g) == 2 and g[0].get("function") == "level-members":
        kind, members = _groupfilter_members(g[1])
        if kind == "members":
            return "except", members
    return "other", []


@dataclass
class Filt:
    item: Item
    kind: str  # names | top | action | categorical | range | relative | other
    members: list = field(default_factory=list)  # categorical / names
    exclude: bool = False
    noop: bool = False
    context: bool = False
    detail: dict = field(default_factory=dict)
    text: str = ""


def _filter(sheet, f, values_of):
    """One <filter> of a view or a shared view. values_of(Fld) -> the distinct values in the data (None: unknown)."""
    col = f.get("column", "")
    inst = col.split("].[", 1)[-1][:-1] if "].[" in col else col
    g = f.find("groupfilter")
    if inst.startswith(("Action (", "Tooltip (")) or (g is not None and any(
            k.endswith("ui-action-filter") for e in f.iter("groupfilter") for k in e.attrib)):
        allpass = g is None or g.get("function") in ("level-members", "crossjoin") or any(
            k.endswith("ui-enumeration") and v == "all" for k, v in g.attrib.items())
        return Filt(Item("other", ref=inst), "action", noop=allpass, text=f"filter action {inst}")
    item = sheet.item(col)
    context = f.get("context") == "true"
    cls = f.get("class")
    if item.kind == "names":
        refs = [_literal(c.get("member")) for c in f.iter("groupfilter") if c.get("function") == "member"]
        return Filt(item, "names", [sheet.item(r) for r in refs])
    if cls == "categorical" and g is not None and g.get("function") == "end":
        order = g.find("groupfilter[@function='order']")
        inner = order[0] if order is not None and len(order) else None
        detail = {"n": g.get("count", "0"), "end": g.get("end"),
                  "by": order.get("expression") if order is not None else None,
                  "direction": order.get("direction") if order is not None else None,
                  "all": inner is not None and _groupfilter_members(inner)[0] == "all"}
        return Filt(item, "top", detail=detail, context=context, text=f"Top {detail['n']} of {item.ref}")
    if cls == "categorical" and g is not None:
        kind, members = _groupfilter_members(g)
        if kind == "other":
            return Filt(item, "other", context=context, text=f"filter on {item.ref} ({g.get('function')})")
        filt = Filt(item, "categorical", members, kind == "except", context=context,
                    text=f"filter on {item.ref}")
        values = values_of(item.fld) if item.kind == "dim" else None
        if kind == "all":
            filt.noop = True
        elif values is not None:
            kept = set(values) - set(members) if filt.exclude else set(values) & set(members)
            filt.noop = kept == set(values)
        return filt
    if cls == "quantitative":
        lo, hi = f.findtext("min"), f.findtext("max")
        if lo is None and hi is None:
            return Filt(item, "range", noop=True, text=f"range filter on {item.ref} (all values)")
        return Filt(item, "range", context=context, detail={"min": _literal(lo), "max": _literal(hi)},
                    text=f"range filter on {item.ref}")
    if cls == "relative-date":
        return Filt(item, "relative", context=context, detail=dict(f.attrib), text=f"relative date filter on "
                                                                                     f"{item.ref}")
    return Filt(item, "other", context=context, text=f"{cls} filter on {item.ref}")


def _members(f):
    """A filter's members in the spec: text, or true / false of a boolean field."""
    return [m == "true" for m in f.members] if f.item.fld.datatype == "boolean" else list(f.members)


def _number(text):
    v = float(text)
    return int(v) if v.is_integer() and "." not in text and "e" not in text.lower() else v


def _sheet_filter(f):
    """A filter of one sheet -> the spec sheet's own filter (decisions/057): values of a dimension (a column or a
    formula calc), or a range of an aggregate (a measure filter after the aggregation by the sheet's dimensions)."""
    fld = f.item.fld
    if f.context:
        raise Skip(f"{f.text}: a context filter of one sheet (the spec's context filters are shared)")
    if f.kind == "categorical" and f.item.kind == "dim" and (not fld.is_calc or fld.calc_class == "tableau"):
        out = {"field": fld.name, "default": _members(f)}
        if f.exclude:
            out["exclude"] = True
        return out
    if f.kind == "range" and f.item.kind == "measure" and not f.item.tc:
        m = f.item.measure()  # a number, an aggregate (Skip otherwise)
        try:
            bounds = {k: _number(v) for k, v in f.detail.items() if v}
        except ValueError:
            raise Skip(f"{f.text}: bounds {f.detail} are not numbers") from None
        return {**m, **bounds}
    raise Skip(f"{f.text}: a filter of one sheet the schema cannot take (values of a dimension or a range of an "
               f"aggregate)")


def _shared_filters(book, values_of):
    """{filter column: Filt} of the book's filters applied to every sheet of the data source (shared views)."""
    out = {}
    for sv in book.root.findall("shared-views/shared-view"):
        if sv.get("name") != book.ds_name:
            continue
        holder = _Holder(book, sv)
        for f in sv.findall("filter"):
            out[f.get("column")] = _filter(holder, f, values_of)
    return out


class _Holder(Sheet):
    """A shared view read like a sheet: its datasource-dependencies resolve the filter's instance."""

    def __init__(self, book, el):  # noqa: the base reads a worksheet
        self.book, self.lost, self.foreign, self.name, self.params = book, [], [], "(shared)", set()
        self.instances = {(d.get("datasource"), ci.get("name")): ci for d in el.findall("datasource-dependencies")
                          for ci in d.findall("column-instance")}


def _sort(sheet, dim, measure):
    """'asc' / 'desc' when the dimension is sorted by the sheet's measure; None otherwise (dropped and noted)."""
    for s in sheet.view.findall("shelf-sorts/shelf-sort-v2"):
        if sheet.item(s.get("dimension-to-sort", "")).same(dim):
            if measure.same(sheet.item(s.get("measure-to-sort-by", ""))):
                return s.get("direction", "ASC").lower()
            sheet.lost.append("sort by another measure")
    for s in sheet.view.findall("computed-sort") + sheet.view.findall("sort[@class='computed']"):
        if sheet.item(s.get("column", "")).same(dim):
            if s.get("using") and measure.same(sheet.item(s.get("using"))):
                return s.get("direction", "ASC").lower()
            sheet.lost.append(f"sort of {dim.ref} by another field")
    for tag, kind in (("manual-sort", "manual"), ("sort[@class='manual']", "manual"),
                      ("alphabetic-sort", "alphabetic"), ("sort[@class='alphabetic']", "alphabetic")):
        for s in sheet.view.findall(tag):
            if sheet.item(s.get("column", "")).same(dim):
                sheet.lost.append(f"{kind} sort of {dim.ref}")
    return None


def analyze(book, ws, shared, values_of):
    """A worksheet -> its spec sheet (lost details in Sheet.lost), or Skip(reason)."""
    sh = Sheet(book, ws)
    if sh.foreign:
        raise Skip(f"uses the data source {sh.foreign}: the spec has one")
    agg = sh.view.find("aggregation")
    if agg is not None and agg.get("value") == "false":
        raise Skip("measures not aggregated (Analysis > Aggregate Measures off)")
    rows, rows_plus = sh.shelf("rows")
    cols, cols_plus = sh.shelf("cols")
    _buttons(sh, rows + cols)
    panes = sh.panes()
    marks = [m for m, _ in panes]
    enc = {}
    for _, e in panes:
        for k, v in e.items():
            enc.setdefault(k, []).extend(v)
    # filters: the sheet's own and the shared ones it shows (slices)
    filters = [_filter(sh, f, values_of) for f in sh.view.findall("filter")]
    slices = {c.text for c in sh.view.findall("slices/column")}
    filters += [f for col, f in shared.items() if col in slices]
    names = next((f.members for f in filters if f.kind == "names"), [])
    top, rank, own = None, None, []
    for f in filters:
        if f.kind == "names" or any(f is g for g in shared.values()):
            continue  # Measure Names: the measures; a shared filter goes to the spec's filters (_spec_filters)
        if f.kind == "action" and f.noop:
            continue  # the target of an action shows everything at open; the actions are listed once (_actions_lost)
        if f.noop:
            sh.lost.append(f"{f.text} (all values pass when the book opens)")
            continue
        if f.kind == "top":
            top = f
            continue
        if f.item.kind == "measure" and f.item.tc == "Rank" and f.kind == "categorical" and rank is None:
            rank = f  # ranks 1..N: Top N after the filters (decisions/086), checked against the sheet in _rank_top
            continue
        if f.item.kind == "measure" and f.item.tc:
            raise Skip(f"{f.text}: a filter on a table calculation")
        own.append((_sheet_filter(f), f.item))  # the sheet's own filter (decisions/057)
    ranked = []  # the rank on a shelf (a public book: on Rows before City, its header hidden) orders the bars
    if rank is not None:
        ranked = [i for i in rows + cols if i.kind == "measure" and i.tc == "Rank" and i.same(rank.item)]
        rows = [i for i in rows if not any(i is j for j in ranked)]
        cols = [i for i in cols if not any(i is j for j in ranked)]
    if enc.pop("tooltip", None):
        sh.lost.append("tooltip fields")
    every = rows + cols + [i for k, v in enc.items() if k in ("text", "label", "lod", "color") for i in v] + names
    flds, par_keys = book.closure([i.fld for i in every + [i for _, i in own] if i.fld])
    for f in flds:
        if f.is_calc and (f.calc_class != "tableau" or not f.formula):
            raise Skip(f"'{f.name}': a {f.calc_class} field (a group or bin; the schema takes formulas)")
    for k in sorted(par_keys):
        p = book.params.get(k)
        if p is None or p.spec is None:
            raise Skip(f"parameter '{p.name if p else k}': {p.reason if p else 'not in the book'}")
    bad = [i.ref for i in every if i.kind in ("other", "param")]
    if bad:
        raise Skip(f"fields the schema cannot read: {', '.join(dict.fromkeys(bad))}")
    spec = _archetype(sh, rows, cols, rows_plus or cols_plus, marks, enc, names, top)
    if rank is not None:
        _rank_top(spec, rank, ranked, top, sh)
    if own:
        spec["filters"] = [s for s, _ in own]
    for k, items in enc.items():  # what the archetype did not take
        if items:
            sh.lost.append(f"{k} {', '.join(dict.fromkeys(i.ref for i in items))}")
    title = _title(ws)
    if title:
        spec["title"] = title
    return spec, sh


def _buttons(sh, shelves):
    """A sheet of buttons (a public book's Years Button): a constant calc on an axis (AVG(0)) only places the marks, and the
    sheet is the source of actions. Its click is the point: Skip with what it does (decisions/086)."""
    const = [i for i in shelves if i.kind == "measure" and i.fld.is_calc and i.fld.formula
             and len(sh.book.closure([i.fld])[0]) == 1 and not sh.book.closure([i.fld])[1]]
    every = sh.book.root.find("actions")
    acts = [] if every is None else [a for a in every if any(s.get("worksheet") == sh.name for s in a.iter("source"))]
    if not const or not acts:
        return
    does = []
    for a in acts:
        target = a.find("params/param[@name='target-parameter']")
        if a.tag == "edit-parameter-action" and target is not None:
            p = sh.book.params.get(target.get("value", "")[len("[Parameters]."):])
            does.append(f"sets {p.name if p else target.get('value')} (parameter action)")
        elif a.tag == "action" and "filter" in (a.find("command").get("command") if a.find("command") is not None
                                                else ""):
            does.append("filters the other sheets (filter action)")
        else:
            does.append(f"runs '{a.get('caption') or a.get('name')}'")
    shown = ", ".join(i.ref for i in shelves if not any(i is c for c in const))
    raise Skip(f"buttons: {shown} as marks on a constant axis {const[0].fld.formula}; a click "
               f"{' and '.join(dict.fromkeys(does))}. The schema's buttons set a string parameter and filter nothing "
               f"(decisions/042), the numbers at open would match but not the click")


def _dims(items):
    return [i for i in items if i.kind == "dim"]


def _measures(items):
    return [i for i in items if i.kind == "measure"]


def _plain(m, sh, where):
    """A measure item the spec can draw on an axis or as a number: no quick table calc."""
    if m.tc:
        raise Skip(f"{m.ref} with a quick table calculation ({m.tc}) {where}")
    return m.measure()


def _text_measures(sh, enc, names, where):
    out = []
    for i in enc.pop("text", []) + enc.pop("label", []):
        if i.kind == "values":
            out += names
        elif i.kind == "measure" and i.tc:
            sh.lost.append(f"label {i.ref}")
        elif i.kind == "measure":
            out.append(i)
        else:
            sh.lost.append(f"text {i.ref}")
    if not names and any(i.kind == "values" for i in out):
        raise Skip("Measure Values without a Measure Names filter")
    seen = []
    for m in out:
        if not any(m.same(s) for s in seen):
            seen.append(m)
    for m in seen:
        _plain(m, sh, where)
    return seen


def _color(sh, enc, measure=None):
    """The Color encoding: a dimension name, {'scale': ...} for the sheet's own measure, or None (lost)."""
    items = enc.pop("color", [])
    if not items:
        return None
    c = items[0]
    if len(items) > 1:
        sh.lost.append(f"color {', '.join(i.ref for i in items[1:])}")
    if c.kind == "dim":
        return c.fld.name
    if c.kind == "measure" and measure is not None and c.same(measure) and not c.tc:
        return {"scale": "sequential"}
    sh.lost.append(f"color {c.ref}")
    return None


def _archetype(sh, rows, cols, plus, marks, enc, names, top):
    name = sh.name
    mark = next((m for m in marks if m != "Automatic"), "Automatic")
    if len({m for m in marks if m != "Automatic"}) > 1:
        sh.lost.append(f"marks {sorted(set(marks))} (one mark per sheet)")
    geo = [i for i in rows + cols if i.kind == "geo"]
    if geo:
        return _map(sh, rows, cols, marks, enc)
    if plus:
        raise Skip("several fields joined with + on a shelf (shared or dual axes)")
    if any(i.kind in ("names", "values") for i in rows + cols) and not names:
        raise Skip("Measure Names / Values on a shelf without a Measure Names filter")
    lod = enc.pop("lod", [])
    if lod:
        raise Skip(f"detail {', '.join(i.ref for i in lod)} (marks at a finer level than the shelves)")
    r_meas, c_meas = _measures(rows), _measures(cols)
    dates = [i for i in rows + cols if i.kind == "date"]
    r_dims, c_dims = _dims(rows), _dims(cols)
    axes = r_meas + c_meas
    if not axes and not dates:
        texts = _text_measures(sh, enc, names, "as text")
        colored = [i for i in enc.get("color", []) if i.kind == "measure" and not i.tc]
        if mark == "Square" and r_dims and c_dims and colored and all(colored[0].same(t) for t in texts):
            texts = colored[:1]  # a heatmap: the cells colored by the measure (its number as text or not)
            enc["color"].remove(colored[0])
        if not texts:
            raise Skip("no measure")
        if not r_dims and not c_dims:
            if top:
                raise Skip(f"{top.text} without a dimension")
            return {"name": name, "type": "kpi", "measures": [m.measure() for m in texts]}
        if r_dims and c_dims and len(texts) == 1 and len(c_dims) == 1 and len(r_dims) <= 2:
            if top:
                raise Skip(f"{top.text} on a table")
            kind = "heatmap" if mark == "Square" and len(r_dims) == 1 else "table"
            s = {"name": name, "type": kind, "rows": r_dims[0].fld.name if len(r_dims) == 1 else
                 [d.fld.name for d in r_dims], "cols": c_dims[0].fld.name, "measure": texts[0].measure()}
            return s
        dims = r_dims or c_dims
        if (r_dims and c_dims) or len(dims) > 2:
            raise Skip(f"dimensions {[d.ref for d in r_dims]} x {[d.ref for d in c_dims]} with "
                       f"{len(texts)} measures as text")
        if not r_dims:
            sh.lost.append("values in one row across the columns (drawn as a registry column)")
        s = {"name": name, "type": "registry", "rows": [d.fld.name for d in dims],
             "columns": [{"measure": m.measure(), "style": "text"} for m in texts]}
        if top:
            s["top"] = _top(top, dims[0], texts[0], sh)
        return s
    if not axes and len(dates) == 1:
        return _date_heatmap(sh, rows, cols, dates[0], mark, enc, names, top)
    if len(axes) != 1:
        raise Skip("a date field without a measure axis" if dates and not axes else
                   f"{len(axes)} measure axes")
    m = axes[0]
    measure = _plain(m, sh, "on the axis")
    for i in _text_measures(sh, enc, names, "as a label"):
        sh.lost.append(f"label {i.ref}")
    if dates:
        return _line(sh, rows, cols, m, measure, dates, mark, enc, top)
    on_rows = m in r_meas
    dims = c_dims if on_rows else r_dims
    other = r_dims if on_rows else c_dims
    if len(dims) != 1 or other:
        raise Skip(f"bars need one dimension against the measure (got {[d.ref for d in dims + other]})")
    if mark not in ("Automatic", "Bar"):
        raise Skip(f"{mark} marks against a measure axis (the schema draws bars)")
    s = {"name": name, "type": "bar", "dimension": dims[0].fld.name, "measure": measure}
    color = _color(sh, enc, m)
    if color is not None:
        if isinstance(color, str) and color == s["dimension"]:
            sh.lost.append("color by the bar dimension")
        else:
            s["color"] = color
    if on_rows:
        s["orientation"] = "vertical"
    sort = _sort(sh, dims[0], m)
    if sort:
        s["sort"] = sort
    if top:
        s["top"] = _top(top, dims[0], m, sh)
    return s


# a date level as text, one value per period, in the keys expected.py gives the level (STR of a date is ISO, 031)
PERIOD_KEY = {"year": "STR(YEAR({k}))", "quarter": 'STR(YEAR({k})) + "-Q" + STR(QUARTER({k}))',
              "month": "LEFT(STR({k}), 7)", "day": "LEFT(STR({k}), 10)"}


def _date_heatmap(sh, rows, cols, d, mark, enc, names, top):
    """A truncated date against one dimension, no measure axis, the marks colored by a measure (a public book: a Shape per
    Sub-Category and month): a heatmap with a text column per period, the same marks and numbers (decisions/060)."""
    dims = _dims(rows + cols)
    colored = [i for i in enc.get("color", []) if i.kind == "measure" and not i.tc]
    texts = _text_measures(sh, enc, names, "as text")
    why = None
    if top or len(dims) != 1 or (d in rows) == (dims[0] in rows):
        why = "one dimension against the date"
    elif not colored or any(not colored[0].same(t) for t in texts):
        why = "marks colored by one measure"
    elif d.level not in PERIOD_KEY:
        why = f"a {d.level} level (a heatmap column per year, quarter, month or day)"
    elif mark not in ("Automatic", "Shape", "Square", "Circle"):
        why = f"{mark} marks"
    if why:
        raise Skip(f"a date field without a measure axis (a heatmap needs {why})")
    if d.level in ("quarter", "year") and sh.book.fiscal_start() != 1:
        raise Skip("a fiscal year that does not start in January")
    enc["color"].remove(colored[0])
    period = sh.book.derived(f"{d.level.capitalize()} of {d.fld.name}", PERIOD_KEY[d.level].format(k=d.fld.key),
                             "string")
    sh.lost.append(f"{mark} marks over {d.ref} colored by {colored[0].ref} (drawn as a heatmap, a column per "
                   f"period: the calc '{period.name}')")
    on_rows = d in rows
    return {"name": sh.name, "type": "heatmap", "rows": period.name if on_rows else dims[0].fld.name,
            "cols": dims[0].fld.name if on_rows else period.name, "measure": colored[0].measure()}


def _top(top, dim, measure, sh):
    d = top.detail
    if not top.item.same(dim):
        raise Skip(f"{top.text}: Top N of another field than {dim.ref}")
    if d["end"] != "top" or (d["direction"] or "DESC") != "DESC" or not d["all"]:
        raise Skip(f"{top.text}: only a Top N (largest first) over all members")
    by = _top_by(top, measure, sh)
    n = d["n"]
    if n.isdigit():
        out = {"n": int(n)}
    else:
        p = sh.book.params.get(n[len("[Parameters]."):]) if n.startswith("[Parameters].") else None
        if p is None or p.spec is None or p.spec["type"] != "integer":
            raise Skip(f"{top.text}: N is {n} ({p.reason if p else 'not an integer parameter'})")
        sh.params.add(p.key)
        out = {"n": p.name}
    if by is not None:
        out["by"] = by
    return out


_TOP_BY = re.compile(r"(?:(SUM|AVG|MIN|MAX|COUNT|COUNTD)\((\[(?:[^\]]|\]\])+\])\)|(\[(?:[^\]]|\]\])+\]))")


def _top_by(top, measure, sh):
    """The Top N's 'by field' as top.by when it is not the sheet's measure (decisions/067), else None. Desktop writes
    SUM([Sales]) for a column, [Calculation_1] for an aggregate calc."""
    expr = (top.detail["by"] or "").replace(" ", "")
    m = _TOP_BY.fullmatch(expr)
    fld = sh.book.fields.get(m.group(2) or m.group(3)) if m else None
    if fld is None:
        raise Skip(f"{top.text} by {top.detail['by']}: not a field of the book")
    agg = m.group(1).lower() if m.group(1) else None
    if fld.key == measure.fld.key and agg == measure.agg:
        return None
    flds, pars = sh.book.closure([fld])
    for f in flds:
        if f.is_calc and (f.calc_class != "tableau" or not f.formula):
            raise Skip(f"{top.text} by '{f.name}': a {f.calc_class} field")
    for k in sorted(pars):
        p = sh.book.params.get(k)
        if p is None or p.spec is None:
            raise Skip(f"{top.text} by {top.detail['by']}: parameter '{p.name if p else k}'")
        sh.params.add(k)
    return Item("measure", fld, agg, ref=expr).measure()


def _rank_top(spec, rank, ranked, top, sh):
    """A filter of ranks 1..N on RANK(measure) -> top: {n, after: 'filters'} of a bar (decisions/086). The rank is
    the bar's measure, Competition and Descending (Desktop's default: the top N, ties kept), along the bar's
    dimension; a rank on a shelf orders the bars by it, so they are sorted by the measure, largest first."""
    why = None
    tc = rank.item.tcx
    opts = set((tc.get("rank-options") or "").split(",")) if tc is not None else set()
    along = tc.get("ordering-field", "") if tc is not None else ""
    along = along.split("].[", 1)[-1][:-1] if "].[" in along else along
    members = [str(m) for m in rank.members]
    if top is not None:
        why = f"{top.text} and a rank filter on one sheet"
    elif spec["type"] != "bar" or "color" in spec:
        why = "a bar of one dimension (the schema's Top N after the filters)"
    elif rank.item.measure() != spec["measure"]:
        why = f"the rank of the bar's measure (it ranks {rank.item.label()})"
    elif rank.exclude or not all(m.isdigit() for m in members) or \
            sorted(int(m) for m in members) != list(range(1, len(members) + 1)) or len(members) < 2:
        why = f"ranks 1..N with N from 2 (it keeps {members})"
    elif opts != {"Competition", "Descending"}:
        why = f"rank-options Competition, Descending (it has {tc.get('rank-options') if tc is not None else None!r})"
    elif tc.get("ordering-type") != "Field" or along not in (_dim_key(spec, sh), f"none:{_dim_key(spec, sh)}:nk"):
        why = f"the rank along the bar's dimension (it runs along {tc.get('ordering-field') or tc.get('ordering-type')})"
    if why:
        raise Skip(f"{rank.text}: Top N after the filters needs {why}")
    spec["top"] = {"n": len(members), "after": "filters"}
    if ranked:
        sh.lost.append(f"{ranked[0].ref} on the shelf, its header hidden: the bars sorted by "
                       f"{rank.item.label()} descending (the rank's order)")
        if spec.get("sort") not in (None, "desc"):
            raise Skip(f"{rank.text}: the rank orders the bars, the sheet sorts them {spec['sort']}")
        spec["sort"] = "desc"


def _dim_key(spec, sh):
    """The book's local name of the bar's dimension, without brackets: City."""
    return next(_unbracket(f.key) for f in sh.book.fields.values() if f.name == spec["dimension"])


def _line(sh, rows, cols, m, measure, dates, mark, enc, top):
    if top:
        raise Skip(f"{top.text} on a time series")
    if len(dates) != 1:
        raise Skip(f"{len(dates)} date fields")
    d = dates[0]
    if (d in rows) == (m in rows):
        raise Skip("the date and the measure on the same shelf")
    date = {"field": d.fld.name, "level": d.level}
    if d.level == "week" and sh.book.week_start() == "sunday":
        # the schema's weeks start on Monday: the Sunday of each week as a calc, one mark a day (DATEPART weekday
        # is 1 on Sunday whatever the week start, decisions/031), the same marks and numbers (decisions/060)
        k = d.fld.key
        week = sh.book.derived(f"Week Start of {d.fld.name}",
                               f"DATEADD('day', 1 - DATEPART('weekday', {k}), {k})", "date")
        date = {"field": week.name, "level": "day"}
        sh.lost.append(f"weeks from Sunday: drawn by day of the calc '{week.name}', the Sunday of each week")
    elif d.level == "week" and sh.book.week_start() != "monday":
        raise Skip(f"weeks start on {sh.book.week_start()} in this book; the schema's weeks start on Monday")
    if d.level in ("quarter", "year") and sh.book.fiscal_start() != 1:
        raise Skip("a fiscal year that does not start in January")
    panels = _dims(rows + cols)
    color = _color(sh, enc, m)
    series = [c for c in ([color] if isinstance(color, str) else []) + [p.fld.name for p in panels]]
    if isinstance(color, dict):
        sh.lost.append("color by the measure")
    if len(set(series)) > 1:
        raise Skip(f"two series fields {series}")
    if mark not in ("Automatic", "Line", "Area", "Bar"):
        raise Skip(f"{mark} marks over a date axis")
    if mark == "Bar":
        sh.lost.append("bars over a date axis (drawn as a line)")
    if panels:
        sh.lost.append(f"a panel per {panels[0].ref} (drawn as a line per value)")
    s = {"name": sh.name, "type": "area" if mark == "Area" else "line", "date": date, "measure": measure}
    if series:
        s["color"] = series[0]
    return s


def _map(sh, rows, cols, marks, enc):
    lod = [i for i in enc.pop("lod", []) if i.kind == "dim"]
    places = list({i.fld.key: i for i in lod}.values())
    if len(places) != 1:
        raise Skip(f"a map needs one place field on Detail (got {[p.ref for p in places]})")
    place = places[0]
    role = GEO_ROLES.get(place.fld.semantic or "")
    if role is None:
        raise Skip(f"{place.ref}: geographic role {place.fld.semantic} (the schema: country, state, city)")
    color, size = enc.pop("color", []), enc.pop("size", [])
    enc.pop("geometry", None)
    filled = "Multipolygon" in marks and color and color[0].kind == "measure"
    m = color[0] if filled else size[0] if size and size[0].kind == "measure" else None
    if m is None:
        raise Skip("a map without a measure on Color (filled) or Size (symbol)")
    if filled and size:
        sh.lost.append(f"a second map layer sized by {size[0].ref}")
    s = {"name": sh.name, "type": "map", "geo": {"field": place.fld.name, "role": role},
         "measure": _plain(m, sh, "on the map"), "style": "filled" if filled else "symbol"}
    if role != "country":
        s["geo"]["country"] = None  # filled in from the data (_country)
    return s


def _title(ws):
    t = ws.find("layout-options/title/formatted-text")
    if t is None:
        return None
    text = _attr_text(t).replace("<Sheet Name>", ws.get("name")).split("\n")[0]
    text = re.sub(r"<[^<>]*>", "", text)
    text = UNSAFE.sub("", text).strip()
    return text[:200] or None


# ---- dashboard -----------------------------------------------------------------------------------------------------
def _zones(d):
    """A dashboard's zones (not its device layouts')."""
    top = d.find("zones") if d is not None else None
    return list(top.iter("zone")) if top is not None else []


def _zone_box(z):
    return tuple(int(z.get(k, "0")) for k in ("x", "y", "w", "h"))


def _bands(items, axis):
    """Items [(name, (x, y, w, h))] -> bands across axis (1: rows top to bottom, 0: columns left to right). An item
    joins the band it overlaps by more than a sliver; a tiled layout has clean cuts between its bands."""
    a = axis
    bands = []
    for it in sorted(items, key=lambda z: (z[1][a], z[1][1 - a])):
        s, n = it[1][a], it[1][a + 2]
        b = bands[-1] if bands else None
        if b and min(s + n, b["end"]) - max(s, b["start"]) > 0.05 * min(n, b["end"] - b["start"]):
            b["items"].append(it)
            b["end"] = max(b["end"], s + n)
        else:
            bands.append({"start": s, "end": s + n, "items": [it]})
    return [(b["items"], b["end"] - b["start"]) for b in bands]


def _tree(items):
    """The zones as nested cuts (decisions/060): a sheet name, or ("rows" | "cols", [(subtree, extent)]). Rows are
    cut first, then columns inside a band: a sheet stacked under another one in the same column of the book stays
    in that column (a public book: State Wise under Sales by State), not beside it."""
    if len(items) == 1:
        return items[0][0]
    for axis, kind in ((1, "rows"), (0, "cols")):
        bands = _bands(items, axis)
        if len(bands) > 1:
            return kind, [(_tree(b), extent) for b, extent in bands]
    # floating zones overlapping both ways: one row each, top to bottom
    return "rows", [(n, box[3]) for n, box in sorted(items, key=lambda z: (z[1][1], z[1][0]))]


def _weights(extents):
    least = min(extents) or 1
    return [max(1, min(12, round(e / least))) for e in extents]


def _leaves(node):
    return [node] if isinstance(node, str) else [n for kid, _ in node[1] for n in _leaves(kid)]


def _grid_rows(node, depth=1):
    """A tree -> (rows of cells, row weights) of a grid at depth (the top grid is 1, build.MAX_GRID_DEPTH = 3). A
    row of more than GRID_MAX cells goes on in the next row; more than GRID_MAX rows nest in groups."""
    kids = node[1] if isinstance(node, tuple) and node[0] == "rows" else [(node, 1)]
    rows, heights = [], []
    for kid, h in zip([k for k, _ in kids], _weights([e for _, e in kids])):
        cells = _grid_row(kid, depth)
        for i in range(0, len(cells), GRID_MAX):
            rows.append(cells[i:i + GRID_MAX])
            heights.append(h)
    if len(rows) <= GRID_MAX:
        return rows, heights
    groups = [(rows[i:i + GRID_MAX], heights[i:i + GRID_MAX]) for i in range(0, len(rows), GRID_MAX)]
    return [[{"rows": g, "row_heights": w}] for g, w in groups], [max(1, min(12, len(g))) for g, _ in groups]


def _grid_row(node, depth):
    kids = node[1] if isinstance(node, tuple) and node[0] == "cols" else [(node, 1)]
    out = []
    for kid, w in zip([k for k, _ in kids], _weights([e for _, e in kids])):
        if isinstance(kid, str):
            out.append({"sheet": kid, "width": w})
            continue
        if depth + 1 >= 3:  # one level below would be too deep for the builder: the sheets one under another
            kid = ("rows", [(n, 1) for n in _leaves(kid)])
        rows, heights = _grid_rows(kid, depth + 1)
        out.append({"rows": rows, "row_heights": heights, "width": w})
    return out


def _grid(zones, extra, wider=None, apart=(), taller=None):
    """Sheet zones [(name, (x, y, w, h))] -> rows of cells by their positions (nested cuts, groups where a column
    holds several sheets); extra sheets (not on the dashboard) as rows of three after them. The fit of the generator
    (decisions/060): wider {sheet: n} adds n to the sheet's width weight, a sheet in apart gets a row of its own at
    the end, taller {sheet: n} adds n to the height weight of its row among the others (decisions/066)."""
    zones = [z for z in zones if z[0] not in apart]
    kids = []
    if zones:
        tree = _tree(zones)
        kids = tree[1] if isinstance(tree, tuple) and tree[0] == "rows" else [(tree, max(z[1][3] for z in zones))]
    tallest = max([e for _, e in kids] or [1])
    extra = [n for n in extra if n not in apart]
    for i in range(0, len(extra), 3):
        kids.append((_threes(extra[i:i + 3]), tallest))
    apart = list(apart)
    if len(kids) + len(apart) > GRID_MAX:  # a row each would nest the whole dashboard in groups: one row, three a row
        kids += [(_threes(apart[i:i + 3]), tallest) for i in range(0, len(apart), 3)]  # (a public book, decisions/066)
    else:
        kids += [(n, tallest) for n in apart]
    grid, heights = _grid_rows(("rows", kids))
    if _depth(grid) > 3:  # rows nested in groups on top of nested cuts: the sheets in reading order, three a row
        names = [n for kid, _ in kids for n in _leaves(kid)]
        grid, heights = _grid_rows(("rows", [(_threes(names[i:i + 3]), 1) for i in range(0, len(names), 3)]))
    for name, n in (wider or {}).items():
        cell = _fit_target(grid, name)[1]
        if cell is not None:
            cell["width"] = min(12, cell["width"] + n)
    for name, n in (taller or {}).items():
        at = _fit_row(grid, heights, name)
        if at is not None:
            at[0][at[1]] = min(12, at[0][at[1]] + n)
    return grid, heights


def _fit_row(rows, heights, name):
    """(height weights, index, rows) of the row that holds a sheet, at the level where it shares the height with
    other rows (a sheet stacked in a group: its row in the group, decisions/066); None when no such row."""
    for i, r in enumerate(rows):
        for c in r:
            if c.get("sheet") == name:
                return (heights, i, rows) if len(rows) > 1 else None
            if "rows" in c:
                inner = _fit_row(c["rows"], c.setdefault("row_heights", [1] * len(c["rows"])), name)
                if inner is not None:
                    return inner
                if any(name == x.get("sheet") for x in _cells(c["rows"])):
                    return (heights, i, rows) if len(rows) > 1 else None
    return None


def _fit_target(rows, name):
    """(found, cell) the width weight that widens a sheet: its own cell when it shares its row, else the nearest group
    around it that shares its row (a sheet stacked in a group: a public book's State Wise under the map, decisions/066);
    cell None when no such cell."""
    for r in rows:
        for c in r:
            if c.get("sheet") == name:
                return True, (c if len(r) > 1 else None)
            if "rows" in c:
                found, cell = _fit_target(c["rows"], name)
                if found:
                    return True, cell if cell is not None else (c if len(r) > 1 else None)
    return False, None


def _cells(rows):
    for r in rows:
        for c in r:
            yield c
            if "rows" in c:
                yield from _cells(c["rows"])


def _threes(names):
    return ("cols", [(n, 1) for n in names]) if len(names) > 1 else names[0]


def _depth(rows, depth=1):
    return max([depth] + [_depth(c["rows"], depth + 1) for r in rows for c in r if "rows" in c])


def _dashboard(book, report, sheets, fit=None):
    """The dashboard of the book that holds most rebuilt sheets, as a grid; the rebuilt sheets on no dashboard after.
    fit: {"wider": {sheet: n}, "apart": [sheet]} (_validate)."""
    names = {s["name"] for s in sheets}
    dashes = book.root.findall("dashboards/dashboard")
    def zones(d):
        return [(z.get("name"), _zone_box(z)) for z in _zones(d) if z.get("name") in names
                and z.get("type-v2") is None and z.get("type") is None]
    best = max(dashes, key=lambda d: len(zones(d)), default=None)
    placed = []
    if best is not None:
        seen = set()
        for n, box in zones(best):
            if n not in seen:
                seen.add(n)
                placed.append((n, box))
        for d in dashes:
            if d is not best and zones(d):
                report.lost.append((f"dashboard '{d.get('name')}'", f"its sheets are on '{best.get('name')}'"))
    extra = [s["name"] for s in sheets if s["name"] not in {n for n, _ in placed}]
    for n in extra:  # a viz in tooltip (a public book's Sales by City in the map's tooltip): its view, on the dashboard
        hosts = [w.get("name") for w in book.root.findall("worksheets/worksheet") if any(
            f'<Sheet name="{n}"' in (r.text or "") for r in w.iter("run"))]
        if hosts:
            report.lost.append((f"sheet '{n}'", f"a viz in the tooltip of {', '.join(map(repr, hosts))} (filtered "
                                                f"by the hovered mark): drawn on the dashboard as the sheet opens"))
    fit = fit or {}
    grid, heights = _grid(placed, extra, fit.get("wider"), [n for n in fit.get("apart", []) if n in names],
                          fit.get("taller"))
    name = best.get("name") if best is not None else "Dashboard"
    out = {"name": UNSAFE.sub("_", name).strip() or "Dashboard", "title": _dash_title(best) or _text_name(name),
           "theme": "flat",  # the book's own layout; _fit (decisions/060, 066, 101) sizes it without cards (decisions/168)
           "grid": grid}
    size = best.find("size") if best is not None else None
    if size is not None and size.get("maxwidth") and size.get("maxheight"):
        out["width"] = max(400, min(4000, int(size.get("maxwidth"))))
        out["height"] = max(300, min(4000, int(size.get("maxheight"))))
        for n in fit.get("keep", ()):  # a chart's row grown (decisions/101): the dashboard grows by as much, so
            at = _fit_row(grid, heights, n)  # the rows beside it keep their height
            if at is not None and fit["taller"][n]:
                total = sum(at[0])
                out["height"] = min(4000, -(-out["height"] * total // (total - fit["taller"][n])))
    else:
        out["width"], out["height"] = 1200, 800
        report.lost.append((f"dashboard '{name}'", "automatic or range size (drawn 1200 x 800)"))
    if len(grid) > 1:
        out["row_heights"] = heights
    if best is not None:
        _dashboard_lost(best, names, report)
    return out


def _text_name(name):
    return UNSAFE.sub("", name).strip()[:200] or "Dashboard"


def _dash_title(d):
    """The text zone with the largest font (16pt and up): the dashboard's header."""
    best = None
    for z in _zones(d):
        if z.get("type-v2") != "text" and z.get("type") != "text":
            continue
        for r in z.iter("run"):
            size = float(r.get("fontsize") or 0)
            if size >= 16 and (best is None or size > best[0]):
                best = (size, z)
    if best is None:
        return None
    text = UNSAFE.sub("", _attr_text(best[1]).split("\n")[0]).strip()
    return text[:200] or None


def _dashboard_lost(d, names, report):
    kinds = Counter()
    for z in _zones(d):
        t = z.get("type-v2") or z.get("type")
        if t in ("text", "bitmap", "web", "paramctrl", "color", "size", "shape", "map", "empty"):
            kinds[t] += 1
        elif t is None and z.get("name") and z.get("name") not in names:
            kinds["sheet not rebuilt"] += 1
    shown = {"text": "text zones", "bitmap": "images", "web": "web pages", "paramctrl": "parameter controls",
             "color": "color legends", "size": "size legends", "shape": "shape legends", "map": "map legends"}
    parts = [f"{n} {shown[k]}" for k, n in sorted(kinds.items()) if k in shown]
    if parts:
        report.lost.append((f"dashboard '{d.get('name')}'", ", ".join(parts) + " (the header and legends are "
                                                                               "drawn by the generator)"))


def _actions_lost(book, report):
    for a in book.root.findall("actions/*"):
        if a.tag in ("datasources", "datasource-dependencies"):
            continue  # what the actions' fields come from; every action is listed (parameter actions too)
        src = a.find("source")
        cmd = a.find("command")
        what = (cmd.get("command") if cmd is not None else a.tag).split(":")[-1]
        report.lost.append(("actions", f"'{a.get('caption') or a.get('name')}' ({what} from "
                                       f"{src.get('worksheet') or src.get('dashboard') if src is not None else '?'})"))


# ---- the spec ------------------------------------------------------------------------------------------------------
def _spec_filters(book, report, shared, sheets):
    """Shared filters that change the numbers -> the spec's filters (a card on a rebuilt sheet)."""
    cards = {}
    for z in book.root.iter("zone"):
        if (z.get("type-v2") or z.get("type")) == "filter" and z.get("param"):
            cards.setdefault(z.get("param"), z)
    out, dropped = [], {}
    rebuilt = [s["name"] for s in sheets]
    for col, f in shared.items():
        zone = cards.get(col)
        if f.noop and zone is None:
            report.lost.append(("workbook", f"{f.text} (all values pass)"))
            continue
        try:
            out.append(_spec_filter(f, zone, rebuilt, report, book))
        except Skip as e:
            dropped[col] = str(e)
    return out, dropped


def _spec_filter(f, zone, rebuilt, report, book):
    fld = f.item.fld
    if f.kind == "categorical" and f.item.kind == "dim" and (not fld.is_calc or fld.calc_class == "tableau"):
        if fld.is_calc:  # a formula calc (decisions/057): its parameters must be ones the spec takes
            for k in sorted(book.closure([fld])[1]):
                p = book.params.get(k)
                if p is None or p.spec is None:
                    raise Skip(f"shared {f.text}: parameter '{p.name if p else k}': "
                               f"{p.reason if p else 'not in the book'}")
        s = {"field": fld.name}
        if f.members and not f.noop:
            s["default"] = _members(f)
            if f.exclude:
                s["exclude"] = True
        if f.context:
            s["context"] = True
    elif f.kind == "range" and f.item.kind == "date" and not f.item.fld.is_calc:
        s = {"field": f.item.fld.name, "mode": "range", **_range(f)}
    elif f.kind == "relative" and f.item.kind == "date" and not f.item.fld.is_calc:
        s = {"field": f.item.fld.name, "mode": "relative", **_relative(f)}
        if f.context:
            s["context"] = True
    else:
        raise Skip(f"shared {f.text}: the spec's filters take a data column's values or dates")
    show = zone.get("name") if zone is not None else None
    if show not in rebuilt:
        if zone is None:
            report.lost.append(("workbook", f"{f.text}: a card is added (the book's filter has none)"))
        show = rebuilt[0]
    s["show_on"] = show
    return s


def _range(f):
    """A date range filter's bounds as the spec's min / max (whole days, both or none)."""
    lo, hi = f.detail.get("min"), f.detail.get("max")
    if f.noop:
        return {}
    if not lo or not hi:
        raise Skip(f"shared {f.text}: one bound only (the spec's range has both)")
    if lo[10:].strip() not in ("", "00:00:00") or hi[10:].strip() not in ("", "00:00:00", "23:59:59"):
        raise Skip(f"shared {f.text}: bounds within a day ({lo} .. {hi})")
    if hi[10:].strip() == "00:00:00" and f.item.fld.datatype == "datetime":
        raise Skip(f"shared {f.text}: ends at the first second of {hi[:10]} (the spec keeps whole days)")
    return {"min": lo[:10], "max": hi[:10]}


def _relative(f):
    """A relative date filter -> the spec's last N periods up to the anchor."""
    a = f.detail
    period = a.get("period-type-v2") or a.get("period-type")
    first, last = int(a.get("first-period", "0")), int(a.get("last-period", "0"))
    anchor = a.get("period-anchor")
    if period not in ("year", "quarter", "month", "week", "day") or last != 0 or first > 0:
        raise Skip(f"shared {f.text}: periods {first}..{last} of {period} (the spec: the last N up to the anchor)")
    if not anchor:
        raise Skip(f"shared {f.text}: relative to today (the spec anchors on a date)")
    if a.get("include-null") == "true" or a.get("include-future") == "false":
        raise Skip(f"shared {f.text}: null or future dates handled otherwise than the spec does")
    return {"period": period, "last": 1 - first, "anchor": _literal(anchor)[:10]}


def _country(book, values_of, shared):
    """The country state / city names are looked up in: the data source's own (semantic value [Country].[Name],
    what Desktop geocodes by when no country field is in the view); else a column with a Country role that a shared
    filter keeps to one value, or that has one value."""
    sv = book.ds.find("semantic-values/semantic-value[@key='[Country].[Name]']")
    if sv is not None and _literal(sv.get("value")):
        return _literal(sv.get("value"))
    for f in book.fields.values():
        if not (f.semantic or "").startswith("[Country]") or f.is_calc:
            continue
        v = values_of(f)
        kept = [g for g in shared.values() if g.kind == "categorical" and g.item.fld is f and not g.exclude
                and len(g.members) == 1]
        if kept:
            return kept[0].members[0]
        if v is not None and len(v) == 1:
            return v[0]
    return None


def _assemble(book, report, plans, shared, ds, fit=None):
    """The spec of the rebuilt sheets: their calcs and parameters, the shared filters, the dashboard."""
    sheets = [p[0] for p in plans.values()]
    filters, dropped = _spec_filters(book, report, shared, sheets)
    for name in list(plans):
        cols = {c.text for c in plans[name][1].view.findall("slices/column")}
        why = [dropped[c] for c in cols if c in dropped]
        if why:
            plans.pop(name)
            report.skipped.append((name, why[0]))
    sheets = [p[0] for p in plans.values()]
    if not sheets:
        return None
    filter_flds = [f.item.fld for col, f in shared.items() if col not in dropped and f.item.fld]
    used = [f for p in plans.values() for f in p[2]] + filter_flds
    closure, par_keys = book.closure(used)
    par_keys |= {k for p in plans.values() for k in p[1].params}
    renamed = {new: old for old, new in book.renamed}
    for f in closure:
        if f.name in renamed:
            report.lost.append(("field names", f"'{renamed[f.name]}' is '{f.name}' (characters the schema does not "
                                               f"allow)"))
    calcs = [{"name": f.name, "formula": book.translate(f.formula)} for f in closure
             if f.is_calc and f.calc_class == "tableau"]
    spec = {"version": 1, "datasource": ds, "sheets": sheets}
    if calcs:
        spec["calcs"] = calcs
    params = [book.params[k].spec for k in sorted(par_keys) if k in book.params]
    if params:
        ctrls = {z.get("param") for z in book.root.iter("zone") if (z.get("type-v2") or z.get("type")) == "paramctrl"}
        spec["parameters"] = [dict(book.params[k].spec, control="card" if f"[Parameters].{k}" in ctrls else "none")
                              for k in sorted(par_keys) if k in book.params]  # a card where the book has one
    if filters:
        spec["filters"] = filters
    spec["dashboard"] = _dashboard(book, report, sheets, fit)
    return spec


def _sheet_fields(book, spec_sheet):
    """Book fields the spec sheet uses (by its spec names)."""
    names = book.by_name()
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("field", "dimension", "rows", "cols", "color"):
                    walk_name(x)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    def walk_name(x):
        for n in x if isinstance(x, list) else [x]:
            if isinstance(n, str) and n in names:
                found.add(n)
    walk(spec_sheet)
    return [names[n] for n in sorted(found)]


def _check(spec, base):
    """The spec builds and passes the gate (into a temporary file) and expected.py computes every number of it: the
    numbers the rebuilt book is checked by."""
    from .build import build
    with tempfile.TemporaryDirectory() as tmp:
        build(spec, Path(tmp) / "check.twbx", base)
    expected.compute(spec, base / spec["datasource"]["path"])


def _error(spec, base):
    """None when the spec builds, else the generator's message."""
    try:
        _check(spec, base)
        return None
    except CHECK_ERRORS as e:
        return str(e)


def _mini(spec, sheet, book, used):
    """The spec of one sheet: the shared filters, the calcs and parameters it needs (another sheet's calc the
    generator refuses must not refuse this one, decisions/057)."""
    s = {k: v for k, v in spec.items() if k not in ("sheets", "dashboard", "filters", "calcs", "parameters")}
    by = book.by_name()
    closure, pars = book.closure(list(used) + [by[f["field"]] for f in spec.get("filters", []) if f["field"] in by])
    names = {f.name for f in closure}
    top = sheet.get("top", {}).get("n")
    pnames = {book.params[k].name for k in pars if k in book.params} | ({top} if isinstance(top, str) else set())
    calcs = [c for c in spec.get("calcs", []) if c["name"] in names]
    pars = [p for p in spec.get("parameters", []) if p["name"] in pnames]
    if calcs:
        s["calcs"] = calcs
    if pars:
        s["parameters"] = pars
    if spec.get("filters"):
        s["filters"] = [dict(f, show_on=sheet["name"]) for f in spec["filters"]]
    s["sheets"] = [sheet]
    s["dashboard"] = {"name": "Check", "title": spec["dashboard"].get("title") or "Check",  # parameter cards
                      "grid": [[sheet["name"]]]}
    return s


def rebuild(src, out, data=None):
    """src .twbx / .twb -> out spec.json and its data file; the Report. RebuildError when nothing can be rebuilt
    (nothing is left on disk then)."""
    src, out = Path(src), Path(out)
    report = Report(src.name)
    # the data profiled once and the numbers of a spec computed once: _fit checks the same sheets in many layouts
    with tempfile.TemporaryDirectory() as tmp, excel.cached(), expected.cached():
        book = Book(src, tmp)
        try:
            spec = _rebuild(book, report, out, Path(data) if data else out.with_suffix(""))
        finally:
            if book.zip is not None:
                book.zip.close()
    order = {ws.get("name"): i for i, ws in enumerate(book.root.findall("worksheets/worksheet"))}
    report.skipped.sort(key=lambda s: order.get(s[0], 0))
    report.lost = list(dict.fromkeys(report.lost))  # the spec may be assembled twice (_validate)
    if spec is None:
        raise RebuildError(f"{src.name}: no sheet can be rebuilt\n{report.text()}", report)
    return report


def _rebuild(book, report, out, data_out):
    if book.others:
        report.lost.append(("workbook", f"data sources {book.others} (the spec has one)"))
    worksheets = book.root.findall("worksheets/worksheet")
    # pass 1, the structure only: the fields each sheet reads tell which table the data comes from
    candidates = {}
    for ws in worksheets:
        sh = Sheet(book, ws)
        items = [i for t in ("rows", "cols") for i in sh.shelf(t)[0]] + \
            [i for _, e in sh.panes() for v in e.values() for i in v] + \
            [sh.item(f.get("column", "")) for f in sh.view.findall("filter")]
        candidates[ws.get("name")] = (book.closure([i.fld for i in items if i.fld])[0], None)
    _source_kind(book)  # a live source fails before anything else
    main = _choose_table(book, report, candidates)
    if not candidates:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    data_out.parent.mkdir(parents=True, exist_ok=True)
    path, ds = write_data(book, report, main, data_out)
    try:
        spec = _sheets_spec(book, report, worksheets, candidates, path, ds, out.parent)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if spec is None:
        path.unlink(missing_ok=True)
        return None
    _actions_lost(book, report)
    report.lost.append(("style", "fonts, colors, number formats, tooltips, sizes: the design system's"))
    spec = {"$schema": _relpath(Path(__file__).parent / "spec.schema.json", out.parent), **spec}
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    report.spec_path = out
    return spec


def _sheets_spec(book, report, worksheets, candidates, path, ds, base):
    """Pass 2, with the data: each candidate sheet -> a spec sheet or the reason it is not rebuilt; the spec."""
    ds["path"] = _relpath(path, base)
    prof = excel.load(path, ds.get("sheet"))
    report.data_path, report.rows = path, len(prof.rows)
    columns = {c.name for c in prof.columns}
    distinct = {}

    def values_of(f):
        if f is None or f.is_calc or f.name not in columns:
            return None
        if f.name not in distinct:
            distinct[f.name] = sorted({r[f.name] for r in prof.rows if r[f.name] != ""})
        return distinct[f.name]
    shared = _shared_filters(book, values_of)
    country = _country(book, values_of, shared)
    done = {}
    for ws in worksheets:
        name = ws.get("name")
        if name not in candidates:
            continue
        try:
            spec_sheet, sh = analyze(book, ws, shared, values_of)
            if spec_sheet["type"] == "map" and "country" in spec_sheet["geo"]:
                if country is None:
                    raise Skip("a state / city map without one country in the data")
                spec_sheet["geo"]["country"] = country
            used = _sheet_fields(book, spec_sheet)
            missing = [f.name for f in used if not f.is_calc and f.name not in columns]
            if missing:
                raise Skip(f"fields {missing} are not in the data")
            done[name] = (spec_sheet, sh, used)
        except Skip as e:
            report.skipped.append((name, str(e)))
    spec = _validate(book, report, done, shared, ds, base)
    if spec is None:
        return None
    for spec_sheet, sh, _ in done.values():
        for what in dict.fromkeys(sh.lost):
            report.lost.append((f"sheet '{sh.name}'", what))
        report.rebuilt.append((sh.name, _summary(spec_sheet)))
    return spec


def _validate(book, report, done, shared, ds, base):
    """The spec of the sheets the generator takes. A sheet it refuses is not rebuilt (its message is the reason);
    one it takes without its color dimension loses the color (noted). Calcs, parameters, filters and the grid are
    assembled again for the sheets kept."""
    spec = _assemble(book, report, done, shared, ds) if done else None
    whole = _error(spec, base) if spec else None
    if whole is None:
        return spec
    changed = False
    for name, (sheet, sh, used) in list(done.items()):
        err = _error(_mini(spec, sheet, book, used), base)
        if err is None:
            continue
        changed = True
        if isinstance(sheet.get("color"), str):
            bare = {k: v for k, v in sheet.items() if k != "color"}
            if _error(_mini(spec, bare, book, used), base) is None:
                sh.lost.append(f"color {sheet['color']} (the generator: {err.splitlines()[-1].strip()})")
                done[name] = (bare, sh, used)
                continue
        report.skipped.append((name, f"the generator does not take it: {err}"))
        done.pop(name)
    if changed:
        spec = _assemble(book, report, done, shared, ds) if done else None
        whole = _error(spec, base) if spec else None
    return _fit(book, report, done, shared, ds, base, spec, whole)


def _fit(book, report, done, shared, ds, base, spec, err):
    """Every sheet builds alone, the dashboard does not: the book's layout gives a cell less room than the generator
    needs (a public book: a registry of two columns in a sliver, decisions/060). The generator's check stays; the cell it
    names gets one more width weight at a time while it shares its row (a sheet stacked in a group: the group's),
    then a row at the end (its own, or three a row when the grid has no room), then the sheet is not rebuilt (its
    message is the reason). Too short (decisions/066): a group of three or more rows first sheds its last sheet to the
    end, then the sheet's row gets up to TALLER_MAX height weights more. Any other message is an error."""
    fit = {"wider": Counter(), "taller": Counter(), "apart": []}
    shed = {}  # a group's last sheet put apart -> the sheet it made room for
    first = {}
    while err is not None:
        m = _CELL_ERROR.match(err)
        name = m.group(1) if m else None
        if name not in done:
            raise RebuildError(f"the rebuilt spec does not build: {err}", report)
        first.setdefault((name, m.group(2)), err)
        cell = _fit_target(spec["dashboard"]["grid"], name)[1]  # its cell, or the group around it (decisions/066)
        d = spec["dashboard"]
        row = _fit_row(d["grid"], d.get("row_heights", [1] * len(d["grid"])), name)  # decisions/066: too short
        if m.group(2) == "narrow" and cell is not None and cell["width"] < 12:  # also beside another sheet apart
            fit["wider"][name] += 1
        elif (m.group(2) == "short" and name not in fit["apart"] and row is not None and len(row[2]) > 2
              and d["grid"] is not row[2] and _CHART_SHORT not in err):
            # (a chart too short, decisions/101, grows its own row first: shedding the group's last sheet does not
            # make its row taller enough and moves a sheet that fitted)
            # a group of three or more rows too short for one of them: its last sheet leaves first (a row of its
            # own), the rest keep the book's column (a public book: State Wise (%) under State Wise under the map)
            last = [x["sheet"] for x in _cells([row[2][-1]]) if "sheet" in x][-1]
            fit["apart"].append(last)
            shed[last] = name
        elif (m.group(2) == "short" and name not in fit["apart"] and row is not None and row[0][row[1]] < 12
              and fit["taller"][name] < TALLER_MAX):
            fit["taller"][name] += 1
            if _CHART_SHORT in err:  # the dashboard grows with it, the rows beside it keep their height (101)
                fit.setdefault("keep", set()).add(name)
        elif name not in fit["apart"]:
            fit["apart"].append(name)
        else:
            report.skipped.append((name, f"the generator does not take it on the dashboard: {err}"))
            done.pop(name)
        spec = _assemble(book, report, done, shared, ds, fit) if done else None
        err = _error(spec, base) if spec else None
    placed = set()
    for name, other in shed.items():  # no message of its own: it made room in its group
        if name in done and name not in {n for n, _ in first}:
            placed.add(name)
            done[name][1].lost.append(f"its place on the dashboard: a row at the end (its group was too "
                                      f"short for '{other}': {first[(other, 'short')].split(';')[0]})")
    for (name, kind), why in first.items():  # the first message of each kind: wider, taller (decisions/066)
        if name not in done:
            continue
        lost = done[name][1].lost
        why = why.split(";")[0]
        if name in fit["apart"]:
            if name not in placed:
                placed.add(name)
                lost.append(f"its place on the dashboard: a row at the end (the generator: {why})")
        elif kind == "narrow" and fit["wider"][name]:
            lost.append(f"its width on the dashboard: {fit['wider'][name]} weight(s) wider than the book's cell "
                        f"(the generator: {why})")
        elif kind == "short" and fit["taller"][name]:
            lost.append(f"its height on the dashboard: {fit['taller'][name]} weight(s) taller than the book's cell "
                        + (f"and the dashboard {spec['dashboard']['height']}px high, so the rows beside it keep "
                           f"theirs " if name in fit.get("keep", ()) and spec else "") + f"(the generator: {why})")
    return spec


# A sheet too short for the generator gets at most this many height weights more among its row's neighbours, then a
# row of its own: more would squeeze them (a public book: State Wise and State Wise (%) under the map left it a 60px strip,
# decisions/066)
TALLER_MAX = 2
_CHART_SHORT = "too short for a chart"  # the generator's message (build.Builder.windows, decisions/101)
_CELL_ERROR = re.compile(r"(?:Registry|Sheet) '(.+?)': .*too (narrow|short)")


def _relpath(path, start):
    """path relative to start, posix; absolute when there is no relative path (another drive)."""
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(start).resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def _summary(s):
    t = s["type"]
    if t == "kpi":
        return "kpi " + ", ".join(m["field"] for m in s["measures"])
    if t == "bar":
        return f"bar {s['dimension']} x {s['measure']['field']}" + (f" by {s['color']}" if isinstance(
            s.get("color"), str) else "") + (f", top {s['top']['n']}" if "top" in s else "")
    if t in ("line", "area"):
        return f"{t} {s['date']['field']} ({s['date']['level']}) x {s['measure']['field']}" + (
            f" by {s['color']}" if "color" in s else "")
    if t in ("table", "heatmap"):
        return f"{t} {s['rows']} x {s['cols']}: {s['measure']['field']}"
    if t == "registry":
        return f"registry {s['rows']}: {', '.join(c['measure']['field'] for c in s['columns'])}"
    if t == "map":
        return f"map {s['geo']['field']} ({s['style']}): {s['measure']['field']}"
    return t

