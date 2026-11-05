"""Field properties (todo 2.6, decisions/033): aliases, manual order, groups, default color of a field's members;
the field's own name in the workbook (decisions/073).

Spec, top level:
  "fields": {
    "customer_tier": {"caption": "Customer Tier"},
    "Day":        {"aliases": {"19 Mon": "Mon", ...}, "order": ["19 Mon", "20 Tue", ...]},
    "Type":       {"color": {"Incidents": "#1f3a5f", "Service requests": "#4e79a7", "Tasks": "#a0c4e8"}},
    "Type Group": {"group": {"field": "Type", "bins": {"Requests": ["Service requests", "Tasks"]}, "other": "Other"}}
  }
Keys of aliases / order / color are the field's values in the data (a group's values: its bin names, "other", and
without "other" the members left out of the bins). Aliases rename what Tableau shows; the data and formulas keep the
raw values (Tableau's own semantics). Forms of the XML are Desktop's (reference books, decisions/033):
  aliases   <column><aliases><alias key='"19 Mon"' value='Mon'/></aliases></column>, in the datasource and in each
            sheet's dependencies
  order     <default-sorts><manual-sort column='[none:Day:nk]' direction='ASC'><dictionary><bucket>"19 Mon"</bucket>
            in the datasource (Default Properties > Sort > Manual), after date-options
  group     <column name='[Type Group]'><calculation class='categorical-bin' column='[Type]' default='"Other"'
            new-bin='true'><bin default-name='false' value='"Requests"'><value>"Tasks"</value>...
  color     a palette map on [none:<field>:nk] in the datasource style (Default Properties > Color), as _palettes
  caption   <column caption='Customer Tier' datatype=... name='[customer_tier]' ...>, in the datasource and in each
            sheet's dependencies (Rename; a case's improved.twb: caption='Diff' name='[diff]'); references keep the name
A row-level text calc takes 'order' (decisions/090): the same <manual-sort> on [none:Calculation_...:nk], the calc's
internal name (StudentPortrait 2023.3); its values are the calc's over the data rows, checked once the calcs are
evaluated (Fields.check_calcs).
"""
from dataclasses import dataclass

import xml.etree.ElementTree as ET


def resolve_tokens(spec):
    """The spec with the design tokens of fields.<f>.color (accent, bad, ...) replaced by their #rrggbb (decisions/091),
    so every reader sees hex. The spec is copied only when a token is there."""
    from .design import COLOR
    fs = spec.get("fields") or {}
    if not any(c in COLOR for p in fs.values() for c in p.get("color", {}).values()):
        return spec
    return {**spec, "fields": {k: {**p, "color": {v: COLOR.get(c, c) for v, c in p["color"].items()}}
                               if "color" in p else p for k, p in fs.items()}}


@dataclass
class GroupColumn:
    """A group field (Tableau 'Create Group'), shaped like a profiled CSV column so Field can use it."""
    name: str
    source: str
    bins: dict  # label -> [members] (as text; a number's digits)
    other: str  # label of the members out of every bin; None: they keep their own name
    distinct: list  # the group's values, sorted; None until check_calcs for a group of a calc
    of_calc: bool = False  # the source is a calculated field (decisions/151)
    numeric: bool = False  # the source is an integer column: members are numbers, written unquoted

    datatype = "string"
    role = "dimension"

    def value(self, raw):
        if raw is None or raw == "":
            return None
        raw = str(raw)
        for label, members in self.bins.items():
            if raw in members:
                return label
        return self.other or raw

    def bind(self, where, values):
        """The group against the values of its source: members are values, a member in one bin; sets `distinct`."""
        seen = {}
        for label, members in self.bins.items():
            _keys(where, f"bin '{label}'", members, values)
            for m in members:
                if m in seen:
                    raise ValueError(f"{where}: '{m}' is in bins '{seen[m]}' and '{label}'; a member belongs to one bin")
                seen[m] = label
        rest = [v for v in values if v not in seen]
        if self.other is not None:
            if self.other in self.bins:
                raise ValueError(f"{where}: other '{self.other}' is also a bin name")
            self.distinct = sorted(set(self.bins) | ({self.other} if rest else set()))
        else:
            clash = sorted(set(self.bins) & set(rest))
            if clash:
                raise ValueError(f"{where}: bin names {clash} are also members left out of the bins; rename the bin or "
                                 f"put the member in it")
            self.distinct = sorted(set(self.bins) | set(rest))


