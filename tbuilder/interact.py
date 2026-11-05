"""Interactivity (decisions/042): buttons that set a parameter, a period switch, a view switch.

References (reference books):
- SuperMart: 'Click a metric to filter the views' - each clickable thing is a worksheet of its own whose mark
  carries a constant calc ("1"); an edit-parameter-action on that sheet writes the calc into the parameter. The
  same for its period buttons L6M ... All and for the area / bar icons. Here a `buttons` sheet expands into one such
  worksheet per parameter value: the value as text, colored by whether it is the current value.
- SuperMart's period: a boolean calc over the parameter (`[order_date] >= DATEADD('month', -6, {MAX(...)})` per
  value), as a shared filter = true. Here one calc: CASE over the values L<N><D|W|M|Q|Y> | All, DATEDIFF from the
  last date of the data (FIXED MAX: decisions/019's default anchor, and it moves with the data).
- SuperMart / Admissions: Dynamic Zone Visibility - a container per alternative, `hidden-by-user` on the hidden
  ones, and a <datagraph> that links each container (dashboard simple-id + zone id) to a boolean calc
  `[Parameter] = "value"`.
- A parameter card as radio buttons: `paramctrl mode='list'` (reference Sample Superstore).

Logic lives here; build.py only calls in.
"""
import re
import uuid
import xml.etree.ElementTree as ET

from . import design
from .design import COLOR, FONT, SPACE

BUTTONS, SWITCH, BUTTON = "buttons", "switch", "button"  # spec sheet types; a physical button worksheet
SWITCH_VIEWS = ("bar", "line", "area", "table", "heatmap", "registry")  # a registry with its titles (082)
PERIOD = re.compile(r"^L([1-9]\d{0,2})([DWMQY])$")
LEVEL = {"D": "day", "W": "week", "M": "month", "Q": "quarter", "Y": "year"}
ALL = "All"
CONTROLS = ("card", "radio", "none")
ACTION_FLAGS = ("ParameterAction", "ParameterActionClearSelection")  # in every reference with parameter actions
DZV_FLAGS = ("DatagraphCoreV1", "DatagraphNodeDashboardZoneVisibilityV1", "DatagraphNodeSingleValueFieldV1",
             "ZoneVisibilityControl")  # SuperMart, Admissions, E-Commerce, Demand Capacity
_ID_NS = uuid.UUID("2f9d3c1a-7b4e-4c8a-9e61-5d0f3a2b7c94")  # stable ids: a rebuild matches its golden
USER_NS = "http://www.tableausoftware.com/xml/user"


# ---- spec ---------------------------------------------------------------------------------------------------
def buttons(spec):
    return [s for s in spec["sheets"] if s["type"] == BUTTONS]


def switches(spec):
    return [s for s in spec["sheets"] if s["type"] == SWITCH]


def periods(spec):
    """Parameters that filter the dates: [(parameter spec, date field)]."""
    return [(p, p["period"]["field"]) for p in spec.get("parameters", []) if "period" in p]


def driven(spec):
    """Names of the parameters a buttons sheet sets."""
    return {s["parameter"] for s in buttons(spec)}


def control(p, spec):
    """card | radio | none: the parameter's card in the header row; a parameter set by buttons has none unless the
    spec asks for one."""
    return p.get("control", "none" if p["name"] in driven(spec) else "card")


def card_here(spec, p):
    """Does parameter p's card go on the current dashboard (spec['dashboard'])? A switch's parameter goes where its
    switch is (decisions/082: a case's Won / Lost radio is for Pipeline, not Revenue); any other everywhere."""
    on = [s for s in switches(spec) if s["parameter"] == p]
    if not on or "grid" not in spec.get("dashboard", {}):
        return True
    from .build import _leaves
    here = set(_leaves(spec["dashboard"]["grid"]))
    return any(s["name"] in here for s in on)


def params_used(spec):
    """Parameters this module uses (params.check: every parameter changes something)."""
    return driven(spec) | {p["name"] for p, _ in periods(spec)} | {s["parameter"] for s in switches(spec)}


def value_calc(p, v):
    return f"{p} · {v}"


def active_calc(p, v):
    return f"{p} · {v} · on"


def period_calc(p):
    return f"{p} filter"


def switch_calc(s, v):
    return f"{s['name']} · {v}"


def _lit(v):
    return '"' + v + '"'


