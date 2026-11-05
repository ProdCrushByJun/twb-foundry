"""Parameters (todo 2.3, decisions/020): metric switch, Top N, period level.

Spec: `parameters: [{name, type, values | range {min, max, step}, default}]` (decisions/020, 057):
  string   values (a dropdown)
  integer  range (a slider) or values (a dropdown: a public book's Year Parameter)
  real     range (a slider) or values (a dropdown)
  date     range {min, max} of ISO dates (a date card: a public book's Order Date Cutoff) or values
  boolean  no domain: true / false (a dropdown)
A parameter is used by its name:
- in calc formulas, as [Name] or [Parameters].[Name] (tbuilder/formula.py: a constant, CASE switches over it, a
  string parameter of date levels can be the level of DATETRUNC);
- as the count of a bar's Top N filter: `top: {n: "Name"}` (or a fixed `top: {n: 10}`);
- in a dashboard or block title/subtitle: [Name] shows its current value.
Its control is a compact card in the dashboard header row after the filter cards (reference: `paramctrl
mode="compact"`, fixed 142px); a range parameter is a slider. Desktop 2025.1 names parameters [Parameter N] in the
datasource 'Parameters' (first in <datasources>); calcs refer to [Parameters].[Parameter N].
Logic lives here; build.py only calls in.
"""
import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import actions, design, filters, formula, interact, reflines, tables

DS = "Parameters"
NAME_REF = re.compile(r"\[([^\[\]]+)\]")  # [Name] in a title or subtitle
USER_NS = "http://www.tableausoftware.com/xml/user"
# a registry with one row dimension, by its first column (decisions/039); a line / area by its series field, a table
# by its row field, a heatmap by its rows (decisions/148)
TOP_SHEETS = ("bar", "registry", "line", "area", "table", "heatmap")


def top_by(s):
    """(dimension, measure spec) a sheet's Top N ranks: top.by if given (decisions/067), else the sheet's own measure;
    a registry's row by its first column, a line's series (its color field), a table's / heatmap's first row field."""
    by = s.get("top", {}).get("by")
    t = s["type"]
    if t == "registry":
        return s["rows"][0], by or s["columns"][0]["measure"]
    if t in ("line", "area"):
        return s.get("color"), by or s["measure"]
    if t in ("table", "heatmap"):
        r = s["rows"]
        return (r if isinstance(r, str) else r[0]), by or s["measure"]
    return s["dimension"], by or s["measure"]


def top_index(s):
    """Where the ranked dimension sits in the sheet's expected keys: a line's series follows its date."""
    return 1 if s["type"] in ("line", "area") else 0


def bottom(s):
    return s.get("top", {}).get("end") == "bottom"


TYPES = ("string", "integer", "real", "date", "boolean")
QUANTITATIVE = ("integer", "real", "date")  # Desktop: type quantitative (a date parameter too: a public book)


def real_literal(v):
    """A real as Desktop 2025.1 writes it: 17 significant digits, '.0' on a whole number. Re-saved by Desktop
    (decisions/057): a measure filter's 0.14 -> '0.14000000000000001', 10000 -> '10000.0', '0.11000000000000001'
    kept; Daimler P&L 2025.2: '0.080000000000000002', range '1.0'; Actual vs. Budget 2025.1: '2025.0'."""
    s = format(float(v), ".17g")
    return s if any(c in s for c in ".en") else s + ".0"