def _donut_highlights(spec, prof):
    """fields with a donut's color.highlight written as the default colors of its dimension: the highlighted members
    in the accent, the others muted (decisions/091). The donut's rings and legend sheets take their colors from
    there, as from a hand-written fields.<dimension>.color."""
    from .design import COLOR
    props = spec.get("fields", {})
    columns = {c.name: c for c in prof.columns}
    for s in spec["sheets"]:
        if s["type"] != "donut" or "color" not in s:
            continue
        where, dim = f"Sheet '{s['name']}'", s["dimension"]
        if "field" in s["color"] and s["color"]["field"] != dim:
            raise ValueError(f"{where}: a donut highlights its own dimension '{dim}', not '{s['color']['field']}'")
        if "color" in props.get(dim, {}):
            raise ValueError(f"{where}: color.highlight and fields '{dim}'.color both set its colors; keep one")
        if dim not in columns:
            raise ValueError(f"{where}: no such column '{dim}'")
        values = sorted(columns[dim].distinct)
        unknown = [v for v in s["color"]["highlight"] if v not in values]
        if unknown:
            raise ValueError(f"{where}: highlight {unknown} are not values of '{dim}'; values: {values}")
        props = {**props, dim: {**props.get(dim, {}), "color": {v: COLOR["accent"] if v in s["color"]["highlight"]
                                                                  else COLOR["mark_muted"] for v in values}}}
    return props


