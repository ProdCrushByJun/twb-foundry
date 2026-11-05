"""Point edits of a workbook someone else made (todo 16, decisions/161), checked by the gate before it is written.

  python -m tbuilder patch <in.twbx|.twb> <ops.json> -o <out.twbx|.twb> [--resave [-d out/resave]]

ops.json is a list of edits, applied in order (the field and sheet names are the ones shown in Desktop):
  {"op": "add_calc", "name": "Margin", "formula": "SUM([Profit]) / SUM([Sales])"}
  {"op": "copy_sheet", "sheet": "Sales by Order Date", "name": "Sales by Ship Date",
   "replace": {"Order Date": "Ship Date"}}
  {"op": "rename", "field": "Owner Team", "to": "Team"}
  {"op": "sql", "sql": "SELECT ...", "relation": "Custom SQL Query"}
  {"op": "param", "name": "Top Closed", "value": "Lost"}
  {"op": "text", "sheet": "By Team", "part": "cells", "size": 9, "color": "#333333", "align": "left"}
  {"op": "title", "dashboard": "Overview", "line": 1, "text": "Sales", "size": 18, "bold": true}
  {"op": "block", "dashboard": "Overview", "zone": "By Team", "padding": 12, "background": "#ffffff"}
  {"op": "number_format", "field": "Sales", "format": "currency_k"}
  {"op": "marks", "sheet": "Trend", "color": "#4e79a7", "size": 2, "opacity": 80}
  {"op": "lines", "sheet": "*", "grid": false, "zero": true, "axis": false, "dividers": true}
  {"op": "table_size", "sheet": "Detail", "row_height": 30, "column_width": 80, "header_width": 120}
  {"op": "axis", "sheet": "Trend", "field": "Sales", "show": false, "title": "Revenue"}
  {"op": "labels", "sheet": "By Team", "show": true, "size": 9, "color": "#333333", "bold": false}
  {"op": "series_colors", "field": "Region", "colors": {"East": "#4e79a7", "West": "#e15759"}}
  {"op": "tooltip", "sheet": "By Team", "text": "<Owner Team>: <Closures> closures", "size": 9}
  {"op": "legend", "sheet": "By Team", "show": false, "title": false, "size": 9}
  {"op": "filter_view", "dashboard": "Overview", "field": "Region", "mode": "single_dropdown"}
  {"op": "dashboard_size", "dashboard": "Overview", "width": 1400, "height": 900}
  {"op": "color_scale", "sheet": "Profit", "colors": ["#ff5c60", "#f1f1f1", "#3ea8a6"], "center": 0, "min": -50, "max": 50}
  {"op": "reference_line", "sheet": "Regions", "color": "#333333", "width": 2, "pattern": "solid", "label": "Goal <Value>"}
  {"op": "sheet_title", "sheet": "By Team", "show": false}
  {"op": "map_style", "sheet": "States", "style": "dark", "washout": 20}
Optional keys: "datasource" (caption or name; needed when the field is in several), add_calc "datatype" (inferred
when the formula's fields allow it), sql "relation" (needed when the datasource has several Custom SQL relations).

What each edit touches:
- add_calc: one <column><calculation/></column> in the datasource. A formula field must exist; with an extract, a
  source column must be in the extract (XML cannot add data to a Hyper file: the calc would not compute).
- copy_sheet: a new worksheet and its window right after the source's; new simple-id uuids; each replaced field
  swapped in the copy's dependencies, shelves, filters, encodings and titles (same datatype only). The copy is not
  placed on a dashboard. Calcs that use the old field are not rewritten.
- rename: the caption of the field in the datasource and in every dependency copy (sheets, dashboards, shared
  views); formulas and shelves reference the internal name and do not change.
- sql: the text of the Custom SQL relation(s) of that name. With an extract the new columns arrive only after an
  extract refresh in Desktop (reported).
- param: the current value of a parameter (value, formula, alias) in the Parameters datasource and its dependency
  copies; a list parameter takes a member's value or its alias, a range one a value within min..max.
- text (decisions/189): a sheet's table style. "sheet" a name or "*"; "part" all (default) / cells / headers; font,
  size, color, bold, align (cells and headers only). part all also sets those formats where cells and headers have
  their own, which would win.
- title: a formatted text's runs. "sheet" a name or "*" (a sheet with Tableau's automatic title has none to edit), or
  "dashboard" with an optional "zone" (a text zone's id or "*"; without it the title object, else the largest text).
  font, size, color, bold, align; "line" (1-based) limits them to one line, "text" replaces the words of that line.
- block: a dashboard zone's zone-style. "zone" a sheet's name (the card around it in the card theme, else its own
  zone), a zone id (exactly that zone) or "*" (every card, and the sheets and texts outside cards); padding,
  margin, margin_top / right / bottom / left, background, border_color, border_style, border_width. "canvas" is the
  dashboard's own background. Device layouts keep their own.
- number_format: a number field's default-format and its dependency copies, so labels, axes, tooltips and KPI text
  agree; a sheet's own text-format on that field follows, a custom one ('*...') stays and is reported. "format" a
  preset, a format object (formats.py) or Desktop's own string. With "sheet" only that sheet changes, by text-format
  on its cells, labels and axis (decisions/192).
- marks (decisions/190): each pane's mark-color, size (Desktop's slider units) and mark-transparency (opacity 0-100
  percent). "sheet" a name or "*"; "pane" (1-based) one pane of a dual axis. A sheet that colors or sizes marks by a
  field keeps them; that is reported.
- lines: grid, zero, axis, dividers: false writes the generator's off form, true takes it off (Tableau's default
  line; dividers: rows only).
- table_size: row_height and header_width on the innermost discrete field of Rows, column_width on that of Columns;
  "field" picks another. Entire-view would squeeze them, so a sheet in it on a dashboard takes the fit that keeps the
  size (decisions/190), which is reported.
- axis: a continuous field's axis on Rows or Columns; without "field" every axis of the sheet. show, title ("" none,
  null automatic); a title takes off a fixed axis width, which would cut it off.
- labels (decisions/191): each pane's mark-labels-show and datalabel fonts; the runs of a sheet's own label too.
- series_colors: the datasource's palette map of a field some sheet colors by, so every such sheet agrees; a member is
  its value in the data, not its alias. One the map does not have yet is added, and with an existing map reported. A
  continuous scale is refused. The map's column-instance is declared in the datasource: Desktop drops it otherwise.
- tooltip: show false (an empty customized tooltip), show true (Tableau's automatic one), text with <Field> for a field
  on the sheet, fonts of a tooltip that has text.
- legend: on every dashboard the sheet's color legend: show (hidden-by-user), title (show-title); fonts in the sheet.
- filter_view: the card of a value filter: checkdropdown, single_dropdown, multi_list, single_list. A card for one value
  is refused while a sheet selects several: the numbers would change.
- dashboard_size: a fixed width and height; zones are shares and follow, a fixed-size zone keeps its pixels (reported).
- color_scale (decisions/192): the sheet's own scale of a continuous field on Color: colors (2, or 3 with a center),
  min, max, center. Tableau's automatic scale needs "colors" to be replaced.
- reference_line: each line's stroke by its id: color, width (0 hides it), pattern, label_size, label_color; "line"
  (1-based) picks one; label a text ("<Value>" for the number), true for the value, false for none.
- sheet_title: show-title of the sheet's zones, on every dashboard or on "dashboard". A block's title in a text zone is
  a separate zone: the title op edits it.
- map_style: a map's map-style (light, normal, dark) and washout in percent.
A value off the design system (font, size, color, spacing) is a warning, not a refusal; a value that is not a value
(a color that is not #rrggbb, a negative size) is a refusal. Style ops can be applied again to a rebuilt book.

What never changes: everything else. The edits are byte splices (restyle.parse spans), invariant() proves every
worksheet, dashboard, window, shared view and datasource the ops did not touch keeps its exact bytes, and every
other package member (extract, images, data files) is copied byte for byte. The gate runs on the input and on the
output: a finding the input does not have blocks the file (the gate's own rules are the project's, so a foreign
book has findings of its own; only new ones count). After a style op, a new finding of the design rules only
(STYLE_CHECKS) is a warning: the user chose that value. After every style op the XML outside style nodes and run fonts
is proved equal.
"""
import copy
import json
import re
import shutil
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import fit, formats
from . import formula as fx
from .build import DECLUTTER
from .design import COLOR, FONT, FONT_CARDS, SHEET_TEXT_PT, SPACE
from .restyle import (DASH_TITLE_MIN_PT, FONT_FAMILY, STYLE_TAGS, _append_child, _insert, _replace, _set_format, _start,
                      _twb_name, _zone_set, apply, parse, read_twb, serialize)

PARAMS = "Parameters"
NUMERIC = ("integer", "real")
DATES = ("date", "datetime")
TYPES = NUMERIC + ("string", "boolean") + DATES
UNITS = {"datasource": "datasources", "worksheet": "worksheets", "dashboard": "dashboards", "window": "windows",
         "shared-view": "shared-views"}  # top-level parts of a .twb that the invariant compares by name
UUID_NS = uuid.UUID("5f0c7b2e-1d61-4a61-9c1b-2f7e1e0d0161")
NEW_CALC = "patch: new calc"  # the new calc's name inside the CalcSet that infers its datatype


@dataclass
class Report:
    lines: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    copies: dict = field(default_factory=dict)  # new sheet -> source sheet
    style: bool = False  # a style op ran: the gate's design findings are warnings

    def text(self):
        return "\n".join(self.lines + [f"WARNING: {w}" for w in self.warnings])


@dataclass
class Field:
    name: str  # internal name in brackets: [Sales], [Calculation_1...]
    caption: str  # the name Desktop shows
    datatype: str
    el: object = None  # the datasource's <column>; None for a source column without one

    @property
    def calc(self):
        return self.el is not None and self.el.find("calculation") is not None


def fields(ds):
    """A datasource's fields by internal name: the source columns of its metadata-records and its <column>s."""
    out = {}
    for rec in ds.iter("metadata-record"):
        n = rec.findtext("local-name")
        if rec.get("class") == "column" and n and n not in out:
            out[n] = Field(n, n[1:-1], rec.findtext("local-type") or "")
    for col in ds.findall("column"):
        n = col.get("name")
        if not n or "].[" in n:  # [__tableau_internal_object_id__].[...]
            continue
        dtype = col.get("datatype") or (out[n].datatype if n in out else "")
        out[n] = Field(n, col.get("caption") or n[1:-1], dtype, col)
    return out


def lookup(flds, text):
    """The field shown as text (its caption), else the one whose internal name is [text]; None if neither."""
    hits = [f for f in flds.values() if f.caption == text]
    if len(hits) > 1:
        raise ValueError(f"field '{text}' is ambiguous: {[f.name for f in hits]}")
    return hits[0] if hits else flds.get(f"[{text}]")


# ---- the document ----------------------------------------------------------------------------------------------
def _datasources(doc):
    return doc.root.findall("datasources/datasource")


def _ds_label(ds):
    return ds.get("caption") or ds.get("name")


def _pick_ds(doc, op, names, what):
    """The datasource of an op: by its "datasource" key, else the one (not Parameters) that has every name."""
    cands = [d for d in _datasources(doc) if d.get("name") != PARAMS]
    want = op.get("datasource")
    if want is not None:
        cands = [d for d in cands if want in (d.get("caption"), d.get("name"))]
        if not cands:
            raise ValueError(f"{what}: no datasource '{want}' (have {[_ds_label(d) for d in _datasources(doc)]})")
        return cands[0]
    hits = [d for d in cands if all(lookup(fields(d), n) for n in names)]
    if len(hits) != 1:
        found = "no datasource has" if not hits else f"datasources {[_ds_label(d) for d in hits]} all have"
        raise ValueError(f"{what}: {found} {names}; set \"datasource\"")
    return hits[0]


def _params(doc):
    ds = next((d for d in _datasources(doc) if d.get("name") == PARAMS), None)
    return [] if ds is None else ds.findall("column")


def _param(doc, text):
    return next((p for p in _params(doc) if text in (p.get("caption"), (p.get("name") or "")[1:-1])), None)


def _unit(doc, el):
    """(kind, name) of the top-level part holding el (UNITS), or None."""
    while el is not None:
        if el.tag in UNITS and doc.parent.get(id(el)) is not None and doc.parent[id(el)].tag == UNITS[el.tag]:
            return el.tag, el.get("name")
        el = doc.parent.get(id(el))
    return None