@dataclass
class Parameter:
    name: str  # spec name, the caption in Tableau
    datatype: str  # string | integer | real | date | boolean
    default: object  # typed: a date parameter's values are datetime.date
    values: list  # list domain (string, integer, real, date; boolean: [True, False]), else None
    range: dict  # range domain {min, max, step} (integer, real; date: no step), typed, else None
    index: int  # 1-based in spec order -> [Parameter N]
    value: object  # the value formulas are evaluated at: the default unless expected.py asks for another
    control: str = "card"  # card | radio | none: its card in the header row (decisions/042)
    aliases: dict = None  # {value key: label} of a list: the label the dropdown shows (decisions/148), else None
    source: str = None  # values_from: the CSV column its list is read from when the workbook opens (decisions/163)
    default_calc: str = None  # default_from: the calc whose value it takes when the workbook opens (decisions/163)

    def key(self, v):
        """A value as an alias is spelled in the spec: ISO date, true / false, else its text."""
        return v.isoformat() if self.datatype == "date" else "true" if v is True else "false" if v is False else str(v)

    @property
    def xml_name(self):
        return f"[Parameter {self.index}]"

    @property
    def ref(self):
        return f"[{DS}].{self.xml_name}"

    def literal(self, v):
        """The value as a Tableau literal: "Sales", 8, 0.5 / 2025.0, #2015-12-31#, true."""
        if self.datatype == "string":
            return f'"{v}"'
        if self.datatype == "real":
            return real_literal(v)
        if self.datatype == "date":
            return f"#{v.isoformat()}#"
        if self.datatype == "boolean":
            return "true" if v else "false"
        return str(v)

    def typed(self, v):
        """A spec value (JSON) as the parameter holds it: a date from its ISO text, a real as a float."""
        if self.datatype == "date" and isinstance(v, str):
            try:
                return dt.date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Parameter '{self.name}': {v!r} is not an ISO date (YYYY-MM-DD)") from None
        if self.datatype == "real" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        return v

    @property
    def mode(self):
        """Control: a dropdown of the values, radio buttons (reference Sample Superstore: mode list), a slider, or a
        date card (a date range: mode datetime, #RWFD Citizen Service Request, Sales vs Quota)."""
        if self.range:
            return "datetime" if self.datatype == "date" else "slider"
        return "list" if self.control == "radio" else "compact"

    def admits(self, v):
        if self.datatype == "boolean":
            return isinstance(v, bool)
        if self.values is not None:
            return v in self.values and type(v) is type(self.values[0])
        lo, hi = self.range["min"], self.range["max"]
        if self.datatype == "date":
            return isinstance(v, dt.date) and lo <= v <= hi
        step = self.range.get("step", 1)
        if self.datatype == "real":
            n = (v - lo) / step if isinstance(v, float) else None
            return n is not None and lo <= v <= hi and abs(n - round(n)) < 1e-9
        return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi and (v - lo) % step == 0

    def widest(self):
        """The longest text the parameter can show (title width estimates)."""
        if self.values is not None:
            return max([str(v) for v in self.values] + list((self.aliases or {}).values()), key=len)
        return max((str(self.range["min"]), str(self.range["max"])), key=len)


def _domain(p, where):
    """(values, range) of a spec parameter, typed, after the type / domain checks."""
    t, values, rng = p["type"], p.get("values"), p.get("range")
    if t not in TYPES:
        raise ValueError(f"{where}: type '{t}' (types: {', '.join(TYPES)})")
    if t == "boolean":
        if values is not None or rng is not None:
            raise ValueError(f"{where}: a boolean parameter is true or false; leave out values and range")
        return [True, False], None  # Desktop's members: true, false (Higher Education Admissions)
    if (values is None) == (rng is None):
        raise ValueError(f"{where}: a {t} parameter takes 'values' or 'range'" if t != "string" else
                         f"{where}: a string parameter takes 'values'")
    if t == "string" and rng is not None:
        raise ValueError(f"{where}: a string parameter takes 'values', not a range")
    probe = Parameter(p["name"], t, None, None, None, 0, None)
    if values is not None:
        typed = [probe.typed(v) for v in values]
        ok = {"string": str, "integer": int, "real": float, "date": dt.date}[t]
        bad = [v for v, x in zip(values, typed) if not isinstance(x, ok) or isinstance(x, bool)]
        if bad:
            raise ValueError(f"{where}: values {bad} are not {t} values")
        if len(set(typed)) != len(typed):
            raise ValueError(f"{where}: a value is listed twice")
        return typed, None
    rng = {k: probe.typed(v) for k, v in rng.items()}
    if t == "date" and "step" in rng:
        raise ValueError(f"{where}: a date range has no step (Desktop: any day between min and max)")
    if not rng["min"] < rng["max"]:
        raise ValueError(f"{where}: range min {rng['min']} must be below max {rng['max']}")
    if t == "integer" and (rng["max"] - rng["min"]) % rng.get("step", 1):
        raise ValueError(f"{where}: range {rng['min']}..{rng['max']} is not a whole number of steps "
                         f"{rng.get('step', 1)}")
    if t == "real":
        rng["step"] = float(rng.get("step", 1))
        n = (rng["max"] - rng["min"]) / rng["step"]
        if rng["step"] <= 0 or abs(n - round(n)) > 1e-9:
            raise ValueError(f"{where}: range {rng['min']}..{rng['max']} is not a whole number of steps "
                             f"{rng['step']}")
    return None, rng