class Fields:
    """The spec's field properties, checked against the data."""

    def __init__(self, spec, prof):
        self.props = _donut_highlights(spec, prof)
        # a folder is the Data pane's (folders.py, decisions/146), not a property of the field's values
        self.props = {n: q for n, p in self.props.items() if (q := {k: v for k, v in p.items() if k != "folder"})}
        calcs ={c["name"] for c in spec.get("calcs", [])}
        self.calcs = {}  # calc name -> its values, once check_calcs has them (decisions/090)
        self.calc_captions = set()  # calcs with a caption only: named on their own column (polish-26)
        columns = {c.name: c for c in prof.columns}
        self.groups = {}
        for name, p in self.props.items():
            if "group" in p:
                if "aliases" in p:
                    raise ValueError(f"fields '{name}': a group is renamed through its bin names; Tableau Desktop "
                                     f"drops the aliases of a group (decisions/151). Name the bins as they should show")
                self.groups[name] = _group(name, p["group"], columns, calcs, prof.rows)
        self._check_captions(columns, calcs)
        for name, p in self.props.items():
            where = f"fields '{name}'"
            if name not in self.groups:
                if name in calcs:
                    if not set(p) <= {"aliases", "order", "color", "caption"}:
                        raise ValueError(f"{where}: of a calculated field's properties only 'aliases', 'order', "
                                         f"'color' and 'caption' are supported, got "
                                         f"{sorted(set(p) - {'aliases', 'order', 'color', 'caption'})}")
                    continue  # its values come from the calc: check_calcs
                if name not in columns:
                    raise ValueError(f"{where}: no such column; columns: {sorted(columns)}")
                if set(p) == {"caption"}:  # any column takes a name of its own
                    continue
                if columns[name].datatype != "string":
                    raise ValueError(f"{where}: '{name}' is {columns[name].datatype}; aliases, order, group and color "
                                     f"apply to text dimensions")
            if name in self.groups and self.groups[name].distinct is None:
                continue  # a group of a calc: its values come with the calc, check_calcs
            self._check_props(where, p, self.values(name, columns))
        self._values = {name: self.values(name, columns) for name in self.props if name not in calcs
                        and (name not in self.groups or self.groups[name].distinct is not None)}

    @staticmethod
    def _check_props(where, p, values):
        """aliases / order / color of a field against its values."""
        if any('"' in v for v in values):
            raise ValueError(f"{where}: values containing '\"' are not verified against Tableau yet")
        if "aliases" in p:
            _keys(where, "aliases", p["aliases"], values)
            shown = [p["aliases"].get(v, v) for v in values]
            dup = sorted({s for s in shown if shown.count(s) > 1})
            if dup:
                raise ValueError(f"{where}: aliases show {dup} for more than one value; each value needs its own "
                                 f"label")
        for prop in ("order", "color"):
            if prop in p:
                _keys(where, prop, p[prop], values)
                left = [v for v in values if v not in p[prop]]
                if left:
                    raise ValueError(f"{where}: {prop} leaves out {left}; "
                                     + ("list every value of the field" if prop == "order"
                                        else "Tableau would pick their colors itself"))

    def check_calcs(self, calcs):
        """The properties of a calc against its values, and the groups over calcs. calcs: {name: (row-level text
        dimension?, its values)} of the calcs with properties and of the sources of groups."""
        for name, (text_dim, values) in calcs.items():
            where = f"fields '{name}'"
            if name not in self.props:
                continue
            if set(self.props[name]) <= {"caption"}:  # a calc's own name only (polish-26)
                self.calc_captions.add(name)
                continue
            if not text_dim:
                raise ValueError(f"{where}: aliases, order and color apply to a row-level text calculation (a "
                                 f"dimension); '{name}' is an aggregate, a number, a date or a boolean")
            self._check_props(where, self.props[name], values)
            self.calcs[name] = self._values[name] = list(values)
        for g in self.groups.values():
            if not g.of_calc:
                continue
            where = f"fields '{g.name}' group"
            text_dim, values = calcs[g.source]
            if not text_dim:
                raise ValueError(f"{where}: '{g.source}' must be a row-level text calculation (a dimension) to be "
                                 f"grouped")
            g.bind(where, list(values))
            self._check_props(f"fields '{g.name}'", self.props[g.name], g.distinct)
            self._values[g.name] = g.distinct

    def _check_captions(self, columns, calcs):
        """A caption names one field: not a group (named by its key), no other field's name or caption."""
        taken = {}
        for name, p in self.props.items():
            if "caption" not in p:
                continue
            where, cap = f"fields '{name}'", p["caption"]
            if name in self.groups:
                raise ValueError(f"{where}: a group is named by its key; caption applies to a column of the data")
            other = taken.get(cap) or next((n for n in [*columns, *calcs, *self.groups] if n == cap and n != name), None)
            if other:
                raise ValueError(f"{where}: caption '{cap}' is already the name of '{other}'; Tableau would show two "
                                 f"fields under one name")
            taken[cap] = name

    def caption(self, name):
        """The field's own name in the workbook (decisions/073), None when it keeps the data's name."""
        return self.props.get(name, {}).get("caption")

    def values(self, name, columns=None):
        """The field's values: a column's distinct values, a group's bins (+ other or the members left out)."""
        if name in self.groups:
            return self.groups[name].distinct
        if columns is None:
            return self._values[name]
        return columns[name].distinct

    def shown(self, name, raw):
        """The label Tableau shows for a value (its alias, or the value)."""
        return self.props.get(name, {}).get("aliases", {}).get(raw, raw)

    def rank(self, name, raw):
        """Sort key of a value along the field: the manual order, else the value (Tableau's default, alphabetic)."""
        order = self.props.get(name, {}).get("order")
        return (order.index(raw), "") if order and raw in order else (len(order or ()), raw)

    def labels(self, col):
        """What the field shows (header widths): aliases instead of the values they rename."""
        return [self.shown(col.name, v) for v in col.distinct]


def _group(name, g, columns, calcs, rows):
    where = f"fields '{name}' group"
    if name in columns or name in calcs:
        raise ValueError(f"{where}: '{name}' is already a column or a calculated field; give the group its own name")
    src = g["field"]
    bins = {label: [str(m) for m in members] for label, members in g["bins"].items()}
    group = GroupColumn(name, src, bins, g.get("other"), None, of_calc=src in calcs and src not in columns)
    if group.of_calc:  # its values are the calc's: bound in check_calcs
        return group
    if src not in columns or columns[src].datatype not in ("string", "integer"):
        raise ValueError(f"{where}: field '{src}' must be a text or integer column or a text calculation (a real or "
                         f"date field has no members to group)")
    if columns[src].datatype == "integer":
        group.numeric = True
        values = sorted({r[src] for r in rows if r[src] != ""}, key=int)
    else:
        values = columns[src].distinct
    group.bind(where, values)
    return group


def _keys(where, what, keys, values):
    unknown = [k for k in keys if k not in values]
    if unknown:
        raise ValueError(f"{where}: {what} names {unknown}, not values of the field (values: {values[:12]})")


def _bucket(v):
    return f'"{v}"'


