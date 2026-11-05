"""Dimension filters v2 (decisions/035): the selection the workbook opens with, the card type, only relevant values,
exclude, context filters.

Spec, on a filter of values (`mode` other than the date modes range / relative of decisions/019):
  default: [values]   selected at open (shared-view lists them instead of the (All) state of decisions/021)
  mode: checkdropdown (= values, the default) | single_dropdown | single_list | single_slider | multi_list | wildcard
                      the card type (single_list, single_slider, wildcard: decisions/162)
  pattern, match      wildcard: the text typed in the card, contains (the default) | starts_with
  apply: true         the card has an Apply button (a multiple-values card; decisions/162)
  relevant: true      the card lists only the values relevant to the other filters (cascade Region -> City)
  exclude: true       default lists the values left out; values added to the data later pass
  context: true       (also on a date filter) a context filter: Tableau applies it before Top N and FIXED
  scope: dashboard | workbook   a book with several dashboards (decisions/071): the sheets of its card's dashboard
                      (the default), or every sheet of the data source (040)

A filter on a measure (decisions/162): mode range with numeric min / max on a number column, the row-level
[none:Sales:qk] in the shared view (Global Superstore), its card a range slider.

Order of operations (Tableau): context filters -> FIXED LOD, Top N -> dimension filters. expected.py follows it:
`split_rows` gives the context rows (what FIXED and Top N see) and the rows after all filters.

XML shapes are Desktop's: (All) -> decisions/021; one member: `member` with ui-domain / ui-enumeration inclusive
(SuperMart, TableauReportsUsage, CustomerSupportCaseDemo); several: `union` of `member` (golden_2025_1 as Desktop
2025.1 saved it before 021); exclude: `except` of level-members and the member (Citizen Service Requests,
Demand Capacity); context: `context="true"` on the shared filter (RETAIL-POS, DataQualityTesting); the card:
zone `mode` (`dropdown`: HelpDesk, SecOps) and `values` database / relevant. A filter of one dashboard (071): a
copy in the view of each sheet it applies to, `filter-group` N on every copy (a case's Web Engagement, Desktop 2025.1).
Cards of decisions/162: zone mode `radiolist` / `slider` (reference 'Filter Modes', 2024.2), `pattern` with a
`filter` groupfilter over level-members (CONTAINS / STARTSWITH, ui-pattern_text / _type: references 2023.1,
2020.1), `show-apply` (Enterprise Risk Dashboard, 2025.1).
"""
import xml.etree.ElementTree as ET

from . import dates

USER_NS = "http://www.tableausoftware.com/xml/user"
# spec mode -> the filter zone's mode attribute
CARD = {"values": "checkdropdown", "checkdropdown": "checkdropdown", "single_dropdown": "dropdown",
        "single_list": "radiolist", "single_slider": "slider", "multi_list": "checklist", "wildcard": "pattern"}
SINGLE = {"single_dropdown", "single_list", "single_slider"}
# card modes whose zone Desktop saved for us; multi_list = the right panel's list (golden_2025_1, decisions/002)
VERIFIED = {"values", "checkdropdown", "single_dropdown", "multi_list", "single_list", "single_slider", "wildcard"}
LISTS = {"multi_list", "single_list"}  # a line per value: the right panel only
APPLY = {"values", "checkdropdown", "multi_list"}  # cards with an Apply button (multiple values)
# spec match -> (user:ui-pattern_type, the function of the groupfilter's expression), as Desktop writes them
MATCH = {"contains": ("contains", "CONTAINS"), "starts_with": ("starts-with", "STARTSWITH")}
SLIDER_H_PX = 80  # a single value slider card: field name, value box, slider (decisions/162)


def is_measure_range(f):
    """A dashboard filter on a measure (decisions/162): range with numeric bounds."""
    return f.get("mode") == "range" and isinstance(f.get("min"), (int, float))


def is_dimension(f):
    return not dates.is_date_filter(f) and not is_measure_range(f)


def is_wildcard(f):
    return f.get("mode") == "wildcard"


def card_mode(f):
    return CARD[f.get("mode", "values")]


def card_values(f):
    """The zone's `values`: which values the card lists."""
    return "relevant" if f.get("relevant") else "database"