def _field_values(p, prof, where):
    """values_from (decisions/163, Tableau 2020.1+ 'When workbook opens: from field'): the list is the column's
    values, re-read by Desktop at every open; here its distinct values in the data, ascending, nulls left out."""
    t, src = p["type"], p["values_from"]
    if t == "boolean" or "values" in p or "range" in p:
        raise ValueError(f"{where}: values_from takes the list from a field; leave out values and range "
                         f"(a boolean has no list)")
    if p.get("aliases"):
        raise ValueError(f"{where}: values_from keeps no members in the workbook, so its values have no aliases")
    if prof is None or src not in {c.name for c in prof.columns}:
        raise ValueError(f"{where}: values_from '{src}' is not a column of the data")
    have = prof.col(src).datatype
    if have != t:
        raise ValueError(f"{where}: values_from '{src}' is a {have} column; a {t} parameter lists a {t} column")
    read = {"string": str, "integer": int, "real": float, "date": dt.date.fromisoformat}[t]
    return sorted({read(r[src]) for r in prof.rows if r[src] != ""})


def _calc_default(p, spec, prof, where):
    """default_from (decisions/163, Desktop's default-value-field): the value of a calc of one value over the whole
    data when the workbook opens, {MAX([Order Date])} or {FIXED : MIN([Quantity])} as the references write it; here
    computed from the data. Not through a parameter (it would depend on itself)."""
    specs = {c["name"]: c for c in spec.get("calcs", [])}
    name = p["default_from"]
    if "default" in p:
        raise ValueError(f"{where}: give default or default_from, not both")
    if name not in specs:
        raise ValueError(f"{where}: default_from '{name}' is not a calculated field (calcs: {sorted(specs) or 'none'})")
    columns = {c.name: c.datatype for c in prof.columns}
    need, todo = {}, [name]
    while todo:
        n = todo.pop()
        if n in need:
            continue
        need[n] = specs[n]
        for r in formula._refs(formula.parse(specs[n]["formula"])):
            if isinstance(r, formula.Param) or (r.name not in columns and r.name not in specs):
                raise ValueError(f"{where}: default_from '{name}' refers to a parameter ([{r.name}]); the value at "
                                 f"open must come from the data alone")
            if r.name in specs:
                todo.append(r.name)
    cs = formula.CalcSet(list(need.values()), columns, prof.rows)
    c = cs[name]
    if not (isinstance(c.node, formula.Lod) and c.node.kind == "FIXED" and not c.node.dims):
        raise ValueError(f"{where}: default_from '{name}' must be one value over the whole data: a FIXED LOD "
                         f"without dimensions, e.g. {{MAX([Order Date])}} (got {c.formula})")
    if c.datatype != p["type"]:
        raise ValueError(f"{where}: default_from '{name}' is {c.datatype}; the parameter is {p['type']}")
    return cs.row_value(name, prof.rows[0])