def _named(doc, kind, name):
    return next((e for e in doc.root.findall(f"{UNITS[kind]}/{kind}") if e.get("name") == name), None)


def _indent(doc, el):
    s = doc.span[id(el)][0]
    ws = doc.raw[doc.raw.rfind(b"\n", 0, s):s]
    return ws if ws and not ws.strip() else b"\n"


def _swap(doc, old, new):
    doc.edits.append((*doc.span[id(old)], serialize(new).encode("utf-8")))


def _insert_after(doc, ref, new):
    end = doc.span[id(ref)][1]
    doc.edits.append((end, end, _indent(doc, ref) + serialize(new).encode("utf-8")))


def _sorted_attrs(el):
    """Attributes in alphabetical order, as Desktop writes them."""
    items = sorted(el.attrib.items())
    el.attrib.clear()
    el.attrib.update(items)
    return el


def _column_anchor(ds):
    """The element a new datasource <column> goes after: the last <column>, else <aliases>, else <connection>."""
    for tag in ("column", "aliases", "connection"):
        found = ds.findall(tag)
        if found:
            return found[-1]
    raise ValueError(f"datasource '{_ds_label(ds)}' has no <connection>")


def _extract_columns(ds):
    """Local names of the extract's columns, or None when the datasource has no (described) extract."""
    ex = ds.find("extract")
    if ex is None or ex.get("enabled") == "false":
        return None
    names = {r.findtext("local-name") for r in ex.iter("metadata-record") if r.get("class") == "column"}
    return names or None


def _role(datatype, agg):
    if agg or datatype in NUMERIC:
        return "measure", "quantitative"
    return "dimension", "ordinal" if datatype in DATES else "nominal"


# ---- add_calc ----------------------------------------------------------------------------------------------------
def _translate(doc, flds, src, what):
    """A formula with Desktop names -> (the formula as stored: internal names, [raw source columns])."""
    try:
        fx.parse(src)
        toks = fx.tokenize(src)
    except fx.FormulaError as e:
        raise ValueError(f"{what}: {e}") from None
    out, raw = src, []
    for t in reversed(toks):
        if t.kind not in ("field", "param"):
            continue
        inner = t.text[len("[Parameters].["):-1] if t.kind == "param" else t.text[1:-1]
        f = lookup(flds, inner) if t.kind == "field" else None
        if f is not None:
            repl = f.name
            if not f.calc:
                raw.append(f.name)
        else:
            p = _param(doc, inner)
            if p is None:
                raise ValueError(f"{what}: unknown field {t.text}")
            repl = f"[{PARAMS}].{p.get('name')}"
        out = out[:t.start] + repl + out[t.end:]
    return out, raw


def _infer(flds, xml_formula):
    """(datatype, aggregate?) of a stored formula by formula.CalcSet over the source columns and the calcs it uses."""
    specs, todo, seen = [], [xml_formula], set()
    while todo:
        for t in fx.tokenize(todo.pop()):
            f = flds.get(t.text) if t.kind == "field" else None
            if f is not None and f.calc and f.name not in seen:
                seen.add(f.name)
                body = f.el.find("calculation").get("formula") or ""
                specs.append({"name": f.name[1:-1], "formula": body})
                todo.append(body)
    types = {f.name[1:-1]: f.datatype for f in flds.values() if not f.calc and f.datatype in TYPES}
    c = fx.CalcSet(specs + [{"name": NEW_CALC, "formula": xml_formula}], types)[NEW_CALC]
    return c.datatype, c.is_agg


def add_calc(doc, op, rep, touched, added):
    name, src = op["name"], op["formula"]
    what = f"add_calc '{name}'"
    names = [t.text[1:-1] for t in _tokens(src, what) if t.kind == "field"]
    ds = _pick_ds(doc, op, [n for n in names if _param(doc, n) is None], what)
    flds = fields(ds)
    if lookup(flds, name) is not None:
        raise ValueError(f"{what}: datasource '{_ds_label(ds)}' already has a field '{name}'")
    xml_formula, raw = _translate(doc, flds, src, what)
    extract = _extract_columns(ds)
    missing = [n for n in raw if extract is not None and n not in extract]
    if missing:
        raise ValueError(f"{what}: {missing} not in the extract of '{_ds_label(ds)}': the calc would not compute "
                         f"until the extract is refreshed in Desktop")
    dtype, agg = op.get("datatype"), False
    try:
        dtype_inferred, agg = _infer(flds, xml_formula)
    except fx.FormulaError as e:
        if dtype is None:
            raise ValueError(f"{what}: cannot infer the datatype ({e}); set \"datatype\"") from None
    else:
        if dtype is not None and dtype != dtype_inferred:
            raise ValueError(f"{what}: datatype {dtype} given, the formula gives {dtype_inferred}")
        dtype = dtype_inferred
    if dtype not in TYPES:
        raise ValueError(f"{what}: datatype {dtype!r} (known: {sorted(TYPES)})")
    cid = fx.calc_id(f"{_ds_label(ds)}/{name}")
    if f"[{cid}]" in flds:
        raise ValueError(f"{what}: internal name {cid} is taken")
    role, typ = _role(dtype, agg)
    col = ET.Element("column", {"caption": name, "datatype": dtype, "name": f"[{cid}]", "role": role, "type": typ})
    ET.SubElement(col, "calculation", {"class": "tableau", "formula": xml_formula})
    _insert_after(doc, _column_anchor(ds), col)
    touched.add(("datasource", ds.get("name")))
    rep.lines.append(f"add_calc: '{name}' = {xml_formula} ({dtype} {role}, [{cid}]) in '{_ds_label(ds)}'")


def _tokens(src, what):
    try:
        return fx.tokenize(src)
    except fx.FormulaError as e:
        raise ValueError(f"{what}: {e}") from None


# ---- copy_sheet --------------------------------------------------------------------------------------------------
def _new_uuid(*parts):
    return "{" + str(uuid.uuid5(UUID_NS, "/".join(parts))).upper() + "}"


def _field_subs(old, new):
    """Text substitutions of a field swap: its instances [pfx:old:sfx] and the bare [old]."""
    o, n = re.escape(old[1:-1]), new[1:-1].replace("\\", "\\\\")
    return [(re.compile(r"\[((?:[^\[\]:]+:)+)" + o + r"((?::[^\[\]:]+)+)\]"), r"[\g<1>" + n + r"\g<2>]"),
            (re.compile(re.escape(old)), new.replace("\\", "\\\\"))]


def _rewrite(el, subs, skip):
    """Apply subs to every attribute and text under el, except inside the elements in skip (definitions)."""
    if id(el) in skip:
        return
    for k, v in el.attrib.items():
        for rx, r in subs:
            v = rx.sub(r, v)
        el.attrib[k] = v
    if el.text:
        for rx, r in subs:
            el.text = rx.sub(r, el.text)
    for c in el:
        _rewrite(c, subs, skip)


def _swap_in_deps(doc, deps, fo, fn):
    """In a copied datasource-dependencies: the column of fo replaced by fn's (once), duplicate instances dropped."""
    cols = deps.findall("column")
    old = next(c for c in cols if c.get("name") == fo.name)
    i = list(deps).index(old)
    deps.remove(old)
    if not any(c.get("name") == fn.name for c in cols):
        if fn.el is not None:
            new = copy.deepcopy(fn.el)
        else:
            new = ET.Element("column", {"datatype": fn.datatype, "name": fn.name, "role": old.get("role"),
                                        "type": old.get("type")})
        new.tail = old.tail
        deps.insert(i, new)


def _shared_instances(doc, ds, fo):
    """The column-instances of fo that a shared view (a filter on every sheet of the datasource) filters on."""
    pattern = _field_subs(fo.name, fo.name)[0][0]
    out = []
    for sv in doc.root.findall("shared-views/shared-view"):
        if sv.get("name") != ds.get("name"):
            continue
        filtered = {f.get("column") for f in sv.iter("filter")}
        out += [ci for ci in sv.iter("column-instance") if pattern.fullmatch(ci.get("name") or "")
                and f"[{ds.get('name')}].{ci.get('name')}" in filtered]
    return out


def _append(deps, el):
    """el as the last child of deps (indented as its siblings), unless deps has one of that name already."""
    if any(c.tag == el.tag and c.get("name") == el.get("name") for c in deps):
        return
    last = deps[-1]
    el.tail, last.tail = last.tail, deps.text
    deps.append(el)


def _dedupe_instances(deps):
    seen = set()
    for ci in deps.findall("column-instance"):
        if ci.get("name") in seen:
            deps.remove(ci)
        seen.add(ci.get("name"))


def copy_sheet(doc, op, rep, touched, added):
    src, name, replace = op["sheet"], op["name"], op.get("replace") or {}
    what = f"copy_sheet '{src}' -> '{name}'"
    ws = _named(doc, "worksheet", src)
    if ws is None:
        raise ValueError(f"{what}: no worksheet '{src}'")
    if any(e.get("name") == name for k in ("worksheet", "dashboard") for e in doc.root.findall(f"{UNITS[k]}/{k}")):
        raise ValueError(f"{what}: a sheet or dashboard '{name}' exists")
    win = next((w for w in doc.root.findall("windows/window") if w.get("name") == src
                and w.get("class") == "worksheet"), None)
    new_ws = copy.deepcopy(ws)
    new_ws.set("name", name)
    new_ws.tail = None
    for r in new_ws.findall("repository-location"):  # Server/Public identity of the source sheet
        new_ws.remove(r)
    if new_ws.find("simple-id") is not None:
        new_ws.find("simple-id").set("uuid", _new_uuid("worksheet", name))
    new_win = None
    if win is not None:
        new_win = copy.deepcopy(win)
        new_win.set("name", name)
        new_win.attrib.pop("maximized", None)
        new_win.tail = None
        if new_win.find("simple-id") is not None:
            new_win.find("simple-id").set("uuid", _new_uuid("window", name))
    ds_by_name = {d.get("name"): d for d in _datasources(doc)}
    for old_text, new_text in replace.items():
        swapped = []
        for deps in new_ws.iter("datasource-dependencies"):
            ds = ds_by_name.get(deps.get("datasource"))
            flds = fields(ds) if ds is not None else {}
            fo = lookup(flds, old_text)
            if fo is None or not any(c.get("name") == fo.name for c in deps.findall("column")):
                continue
            fn = lookup(flds, new_text)
            if fn is None:
                raise ValueError(f"{what}: no field '{new_text}' in '{_ds_label(ds)}'")
            if fn.datatype != fo.datatype:
                raise ValueError(f"{what}: '{old_text}' is {fo.datatype}, '{new_text}' is {fn.datatype}: a swap "
                                 f"keeps the sheet's derivations only between fields of one datatype")
            swapped.append((deps, ds, fo, fn))
        if not swapped:
            raise ValueError(f"{what}: the sheet does not use '{old_text}'")
        for deps, ds, fo, fn in swapped:
            old_col = copy.deepcopy(next(c for c in deps.findall("column") if c.get("name") == fo.name))
            _swap_in_deps(doc, deps, fo, fn)
            subs = _field_subs(f"[{ds.get('name')}].{fo.name}", f"[{ds.get('name')}].{fn.name}") \
                + _field_subs(fo.name, fn.name)
            shared = _shared_instances(doc, ds, fo)
            skip = {id(c) for d in new_ws.iter("datasource-dependencies") for c in d.findall("column")}
            skip |= {id(c) for sl in new_ws.iter("slices") for c in sl.findall("column")
                     if c.text in {f"[{ds.get('name')}].{ci.get('name')}" for ci in shared}}
            _rewrite(new_ws, subs, skip)
            calcs = [c.find("calculation").get("formula") or "" for c in deps.findall("column")
                     if c.find("calculation") is not None]
            if shared or any(fo.name in f for f in calcs):
                # a shared filter on the old field still applies to the copy, a calc of the copy still reads it:
                # Desktop keeps it declared
                _append(deps, old_col)
                for ci in shared:
                    _append(deps, copy.deepcopy(ci))
            if new_win is not None:
                _rewrite(new_win, subs, set())
            _dedupe_instances(deps)
    _insert_after(doc, ws, new_ws)
    added.add(("worksheet", name))
    if new_win is not None:
        _insert_after(doc, win, new_win)
        added.add(("window", name))
    rep.copies[name] = src
    swaps = ", ".join(f"{a} -> {b}" for a, b in replace.items()) or "as is"
    rep.lines.append(f"copy_sheet: '{src}' -> '{name}' ({swaps}); not placed on a dashboard")