def check(spec, prof, values_of=None):
    """Spec-level checks of the v2 options against the data (prof: the build's profile). values_of(field): the
    distinct values of a filter field (a calc's too, decisions/057); default: the profiled column's."""
    for f in spec.get("filters", []):
        where, mode = f"Filter on '{f['field']}'", f.get("mode", "values")
        if "scope" in f and "dashboards" not in spec:
            raise ValueError(f"{where}: scope applies to a book with several dashboards (decisions/071)")
        if "sheets" in f:
            _check_sheets(spec, f, where)
        if scope(spec, f) is not None and (not is_dimension(f) or f.get("context")):
            kind = "context" if f.get("context") else "measure" if is_measure_range(f) else "date"
            raise ValueError(f"{where}: a {kind} filter of some sheets only is not verified in Desktop yet; give it "
                             f"scope 'workbook', without sheets (decisions/071, 074)")
        if not is_dimension(f):
            for k in ("default", "exclude", "relevant", "pattern", "match", "apply"):
                if k in f:
                    raise ValueError(f"{where}: '{k}' applies to a filter of values, not to a {mode} "
                                     f"{'measure' if is_measure_range(f) else 'date'} filter")
            if is_measure_range(f):
                _check_measure_range(where, f, prof)
            continue
        if mode not in VERIFIED:
            raise ValueError(f"{where}: card mode '{mode}' is not verified in Desktop yet (decisions/035); use "
                             f"single_dropdown or checkdropdown")
        if f.get("apply") and mode not in APPLY:
            raise ValueError(f"{where}: an Apply button is verified on a multiple-values card (checkdropdown, "
                             f"multi_list), not on {mode}: a single-value card applies at once (decisions/162)")
        if is_wildcard(f):
            _check_wildcard(where, f, prof)
            continue
        for k in ("pattern", "match"):
            if k in f:
                raise ValueError(f"{where}: '{k}' applies to a wildcard card (mode wildcard)")
        if f.get("exclude") and not f.get("default"):
            raise ValueError(f"{where}: exclude needs default, the values left out")
        if f.get("default") is not None:
            _check_default(where, f, set(values_of(f["field"]) if values_of else prof.col(f["field"]).distinct),
                           mode)


def _check_measure_range(where, f, prof):
    """A range filter on a measure (decisions/162): a number column of the data, min <= max."""
    if f["field"] not in {c.name for c in prof.columns}:
        raise ValueError(f"{where}: a range on a measure takes a number column of the data; a calc is not verified")
    col = prof.col(f["field"])
    if col.datatype not in ("integer", "real"):
        raise ValueError(f"{where}: numeric min / max need a number column, '{col.name}' is {col.datatype} (a date "
                         f"range takes YYYY-MM-DD bounds)")
    if not isinstance(f.get("max"), (int, float)):
        raise ValueError(f"{where}: a range on a measure takes numeric min and max")
    if f["min"] > f["max"]:
        raise ValueError(f"{where}: min {f['min']} is above max {f['max']}")
    if f.get("context"):
        raise ValueError(f"{where}: a context filter on a measure is not verified in Desktop yet (decisions/162)")


def _check_wildcard(where, f, prof):
    """A wildcard card (decisions/162): a text column of the data, a pattern Desktop matches as the build does."""
    for k in ("default", "exclude", "relevant", "context"):
        if k in f:
            raise ValueError(f"{where}: '{k}' is not verified with a wildcard card (decisions/162)")
    if f["field"] not in {c.name for c in prof.columns} or prof.col(f["field"]).datatype != "string":
        raise ValueError(f"{where}: a wildcard card takes a text column of the data (a calc or a group is not "
                         f"verified)")
    pattern = f.get("pattern")
    if pattern is None:
        if "match" in f:
            raise ValueError(f"{where}: match without pattern")
        return
    bad = [c for c in ("'", "\\", "\n", '"') if c in pattern]
    if bad:
        raise ValueError(f"{where}: pattern {pattern!r}: {bad[0]!r} in the expression literal is not verified")
    values = prof.col(f["field"]).distinct
    kept = {v for v in values if matches(f, v)}
    if not kept:
        raise ValueError(f"{where}: pattern {pattern!r} matches no value of the data: the card would show nothing")
    lower = {v for v in values if matches({**f, "pattern": pattern.lower()}, v.lower())}
    if lower != kept:
        raise ValueError(f"{where}: pattern {pattern!r} keeps {sorted(kept)[:6]} matched with case and "
                         f"{sorted(lower - kept)[:6]} more without; Desktop's case rule is not verified, use a "
                         f"pattern where case does not matter")


def matches(f, value):
    """Does a wildcard pattern keep this value (CONTAINS / STARTSWITH, with case)?"""
    pattern = f["pattern"]
    return value.startswith(pattern) if f.get("match", "contains") == "starts_with" else pattern in value