def load(spec, columns, values=None, prof=None):
    """Spec parameters -> {name: Parameter}; `values` overrides the evaluation value ({name: value}); `prof` (the
    data) gives the values of values_from and default_from (decisions/163)."""
    out = {}
    calcs = {c["name"] for c in spec.get("calcs", [])}
    for i, p in enumerate(spec.get("parameters", []), 1):
        name, where = p["name"], f"Parameter '{p['name']}'"
        if name in out:
            raise ValueError(f"{where}: duplicate parameter name")
        if name in columns or name in calcs:
            raise ValueError(f"{where}: a {'CSV column' if name in columns else 'calculated field'} has the same "
                             f"name; [{name}] in a formula would be ambiguous")
        domain, rng = (_field_values(p, prof, where), None) if "values_from" in p else _domain(p, where)
        par = Parameter(name, p["type"], None, domain, rng, i, None, interact.control(p, spec), p.get("aliases"),
                        p.get("values_from"), p.get("default_from"))
        if par.aliases:
            known = {par.key(v) for v in domain or []}
            lost = sorted(k for k in par.aliases if k not in known)
            if lost:
                raise ValueError(f"{where}: aliases for {lost}, which are not values of the parameter "
                                 f"(values: {sorted(known) or 'none: a range has no aliases'})")
        if par.default_calc and prof is None:
            raise ValueError(f"{where}: default_from needs the data")
        default = _calc_default(p, spec, prof, where) if par.default_calc else par.typed(p["default"])
        par.default = par.value = par.typed(default)
        if not par.admits(par.default):
            dom = f"values from '{par.source}'" if par.source else \
                f"values {p.get('values', [True, False])}" if domain is not None else \
                "range" if par.datatype == "date" else "range steps"
            got = f"default_from '{par.default_calc}' gives {par.key(par.default)}, which" if par.default_calc else \
                f"default {p['default']!r}"
            raise ValueError(f"{where}: {got} is not one of its {dom}")
        out[name] = par
    for s in interact.buttons(spec) + interact.switches(spec):  # their calcs compare with text (decisions/042)
        p = out.get(s["parameter"])
        if p is not None and p.source:  # a button per value, written at build: the list at open may differ
            raise ValueError(f"Sheet '{s['name']}': {s['type']} need a fixed list; '{p.name}' takes its values from "
                             f"'{p.source}' when the workbook opens")
        if p is not None and p.datatype != "string" and p.values is not None:  # a range: interact.check says so
            raise ValueError(f"Sheet '{s['name']}': {s['type']} take a string parameter's values; '{p.name}' is "
                             f"{p.datatype}")
    for name, v in (values or {}).items():
        if name not in out:
            raise ValueError(f"Unknown parameter '{name}' (parameters: {sorted(out) or 'none'})")
        v = out[name].typed(v)
        if not out[name].admits(v):
            raise ValueError(f"Parameter '{name}': {v!r} is not one of its values")
        out[name].value = v
    return out


# ---- spec checks ------------------------------------------------------------------------------------------
def top_param(b, s):
    """The parameter a sheet's Top N counts by, or None (no Top N, or a fixed count)."""
    n = s.get("top", {}).get("n")
    return b.params[n] if isinstance(n, str) else None