# ---- rename ------------------------------------------------------------------------------------------------------
def rename(doc, op, rep, touched, added):
    old_text, to = op["field"], op["to"]
    what = f"rename '{old_text}' -> '{to}'"
    if op.get("datasource") == PARAMS or (op.get("datasource") is None and _param(doc, old_text) is not None
                                           and not any(lookup(fields(d), old_text) for d in _datasources(doc)
                                                       if d.get("name") != PARAMS)):
        ds = next(d for d in _datasources(doc) if d.get("name") == PARAMS)
    else:
        ds = _pick_ds(doc, op, [old_text], what)
    flds = fields(ds)
    f = lookup(flds, old_text)
    if f is None:
        raise ValueError(f"{what}: no field '{old_text}' in '{_ds_label(ds)}'")
    clash = lookup(flds, to)
    if clash is not None:
        raise ValueError(f"{what}: '{_ds_label(ds)}' already has a field '{to}' ({clash.name})")
    copies = [c for deps in doc.root.iter("datasource-dependencies") if deps.get("datasource") == ds.get("name")
              for c in deps.findall("column") if c.get("name") == f.name]
    if f.el is not None:
        new = copy.deepcopy(f.el)
        new.set("caption", to)
        _swap(doc, f.el, _sorted_attrs(new))
    else:  # a source column shown by its own name: Desktop declares the caption on a new datasource <column>
        role, typ = (copies[0].get("role"), copies[0].get("type")) if copies else _role(f.datatype, False)
        _insert_after(doc, _column_anchor(ds), ET.Element("column", {
            "caption": to, "datatype": f.datatype, "name": f.name, "role": role, "type": typ}))
    touched.add(("datasource", ds.get("name")))
    for c in copies:
        new = copy.deepcopy(c)
        new.set("caption", to)
        _swap(doc, c, _sorted_attrs(new))
        touched.add(_unit(doc, c))
    rep.lines.append(f"rename: '{old_text}' ({f.name}) -> '{to}' in '{_ds_label(ds)}' and {len(copies)} "
                     f"dependency copies")


# ---- sql ---------------------------------------------------------------------------------------------------------
def sql(doc, op, rep, touched, added):
    what = "sql"
    want = op.get("relation")
    found = [(d, r) for d in _datasources(doc) for r in d.iter("relation")
             if r.get("type") == "text" and (want is None or r.get("name") == want)
             and op.get("datasource") in (None, d.get("caption"), d.get("name"))]
    if not found:
        raise ValueError(f"{what}: no Custom SQL relation" + (f" '{want}'" if want else ""))
    keys = {(d.get("name"), r.get("name")) for d, r in found}
    if len(keys) > 1:
        raise ValueError(f"{what}: several Custom SQL relations {sorted(keys)}; set \"relation\" / \"datasource\"")
    for d, r in found:
        if len(r):
            raise ValueError(f"{what}: relation '{r.get('name')}' has child elements; not a plain Custom SQL text")
        new = copy.deepcopy(r)
        new.text = op["sql"]
        _swap(doc, r, new)
    ds = found[0][0]
    touched.add(("datasource", ds.get("name")))
    rep.lines.append(f"sql: relation '{found[0][1].get('name')}' of '{_ds_label(ds)}' ({len(found)} copies)")
    if ds.find("extract") is not None or any(c.get("class") == "hyper" for c in ds.iter("connection")):
        rep.warnings.append(f"sql: '{_ds_label(ds)}' reads an extract: the new SQL takes effect, and new columns "
                            f"appear, only after an extract refresh in Desktop")


# ---- param -------------------------------------------------------------------------------------------------------
def _literal(datatype, value, what):
    v = str(value)
    if datatype == "string":
        return '"' + v.replace('"', '""') + '"'
    if datatype == "boolean":
        if v.lower() not in ("true", "false"):
            raise ValueError(f"{what}: {v!r} is not true / false")
        return v.lower()
    if datatype in NUMERIC:
        try:
            n = int(v) if datatype == "integer" else float(v)
        except ValueError:
            raise ValueError(f"{what}: {v!r} is not {datatype}") from None
        return str(n) if datatype == "integer" else v
    if datatype in DATES:
        lit = f"#{v}#"
        try:
            fx.date_literal(lit)
        except fx.FormulaError as e:
            raise ValueError(f"{what}: {e}") from None
        return lit
    raise ValueError(f"{what}: parameter datatype {datatype!r} not supported")


def _param_value(p, value, what):
    """(literal, alias or None) of a parameter's new value, within its domain."""
    dtype, domain = p.get("datatype"), p.get("param-domain-type")
    aliases = {a.get("key"): a.get("value") for a in p.findall("aliases/alias")}
    members = [m.get("value") for m in p.findall("members/member")]
    if domain == "list":
        lit = None
        try:
            lit = _literal(dtype, value, what)
        except ValueError:
            pass
        if lit not in members:
            by_alias = [k for k, a in aliases.items() if a == str(value) and k in members]
            if len(by_alias) != 1:
                raise ValueError(f"{what}: {value!r} is not a member (values {members}, aliases "
                                 f"{[aliases.get(m, m) for m in members]})")
            lit = by_alias[0]
        return lit, aliases.get(lit)
    lit = _literal(dtype, value, what)
    rng = p.find("range")
    if domain == "range" and rng is not None:
        key = (lambda s: float(s)) if dtype in NUMERIC else (lambda s: s)
        lo, hi = rng.get("min"), rng.get("max")
        if (lo is not None and key(lit) < key(lo)) or (hi is not None and key(lit) > key(hi)):
            raise ValueError(f"{what}: {value!r} is outside {lo}..{hi}")
    return lit, aliases.get(lit)


def param(doc, op, rep, touched, added):
    what = f"param '{op['name']}'"
    p = _param(doc, op["name"])
    if p is None:
        raise ValueError(f"{what}: no parameter (have {[c.get('caption') or c.get('name') for c in _params(doc)]})")
    lit, alias = _param_value(p, op["value"], what)
    copies = [c for deps in doc.root.iter("datasource-dependencies") if deps.get("datasource") == PARAMS
              for c in deps.findall("column") if c.get("name") == p.get("name")]
    for el in [p] + copies:
        new = copy.deepcopy(el)
        new.set("value", lit)
        if new.find("calculation") is not None:
            new.find("calculation").set("formula", lit)
        if "alias" in new.attrib:
            if alias is None:
                del new.attrib["alias"]
            else:
                new.set("alias", alias)
        _swap(doc, el, new)
        touched.add(_unit(doc, el))
    zones = _switch_zones(doc, p.get("name"), lit, touched)
    rep.lines.append(f"param: '{op['name']}' = {lit} ({len(copies)} dependency copies"
                     + (f", {zones} zones shown / hidden by it" if zones else "") + ")")


def _visible_by(doc, fname, pname, lit):
    """Whether a zone-visibility field is true at open with pname = lit; None if the field does not use pname:
    the parameter itself (boolean) or a calc [Parameters].[p] = "x" (gate.PARAM_EQ, decisions/082)."""
    from .gate import INSTANCE, PARAM_EQ
    if fname == f"[{PARAMS}].{pname}":
        return lit == "true"
    m = INSTANCE.fullmatch(fname)
    ds = next((d for d in _datasources(doc) if m and d.get("name") == m.group(1)), None)
    col = next((c for c in ds.findall("column") if c.get("name") == m.group(2)), None) if ds is not None else None
    eq = PARAM_EQ.fullmatch(col.find("calculation").get("formula", "")) \
        if col is not None and col.find("calculation") is not None else None
    return eq.group(2) == lit if eq and eq.group(1) == pname else None


def _switch_zones(doc, pname, lit, touched):
    """Dynamic zone visibility driven by the parameter: hidden-by-user of each such container and the zones in it
    as Desktop saves them for the new value (gate check_interactivity). Returns how many zones changed."""
    graph = doc.root.find("datagraph/graph")
    if graph is None:
        return 0
    fields_ = {n.get("value-output-guid"): n.get("fieldname", "") for n in graph.iter("single-value-field-node")}
    edges = {e.get("to"): e.get("from") for e in graph.iter("edge")}
    dashes = {d.find("simple-id").get("uuid"): d for d in doc.root.iter("dashboard")
              if d.find("simple-id") is not None}
    nodes = graph.findall("nodes/dashboard-zone-visibility-node")
    changed = 0
    for n in nodes:
        visible = _visible_by(doc, fields_.get(edges.get(n.get("visibility-input-guid")), ""), pname, lit)
        db = dashes.get(n.get("dashboard-identifier"))
        if visible is None or db is None:
            continue
        ids = {m.get("zone-id") for m in nodes if m.get("dashboard-identifier") == n.get("dashboard-identifier")}
        box = next((z for z in db.iter("zone") if z.get("id") == n.get("zone-id")), None)
        for z in ([] if box is None else box.iter("zone")):
            owner = z  # the zone's nearest visibility container
            while owner is not None and owner.get("id") not in ids:
                owner = doc.parent.get(id(owner))
            if owner is not box or (z.get("hidden-by-user") == "true") != visible:
                continue
            new = copy.copy(z)
            if visible:
                del new.attrib["hidden-by-user"]
            else:
                new.set("hidden-by-user", "true")
            closed = doc.end_tag_start(z) is None
            doc.edits.append((doc.span[id(z)][0], doc.start_tag_end(z), _start(new, closed).encode("utf-8")))
            touched.add(_unit(doc, z))
            changed += 1
    return changed


# ---- style: text, title, block, number_format (decisions/189) -------------------------------------------------------
TEXT_PARTS = {"all": "worksheet", "cells": "cell", "headers": "label"}  # the Format pane's Worksheet, Pane, Header
TEXT_ELEMENTS = ("cell", "label", "header")  # their own font formats would win over the worksheet's: "all" sets them
ALIGN_RUN = {"left": "0", "center": "1", "right": "2"}
BORDER_STYLES = ("none", "solid", "dashed", "dotted")
BLOCK_KEYS = {"padding": "padding", "margin": "margin", "margin_top": "margin-top", "margin_right": "margin-right",
              "margin_bottom": "margin-bottom", "margin_left": "margin-left", "background": "background-color",
              "border_color": "border-color", "border_style": "border-style", "border_width": "border-width"}
FONT_KEYS = ("font", "size", "color", "bold", "align")
LINE_BREAK_RUN = "\u00c6\n"
RUN_ATTRS = ("fontname", "fontsize", "fontcolor", "bold", "fontalignment")
# What a style edit may break on the gate's design rules only (the user chose the value): a warning, not a refusal.
# Everything else the gate finds still blocks the file.
STYLE_CHECKS = ("theme", "spacing", "contrast", "widths", "fit", "fit-crowded", "legend-below", "bar-labels")


def _keys(op, allowed, what):
    extra = sorted(set(op) - set(allowed) - {"op"})
    if extra:
        raise ValueError(f"{what}: unknown keys {extra} (known: {sorted(allowed)})")


def _hex(value, what):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"{what}: color {value!r} is not #rrggbb")
    return value.lower()


def _px(value, what, low=0):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= 500:
        raise ValueError(f"{what}: {value!r} is not a whole number from {low} to 500")
    return str(value)


def _font_values(op, what, rep):
    """The checked font keys of an op; a value off the design system is a warning (the user asked for it)."""
    out = {k: op[k] for k in FONT_KEYS if k in op}
    if "font" in out:
        if not isinstance(out["font"], str) or not out["font"].strip():
            raise ValueError(f"{what}: font {out['font']!r} is not a name")
        if out["font"] != FONT_FAMILY:
            rep.warnings.append(f"{what}: font '{out['font']}' is not the project's {FONT_FAMILY}; a viewer without "
                                f"it sees a substitute")
    if "size" in out:
        _px(out["size"], f"{what}: size", 1)
        if out["size"] not in {*FONT.values(), *FONT_CARDS.values(), SHEET_TEXT_PT}:
            rep.warnings.append(f"{what}: size {out['size']} is not on the design scale")
    if "color" in out:
        out["color"] = _hex(out["color"], what)
        if out["color"] not in {v.lower() for v in COLOR.values()}:
            rep.warnings.append(f"{what}: color {out['color']} is not a design token")
    if not isinstance(out.get("bold", False), bool):
        raise ValueError(f"{what}: bold must be true or false")
    if out.get("align", "left") not in ALIGN_RUN:
        raise ValueError(f"{what}: align {out['align']!r} is not one of {sorted(ALIGN_RUN)}")
    return out