def _check_sheets(spec, f, where):
    """A filter of listed sheets (decisions/074): sheets of the spec, its card on one of them, not on every sheet."""
    names = {s["name"] for s in spec["sheets"]}
    unknown = [n for n in f["sheets"] if n not in names]
    if unknown:
        raise ValueError(f"{where}: sheets {unknown}: no sheet of that name")
    if f.get("scope") == "workbook":
        raise ValueError(f"{where}: sheets limits the filter, scope 'workbook' spreads it; give one of them")
    if f["show_on"] not in f["sheets"]:
        raise ValueError(f"{where}: show_on '{f['show_on']}' is not among its sheets {f['sheets']}: the card would "
                         f"stand on a sheet the filter does not change")


def _check_default(where, f, values, mode="values"):
    """The values a filter selects (or leaves out) at open, against the field's values in the data."""
    default = f["default"]
    if len(set(default)) != len(default):
        raise ValueError(f"{where}: default repeats a value: {default}")
    unknown = sorted(set(default) - values, key=str)
    if unknown:
        raise ValueError(f"{where}: default {unknown} is not in the data (values: {sorted(values, key=str)[:12]})")
    bad = sorted(v for v in default if isinstance(v, str) and '"' in v)
    if bad:
        raise ValueError(f"{where}: default {bad}: a value with '\"' in a member literal is not verified")
    if mode in SINGLE and len(default) != 1:
        raise ValueError(f"{where}: a single-value card ({mode}) selects one value, default has {len(default)}")
    if f.get("exclude") and mode in SINGLE:
        raise ValueError(f"{where}: exclude needs a multiple-values card, not {mode}")
    if set(default) == values:
        raise ValueError(f"{where}: default {'excludes' if f.get('exclude') else 'selects'} every value of the "
                         f"data; " + ("nothing would be shown" if f.get("exclude") else
                                      "leave it out: (All) also keeps the values added later (decisions/021)"))
    if f.get("exclude") and len(default) > 1:
        raise ValueError(f"{where}: exclude of several values is not verified in Desktop yet (decisions/035)")


def selection(f, where=None):
    """(values, excluded) a filter of values keeps: the workbook user's choice in `where`, else the default;
    values None = (All)."""
    if where is not None and f["field"] in where:
        return set(where[f["field"]]), False
    if f.get("default"):
        return set(f["default"]), bool(f.get("exclude"))
    return None, False


def keeps(f, value, where=None):
    """Does the filter keep a row with this value? Null (Desktop 2025.1, decisions/056): kept by (All) and by an
    exclude, dropped by a list of values."""
    if is_wildcard(f) and f.get("pattern") is not None and not (where and f["field"] in where):
        return value != "" and matches(f, value)  # CONTAINS(Null) is Null: the row drops out
    values, excluded = selection(f, where)
    if value == "":
        return values is None or excluded
    if values is None:
        return True
    return (value not in values) if excluded else (value in values)


def scope(spec, f):
    """The spec sheets a filter applies to, None = every sheet of the data source (the shared-view of 021/035).
    `sheets` (decisions/074): those sheets. A book with several dashboards (071): the sheets of its card's dashboard
    (show_on's), with every dashboard sharing a sheet with them, so no sheet is filtered on one dashboard and not on
    another; `scope: workbook` or one dashboard: None. A switch's views go with the switch. A scope over every sheet
    of every dashboard is the shared-view too (golden_nav). With several datasources (decisions/083) the spec is the
    filter's source's (spec.split): the dashboards count with that source's sheets only."""
    from .build import _leaves
    from .interact import SWITCH
    own = {s["name"] for s in spec["sheets"]}
    grids = [set(_leaves(d["grid"])) & own for d in spec.get("dashboards") or [spec["dashboard"]]]
    if "sheets" in f:
        names = set(f["sheets"])
    elif "dashboards" not in spec or f.get("scope") == "workbook":
        return None
    else:
        names = set().union(*(g for g in grids if f["show_on"] in g))
        while any(g & names and not g <= names for g in grids):
            names |= set().union(*(g for g in grids if g & names))
    if all(g <= names for g in grids):
        return None
    return names | {v for s in spec["sheets"] if s["type"] == SWITCH and s["name"] in names
                    for v in s["views"].values()}


def applies(spec, f, sheet):
    """Does filter f filter this sheet (a spec sheet or a part of one: 'KPI · Sales', 'Top · Region')?"""
    sc = scope(spec, f)
    return sc is None or any(sheet == n or sheet.startswith(n + " · ") for n in sc)