def calcs(spec):
    """Calc specs: per value of a parameter set by buttons its constant (the action's source field) and whether it
    is the current one (the button's color); the period filter; per view of a switch whether it is shown."""
    out = []
    for name in sorted(driven(spec)):
        p = next(q for q in spec.get("parameters", []) if q["name"] == name)
        for v in p.get("values", []):
            out.append({"name": value_calc(name, v), "formula": _lit(v)})
            out.append({"name": active_calc(name, v), "formula": f"[{name}] = {_lit(v)}"})
    for p, field in periods(spec):
        whens = []
        for v in p["values"]:
            m = PERIOD.match(v)
            cond = "TRUE" if v == ALL else (f"DATEDIFF('{LEVEL[m.group(2)]}', [{field}], {{FIXED : MAX([{field}])}}) "
                                            f"< {m.group(1)}")
            whens.append(f"WHEN {_lit(v)} THEN {cond}")
        out.append({"name": period_calc(p["name"]), "formula": f"CASE [{p['name']}] {' '.join(whens)} END"})
    for s in switches(spec):
        for v in s["views"]:
            out.append({"name": switch_calc(s, v), "formula": f"[{s['parameter']}] = {_lit(v)}"})
    return out


def check(spec, params, columns):
    """Spec checks (ValueError). params: {name: params.Parameter}; columns: {CSV column: datatype}."""
    sheets = {s["name"]: s for s in spec["sheets"]}
    for p in spec.get("parameters", []):
        c = p.get("control")
        if c == "radio" and p["type"] != "string":
            raise ValueError(f"Parameter '{p['name']}': radio buttons list the values of a string parameter")
    for s in buttons(spec) + switches(spec):
        where = f"Sheet '{s['name']}'"
        name = s["parameter"]
        if name not in params:
            raise ValueError(f"{where}: parameter '{name}' is not declared (parameters: {sorted(params) or 'none'})")
        if params[name].values is None:
            raise ValueError(f"{where}: parameter '{name}' is a range; {s['type']} take a string parameter's values")
    seen = [s["parameter"] for s in buttons(spec)]
    dup = sorted({n for n in seen if seen.count(n) > 1})
    if dup:
        raise ValueError(f"Parameters {dup} have two buttons sheets; one set of buttons per parameter")
    for p, field in periods(spec):
        where = f"Parameter '{p['name']}'"
        if p["type"] != "string":
            raise ValueError(f"{where}: a period switch is a string parameter of L<N><D|W|M|Q|Y> and All")
        if columns.get(field) != "date":
            raise ValueError(f"{where}: period field '{field}' must be a date column of the data "
                             f"(got {columns.get(field, 'no such column')})")
        bad = [v for v in p["values"] if v != ALL and not PERIOD.match(v)]
        if bad:
            raise ValueError(f"{where}: values {bad} are not periods: L<N> and D, W, M, Q or Y (L6M = the last 6 "
                             f"months up to the last date of the data), or All")
    placed = {}
    for s in switches(spec):
        where = f"Sheet '{s['name']}'"
        values = params[s["parameter"]].values
        if sorted(s["views"]) != sorted(values):
            raise ValueError(f"{where}: views {sorted(s['views'])} must be the values of '{s['parameter']}' "
                             f"{sorted(values)}: each value shows one view")
        for v, n in s["views"].items():
            if n not in sheets:
                raise ValueError(f"{where}: view '{v}' is sheet '{n}', which does not exist")
            if sheets[n]["type"] not in SWITCH_VIEWS:
                raise ValueError(f"{where}: view '{n}' is a {sheets[n]['type']}; a switch shows "
                                 f"{', '.join(SWITCH_VIEWS)}")
            if n in placed:
                raise ValueError(f"{where}: sheet '{n}' is already a view of switch '{placed[n]}'")
            placed[n] = s["name"]
    return placed


def check_sources(spec):
    """A switch in a book with several datasources (decisions/082): its flag calcs live in one datasource, so its
    views and the switch itself take the same one (the parameter is the book's)."""
    first = spec["datasources"][0]["name"]
    src = {s["name"]: s.get("datasource", first) for s in spec["sheets"]}
    for s in switches(spec):
        views = {n: src.get(n) for n in s["views"].values()}
        used = sorted({d for d in views.values() if d})
        if len(used) > 1:
            raise ValueError(f"Sheet '{s['name']}': its views take datasources {used} "
                             f"({', '.join(f'{n}: {d}' for n, d in views.items())}); a switch shows views of one "
                             f"datasource (decisions/082)")
        if used and src[s["name"]] != used[0]:
            raise ValueError(f"Sheet '{s['name']}': its views take datasource '{used[0]}', the switch "
                             f"'{src[s['name']]}'; give the switch \"datasource\": \"{used[0]}\" (its flag calcs live "
                             f"in its views' datasource, decisions/082)")


