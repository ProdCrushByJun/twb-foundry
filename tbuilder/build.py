"""spec (dict) + CSV -> .twbx, mirroring golden/golden_2025_1.twb (Tableau Desktop 2025.1).

Every structure emitted here was observed in a workbook saved by Desktop 2025.1;
comments point to the golden line ranges each builder reproduces.
"""
import contextlib
import functools
import math
import os
import random
import string
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import actions, cards, colors, dates, excel, formats, ink, params, reflines, registry, shell, spacing, theme
from . import sparkline
from . import kpi2, tablecalc, tooltips, totals
from . import heatmap
from . import benchmark
from . import dualaxis
from . import maps as maps_mod
from . import scatter
from . import treemap
from . import distviz
from . import waterfall
from . import barinbar
from . import pareto
from . import steparea
from . import funnel
from . import facetgrid
from . import compareviz
from . import tilegrid
from . import annotate
from . import gantt
from . import design
from . import nav
from . import interact
from . import insight, kpitable, tables
from . import barlabels
from . import fields as fields_mod
from . import folders as folders_mod
from . import filters as filters_mod
from . import expected as expected_mod
from . import fit
from . import gate
from . import hyper as hyper_mod
from . import spec as spec_mod
from .design import COLOR, FONT, SPACE
from .formula import Calc, CalcSet, Func

USER_NS = "http://www.tableausoftware.com/xml/user"
ET.register_namespace("user", USER_NS)
TEMPLATES = Path(__file__).parent / "templates" / "2025.1"

SOURCE_BUILD = "2025.1.0 (20251.25.0313.2002)"
REMOTE_TYPE = {"date": "133", "datetime": "135", "string": "129", "real": "5", "integer": "20"}
DEFAULT_AGG = {"date": "Year", "datetime": "Year", "string": "Count", "real": "Sum", "integer": "Sum"}
AGG = {"sum": ("sum", "Sum"), "avg": ("avg", "Avg"), "min": ("min", "Min"),
       "max": ("max", "Max"), "count": ("cnt", "Count"), "countd": ("ctd", "CountD"),
       "median": ("med", "Median")}
TRUNC = {"year": ("tyr", "Year-Trunc"), "quarter": ("tqr", "Quarter-Trunc"),
         "month": ("tmn", "Month-Trunc"), "week": ("twk", "Week-Trunc"), "day": ("tdy", "Day-Trunc")}
# Lines the reference authors switch off on almost every sheet (reference dashboards):
# table dividers, gridlines, zero lines, axis rulers and ticks, row banding.
# Rule order is the one Desktop 2025.1 writes on save (golden_declutter_2025_1).
DECLUTTER = [
    ("axis", [dict(attr="line-visibility", value="off"), dict(attr="stroke-size", value="0"),
              dict(attr="tick-color", value="#00000000")]),
    ("header", [dict(attr="band-color", scope="rows", value="#00000000")]),
    ("pane", [dict(attr="band-color", scope="rows", value="#00000000")]),
    ("gridline", [dict(attr="line-visibility", scope=sc, value="off") for sc in ("rows", "cols")]
     + [dict(attr="stroke-size", scope=sc, value="0") for sc in ("rows", "cols")]),
    ("zeroline", [dict(attr="line-visibility", value="off"), dict(attr="stroke-size", value="0")]),
    ("table-div", [dict(attr="line-visibility", scope=sc, value="off") for sc in ("rows", "cols")]
     + [dict(attr="stroke-size", scope=sc, value="0") for sc in ("rows", "cols")]),
]
# Quick table calcs: spec type -> (instance prefix, Tableau type). Semantics follow the formulas Desktop
# shows for them: SUM/TOTAL(SUM), ZN(SUM)-LOOKUP(ZN(SUM),-1), .../ABS(LOOKUP(...)), RUNNING_SUM(SUM).
TABLE_CALC = {"percent_of_total": ("pcto", "PctTotal"), "difference": ("diff", "Difference"),
              "percent_difference": ("pcdf", "PctDiff"), "running_total": ("cum", "CumTotal")}
FILTER_GROUP_FIRST = 3  # the first filter-group of a dashboard's filter (decisions/071)
MARK_CLASS = {"area": "Area", "heatmap": "Square", "treemap": "Square", "waterfall": "GanttBar", "gantt": "GanttBar", "funnel": "GanttBar", **distviz.MARK, **compareviz.MARK, "bubbles": "Circle", tilegrid.KIND: "Square", "card_history": "Bar",  # explicit marks; others stay Automatic
              kpi2.PILL: "Bar", kpi2.MARKER: "Bar",  # MIN(1) on a fixed 0..1 axis fills the zone (decisions/063)
              kpi2.STATUS: "Circle",  # a status dot (decisions/062)
              dualaxis.DOTS: "Circle",  # a donut legend's dots (decisions/069)
              dualaxis.LEGEND: "Text"}  # and its text beside them: 'member / value (share)'
# Calc formats other than a spec number format (tbuilder/formats.py): the card formats (tbuilder/cards.py: a date
# format is used as is).
FORMATS = {"delta": cards.DELTA_FORMAT, "delta_plain": cards.DELTA_PLAIN_FORMAT, "delta_pp": cards.DELTA_PP_FORMAT}
CARD_PARTS = ("tile", "card_value", "card_history", interact.BUTTON) + kpi2.PARTS  # drawn without a worksheet title
TILE_ALIGN = (("text-align", "left"), ("vertical-align", "center"))  # a KPI tile's text (decisions/068)
MAX_GRID_DEPTH = 3  # the top grid is level 1
MIN_CHECK = True  # refuse a chart zone too short for Desktop to draw (fit.short_charts, decisions/101); off in a lab


def _tpl(name):
    return ET.parse(TEMPLATES / name).getroot()


def card_lefts(right, boxes_px, size):
    """Zone units of the header cards' left edges, as Desktop 2025.1 writes them: a chain back from the row's right
    edge, each card's width in whole units (edge 6 at 1400, cards 150 + 152: 99571 - 10857 = 88714, - 10714 = 78000).
    Any other value Desktop rewrites on save."""
    lefts = []
    for px in reversed(boxes_px):
        right -= math.floor(px * 100000 / size)
        lefts.insert(0, right)
    return lefts


def _rand_id(n=28):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _simple_id(parent):
    ET.SubElement(parent, "simple-id", uuid="{" + str(uuid.uuid4()).upper() + "}")


def _cells(row):
    """Grid row -> [(sheet name | group, width weight)]; a cell is a name, {sheet, width} or a group {rows, ...}."""
    return [(c, 1) if isinstance(c, str) else (c.get("sheet", c), c.get("width", 1)) for c in row]


def _leaves(rows):
    """Sheet names of a grid in reading order, groups included."""
    for row in rows:
        for c, _ in _cells(row):
            yield from (_leaves(c["rows"]) if isinstance(c, dict) else [c])


def _groups(rows, depth=1):
    """(group, nesting depth) for every group cell of a grid; the top grid is depth 1."""
    for row in rows:
        for c, _ in _cells(row):
            if isinstance(c, dict):
                yield c, depth + 1
                yield from _groups(c["rows"], depth + 1)


def _split(start, total, weights):
    """Split [start, start+total) by integer weights -> [(offset, size)] with no gaps."""
    acc, out, s = 0, [], sum(weights)
    for w in weights:
        a, b = start + total * acc // s, start + total * (acc + w) // s
        out.append((a, b - a))
        acc += w
    return out


def _bold_parts(title):
    """'**Regions** Overview' -> [('Regions', True), (' Overview', False)]; without ** the whole title is bold."""
    if "**" not in title:
        return [(title, True)]
    return [(t, i % 2 == 1) for i, t in enumerate(title.split("**")) if t]


def _sub(parent, tag, **attrs):
    """SubElement with python-friendly attr names: fixed_size -> fixed-size, type_v2 -> type-v2."""
    return ET.SubElement(parent, tag, {k if k.startswith("{") else k.replace("_", "-"): v for k, v in attrs.items()})


@dataclass
class CalcColumn:
    """A calculated field, shaped like a profiled CSV column so Field can use it.

    name is the internal Tableau column name (Calculation_...), caption the visible one.
    """
    calc: Calc
    distinct: list

    @property
    def name(self):
        return self.calc.id

    @property
    def caption(self):
        return self.calc.name

    @property
    def datatype(self):
        return self.calc.datatype

    @property
    def role(self):
        # an INCLUDE/EXCLUDE formula is a measure even when it is text (golden_calcs_v2)
        return ("measure" if self.calc.is_agg or self.calc.view_lod or self.datatype in ("integer", "real")
                else "dimension")


def column_attrs(col, fmt=None, caption=None):
    """fmt: the number format of a CSV column (tbuilder/formats.py); a calc carries its own. caption: a CSV column's
    own name in the workbook (decisions/073), first as Desktop writes it."""
    if col.datatype in ("date", "datetime"):
        # Desktop types a DATETRUNC/DATEADD result as datetime (golden_cards_2025_1); a column or MAX() keeps its type,
        # and so do MAKEDATE / DATE / IIF of dates: a date (golden_calcs_v3_2025_1, decisions/055); IFNULL of two dates too, the formula's own type for a date and a datetime (golden_calcs_v4, decisions/149)
        dt = "datetime" if isinstance(col, CalcColumn) and isinstance(col.calc.node, Func) and \
            col.calc.node.name not in ("MAKEDATE", "DATE", "IIF", "IFNULL") else col.datatype
        attrs = dict(datatype=dt, name=f"[{col.name}]", role="dimension", type="ordinal")
    elif col.role == "measure":
        attrs = dict(datatype=col.datatype, name=f"[{col.name}]", role="measure",
                     type="quantitative" if col.datatype in ("integer", "real") else "nominal")  # an aggregate flag
    else:
        attrs = dict(datatype=col.datatype, name=f"[{col.name}]", role="dimension",
                     type="ordinal" if isinstance(col, fields_mod.DimColumn) else "nominal")  # a grouped number
    if caption and not isinstance(col, CalcColumn):
        attrs = {"caption": caption, **attrs}
    if isinstance(col, CalcColumn):
        attrs = {"caption": caption or col.caption, **attrs}  # fields.<calc>.caption (polish-26)
        f = col.calc.fmt
        if f:
            attrs["default_format"] = formats.tableau(f) if formats.is_number_format(f) else FORMATS.get(f, f)
    elif fmt:
        attrs["default_format"] = formats.tableau(fmt)
    return attrs


class Field:
    """A column instance on a shelf, e.g. [sum:Sales:qk] or [usr:Calculation_...:qk]."""

    def __init__(self, col, kind, how=None, tc=None, discrete=False):
        self.col, self.kind, self.tc, self.tc_order = col, kind, tc, []
        label = getattr(col, "caption", col.name)
        is_agg_calc = isinstance(col, CalcColumn) and col.calc.is_agg
        if kind == "dim":
            if is_agg_calc:
                raise ValueError(f"'{label}' is an aggregate calculation: it can only be a measure")
            if isinstance(col, CalcColumn) and col.calc.uses_view_lod:
                raise ValueError(f"'{label}' uses INCLUDE/EXCLUDE: it can only be a measure")
            if col.datatype in ("date", "datetime"):
                raise ValueError(f"'{label}' is a date: use a date trunc, not a plain dimension")
            if col.role == "measure":
                raise ValueError(f"'{label}' is numeric ({col.datatype}): numeric fields as dimensions "
                                 f"are not supported yet (no golden pattern)")
            prefix, self.derivation, self.type, self.order = "none", "None", "nominal", 0
            suffix = "nk"
        elif kind == "agg":
            if is_agg_calc != (how == "user"):
                raise ValueError(f"'{label}' is an aggregate calculation: remove 'agg'" if is_agg_calc
                                 else f"Unsupported aggregation '{how}' for '{label}'. Allowed: {sorted(AGG)}")
            if how not in AGG and how != "user":
                raise ValueError(f"Unsupported aggregation '{how}' for '{label}'. Allowed: {sorted(AGG)}")
            if how in ("sum", "avg") and col.datatype not in ("integer", "real"):
                raise ValueError(f"Cannot {how.upper()} non-numeric field '{label}' ({col.datatype})")
            (prefix, self.derivation) = ("usr", "User") if how == "user" else AGG[how]
            self.type, self.order = ("nominal", 0) if discrete else ("quantitative", 1)  # discrete: a flag on color
            suffix = "nk" if discrete else "qk"
        elif kind == "date":
            if col.datatype not in ("date", "datetime"):
                raise ValueError(f"'{label}' is {col.datatype}, not a date")
            if how not in TRUNC:
                raise ValueError(f"Unsupported date level '{how}'. Allowed: {sorted(TRUNC)}")
            (prefix, self.derivation), self.type, self.order = TRUNC[how], "quantitative", 2
            suffix = "qk"
            if discrete:  # a bar's periods as headers: [tmn:<date>:ok] (decisions/090)
                self.type, suffix = "ordinal", "ok"
        else:
            raise ValueError(kind)
        if tc:
            prefix = f"{TABLE_CALC[tc['type']][0]}:{prefix}"
        self.name = f"[{prefix}:{col.name}:{suffix}]"

    def column_attrs(self):
        return column_attrs(self.col)