def _worksheets(doc, name, what):
    all_ = doc.root.findall("worksheets/worksheet")
    if name == "*":
        return all_
    hits = [w for w in all_ if w.get("name") == name]
    if not hits:
        raise ValueError(f"{what}: no sheet '{name}' (have {[w.get('name') for w in all_]})")
    return hits


def _dashboard(doc, name, what):
    all_ = doc.root.findall("dashboards/dashboard")
    hit = next((d for d in all_ if d.get("name") == name), None)
    if hit is None:
        raise ValueError(f"{what}: no dashboard '{name}' (have {[d.get('name') for d in all_]})")
    return hit


def style_text(doc, op, rep, touched, added):
    """The text of a sheet's chart: its Format pane fonts, in the sheet's table style."""
    what = f"text '{op['sheet']}'"
    _keys(op, ("sheet", "part", *FONT_KEYS), what)
    part = op.get("part", "all")
    if part not in TEXT_PARTS:
        raise ValueError(f"{what}: part {part!r} is not one of {sorted(TEXT_PARTS)}")
    vals = _font_values(op, what, rep)
    if not vals:
        raise ValueError(f"{what}: nothing to set (keys: {', '.join(FONT_KEYS)})")
    if part == "all" and "align" in vals:
        raise ValueError(f"{what}: align needs a part, 'cells' or 'headers'")
    fmt = {}
    if "font" in vals:
        fmt["font-family"] = vals["font"]
    if "size" in vals:
        fmt["font-size"] = str(vals["size"])
    if "color" in vals:
        fmt["color"] = vals["color"]
    if "bold" in vals:
        fmt["font-weight"] = "bold" if vals["bold"] else "normal"
    if "align" in vals:
        fmt["text-align"] = vals["align"]
    element, changed = TEXT_PARTS[part], 0
    for ws in _worksheets(doc, op["sheet"], what):
        table = ws.find("table")
        st = table.find("style")
        new = copy.deepcopy(st) if st is not None else ET.Element("style")
        for attr, value in fmt.items():
            _set_format(new.findall(f"style-rule[@element='{element}']"), new, element, attr, value)
            for other in TEXT_ELEMENTS if part == "all" else ():  # only what would win over the worksheet's
                for f in new.findall(f"style-rule[@element='{other}']/format[@attr='{attr}']"):
                    f.set("value", value)
        if st is None:
            _insert(doc, doc.span[id(table.find("panes"))][0], new)
        elif serialize(st) == serialize(new):
            continue
        else:
            _replace(doc, st, new)
        touched.add(("worksheet", ws.get("name")))
        changed += 1
    rep.style = True
    rep.lines.append(f"text: {part} of {changed} sheets: {fmt}" if changed else f"text: '{op['sheet']}' already so")


def _run_lines(runs):
    """Runs by the line of the formatted text they are on (a run ending in a line break ends its line)."""
    lines = [[]]
    for r in runs:
        lines[-1].append(r)
        if "\n" in (r.text or ""):
            lines.append([])
    return [ln for ln in lines if ln]


def _edit_formatted(doc, ft, op, vals, what):
    """Set a formatted-text's run fonts, and a line's words. True if it changed."""
    new = copy.deepcopy(ft)
    lines = _run_lines(new.findall("run"))
    line = op.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(lines)):
        raise ValueError(f"{what}: line {line!r}: it has {len(lines)} lines")
    if "text" in op:
        if line is None and len(lines) > 1:
            raise ValueError(f"{what}: it has {len(lines)} lines; set \"line\" for the new text")
        runs = lines[(line or 1) - 1]
        words = [r for r in runs if (r.text or "") != LINE_BREAK_RUN] or runs[:1]  # Desktop's own run between lines
        end = "\n" if "\n" in (words[-1].text or "") else ""
        words[0].text = op["text"] + end
        for r in words[1:]:
            new.remove(r)
    present = new.findall("run")
    for r in present if line is None else [r for r in lines[line - 1] if r in present]:
        if "font" in vals:
            r.set("fontname", vals["font"])
        if "size" in vals:
            r.set("fontsize", str(vals["size"]))
        if "color" in vals:
            r.set("fontcolor", vals["color"])
        if vals.get("bold"):
            r.set("bold", "true")
        elif "bold" in vals:
            r.attrib.pop("bold", None)
        if "align" in vals:
            r.set("fontalignment", ALIGN_RUN[vals["align"]])
        _sorted_attrs(r)
    if serialize(new) == serialize(ft):
        return False
    _replace(doc, ft, new)
    return True


def _text_zones(db):
    zones = db.find("zones")
    return [z for z in (zones.iter("zone") if zones is not None else []) if z.get("type-v2") == "text"
            and z.find("formatted-text") is not None]


def _largest_run(zone):
    return max([float(r.get("fontsize", 0)) for r in zone.iter("run")] or [0])


def _title_targets(doc, op, what):
    """The formatted texts a title op edits, each with the part that holds it."""
    if ("sheet" in op) == ("dashboard" in op):
        raise ValueError(f"{what}: set either \"sheet\" or \"dashboard\"")
    if "sheet" in op:
        out = [(ws, ws.find("layout-options/title/formatted-text")) for ws in _worksheets(doc, op["sheet"], what)]
        if op["sheet"] != "*" and out[0][1] is None:
            raise ValueError(f"{what}: the sheet shows Tableau's automatic title; give it one in Desktop or in the spec")
        return [(u, ft) for u, ft in out if ft is not None]
    db = _dashboard(doc, op["dashboard"], what)
    zones = _text_zones(db)
    if "zone" in op:
        hits = zones if op["zone"] == "*" else [z for z in zones if z.get("id") == str(op["zone"])]
        if not hits:
            raise ValueError(f"{what}: no text zone {op['zone']!r} (text zones: {[z.get('id') for z in zones]})")
        return [(db, z.find("formatted-text")) for z in hits]
    ft = db.find("layout-options/title/formatted-text")
    if ft is not None:
        return [(db, ft)]
    big = [z for z in zones if _largest_run(z) >= DASH_TITLE_MIN_PT]
    if not big:
        raise ValueError(f"{what}: no title found; name the text zone with \"zone\" (text zones: "
                         f"{[z.get('id') for z in zones]})")
    return [(db, max(big, key=_largest_run).find("formatted-text"))]


def style_title(doc, op, rep, touched, added):
    what = f"title '{op.get('sheet') or op.get('dashboard')}'"
    _keys(op, ("sheet", "dashboard", "zone", "line", "text", *FONT_KEYS), what)
    vals = _font_values(op, what, rep)
    if not vals and "text" not in op:
        raise ValueError(f"{what}: nothing to set (keys: text, {', '.join(FONT_KEYS)})")
    targets = _title_targets(doc, op, what)
    if not targets:
        raise ValueError(f"{what}: no sheet here has a title of its own")
    changed = 0
    for unit, ft in targets:
        if _edit_formatted(doc, ft, op, vals, what):
            touched.add((unit.tag, unit.get("name")))
            changed += 1
    rep.style = True
    rep.lines.append(f"title: {changed} of {len(targets)} changed in '{op.get('sheet') or op.get('dashboard')}'")


def _block_of(doc, zone):
    """The zone a block's look lives on: the card around it in the card theme (the border, fill and padding are the
    container's, decisions/030), else the zone itself."""
    from .gate import _is_card
    z = doc.parent.get(id(zone))
    while z is not None and z.tag == "zone":
        if _is_card(z):
            return z
        z = doc.parent.get(id(z))
    return zone


def block(doc, op, rep, touched, added):
    """A dashboard block's padding, margins, background and border (zone-style), the dashboard's canvas color."""
    what = f"block '{op['dashboard']}'"
    _keys(op, ("dashboard", "zone", "canvas", *BLOCK_KEYS), what)
    db = _dashboard(doc, op["dashboard"], what)
    values = {}
    for key, attr in BLOCK_KEYS.items():
        if key not in op:
            continue
        if key in ("background", "border_color"):
            values[attr] = _hex(op[key], f"{what}: {key}")
        elif key == "border_style":
            if op[key] not in BORDER_STYLES:
                raise ValueError(f"{what}: border_style {op[key]!r} is not one of {BORDER_STYLES}")
            values[attr] = op[key]
        else:
            values[attr] = _px(op[key], f"{what}: {key}")
            if key != "border_width" and op[key] not in SPACE.values():
                rep.warnings.append(f"{what}: {key} {op[key]} is not a spacing token {sorted(set(SPACE.values()))}")
    if not values and "canvas" not in op:
        raise ValueError(f"{what}: nothing to set (keys: canvas, {', '.join(BLOCK_KEYS)})")
    if values and "zone" not in op:
        raise ValueError(f"{what}: name the zone: a sheet's name, a zone id, or \"*\" for all sheets and texts")
    changed = 0
    if "canvas" in op:
        st = db.find("style")
        new = copy.deepcopy(st) if st is not None else ET.Element("style")
        _set_format(new.findall("style-rule[@element='table']"), new, "table", "background-color",
                    _hex(op["canvas"], f"{what}: canvas"))
        if st is None:
            _insert(doc, doc.span[id(db.find("size") if db.find("size") is not None else db.find("zones"))][0], new)
            changed += 1
        elif serialize(st) != serialize(new):
            _replace(doc, st, new)
            changed += 1
    if values:
        zones = list(db.find("zones").iter("zone"))
        sheets = [z for z in zones if z.get("name") and z.get("type-v2") is None]
        want = op["zone"]
        if want == "*":
            hits = [_block_of(doc, z) for z in sheets + [z for z in zones if z.get("type-v2") == "text"]]
        else:  # an id is that zone exactly; a sheet's name is the block it sits in
            hits = [z for z in zones if z.get("id") == str(want)] + [_block_of(doc, z) for z in sheets
                                                                     if z.get("name") == want]
        if not hits:
            raise ValueError(f"{what}: no zone {want!r} (sheets: {sorted({z.get('name') for z in sheets})})")
        for z in {id(z): z for z in hits}.values():
            zs = z.find("zone-style")
            new = copy.deepcopy(zs) if zs is not None else ET.Element("zone-style")
            if not _zone_set(new, values):
                continue
            if zs is not None:
                _replace(doc, zs, new)
            else:
                _append_child(doc, z, new)
            changed += 1
    if changed:
        touched.add(("dashboard", db.get("name")))
    rep.style = True
    rep.lines.append(f"block: {changed} changed on '{db.get('name')}': {op.get('zone', 'canvas')}")


def _number_format(value, what):
    """A format as the op gives it (a preset, a format object, or Desktop's own string) -> Desktop's string."""
    try:
        if isinstance(value, str) and value not in formats.PRESETS:
            formats.parse(value)
            return value
        return formats.tableau(value)
    except formats.FormatError as e:
        raise ValueError(f"{what}: {e}") from None