def split_rows(spec, prof, where=None, calc=None, sheet=None):
    """(context rows, rows after all filters): Tableau's order, context filters first (FIXED and Top N are computed
    on the context rows), then the dimension filters. calc: calc_values(...) when the caller has it. sheet: the rows
    of this sheet, without the filters of other dashboards (decisions/071)."""
    applied = [f for f in spec.get("filters", []) if sheet is None or applies(spec, f, sheet)]
    date_filters = {id(f): dates.DateFilter(prof.col(f["field"]), f, prof.rows)  # once, not per row (decisions/051)
                    for f in applied if dates.is_date_filter(f)}
    calc = calc or calc_values(spec, prof)

    def keep(f, r):
        if id(f) in date_filters:
            return date_filters[id(f)].keeps(r[f["field"]])
        if is_measure_range(f):  # in-range: a Null drops out (decisions/162)
            return r[f["field"]] != "" and f["min"] <= float(r[f["field"]]) <= f["max"]
        return keeps(f, field_value(f, r, calc), where)

    ctx = [f for f in applied if f.get("context")]
    rest = [f for f in applied if not f.get("context")]
    context_rows = [r for r in prof.rows if all(keep(f, r) for f in ctx)]
    rows = [r for r in context_rows if all(keep(f, r) for f in rest)]
    return context_rows, rows


def write(parent, f, column, level):
    """The shared filter of values in the state the spec asks for."""
    attrs = {"class": "categorical", "column": column}
    if f.get("context"):
        attrs["context"] = "true"
    flt = ET.SubElement(parent, "filter", attrs)
    u = lambda k: f"{{{USER_NS}}}{k}"  # noqa: E731
    default = f.get("default")
    if is_wildcard(f) and f.get("pattern") is not None:  # decisions/162: the pattern over (All)
        ptype, fn = MATCH[f.get("match", "contains")]
        g = ET.SubElement(flt, "groupfilter", {"expression": f"{fn}({flt_field(level)}, '{f['pattern']}')",
                                               "function": "filter", u("ui-enumeration"): "inclusive",
                                               u("ui-pattern-include-all-when-empty"): "true",
                                               u("ui-pattern_text"): f["pattern"], u("ui-pattern_type"): ptype})
        ET.SubElement(g, "groupfilter", {"function": "level-members", "level": level, u("ui-enumeration"): "all",
                                         u("ui-marker"): "enumerate"})
        return flt
    if not default:  # (All), decisions/021
        ET.SubElement(flt, "groupfilter", {"function": "level-members", "level": level, u("ui-enumeration"): "all",
                                           u("ui-marker"): "enumerate"})
        return flt
    ui = {u("ui-domain"): card_values(f), u("ui-enumeration"): "exclusive" if f.get("exclude") else "inclusive",
          u("ui-marker"): "enumerate"}
    member = lambda p, v, extra=None: ET.SubElement(  # noqa: E731
        p, "groupfilter", {"function": "member", "level": level, "member": member_literal(v), **(extra or {})})
    if f.get("exclude"):
        g = ET.SubElement(flt, "groupfilter", {"function": "except", **ui})
        ET.SubElement(g, "groupfilter", {"function": "level-members", "level": level})
        member(g, default[0])
    elif len(default) == 1:
        member(flt, default[0], ui)
    else:
        g = ET.SubElement(flt, "groupfilter", {"function": "union", **ui})
        for v in sorted(default, key=str):  # Desktop lists the members in the field's order
            member(g, v)
    return flt


def flt_field(level):
    """[City] of the filter instance [none:City:nk]: the field a wildcard's expression names."""
    return "[" + level[1:-1].split(":")[1] + "]"


class MeasureRange:
    """A dashboard range filter on a measure (decisions/162), shaped like build.Field for the dependency writer: the
    row-level value [none:Sales:qk] (Global Superstore: quantitative, in-range, min and max)."""
    derivation, type, tc, kind, mode = "None", "quantitative", None, "measure_range", "range"

    def __init__(self, col, spec):
        self.col, self.spec = col, spec
        self.name = f"[none:{col.name}:qk]"

    def write(self, parent, column):
        el = ET.SubElement(parent, "filter", {"class": "quantitative", "column": column, "included-values": "in-range"})
        for k in ("min", "max"):
            ET.SubElement(el, k).text = number_literal(self.spec[k], self.col.datatype == "real")
        return el


def card_px(f):
    """Fixed width of a filter card in the dashboard header row: a measure range like a date range (both bounds
    and the slider on one line)."""
    from . import design
    return design.HEADER_DATE_RANGE_PX if isinstance(f, MeasureRange) else dates.card_px(f)


def card_h(f):
    """Height of a filter card in the header row or a sidebar: a single value slider has its slider under the
    value box (60px cut it off in Desktop 2025.1, decisions/162)."""
    from . import design
    return SLIDER_H_PX if f.get("mode") == "single_slider" else design.HEADER_FILTER_H_PX