def check(b):
    """Top N filters and parameter use; after the calcs are compiled (b.calcs)."""
    used = set()
    for c in b.calcs.calcs.values():
        used.update(c.params)
    d = b.spec["dashboard"]
    texts = [d.get("title"), d.get("subtitle")] + [t for s in b.spec["sheets"] for t in (s.get("title"),
                                                                                          s.get("subtitle"))]
    used.update(n for t in texts if t for n in NAME_REF.findall(t) if n in b.params)
    used.update(n for s in b.spec["sheets"] if isinstance(s.get("measure"), dict)
                for n in NAME_REF.findall(s["measure"].get("heading", "")) if n in b.params)
    used.update(reflines.params_used(b.spec))  # a reference line at a parameter (decisions/028)
    used.update(interact.params_used(b.spec))  # buttons, a period switch, a view switch (decisions/042)
    used.update(actions.params_used(b.spec))  # set by a click on a mark (decisions/160)
    for s in b.spec["sheets"]:
        if "top" not in s:
            continue
        where = f"Sheet '{s['name']}'"
        if s["type"] not in TOP_SHEETS:
            raise ValueError(f"{where}: Top N filters bars, lines, areas, tables, heatmaps and registries only")
        n, (dim, m) = s["top"]["n"], top_by(s)
        if s["type"] in ("line", "area") and not isinstance(dim, str):
            raise ValueError(f"{where}: Top N of a {s['type']} ranks its series: give the sheet a 'color' field")
        if s["type"] == "table" and len(tables.rows(s)) > 1:
            raise ValueError(f"{where}: Top N of a table ranks one row field; this one has two")
        if bottom(s) and filters.after_filters(s):
            raise ValueError(f"{where}: Bottom N cannot be ranked after the filters (top.after); the rank filter "
                             f"counts from the largest")
        if filters.after_filters(s):  # a rank filter of its own, after the others (decisions/086)
            filters.check_rank(b, s, where)
        elif dim in {f["field"] for f in b.spec.get("filters", [])}:
            raise ValueError(f"{where}: '{dim}' also has a dashboard filter; Tableau keeps one filter per "
                             f"field on a sheet, so the Top N would replace it on every sheet")
        if isinstance(n, str):
            if n not in b.params:
                raise ValueError(f"{where}: top n '{n}' is not a parameter (parameters: {sorted(b.params) or 'none'})")
            if b.params[n].datatype != "integer":
                raise ValueError(f"{where}: top n '{n}' is a {b.params[n].datatype} parameter; it must be integer")
            used.add(n)
        if "table_calc" in m:
            raise ValueError(f"{where}: Top N by a table calculation is not supported (Tableau ranks by the "
                             f"aggregate, not by the table calc)")
        col = b.col(m["field"])
        if "by" in s["top"]:
            b._measure(m)  # a number: an aggregate of a numeric column or a numeric aggregate calc
        if getattr(col, "calc", None) is not None and col.calc.uses_view_lod:
            raise ValueError(f"{where}: Top N by an INCLUDE/EXCLUDE measure is not supported yet")
    unused = [n for n in b.params if n not in used]
    if unused and not getattr(b, "part_of_many", False):  # a source of several: the book checks (decisions/083)
        raise ValueError(f"Parameters {unused} are not used by any calc, Top N or title: their control would "
                         f"change nothing; use them or remove them")
    if any(p.control != "none" for p in b.params.values()):
        if d.get("sidebar"):
            raise ValueError("Parameter controls stand in the dashboard header row; with a sidebar they are not "
                             "supported yet")
        if not (d.get("title") or d.get("subtitle")):
            raise ValueError("Parameter controls stand in the dashboard header row: the dashboard needs a title or "
                             "a subtitle")
    return used


# ---- titles -------------------------------------------------------------------------------------------------
def text(s, params):
    """'Top [Top N] products' -> 'Top <[Parameters].[Parameter 2]> products': a text-zone run that shows the
    parameter's current value (reference's header date). One run with the text around it: Desktop drops a run that is
    only a space ('Top 8products' with the parameter in a run of its own). [X] that is no parameter stays text."""
    return NAME_REF.sub(lambda m: f"<{params[m.group(1)].ref}>" if m.group(1) in params else m.group(), s)


def shown(text, params):
    """The text as wide as it can be shown: each [Parameter] replaced by its longest value."""
    return NAME_REF.sub(lambda m: params[m.group(1)].widest() if m.group(1) in params else m.group(), text)