def number_format(doc, op, rep, touched, added):
    """A number field's format: the column's default-format, so labels, axes, tooltips and KPI text agree (032)."""
    what = f"number_format '{op['field']}'"
    _keys(op, ("field", "format", "datasource", "sheet"), what)
    ds = _pick_ds(doc, op, [op["field"]], what)
    f = lookup(fields(ds), op["field"])
    if f.datatype not in NUMERIC:
        raise ValueError(f"{what}: it is a {f.datatype} field, not a number")
    value = _number_format(op["format"], what)
    if "sheet" in op:  # that sheet only: text-format of each instance, on its cells and labels and on its axis
        changed = found = 0
        for ws in _worksheets(doc, op["sheet"], what):
            names = [c.get("name") for deps in ws.iter("datasource-dependencies")
                     if deps.get("datasource") == ds.get("name") for c in deps.findall("column-instance")
                     if c.get("column") == f.name and c.get("type") == "quantitative"]
            found += len(names)
            st, new = _table_style(ws)
            for name in names:
                token = f"[{ds.get('name')}].{name}"
                _field_format(new, "cell", "text-format", token, value)
                _field_format(new, "label", "text-format", token, value)
            changed += _commit_table_style(doc, ws, st, new, touched)
        if not found:
            raise ValueError(f"{what}: this field is not a measure on sheet '{op['sheet']}'")
        rep.style = True
        rep.lines.append(f"number_format: '{op['field']}' -> {value} on {changed} sheets, {found} instances")
        return
    copies = [c for deps in doc.root.iter("datasource-dependencies") if deps.get("datasource") == ds.get("name")
              for c in deps.findall("column") if c.get("name") == f.name]
    if f.el is not None:
        if f.el.get("default-format") != value:
            new = copy.deepcopy(f.el)
            new.set("default-format", value)
            _swap(doc, f.el, _sorted_attrs(new))
            touched.add(("datasource", ds.get("name")))
    else:  # a source column without its own <column>: Desktop declares one to hold the format
        role, typ = (copies[0].get("role"), copies[0].get("type")) if copies else _role(f.datatype, False)
        _insert_after(doc, _column_anchor(ds), ET.Element("column", {
            "datatype": f.datatype, "default-format": value, "name": f.name, "role": role, "type": typ}))
        touched.add(("datasource", ds.get("name")))
    for c in copies:
        if c.get("default-format") != value:
            new = copy.deepcopy(c)
            new.set("default-format", value)
            _swap(doc, c, _sorted_attrs(new))
            touched.add(_unit(doc, c))
    instance = re.compile(rf"\[(?:[^\]]*:)?{re.escape(f.name[1:-1])}(?::[^\]]*)?\]$")
    kept, swapped = [], 0
    for ws in doc.root.findall("worksheets/worksheet"):  # a sheet's own format would hide the field's
        for st in ws.iter("style"):
            new = copy.deepcopy(st)
            for fm in new.iter("format"):
                if fm.get("attr") == "text-format" and instance.search(fm.get("field") or ""):
                    if (fm.get("value") or "").startswith("*"):
                        kept.append(ws.get("name"))
                    elif fm.get("value") != value:
                        fm.set("value", value)
                        swapped += 1
            if serialize(new) != serialize(st):
                _replace(doc, st, new)
                touched.add(("worksheet", ws.get("name")))
    if kept:
        rep.warnings.append(f"{what}: these sheets keep their own custom format: {sorted(set(kept))}")
    rep.style = True
    rep.lines.append(f"number_format: '{op['field']}' -> {value}, {len(copies)} dependency copies, "
                     f"{swapped} sheet formats")


# What a style op may change beyond style nodes and run fonts. Everything else in the XML must stay equal.
EXTRA_TAGS = {"number_format": ("datasources",), "series_colors": ("datasources",), "table_size": ("zoom",),
              "tooltip": ("customized-tooltip",)}
ZONE_ATTRS = {"legend": ("hidden-by-user", "show-title"), "filter_view": ("mode", "show-apply"),
              "sheet_title": ("show-title",)}


def _style_only(raw, op_name, has_text):
    """Canonical XML without what the style op may change: style nodes outside the datasources, run fonts; a title's
    new words drop the runs; EXTRA_TAGS and ZONE_ATTRS of that op; a dashboard's size for dashboard_size."""
    doc = parse(raw)
    for el in list(doc.root.iter()):
        for c in list(el):
            if c.tag in STYLE_TAGS and not doc.inside(c, "datasources"):
                el.remove(c)
            elif has_text and c.tag == "run" or c.tag in EXTRA_TAGS.get(op_name, ()):
                el.remove(c)
            elif op_name == "dashboard_size" and c.tag == "size" and el.tag == "dashboard":
                el.remove(c)
        if el.tag == "run":
            for a in RUN_ATTRS:
                el.attrib.pop(a, None)
        if el.tag == "zone":
            for a in ZONE_ATTRS.get(op_name, ()):
                el.attrib.pop(a, None)
        if op_name == "number_format":
            el.attrib.pop("default-format", None)
        if op_name == "reference_line" and el.tag == "reference-line":
            for a in ("label", "label-type"):
                el.attrib.pop(a, None)
    for el in doc.root.iter():
        el.text = el.text if el.text and el.text.strip() else None
        el.tail = el.tail if el.tail and el.tail.strip() else None
    return ET.canonicalize(ET.tostring(doc.root, encoding="unicode"))


# ---- style of a chart: marks, lines, table_size, axis (decisions/190) -------------------------------------------------
LINE_ELEMENTS = {"grid": "gridline", "zero": "zeroline", "axis": "axis", "dividers": "table-div"}
TOKEN = re.compile(r"\[([^\]]+)\]\.\[([^\]]+)\]")


def _table_style(ws):
    """(the sheet's table style or None, a copy to edit)."""
    st = ws.find("table/style")
    return st, copy.deepcopy(st) if st is not None else ET.Element("style")


def _commit_table_style(doc, ws, st, new, touched):
    """Write the edited copy. True if the sheet changed."""
    if st is None:
        if not len(new):
            return False
        _insert(doc, doc.span[id(ws.find("table/panes"))][0], new)
    elif serialize(st) == serialize(new):
        return False
    else:
        _replace(doc, st, new)
    touched.add(("worksheet", ws.get("name")))
    return True


def _shelf(ws, shelf):
    """The fields on a shelf in order: (qualified instance, its datasource, the field's bare name, discrete, the
    dual axis' class: 1 for a measure after ' + ')."""
    src = ws.findtext(f"table/{shelf}") or ""
    out = []
    for m in TOKEN.finditer(src):
        parts = m.group(2).split(":")  # [pcto:]sum:Sales:qk[:1]
        kind = next((i for i, x in enumerate(parts) if x in ("nk", "ok", "qk")), None)
        if kind:
            second = src[:m.start()].rstrip().endswith("+")
            out.append((m.group(0), m.group(1), parts[kind - 1], parts[kind] != "qk", "1" if second else "0"))
    return out


def _is_field(doc, token, text):
    """A shelf token is the field shown as text (by its caption or its name)."""
    ds = next((d for d in _datasources(doc) if d.get("name") == token[1]), None)
    f = lookup(fields(ds), text) if ds is not None else None
    return token[2] == (f.name[1:-1] if f is not None else text)


def _field_format(style, element, attr, field_, value, **extra):
    """Set (or add) attr on one field's format in a style-rule of the table's style."""
    for f in style.findall(f"style-rule[@element='{element}']/format[@attr='{attr}']"):
        if f.get("field") == field_:
            f.set("value", value)
            return
    rule = style.find(f"style-rule[@element='{element}']")
    if rule is None:
        rule = ET.SubElement(style, "style-rule", element=element)
    ET.SubElement(rule, "format", {"attr": attr, **extra, "field": field_, **({"value": value})})


def _drop_formats(style, element, keep):
    """Take off an element's formats that keep(format) refuses; a style-rule left empty goes too."""
    for rule in style.findall(f"style-rule[@element='{element}']"):
        for f in rule.findall("format"):
            if not keep(f):
                rule.remove(f)
        if not len(rule):
            style.remove(rule)


def marks(doc, op, rep, touched, added):
    """A sheet's mark color, size and opacity (the Marks card, in each pane's style)."""
    what = f"marks '{op['sheet']}'"
    _keys(op, ("sheet", "pane", "color", "size", "opacity"), what)
    fmt = {}
    if "color" in op:
        fmt["mark-color"] = _hex(op["color"], what)
        if fmt["mark-color"] not in {v.lower() for v in COLOR.values()}:
            rep.warnings.append(f"{what}: color {fmt['mark-color']} is not a design token")
    if "size" in op:
        if isinstance(op["size"], bool) or not isinstance(op["size"], (int, float)) or not 0 < op["size"] <= 100:
            raise ValueError(f"{what}: size {op['size']!r} is not a number above 0, up to 100 (Desktop's slider units)")
        fmt["size"] = str(op["size"])
    if "opacity" in op:
        if isinstance(op["opacity"], bool) or not isinstance(op["opacity"], int) or not 0 <= op["opacity"] <= 100:
            raise ValueError(f"{what}: opacity {op['opacity']!r} is not a percent from 0 to 100")
        fmt["mark-transparency"] = str(round(op["opacity"] * 255 / 100))  # Desktop stores the slider as 0-255
    if not fmt:
        raise ValueError(f"{what}: nothing to set (keys: color, size, opacity)")
    changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        panes = list(ws.find("table").iter("pane"))
        if "pane" in op:
            if isinstance(op["pane"], bool) or not isinstance(op["pane"], int) or not 1 <= op["pane"] <= len(panes):
                raise ValueError(f"{what}: pane {op['pane']!r}: sheet '{ws.get('name')}' has {len(panes)} panes")
            panes = [panes[op["pane"] - 1]]
        for pane in panes:
            if "mark-color" in fmt and pane.find("encodings/color") is not None:
                rep.warnings.append(f"{what}: sheet '{ws.get('name')}' colors marks by a field: its colors stay")
            if "size" in fmt and pane.find("encodings/size") is not None:
                rep.warnings.append(f"{what}: sheet '{ws.get('name')}' sizes marks by a field: its sizes stay")
            st = pane.find("style")
            new = copy.deepcopy(st) if st is not None else ET.Element("style")
            for attr, value in fmt.items():
                _set_format(new.findall("style-rule[@element='mark']"), new, "mark", attr, value)
            if st is None:
                _append_child(doc, pane, new)
            elif serialize(st) == serialize(new):
                continue
            else:
                _replace(doc, st, new)
            touched.add(("worksheet", ws.get("name")))
            changed += 1
    rep.style = True
    rep.lines.append(f"marks: {changed} panes: {fmt}")


def lines(doc, op, rep, touched, added):
    """Gridlines, zero lines, axis rulers and row dividers. false writes the off form the generator writes
    (build.DECLUTTER); true takes it off, so the sheet shows Tableau's default line."""
    what = f"lines '{op['sheet']}'"
    _keys(op, ("sheet", *LINE_ELEMENTS), what)
    asked = {k: op[k] for k in LINE_ELEMENTS if k in op}
    if not asked:
        raise ValueError(f"{what}: nothing to set (keys: {', '.join(LINE_ELEMENTS)})")
    if not all(isinstance(v, bool) for v in asked.values()):
        raise ValueError(f"{what}: each value must be true or false")
    declutter = dict(DECLUTTER)
    changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        st, new = _table_style(ws)
        for key, show in asked.items():
            element = LINE_ELEMENTS[key]
            own = declutter[element]
            attrs = {f["attr"] for f in own}
            if show:  # row dividers only: column dividers stay as they are
                _drop_formats(new, element, lambda f: f.get("attr") not in attrs or f.get("field") is not None
                              or (key == "dividers" and f.get("scope") != "rows"))
            else:
                for f in own:
                    _set_format(new.findall(f"style-rule[@element='{element}']"), new, element, f["attr"], f["value"],
                                f.get("scope"))
        changed += _commit_table_style(doc, ws, st, new, touched)
    rep.style = True
    rep.lines.append(f"lines: {changed} sheets: {asked}")


def _size_target(doc, ws, shelf, op, what):
    """The discrete field whose rows or columns a size applies to: "field", else the innermost on the shelf."""
    tokens = [t for t in _shelf(ws, shelf) if t[3]]
    if "field" in op:
        tokens = [t for t in tokens if _is_field(doc, t, op["field"])]
    return tokens[-1][0] if tokens else None


def _free_size(doc, ws, row, col, rep, touched):
    """Entire-view squeezes rows and columns to the zone, so a set size would not show: on each dashboard the sheet takes
    the fit that leaves that direction its own size (row height: fit-width; column width: fit-height; both: standard)."""
    for win in doc.root.findall("windows/window[@class='dashboard']"):
        for vp in win.iter("viewpoint"):
            if vp.get("name") != ws.get("name"):
                continue
            was = now = fit.zoom_of(vp)
            if row and now in (fit.EV, fit.FH):
                now = fit.FW if now == fit.EV else fit.STD
            if col and now in (fit.EV, fit.FW):
                now = fit.FH if now == fit.EV else fit.STD
            if now == was:
                continue
            new = copy.deepcopy(vp)
            for z in new.findall("zoom"):
                new.remove(z)
            if now != fit.STD:
                new.insert(0, ET.Element("zoom", type=now))
            _replace(doc, vp, new)
            touched.add(("window", win.get("name")))
            rep.lines.append(f"table_size: sheet '{ws.get('name')}' on '{win.get('name')}': fit {was} -> {now}, or the "
                             f"size would not show; it may scroll in its zone")