# ---- XML ---------------------------------------------------------------------------------------------------------
def declared(b):
    """Columns the datasource declares for their properties: the CSV columns with aliases, order or color (Desktop
    declares a column that carries a property) and the group fields with their source columns (Desktop 2025.1 adds
    the source on Save As, decisions/061). A calc is declared anyway."""
    out = []
    for name in b.fields.props:
        if name in b.fields.calcs or name in b.fields.calc_captions:
            continue
        if name in b.fields.groups:
            out += [b.group_cols[name], source(b, b.group_cols[name])]
        else:
            out.append(b.prof.col(name))
    return out


def column(b, el, col):
    """A column's property children: a group's categorical-bin calculation, a column's aliases."""
    if isinstance(col, GroupColumn):
        source = b.calc_cols[col.source].name if col.of_calc else col.source  # a calc's internal name
        attrs = {"class": "categorical-bin", "column": f"[{source}]"}
        if col.other is not None:
            attrs["default"] = _bucket(col.other)
        attrs["new-bin"] = "true"
        calc = ET.SubElement(el, "calculation", attrs)
        for label, members in sorted(col.bins.items()):  # Desktop saves the bins alphabetically (decisions/151)
            bin_ = ET.SubElement(calc, "bin", {"default-name": "false", "value": _bucket(label)})
            for m in members:
                ET.SubElement(bin_, "value").text = m if col.numeric else _bucket(m)  # a number unquoted
        return  # a group is renamed through its bins: Desktop drops <aliases> of a group
    aliases = b.fields.props.get(getattr(col, "caption", col.name), {}).get("aliases")  # a calc: by its spec name
    if aliases:
        al = ET.SubElement(el, "aliases")
        for key in b.fields.values(getattr(col, "caption", col.name)):  # in the field's own order, as Desktop lists them
            if key in aliases:
                ET.SubElement(al, "alias", key=_bucket(key), value=aliases[key])


def instance(name, group=None):
    """How the field is referenced: a column through its instance [none:X:nk]; a group as its column [X], with no
    instance (Desktop: HelpDesk RWFD, DataQualityTesting)."""
    return f"[{name}]" if group is not None else f"[none:{name}:nk]"


def _column(b, name):
    """The field's column name in the workbook: a calc's internal Calculation_... (decisions/090)."""
    return b.calc_cols[name].name if name in b.fields.calcs else name


def instances(b):
    """(instance, column, derivation, type) the datasource declares for the default sort and the palette maps."""
    return [(instance(_column(b, name)), _column(b, name), "None", "nominal") for name, p in b.fields.props.items()
            if ("order" in p or "color" in p) and name not in b.fields.groups]


def palettes(b):
    """Default colors of the members: {instance: (column | None, derivation, [(bucket, color)])}; a group's map has
    no instance of its own."""
    out = {}
    for name, p in b.fields.props.items():
        if "color" in p:
            group = b.fields.groups.get(name)
            out[instance(_column(b, name), group)] = (None if group else _column(b, name), "None",
                                          [(_bucket(v), c.lower()) for v, c in p["color"].items()])
    return out


def default_sorts(b, ds):
    """<default-sorts>: the manual order of each field that has one (after date-options)."""
    ordered = [(instance(_column(b, name), b.fields.groups.get(name)), p["order"])
               for name, p in b.fields.props.items() if "order" in p]
    if not ordered:
        return
    ordered.sort(key=lambda o: o[0])  # by the column text, as Desktop: [Qty Band] [Size Tier] [none:Calc..:nk] (151)
    sorts = ET.SubElement(ds, "default-sorts")
    for inst, order in ordered:
        ms = ET.SubElement(sorts, "manual-sort", column=inst, direction="ASC")
        d = ET.SubElement(ms, "dictionary")
        for v in order:
            ET.SubElement(d, "bucket").text = _bucket(v)


@dataclass
class DimColumn:
    """A numeric column grouped: declared as a dimension (a group of numbers groups its discrete values)."""
    name: str
    datatype: str
    role = "dimension"


def source(b, col):
    """The column a group groups: a CSV column (an integer one as a dimension), or a calc."""
    if col.of_calc:
        return b.calc_cols[col.source]
    c = b.prof.col(col.source)
    return DimColumn(c.name, c.datatype) if col.numeric else c


def deps(b, col):
    """A group field's worksheet dependencies: the group, the column it groups, and what a calc needs."""
    src = source(b, col)
    return [col, *(b.with_deps(src) if col.of_calc else [src])]