def card_attrs(f, place):
    """mode / values of the filter's card zone. place: header (the dashboard header row), sidebar or panel (the
    right panel, a multiple-values list with a line per value, as the hand-made golden_2025_1 card)."""
    if not is_dimension(f):  # Desktop: no mode, a slider over the database values (decisions/019, 162)
        return {"values": "database"}
    mode, where = f.get("mode", "values"), f"Filter on '{f['field']}'"
    if place == "panel":
        if mode not in {"values"} | LISTS:
            raise ValueError(f"{where}: a {mode} card in the right panel is not verified in Desktop; give the "
                             f"dashboard a title (its cards go to the header row) or use multi_list / single_list")
        out = {} if mode in ("values", "multi_list") else {"mode": CARD[mode]}
    else:
        if mode in LISTS:
            raise ValueError(f"{where}: a {mode} card needs a line per value: only in the right panel (a "
                             f"dashboard without title and sidebar); here use checkdropdown / single_dropdown")
        out = {"mode": CARD[mode]}
    if f.get("relevant"):
        out["values"] = "relevant"
    if f.get("apply"):
        out["show_apply"] = "true"
    return out


def write_context(el, f):
    """A context date filter: context="true" after column, as Desktop orders the attributes."""
    if f.get("context"):
        attrs = dict(el.attrib)
        el.attrib.clear()
        for k, v in attrs.items():
            el.set(k, v)
            if k == "column":
                el.set("context", "true")


# ---- v3 (decisions/057): filters on calcs, a sheet's own filters, filters on a measure ------------------------------
# A sheet's own filters (spec sheets[].filters), written in its view, not in the shared view, no card:
#   {field, default: [v...], exclude}   a filter of values, on a column or a row-level calc (text or boolean)
#   {field, agg, min, max}              a filter on an aggregate: SUM([Sales]) >= 1000, an aggregate calc in a range
# Order of operations (Tableau): context -> FIXED -> dimension filters (the dashboard's and the sheet's) -> measure
# filters, at the sheet's level of detail (each mark's aggregate) -> table calcs.
SHEET_TYPES = ("kpi", "bar", "line", "area", "table", "heatmap", "registry",
               "histogram", "strip", "beeswarm", "calendar", "bump",  # decisions/140
               "slope", "boxplot", "waffle", "bubbles",  # decisions/141
               "funnel")  # decisions/159
SORTS = ("manual-sort", "computed-sort", "shelf-sorts", "sort", "natural-sort", "alphabetic-sort")


def member_literal(v):
    """A member as Desktop writes it: "East" (text); true / false (a boolean calc: a public book's Order Date Cutoff)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return f'"{v}"'


def number_literal(v, real):
    """A measure filter bound as Desktop 2025.1 saves it: a real aggregate's as a real (10000 -> '10000.0', 0.11),
    an integer one's (COUNT) as written."""
    from .params import real_literal
    return real_literal(v) if real or not isinstance(v, int) else str(v)


def _real_aggregate(fld):
    """Is the aggregate of a measure filter's instance a real? AVG always, COUNT never, else its column's type."""
    return fld.derivation == "Avg" or (fld.derivation not in ("Count", "CountD") and fld.col.datatype == "real")


def sheet_filters(s):
    """A sheet's own filters; a KPI tile (one worksheet per measure) has its KPI's."""
    return s.get("filters") or (s.get("kpi") or {}).get("filters", [])


def is_measure(f):
    """A sheet's filter on an aggregate (min / max), not on values."""
    return "min" in f or "max" in f


def _calc_fields(spec):
    return {f["field"] for f in spec.get("filters", []) if is_dimension(f)} | \
        {f["field"] for s in spec.get("sheets", []) for f in sheet_filters(s) if not is_measure(f)}


def calc_values(spec, prof, pars=None):
    """(name, row) -> value of a row-level calc a filter names; None when no filter names a calc."""
    columns = {c.name for c in prof.columns}
    if not _calc_fields(spec) - columns:
        return None
    from . import params as params_mod
    from .formula import CalcSet
    from . import compareviz
    from .fields import Fields
    types = {c.name: c.datatype for c in prof.columns}
    cs = CalcSet(spec.get("calcs", []) + compareviz.calcs(spec, types), types, prof.rows,  # + a waffle's cells (141)
                 pars if pars is not None else params_mod.load(spec, columns))
    groups = Fields(spec, prof).groups  # a filter by a group (decisions/151)

    def row_value(name, r):
        g = groups.get(name)
        if g is None:
            return cs.row_value(name, r)
        return g.value(cs.row_value(g.source, r) if g.of_calc else r[g.source])
    return row_value