def table_size(doc, op, rep, touched, added):
    """A table's row height, column width and row header width (what dragging an edge in Desktop writes)."""
    what = f"table_size '{op['sheet']}'"
    _keys(op, ("sheet", "field", "row_height", "column_width", "header_width"), what)
    asked = {k: _px(op[k], f"{what}: {k}", 1) for k in ("row_height", "column_width", "header_width") if k in op}
    if not asked:
        raise ValueError(f"{what}: nothing to set (keys: row_height, column_width, header_width)")
    changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        st, new = _table_style(ws)
        applied = 0
        rows = _size_target(doc, ws, "rows", op, what)
        cols = _size_target(doc, ws, "cols", op, what)
        for key, value in asked.items():
            if key == "column_width" and cols is None and "field" not in op and _shelf(ws, "rows"):
                _set_format(new.findall("style-rule[@element='cell']"), new, "cell", "width", value)
                applied += 1
                continue
            target = cols if key == "column_width" else rows
            if target is None:
                continue
            element, attr = {"row_height": ("cell", "height"), "column_width": ("cell", "width"),
                             "header_width": ("header", "width")}[key]
            _field_format(new, element, attr, target, value)
            applied += 1
        if op["sheet"] != "*" and applied < len(asked):
            raise ValueError(f"{what}: this sheet has no discrete field on the shelf for {sorted(asked)}"
                             + (f" named '{op['field']}'" if "field" in op else ""))
        changed += _commit_table_style(doc, ws, st, new, touched)
        _free_size(doc, ws, "row_height" in asked and rows is not None, "column_width" in asked, rep, touched)
    rep.style = True
    rep.lines.append(f"table_size: {changed} sheets: {asked}")


def axis(doc, op, rep, touched, added):
    """A sheet's axis: shown or hidden, its title. "title" a text, "" for none, null for Tableau's automatic one."""
    what = f"axis '{op['sheet']}'"
    _keys(op, ("sheet", "field", "show", "title"), what)
    if "show" not in op and "title" not in op:
        raise ValueError(f"{what}: nothing to set (keys: show, title)")
    if not isinstance(op.get("show", True), bool):
        raise ValueError(f"{what}: show must be true or false")
    if op.get("title") is not None and not isinstance(op["title"], str):
        raise ValueError(f"{what}: title {op['title']!r} is not a text")
    found, changed = 0, 0
    for ws in _worksheets(doc, op["sheet"], what):
        st, new = _table_style(ws)
        for shelf, scope in (("rows", "rows"), ("cols", "cols")):
            for t in _shelf(ws, shelf):
                if t[3] or ("field" in op and not _is_field(doc, t, op["field"])):
                    continue
                found += 1
                is_this = lambda a: lambda f: not (f.get("attr") == a and f.get("field") == t[0])  # noqa: E731
                if op.get("show") is True:
                    _drop_formats(new, "axis", is_this("display"))
                elif op.get("show") is False:
                    _field_format(new, "axis", "display", t[0], "false", **{"class": t[4], "scope": scope})
                if "title" in op and op["title"] is None:
                    _drop_formats(new, "axis", is_this("title"))
                elif "title" in op:
                    _field_format(new, "axis", "title", t[0], op["title"], **{"class": t[4], "scope": scope})
                    if op["title"]:  # a fixed width holds the numbers only: the title would be cut off
                        _drop_formats(new, "axis", is_this("width"))
        changed += _commit_table_style(doc, ws, st, new, touched)
    if not found:
        raise ValueError(f"{what}: no continuous field on Rows or Columns"
                         + (f" named '{op['field']}'" if "field" in op else ""))
    rep.style = True
    rep.lines.append(f"axis: {found} axes on {changed} changed sheets")


# ---- beyond style: labels, series_colors, tooltip, legend, filter_view, dashboard_size (decisions/191) -----------------
FILTER_MODES = ("checkdropdown", "single_dropdown", "multi_list", "single_list")  # filters.CARD keys of a value filter
LABEL_KEYS = ("sheet", "pane", "show", "font", "size", "color", "bold")
MIN_DASH_PX, MAX_DASH_PX = 200, 10000


def _font_formats(vals):
    fmt = {}
    if "font" in vals:
        fmt["font-family"] = vals["font"]
    if "size" in vals:
        fmt["font-size"] = str(vals["size"])
    if "color" in vals:
        fmt["color"] = vals["color"]
    if "bold" in vals:
        fmt["font-weight"] = "bold" if vals["bold"] else "normal"
    return fmt


def _run_fonts(runs, vals):
    """A sheet's own label or tooltip text: its runs' fonts would win over the style."""
    for r in runs:
        if "font" in vals:
            r.set("fontname", vals["font"])
        if "size" in vals:
            r.set("fontsize", str(vals["size"]))
        if "color" in vals:
            r.set("fontcolor", vals["color"])
        if vals.get("bold"):
            r.set("bold", "true")
        elif "bold" in vals:
            r.attrib.pop("bold", None)
        _sorted_attrs(r)


def _panes(ws, op, what):
    panes = list(ws.find("table").iter("pane"))
    if "pane" not in op:
        return panes
    if isinstance(op["pane"], bool) or not isinstance(op["pane"], int) or not 1 <= op["pane"] <= len(panes):
        raise ValueError(f"{what}: pane {op['pane']!r}: sheet '{ws.get('name')}' has {len(panes)} panes")
    return [panes[op["pane"] - 1]]


def labels(doc, op, rep, touched, added):
    """Mark labels: shown or not (the mark rule) and their font (datalabel, and the runs of a sheet's own label)."""
    what = f"labels '{op['sheet']}'"
    _keys(op, LABEL_KEYS, what)
    if not isinstance(op.get("show", True), bool):
        raise ValueError(f"{what}: show must be true or false")
    vals = _font_values(op, what, rep)
    if "align" in vals:
        raise ValueError(f"{what}: unknown keys ['align']")
    if not vals and "show" not in op:
        raise ValueError(f"{what}: nothing to set (keys: show, font, size, color, bold)")
    fmt = _font_formats(vals)
    if "color" in fmt:
        fmt["color-mode"] = "user"
    changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        for pane in _panes(ws, op, what):
            if op.get("show") is False and (pane.find("mark") is not None and pane.find("mark").get("class") == "Text"):
                if op["sheet"] != "*":
                    raise ValueError(f"{what}: the sheet's marks are its text: hide it another way")
                continue
            new = copy.deepcopy(pane)
            st = new.find("style")
            if st is None:
                st = ET.SubElement(new, "style")
            if "show" in op:
                _set_format(st.findall("style-rule[@element='mark']"), st, "mark", "mark-labels-show",
                            "true" if op["show"] else "false")
            for attr, value in fmt.items():
                _set_format(st.findall("style-rule[@element='datalabel']"), st, "datalabel", attr, value)
            _run_fonts(new.findall("customized-label/formatted-text/run"), vals)
            if serialize(new) != serialize(pane):
                _replace(doc, pane, new)
                touched.add(("worksheet", ws.get("name")))
                changed += 1
    rep.style = True
    rep.lines.append(f"labels: {changed} panes: {dict(show=op.get('show'), **fmt) if 'show' in op else fmt}")


def _bucket(value):
    """A member as Desktop writes it in a palette map: text in quotes, a number bare, a Null %null%."""
    if value is None:
        return "%null%"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if isinstance(value, (int, float)) else f'"{value}"'


def series_colors(doc, op, rep, touched, added):
    """A color per member: the datasource's palette map of the field, so every sheet that colors by it agrees."""
    what = f"series_colors '{op['field']}'"
    _keys(op, ("field", "colors", "datasource"), what)
    if not isinstance(op["colors"], dict) or not op["colors"]:
        raise ValueError(f"{what}: colors must map members to #rrggbb")
    colors = {k: _hex(v, f"{what}: '{k}'") for k, v in op["colors"].items()}
    ds = _pick_ds(doc, op, [op["field"]], what)
    f = lookup(fields(ds), op["field"])
    bare = f.name[1:-1]
    on_color = {e.get("column") for ws in doc.root.findall("worksheets/worksheet")
                for e in ws.find("table").iterfind("panes/pane/encodings/color")}
    instances = [m.group(2) for c in on_color if c for m in [TOKEN.fullmatch(c)]
                 if m and m.group(1) == ds.get("name") and f":{bare}:" in f":{m.group(2)}:"]
    discrete = [i for i in instances if i.split(":")[-1] != "qk"]
    if not discrete:
        raise ValueError(f"{what}: no sheet colors its marks by this field as discrete values")
    style = ds.find("style")
    new = copy.deepcopy(style) if style is not None else ET.Element("style")
    names = {f"[{i}]" for i in discrete} | {f.name}
    enc = next((e for e in new.iterfind("style-rule[@element='mark']/encoding[@attr='color']")
                if e.get("field") in names), None)
    if enc is not None and enc.get("type") != "palette":
        raise ValueError(f"{what}: its colors are a {enc.get('type')} scale, not a color per member")
    if enc is None:
        rule = new.find("style-rule[@element='mark']")
        if rule is None:
            rule = ET.SubElement(new, "style-rule", element="mark")
        enc = ET.SubElement(rule, "encoding", {"attr": "color", "field": f"[{discrete[0]}]", "type": "palette"})
    maps = {b.text: m for m in enc.findall("map") for b in m.findall("bucket")}
    if maps:
        strange = sorted(k for k in op["colors"] if _bucket(k) not in maps)
        if strange:
            rep.warnings.append(f"{what}: not among the members the book has colored so far: {strange}")
    for member, color in colors.items():
        key = _bucket(member)
        if key in maps:
            maps[key].set("to", color)
        else:
            ET.SubElement(ET.SubElement(enc, "map", to=color), "bucket").text = key
    if style is not None:
        _replace(doc, style, new)
    else:
        after = ds.find("semantic-values")
        _insert(doc, doc.span[id(after)][0] if after is not None else doc.end_tag_start(ds), new)
    field_ = enc.get("field")
    if ":" in field_ and not any(c.get("name") == field_ for c in ds.findall("column-instance")):
        # Desktop drops a map whose instance the datasource does not declare: the copy a sheet's dependencies hold
        inst = next((c for deps in doc.root.iter("datasource-dependencies") if deps.get("datasource") == ds.get("name")
                     for c in deps.findall("column-instance") if c.get("name") == field_), None)
        if inst is None:
            raise ValueError(f"{what}: no sheet declares {field_}")
        layout = ds.find("layout")
        if layout is None:
            raise ValueError(f"{what}: the datasource has no <layout> to place {field_} before")
        decl = ET.Element("column-instance", dict(inst.attrib))
        for c in inst:
            decl.append(copy.deepcopy(c))
        _insert(doc, doc.span[id(layout)][0], decl)
    touched.add(("datasource", ds.get("name")))
    rep.style = True
    rep.lines.append(f"series_colors: '{op['field']}': {len(colors)} members on {enc.get('field')}")


def _tooltip_runs(doc, ws, pane, text, what):
    """Runs of a tooltip's text; <Field> is a field that is on the sheet for this pane."""
    on = _shelf(ws, "rows") + _shelf(ws, "cols")
    for e in pane.iterfind("encodings/*"):
        m = TOKEN.fullmatch(e.get("column") or "")
        parts = m.group(2).split(":") if m else []
        kind = next((i for i, x in enumerate(parts) if x in ("nk", "ok", "qk")), None)
        if kind:
            on.append((m.group(0), m.group(1), parts[kind - 1], parts[kind] != "qk", "0"))
    runs = []
    for i, part in enumerate(re.split(r"<([^<>]+)>", text)):
        if i % 2:
            hit = next((t for t in on if _is_field(doc, t, part)), None)
            if hit is None:
                raise ValueError(f"{what}: <{part}> is not on the sheet '{ws.get('name')}' (rows, columns or marks)")
            run = ET.Element("run")
            run.text = f"<{hit[0]}>"
            runs.append(run)
            continue
        for j, line in enumerate(part.split("\n")):
            if j:
                run = ET.Element("run")
                run.text = LINE_BREAK_RUN
                runs.append(run)
            if line:
                run = ET.Element("run")
                run.text = line
                runs.append(run)
    return runs