def check_grid(on_dash, spec):
    """A switch's views are drawn inside it: none of them stands in a grid of its own."""
    views = {n: s["name"] for s in switches(spec) for n in s["views"].values()}
    for n in on_dash:
        if n in views:
            raise ValueError(f"Sheet '{n}' is a view of switch '{views[n]}': place the switch in the grid, not the "
                             f"sheet itself")


# ---- worksheets ---------------------------------------------------------------------------------------------
def expand(s, params):
    """A buttons sheet -> one button worksheet per value of its parameter, in the parameter's order."""
    return [{"name": f"{s['name']} · {v}", "type": BUTTON, "buttons": s, "value": v}
            for v in params[s["parameter"]].values]


def shape(b, s):
    """sheet_shape of a button: the value as text, colored by the current-value flag."""
    from .build import Field
    p = s["buttons"]["parameter"]
    text = Field(b.col(value_calc(p, s["value"])), "dim")
    flag = Field(b.col(active_calc(p, s["value"])), "dim")
    return [text, flag], None, None, [("color", b.q(flag.name)), ("text", b.q(text.name))], True, None


def label(b, pane, s, fields):
    ft = ET.SubElement(ET.SubElement(pane, "customized-label"), "formatted-text")
    ET.SubElement(ft, "run", bold="true", fontsize=str(FONT["toggle"])).text = f"<{b.q(fields[0].name)}>"


def palettes(b):
    """The current value in the accent, the others muted."""
    out = {}
    for p in b.worksheets:
        if p["type"] == BUTTON:
            col = b.calc_cols[active_calc(p["buttons"]["parameter"], p["value"])].name
            out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", COLOR["muted"])])
    return out


def min_px():
    """Height of a button zone: one line at the button font, the pane padding and its margins."""
    return design.header_px([(FONT["toggle"], 1)]) + design.TILE_TEXT_PAD_PX


# ---- period filter (a shared filter on the period calc) -----------------------------------------------------
def period_fields(b):
    """The period calcs as dimensions: every worksheet depends on them and lists them in its slices."""
    from .build import Field
    return [Field(b.col(period_calc(p["name"])), "dim") for p, _ in periods(b.spec)]


def write_period_filter(sv, b, f):
    """As SuperMart writes its date parameter filter in the shared view: member true, with its target."""
    flt = ET.SubElement(sv, "filter", {"class": "categorical", "column": b.q(f.name)})
    u = lambda k: f"{{{USER_NS}}}{k}"  # noqa: E731
    ET.SubElement(flt, "groupfilter", {"function": "member", "level": f.name, "member": "true",
                                       u("ui-domain"): "database", u("ui-enumeration"): "inclusive",
                                       u("ui-marker"): "enumerate"})
    ET.SubElement(flt, "target", field=b.q(f.name))


def period_rows(spec, calcs_, rows):
    """Rows the period filters keep at the parameters' current values (expected.py)."""
    for p, _ in periods(spec):
        rows = [r for r in rows if calcs_.row_value(period_calc(p["name"]), r) is True]
    return rows


# ---- parameter actions --------------------------------------------------------------------------------------
def write_actions(parent, b, dashes, start):
    """<edit-parameter-action> per button on each dashboard that shows it, after the filter actions and their
    dependencies; numbered on from start, written in name order as Desktop sorts them (Citizen, SuperMart)."""
    acts = []
    k = start
    for d, on_dash in dashes:
        for name in on_dash:
            s = next(x for x in b.spec["sheets"] if x["name"] == name)
            if s["type"] != BUTTONS:
                continue
            p = b.params[s["parameter"]]
            for part in b.physical[name]:
                ident = uuid.uuid5(_ID_NS, f"{d['name']}/{part['name']}").hex.upper()
                acts.append((f"[Action{k}_{ident}]", d["name"], part, p))
                k += 1
    if not acts:
        return
    el = parent.find("actions")
    if el is None:
        el = ET.SubElement(parent, "actions")
    for name, dash, part, p in sorted(acts, key=lambda a: a[0]):
        x = ET.SubElement(el, "edit-parameter-action", caption=part["name"], name=name)
        ET.SubElement(x, "activation", type="on-select")
        ET.SubElement(x, "source", dashboard=dash, type="sheet", worksheet=part["name"])
        ET.SubElement(x, "agg-type", type="attr")
        ET.SubElement(x, "clear-option", type="do-nothing", value="s:LROOT:")  # keep the value when unselected
        ps = ET.SubElement(x, "params")
        col = b.calc_cols[value_calc(p.name, part["value"])].name
        ET.SubElement(ps, "param", name="source-field", value=b.q(f"[none:{col}:nk]"))
        ET.SubElement(ps, "param", name="target-parameter", value=p.ref)