def field_value(f, r, calc):
    """The row's value of the filter field: the CSV text, or the calc's value ('' for Null)."""
    if f["field"] in r:
        return r[f["field"]]
    v = calc(f["field"], r)
    return "" if v is None else v


def sheet_rows(s, rows, calc):
    """Rows a sheet's own filters of values keep (after the dashboard's filters)."""
    fs = [f for f in sheet_filters(s) if not is_measure(f)]
    if not fs:
        return rows
    return [r for r in rows if all(keeps(f, field_value(f, r, calc)) for f in fs)]


def measure_of(f):
    return {"field": f["field"], **({"agg": f["agg"]} if "agg" in f else {})}


def passes(f, v):
    """A mark's aggregate inside the filter's range (in-range: a null aggregate is left out)."""
    return v is not None and ("min" not in f or v >= f["min"]) and ("max" not in f or v <= f["max"])


def measure_rows(s, rows, keys, value):
    """Rows of the marks a sheet's measure filters keep: each mark (a group of rows by the sheet's keys) by its
    aggregate. keys: [(field, row -> key)] as expected.py groups; value(measure) -> (rows, View) -> number."""
    fs = [f for f in sheet_filters(s) if is_measure(f)]
    if not fs:
        return rows
    from .formula import View
    groups = {}
    for r in rows:
        groups.setdefault(tuple(fn(r) for _, fn in keys), []).append(r)
    view = View(keys, rows)
    kept = {k for k, g in groups.items() if all(passes(f, value(measure_of(f))(g, view)) for f in fs)}
    return [r for r in rows if tuple(fn(r) for _, fn in keys) in kept]


def distinct(b, name):
    """Distinct non-null values of a filter field: a CSV column's, or a row-level calc's over the data."""
    if name in b.group_cols:
        return set(b.group_cols[name].distinct)
    if name in b.calc_cols:
        c = b.calc_cols[name].calc
        if c.datatype == "boolean" and c.params:  # true / false at some value of its parameters (a public book's cutoff)
            return {True, False}
        return {v for v in (b.calcs.row_value(name, r) for r in b.prof.rows) if v is not None}
    return set(b.prof.col(name).distinct)


def check_calc_field(b, name, where):
    """A filter of values on a calc: a row-level text or boolean calc, without LODs or table calcs."""
    col = b.calc_cols.get(name)
    if col is None:
        return
    c = col.calc
    if c.is_agg or c.uses_view_lod or c.table_calc:
        raise ValueError(f"{where}: '{name}' is an aggregate (or a LOD / table calculation); filter it on a sheet "
                         f"as a measure (min / max)")
    if c.datatype not in ("string", "boolean"):
        raise ValueError(f"{where}: '{name}' is a {c.datatype} calc; filters of values take text or boolean calcs")
    formulas = [c.xml_formula] + [b.calcs.calcs[n].xml_formula for n in c.calc_deps]
    if any("FIXED" in f.upper() for f in formulas):
        raise ValueError(f"{where}: '{name}' uses FIXED; a filter on a FIXED calc is not verified (order of operations)")


def check_sheets(b):
    """The sheets' own filters against the data and the sheet (after the calcs are compiled)."""
    from . import heatmap, reflines, totals
    shared = {f["field"] for f in b.spec.get("filters", [])}
    for s in b.spec["sheets"]:
        fs = sheet_filters(s)
        if not fs:
            continue
        where = f"Sheet '{s['name']}'"
        if s["type"] not in SHEET_TYPES or s.get("style") == "cards" or "plan" in s:
            raise ValueError(f"{where}: a sheet's own filters are verified on {', '.join(SHEET_TYPES)} (kpi tiles, "
                             f"bars without a plan)")
        seen = set()
        for f in fs:
            fw = f"{where}, filter on '{f['field']}'"
            if f["field"] in seen:
                raise ValueError(f"{fw}: the field has two filters on the sheet")
            seen.add(f["field"])
            if f["field"] in shared:
                raise ValueError(f"{fw}: the field also has a dashboard filter; Tableau keeps one filter per field on "
                                 f"a sheet")
            if is_measure(f):
                _check_measure(b, f, fw)
                continue
            if "top" in s and not after_filters(s) and f["field"] == params_top_dim(s):  # a rank filter: its own
                raise ValueError(f"{fw}: the sheet's Top N is a filter on that field too; Tableau keeps one")
            b.col(f["field"])  # unknown field -> a clear error
            check_calc_field(b, f["field"], fw)
            if f["field"] not in b.calc_cols and b.prof.col(f["field"]).datatype != "string":
                raise ValueError(f"{fw}: a {b.prof.col(f['field']).datatype} column; a sheet's filter of values "
                                 f"takes a text column or a text / boolean calc (dates: a dashboard range filter)")
            if not f.get("default"):
                raise ValueError(f"{fw}: without default it keeps every value; give the values it keeps (or "
                                 f"leaves out with exclude)")
            _check_default(fw, f, distinct(b, f["field"]))
        if any(is_measure(f) for f in fs):
            ms = ([s["measure"]] if "measure" in s else []) + s.get("measures", []) + \
                [c["measure"] for c in s.get("columns", [])]
            tc = [m["field"] for m in ms if "table_calc" in m or getattr(getattr(b.col(m["field"]), "calc", None),
                                                                           "table_calc", False)]
            if tc or totals.of(s):
                raise ValueError(f"{where}: a measure filter with table calculations or totals is not verified "
                                 f"(Tableau computes them after the measure filter)")
            if reflines.lines(s):
                raise ValueError(f"{where}: a measure filter with reference lines is not verified")
        if heatmap.margins(s):
            raise ValueError(f"{where}: a sheet's own filters with marginal totals are not supported yet")