def tooltip(doc, op, rep, touched, added):
    """A pane's tooltip: none, Tableau's automatic one, its text ("<Sales>" a field on the sheet), its font."""
    what = f"tooltip '{op['sheet']}'"
    _keys(op, ("sheet", "pane", "show", "text", "font", "size", "color", "bold"), what)
    if not isinstance(op.get("show", True), bool):
        raise ValueError(f"{what}: show must be true or false")
    if op.get("show") is False and ("text" in op or set(op) & set(FONT_KEYS)):
        raise ValueError(f"{what}: show false has no text or font")
    vals = _font_values(op, what, rep)
    if "align" in vals:
        raise ValueError(f"{what}: unknown keys ['align']")
    if not vals and "show" not in op and "text" not in op:
        raise ValueError(f"{what}: nothing to set (keys: show, text, font, size, color, bold)")
    changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        for pane in _panes(ws, op, what):
            new = copy.deepcopy(pane)
            tip = new.find("customized-tooltip")
            if op.get("show") is False or "text" in op:
                if tip is None:
                    tip = ET.Element("customized-tooltip", {"show-buttons": "false"})
                    at = next((i for i, c in enumerate(new) if c.tag in ("customized-label", "style")), len(new))
                    new.insert(at, tip)
                for ft in tip.findall("formatted-text"):
                    tip.remove(ft)
                ft = ET.SubElement(tip, "formatted-text")
                ft.extend(_tooltip_runs(doc, ws, pane, op.get("text", ""), what))
            elif op.get("show") is True and tip is not None and "".join(tip.itertext()).strip() == "":
                new.remove(tip)  # an empty one is "no tooltip": without it Desktop shows its own
                tip = None
            if vals:
                if tip is None or not tip.findall("formatted-text/run"):
                    if op["sheet"] != "*":
                        raise ValueError(f"{what}: Tableau's automatic tooltip has no runs; set \"text\" with the font")
                    continue
                _run_fonts(tip.findall("formatted-text/run"), vals)
            if serialize(new) != serialize(pane):
                _replace(doc, pane, new)
                touched.add(("worksheet", ws.get("name")))
                changed += 1
    rep.style = True
    rep.lines.append(f"tooltip: {changed} panes of '{op['sheet']}'")


def _zone_attrs(doc, z, update):
    """Change a zone's attributes (None takes one off): its start tag only, children keep their bytes."""
    new = ET.Element(z.tag, dict(z.attrib))
    for k, v in update.items():
        if v is None:
            new.attrib.pop(k, None)
        else:
            new.set(k, v)
    if new.attrib == z.attrib:
        return False
    _sorted_attrs(new)
    closed = doc.end_tag_start(z) is None
    doc.edits.append((doc.span[id(z)][0], doc.start_tag_end(z), _start(new, closed).encode("utf-8")))
    return True


def legend(doc, op, rep, touched, added):
    """A sheet's color legend: on its dashboards shown or hidden, with or without its title; its font (the sheet)."""
    what = f"legend '{op['sheet']}'"
    _keys(op, ("sheet", "show", "title", "font", "size", "color", "bold"), what)
    for key in ("show", "title"):
        if not isinstance(op.get(key, True), bool):
            raise ValueError(f"{what}: {key} must be true or false")
    vals = _font_values(op, what, rep)
    if "align" in vals:
        raise ValueError(f"{what}: unknown keys ['align']")
    if not vals and "show" not in op and "title" not in op:
        raise ValueError(f"{what}: nothing to set (keys: show, title, font, size, color, bold)")
    update = {}
    if "show" in op:
        update["hidden-by-user"] = None if op["show"] else "true"
    if "title" in op:
        update["show-title"] = None if op["title"] else "false"
    fmt = _font_formats(vals)
    changed, found = 0, 0
    for ws in _worksheets(doc, op["sheet"], what):
        zones = [(db, z) for db in doc.root.findall("dashboards/dashboard") for z in db.find("zones").iter("zone")
                 if z.get("type-v2") == "color" and z.get("name") == ws.get("name")]
        found += len(zones)
        for db, z in zones if update else ():
            if _zone_attrs(doc, z, update):
                touched.add(("dashboard", db.get("name")))
                changed += 1
        if fmt and zones:
            st, new = _table_style(ws)
            for attr, value in fmt.items():
                _set_format(new.findall("style-rule[@element='legend']"), new, "legend", attr, value)
            if "font-size" in fmt:
                _set_format(new.findall("style-rule[@element='legend-title']"), new, "legend-title", "font-size",
                            fmt["font-size"])
            changed += _commit_table_style(doc, ws, st, new, touched)
    if not found:
        raise ValueError(f"{what}: no color legend of this sheet on a dashboard")
    rep.style = True
    rep.lines.append(f"legend: {changed} changes on {found} legends of '{op['sheet']}'")


def filter_view(doc, op, rep, touched, added):
    """How a value filter's card looks on a dashboard. A card for one value needs a filter with at most one value
    selected: the book's numbers must not change."""
    from . import filters
    what = f"filter_view '{op['field']}'"
    _keys(op, ("dashboard", "field", "mode"), what)
    if op["mode"] not in FILTER_MODES:
        raise ValueError(f"{what}: mode {op['mode']!r} is not one of {FILTER_MODES}")
    db = _dashboard(doc, op["dashboard"], what)
    cards = []
    for z in db.find("zones").iter("zone"):
        m = TOKEN.fullmatch(z.get("param") or "") if z.get("type-v2") == "filter" else None
        parts = m.group(2).split(":") if m else []
        kind = next((i for i, x in enumerate(parts) if x in ("nk", "ok", "qk")), None)
        if kind and _is_field(doc, (m.group(0), m.group(1), parts[kind - 1]), op["field"]):
            if parts[kind] == "qk":
                raise ValueError(f"{what}: a range filter, not a filter of values")
            cards.append((z, m.group(0)))
    if not cards:
        raise ValueError(f"{what}: no filter card of this field on '{db.get('name')}'")
    single = op["mode"] in filters.SINGLE
    changed = 0
    for z, column in cards:
        if single:
            for flt in doc.root.iter("filter"):  # on a sheet, or in a shared view of the dashboard's filters
                if flt.get("column") != column:
                    continue
                picked = [g for g in flt.iter("groupfilter") if g.get("function") == "member"]
                excluded = any(g.get("function") == "except" for g in flt.iter("groupfilter"))
                if len(picked) > 1 or excluded:
                    raise ValueError(f"{what}: the filter selects several values; a card for one value would change "
                                     f"the numbers")
        update = {"mode": filters.CARD[op["mode"]]}
        if op["mode"] == "multi_list":
            update["mode"] = None  # Desktop's default card, no mode attribute (golden_2025_1)
        if single:
            update["show-apply"] = None
        if _zone_attrs(doc, z, update):
            touched.add(("dashboard", db.get("name")))
            changed += 1
    rep.style = True
    rep.lines.append(f"filter_view: {changed} cards of '{op['field']}' -> {op['mode']}")


def dashboard_size(doc, op, rep, touched, added):
    """A dashboard's fixed size. Zones are in shares of it and follow; a fixed-size zone keeps its pixels."""
    what = f"dashboard_size '{op['dashboard']}'"
    _keys(op, ("dashboard", "width", "height"), what)
    db = _dashboard(doc, op["dashboard"], what)
    for key in ("width", "height"):
        v = op[key]
        if isinstance(v, bool) or not isinstance(v, int) or not MIN_DASH_PX <= v <= MAX_DASH_PX:
            raise ValueError(f"{what}: {key} {v!r} is not a whole number from {MIN_DASH_PX} to {MAX_DASH_PX}")
    size = db.find("size")
    if size is not None and (op["height"] < int(size.get("maxheight", 0)) or op["width"] < int(size.get("maxwidth", 0))):
        rep.warnings.append(f"{what}: smaller than {size.get('maxwidth')} x {size.get('maxheight')}: a title in a text "
                            f"zone can lose its second line or end in '..'; look at the dashboard")
    new = ET.Element("size", maxheight=str(op["height"]), maxwidth=str(op["width"]), minheight=str(op["height"]),
                     minwidth=str(op["width"]))
    if size is not None and size.get("sizing-mode"):
        new.set("sizing-mode", "fixed")
    if size is None:
        _insert(doc, doc.span[id(db.find("zones"))][0], new)
    elif serialize(new) == serialize(size):
        rep.lines.append(f"dashboard_size: '{db.get('name')}' already so")
        rep.style = True
        return
    else:
        _replace(doc, size, new)
    fixed = [z.get("name") or z.get("id") for z in db.find("zones").iter("zone") if z.get("is-fixed")]
    if fixed:
        rep.warnings.append(f"{what}: these zones keep their fixed pixels: {fixed}")
    touched.add(("dashboard", db.get("name")))
    rep.style = True
    rep.lines.append(f"dashboard_size: '{db.get('name')}' {op['width']} x {op['height']}")


# ---- small edits: color_scale, reference_line, sheet_title, map_style (decisions/192) ---------------------------------
SCALE_STOPS = 11  # the stops a custom scale carries (heatmap.py, golden_heatmap_rows)
LINE_PATTERNS = ("solid", "dashed", "dotted")
MAP_STYLES = ("light", "normal", "dark")