# ---- XML ----------------------------------------------------------------------------------------------------
def _column(parent, p, ds, dependency=False):
    """A parameter column; in a dependency list Desktop leaves out the members (references: Bonus Project,
    Sample Superstore) and keeps the range. `ds`: the data source of its values_from / default_from fields."""
    attrs = {"caption": p.name, "datatype": p.datatype, "name": p.xml_name,
             "param-domain-type": "range" if p.range else "list", "role": "measure",
             "type": "quantitative" if p.datatype in QUANTITATIVE else "nominal", "value": p.literal(p.default)}
    shown = (p.aliases or {}).get(p.key(p.default))
    if shown is not None:  # the default's label (Enterprise Risk: <column alias='All' ... value='4'>, decisions/163)
        attrs["alias"] = shown
    if p.default_calc:  # from a calc when the workbook opens (Current vs Comparison Period, Enterprise Risk)
        attrs["default-value-field"] = f"[{ds}].[{formula.calc_id(p.default_calc)}]"
    if p.source:  # the list from a field when the workbook opens: no members (Current vs Comparison Period)
        attrs["source-field"] = f"[{ds}].[{p.source}]"
    el = ET.SubElement(parent, "column", dict(sorted(attrs.items())))
    ET.SubElement(el, "calculation", {"class": "tableau", "formula": p.literal(p.default)})
    if p.aliases:  # Desktop writes the labels twice: <aliases> here, in sheets' lists too, and member alias=
        al = ET.SubElement(el, "aliases")  # (golden_params_v2 --resave, decisions/148)
        for v in p.values:
            if p.key(v) in p.aliases:
                ET.SubElement(al, "alias", key=p.literal(v), value=p.aliases[p.key(v)])
    if p.range and p.datatype == "date":  # no granularity (a public book: <range max='#2015-12-31#' min='#2015-01-01#'/>)
        ET.SubElement(el, "range", max=p.literal(p.range["max"]), min=p.literal(p.range["min"]))
    elif p.range:
        ET.SubElement(el, "range", granularity=p.literal(p.range.get("step", 1)), max=p.literal(p.range["max"]),
                      min=p.literal(p.range["min"]))
    elif not dependency and not p.source:
        members = ET.SubElement(el, "members")
        for v in p.values:
            a = (p.aliases or {}).get(p.key(v))
            ET.SubElement(members, "member", {"alias": a, "value": p.literal(v)} if a is not None else
                          {"value": p.literal(v)})
    return el


def datasource(parent, b):
    """<datasource name='Parameters'>, first in <datasources> as Desktop writes it."""
    if not b.params:
        return
    ds = ET.SubElement(parent, "datasource", hasconnection="false", inline="true", name=DS, version="18.1")
    ET.SubElement(ds, "aliases", enabled="yes")
    for p in b.params.values():
        _column(ds, p, b.ds)


def datasource_deps(ds, b):
    """The CSV datasource depends on the parameters its calcs use, after <date-options> (Desktop 2025.1 Save As,
    out/params_lab/ref_topn); members are left out as in a sheet's list."""
    used = {n for c in b.calcs.calcs.values() for n in c.params}
    if not used:
        return
    deps = ET.SubElement(ds, "datasource-dependencies", datasource=DS)
    for p in sorted((b.params[n] for n in used), key=lambda p: p.xml_name):
        _column(deps, p, b.ds, dependency=True)


def _refs(parent, used, ds):
    """Parameters in a <datasources> list and their dependency block (before the CSV datasource's)."""
    dss = parent.find("datasources")
    ET.SubElement(dss, "datasource", name=DS)
    deps = ET.Element("datasource-dependencies", datasource=DS)
    first = next(i for i, ch in enumerate(parent) if ch.tag == "datasource-dependencies")
    parent.insert(first, deps)
    for p in sorted(used, key=lambda p: p.xml_name):
        _column(deps, p, ds, dependency=True)