def params_top_dim(s):
    from . import params as params_mod
    return params_mod.top_by(s)[0]


def _check_measure(b, f, where):
    if "default" in f or "exclude" in f:
        raise ValueError(f"{where}: min / max filter an aggregate; default / exclude filter values")
    col = b.col(f["field"])
    calc = getattr(col, "calc", None)
    if calc is not None and not calc.is_agg:
        raise ValueError(f"{where}: '{f['field']}' is a row-level calc; a measure filter takes a numeric column "
                         f"with agg or an aggregate calc")
    if calc is not None and (calc.table_calc or calc.uses_view_lod):
        raise ValueError(f"{where}: a filter on a table calculation or INCLUDE/EXCLUDE is not supported")
    if calc is None and col.datatype not in ("integer", "real") and f.get("agg", "sum") not in ("count", "countd"):
        raise ValueError(f"{where}: '{f['field']}' is {col.datatype}; a measure filter needs a number")
    if calc is not None and calc.datatype not in ("integer", "real"):
        raise ValueError(f"{where}: '{f['field']}' is a {calc.datatype} aggregate; a measure filter needs a number")
    if "min" in f and "max" in f and f["min"] > f["max"]:
        raise ValueError(f"{where}: min {f['min']} is above max {f['max']}")


def sheet_fields(b, s):
    """The instances of a sheet's own filters, in spec order: [none:Region:nk], [sum:Sales:qk], [usr:Calc:qk]."""
    from .build import Field
    return [b._measure(measure_of(f)) if is_measure(f) else Field(b.col(f["field"]), "dim") for f in sheet_filters(s)]


def write_sheet(b, view, s, fields):
    """A sheet's own filters in its view, before the sorts; Desktop orders a view's filters by column (a public book,
    a public book). -> their columns for the slices, in spec order."""
    if not sheet_filters(s):
        return []
    holder = ET.Element("view")
    for f, fld in zip(sheet_filters(s), fields):
        col = b.q(fld.name)
        if is_measure(f):  # Bangalore's Residential Hotspots, a public book: in-range with the bounds given
            el = ET.SubElement(holder, "filter", {"class": "quantitative", "column": col, "included-values": "in-range"})
            for k in ("min", "max"):
                if k in f:
                    ET.SubElement(el, k).text = number_literal(f[k], _real_aggregate(fld))
        else:
            write(holder, {k: v for k, v in f.items() if k != "context"}, col, fld.name)
    _insert(view, holder)
    return [b.q(fld.name) for fld in fields]


def _insert(view, holder):
    """The filters of holder into the view, all its filters ordered by column, before the sorts."""
    existing = [ch for ch in view if ch.tag == "filter"]
    sorts = [i for i, ch in enumerate(view) if ch.tag in SORTS]
    at = list(view).index(existing[0]) if existing else (sorts[0] if sorts else len(view))
    for ch in existing:
        view.remove(ch)
    for i, el in enumerate(sorted(existing + list(holder), key=lambda e: e.get("column"))):
        view.insert(at + i, el)


def write_groups(b, view, groups):
    """The filters of one dashboard a sheet carries (decisions/071): Desktop's 'Apply to selected worksheets', the
    filter in the view with `filter-group` N, the same N on each sheet it applies to (a case's Web Engagement, Desktop
    2025.1). groups: [(spec filter, Field, N)] -> their columns for the slices."""
    holder = ET.Element("view")
    for f, fld, n in groups:
        write(holder, f, b.q(fld.name), fld.name).set("filter-group", str(n))
    _insert(view, holder)
    return [b.q(fld.name) for _, fld, _ in groups]