# ---- dynamic zone visibility --------------------------------------------------------------------------------
def switch_cell(b, parent, s, box, size):
    """A switch in its grid cell: a horizontal container with one container per view, each drawn as an ordinary cell
    (block header and sheet; a registry's column titles too); the views but the one of the parameter's default are
    hidden-by-user. Each view's container is recorded for the datagraph: (dashboard simple-id, dashboard name, zone
    id, flag field). Called with the switch's source current (decisions/083): the flag calc is a field of its
    datasource.

    The container is a layout-basic, like a grid cell (decisions/082): Desktop keeps the zones of a free layout as
    written, while a vertical flow (042) restacks a registry's side-by-side titles and fixes the sheet's height on
    save. Desktop writes hidden-by-user on every zone inside a hidden container: so does this."""
    from .build import _sub
    x, y, w, h = box
    row = _sub(parent, "zone", h=str(h), id=b._zid(), param="horz", type_v2="layout-flow", w=str(w), x=str(x),
               y=str(y))
    default = b.params[s["parameter"]].default
    for v in b.params[s["parameter"]].values:
        z = _sub(row, "zone", h=str(h), id=b._zid(), type_v2="layout-basic", w=str(w), x=str(x), y=str(y))
        b._grid(z, [[s["views"][v]]], box, [1], size)
        if v != default:
            for e in z.iter("zone"):
                e.set("hidden-by-user", "true")
        b.dzv.append((b.dash_uuid, b.spec["dashboard"]["name"], z.get("id"),
                      f"[{b.ds}].[{b.calc_cols[switch_calc(s, v)].name}]"))


def datagraph(wb, b):
    """<datagraph> after the windows: per hidden-able container a field node (its flag calc) and a zone
    visibility node, joined by an edge from the field's value to the zone's visibility input. As Desktop saves it
    (decisions/082, resave): the edges by their 'from' guid. The subgraph pairs and the nodes Desktop writes in an
    order of its own (a hash set, no rule from 4 books; the same nodes under other guids change places, 168): here
    pairs fields then zones, last to first, nodes fields then zones, and resave / round-trip match by node-guid."""
    if not b.dzv:
        return
    sub = ET.SubElement(ET.SubElement(wb, "datagraph"), "graph")
    gid = lambda *k: str(uuid.uuid5(_ID_NS, "/".join(k)))  # noqa: E731
    run = gid("subgraph")
    ET.SubElement(ET.SubElement(sub, "properties"), "default-execution-subgraph-guid", value=run)
    pairs = ET.SubElement(sub, "node-execution-subgraphs")
    nodes = ET.SubElement(sub, "nodes")
    fields, zones, edges = [], [], []
    for dash, name, zone, field in b.dzv:  # guids from the dashboard's name: its simple-id is new on every build
        out, inp = gid(name, zone, "value"), gid(name, zone, "visibility")
        fields.append({"fieldname": field, "fieldname-input-guid": gid(name, zone, "input"),
                       "node-guid": gid(name, zone, "field"), "value-output-guid": out})
        zones.append({"dashboard-identifier": dash, "node-guid": gid(name, zone, "zone"),
                      "visibility-input-guid": inp, "zone-id": zone})
        edges.append((out, inp))
    for n in fields[::-1] + zones[::-1]:
        ET.SubElement(pairs, "pair", {"execution-subgraph-guid": run, "node-guid": n["node-guid"]})
    for n in fields:
        ET.SubElement(nodes, "single-value-field-node", n)
    for n in zones:
        ET.SubElement(nodes, "dashboard-zone-visibility-node", n)
    e = ET.SubElement(sub, "edges")
    for a, c in sorted(edges):
        ET.SubElement(e, "edge", {"from": a, "to": c})
    ET.SubElement(sub, "pin-values")


def manifest_flags(manifest, b):
    """Parameter action and zone visibility flags in Desktop's (alphabetical) order."""
    flags = (ACTION_FLAGS if buttons(b.spec) else ()) + (DZV_FLAGS if switches(b.spec) else ())
    for flag in flags:
        if manifest.find(flag) is not None:
            continue
        later = [i for i, e in enumerate(manifest) if e.tag > flag]
        manifest.insert(later[0] if later else len(manifest), ET.Element(flag))


RADIO_FRAME_PX = 6  # the list box's frame: without it Desktop scrolls a radio of 3 values (golden_switch_registry)


def radio_px(p):
    """Height of a radio card: its title line and a line per value, inside the card's margins."""
    return (len(p.values) + 1) * design.LEGEND_LINE_PX + 2 * SPACE["zone_margin"] + RADIO_FRAME_PX