def sheet_used(b, s, fields):
    """Parameters a worksheet depends on: through its calcs (transitively) and its Top N count."""
    names = {n for f in fields for col in b.with_deps(f.col) if getattr(col, "calc", None) for n in col.calc.params}
    if top_param(b, s) is not None:
        names.add(top_param(b, s).name)
    if isinstance(s.get("measure"), dict) and "card" in s:  # a KPI tile's heading says a parameter (decisions/148)
        names.update(n for n in NAME_REF.findall(s["measure"].get("heading", "")) if n in b.params)
    names.update(r["parameter"] for r in reflines.lines(s) if r["type"] == "param")
    names.update(v for r in reflines.lines(s) if r["type"] == "band" for v in (r["from"], r["to"])
                 if isinstance(v, str))  # a band at parameters (decisions/043)
    return [b.params[n] for n in names]


def sheet_refs(b, view, s, fields):
    used = sheet_used(b, s, fields)
    if used:
        _refs(view, used, b.ds)
    for p in used:  # its field and calc at open are the sheet's dependencies too (every reference, decisions/163)
        for name in (p.source, p.default_calc):
            if name:
                _declare(b, view, b.col(name))


def top_filter(b, view, s, fields):
    """Top N of the bar's dimension by its measure (Filter -> Top -> By field); -> the filtered instance, or None.

    Tableau computes it before the dimension filters (order of operations): the top members of the whole data,
    then the other filters (tbuilder/expected.py does the same)."""
    if "top" not in s:
        return None
    if filters.after_filters(s):  # a RANK table calc filtered to 1..N (decisions/086)
        return filters.rank_filter(b, view, s, fields)
    if s["type"] == "registry":  # its row by the first column's measure
        dims, cols = b.registry_cols[s["name"]]
        d, m = dims[0], cols[0]["measure"]
    elif s["type"] in ("line", "area"):  # [date, measure, series]
        d, m = fields[2], fields[1]
    elif s["type"] in ("table", "heatmap"):  # [row, column, measure]
        d, m = fields[0], fields[2]
    else:
        d, m = fields[0], fields[1]
    if "by" in s["top"]:  # by another measure (decisions/067)
        m = b._measure(s["top"]["by"])
        _declare(b, view, m.col)
    p = top_param(b, s)
    flt = ET.Element("filter", {"class": "categorical", "column": b.q(d.name)})
    sorts = [i for i, ch in enumerate(view) if ch.tag == "manual-sort"]  # filters come before the sorts
    view.insert(sorts[0] if sorts else len(view), flt)
    end = ET.SubElement(flt, "groupfilter", {"count": p.ref if p else str(s["top"]["n"]), "end": "bottom" if bottom(s) else "top",
                                             "function": "end", "units": "records", f"{{{USER_NS}}}ui-marker": "end",
                                             f"{{{USER_NS}}}ui-top-by-field": "true"})
    order = ET.SubElement(end, "groupfilter", {"direction": "DESC", "expression": _expression(m),
                                               "function": "order", f"{{{USER_NS}}}ui-marker": "order"})
    ET.SubElement(order, "groupfilter", {"function": "level-members", "level": d.name,
                                         f"{{{USER_NS}}}ui-enumeration": "all", f"{{{USER_NS}}}ui-marker": "enumerate"})
    return b.q(d.name)


def _declare(b, view, col):
    """The 'by field' of a Top N in the sheet's dependencies: its column (and a calc's columns) without an instance,
    in Desktop's order by bracketed name (a public book's State Wise (%): <column name='[Sales]'/>, no [sum:Sales:qk])."""
    deps = next(d for d in view.findall("datasource-dependencies") if d.get("datasource") == b.ds)
    have = {c.get("name") for c in deps.findall("column")}
    for c in b.with_deps(col):
        name = f"[{c.name}]"
        if name in have:
            continue
        el = b.column(deps, c)
        deps.remove(el)
        kids = list(deps)
        at = next((i for i, k in enumerate(kids) if k.tag != "column" or k.get("name") > name), len(kids))
        deps.insert(at, el)
        have.add(name)