def order_view(view, s, grouped=False):
    """Desktop 2025.1 saves a view's filters and its computed sort ordered by column, a filter before the sort of
    the same column (golden_params_filters_v3: filter on a calc, the sort of Product, the filter on Region).
    grouped: the view has filters of a dashboard (decisions/071)."""
    if not (sheet_filters(s) or grouped or after_filters(s)):  # a rank filter too (golden_top_after, 086)
        return
    kids = list(view)
    at = [i for i, ch in enumerate(kids) if ch.tag in ("filter", "computed-sort")]
    els = sorted((kids[i] for i in at), key=lambda e: (e.get("column"), e.tag != "filter"))
    for i, el in zip(at, els):
        view.remove(kids[i])
    for i, el in zip(at, els):
        view.insert(i, el)


# ---- Top N after the filters: a RANK table calc filtered to 1..N (decisions/086) ----------------------------------
# a public book's Sales by City: SUM(Sales) as a quick table calc Rank (Competition, Descending, along City) and a filter of
# its members 1..5. A table calc is computed after every filter (context, dimension, measure), so this is the top N
# of the marks the sheet shows; the Top N filter of decisions/020 ranks before the dimension filters.
RANK_OPTIONS = "Competition,Descending"  # Desktop's default rank: 1, 2, 2, 4; the largest first


def after_filters(s):
    return s.get("top", {}).get("after") == "filters"


def check_rank(b, s, where):
    """Spec checks of top.after = filters (ValueError): a bar of one dimension, N a number from 2."""
    from . import colors, reflines
    n = s["top"]["n"]
    if s["type"] != "bar" or "plan" in s or colors.series_field(s):
        raise ValueError(f"{where}: Top N after the filters is a bar of one dimension for now (no plan, no color "
                         f"split)")
    if not isinstance(n, int) or n < 2:
        raise ValueError(f"{where}: Top N after the filters takes a number from 2 (members 1..N of the rank; a "
                         f"parameter N has no members to list)")
    if "by" in s["top"]:
        raise ValueError(f"{where}: Top N after the filters ranks by the bar's measure; 'by' is not supported")
    if "table_calc" in s["measure"]:
        raise ValueError(f"{where}: Top N after the filters on a table calculation measure is not supported")
    if reflines.lines(s) or reflines.vs_avg(s):
        raise ValueError(f"{where}: reference lines with Top N after the filters are not verified")


def rank_name(measure):
    """[rank:sum:Sales:ok] of the bar's measure instance [sum:Sales:qk]: discrete (ordinal), as Desktop names it."""
    return "[rank:" + measure.name[1:].rsplit(":", 1)[0] + ":ok]"


def rank_filter(b, view, s, fields):
    """The rank instance in the sheet's dependencies (not on a shelf) and its filter of members 1..N -> the column."""
    d, m = fields[0], fields[1]
    deps = next(x for x in view.findall("datasource-dependencies") if x.get("datasource") == b.ds)
    name = rank_name(m)
    ci = ET.Element("column-instance", {"column": f"[{m.col.name}]", "derivation": m.derivation, "name": name,
                                        "pivot": "key", "type": "ordinal"})
    ET.SubElement(ci, "table-calc", {"ordering-field": b.q(d.name), "ordering-type": "Field",
                                     "rank-options": RANK_OPTIONS, "type": "Rank"})
    kids = list(deps)
    at = next((i for i, k in enumerate(kids) if k.tag == "column-instance" and k.get("name") > name), len(kids))
    deps.insert(at, ci)
    col = b.q(name)
    flt = ET.Element("filter", {"class": "categorical", "column": col})
    g = ET.SubElement(flt, "groupfilter", {"function": "union", f"{{{USER_NS}}}ui-domain": "relevant",
                                           f"{{{USER_NS}}}ui-enumeration": "inclusive",
                                           f"{{{USER_NS}}}ui-marker": "enumerate"})
    for i in range(1, s["top"]["n"] + 1):
        ET.SubElement(g, "groupfilter", {"function": "member", "level": name, "member": str(i)})
    holder = ET.Element("view")
    holder.append(flt)
    _insert(view, holder)
    return col


def rank_members(groups, value, n):
    """Members whose competition rank (descending) is 1..n: rank = 1 + the number of larger values, so a tie at the
    n-th place keeps every tied member. groups: {member: rows}; a member without a value (Null) has no rank."""
    vals = {k: value(rs) for k, rs in groups.items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    ordered = sorted(vals.values(), reverse=True)
    return {k for k, v in vals.items() if 1 + sum(1 for o in ordered if o > v) <= n}