def _stops(colors):
    """2 or 3 #rrggbb -> SCALE_STOPS colors, evenly between them."""
    rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in colors]
    out = []
    for n in range(SCALE_STOPS):
        at = n / (SCALE_STOPS - 1) * (len(rgb) - 1)
        i = min(int(at), len(rgb) - 2)
        t = at - i
        out.append("#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(rgb[i], rgb[i + 1])))
    return out


def _number(op, key, what):
    v = op[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{what}: {key} {v!r} is not a number")
    return str(float(v))


def color_scale(doc, op, rep, touched, added):
    """A sheet's continuous color: its colors (2, or 3 with a center) and its range, in the sheet's own scale."""
    what = f"color_scale '{op['sheet']}'"
    _keys(op, ("sheet", "field", "colors", "min", "max", "center"), what)
    if not set(op) & {"colors", "min", "max", "center"}:
        raise ValueError(f"{what}: nothing to set (keys: colors, min, max, center)")
    colors = op.get("colors")
    if colors is not None:
        if not isinstance(colors, list) or len(colors) not in (2, 3):
            raise ValueError(f"{what}: colors must be 2 #rrggbb, or 3 with a center")
        colors = [_hex(c, what) for c in colors]
        if len(colors) == 3 and "center" not in op:
            raise ValueError(f"{what}: 3 colors need a center: the value the middle color means")
    range_ = {k: _number(op, k, what) for k in ("min", "max", "center") if k in op}
    changed = found = 0
    for ws in _worksheets(doc, op["sheet"], what):
        on_color = {e.get("column") for e in ws.find("table").iterfind("panes/pane/encodings/color")}
        tokens = [m.group(0) for c in on_color if c for m in [TOKEN.fullmatch(c)] if m and m.group(2).endswith(":qk")]
        if "field" in op:
            tokens = [t for t in tokens if any(_is_field(doc, s, op["field"]) for s in [_token(t)])]
        st, new = _table_style(ws)
        for field_ in tokens:
            found += 1
            rule = new.find("style-rule[@element='mark']")
            enc = None if rule is None else next((e for e in rule.findall("encoding")
                                                  if e.get("attr") == "color" and e.get("field") == field_), None)
            if enc is None and colors is None:
                raise ValueError(f"{what}: this sheet's scale is Tableau's automatic one; set \"colors\" with the range")
            if rule is None:
                rule = ET.Element("style-rule", element="mark")
                new.insert(0, rule)
            if enc is None:
                enc = ET.Element("encoding", {"attr": "color", "field": field_, "type": "custom-interpolated"})
                rule.insert(0, enc)
            if colors is not None:
                for k in ("palette", "reverse"):
                    enc.attrib.pop(k, None)
                enc.set("type", "custom-interpolated")
                for p in enc.findall("color-palette"):
                    enc.remove(p)
                pal = ET.SubElement(enc, "color-palette", {
                    "custom": "true", "name": "",
                    "type": "ordered-diverging" if len(colors) == 3 else "ordered-sequential"})
                for c in _stops(colors):
                    ET.SubElement(pal, "color").text = c
                if len(colors) == 2:
                    enc.attrib.pop("center", None)
            for k, v in range_.items():
                enc.set(k, v)
            _sorted_attrs(enc)
        changed += _commit_table_style(doc, ws, st, new, touched)
    if not found:
        raise ValueError(f"{what}: no continuous field on Color" + (f" named '{op['field']}'" if "field" in op else ""))
    rep.style = True
    rep.lines.append(f"color_scale: {found} scales on {changed} changed sheets")


def _token(text):
    """A qualified instance as _shelf's tuple."""
    m = TOKEN.fullmatch(text)
    parts = m.group(2).split(":")
    kind = next((i for i, x in enumerate(parts) if x in ("nk", "ok", "qk")), None)
    return text, m.group(1), parts[kind - 1] if kind else m.group(2), bool(kind) and parts[kind] != "qk", "0"


def reference_line(doc, op, rep, touched, added):
    """A reference line's look (refline formats by its id) and label (its label and label-type)."""
    what = f"reference_line '{op['sheet']}'"
    _keys(op, ("sheet", "line", "color", "width", "pattern", "label", "label_size", "label_color"), what)
    fmt = {}
    if "color" in op:
        fmt["stroke-color"] = _hex(op["color"], what)
    if "width" in op:
        fmt["stroke-size"] = _px(op["width"], f"{what}: width", 0)
        fmt["line-visibility"] = "on" if op["width"] else "off"
    if "pattern" in op:
        if op["pattern"] not in LINE_PATTERNS:
            raise ValueError(f"{what}: pattern {op['pattern']!r} is not one of {LINE_PATTERNS}")
        fmt["line-pattern-only"] = op["pattern"]
    if "label_size" in op:
        fmt["font-size"] = _px(op["label_size"], f"{what}: label_size", 1)
    if "label_color" in op:
        fmt["color"] = _hex(op["label_color"], what)
    label = op.get("label")
    if "label" in op and not isinstance(label, (str, bool)):
        raise ValueError(f"{what}: label is a text, true for the value, or false for none")
    if not fmt and "label" not in op:
        raise ValueError(f"{what}: nothing to set (keys: color, width, pattern, label, label_size, label_color)")
    found = changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        lines_ = list(ws.iter("reference-line"))
        if "line" in op:
            if isinstance(op["line"], bool) or not isinstance(op["line"], int) or not 1 <= op["line"] <= len(lines_):
                raise ValueError(f"{what}: line {op['line']!r}: sheet '{ws.get('name')}' has {len(lines_)} lines")
            lines_ = [lines_[op["line"] - 1]]
        found += len(lines_)
        st, new = _table_style(ws)
        for line in lines_:
            if "label" in op:
                update = {"label": None, "label-type": "none"} if label is False else \
                    {"label": None, "label-type": "value"} if label is True else {"label": label, "label-type": "custom"}
                if _zone_attrs(doc, line, update):
                    touched.add(("worksheet", ws.get("name")))
                    changed += 1
            for attr, value in fmt.items():
                rule = new.find("style-rule[@element='refline']")
                if rule is None:
                    rule = ET.SubElement(new, "style-rule", element="refline")
                hit = next((f for f in rule.findall("format") if f.get("attr") == attr
                            and f.get("id") == line.get("id")), None)
                if hit is not None:
                    hit.set("value", value)
                else:
                    ET.SubElement(rule, "format", attr=attr, id=line.get("id"), value=value)
        changed += _commit_table_style(doc, ws, st, new, touched)
    if not found:
        raise ValueError(f"{what}: no reference line on this sheet")
    rep.style = True
    rep.lines.append(f"reference_line: {found} lines, {changed} changes on '{op['sheet']}'")


def sheet_title(doc, op, rep, touched, added):
    """A sheet's own title on a dashboard: shown or not (show-title of its zone). The block's text zone is not it."""
    what = f"sheet_title '{op['sheet']}'"
    _keys(op, ("sheet", "dashboard", "show"), what)
    if not isinstance(op["show"], bool):
        raise ValueError(f"{what}: show must be true or false")
    names = {w.get("name") for w in _worksheets(doc, op["sheet"], what)}
    dashboards = [_dashboard(doc, op["dashboard"], what)] if "dashboard" in op \
        else doc.root.findall("dashboards/dashboard")
    found = changed = 0
    for db in dashboards:
        for z in db.find("zones").iter("zone"):
            if z.get("type-v2") is None and z.get("name") in names:
                found += 1
                if _zone_attrs(doc, z, {"show-title": None if op["show"] else "false"}):
                    touched.add(("dashboard", db.get("name")))
                    changed += 1
    if not found:
        raise ValueError(f"{what}: this sheet is on no dashboard")
    rep.style = True
    rep.lines.append(f"sheet_title: {changed} of {found} zones changed, show {op['show']}")


def map_style(doc, op, rep, touched, added):
    """A map's background: light, normal or dark, and its washout in percent."""
    what = f"map_style '{op['sheet']}'"
    _keys(op, ("sheet", "style", "washout"), what)
    if "style" not in op and "washout" not in op:
        raise ValueError(f"{what}: nothing to set (keys: style, washout)")
    if "style" in op and op["style"] not in MAP_STYLES:
        raise ValueError(f"{what}: style {op['style']!r} is not one of {MAP_STYLES}")
    fmt = {"map-style": op["style"]} if "style" in op else {}
    if "washout" in op:
        v = op["washout"]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100:
            raise ValueError(f"{what}: washout {v!r} is not a percent from 0 to 100")
        fmt["washout"] = str(v / 100)
    found = changed = 0
    for ws in _worksheets(doc, op["sheet"], what):
        shelves = (ws.findtext("table/rows") or "") + (ws.findtext("table/cols") or "")
        if "(generated)" not in shelves and ws.find("table/style/style-rule[@element='map']") is None:
            continue
        found += 1
        st, new = _table_style(ws)
        for attr, value in fmt.items():
            _set_format(new.findall("style-rule[@element='map']"), new, "map", attr, value)
        changed += _commit_table_style(doc, ws, st, new, touched)
    if not found:
        raise ValueError(f"{what}: this sheet is not a map")
    rep.style = True
    rep.lines.append(f"map_style: {found} maps, {changed} changed: {fmt}")


STYLE_OPS = {"text": style_text, "title": style_title, "block": block, "number_format": number_format, "marks": marks,
             "lines": lines, "table_size": table_size, "axis": axis, "labels": labels, "series_colors": series_colors,
             "tooltip": tooltip, "legend": legend, "filter_view": filter_view, "dashboard_size": dashboard_size,
             "color_scale": color_scale, "reference_line": reference_line, "sheet_title": sheet_title,
             "map_style": map_style}
OPS = {"add_calc": add_calc, "copy_sheet": copy_sheet, "rename": rename, "sql": sql, "param": param, **STYLE_OPS}


# ---- the invariant -----------------------------------------------------------------------------------------------
def _units(doc):
    return {(k, e.get("name")): e for k, parent in UNITS.items() for e in doc.root.findall(f"{parent}/{k}")}


def _outside(doc, units):
    """doc.raw without the units' bytes, whitespace dropped (an inserted unit brings its indent)."""
    out, pos = [], 0
    for s, e in sorted(doc.span[id(u)] for u in units.values()):
        out.append(doc.raw[pos:s])
        pos = e
    return re.sub(rb"\s+", b"", b"".join(out + [doc.raw[pos:]]))


def invariant(before, after, touched, added):
    """Raise ValueError unless every part not in touched keeps its bytes, the parts of after not in before are
    exactly added, and the XML outside the parts is the same (whitespace aside)."""
    a, b = parse(before), parse(after)
    ua, ub = _units(a), _units(b)
    for key, el in ua.items():
        if key not in ub:
            raise ValueError(f"patch invariant: {key[0]} '{key[1]}' disappeared")
        if key not in touched and before[slice(*a.span[id(el)])] != after[slice(*b.span[id(ub[key])])]:
            raise ValueError(f"patch invariant: {key[0]} '{key[1]}' changed, no op touches it")
    if set(ub) - set(ua) != set(added):
        raise ValueError(f"patch invariant: new parts {sorted(set(ub) - set(ua))}, expected {sorted(added)}")
    if _outside(a, ua) != _outside(b, ub):
        raise ValueError("patch invariant: XML outside the datasources, sheets, dashboards and windows changed")


def patch_xml(raw, ops):
    """.twb bytes + ops -> (patched bytes, Report). Each op sees the result of the ones before it."""
    if not isinstance(ops, list) or not ops:
        raise ValueError("patch: ops must be a non-empty list")
    rep, touched, added, out = Report(), set(), set(), raw
    for i, op in enumerate(ops):
        fn = OPS.get(op.get("op")) if isinstance(op, dict) else None
        if fn is None:
            raise ValueError(f"patch: op {i + 1}: unknown op {op!r} (known: {', '.join(OPS)})")
        doc = parse(out)
        try:
            fn(doc, op, rep, touched, added)
        except KeyError as e:
            raise ValueError(f"patch: op {i + 1} ({op['op']}): missing key {e}") from None
        new = apply(doc)
        if op["op"] in STYLE_OPS and _style_only(out, op["op"], "text" in op) != _style_only(new, op["op"], "text" in op):
            raise ValueError(f"patch: op {i + 1} ({op['op']}) changed more than style")
        out = new
    ET.fromstring(out)  # well-formed
    invariant(raw, out, touched, added)
    return out, rep


# ---- files and the gate ------------------------------------------------------------------------------------------
def _gate_keys(path, copies=None):
    """The gate's findings as strings, a copied sheet's under its source's name: a copy inherits the source's
    findings, and only a finding the input does not have is new (a set: a second copy of a finding is not)."""
    from . import gate
    keys = set()
    for i in gate.run(path):
        s = str(i)
        for new, src in (copies or {}).items():
            s = s.replace(f"'{new}'", f"'{src}'")
        keys.add(s)
    return keys


def _twbx_of_twb(raw, name, d):
    p = Path(d) / (Path(name).stem + ".twbx")
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, raw)
    return p


def patch_file(src, out, ops):
    """Patch src (.twbx or .twb) into out (same kind); the gate's new findings block it (GateError)."""
    from .gate import GateError
    src, out = Path(src), Path(out)
    if src.suffix.lower() != out.suffix.lower():
        raise ValueError(f"patch: {src.name} -> {out.name}: input and output must both be .twbx or .twb")
    if src.resolve() == out.resolve():
        raise ValueError("patch: the output must be a new file (the input is never rewritten)")
    raw = read_twb(src)
    new, rep = patch_xml(raw, ops)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as d:
        if src.suffix.lower() == ".twb":
            for sub in ("a", "b"):
                (Path(d) / sub).mkdir()
            before, after = _twbx_of_twb(raw, src.name, Path(d) / "a"), _twbx_of_twb(new, src.name, Path(d) / "b")
            tmp = Path(d) / "out.twb"
            tmp.write_bytes(new)
        else:
            before, tmp = src, Path(d) / "out.twbx"
            with zipfile.ZipFile(src) as z, zipfile.ZipFile(tmp, "w") as w:
                name = _twb_name(z)
                for info in z.infolist():
                    w.writestr(info, new if info.filename == name else z.read(info.filename),
                               compress_type=info.compress_type)
            with zipfile.ZipFile(src) as z, zipfile.ZipFile(tmp) as w:  # every other member byte for byte
                for info in z.infolist():
                    if info.filename != name and z.read(info.filename) != w.read(info.filename):
                        raise ValueError(f"patch: package member {info.filename} changed")
            after = tmp
        fresh = _gate_keys(after, rep.copies) - _gate_keys(before)
        if rep.style:  # the user chose the value: a design rule warns, the rest still blocks
            design_only = {k for k in fresh if k[1:k.index("]")] in STYLE_CHECKS
                           or (k.startswith("[reflines]") and "has no label" in k)}
            rep.warnings += [f"gate: {k}" for k in sorted(design_only)]
            fresh -= design_only
        if fresh:
            from .gate import Issue
            raise GateError([Issue("patch", "new", k) for k in sorted(fresh)])
        shutil.move(tmp, out)
    return rep


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="tbuilder patch", description="Point edits of an existing workbook, gated "
                                 "(decisions/161).")
    ap.add_argument("src", type=Path)
    ap.add_argument("ops", type=Path, help="JSON list of edits (see tbuilder/patch.py)")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--resave", action="store_true", help="then check-desktop --resave the output (decisions/054)")
    ap.add_argument("-d", "--out-dir", type=Path, default=Path("out") / "resave")
    a = ap.parse_args(argv)
    rep = patch_file(a.src, a.out, json.loads(a.ops.read_text(encoding="utf-8")))
    print(rep.text())
    print(f"{a.out}: gate OK (no new findings that block)")
    if a.resave:
        from .resave import main as resave_main
        return resave_main([str(a.out), "-d", str(a.out_dir)])
    return 0