def _expression(m):
    """The 'by field' of a Top N: SUM([Sales]), or an aggregate calc by its internal name."""
    if m.derivation == "User":
        return f"[{m.col.name}]"
    return f"{m.derivation.upper()}([{m.col.name}])"


def header_controls(b):
    """[(Parameter, card px)] for the dashboard header row, in spec order."""
    return [(p, design.HEADER_FILTER_PX) for p in b.params.values()
            if p.control != "none" and interact.card_here(b.spec, p.name)]  # a switch's: on its dashboard (082)


# Without a filter card the manifest has no ZoneBackgroundTransparency (build.py), and Desktop then writes the card's
# own white background on save (golden_reflines_2025_1; golden_params with a filter card has none).
CONTROL_BG = "#ffffff"


def control_zone(b, row, p, px, box, margin):
    """A parameter card in the header row, as the reference places them (fixed width, margins outside it); margin from
    tbuilder/spacing.py like the filter cards."""
    x, y, w, h = box
    z = ET.SubElement(row, "zone", {"fixed-size": str(px), "h": str(h), "id": b._zid(), "is-fixed": "true",
                                    "mode": p.mode, "param": p.ref, "type-v2": "paramctrl", "w": str(w),
                                    "x": str(x), "y": str(y)})
    b._zone_style(z, margin, background=None if b.filters else CONTROL_BG)


def dashboard_refs(b, db):
    """A dashboard with parameter cards lists Parameters first and depends on them (Loan Retention, Ads
    Campaigns); here Desktop keeps the members of a list parameter (out/params_lab/ref_topn)."""
    carded = [p for p, _ in header_controls(b)]  # a parameter without a card is no dependency (decisions/042)
    if not carded:
        return
    dss = db.find("datasources")
    if dss is None:
        dss = ET.Element("datasources")
        db.insert(list(db).index(db.find("size")) + 1, dss)
    dss.insert(0, ET.Element("datasource", name=DS))
    deps = ET.Element("datasource-dependencies", datasource=DS)
    db.insert(list(db).index(dss) + 1, deps)
    for p in sorted(carded, key=lambda p: p.xml_name):
        _column(deps, p, b.ds)


def manifest_flags(manifest, b):
    """ParameterDefaultValues (alphabetical, as Desktop writes it) when a parameter reads a field when the workbook
    opens: every reference with source-field / default-value-field has it (decisions/163)."""
    if not any(p.source or p.default_calc for p in b.params.values()) or manifest.find("ParameterDefaultValues") is not None:
        return
    later = [i for i, e in enumerate(manifest) if e.tag > "ParameterDefaultValues"]
    manifest.insert(later[0] if later else len(manifest), ET.Element("ParameterDefaultValues"))


# ---- expected -----------------------------------------------------------------------------------------------
def top_n(s, params):
    """The count of a sheet's Top N at the current parameter values, or None."""
    if "top" not in s:
        return None
    n = s["top"]["n"]
    return params[n].value if isinstance(n, str) else n


def top_members(rows, key, value, n, where, bottom=False):
    """Members of the top (bottom) n by value over rows (Tableau: before the dimension filters). Ties are broken
    A-Z by the member's text for both ends (measured in Desktop 2025.1, decision 148; not the data order)."""
    groups = {}
    for r in rows:
        k = key(r)
        if k is not None and k != "":
            groups.setdefault(k, []).append(r)
    ranked = sorted(((value(g), k) for k, g in groups.items()),
                    key=lambda vk: (vk[0] is None, (vk[0] or 0) if bottom else -(vk[0] or 0), str(vk[1])))
    return {k for _, k in ranked[:n]}