class Builder:
    # What a data source has of its own (decisions/083): in a book with several sources the builder of the whole book
    # takes these from the source being drawn (_source), the rest is the book's
    SOURCE_ATTRS = ("spec", "prof", "fields", "group_cols", "csv_path", "ds", "excel", "hyper", "conn", "table",
                    "obj_id", "caption", "bin_cols", "params", "number_formats", "switch_views", "calcs", "calc_cols", "period",
                    "filters", "filter_spec", "filter_scope", "worksheets", "data_dir", "data_file", "folders")
    sources = None  # the builders of the sources, in a book with several (decisions/083)

    def __init__(self, spec, csv_path, hyper=False, part=False):
        """part: the builder of one source of a book with several (decisions/083): the book checks what spans them."""
        self.part_of_many = part
        self.params_used = set()  # the parameters some calc, Top N or title uses (params.check)
        spec = cards.own_formats(fields_mod.resolve_tokens(spec))  # fields.<f>.color by token name (decisions/091)
        nav.check(spec)  # several dashboards, the nav (decisions/040)
        self.dashes = nav.dashboards(spec)
        views = [{**spec, "dashboard": d} for d in self.dashes]  # the spec as each dashboard's checks read it
        # 'dashboard' is the one being drawn (self._on); outside of that the first, whose shell all share
        spec = self.spec = nav.primary(spec)
        self.locale = formats.workbook_locale(spec)  # <workbook locale> (decisions/085)
        self.window_ids = nav.window_ids(spec)
        self.prof = excel.load(csv_path, spec["datasource"])  # a CSV or an Excel table (decisions/025, 050)
        self._check_cards()
        self._check_registries()
        totals.check(spec)  # decisions/036
        tooltips.check(spec)
        for v in views:  # each dashboard's subtitle words
            colors.check(v, self.prof)
        heatmap.check(spec)  # color scales, marginal totals (decisions/041)
        barlabels.check(spec)  # values at the bar ends (decisions/087)
        barinbar.check(spec)  # parts inside the member's bar (decisions/156)
        dualaxis.check(spec)  # combo, donut, lollipop (decisions/044)
        maps_mod.check(spec, self.prof)  # geographic roles, known place names (decisions/046)
        scatter.check(spec, self.prof)  # decisions/047
        treemap.check(spec, self.prof)  # decisions/138
        distviz.check(spec, self.prof)  # decisions/140
        waterfall.check(spec)  # decisions/139
        pareto.check(spec)  # decisions/157
        funnel.check(spec)  # decisions/159
        gantt.check(spec, self.prof)  # polish-26
        compareviz.check(spec, self.prof)  # slope, box plot, waffle (decisions/141)
        facetgrid.check(spec, self.prof)  # small multiples in rows (decisions/144)
        tilegrid.check(spec, self.prof)  # tile map, wall (decisions/154)
        self.fields = fields_mod.Fields(spec, self.prof)  # aliases, order, groups, colors (decisions/033)
        self.group_cols = self.fields.groups
        self.bin_cols = distviz.bin_columns(spec, self.prof)  # histogram / beeswarm bins (decisions/140)
        self.bin_cols.update(tilegrid.bin_columns(spec, self.prof))  # a tile map's row and column (decisions/154)
        self.csv_path = Path(csv_path)
        self.ds = "federated." + _rand_id()
        self.excel = excel.is_excel(csv_path)  # decisions/025
        self.hyper = hyper  # the data is packaged as a .hyper (decisions/026)
        if self.excel and hyper:
            raise ValueError("hyper: packaging as a Hyper extract applies to a CSV source only")
        self.conn = ("excel-direct." if self.excel else "hyper." if hyper else "textscan.") + _rand_id()
        # the table object's caption; for a Hyper table also the relation name, the columns' parent
        self.table = self.prof.sheet if self.excel else hyper_mod.TABLE if hyper else self.csv_path.name
        self.obj_id = f"{hyper_mod.OBJECT if hyper else self.table}_{uuid.uuid4().hex.upper()}"
        self.caption = excel.caption(self.prof) if self.excel else self.csv_path.stem
        self.params = params.load(spec, {c.name for c in self.prof.columns}, prof=self.prof)  # decisions/020, 163
        self.number_formats = formats.fields(spec, self._datatype)  # decisions/032
        reflines.check(spec, self.prof, self.params)  # decisions/028
        benchmark.check(spec, self.prof, self.params)  # selected vs benchmark, line-end labels (decisions/043)
        for v in views:  # the period line and 'Data as of' need each dashboard's header (decisions/037)
            kpi2.check(v, self.prof)
        types = {c.name: c.datatype for c in self.prof.columns}
        self._check_card_calcs(types)
        self.switch_views = interact.check(spec, self.params, types)  # buttons, period, switch (decisions/042)
        self.calcs = CalcSet(spec.get("calcs", []) + cards.calcs(spec)
                             + registry.calcs(spec, registry.agg_calcs(spec, types, self.prof.rows, self.params))
                             + colors.calcs(spec) + shell.calcs(spec) + kpi2.calcs(spec) + interact.calcs(spec)
                             + benchmark.calcs(spec) + dualaxis.calcs(spec) + scatter.calcs(spec)
                             + treemap.calcs(spec) + insight.calcs(spec) + waterfall.calcs(spec) + funnel.calcs(spec) + barinbar.calcs(spec) + pareto.calcs(spec)
                             + distviz.calcs(spec, self.prof) + compareviz.calcs(spec, types) + annotate.calcs(spec) + gantt.calcs(spec)
                             + facetgrid.calcs(spec, self.prof) + tilegrid.calcs(spec) + heatmap.calcs(spec),
                             types, self.prof.rows, self.params)
        insight.check(spec, self.calcs)  # insight lines, tile notes, inline legends (decisions/045)
        tables.check(spec)  # a table's two row fields, its sort by the row total
        self.calc_cols = {name: CalcColumn(c, self._calc_distinct(c)) for name, c in self.calcs.calcs.items()}
        self.folders = folders_mod.of(self)  # the Data pane's field folders (decisions/146)
        kpitable.whole_formats(self)  # a KPI table's whole sums show without a fraction (decisions/106)
        grouped = {g.source for g in self.fields.groups.values() if g.of_calc}  # calcs a group groups (decisions/151)
        self.fields.check_calcs({n: (c.datatype == "string" and not (c.calc.is_agg or c.calc.uses_view_lod), c.distinct)
                                 for n, c in self.calc_cols.items() if n in self.fields.props or n in grouped})  # decisions/090
        self.period = interact.period_fields(self)  # the period switches' shared filters
        self.dzv = []  # (dashboard simple-id, dashboard name, zone id, flag calc) of the switch views
        for d in self.dashes:
            with self._on(d):
                self.params_used |= params.check(self)
        for f in spec.get("filters", []):  # a filter on a row-level text / boolean calc (decisions/057)
            filters_mod.check_calc_field(self, f["field"], f"Filter on '{f['field']}'")
        self.filters = [dates.DateFilter(self.prof.col(f["field"]), f, self.prof.rows) if dates.is_date_filter(f)
                        else filters_mod.MeasureRange(self.prof.col(f["field"]), f)  # decisions/162
                        if filters_mod.is_measure_range(f) and f["field"] in {c.name for c in self.prof.columns}
                        else Field(self._filter_col(f["field"]), "dim") for f in spec.get("filters", [])]
        for f in self.filters:  # a group is filtered as its column [Group], with no instance (decisions/151)
            if isinstance(f.col, fields_mod.GroupColumn):
                f.name = fields_mod.instance(f.col.name, f.col)
        filters_mod.check(spec, self.prof, lambda n: filters_mod.distinct(self, n))  # decisions/035, 057
        filters_mod.check_sheets(self)  # a sheet's own filters, measure filters (decisions/057)
        self.filter_spec = {self.q(f.name): s for f, s in zip(self.filters, spec.get("filters", []))}
        # the spec sheets of a dashboard's filter, None for a filter of every sheet (decisions/071)
        self.filter_scope = [filters_mod.scope(spec, s) for s in spec.get("filters", [])]
        self.block_headers = spec.get("block_headers", True)
        theme.check(spec)
        self.theme, self.font = theme.on(spec), theme.font(spec)  # card theme (decisions/030)
        self._zone_id = 2

    def _datatype(self, name):
        """A CSV column's type for formats.fields; None for a calc (its format is its own)."""
        if name in {c["name"] for c in self.spec.get("calcs", [])}:
            return None
        return self.prof.col(name).datatype

    def number_format(self, col):
        """The spec number format a column or calc is shown in, None when Tableau's automatic one."""
        if isinstance(col, CalcColumn):
            return col.calc.fmt if formats.is_number_format(col.calc.fmt) else None
        return self.number_formats.get(col.name)

    def _filter_col(self, name):
        if name in self.group_cols:  # a filter by group (decisions/151)
            return self.group_cols[name]
        if name in self.calc_cols:  # decisions/057
            return self.calc_cols[name]
        col = self.prof.col(name)
        if col.datatype in ("date", "datetime"):
            raise ValueError(f"Filter on '{name}': a date field needs mode 'range' or 'relative' (decisions/019)")
        return col

    def _check_registries(self):
        """Registry columns are checked before their calcs are generated (tbuilder/registry.py)."""
        calc_names = {c["name"] for c in self.spec.get("calcs", [])}
        for s in self.spec["sheets"]:
            if not registry.is_registry(s):
                continue
            where = f"Registry '{s['name']}'"
            labels = [registry.label(c) for c in s["columns"]]
            if len(set(labels)) != len(labels):
                raise ValueError(f"{where}: column labels must be unique, got {labels}")
            measures = [(c["measure"]["field"], c["measure"].get("agg", "sum")) for c in s["columns"]
                        if registry.style(c) in ("bar", "bar_inside", "tick")]
            if len(set(measures)) != len(measures):
                raise ValueError(f"{where}: a bar column repeats a measure; each bar column needs its own")
            registry.check(s)  # options of the column styles (decisions/039)
            sparkline.check_date(self, s)  # spark.date is a date of the data (decisions/153)
            for c in s["columns"]:
                for m in [c["measure"]] + [c[k] for k in ("base", "second") if k in c]:
                    if m["field"] not in calc_names:
                        self.prof.col(m["field"])

    def _check_cards(self):
        """KPI card options are checked before their calcs are generated (tbuilder/cards.py)."""
        for s in self.spec["sheets"]:
            if s["type"] != "kpi":
                continue
            where = f"KPI '{s['name']}'"
            if not cards.is_cards(s):
                extra = [k for k in ("date", "compare") + kpi2.KEYS if k in s] + [k for m in s["measures"]
                                                                                 for k in ("good", "per", "per_agg", "delta") if k in m]
                if extra:
                    raise ValueError(f"{where}: {sorted(set(extra))} only apply to style 'cards'")
                continue
            if "date" not in s:
                raise ValueError(f"{where}: style 'cards' needs 'date' (the field that defines the periods)")
            if self.prof.col(s["date"]["field"]).datatype not in ("date", "datetime"):
                raise ValueError(f"{where}: card date '{s['date']['field']}' is not a date column")
            own = {c["name"] for c in self.spec.get("calcs", [])}  # their turn is _check_card_calcs
            for m in s["measures"]:
                if "per_agg" in m and not cards.is_ratio(m):
                    raise ValueError(f"{where}: '{cards.label(m)}': per_agg is how 'per' adds up: give it 'per'")
                for f in {m["field"], m.get("per", m["field"])} - own:
                    self.prof.col(f)  # unknown field -> clear error before the card calcs are built
                if cards.is_ratio(m):  # decisions/110
                    if m.get("agg", "sum") != "sum" or "status" in m:
                        raise ValueError(f"{where}: '{cards.label(m)}' is a ratio (field / per): agg is sum, no status")
                    if kpi2.abs_delta(s):
                        raise ValueError(f"{where}: '{cards.label(m)}' is a ratio: the sheet's delta 'abs_pct' "
                                         f"(absolute | percent) does not apply")

    def _check_card_calcs(self, types):
        """A card's measure may be a row-level calc: its period adds up over the rows (decisions/198). An aggregate one
        cannot be cut to a period from outside. Said here in the spec's words, not about a generated calc."""
        cards_ = [s for s in self.spec["sheets"] if cards.is_cards(s)]
        own = {c["name"] for c in self.spec.get("calcs", [])}
        used = {f for s in cards_ for m in s["measures"] for f in (m["field"], m.get("per"))} & own
        calcs = CalcSet(self.spec["calcs"], types, self.prof.rows, self.params).calcs if used else {}
        for s in cards_:
            for m in s["measures"]:
                where, ratio = f"KPI '{s['name']}': '{cards.label(m)}'", cards.is_ratio(m)
                parts = [(m["field"], "sum" if ratio else m.get("agg", "sum"))]
                parts += [(m["per"], cards.per_agg(m).lower())] if ratio else []
                for f, how in parts:
                    if f in calcs and (calcs[f].is_agg or calcs[f].uses_view_lod):
                        raise ValueError(f"{where}: '{f}' is an aggregate calculation, and a card cuts its measure to a "
                                         f"period row by row. Give it a row-level field and 'per' (with 'per_agg' to "
                                         f"count): SUM(field) / COUNTD(per) of each period")
                    datatype = calcs[f].datatype if f in calcs else types[f]
                    if (ratio or f in calcs) and how not in ("count", "countd") and datatype not in ("integer", "real"):
                        raise ValueError(f"{where}: '{f}' is not a number, {how.upper()} needs one"
                                         + (" ('per_agg' counts)" if f == m.get("per") else ""))

    # ---- several data sources (decisions/083) ------------------------------------------------------------------
    @classmethod
    def multi(cls, spec, parts):
        """The builder of a book with several data sources. parts: [(sub-spec, data path, hyper)] of
        spec_mod.split. Each source is checked and compiled by a builder of its own (its sheets, calcs, filters);
        this one draws the book and takes a source's state while it writes that source's datasource, sheets and
        cards (_source)."""
        unsupported = shell.welcome(nav.primary(spec)) or kpi2.as_of_field(nav.primary(spec)) or any(
            s["type"] == interact.BUTTONS or kpi2.period_strip(s) for s in spec["sheets"]) or \
            interact.periods(nav.primary(spec))
        if unsupported:
            raise ValueError("Several datasources: a top bar welcome, data_as_of, period_line, buttons and a period "
                             "switch are not supported yet (decisions/083)")
        interact.check_sources(spec)  # a switch and its views take one datasource (decisions/082)
        subs = [cls(sub, path, hyper, part=True) for sub, path, hyper in parts]
        b = cls.__new__(cls)
        b.__dict__.update(subs[0].__dict__)  # the book's own state: dashboards, window ids, theme, zone ids
        for a in cls.SOURCE_ATTRS:
            setattr(b, a, None)  # outside a source nothing of one is at hand
        b.spec, b.params, b.switch_views = nav.primary(spec), subs[0].params, subs[0].switch_views
        b.filters = [f for sb in subs for f in sb.filters]  # any filter at all: manifest flags, card backgrounds
        b.filter_spec = {r: f for sb in subs for r, f in sb.filter_spec.items()}  # a card's spec filter by its field
        b.sources, b._cur = subs, None
        unused = [n for n in b.params if not any(n in sb.params_used for sb in subs)]
        if unused:
            raise ValueError(f"Parameters {unused} are not used by any calc, Top N or title: their control would "
                             f"change nothing; use them or remove them")
        data = [sb.csv_path.name for sb in subs]
        if len(set(data)) != len(data):
            raise ValueError(f"Several datasources: the data files {data} share a name; rename one")
        return b

    @contextlib.contextmanager
    def _source(self, i):
        """Meanwhile the builder is source i's: its spec (with the dashboard being drawn), data, calcs, filters,
        worksheets. A no-op in a book with one source, or when source i is already the current one."""
        if self.sources is None or i == self._cur:
            yield
            return
        sb, prev = self.sources[i], self._cur
        saved = {a: getattr(self, a) for a in self.SOURCE_ATTRS}
        sb.spec["dashboard"] = self.spec["dashboard"]
        for a in self.SOURCE_ATTRS:
            setattr(self, a, getattr(sb, a, None))  # worksheets, data_dir: set once the book is laid out
        self._cur = i
        try:
            yield
        finally:
            for a in self.SOURCE_ATTRS:
                setattr(sb, a, getattr(self, a))  # what the source got meanwhile (its data dir, ...)
            sb.spec["dashboard"] = saved["spec"]["dashboard"]
            for a, v in saved.items():
                setattr(self, a, v)
            self._cur = prev

    def _each_source(self, by_name=False):
        """Iterate with each source current in turn (decisions/083); once, as is, in a book with one. by_name: in the
        order of the datasource names, as Desktop 2025.1 saves shared views and a dashboard's sources (resave)."""
        order = list(range(len(self.sources) if self.sources else 1))
        if by_name and self.sources:
            order.sort(key=lambda i: self.sources[i].ds)
        for i in order:
            with self._source(i):
                yield i

    def _any_source(self, fn):
        """fn() true for some source, each current in turn."""
        found = False
        for _ in self._each_source():
            found = fn() or found
        return found

    def source_of(self, name):
        """The index of the source of a sheet, a part of one or a generated sheet (0 in a book with one source)."""
        return self.src_of.get(name, 0) if self.sources else 0

    def _source_of(self, name):
        return self._source(self.source_of(name))

    def owns(self, name):
        """Is the sheet one of the current source's (always, in a book with one source)?"""
        return self.sources is None or self.source_of(name) == self._cur

    @functools.cached_property
    def expected(self):
        """The numbers each sheet must show (tbuilder/expected.py): axis widths are sized from them."""
        if self.sources:  # every source's sheets, by sheet name
            return {k: v for sb in self.sources for k, v in sb.expected.items()}
        return expected_mod.compute(self.spec, self.csv_path, prof=self.prof)

    def _calc_distinct(self, calc):
        """Distinct values of a row-level dimension calc (legend sizing), computed from the CSV."""
        if calc.is_agg or calc.uses_view_lod or calc.datatype in ("integer", "real"):
            return []
        values = {self.calcs.row_value(calc.name, r) for r in self.prof.rows}
        return sorted(str(v) for v in values if v is not None)

    def col(self, name):
        """CSV column or calculated field by its visible name."""
        if name in self.calc_cols:
            return self.calc_cols[name]
        if name in self.group_cols:
            return self.group_cols[name]
        if name in self.bin_cols:
            return self.bin_cols[name]
        try:
            return self.prof.col(name)
        except ValueError as e:
            if self.calc_cols:
                raise ValueError(f"{e} Calculated fields: {sorted(self.calc_cols)}") from None
            raise

    def with_deps(self, col):
        """The column plus every CSV column and calc its formula needs (worksheet dependencies)."""
        if isinstance(col, fields_mod.GroupColumn):
            return fields_mod.deps(self, col)
        if isinstance(col, distviz.BinColumn):
            return [col, self.prof.col(col.source)]
        if not isinstance(col, CalcColumn):
            return [col]
        return ([col] + [self.prof.col(n) for n in col.calc.raw_deps]
                + [self.calc_cols[n] for n in col.calc.calc_deps])

    def shown(self, col):
        """The name a field shows in the workbook: a column's caption (decisions/073), a calc's name, else its name."""
        return self._caption(col) or getattr(col, "caption", col.name)

    def _caption(self, col):
        """fields.<name>.caption of a column, or of a calc by its spec name (polish-26)."""
        return self.fields.caption(col.name) or (self.fields.caption(col.caption) if isinstance(col, CalcColumn)
                                                 else None)

    def column(self, parent, col):
        if isinstance(col, distviz.BinColumn):  # a bin (decisions/140)
            return distviz.column(parent, col)
        el = _sub(parent, "column", **column_attrs(col, self.number_formats.get(col.name), self._caption(col)))
        if isinstance(col, CalcColumn):
            calc = _sub(el, "calculation", **{"class": "tableau"}, formula=col.calc.xml_formula)
            reflines.calculation(calc, col.calc)  # a generated table calc: Desktop's default compute-using
            tablecalc.calculation(calc, col.calc)  # a spec calc with table calc functions (decisions/034)
        maps_mod.column(el, col, self)  # a geographic role (decisions/046, by name: 092)
        fields_mod.column(self, el, col)  # aliases, a group's bins (decisions/033)
        return el

    def q(self, inst):
        return f"[{self.ds}].{inst}"

    # ---- datasource (golden 23-164) -------------------------------------------------
    @property
    def text_locale(self):
        """The CSV's text-file locale: the one its dates need (DD.MM -> ru_RU, MM/DD -> en_US), else the workbook's
        (ISO or no dates read in any; decisions/019, 085)."""
        return self.prof.locale or self.locale

    def _relation(self, parent):
        if self.excel:
            return excel.relation(parent, self)
        if self.hyper:
            return hyper_mod.relation(parent, self.conn)
        rel = _sub(parent, "relation", connection=self.conn, name=self.csv_path.name,
                   table=f"[{self.csv_path.name.replace('.', '#')}]", type="table")
        # Explicit separator: without it Desktop sniffs the delimiter and picks space when
        # values contain many spaces (a case: "North – Harbor", "Analyst B01").
        cols = _sub(rel, "columns", character_set="UTF-8", header="yes", locale=self.text_locale, separator=",")
        for i, c in enumerate(self.prof.columns):
            _sub(cols, "column", datatype=c.datatype, name=c.name, ordinal=str(i))

    def datasource(self, parent):
        ds = _sub(parent, "datasource", caption=self.caption, inline="true", name=self.ds, version="18.1")
        fed = _sub(ds, "connection", **{"class": "federated"})
        nc = _sub(_sub(fed, "named-connections"), "named-connection", caption=self.csv_path.stem, name=self.conn)
        if self.excel:
            excel.connection(nc, self)
        elif self.hyper:
            hyper_mod.connection(nc, self.data_file)
        else:
            _sub(nc, "connection", **{"class": "textscan"}, directory=self.data_dir, filename=self.csv_path.name,
                 password="", server="")
        self._relation(fed)
        if self.excel:
            excel.cols(fed, self)  # a join's field -> sheet column map (decisions/050)
        recs = _sub(fed, "metadata-records")
        if self.excel:
            excel.metadata(recs, self)
        else:
            self._text_metadata(recs)
        _sub(ds, "aliases", enabled="yes")
        # Desktop declares the measures a Measure Names palette maps and the fields a table-calc palette is
        # computed along (decisions/016, 028)
        measures = colors.measures(self) + reflines.along_fields(self) + pareto.along_fields(self)  # 157
        measures += kpi2.along_fields(self, {f.name for f in measures})  # a sparkline's point kinds (decisions/059)
        cols = {c.name: c for c in [*self.calc_cols.values(), *(f.col for f in measures),
                                    *map(self.prof.col, self.number_formats),  # a formatted column: decisions/032
                                    *fields_mod.declared(self),  # a column with properties: decisions/033
                                    *maps_mod.columns(self),  # a geographic role: decisions/046
                                    *self.bin_cols.values(),  # a bin: decisions/140
                                    *tilegrid.bin_sources(self)]}  # a tile map's row / column (decisions/154)
        labels = kpitable.aliases(self)
        if labels:  # Measure Names members shown under the spec's labels (decisions/106); ':' sorts before the letters
            kpitable.column(ds, labels)
        obj = f"[__tableau_internal_object_id__].[{self.obj_id}]"  # among them by name: after [Sales], before [id] (158)
        for key, col in sorted([(f"[{c.name}]", c) for c in cols.values()] + [(obj, None)], key=lambda x: x[0]):
            if col is None:  # as Desktop: [Product Line] < [Product] (061)
                _sub(ds, "column", caption=self.table, datatype="table", name=obj, role="measure", type="quantitative")
            else:
                self.column(ds, col)
        palettes = self._palettes()
        instances = [(inst, col, derivation, "nominal") for inst, col, derivation, _ in palettes if col]
        instances += [(f.name, f.col.name, f.derivation, f.type) for f in measures]
        instances += [i for i in fields_mod.instances(self) if i[0] not in {x[0] for x in instances}]
        for inst, col, derivation, typ in sorted(instances):  # the palette maps below refer to these instances
            ci = _sub(ds, "column-instance", column=f"[{col}]", derivation=derivation, name=inst, pivot="key", type=typ)
            reflines.instance_table_calc(self, ci)  # a table-calc flag: its compute-using here too (reference Ads)
            kpi2.instance_table_calc(self, ci)  # a sparkline's point kind, the same (decisions/059)
            registry.instance_table_calc(self, ci)  # a registry track's share and rest, the same (decisions/065)
            pareto.instance_table_calc(self, ci)  # a Pareto's vital flag, the same (decisions/157)
        folders_mod.write(self, ds)
        _sub(ds, "layout", dim_ordering="alphabetic", measure_ordering="alphabetic",
             show_structure="false" if self.folders else "true")
        if palettes:  # a palette map on a boolean calc or Measure Names, in the datasource style as Desktop does
            rule = _sub(_sub(ds, "style"), "style-rule", element="mark")
            for inst, _, _, maps in palettes:
                enc = _sub(rule, "encoding", attr="color", field=inst, type="palette")
                for bucket, color in sorted(maps, key=lambda bc: bc[1]):  # Desktop orders the maps by color
                    ET.SubElement(_sub(enc, "map", to=color), "bucket").text = bucket
            for inst, maps in sorted(registry.shape_maps(self).items()):  # citizeenservicerequests (decisions/139)
                enc = _sub(rule, "encoding", attr="shape", field=inst, type="shape")
                for bucket, shape in maps:
                    ET.SubElement(_sub(enc, "map", to=shape), "bucket").text = bucket
        ds.append(_tpl("semantic-values.xml"))
        maps_mod.semantic_values(ds, self.spec)  # the country states are looked up in (decisions/046)
        _sub(ds, "date-options", start_of_week="monday")
        fields_mod.default_sorts(self, ds)  # manual order of the members (decisions/033)
        params.datasource_deps(ds, self)  # the parameters its calcs use (decisions/020)
        obj = _sub(_sub(ds, "object-graph"), "objects")
        obj = _sub(obj, "object", caption=self.table, id=self.obj_id)
        self._relation(_sub(obj, "properties", context=""))

    def _text_metadata(self, recs):
        if not self.hyper:  # the text file's reading options; a Hyper table has none
            cap = _tpl("capability-record.xml")
            cap.find("parent-name").text = f"[{self.csv_path.name}]"
            dates.localize_capability(cap, self.text_locale)
            recs.append(cap)
        for i, c in enumerate(self.prof.columns):
            r = _sub(recs, "metadata-record", **{"class": "column"})
            for tag, text in [("remote-name", c.name), ("remote-type", REMOTE_TYPE[c.datatype]),
                              ("local-name", f"[{c.name}]"), ("parent-name", f"[{self.table}]"),
                              ("remote-alias", c.name), ("ordinal", str(i)), ("local-type", c.datatype),
                              ("aggregation", DEFAULT_AGG[c.datatype])]:
                ET.SubElement(r, tag).text = text
            if c.datatype == "string" and not self.hyper:
                ET.SubElement(r, "scale").text = "1"
                ET.SubElement(r, "width").text = "1073741823"
            ET.SubElement(r, "contains-null").text = "true"
            if c.datatype == "string":
                _sub(r, "collation", flag="0", name=hyper_mod.COLLATION if self.hyper
                     else dates.LOCALES[self.text_locale]["string_collation"])
            ET.SubElement(r, "object-id").text = f"[{self.obj_id}]"

    def _palettes(self):
        """Color maps on boolean calcs: [(instance, column, derivation, [(bucket, color)])], by instance name.

        KPI card history: the current period in the accent color, earlier ones muted. Registry highlight:
        flagged cells in the 'bad' background, the others in the column's own color.
        """
        out = {}
        for p in self.worksheets:
            if p["type"] == "card_history" and not reflines.changes(p) and not kpi2.line(p["card"]):
                col = self.calc_cols[cards.is_current(p["card"])].name
                out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", theme.history(self))])
            if registry.is_registry(p):
                for c in p["columns"]:
                    if "highlight" in c:
                        col = self.calc_cols[registry.flag_calc(p, c)].name
                        out[f"[usr:{col}:nk]"] = (col, "User", registry.flag_buckets(p, c))
                    elif registry.zero_filled(p, c):  # a 0 total bar in the total's shading (decisions/164)
                        col = self.calc_cols[registry.fill_calc(p, c)].name
                        out[f"[usr:{col}:nk]"] = (col, "User", registry.fill_buckets(p, c))
        out.update(colors.palettes(self))  # highlight, good/bad, plan (tbuilder/colors.py)
        out.update(reflines.palettes(self))  # color vs avg, history change (decisions/028)
        out.update(scatter.palettes(self))  # highlighted points (decisions/047)
        out.update(treemap.palettes(self))  # highlighted rectangles (decisions/138)
        out.update(distviz.palettes(self))  # a bump's highlighted lines (decisions/140)
        out.update(waterfall.palettes(self))  # a step's sign (decisions/139)
        out.update(pareto.palettes(self))  # the vital few (decisions/157)
        out.update(compareviz.palettes(self))  # slope, waffle flags (decisions/141)
        out.update(registry.pill_palettes(self))  # a registry pill's level fills (decisions/096)
        out.update(registry.sign_palettes(self))  # a registry status mark's sign (decisions/139)
        out.update(kpi2.palettes(self))  # the sign of a card's marker and pill (decisions/037)
        out.update(interact.palettes(self))  # the current value among the buttons (decisions/042)
        out.update(fields_mod.palettes(self))  # default colors of the members (decisions/033)
        return [(inst, *out[inst]) for inst in sorted(out)]

    # ---- shared helpers -----------------------------------------------------------------
    def _ds_ref(self, parent):
        """<datasources><datasource/>: one list with each source the element depends on (decisions/083)."""
        dss = parent.find("datasources")
        _sub(_sub(parent, "datasources") if dss is None else dss, "datasource", caption=self.caption, name=self.ds)

    def _deps(self, parent, fields, bare=False):
        """bare: a filter on a calc is declared without the CSV columns of its formula (shared view, dashboard:
        Desktop 2025.1 drops them on save, a public book's shared view; decisions/057; the period switch's calc of 042 too,
        decisions/061)."""
        deps = _sub(parent, "datasource-dependencies", datasource=self.ds)
        cols = {}
        for f in fields:
            for col in self.with_deps(f.col):
                of_calc = isinstance(f.col, fields_mod.GroupColumn) and f.col.of_calc  # a group over a calc (151)
                if (bare and (f in self.filters or f in self.period) and (isinstance(f.col, CalcColumn) or of_calc)
                        and not isinstance(col, (CalcColumn, fields_mod.GroupColumn))):
                    continue
                cols[col.name] = col
        insts = {}
        for f in fields:  # a group has no instance (decisions/033)
            if f.name not in insts and not isinstance(f.col, fields_mod.GroupColumn):
                insts[f.name] = f
        # columns and column-instances in one order by the bracketed name, as Desktop (decisions/061): [cnt:id:qk] <
        # [id] < [none:status:nk] < [status] (158); [Sales] < [none:Sales:nk] put every column first before
        for key, col, f in sorted([(f"[{n}]", c, None) for n, c in cols.items()] +
                                  [(n, None, f) for n, f in insts.items()], key=lambda x: x[0]):
            if col is not None:
                self.column(deps, col)
                continue
            ci = _sub(deps, "column-instance", column=f"[{f.col.name}]", derivation=f.derivation, name=f.name,
                      pivot="key", type=f.type)
            if f.tc:
                self._table_calc(ci, f)
            tablecalc.write(ci, f)  # a table calc calc's compute_using (decisions/034)
            reflines.table_calc(self, ci, f)  # a generated color flag's compute-using

    @staticmethod
    def _table_calc(parent, f):
        """Quick table calc computed along explicit dimensions (Tableau 'Specific Dimensions')."""
        # Shapes copied from Desktop-saved workbooks: one dimension -> ordering-field attribute,
        # several -> <order> children; Difference/PctDiff need <address><value>-1</value></address>
        # ("relative to previous") - without it Desktop 2025.1 crashes when the sheet is opened.
        kind = TABLE_CALC[f.tc["type"]][1]
        attrs = {}
        if kind == "CumTotal":
            attrs["aggregation"] = "Sum"
        if kind in ("Difference", "PctDiff"):
            attrs["diff-options"] = "Relative"
        if len(f.tc_order) == 1:
            attrs["ordering-field"] = f.tc_order[0]
        attrs.update({"ordering-type": "Field", "type": kind})
        tc = ET.SubElement(parent, "table-calc", attrs)
        if len(f.tc_order) > 1:
            for ref in f.tc_order:
                _sub(tc, "order", field=ref)
        if kind in ("Difference", "PctDiff"):
            ET.SubElement(_sub(tc, "address"), "value").text = "-1"

    def _member_filter(self, parent, field, members):
        flt = _sub(parent, "filter", **{"class": "categorical"}, column=self.q(field))
        g = _sub(flt, "groupfilter", function="union", **{f"{{{USER_NS}}}op": "manual"})
        for m in members:
            _sub(g, "groupfilter", function="member", level=field, member=f'"{m}"')

    # ---- shared filters (golden 166-184) -------------------------------------------------
    def _shared(self):
        """The filters of every sheet of the data source (shared-view); the others are a dashboard's (decisions/071)."""
        return [f for f, sc in zip(self.filters, self.filter_scope) if sc is None]

    def _dashboard_filters(self, p):
        """[(spec filter, Field, filter-group N)] of the dashboards' filters worksheet p carries (decisions/071): those
        whose scope holds p or the sheet it is a part of (a KPI tile 'KPI · Sales', an insight 'Trend · Insight')."""
        # N from 3: Desktop 2025.1 rewrites groups 1 and 2 on save (1 loses its group, 2 its datasource prefix);
        # its own books start at 3 (a case's Web Engagement: 3, 4, 5, 7), decisions/071
        return [(spec_f, f, i + FILTER_GROUP_FIRST) for i, (spec_f, f, sc) in
                enumerate(zip(self.spec.get("filters", []), self.filters, self.filter_scope))
                if sc and filters_mod.applies(self.spec, spec_f, p["name"])]

    def _filter_on(self, spec_f):
        """Is the card of this filter on the current dashboard: a filter of every sheet is on each (040), a
        dashboard's filter on the dashboards of its scope (071); either only where its source's sheets are (083)."""
        return any(filters_mod.applies(self.spec, spec_f, n) for n in _leaves(self.spec["dashboard"]["grid"])
                   if self.owns(n))

    def shared_views(self, parent):
        shared = self._shared()
        if not (shared or self.period):
            return
        svs = parent.find("shared-views")  # one list, a shared view per source (decisions/083)
        sv = _sub(_sub(parent, "shared-views") if svs is None else svs, "shared-view", name=self.ds)
        self._ds_ref(sv)
        self._deps(sv, shared + self.period, bare=True)
        for f in sorted(shared + self.period, key=lambda f: f.name):  # Desktop orders shared filters by field
            if f in self.period:  # a period switch (decisions/042): no card, the parameter's buttons set it
                interact.write_period_filter(sv, self, f)
                continue
            spec_f = self.filter_spec[self.q(f.name)]
            if isinstance(f, (dates.DateFilter, filters_mod.MeasureRange)):  # date range / relative, measure range
                filters_mod.write_context(f.write(sv, self.q(f.name)), spec_f)
            else:  # (All), the default selection, exclude, context (decisions/021, 035)
                filters_mod.write(sv, spec_f, self.q(f.name), f.name)

    # ---- worksheets (golden 185-349) -----------------------------------------------------
    def _measure(self, m, text=False):
        """text: the sheet can show a text aggregate (a KPI tile); elsewhere it is an error."""
        col = self.col(m["field"])
        if isinstance(col, CalcColumn) and col.calc.is_agg:
            if "agg" in m:
                raise ValueError(f"'{m['field']}' is an aggregate calculation: remove 'agg'")
            discrete = col.datatype not in ("integer", "real")
            if discrete and not text:
                raise ValueError(f"'{m['field']}' is a {col.datatype} aggregate, not a number: only a KPI tile "
                                 f"(kpi style 'tiles') can show it")
            # a text aggregate ("Busiest day: " + ...) is discrete: Desktop writes [usr:...:nk], a :qk tile stays empty
            return Field(col, "agg", "user", tc=m.get("table_calc"), discrete=discrete)
        return Field(col, "agg", m.get("agg", "sum"), tc=m.get("table_calc"))

    def _dim(self, name):
        f = Field(self.col(name), "dim")
        if isinstance(f.col, fields_mod.GroupColumn):  # Desktop puts a group on a shelf as its column: [ds].[Group]
            f.name = fields_mod.instance(f.col.name, f.col)
        return f

    def _bar_dim(self, s):
        """A bar's dimension: its members, or the periods of a date with date_level (decisions/090)."""
        level = dates.bar_level(s)
        if level is None:
            return self._dim(s["dimension"])
        col = self.col(s["dimension"])
        dates.check_bar(s, col)
        return Field(col, "date", level, discrete=True)

    def sheet_shape(self, s):
        """-> fields, rows, cols, encodings[(tag, field_ref)], labels, measure_names"""
        t = s["type"]
        if t == "kpi":
            ms = [self._measure(m) for m in s["measures"]]
            return ms, None, "[:Measure Names]", [("text", self.q("[Multiple Values]"))], True, ms
        if t == "tile":
            fs = [self._measure(s["measure"], text=True)] + insight.note_fields(self, s)  # + its note (045)
            return fs, None, None, [("text", self.q(f.name)) for f in fs], True, None
        if t == insight.KIND:  # an insight line under a block header (decisions/045)
            return insight.shape(self, s)
        if t == "card_value":
            c, n = s["card"], cards.names(s["card"], s["measure"])
            per = cards.period_text(c) if cards.date_range(c) else cards.period(c)  # 'wk 12 (Oct 19-24)' (178)
            pc = self.col(per)  # the range text is a string: MIN on :nk, a :qk one stays empty in Desktop (178)
            fs = [Field(pc, "agg", "min", discrete=pc.datatype == "string"), Field(self.col(n["current"]), "agg", "user")]
            if not kpi2.pill(c):  # the change: on the pill instead (decisions/037)
                n2 = kpi2.names(c, s["measure"])
                fs += [Field(self.col(n2[k]), "agg", "user") for k in ("diff_good", "diff_bad") if kpi2.abs_delta(c)]
                fs += [Field(self.col(n[k]), "agg", "user") for k in ("good", "bad")]
                fs += [Field(self.col(n["flat"]), "agg", "user")] if cards.neutral_zero(c) else []  # 169
                fs += [Field(self.col(n["previous"]), "agg", "user")] if kpi2.base_value(c) else []  # 088
            if kpi2.target(s["measure"]):  # '103% of $15.0K target', the last two (decisions/155)
                pn = kpi2.progress_names(c, s["measure"])
                fs += [Field(self.col(pn[k]), "agg", "user") for k in ("progress", "target")]
            return fs, None, None, [("text", self.q(f.name)) for f in fs], True, None
        if t == "welcome":  # top bar (decisions/029)
            return shell.shape(self)
        if t in kpi2.PARTS:  # pill, marker, period line, data as of (decisions/037)
            return kpi2.shape(self, s)
        if t == interact.BUTTON:  # a value of a buttons sheet (decisions/042)
            return interact.shape(self, s)
        if dualaxis.is_dual(s) or t in dualaxis.LEGEND_PARTS:  # combo, donut, lollipop (decisions/044)
            return dualaxis.shape(self, s)
        if maps_mod.is_map(s):  # symbol, filled (decisions/046)
            return maps_mod.shape(self, s)
        if scatter.is_scatter(s):  # decisions/047
            return scatter.shape(self, s)
        if distviz.kind(s):  # histogram, strip, beeswarm, calendar, bump (decisions/140)
            return distviz.shape(self, s)
        if compareviz.kind(s):  # slope, box plot, waffle (decisions/141)
            return compareviz.shape(self, s)
        if treemap.is_treemap(s):  # treemap, packed bubbles (decisions/138, 141)
            return treemap.shape(self, s)
        if tilegrid.is_tilegrid(s):  # tile map, wall (decisions/154)
            return tilegrid.shape(self, s)
        if waterfall.is_waterfall(s):  # decisions/139
            return waterfall.shape(self, s)
        if gantt.is_gantt(s):  # a timeline of tasks (polish-26)
            return gantt.shape(self, s)
        if funnel.is_funnel(s):  # decisions/159
            return funnel.shape(self, s)
        if t == "card_history":
            c = s["card"]
            d = kpi2.history_date(self, c)  # the discrete month under month letters (decisions/088)
            if kpi2.line(c):  # a sparkline (decisions/037)
                fields, enc = kpi2.history_shape(self, s, d, self._measure(cards.history_measure(c, s["measure"])))
                return fields, fields[1].name, d.name, enc, True, None
            m, cur = self._measure(cards.history_measure(c, s["measure"])), self._dim(cards.is_current(c))
            latest = Field(self.col(c["date"]["field"]), "agg", "max")  # label-data of the most-recent label
            fields, enc = [d, m, cur, latest], [("color", self.q(cur.name))]
            reflines.history(self, s, fields, enc)  # history_color change
            return fields, m.name, d.name, enc, True, None
        if sparkline.is_part(s):  # a registry's line spark (decisions/153)
            return sparkline.shape(self, s), None, None, [], False, None
        if t == "registry":  # shelves and panes are written by _registry_table
            registry.check_top_rows(self, s)  # Top N and a text dimension beside it (decisions/144)
            dims = [self._dim(r) for r in s["rows"]]
            cols = [registry.column(self, s, c) for c in sparkline.drawn(s)]  # a line spark: its own sheet (153)
            self.registry_cols[s["name"]] = (dims, cols)
            fields = dims + [f for c in cols for f in c["fields"]]
            if s.get("sort", "none") != "none" or "top" in s:  # by the first column's measure, also under a rank
                fields.append(cols[0]["measure"])
            names = next((c["names"] for c in cols if c["names"]), None)  # a track: Measure Values (decisions/039)
            return fields, None, None, [], True, names
        if t == "bar":
            d, m = self._bar_dim(s), self._measure(s["measure"])
            fields, enc = [d, m], []
            if isinstance(s.get("color"), str):
                c = self._dim(s["color"])
                fields.append(c)
                enc.append(("color", self.q(c.name)))
            names = colors.encode(self, s, fields, enc)  # meaning colors; a plan puts Measure Values on the axis
            reflines.encode(self, s, fields, enc)  # color vs avg, measures of the reference lines
            if barlabels.value_left(s):  # the value as a row header beside the member (decisions/095)
                fields.append(barlabels.value_field(self, s))
            compareviz.facet_field(self, s, fields)  # small multiples (decisions/141)
            barinbar.encode(self, s, fields)  # the parts' position (decisions/156)
            heatmap.margin_inner(self, s, fields)  # row totals beside two row fields (decisions/186)
            x = "[Multiple Values]" if names else m.name
            if s.get("orientation", "horizontal") == "horizontal":  # its values at the bar ends (decisions/087)
                return fields, d.name, x, enc, barlabels.mode(s) == "end", names
            return fields, x, d.name, enc, False, names
        if t in ("line", "area"):
            d = Field(self.col(s["date"]["field"]), "date", s["date"].get("level", "month"))
            m = self._measure(s["measure"])
            fields, enc = [d, m], []
            if isinstance(s.get("color"), str):
                c = self._dim(s["color"])
                fields.append(c)
                enc.append(("color", self.q(c.name)))
            colors.encode(self, s, fields, enc)
            names = benchmark.encode(self, s, fields, enc)  # selected vs benchmark, line-end labels (decisions/043)
            reflines.encode(self, s, fields, enc)
            compareviz.facet_field(self, s, fields)  # small multiples (decisions/141)
            grid = facetgrid.encode(self, s, fields, enc)  # in rows, named at the line's end (decisions/144)
            top = annotate.encode(self, s, fields, enc) or grid  # the N largest values named (polish-26)
            if steparea.labelled(s):  # a step area's label on its latest bar: MAX(date) as label-data (decisions/158)
                fields.append(Field(self.col(s["date"]["field"]), "agg", "max"))
            return fields, "[Multiple Values]" if names else m.name, d.name, enc, top, names
        if t == "table":  # a second row field after the measure (decisions/045)
            r, c, m = self._dim(tables.rows(s)[0]), self._dim(s["cols"]), self._measure(s["measure"])
            return [r, c, m] + tables.extra(self, s), r.name, c.name, [("text", self.q(m.name))], True, None
        if t == "heatmap":
            level = dates.heat_level(s)  # a column per period of a date (decisions/125)
            if level:
                dates.check_heat(s, self.col(s["cols"]))
            r, m = self._dim(tables.rows(s)[0]), self._measure(s["measure"])
            c = Field(self.col(s["cols"]), "date", level, discrete=True) if level else self._dim(s["cols"])
            fields = [r, c, m] + tables.extra(self, s)  # a second row field (decisions/171)
            text = heatmap.text_field(self, s, fields, m)  # labels of the cells >= min only (decisions/171)
            return fields, r.name, c.name, [("color", self.q(m.name)), ("text", self.q(text.name))], True, None
        raise ValueError(f"Unsupported sheet type '{t}'. Allowed: kpi, bar, line, area, table, heatmap, combo, donut, "
                         f"lollipop, dumbbell, pareto, map, scatter, treemap, bubbles, waterfall, gantt, funnel, {', '.join(distviz.TYPES + compareviz.TYPES)}, tilegrid")

    def _resolve_table_calcs(self, s, fields):
        """Map table_calc 'along' names to this sheet's dimension instances."""
        dims = {getattr(f.col, "caption", f.col.name): f for f in fields if f.kind in ("dim", "date")}
        tablecalc.resolve(self, s, fields, dims)  # calcs with table calc functions (decisions/034)
        for f in fields:
            if not f.tc:
                continue
            if not dims:
                raise ValueError(f"Sheet '{s['name']}': a table calculation needs dimensions on the sheet")
            if s["type"] == "bar" and s.get("sort", "none") != "none":
                raise ValueError(f"Sheet '{s['name']}': sorting by a table calculation is not supported yet")
            along = f.tc.get("along") or list(dims)
            for a in along:
                if a not in dims:
                    raise ValueError(f"Sheet '{s['name']}': table_calc along '{a}' is not a dimension of this sheet "
                                     f"(dimensions: {sorted(dims)})")
            f.tc_order = [self.q(dims[a].name) for a in along]

    def worksheet(self, parent, s):
        fields, rows, cols, enc, labels, measure_names = self.sheet_shape(s)
        tip = None
        if tooltips.of(s) is not None:  # the sheet's own tooltip phrase (decisions/036)
            tip, shelf = tooltips.resolve(self, s, fields, ink.helpers(s, fields))
            fields, enc = fields + shelf, enc + [("tooltip", self.q(f.name)) for f in shelf]
        self._resolve_table_calcs(s, fields)
        self.shapes[s["name"]] = (fields, enc)
        ws = _sub(parent, "worksheet", name=s["name"])
        if s.get("title") and not self.block_headers:  # with block headers the title is a dashboard text zone
            _sub(_sub(_sub(_sub(ws, "layout-options"), "title"), "formatted-text"), "run").text = s["title"]
        compareviz.title(self, ws, s)  # a waffle's % (polish-26b)
        table = _sub(ws, "table")
        view = _sub(table, "view")
        self._ds_ref(view)
        maps_mod.view(view, s)  # the map source (decisions/046)
        own = filters_mod.sheet_fields(self, s)  # the sheet's own filters (decisions/057)
        grouped = self._dashboard_filters(s)  # its dashboard's filters (decisions/071)
        carried = self._shared() + [g[1] for g in grouped]
        applied = [f for f in self.filters if any(f is c for c in carried)]  # in spec order
        self._deps(view, fields + applied + self.period + own)
        params.sheet_refs(self, view, s, fields + self.period + applied + own)  # a filter calc's parameters
        slices = []
        if measure_names:
            self._member_filter(view, "[:Measure Names]", [self.q(m.name) for m in measure_names])
            slices.append(self.q("[:Measure Names]"))
            colors.measure_order(self, view, s, measure_names)
            registry.measure_order(self, view, s, measure_names)  # a track: the share first, then the rest
            benchmark.measure_order(self, view, s, measure_names)  # the selected line on top (decisions/043)
            kpitable.measure_order(self, view, s, measure_names)  # a KPI table's columns in the spec order (106)
        top = params.top_filter(self, view, s, fields)  # Top N of a bar (decisions/020)
        if sparkline.is_part(s):  # its periods (decisions/153)
            slices.append(sparkline.periods_filter(self, view, fields))
        own = filters_mod.write_sheet(self, view, s, own)
        filters_mod.write_groups(self, view, grouped)
        if s["type"] in ("bar", "registry", "combo", "lollipop", "dumbbell", sparkline.KIND) and s.get("sort", "none") != "none" \
                or pareto.is_pareto(s):  # a Pareto: always by its measure, descending (decisions/157)
            if sparkline.is_part(s):  # as its registry: the rows by its first column (decisions/153)
                d, m = sparkline.sort(self, s, fields)
            elif s["type"] != "registry":  # by the (bar) measure
                d, m = fields[0], fields[2 if s["type"] == "dumbbell" else 1]  # a dumbbell by its "to"
            else:  # registry: the inner rows by the first column, within the outer group
                dims, cols = self.registry_cols[s["name"]]
                d, m = dims[-1], cols[0]["measure"]
            if s["type"] == "registry" and "top" in s:  # Top N with a text beside it: the kept members (143)
                d = dims[0]
            if s["type"] == "registry" and len(dims) == 2 and "top" not in s:  # nested sort: within each outer group
                _sub(_sub(view, "shelf-sorts"), "shelf-sort-v2", dimension_to_sort=self.q(d.name),
                     direction=s["sort"].upper(), is_on_innermost_dimension="true",
                     measure_to_sort_by=self.q(m.name), shelf="rows")
            else:
                _sub(view, "computed-sort", column=self.q(d.name), direction=s.get("sort", "desc").upper(),
                     using=self.q(m.name))
        insight.stack_order(self, view, s)  # a horizontal stack: the field's order from the left (decisions/173)
        tilegrid.sort(self, view, s, fields)  # a wall: by the measure, the order INDEX() walks (decisions/154)
        if funnel.sort(s) == "desc":  # the stages by their value (decisions/159)
            _sub(view, "computed-sort", column=self.q(fields[0].name), direction="DESC", using=self.q(fields[2].name))
        tables.write_sort(self, view, s, fields)  # a table's rows by their total (decisions/045)
        filters_mod.order_view(view, s, bool(grouped))  # own filters: by column, as Desktop saves (decisions/057)
        slices += [self.q(f.name) for f in applied + self.period] + own + ([top] if top else [])  # Top N last
        if slices:
            sl = _sub(view, "slices")
            for x in slices:
                _sub(sl, "column").text = x
        _sub(view, "aggregation", value="true")
        if registry.is_registry(s):
            self._registry_table(table, s)
            _simple_id(ws)
            return
        if sparkline.is_part(s):  # the reference's form (decisions/153)
            sparkline.table(self, table, s, fields)
            _simple_id(ws)
            return
        style = _sub(table, "style")
        if self.spec.get("declutter", True):
            for element, formats in DECLUTTER:
                rule = _sub(style, "style-rule", element=element)
                for attrs in formats:
                    _sub(rule, "format", **attrs)
        if s["type"] == "card_history":  # a history strip: no axes, only the latest bar is labelled
            axis = style.find("style-rule[@element='axis']")
            if axis is None:
                axis = ET.Element("style-rule", element="axis")
                style.insert(0, axis)
            hidden = [(fields[0], "cols"), (fields[1], "rows")][kpi2.month_letters(s["card"]):]  # letters: a header
            for i, (f, scope) in enumerate(hidden):
                axis.insert(i, ET.Element("format", {"attr": "display", "class": "0", "field": self.q(f.name),
                                                     "scope": scope, "value": "false"}))
        colors.sheet_style(self, style, s, fields)  # data-ink of meaning-color sheets, plan sizes
        reflines.line_axis(self, style, s, fields)  # a line's value axis: zero, a fixed range (decisions/170)
        self._bar_date_label(style, s, fields)  # 'Jan' under a bar of months (decisions/090)
        barlabels.style(self, style, s, fields)  # row headers 10pt; end labels: no axis (decisions/087)
        if s["type"] in ("line", "area"):  # its date axis title, checked in its zone (decisions/066)
            self.axis_fields[s["name"]] = fields
        heatmap.style(self, style, s, fields)  # a continuous color scale (decisions/041)
        heatmap.sheet_style(self, style, s, fields)  # a heatmap with margins and its margin sheets
        treemap.style(self, style, s, fields)  # the sequential scale by the size (decisions/138)
        distviz.style(self, style, s, fields)  # hidden jitter axis, reversed rank axis, calendar scale (140)
        compareviz.style(self, style, s, fields)  # facet / waffle headers, the box's look (decisions/141)
        facetgrid.style(self, style, s, fields)  # grid headers hidden, a facet's date ticks (decisions/144)
        tilegrid.style(self, style, s, fields)  # headers hidden, the measure's scale (decisions/154)
        waterfall.style(self, style, s, fields)  # the total's header and borderless pane (decisions/144)
        funnel.style(self, style, s, fields)  # the start's axis hidden (decisions/159)
        self._log_axes(style, s)  # scale: log (polish-26)
        if s["type"] == "table":
            theme.row_height(self, style, fields[0])  # rows 30px in the card theme
            totals.style(self, style, s, fields[0], fields[1])  # bold, label, shaded total cells (decisions/036)
            tables.style(self, style, s, fields)  # widths of two row headers (decisions/045)
        reflines.style(self, style, s, fields)  # the look of the reference lines
        shell.sheet_style(self, style, s)  # brand colors (decisions/029)
        dualaxis.sheet_style(self, style, s, fields)  # no field label over the dimension (decisions/044, 069)
        kpi2.history_style(self, style, s, fields)  # month letters under a sparkline (decisions/088)
        kpi2.points_style(style, s)  # a sparkline's points layer: no null indicator (decisions/059)
        tablecalc.style(style, s, fields)  # a LOOKUP / difference calc: no '1 null' indicator (decisions/167)
        kpi2.axis_style(self, style, s, fields)  # the pill / marker bar's fixed, hidden axis (decisions/063)
        theme.sheet_text(self, style, s)  # the theme's chart text 8pt muted (decisions/089)
        if s["type"] == kpi2.PROGRESS:  # the track and the fill on one fixed axis (decisions/155)
            kpi2.progress_table(self, table, style, s, fields)
            _simple_id(ws)
            return
        if dualaxis.is_dual(s) or kpi2.has_points(s):  # the fold, a pane per layer, '(A + B)' on the shelf
            dualaxis.table(self, table, style, s, fields)
            _simple_id(ws)
            return
        if barinbar.on(s):  # the total and its parts, a layer each (decisions/156)
            barinbar.table(self, table, style, s, fields)
            _simple_id(ws)
            return
        if maps_mod.is_map(s):  # the map's pane, background and generated latitude / longitude (decisions/046)
            maps_mod.table(self, table, style, s, fields)
            _simple_id(ws)
            return
        if scatter.is_scatter(s):  # points, axis lines, trend line (decisions/047)
            scatter.table(self, table, style, s, fields)
            _simple_id(ws)
            return
        pane = _sub(_sub(table, "panes"), "pane", selection_relaxation_option="selection-relaxation-allow")
        _sub(_sub(pane, "view"), "breakdown", value=colors.breakdown(s))
        bars = s["type"] == "card_history" and not kpi2.line(s["card"])  # a sparkline is a line (decisions/037)
        line = s["type"] == "card_history" and not bars
        # a bar along a date: Bar, for Automatic draws a line along any date, discrete too (decisions/090);
        # an area sparkline: decisions/088
        mark = "Bar" if dates.bar_level(s) else ("Area" if kpi2.area(s["card"]) else "Automatic") if line \
            else MARK_CLASS.get(s["type"], "Automatic")
        _sub(pane, "mark", **{"class": mark})
        kpi2.status_mark(pane, s)  # a status dot: no scaling (decisions/062)
        compareviz.mark(pane, s)  # waffle squares, box dots: no scaling (decisions/141)
        distviz.mark(pane, s)  # histogram bars: no scaling, no gaps (decisions/144)
        dualaxis.dots_mark(pane, s)  # a donut legend's dots: no scaling (decisions/069)
        steparea.mark(pane, s)  # a step area: Bars as wide as the period (decisions/158)
        if bars:  # as Desktop writes a bar on a continuous date axis
            _sub(pane, "mark-sizing", custom_mark_size_in_axis_units="1.0", mark_alignment="mark-alignment-left",
                 mark_sizing_setting="marks-scaling-on", use_custom_mark_size="false")
        if enc:
            e = _sub(pane, "encodings")
            for tag, ref in enc:
                _sub(e, tag, column=ref)
        if bars:  # 'most recent' is the max of the date
            _sub(pane, "label-data", column=self.q(fields[-1].name))
        steparea.label_data(self, pane, s, fields)  # (decisions/158)
        reflines.pane(self, pane, s, fields)  # <reference-line> (decisions/028)
        funnel.pane(self, pane, s, fields)  # room for the widest bar's labels (decisions/159)
        compareviz.pane(self, pane, s, fields)  # the box plot (decisions/141)
        if tip:
            tooltips.write(self, pane, s, tip)
        elif self.block_headers:
            ink.tooltip(self, pane, s, fields)  # without the helper fields (data-ink)
        heatmap.pane_style(pane, s)  # a margin's bars muted and labelled (decisions/041)
        tilegrid.pane(self, pane, s, fields)  # 'member: value' tooltip, code over value (decisions/154)
        if s["type"] == "tile":
            ft = _sub(_sub(pane, "customized-label"), "formatted-text")
            _sub(ft, "run", fontcolor=COLOR["muted"], fontsize=str(self.font["tile_caption"])).text = s["label"]
            _sub(ft, "run").text = "Æ\n"  # Tableau's line-break run
            fg = {"fontcolor": theme.title_color(self)} if self.theme else {}
            _sub(ft, "run", bold="true", **fg, fontsize=str(theme.kpi_value_pt(self, s["kpi"]))).text = \
                f"<{self.q(fields[0].name)}>"
            insight.note_label(self, ft, s, fields[1:])  # '44% of total' under the number (decisions/045)
        if s["type"] == insight.KIND:
            insight.label(self, pane, s, fields)
        if s["type"] == "card_value":
            self._card_label(pane, s, fields)
        if s["type"] == "welcome":
            shell.label(self, pane, s, fields)
        if s["type"] in kpi2.PARTS and labels:
            kpi2.label(self, pane, s, fields)
        if s["type"] == interact.BUTTON:
            interact.label(self, pane, s, fields)
        if s["type"] == dualaxis.LEGEND:
            dualaxis.legend_pane(self, pane, s, fields)  # 'value (share)' (decisions/044)
        if labels:
            pane_style = _sub(pane, "style")
            kpi2.pane_style(pane_style, s)  # 'Data as of' aligned right
            if s["type"] == "tile":  # every tile's caption and number from its left edge, in the middle of its zone:
                rule = _sub(pane_style, "style-rule", element="cell")  # Desktop aligns a number right, a text left,
                for attr, value in TILE_ALIGN:  # each tile its own way otherwise (ITSM, decisions/068)
                    _sub(rule, "format", attr=attr, value=value)
            rule = _sub(pane_style, "style-rule", element="mark")
            _sub(rule, "format", attr="mark-labels-show", value="true")
            if s["type"] == dualaxis.LEGEND:
                dualaxis.legend_style(pane_style)
            if s["type"] == "card_history":  # only the latest bar, always shown (culling hid it next to a taller bar);
                if bars:  # a sparkline: its label calc is null except at the max and the last period
                    _sub(rule, "format", attr="mark-labels-mode", value="most-recent")
                for attr, value in kpi2.area_formats(s["card"], COLOR["accent"]) if line else []:  # decisions/088
                    _sub(rule, "format", attr=attr, value=value)
            else:
                _sub(rule, "format", attr="mark-labels-cull", value="true")
            treemap.mark_style(rule, s)  # white lines between the rectangles (decisions/138)
            tilegrid.mark_style(rule, s)  # every label, white lines between the tiles (decisions/154)
        benchmark.pane_style(pane, s)  # labels at the line ends (decisions/043)
        reflines.mark_style(pane, s)  # a bullet's thin bar (decisions/152)
        distviz.pane_style(pane, s)  # bump dots and end labels, calendar day lines (decisions/140)
        compareviz.pane_style(self, pane, s)  # slope ends, box dots, waffle lines (decisions/141)
        facetgrid.pane_style(pane, s)  # the member at its line's end (decisions/144)
        colors.plain_mark(pane, s, enc)  # one color without a color field: the book's accent (decisions/141)
        steparea.pane_style(pane, s)  # a step line / area (decisions/144, 158)
        kpi2.status_style(pane, s)  # a status dot's size (decisions/062)
        dualaxis.dots_style(pane, s)  # a donut legend's dot size (decisions/069)
        rows_el = _sub(table, "rows")
        if rows:
            rows_el.text = self.q(rows)
        tables.rows_shelf(self, s, fields, rows_el)  # (outer / inner) (decisions/045)
        heatmap.margin_shelf(self, s, fields, rows_el)  # and on a heatmap's row totals (decisions/186)
        if barlabels.value_left(s):  # (member / value), reference 'Labels on the Left' (decisions/095)
            rows_el.text = f"({self.q(rows)} / {self.q(barlabels.value_field(self, s).name)})"
        cols_el = _sub(table, "cols")
        if cols:
            cols_el.text = self.q(cols)
        totals.shelves(self, s, rows_el, cols_el)  # grand totals (decisions/036)
        distviz.shelves(self, s, fields, rows_el, cols_el)  # (dimension / jitter), (month / week) (140)
        compareviz.shelves(self, s, fields, rows_el, cols_el)  # (facet / date): small multiples (decisions/141)
        facetgrid.shelves(self, s, fields, rows_el, cols_el)  # (row * measure), (column * date) (decisions/144)
        tilegrid.shelves(self, s, fields, rows_el, cols_el)  # (group / COL): a wall's blocks (decisions/154)
        waterfall.shelves(s, cols_el)  # the total bar: <cols total='true'> (decisions/144)
        steparea.shelves(s, cols_el)  # every period, a step over the empty ones (decisions/158)
        compareviz.layers(self, table, s, fields)  # a slope's labels spread: a second layer (polish-26b)
        _simple_id(ws)

    def _log_axes(self, style, s):
        """A measure with scale 'log' on a log axis: its space encoding in the axis rule, as Desktop writes it
        (DataQualityTesting, KeywordResearch)."""
        if s["type"] == "scatter":
            axes = [(s["x"], "cols"), (s["y"], "rows")]
        elif s["type"] in ("strip", "beeswarm") or (s["type"] == "bar"
                                                     and s.get("orientation", "horizontal") == "horizontal"):
            axes = [(s.get("measure", {}), "cols")]
        elif s["type"] == "bar":
            axes = [(s.get("measure", {}), "rows")]
        else:
            axes = []
        for m, scope in axes:
            if m.get("scale") != "log":
                continue
            rule = distviz._axis_rule(style)
            ET.SubElement(rule, "encoding", {"attr": "space", "class": "0", "field": self.q(self._measure(m).name),
                                             "field-type": "quantitative", "scale": "log", "scope": scope,
                                             "type": "space"})

    def _bar_date_label(self, style, s, fields):
        """The periods of a bar along a date in a short form: label text-format '*mmm' (decisions/090)."""
        level = dates.bar_level(s) or dates.heat_level(s)
        name = s.get("dimension") or s.get("cols")
        fmt = level and dates.bar_label_format(level, [r[name] for r in self.prof.rows])
        if fmt:
            rule = colors._rule(style, "label", before=("mark", "pane", "worksheet", "gridline", "zeroline",
                                                        "table-div"))
            _sub(rule, "format", attr="text-format", field=self.q(fields[1 if s["type"] == "heatmap" else 0].name),
                 value=fmt)

    def _registry_table(self, table, s):
        """A registry: rows = 1-2 dimensions, a pane per column on Columns (references Reports Usage,
        TUG Tables). Widths are filled in by _registry_cell, once the dashboard knows the zone size."""
        dims, cols = self.registry_cols[s["name"]]
        style = _sub(table, "style")
        if self.spec.get("declutter", True):
            for element, formats in DECLUTTER:
                rule = _sub(style, "style-rule", element=element)
                for attrs in formats:
                    _sub(rule, "format", **attrs)
        axis = style.find("style-rule[@element='axis']")
        if axis is None:
            axis = ET.Element("style-rule", element="axis")
            style.insert(0, axis)
        fixed = [c for c in cols if c["axis"]]  # track 0..1, dot 0..DOT_RANGE: the encodings first (ER Referrals)
        for i, c in enumerate(fixed):
            lo, hi = c["axis"]
            axis.insert(i, ET.Element("encoding", {"attr": "space", "class": "0", "field": registry.x_ref(self, c),
                                                   "field-type": "quantitative", "max": str(hi), "min": str(lo),
                                                   "range-type": "fixed", "scope": "cols", "type": "space"}))
        for i, c in enumerate(cols, len(fixed)):  # no axes: the values are labels on the cells
            axis.insert(i, ET.Element("format", {"attr": "display", "class": "0", "field": registry.x_ref(self, c),
                                                 "scope": "cols", "value": "false"}))
        registry.fold_axis(self, axis, cols)  # a bar_inside's second layer (decisions/077)
        header = style.find("style-rule[@element='header']")
        if header is None:
            header = _sub(style, "style-rule", element="header")
        label = ET.Element("style-rule", element="label")  # Desktop order: header, label, pane, worksheet
        style.insert(list(style).index(header) + 1, label)
        for d in dims:  # row headers read left-aligned, as their titles
            _sub(label, "format", attr="text-align", field=self.q(d.name), value="left")
        if len(dims) == 2:  # a thin rule between the outer groups (as in the reference)
            div = style.find("style-rule[@element='table-div']")
            if div is None:
                div = _sub(style, "style-rule", element="table-div")
            for f in div.findall("format[@scope='rows']"):
                div.remove(f)
            for attr, value in [("line-visibility", "on"), ("stroke-size", "1"), ("stroke-color", COLOR["rule"]),
                                ("line-pattern-only", "solid"), ("div-level", "1")]:
                _sub(div, "format", attr=attr, scope="rows", value=value)
        theme.row_height(self, style, dims[-1])  # rows 30px in the card theme
        totals.style(self, style, s, dims[0])  # decisions/036
        sheet_rule = ET.Element("style-rule", element="worksheet")
        before = style.find("style-rule[@element='pane']")
        style.insert(list(style).index(before if before is not None else label) + 1, sheet_rule)
        _sub(sheet_rule, "format", attr="display-field-labels", scope="rows",
             value="false")  # the titles are text zones above the sheet
        registry.sheet_style(self, style, s, dims, cols)  # two-line rows, dot scale, tick look (decisions/039)
        panes = _sub(table, "panes")
        single = registry.single_pane(cols)  # one axis: its pane is the sheet's only one (decisions/099)
        if not single:
            default = _sub(panes, "pane", selection_relaxation_option="selection-relaxation-allow")
            _sub(_sub(default, "view"), "breakdown", value="auto")
            _sub(default, "mark", **{"class": "Automatic"})
            registry.reference_lines(self, default, cols)  # the ticks (decisions/065)
            ink.empty_tooltip(default)  # every number is on the cells (as in the reference)
        widths, pane_id = [], 0
        for i, c in enumerate(cols, 1):
            pane_id += 1
            pane = _sub(panes, "pane", id=str(pane_id), selection_relaxation_option="selection-relaxation-allow",
                        **({} if single else {"x_axis_name": registry.x_ref(self, c)}))
            _sub(_sub(pane, "view"), "breakdown", value="auto")
            _sub(pane, "mark", **{"class": c["mark"]})
            registry.pane(self, pane, c, i)  # encodings
            if single:  # XSD: after the encodings
                registry.reference_lines(self, pane, cols)
            ink.empty_tooltip(pane)
            registry.write_label(self, pane, c)
            pst = _sub(pane, "style")
            if registry.cell_align(c["spec"]):  # a dot's label at Desktop's own place, right of it (decisions/164)
                cell = _sub(pst, "style-rule", element="cell")
                _sub(cell, "format", attr="text-align", value=registry.cell_align(c["spec"]))  # a pill centred (096)
                if c["style"] == "pill":
                    _sub(cell, "format", attr="vertical-align", value="center")
            if c["style"] != "track" and c["mark"] != "Shape":  # the track's share is in its own column; a status mark has none (139)
                mark = _sub(pst, "style-rule", element="mark")
                _sub(mark, "format", attr="mark-labels-show", value="true")
                if c["color"]:
                    _sub(mark, "format", attr="mark-color", value=c["color"])
                    if c["color"] == COLOR["cell_text"] and c["flag"] is None and totals.of(s) is not None:
                        _sub(mark, "format", attr="mark-transparency", value="0")  # the total's shading shows (072)
            if not single:  # one pane fills the sheet right of the row headers: Desktop drops its width (099)
                widths.append(_sub(pst, "style-rule", element="pane"))
            pane_id = registry.outside_pane(self, panes, c, pane_id)  # a bar_inside's second layer (decisions/077)
        self.registry_els[s["name"]] = (header, widths)
        rows_el = _sub(table, "rows")
        rows_el.text = (self.q(dims[0].name) if len(dims) == 1
                        else f"({self.q(dims[0].name)} / {self.q(dims[1].name)})")

        def nest(xs):
            return xs[0] if len(xs) == 1 else f"({xs[0]} + {nest(xs[1:])})"
        cols_el = _sub(table, "cols")
        cols_el.text = nest([x for c in cols for x in registry.shelf(self, c)])
        totals.shelves(self, s, rows_el, cols_el)  # decisions/036
        totals.subtotals(self, table, s, dims)

    def _registry_cell(self, basic, s, box, size, head=False):
        """Registry in its cell: a strip of column titles (text zones, margin 0), the sheet right under it
        (margin-top 0, as the reference builds it); the sheet's header and pane widths are set so that the titles stand
        over their columns. Without a block header the strip keeps the block's margin above it."""
        x, y, w, h = box
        width, height = size
        dims, cols = self.registry_cols[s["name"]]
        header, panes = self.registry_els[s["name"]]
        sheet_m = spacing.margins(box, box, self.block_headers, edge=self._edge())
        content_px = w * width // 100000 - sheet_m["left"] - sheet_m["right"]
        dim_px = [registry.row_header_px(self, d, s) for d in dims]
        th_px = registry.header_px(self, s)  # a band of the HTML header color is taller (decisions/079)
        sheet_h_px = (h * height // 100000 - th_px - (0 if head and self.block_headers else sheet_m["top"])
                      - sheet_m["bottom"])  # the sheet's height under the titles
        bar = registry.scrollbar_px(self, s, cols, sheet_h_px)  # a scrolling sheet's bar takes room from the panes
        spark = sparkline.line_column(s)  # its own sheet right of the registry, as wide as a column (decisions/153)
        if spark and bar:
            raise ValueError(f"Registry '{s['name']}': its rows do not fit the cell, and a line spark's rows would "
                             f"not scroll with them; give the cell more height, drop rows or set spark.form 'glyphs'")
        col_px = registry.widths(cols + [spark] * bool(spark), content_px - sum(dim_px) - bar)  # equal (decisions/120)
        spark_px = col_px.pop() if spark else 0
        registry.check_widths(self, s, cols, col_px, dim_px, sheet_h_px)  # decisions/064: every number and title whole
        for d, px in zip(dims, dim_px):
            _sub(header, "format", attr="width", field=self.q(d.name), value=str(px))
        for pane, px in zip(panes, col_px):
            _sub(pane, "format", attr="minwidth", value=str(px))
            _sub(pane, "format", attr="maxwidth", value=str(px))
        th = self._units(th_px, height)
        ty = y + (0 if head or not self.block_headers else self._units(sheet_m["top"], height))
        titles = [(self.shown(d.col), px, "0") for d, px in zip(dims, dim_px)] + [
            (registry.label(c["spec"]), px, registry.TITLE_ALIGN[registry.align(c)]) for c, px in zip(cols, col_px)]
        titles += [(registry.label(spark), spark_px, "0")] if spark else []
        left = sheet_m["left"]
        for text, px, ali in titles:  # edges from the running total: rounding each width alone made neighbours overlap
            x0, x1 = self._units(left, width), self._units(left + px, width)
            z = _sub(basic, "zone", forceUpdate="true", h=str(th), id=self._zid(), type_v2="text",
                     w=str(x1 - x0), x=str(x + x0), y=str(ty))
            fg, fill = registry.title_style(self, s)  # on a band: its fill, padding, contrasting text (079)
            _sub(_sub(z, "formatted-text"), "run", bold="true", **fg, fontsize=str(self.font["table_header"]),
                 **({"fontalignment": ali} if ali != "0" else {})).text = text  # a number's title at its right (126)
            self._zone_style(z, margin=0, **fill)  # column titles stand right on their columns (reference: margin 0)
            left += px
        split = w - (self._units(spark_px + sheet_m["right"], width) if spark else 0)
        attrs = dict(h=str(y + h - ty - th), id=self._zid(), name=s["name"], show_title="false", w=str(split),
                     x=str(x), y=str(ty + th))
        if self.block_headers:
            sheet_m["top"] = 0
        self._zone_style(_sub(basic, "zone", **attrs), {**sheet_m, "right": 0} if spark else sheet_m)
        if spark:  # the line's rows level with the registry's, each pane a registry row tall
            p = self.part[sparkline.part_name(s, spark)]
            sparkline.size(self, p, registry.row_height_px(self, s, cols), spark_px)
            self._zone_style(_sub(basic, "zone", **{**attrs, "id": self._zid(), "name": p["name"], "w": str(w - split),
                                                     "x": str(x + split)}), {**sheet_m, "left": 0})

    def _card_label(self, pane, s, fields):
        """KPI card text (the reference's card): period, name, value, change colored good/bad + its base."""
        per, cur = (f"<{self.q(f.name)}>" for f in fields[:2])
        in_card = kpi2.period_in_card(s["card"])  # the date under the name, the name dark (decisions/169, mock)
        ft = _sub(_sub(pane, "customized-label"), "formatted-text")
        br = ("Æ\n", {})  # Tableau's line-break run
        font = kpi2.card_font(self, s["card"])  # the mock's sizes with separate_cards (decisions/178)
        # in the card theme the name is regular and muted, the number in the text color (style-references-3.md)
        name = dict(fontcolor=COLOR["muted"]) if self.theme and not in_card else dict(bold="true")
        value = dict(bold="true", **({"fontcolor": theme.title_color(self)} if self.theme else {}))
        muted = dict(fontcolor=COLOR["muted"], fontsize=font["kpi_period"])
        runs = [] if kpi2.period_in_header(self.spec) or in_card else [(per, muted), br]  # decisions/169
        heading = params.text(cards.heading(s["measure"]), self.params)
        runs += [(heading, dict(**name, fontsize=font["kpi_name"])), br]
        if kpi2.date_under_name(s["card"]):  # the date under the name only with card_date (decisions/177)
            runs += [(per, muted), br]
        runs += [(cur, dict(**value, fontsize=theme.kpi_value_pt(self, s["card"])))]
        if not kpi2.pill(s["card"]):  # the change line: '▲ 10.5% MoM', or '▲ 1 466 | 10.5% MoM' (decisions/037)
            runs += [br] + kpi2.card_runs(self, s, fields[2:])
        if kpi2.target(s["measure"]):  # decisions/155
            runs += [br] + kpi2.progress_runs(self, fields[-2:])
        for text, attrs in runs:
            attrs = kpi2.face(s["card"], attrs, text == heading)  # the weight drawn on separate cards (178)
            _sub(ft, "run", fontalignment="0", **{k: str(v) for k, v in attrs.items()}).text = text  # left

    # ---- dashboard (golden 350-442) ------------------------------------------------------
    def _zid(self):
        self._zone_id += 1
        return str(self._zone_id)

    @staticmethod
    def _units(px, size):
        """Pixels -> Tableau zone units (1/100000 of the dashboard width or height), a half up as Desktop saves it
        (33px at 1600 is 2062.5, Desktop writes 2063; decisions/168)."""
        return math.floor(px * 100000 / size + 0.5)

    @staticmethod
    def _zone_style(z, margin=design.ZONE, padding=None, background=None):
        """Zone formats in the order Desktop writes them; None leaves one out. margin: px or {side: px}."""
        margin = SPACE["zone_margin"] if margin is design.ZONE else margin
        st = _sub(z, "zone-style")
        for a, v in [("border-color", "#000000"), ("border-style", "none"), ("border-width", "0"),
                     *(spacing.formats(margin) if margin is not None else []), ("padding", padding),
                     ("background-color", background)]:
            if v is not None:
                _sub(st, "format", attr=a, value=str(v))

    def _header_px(self, title, subtitle, sizes, width_px, where, top=design.ZONE, bottom=design.ZONE):
        """Height in px of a title/subtitle text block wrapped in width_px, with its zone's top/bottom margins."""
        lines = []
        for text, pt in zip((title, subtitle), sizes):
            if text:
                n = design.text_lines(params.shown(colors.plain(text), self.params).replace("**", ""), pt, width_px)
                if n > design.MAX_TEXT_LINES:
                    raise ValueError(f"{where}: '{text}' needs ~{n} lines at {pt}pt in a {width_px}px block "
                                     f"(max {design.MAX_TEXT_LINES}): shorten it or widen the block")
                lines.append((pt, n))
        return design.header_px(lines, top, bottom)

    def _edge(self, canvas=False):
        """Margin on a block's outer side: block_margin; zone_margin for the early goldens (block_headers false).
        In the card theme 0 inside a card, the card's margin for the header row and the legend panel (canvas)."""
        if self.theme:
            return theme.canvas_edge(self) if canvas else theme.block_edge(self)
        return SPACE["block_margin"] if self.block_headers else SPACE["zone_margin"]

    def _text_zone(self, parent, box, title, subtitle, sizes, margin=design.ZONE, dashboard=False,
                   legend=()):
        """Header as the reference authors build it: a text zone with the title, a line break, a grey subtitle.
        In the card theme the title is in the text color and the dashboard subtitle a darker grey."""
        x, y, w, h = box
        z = _sub(parent, "zone", forceUpdate="true", h=str(h), id=self._zid(), type_v2="text", w=str(w), x=str(x),
                 y=str(y))
        ft = _sub(z, "formatted-text")
        fg = {"fontcolor": theme.title_color(self)} if self.theme else {}
        if title:
            for text, bold in _bold_parts(title):  # a [Parameter] shows its current value (decisions/020)
                _sub(ft, "run", **({"bold": "true"} if bold else {}), **fg, fontsize=str(sizes[0])).text = params.text(
                    text, self.params)
        if title and subtitle:
            _sub(ft, "run").text = "Æ\n"  # Tableau's line-break run
        for text, role in colors.runs(subtitle, "Subtitle") if subtitle else []:  # colored words: bold, in color
            attrs = (dict(bold="true", fontcolor=theme.word_color(self, role)) if role
                     else dict(fontcolor=theme.subtitle_color(self, dashboard)))
            _sub(ft, "run", **attrs, fontsize=str(sizes[1])).text = params.text(text, self.params)
        insight.legend_runs(ft, legend, sizes[1], bool(title or subtitle))  # an inline legend (decisions/045)
        self._zone_style(z, margin)

    def _grid(self, basic, rows, box, heights, size):
        """A grid: rows split the box by their height weights; a group cell holds a grid of its own."""
        x, y0, w, h0 = box
        for i, (row, (y, h)) in enumerate(zip(rows, _split(y0, h0, heights))):
            self._grid_row(basic, i, row, (x, y, w, h), size)

    def _grid_row(self, basic, i, row, box, size):
        """One grid row. Blocks with a header share a band as tall as the tallest header in the row, so the
        sheets under them start level; a block without a header (or a group) uses the full row height."""
        x0, y0, w0, h0 = box
        width, height = size
        sizes = (self.font["block_title"], self.font["block_subtitle"])
        cells, band_px, lines_px = [], 0, {}
        for (cell, _), (x, w) in zip(_cells(row), _split(x0, w0, [wt for _, wt in _cells(row)])):
            if isinstance(cell, dict):  # group
                cells.append((cell, x, w, None, 0, 0))
                continue
            s = self.sheet_spec[cell]
            if s["type"] == interact.SWITCH:  # its views draw their own headers (decisions/042)
                cells.append((s, x, w, interact.SWITCH, 0, 0))
                continue
            with self._source_of(cell):  # the sheet's source (decisions/083)
                # in the card theme a block's zones go into its card, inside the card's margin, border and padding;
                # the padding by the card's weight (decisions/070)
                ix, iy = (theme.inset_units(self, size, s) if self.theme else (0, 0))
                x, w = x + ix, w - 2 * ix
                head = 0
                if self.block_headers and (s.get("title") or s.get("subtitle")):
                    text_px = w * width // 100000 - 2 * self._edge()
                    head = self._header_px(s.get("title"), s.get("subtitle"), sizes, text_px, f"Sheet '{cell}'",
                                           self._edge(), SPACE["header_gap"])
                    head += insight.legend_px(self, s, text_px, sizes[1])  # the legend line (decisions/045)
                    head += kpi2.legend_px(kpi2.block_legend(s), text_px, sizes[1])  # status legend (decisions/062)
                    lines_px[cell] = insight.px(self, s, text_px)  # the insight line under the header
                    band_px = max(band_px, head + lines_px[cell])
            cells.append((s, x, w, head, ix, iy))
        band = self._units(band_px, height)
        h = h0 - 2 * max(iy for *_, iy in cells)
        if band and h - band < band:
            raise ValueError(f"Grid row {i + 1} is too short for its block headers: "
                             f"{(h - band) * height // 100000}px left for sheets under a {band_px}px header; "
                             f"give the row a bigger row_heights weight or the dashboard more height")
        for s, x, w, head, ix, iy in cells:
            if head is None:  # group ('rows' alone would also match a table sheet)
                self._grid(basic, s["rows"], (x, y0, w, h0), s.get("row_heights", [1] * len(s["rows"])), size)
                continue
            if head == interact.SWITCH:
                with self._source_of(s["name"]):  # its flag calcs are its views' source's (decisions/082)
                    interact.switch_cell(self, basic, s, (x, y0, w, h0), size)
                continue
            with self._source_of(s["name"]):  # the sheet's source (decisions/083)
                self._grid_cell(basic, s, (x, w, head, ix, iy), (y0, h0), band, lines_px, size, sizes)

    def _grid_cell(self, basic, s, cell, row, band, lines_px, size, sizes):
        """A block of a grid row: its header, the sheet's zones (_grid_row)."""
        x, w, head, ix, iy = cell
        y0, h0 = row
        width, height = size
        y, h = y0 + iy, h0 - 2 * iy
        if kpi2.separate(s):  # a card per measure (decisions/178)
            self._separate_cards(basic, s, (x - ix, y0, w + 2 * ix, h0), (ix, iy), head, size)
            return
        parent = theme.card(self, basic, (x - ix, y0, w + 2 * ix, h0), (x, y, w, h), s) if self.theme else basic
        if head:
            # Tableau centers a text zone's lines vertically: a header shorter than the row's band keeps its
            # own height (its title level with the others) and an empty zone fills the band under it.
            th = min(band, self._units(head, height))
            self._text_zone(parent, (x, y, w, th), s.get("title"), s.get("subtitle"), sizes,
                            spacing.header((x, y, w, th), (x, y, w, h), self.block_headers, self._edge()),
                            legend=insight.legend(self, s) + kpi2.block_legend(s))
            th += insight.zone(self, parent, s, (x, y + th, w, min(band - th, self._units(
                lines_px.get(s["name"], 0), height))), (x, y, w, h))  # decisions/045
            if th < band:
                self._zone_style(_sub(parent, "zone", h=str(band - th), id=self._zid(), type_v2="empty",
                                      w=str(w), x=str(x), y=str(y + th)))
        sy, sh = (y + band, h - band) if head else (y, h)
        under = self._units(insight.below_px(self, s, w * width // 100000 - 2 * self._edge(), sizes[1]), height)
        sh -= under  # the legend under the block (decisions/173)
        if registry.is_registry(s):
            self._registry_cell(parent, s, (x, sy, w, sh), size, bool(head))
            return
        if heatmap.margins(s):  # the heatmap and its margin sheets, lined up (decisions/041)
            heatmap.cell(self, parent, s, (x, sy, w, sh), size, bool(head))
            return
        for p, (zx, zy, zw, zh) in self._part_boxes(s, (x, sy, w, sh), size, bool(head)):
            if p is theme.DIVIDER:
                theme.divider(self, parent, (zx, zy, zw, zh))
                continue
            if p is kpi2.FILLER:  # the rest of a pill's row (decisions/037)
                self._zone_style(_sub(parent, "zone", h=str(zh), id=self._zid(), type_v2="empty", w=str(zw),
                                      x=str(zx), y=str(zy)),
                                 spacing.margins((zx, zy, zw, zh), (x, sy, w, sh + under), self.block_headers, bool(head),
                                                 self._edge()))
                continue
            attrs = dict(h=str(zh), id=self._zid(), name=p["name"])
            if (p["type"] in CARD_PARTS or self.block_headers) and not compareviz.shows_title(p):
                attrs["show_title"] = "false"
            attrs.update(w=str(zw), x=str(zx), y=str(zy))
            zm = spacing.margins((zx, zy, zw, zh), (x, sy, w, sh + under), self.block_headers, bool(head), self._edge())
            self._zone_style(_sub(parent, "zone", **attrs), zm)
            ink.check_axis_title(self, p, zw * width // 100000 - zm["left"] - zm["right"])
            ink.check_column_labels(self, p, zw * width // 100000 - zm["left"] - zm["right"])
            distviz.fit_zone(self, p, zw * width // 100000 - zm["left"] - zm["right"])  # decisions/144
            heatmap.fit_zone(self, p, zw * width // 100000 - zm["left"] - zm["right"],  # decisions/144
                             zh * height // 100000 - zm["top"] - zm["bottom"])
            dualaxis.fit(self, p, zw * width // 100000 - zm["left"] - zm["right"],  # the ring (decisions/069)
                         zh * height // 100000 - zm["top"] - zm["bottom"])
            compareviz.fit(self, p, zw * width // 100000 - zm["left"] - zm["right"],  # the squares (polish-26b)
                           zh * height // 100000 - zm["top"] - zm["bottom"])
            tilegrid.fit(self, p, zw * width // 100000 - zm["left"] - zm["right"])  # code only on a narrow tile (154)
        if under:
            insight.below_zone(self, parent, s, (x, sy + sh, w, under), (x, y, w, h), sizes[1],
                               w * width // 100000 - 2 * self._edge())

    def _separate_cards(self, basic, s, box, inset, head, size):
        """separate_cards (decisions/178, logistics mock): the cell split into a card per measure, each a white
        face with its border and the canvas between them (theme.card), its text left and its sparkline right
        (_cards_right)."""
        if not self.theme or head:
            raise ValueError(f"Sheet '{s['name']}': separate_cards draws its own cards: it needs the card theme "
                             f"and no title / subtitle (each card names its measure)")
        x, y, w, h = box
        ix, iy = inset
        edge = self._edge()
        text_px = design.header_px(self._card_lines(s), 0, 0)  # the card's padding is the text's margin
        parts = self.physical[s["name"]]
        for m, (cx, cw) in zip(s["measures"], _split(x, w, [1] * len(s["measures"]))):
            inner = (cx + ix, y + iy, cw - 2 * ix, h - 2 * iy)
            parent = theme.card(self, basic, (cx, y, cw, h), inner, s)
            g = [p for p in parts if p["measure"] is m]
            for p, (zx, zy, zw, zh) in self._spark_over(s, g, inner, text_px, size):
                zm = spacing.margins((zx, zy, zw, zh), inner, self.block_headers, False, edge)
                if p is kpi2.FILLER:
                    attrs = dict(h=str(zh), id=self._zid(), type_v2="empty")
                else:
                    attrs = dict(h=str(zh), id=self._zid(), name=p["name"], show_title="false")
                self._zone_style(_sub(parent, "zone", **attrs, w=str(zw), x=str(zx), y=str(zy)), zm)

    def _spark_over(self, s, g, box, text_px, size):
        """A separate card's zones (decisions/178, the mock): its text over the whole face, the sparkline
        (CARD_SPARK_RIGHT_PX wide) on top of it at the right edge, as high as the value line: between the period
        line and the change line, which run the card's full width with the name. The sparkline zone comes after
        the text zone, so Desktop draws it on top."""
        x, y, w, h = box
        width, height = size
        need = 2 * SPACE["zone_margin"] + self._value_px(s) + design.CARD_SPARK_GAP_PX + design.CARD_SPARK_RIGHT_PX[0]
        least = kpi2.separate_min_px(self.spec, s, theme.font(self.spec), theme.kpi_value_pt(self, s))
        if h * height // 100000 < least:  # the same rule as the lint's D12 (decisions/182)
            raise ValueError(f"Sheet '{s['name']}': the cell is too short for a KPI card ({least}px of value "
                             f"text); give its row a bigger row_heights weight or the dashboard more height")
        if w * width // 100000 < need:  # the text's margin and pane, the number, the gap, the sparkline
            raise ValueError(f"Sheet '{s['name']}': separate_cards needs {need}px per card for the value and "
                             f"the sparkline; give the cards more width")
        i = self._card_keys(s).index("kpi_value")
        px = [design.line_px(pt) for pt, _ in self._card_lines(s)]
        top = h * height / 100000 / 2 - sum(px) / 2 + sum(px[:i])  # Desktop centers the text in its zone
        m = SPACE["zone_margin"]  # the sparkline zone's own margin around its line
        sx = x + w - self._units(design.CARD_SPARK_RIGHT_PX[0] + m, width)
        sy = y + max(0, self._units(top - m, height))
        return [(p, (x, y, w, h)) for p in g[:-1]] + [(g[-1], (sx, sy, x + w - sx,
                                                                min(y + h - sy, self._units(px[i] + 2 * m, height))))]

    def _value_px(self, s):
        """The widest number of a separate card at its size: a 2-digit value in each measure's format with its
        unit ('99 min', '99.9%')."""
        def sample(m):
            f = formats.normalize(m.get("format")) or {"type": "number", "units": "none"}
            return 0.999 if f["type"] == "percent" else 99 * formats.UNITS[f["units"]][0]
        pt = theme.kpi_value_pt(self, s)
        return max(design.text_px(formats.render(sample(m), m.get("format") or {"type": "number", "decimals": 0},
                                                 self.locale), pt, bold=True) for m in s["measures"])

    def _part_boxes(self, s, box, size, head=False):
        """Zones of a sheet's physical parts inside its cell: [(part, (x, y, w, h))].

        Tiles sit side by side (arrange row) or stacked (column). A KPI card per measure: in a row of cards its
        value text is above its history; stacked (column), the value is left of the history (as in the reference).
        The card's value text needs its lines, the pane padding and its zone's margins (tbuilder/spacing.py).
        """
        x, y, w, h = box
        width, height = size
        parts = self.physical[s["name"]]
        column = s.get("arrange", "row") == "column"
        value_pt = theme.kpi_value_pt(self, s)
        n = len(s["measures"]) if cards.is_cards(s) else len(parts)  # a card: its value text, its history, ...
        if column:
            cols, rules = None, []
        elif theme.strip(s):  # one card, a 1px divider between the measures (decisions/030)
            cols, rules = theme.divide(self, x, w, n, width)
        elif s["type"] == "donut":  # the legend as wide as its text, the ring the rest (decisions/069)
            cols, rules = dualaxis.split(self, s, x, w, width), []
        else:
            cols, rules = _split(x, w, [1] * n), []
        dividers, out = [(theme.DIVIDER, (rx, y, rw, h)) for rx, rw in rules], []
        if not cards.is_cards(s):
            if parts[0]["type"] == "tile":  # its caption and value, or Desktop adds a scrollbar
                m = (self._edge(), self._edge()) if column else (0 if head else self._edge(), self._edge())
                need = (design.header_px([(self.font["tile_caption"], 1), (value_pt, 1)] + insight.note_lines(s), *m)
                        + design.TILE_TEXT_PAD_PX)
                if (h // (len(parts) if column else 1)) * height // 100000 < need:
                    raise ValueError(f"Sheet '{s['name']}': the cell is too short for a KPI tile ({need}px with "
                                     f"its margins); give its row a bigger row_heights weight or the dashboard "
                                     f"more height")
            if parts[0]["type"] == interact.BUTTON and \
                    (h // (len(parts) if column else 1)) * height // 100000 < interact.min_px():
                raise ValueError(f"Sheet '{s['name']}': the cell is too short for its buttons "
                                 f"({interact.min_px()}px each); give its row a bigger row_heights weight")
            if column:
                return [(p, (x, py, w, ph)) for p, (py, ph) in zip(parts, _split(y, h, [1] * len(parts)))]
            return [(p, (px, y, pw, h)) for p, (px, pw) in zip(parts, cols)] + dividers
        if column:  # a stacked card may be the first or the last of the block: its margins above and below
            m_top, m_bottom = self._edge(), self._edge()
        else:  # in a row of cards the value text is on the block's top edge, the history under it
            m_top, m_bottom = (0 if head else self._edge()), SPACE["zone_margin"]
        text_px = design.header_px(self._card_lines(s), m_top, m_bottom) + design.CARD_TEXT_PAD_PX
        groups = [[p for p in parts if p["measure"] is m] for m in s["measures"]]  # a card's parts, in zone order
        inner, edge = SPACE["zone_margin"], self._edge()
        pill_px = kpi2.under_px(s, inner)  # the pill's or progress bar's fill + margins above and below (155)
        if column:
            value_w = theme.card_value_w(self)
            if kpi2.has_status(s):  # the text keeps its width beside a status dot (decisions/062)
                value_w += design.STATUS_PX + 2 * inner
            vw = self._units(value_w, width)
            for g, (cy, ch) in zip(groups, _split(y, h, [1] * len(groups))):
                if pill_px and cy + ch == y + h:  # the last card's pill is on the block's bottom edge
                    pill_px = kpi2.under_px(s, inner) - inner + edge
                if (ch * height // 100000 < text_px + pill_px
                        or (w - vw) * width // 100000 < design.CARD_HISTORY_MIN_W_PX):
                    raise ValueError(f"Sheet '{s['name']}': a stacked KPI card needs {text_px + pill_px}px of height "
                                     f"and {value_w + design.CARD_HISTORY_MIN_W_PX}px of width; give "
                                     f"the cell more room or use fewer measures")
                out += self._card_text(s, g, (x, cy, vw, ch), x, pill_px, edge, size)
                out.append((g[-1], (x + vw, cy, w - vw, ch)))
            return out
        if kpi2.history_right(s):  # a small sparkline right of the value (decisions/169)
            return self._cards_right(s, groups, cols, (x, y, w, h), text_px, edge, size) + dividers
        vh = self._units(text_px, height)
        ph = self._units(pill_px, height)
        if (h - vh - ph) * height // 100000 < design.CARD_HISTORY_MIN_PX:
            raise ValueError(f"Sheet '{s['name']}': the cell is too short for a KPI card (value text "
                             f"+ at least {design.CARD_HISTORY_MIN_PX}px of history); give its row "
                             f"a bigger row_heights weight or the dashboard more height")
        for g, (cx, cw) in zip(groups, cols):
            out += self._card_text(s, g, (cx, y, cw, vh + ph), x, pill_px, edge, size)
            out.append((g[-1], (cx, y + vh + ph, cw, h - vh - ph)))
        return out + dividers

    def _cards_right(self, s, groups, cols, box, text_px, edge, size):
        """A row of cards with history_place 'right' (decisions/169, logistics mock): the text over the card's
        height, the sparkline (CARD_SPARK_RIGHT_PX) right of it level with the value, empty zones above and below.
        The sparkline narrows to CARD_HISTORY_MIN_W_PX when the card is narrow."""
        x, y, w, h = box
        width, height = size
        inner = SPACE["zone_margin"]
        spark_w, spark_h = design.CARD_SPARK_RIGHT_PX
        lines = self._card_lines(s)
        if h * height // 100000 < text_px:
            raise ValueError(f"Sheet '{s['name']}': the cell is too short for a KPI card ({text_px}px of value "
                             f"text); give its row a bigger row_heights weight or the dashboard more height")
        hh = self._units(spark_h + 2 * inner, height)
        mid = self._units(h * height / 100000 / 2 + kpi2.dot_offset_px(lines, self._card_keys(s).index("kpi_value")),
                          height)  # the value line's middle: Desktop centers the text in its zone
        hy = max(0, min(h - hh, mid - hh // 2))
        out = []
        text_w = max(theme.card_value_w(self), kpi2.delta_line_px(self, s) + 2 * inner)  # on one line
        for g, (cx, cw) in zip(groups, cols):
            sw_px = min(spark_w, cw * width // 100000 - text_w - 2 * inner)
            if sw_px < design.CARD_HISTORY_MIN_W_PX:
                raise ValueError(f"Sheet '{s['name']}': history_place 'right' needs {text_w}px "
                                 f"of value text and {design.CARD_HISTORY_MIN_W_PX + 2 * inner}px of sparkline "
                                 f"per card; give the cards more width or the history below")
            sw = self._units(sw_px + 2 * inner, width)
            out += self._card_text(s, g[:-1], (cx, y, cw - sw, h), x, 0, edge, size)
            hx = cx + cw - sw
            if hy:
                out.append((kpi2.FILLER, (hx, y, sw, hy)))
            out.append((g[-1], (hx, y + hy, sw, hh)))
            if hy + hh < h:
                out.append((kpi2.FILLER, (hx, y + hy + hh, sw, h - hy - hh)))
        return out

    def _card_text(self, s, g, box, cell_x, pill_px, edge, size):
        """Zones of a card's text at box: [marker left of it], [a status dot left of it: decisions/062], the value text,
        [the pill under it and an empty zone for the rest of the pill's row] (decisions/037). Without these options:
        the value text alone."""
        x, y, w, h = box
        width, height = size
        inner = SPACE["zone_margin"]
        by = {p["type"]: p for p in g}
        out = []
        left = edge if x == cell_x else inner  # the left margin of the leftmost zone (spacing.margins)
        if kpi2.MARKER in by:  # its 4px inside its margins
            mw = self._units(design.MARKER_PX + left + inner, width)
            out.append((by[kpi2.MARKER], (x, y, mw, h)))
            x, w, left = x + mw, w - mw, inner
        ph = self._units(pill_px, height) if kpi2.PILL in by or kpi2.PROGRESS in by else 0
        if kpi2.STATUS in by:  # its STATUS_PX inside its margins, its middle level with the number (decisions/062)
            sw = self._units(design.STATUS_PX + left + inner, width)
            off = self._units(round(2 * kpi2.dot_offset_px(self._card_lines(s),
                                                            self._card_keys(s).index("kpi_value"))), height)
            out.append((by[kpi2.STATUS], (x, y + off, sw, h - ph - off)))
            x, w, left = x + sw, w - sw, inner
        out.append((by["card_value"], (x, y, w, h - ph)))
        if kpi2.PROGRESS in by:  # the bar under the text, as wide as it (decisions/155)
            return out + [(by[kpi2.PROGRESS], (x, y + h - ph, w, ph))]
        if kpi2.PILL not in by:
            return out
        pw = min(w, self._units(kpi2.pill_px(self, s) + left + inner, width))
        out.append((by[kpi2.PILL], (x, y + h - ph, pw, ph)))
        if pw < w:
            out.append((kpi2.FILLER, (x + pw, y + h - ph, w - pw, ph)))
        return out

    def _card_keys(self, s):
        """The lines of a KPI card's value text (kpi2.card_keys, shared with the lint)."""
        return kpi2.card_keys(self.spec, s)

    def _card_lines(self, s):
        """[(pt, 1)] of a KPI card's value text (_card_keys)."""
        font = kpi2.card_font(self, s)
        return [(theme.kpi_value_pt(self, s) if k == "kpi_value" else font[k], 1) for k in self._card_keys(s)]

    def side_items(self):
        """Color legends and filter cards for the right panel: (type, sheet, field_ref, lines).

        One legend per color field: sheets sharing a color field share Tableau's color mapping.
        """
        items = []
        for name in (p["name"] for n in _leaves(self.spec["dashboard"]["grid"]) for p in self.physical[n]
                     if p["type"] not in ("card_history", kpi2.PILL, kpi2.MARKER, interact.BUTTON,  # self-explanatory
                                          kpi2.STATUS,  # a status dot: its legend is a header line (decisions/062)
                                          kpi2.PROGRESS,  # its colors: the card text names the target (155)
                                          *dualaxis.LEGEND_PARTS)  # a donut's legend: own sheets (044, 069)
                     and not colors.kind(p) and not insight.inline(p)  # / in the subtitle, in the header (045)
                     and not (scatter.is_scatter(p) and scatter.color_kind(p) == "highlight")  # in the subtitle (047)
                     and not (treemap.is_treemap(p) and treemap.highlight(p))  # in the subtitle (138)
                     and not waterfall.is_waterfall(p)  # good / bad in the subtitle (139)
                     and not funnel.is_funnel(p)  # one accent (159)
                     and distviz.kind(p) != distviz.BUMP  # highlighted in the subtitle (140)
                     and compareviz.kind(p) not in (compareviz.SLOPE, compareviz.WAFFLE)):  # in the subtitle (141)
            for tag, ref in self.shapes[name][1]:
                if tag == "color" and not any(i[0] == "color" and i[2] == ref for i in items):
                    with self._source_of(name):  # the sheet's source (decisions/083)
                        f = next(f for f in self.shapes[name][0] if self.q(f.name) == ref)
                    if f.type == "quantitative":  # heatmap: continuous color, value is labelled in cell
                        continue
                    items.append(("color", name, ref, len(f.col.distinct) + 1))
        for _ in self._each_source():  # each source's filters (decisions/083)
            for spec_f, f in zip(self.spec.get("filters", []), self.filters):
                if not self._filter_on(spec_f):  # another dashboard's filter (decisions/071)
                    continue
                owner = self._filter_owner(spec_f)  # show_on, or a sheet of this dashboard (decisions/040)
                items.append(("filter", owner, self.q(f.name), len(f.col.distinct) + 2))
        return items

    def _dashboard_header(self, root, d, filters, box, size):
        """Header row: title/subtitle text, then filter dropdown cards at the right (the reference's layout:
        a horizontal flow with fixed-width cards). The row is a block (tbuilder/spacing.py): the sides of its text
        and cards on the row's edges get the block margin. Returns the row height in zone units."""
        x, y, w = box
        width, height = size
        sizes = (self.font["dash_title"], self.font["dash_subtitle"])
        by_ref = {}
        for _ in self._each_source():  # each source's filters (decisions/083)
            by_ref.update({self.q(f.name): f for f in self.filters})
        cards = [(i, filters_mod.card_px(by_ref[i[2]])) for i in filters]  # a range card is wider
        ctrls = params.header_controls(self)  # parameter cards after the filter cards (decisions/020)
        edge, inner = self._edge(canvas=True), SPACE["zone_margin"]
        as_of = [(kpi2.AS_OF_SHEET, design.DATA_AS_OF_PX)] if kpi2.as_of_field(self.spec) else []  # decisions/037
        if kpi2.period_in_header(self.spec):  # 'Dec 2025 compared to Nov 2025' left of it (decisions/169)
            as_of = [(kpi2.period_name(kpi2.period_sheet(self.spec)), kpi2.period_header_px(self))] + as_of
        tog = [(None, actions.toggle_px(self.spec))] if actions.toggle(d) and cards else []  # Show/Hide (decisions/160)
        n = len(as_of) + len(cards) + len(ctrls) + len(tog)
        # a card's zone is fixed-size plus its left and right margins (fixed-size excludes them); the last card
        # is on the row's right edge. Desktop lays the cards out from the row's right edge (card_lefts)
        boxes = as_of + cards + ctrls + tog
        lefts = card_lefts(x + w, [b[1] + inner + (edge if k == n - 1 else inner) for k, b in enumerate(boxes)], width)
        card_w = [b - a for a, b in zip(lefts, lefts[1:] + [x + w])]
        text_w = w - sum(card_w)
        if text_w < w // 2:
            raise ValueError(f"Dashboard '{d['name']}': {n} header cards (filters, parameters) leave less than half "
                             f"of the header for the title; use fewer or a wider dashboard")
        text_px = text_w * width // 100000 - edge - (inner if n else edge)
        px = self._header_px(d.get("title"), d.get("subtitle"), sizes, text_px, f"Dashboard '{d['name']}'",
                             edge, edge)
        legend = kpi2.dashboard_legend(self, d)  # the status legend line (decisions/062)
        px += kpi2.legend_px(legend, text_px, sizes[1])
        card_px = design.HEADER_FILTER_H_PX - 2 * inner + 2 * edge  # the card's content keeps its height
        radio = [interact.radio_px(p) for p, _ in ctrls if p.control == "radio"]  # a line per value (042)
        radio += [filters_mod.card_h(self.filter_spec[i[2]]) for i, _ in cards]  # a slider is taller (162)
        card_px = max([card_px] + [r - 2 * inner + 2 * edge for r in radio])
        h = self._units(max(px, card_px) if n > len(as_of) else px, height)
        row_box = (x, y, w, h)
        if not n:
            self._text_zone(root, row_box, d.get("title"), d.get("subtitle"), sizes,
                            spacing.margins(row_box, row_box, self.block_headers, edge=edge), dashboard=True,
                            legend=legend)
            return h
        row = _sub(root, "zone", h=str(h), id=self._zid(), param="horz", type_v2="layout-flow", w=str(w), x=str(x),
                   y=str(y))
        # hidden cards at open: the title takes their width too, as Desktop saves it (decisions/160)
        tw = text_w + (sum(card_w[len(as_of):len(as_of) + len(cards)]) if actions.toggle(d) == "hidden" and tog else 0)
        self._text_zone(row, (x, y, tw, h), d.get("title"), d.get("subtitle"), sizes,
                        spacing.margins((x, y, tw, h), row_box, self.block_headers, edge=edge), dashboard=True,
                        legend=legend)
        cx = x + text_w
        for (sheet, px), cw in zip(as_of, card_w):  # 'Data as of' (Regional Overview: a fixed 200px sheet zone)
            attrs = dict(fixed_size=str(px), h=str(h), id=self._zid(), is_fixed="true", name=sheet, show_title="false",
                         w=str(cw), x=str(cx), y=str(y))
            self._zone_style(_sub(row, "zone", **attrs),
                             spacing.margins((cx, y, cw, h), row_box, self.block_headers, edge=edge))
            cx += cw
        card_w = card_w[len(as_of):]
        holder = row
        if tog:  # the cards in a container of their own, which the button shows and hides (decisions/160)
            holder = _sub(row, "zone", h=str(h), id=self._zid(), param="horz", type_v2="layout-flow",
                          w=str(sum(card_w[:len(cards)])), x=str(cx), y=str(y))
        for ((_, sheet, ref, _), px), cw in zip(cards, card_w):
            attrs = dict(fixed_size=str(px), h=str(h), id=self._zid(), is_fixed="true", name=sheet, param=ref,
                         type_v2="filter", w=str(cw), x=str(cx), y=str(y))
            attrs.update(filters_mod.card_attrs(self.filter_spec[ref], "header"))  # mode, values (decisions/035)
            self._zone_style(_sub(holder, "zone", **dict(sorted(attrs.items()))),
                             spacing.margins((cx, y, cw, h), row_box, self.block_headers, edge=edge))
            cx += cw
        if tog and actions.toggle(d) == "hidden":  # Desktop saves every zone of a hidden container hidden
            for z in holder.iter("zone"):
                z.set("hidden-by-user", "true")
        for (p, px), cw in zip(ctrls, card_w[len(cards):]):
            params.control_zone(self, row, p, px, (cx, y, cw, h),
                                spacing.margins((cx, y, cw, h), row_box, self.block_headers, edge=edge))
            cx += cw
        if tog:
            bw = card_w[-1]
            z = actions.toggle_button(self, row, d, (cx, y, bw, h), holder)
            self._zone_style(z, spacing.margins((cx, y, bw, h), row_box, self.block_headers, edge=edge))
        return h

    def _sidebar(self, flow, d, items, box, size):
        """Left panel (references): the dashboard title, the filter dropdowns and the color legends,
        top to bottom, on a grey background. A brand sidebar is the shell's (decisions/029)."""
        if shell.brand(d):
            return shell.sidebar(self, flow, d, items, box, size)
        x, y, w, h = box
        width, height = size
        pad = SPACE["panel_padding"]
        cx, cw, cy = x + self._units(pad, width), w - 2 * self._units(pad, width), y + self._units(pad, height)
        side = _sub(flow, "zone", fixed_size=str(design.SIDEBAR_PX), h=str(h), id=self._zid(), is_fixed="true",
                    param="vert", type_v2="layout-flow", w=str(w), x=str(x), y=str(y))
        if d.get("title") or d.get("subtitle"):
            sizes = (FONT["dash_title"], FONT["dash_subtitle"])
            text_px = design.SIDEBAR_PX - 2 * pad - 2 * SPACE["zone_margin"]
            th = self._units(self._header_px(d.get("title"), d.get("subtitle"), sizes, text_px,
                                             f"Dashboard '{d['name']}'"), height)
            self._text_zone(side, (cx, cy, cw, th), d.get("title"), d.get("subtitle"), sizes)
            cy += th
        cy = nav.sidebar(self, side, d, (cx, cy, cw), size, COLOR["sidebar_bg"])  # dashboard buttons (decisions/040)
        for kind, sheet, ref, lines in sorted(items, key=lambda i: i[0] != "filter"):  # filters, then legends
            zh = self._units(filters_mod.card_h(self.filter_spec[ref]) if kind == "filter"  # decisions/162
                             else design.LEGEND_LINE_PX * lines, height)
            attrs = dict(h=str(zh), id=self._zid(), name=sheet)
            if kind == "filter":
                attrs.update(filters_mod.card_attrs(self.filter_spec[ref], "sidebar"))  # decisions/035
            else:
                attrs["pane_specification_id"] = "0"
            attrs.update(param=ref, type_v2=kind, w=str(cw), x=str(cx), y=str(cy))
            self._zone_style(_sub(side, "zone", **attrs))
            cy += zh
        if cy > y + h - self._units(pad, height):
            raise ValueError(f"Dashboard '{d['name']}': the sidebar content (title, filters, legends) is taller "
                             f"than the dashboard; use fewer filters or a taller dashboard")
        self._zone_style(side, margin=None, padding=pad, background=COLOR["sidebar_bg"])

    def dashboards(self, parent):
        """<dashboards> in name order, as Desktop writes them (Citizen, E-Commerce); the tab order is the windows'."""
        wrap = _sub(parent, "dashboards")
        for d in sorted(self.dashes, key=lambda d: d["name"]):
            with self._on(d):
                self.dashboard(wrap)

    def dashboard(self, wrap):
        d = self.spec["dashboard"]
        width, height, grid = d.get("width", 1000), d.get("height", 800), d["grid"]
        db = _sub(wrap, "dashboard", enable_sort_zone_taborder="true", name=d["name"])
        self.dash_uuid = "{" + str(uuid.uuid4()).upper() + "}"  # its simple-id: the export buttons' target
        theme.dashboard_style(self, _sub(db, "style"))  # the canvas color in the card theme
        _sub(db, "size", maxheight=str(height), maxwidth=str(width), minheight=str(height), minwidth=str(width))
        for _ in self._each_source(by_name=True):  # the sources whose cards it shows, then each one's (083)
            cards_on = [f for spec_f, f in zip(self.spec.get("filters", []), self.filters) if self._filter_on(spec_f)]
            if cards_on:
                self._ds_ref(db)
                self._deps(db, cards_on, bare=True)
        params.dashboard_refs(self, db)  # parameter cards in the header
        edge = theme.root_margin(self)
        mx, my = self._units(edge, width), self._units(edge, height)
        sidebar = d.get("sidebar", False)
        has_header = bool(d.get("title") or d.get("subtitle")) and not sidebar
        # With a dashboard header, filter cards sit in its row as dropdowns (reference style); legends stay aside.
        # With a sidebar, the title, the filters and the legends all go there.
        items = [] if sidebar else [i for i in self.side_items() if not (has_header and i[0] == "filter")]
        header_filters = [i for i in self.side_items() if has_header and i[0] == "filter"]
        actions.check_toggle(d, header_filters)  # decisions/160
        panel_w = self._units(design.SIDE_PANEL_PX, width) if items else 0
        inner_w, inner_h = 100000 - 2 * mx, 100000 - 2 * my
        zones = _sub(db, "zones")
        root = _sub(zones, "zone", h="100000", id=self._zid(), type_v2="layout-basic", w="100000", x="0", y="0")
        top = shell.topbar(self, root, d, (mx, my, inner_w), (width, height))  # app bar, decisions/029
        top += nav.tabs(self, root, d, (mx, my + top, inner_w), (width, height))  # decisions/040
        if has_header:
            top += self._dashboard_header(root, d, header_filters, (mx, my + top, inner_w), (width, height))
            top += kpi2.period_zone(self, root, (mx, my + top, inner_w), (width, height))  # decisions/037
        body_y, body_h = my + top, inner_h - top
        flow = _sub(root, "zone", h=str(body_h), id=self._zid(), param="horz", type_v2="layout-flow",
                    w=str(inner_w), x=str(mx), y=str(body_y))
        left = 0
        if sidebar:
            left = self._units(design.SIDEBAR_PX, width)
            self._sidebar(flow, d, self.side_items(), (mx, body_y, left, body_h), (width, height))
        sheets_w = inner_w - panel_w - left
        basic = _sub(flow, "zone", h=str(body_h), id=self._zid(), type_v2="layout-basic", w=str(sheets_w),
                     x=str(mx + left), y=str(body_y))
        self._grid(basic, grid, (mx + left, body_y, sheets_w, body_h), d.get("row_heights", [1] * len(grid)),
                   (width, height))
        if items:
            px = mx + left + sheets_w
            side = _sub(flow, "zone", fixed_size=str(design.SIDE_PANEL_PX), h=str(body_h), id=self._zid(),
                        is_fixed="true", param="vert", type_v2="layout-flow", w=str(panel_w), x=str(px), y=str(body_y))
            y = body_y
            panel = (px, body_y, panel_w, body_h)  # a block: its edge margins (tbuilder/spacing.py)
            for kind, sheet, ref, lines in items:  # stacked from the panel's top, never down to its bottom
                m = spacing.margins((px, y, panel_w, 0), panel, self.block_headers, edge=self._edge(canvas=True))
                h = self._units(design.LEGEND_LINE_PX * lines + m["top"] - SPACE["zone_margin"], height)
                attrs = dict(h=str(h), id=self._zid(), name=sheet)
                if kind == "color":
                    attrs["pane_specification_id"] = "0"
                else:  # a multiple-values list (decisions/035)
                    attrs.update(filters_mod.card_attrs(self.filter_spec[ref], "panel"))
                attrs.update(param=ref, type_v2=kind, w=str(panel_w), x=str(px), y=str(y))
                self._zone_style(_sub(side, "zone", **attrs), m)
                y += h
        self._zone_style(root, margin=edge)
        ET.SubElement(db, "simple-id", uuid=self.dash_uuid)

    # ---- windows (golden 444-596) --------------------------------------------------------
    def windows(self, parent):
        # the Data pane's list of sources: 37px with one, 58 with two (Desktop 2025.1 resave, decisions/083)
        wins = _sub(parent, "windows", source_height=str(37 + 21 * (len(self.sources or [None]) - 1)))
        side = {}
        date_cards = set()
        for _ in self._each_source():  # decisions/083
            date_cards |= {self.q(f.name) for f in self.filters
                           if isinstance(f, (dates.DateFilter, filters_mod.MeasureRange))}
        for d in self.dashes:  # the cards of every dashboard (decisions/040)
            with self._on(d):
                for kind, sheet, ref, _ in self.side_items():
                    if ref not in date_cards and (kind, ref) not in side.get(sheet, []):  # a date card lives on
                        side.setdefault(sheet, []).append((kind, ref))  # the dashboard only, as Desktop saved it
        for s in self.worksheets:
            w = _sub(wins, "window", **{"class": "worksheet"}, name=s["name"])
            cards = _sub(w, "cards")
            left = _sub(_sub(cards, "edge", name="left"), "strip", size="160")
            for t in ["pages", "filters", "marks"] + (["measures"] if s["type"] == "kpi" or colors.kind(s) in ("plan", "benchmark")
                                                      else []):
                _sub(left, "card", type=t)
            top = _sub(cards, "edge", name="top")
            for t in ["columns", "rows", "title"]:
                _sub(_sub(top, "strip", size="2147483647"), "card", type=t)
            if s["name"] in side:
                right = _sub(_sub(cards, "edge", name="right"), "strip", size="160")
                for kind, ref in side[s["name"]]:
                    if kind == "color":
                        _sub(right, "card", pane_specification_id="0", param=ref, type="color")
                    else:
                        _sub(right, "card", param=ref, type="filter")
            _sub(w, "viewpoint")
            _simple_id(w)
        fits = fit.dashboard_fits(parent, *self._fit_counters())  # decisions/068
        for dash, name, have, need in (fit.short_charts(parent) if MIN_CHECK else []):  # decisions/101
            owner = next((n for n, ps in self.physical.items() if any(p["name"] == name for p in ps)), name)
            raise ValueError(f"Sheet '{owner}': the cell is too short for a chart ({have}px inside its margins on "
                             f"dashboard '{dash}', {need}px needed: its axes, titles and {fit.PLOT_MIN_PX}px of plot; "
                             f"Desktop draws nothing in less); give its row a bigger row_heights weight or the "
                             f"dashboard more height")
        for kind, dash, name, have, limit in (fit.crowded(parent, *self._fit_counters()) if MIN_CHECK else []):
            owner = next((n for n, ps in self.physical.items() if any(p["name"] == name for p in ps)), name)
            raise ValueError(f"Sheet '{owner}': " + {  # decisions/093
                "fat": f"its bars would stretch to {have}px a row on dashboard '{dash}' (over {limit}px: a few bars in "
                       f"a tall cell become slabs); give the cell less height, or the chart more members",
                "legend": f"the legend rows would be {have}px each on dashboard '{dash}' (under {limit}px, the text "
                          f"overlaps); give the cell more height or cut the members (top_n with Other)",
                "narrow": f"its columns need {limit}px, the cell leaves {have}px on dashboard '{dash}' (Fit Height "
                          f"would scroll it sideways); give the cell more width",
            }[kind])
        for i, d in enumerate(self.dashes):  # tab order; the first opens with the workbook (decisions/040)
            w = _sub(wins, "window", **{"class": "dashboard"}, **({"maximized": "true"} if i == 0 else {}),
                     name=d["name"])
            vps = _sub(w, "viewpoints")
            with self._on(d):
                shown = set(shell.dashboard_sheets(self)) | set(kpi2.dashboard_sheets(self)) | set(
                    insight.dashboard_sheets(self, set(_leaves(d["grid"]))))  # decisions/045
            for name in sorted({p["name"] for n in _leaves(d["grid"]) for p in self.physical[n]} | shown):
                vp = _sub(vps, "viewpoint", name=name)
                zoom = fit.pick(fits.get((d["name"], name), {fit.EV}))
                if zoom != fit.STD:  # fills its zone, or one way of it (decisions/068)
                    _sub(vp, "zoom", type=zoom)
            _sub(w, "active", id="-1")
            ET.SubElement(w, "simple-id", uuid=self.window_ids[d["name"]])  # the nav buttons' target

    def _fit_counters(self):
        """fit's count(ds, ...) and estimate(sheet) over the data; in a book with several sources by the datasource
        and the sheet's source (decisions/083)."""
        if not self.sources:
            return fit.builder_counter(self), fit.builder_estimate(self)
        counters = {sb.ds: fit.builder_counter(sb) for sb in self.sources}
        estimate = fit.builder_estimate(self)

        def count(ds, cols, caps, **kw):
            return counters[ds](ds, cols, caps, **kw) if ds in counters else None

        def estimate_on(name):
            with self._source_of(name):
                return estimate(name)
        return count, estimate_on

    # ---- assembly ------------------------------------------------------------------------
    def _sign(self):
        """The sheets with the current dashboard's action hints after their subtitles (the block headers)."""
        self.sheet_spec = {s["name"]: actions.sign(s, self.spec) for s in self.spec["sheets"]}

    @contextlib.contextmanager
    def _on(self, d):
        """Check or draw dashboard d: meanwhile self.spec['dashboard'] is d, where the single-dashboard code reads
        it (decisions/040)."""
        prev, self.spec["dashboard"] = self.spec["dashboard"], d
        if hasattr(self, "sheet_spec"):
            self._sign()
        try:
            yield
        finally:
            self.spec["dashboard"] = prev
            if hasattr(self, "sheet_spec"):
                self._sign()

    def _filter_owner(self, f):
        """The sheet whose card shows filter f on the current dashboard: its show_on, or on a dashboard without it
        the first chart sheet there (every sheet carries the shared filter, so its card is the same filter;
        decisions/040). A KPI or a registry owns it only when nothing else is on the dashboard. A filter of some sheets
        (071, 074): one of the sheets it changes."""
        on = [n for n in _leaves(self.spec["dashboard"]["grid"]) if self.owns(n) and filters_mod.applies(self.spec, f, n)]
        types = {s["name"]: s["type"] for s in self.spec["sheets"]}
        controls = ("kpi", "registry", interact.BUTTONS, interact.SWITCH)  # a switch view may be hidden (042)
        name = f["show_on"] if f["show_on"] in on else next(
            (n for n in on if types[n] not in controls), next((n for n in on if types[n] != "registry"), on[0]))
        return self.physical[name][0]["name"]

    def validate_spec(self):
        names = [s["name"] for s in self.spec["sheets"]]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate sheet names: {names}")
        types = {s["name"]: s["type"] for s in self.spec["sheets"]}
        many = len(self.dashes) > 1
        on_any = set()
        for d in self.dashes:
            where = f"Dashboard '{d['name']}'" if many else "Dashboard"
            if d["name"] in names:
                raise ValueError(f"Dashboard name '{d['name']}' collides with a sheet name")
            on_dash = list(_leaves(d["grid"]))
            for n in on_dash:
                if n not in names:
                    raise ValueError(f"{where} references unknown sheet '{n}'")
            if len(set(on_dash)) != len(on_dash):
                raise ValueError(f"A sheet appears twice on the dashboard{' ' + repr(d['name']) if many else ''}")
            interact.check_grid(on_dash, self.spec)
            on_any |= set(on_dash)
            if "row_heights" in d and len(d["row_heights"]) != len(d["grid"]):
                raise ValueError(f"row_heights has {len(d['row_heights'])} values for {len(d['grid'])} grid rows")
            for g, depth in _groups(d["grid"]):
                if depth > MAX_GRID_DEPTH:
                    raise ValueError(f"Grid groups are nested {depth} levels deep (max {MAX_GRID_DEPTH})")
                if "row_heights" in g and len(g["row_heights"]) != len(g["rows"]):
                    raise ValueError(f"A grid group's row_heights has {len(g['row_heights'])} values for "
                                     f"{len(g['rows'])} rows")
            with self._on(d):
                dates.check_filters(self.spec)
        for n in names:
            shown = [d["name"] for d in self.dashes if n in _leaves(d["grid"])]
            if types[n] == "registry" and len(shown) > 1:  # its column widths are set from its one cell
                raise ValueError(f"Registry '{n}' is on dashboards {shown}: a registry's column widths come from its "
                                 f"cell, so it goes on one dashboard")
        for f in self.spec.get("filters", []):
            if f["show_on"] not in on_any:
                raise ValueError(f"Filter '{f['field']}' show_on '{f['show_on']}' is not on the dashboard")
        self._sign()  # + action hints
        for s in self.spec["sheets"]:
            if s.get("subtitle") and not self.block_headers:
                raise ValueError(f"Sheet '{s['name']}': subtitle needs block_headers (Tableau's own worksheet title "
                                 f"has no subtitle line)")
        titles = [(f"Dashboard '{d['name']}'", d.get("title")) for d in self.dashes]
        titles += [(f"Sheet '{s['name']}'", s.get("title")) for s in self.spec["sheets"]]
        for where, t in titles:
            if t and (t.count("**") % 2 or not t.replace("**", "").strip()):
                raise ValueError(f"{where}: title '{t}' is empty or has unbalanced ** (they mark bold key words: "
                                 f"'**Regions** Overview')")
        self.physical = {s["name"]: interact.expand(s, self.params) if s["type"] == interact.BUTTONS
                         else self._expand(s) for s in self.spec["sheets"] if s["type"] != interact.SWITCH}
        self.worksheets = ([p for s in self.spec["sheets"] for p in self.physical.get(s["name"], [])]
                           + shell.sheets(self) + kpi2.sheets(self) + insight.sheets(self))
        for s in interact.switches(self.spec):  # a switch shows its views' sheets (decisions/042)
            self.physical[s["name"]] = [p for n in s["views"].values() for p in self.physical[n]]
        self.part = {p["name"]: p for p in self.worksheets}
        all_names = [p["name"] for p in self.worksheets] + [d["name"] for d in self.dashes]
        dup = sorted({n for n in all_names if all_names.count(n) > 1})
        if dup:
            raise ValueError(f"KPI tile names collide with other sheets/dashboard: {dup}")
        if self.sources:
            self._assign_sources()
        self.filter_owners = set()  # the sheets that own a filter card on some dashboard
        for d in self.dashes:
            with self._on(d):
                self._check_actions(list(_leaves(d["grid"])))
                for _ in self._each_source():  # a source's filters on its sheets (decisions/083)
                    self.filter_owners |= {self._filter_owner(f) for f in self.spec.get("filters", [])
                                           if self._filter_on(f)}

    def _assign_sources(self):
        """Each worksheet's source (decisions/083): a spec sheet's and its parts', an insight line its sheet's; the
        source builders get their worksheets."""
        idx = {s["name"]: i for i, sb in enumerate(self.sources) for s in sb.spec["sheets"]}
        self.src_of = {}
        for s in self.spec["sheets"]:
            self.src_of[s["name"]] = idx[s["name"]]
            for p in self.physical.get(s["name"], []):
                self.src_of[p["name"]] = idx[s["name"]]
        for p in self.worksheets:
            if p["name"] not in self.src_of:
                self.src_of[p["name"]] = self.src_of.get((p.get("sheet") or {}).get("name"), 0)
        for i, sb in enumerate(self.sources):
            sb.worksheets = [p for p in self.worksheets if self.src_of[p["name"]] == i]

    def _check_actions(self, on_dash):
        """The current dashboard's actions (decisions/017); with several sources each source's in its own state, an
        action filtering the sheets of its source sheet's datasource only (decisions/083)."""
        if not self.sources:
            actions.check(self, on_dash)
            return
        acts = actions.actions(self.spec)
        for i in range(len(self.sources)):
            own = [a for a in acts if self.source_of(a["source"]) == i]
            for a in own:
                targets = a.get("targets", "all")
                other = [] if targets == "all" else [t for t in targets if self.source_of(t) != i]
                if other:
                    raise ValueError(f"Action (source '{a['source']}'): targets {other} take another datasource; an "
                                     f"action filters the sheets of its source's datasource (decisions/083)")
            with self._source(i):
                d = self.spec["dashboard"]
                self.spec["dashboard"] = {**d, "actions": own}
                try:
                    actions.check(self, on_dash)
                finally:
                    self.spec["dashboard"] = d

    @staticmethod
    def _expand(s):
        """A kpi sheet with style=tiles becomes one 'tile' worksheet per measure; with style=cards, two per
        measure: the card's value text and its history."""
        if heatmap.margins(s):  # the heatmap, then a bar sheet per margin (decisions/041)
            return heatmap.parts(s)
        if sparkline.line_column(s):  # the registry, then its line spark's sheet (decisions/153)
            return sparkline.parts(s)
        if s["type"] == "donut":  # the donut, then its legend sheet (decisions/044)
            return dualaxis.parts(s)
        if s["type"] != "kpi" or s.get("style", "table") not in ("tiles", "cards"):
            return [s]
        labels = [m.get("label", m["field"]) for m in s["measures"]]
        if len(set(labels)) != len(labels):
            raise ValueError(f"KPI '{s['name']}': tile labels must be unique, got {labels}")
        if cards.is_cards(s):  # value text and history; marker and pill with their options (decisions/037)
            return [p for m, lab in zip(s["measures"], labels) for p in kpi2.parts(s, m, lab)]
        return [{"name": f"{s['name']} · {lab}", "type": "tile", "measure": m, "label": lab, "kpi": s}
                for m, lab in zip(s["measures"], labels)]

    def build_tree(self, data_dir):
        """data_dir: the data's folder in the package; a list, one per source, in a book with several (decisions/083)."""
        with formats.shown_in(self.locale):  # text widths of numbers as the workbook shows them (decisions/085)
            return self._build_tree(data_dir)

    def _build_tree(self, data_dir):
        self.validate_spec()
        dirs = data_dir if isinstance(data_dir, list) else [data_dir]
        for i in self._each_source():
            self.calc_cols.update({n: CalcColumn(c, []) for n, c in reflines.table_calcs(self).items()})  # color flags
            self.calc_cols.update({n: CalcColumn(c, []) for n, c in kpi2.table_calcs(self).items()})  # sparkline labels
            self.data_dir = data_dir = dirs[i]
            self.data_file = (f"{data_dir}/{self.csv_path.stem}.hyper" if self.hyper
                              else f"{data_dir}/{self.csv_path.name}")
        self.shapes, self.registry_cols, self.registry_els, self.heat_styles = {}, {}, {}, {}
        self.axis_fields = {}  # line / area -> its fields: ink.check_axis_title (decisions/066)
        self.heat_columns = []  # heatmaps without margins: heatmap.column_widths (decisions/094)
        self.hist_ranges = {}  # histogram -> (style, range field): distviz.fit_zone (decisions/144)
        self.rings, self.ring_px = {}, {}  # donut -> its ring and hole size formats, sized from its zone (069)
        self.waffles, self.waffle_px = {}, {}  # waffle -> its axes and square size, sized from its zone (polish-26b)
        self.tile_values = {}  # tile grid -> its label's value runs, dropped when a tile is too narrow (decisions/154)
        # the workbook's own locale: numbers, month names in it on any machine (File > Workbook Locale; 085)
        wb = ET.Element("workbook", {"locale": self.locale, "original-version": "18.1", "source-build": SOURCE_BUILD,
                                     "source-platform": "win", "version": "18.1"})
        manifest = _tpl("manifest.xml")
        if not self.filters:
            # Desktop 2025.1 drops this flag on save when the dashboard has no filter card
            # (observed in all three goldens: present with a filter zone, absent without).
            manifest.remove(manifest.find("ZoneBackgroundTransparency"))
        if any((s.get("sort", "none") != "none" and not (registry.is_registry(s) and len(s["rows"]) == 2
                                                         and "top" not in s))  # Top N + text: computed-sort (143)
               or colors.kind(s) in ("plan", "benchmark")  # a manual-sort of Measure Names (decisions/043)
               or funnel.sort(s) == "desc"  # the stages by their value (decisions/159)
               or kpitable.is_table(s)  # a KPI table's columns in the spec order (decisions/106)
               or tilegrid.wall(s)  # a wall's members by the measure (decisions/154)
               or pareto.is_pareto(s)  # always sorted (decisions/157)
               or (registry.is_registry(s) and any(registry.style(c) == "track" for c in s["columns"]))  # 134
               for s in self.worksheets) or self._any_source(  # a computed-sort is written (a nested registry sort
                lambda: any("order" in p for p in self.fields.props.values())):  # is a shelf sort) <manual-sort> (056)
            # Desktop 2025.1 reads <computed-sort> and <manual-sort> only under this flag (it adds it on save);
            # without it check-desktop reports "no declaration found for element 'manual-sort'" (decisions/043).
            sheet_ids = manifest.find("SheetIdentifierTracking")
            manifest.insert(list(manifest).index(sheet_ids) + 1, ET.Element("SortTagCleanup"))
        if any(registry.is_registry(s) and len(s["rows"]) == 2 and s.get("sort", "none") != "none" and "top" not in s
               for s in self.worksheets):  # Top N with a text beside it sorts by computed-sort (decisions/144)
            # <shelf-sort-v2> (nested sort) comes with these flags in the reference that uses it (reference Ads)
            mark = manifest.find("MarkAnimation")
            for flag in ("IntuitiveSorting", "IntuitiveSorting_SP2"):
                manifest.insert(list(manifest).index(mark), ET.Element(flag))
        dates.manifest_flags(manifest, self.filters)
        theme.manifest_flags(manifest, self)
        shell.manifest_flags(manifest, self.spec)
        nav.manifest_flags(manifest, self.spec)  # after the shell's: it adds what is missing
        interact.manifest_flags(manifest, self)  # parameter actions, zone visibility (decisions/042)
        actions.manifest_flags(manifest, self)  # parameter actions, the Show/Hide button (decisions/160)
        maps_mod.manifest_flags(manifest, self.spec)  # decisions/046
        params.manifest_flags(manifest, self)  # a parameter from a field when the workbook opens (decisions/163)
        wb.append(manifest)
        wb.append(_tpl("preferences.xml"))
        theme.workbook_style(self, wb)  # the workbook font (decisions/030)
        dss = _sub(wb, "datasources")
        params.datasource(dss, self)  # 'Parameters' first, as Desktop writes it
        for _ in self._each_source():  # in spec order (decisions/083)
            self.datasource(dss)
        maps_mod.workbook(wb, self.spec)  # <mapsources> (decisions/046)
        for _ in self._each_source(by_name=True):  # by name, as Desktop saves them (decisions/083)
            self.shared_views(wb)
        dashes = [(d, list(_leaves(d["grid"]))) for d in self.dashes]
        actions.write(wb, self, dashes)
        interact.write_actions(wb, self, dashes, sum(len(d.get("actions", [])) for d in self.dashes) + 1)
        actions.write_parameters(wb, self, dashes)  # parameter actions by a click on a mark (decisions/160)
        wss = _sub(wb, "worksheets")
        for s in self.worksheets:
            with self._source_of(s["name"]):
                self.worksheet(wss, s)
                theme.sheet_background(self, wss[-1])  # a colored card shows through its sheets (decisions/194)
        heatmap.column_widths(self)  # from the expected numbers, before the fit (decisions/094)
        self.dashboards(wb)
        barlabels.finish(self, wb)  # zero lines of signed bars, room for the end labels (decisions/087)
        reflines.place_labels(self, wb)  # a line's reference labels apart from its end labels (decisions/184)
        registry.thresholds(self, wb)  # bar_inside: its share from the pane's width, known now (decisions/077)
        self.windows(wb)
        interact.datagraph(wb, self)  # the switches' zone visibility
        return ET.ElementTree(wb)


def build(spec, out_path, base_dir=".", hyper_mb=None):
    """Validate spec, then write a .twbx with the data packaged under Data/<parent dir>/: the CSV, or a .hyper made
    from it when the spec asks for one or the CSV is larger than hyper_mb (default hyper.DEFAULT_THRESHOLD_MB).

    The datasource path in the spec is resolved relative to base_dir (the spec file's folder).
    Nothing is written to out_path unless spec, data checks and the validation gate all pass.
    """
    with design.book_accent(spec):  # dashboard.accent (decisions/137)
        return _build(spec, out_path, base_dir, hyper_mb)


def _build(spec, out_path, base_dir, hyper_mb):
    spec_mod.validate(spec)
    spec = registry.expand(spec)  # a registry template over several dimensions (decisions/039)
    out_path = Path(out_path)
    data = []  # (data path, data dir in the package, hyper) of each source (decisions/083)
    for ds in spec_mod.sources(spec):
        csv_path = Path(base_dir) / ds["path"]
        if not csv_path.is_file():
            raise spec_mod.SpecError(f"Datasource not found: {csv_path}")
        data.append((csv_path, f"Data/{csv_path.parent.name}",
                     ds.get("hyper", not excel.is_excel(csv_path) and hyper_mod.wanted(csv_path, hyper_mb))))
    images = shell.files(nav.primary(spec), base_dir)  # the logo picture (decisions/029), one for all dashboards
    if "datasources" in spec:
        parts = [(sub, path, hyper) for (sub, path, _), (_, _, hyper) in zip(expected_mod.parts(spec, base_dir), data)]
        builder = Builder.multi(spec, parts)
        tree = builder.build_tree([d for _, d, _ in data])
    else:
        (csv_path, data_dir, hyper), = data
        builder = Builder(spec, csv_path, hyper)
        tree = builder.build_tree(data_dir)
    ET.indent(tree, "  ")
    twb_name = out_path.stem + ".twb"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_twb = out_path.with_suffix(".twb.tmp")
    tmp_twbx = out_path.with_suffix(".twbx.tmp")
    tmp_hyper = out_path.with_suffix(".hyper.tmp")
    try:
        tree.write(tmp_twb, encoding="utf-8", xml_declaration=True)
        with zipfile.ZipFile(tmp_twbx, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp_twb, twb_name)
            for _ in builder._each_source():  # each source's data (decisions/083)
                z.write(hyper_mod.write(builder.prof, tmp_hyper) if builder.hyper else builder.csv_path,
                        builder.data_file)
            for arc, src in images:
                z.write(src, arc)
        gate.enforce(tmp_twbx, spec, builder.expected if heatmap.ranged(spec) else None)  # scale range vs data
        os.replace(tmp_twbx, out_path)
    finally:
        tmp_twb.unlink(missing_ok=True)
        tmp_twbx.unlink(missing_ok=True)
        tmp_hyper.unlink(missing_ok=True)
    return out_path


def build_file(spec_path, out_path, hyper_mb=None):
    spec_path = Path(spec_path)
    return build(spec_mod.load(spec_path), out_path, spec_path.parent, hyper_mb)
