"""Dashboard actions (dashboard.actions): a click or hover on a sheet's marks filters, highlights, opens a link or
sets a parameter; and the Show/Hide button of the header's filter cards (dashboard.filter_toggle).

The XML is what Desktop 2025.1 writes for Dashboard > Actions > Add Action (decisions/017, 160):
- filter (017): one source sheet; the targets are the dashboard's sheets minus the 'exclude' list; 'All fields' is
  special-fields=all, selected fields are a tsl link expression plus their datasource dependencies; clearing the
  selection shows all values (auto-clear) or, with on-empty=none, excludes all values. The source sheet itself is
  never filtered by its own action.
- highlight (160): the same <action> with command tsc:brush; selected fields are named by their captions
  (field-captions, 'MONTH(Order Date)' for a period), no link and no dependencies (Admissions, Ads Campaigns,
  Internet Access 2025.1).
- url (160): an <action> with a <link> (no <url-action-type>: Desktop 2025.1 refuses it) and no command; the URL names a field of the clicked mark as <[Field]>; on
  'menu' the action has no activation, the link is in the tooltip menu (references).
- parameter (160): an <edit-parameter-action> whose source field is the clicked mark's dimension; clearing the
  selection keeps the value (do-nothing) or sets a fixed one (assign-fixed-value: ER's 'Filter by Status' -> All).
Each action is signed in its source block's subtitle, as the reference authors do ('Sum of sales | Click to filter').
"""
import re
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote

from . import dates, design, strings

SOURCE_TYPES = ("bar", "line", "area", "table", "heatmap", "registry", "map", "scatter")  # sheets with dimension marks to click
# hints after a subtitle ('Click to filter') and captions ('Source → All'): tbuilder/strings.py by locale (177)
CAPTION = {"month": "MONTH", "year": "YEAR", "quarter": "QUARTER", "week": "WEEK", "day": "DAY"}  # field-captions
URL_FIELD = re.compile(r"<([^<>]+)>")  # <Field> in a URL action's spec
PARAM_FLAGS = ("ParameterAction", "ParameterActionClearSelection")  # in all 13 references with parameter actions
# ZoneVisibilityControl, which HelpDesk / StudentPortrait also carry, Desktop drops on Save As while the cards are
# shown at open and adds while they are hidden
TOGGLE_FLAGS = ("BasicButtonObject", "BasicButtonObjectTextSupport", "CollapsiblePane")
TOGGLE_CAPTION = ("hide_filters", "show_filters")  # visual state 0: the cards are shown; 1: hidden (HelpDesk RWFD)
_ID_NS = uuid.UUID("6c1f0b8e-3a52-4f0e-9a3c-0d7e2b1c5a17")  # stable action ids: a rebuild matches its golden


def actions(spec):
    return spec["dashboard"].get("actions", [])


def kind(a):
    return a.get("type", "filter")


def on(a):
    return a.get("on", "select")


def params_used(spec):
    """Parameters set by parameter actions on any dashboard: used, though no calc names them."""
    return {a["parameter"] for d in spec.get("dashboards", [spec.get("dashboard", {})]) for a in d.get("actions", [])
            if kind(a) == "parameter"}


def dims(s):
    """Dimension fields of a source sheet: the fields its marks can filter by."""
    t = s["type"]
    if t == "bar":
        return [s["dimension"]] + ([s["color"]] if s.get("color") else [])
    if t in ("table", "heatmap"):  # a table may have two row fields (decisions/045)
        return ([s["rows"]] if isinstance(s["rows"], str) else list(s["rows"])) + [s["cols"]]
    if t == "registry":
        return list(s["rows"])
    if t == "scatter":  # a click on a dot: its member (polish-26)
        return [s["detail"]]
    if t == "map":  # a click on a place (decisions/046)
        return [s["geo"]["field"]]
    if t in ("line", "area"):
        return [s["color"]] if s.get("color") else []
    return []


def hint(a, spec=None):
    """The action's hint after the source's subtitle: its own 'hint', else the default in the spec's locale."""
    return a.get("hint", strings.t(spec, ("hint", kind(a), on(a))))


def sign(s, spec):
    """The sheet with its actions' hints after its subtitle (the block header): an action's own 'hint' always, the
    default one of its type only with dashboard.action_hints (decisions/183)."""
    on_ = bool(spec["dashboard"].get("action_hints"))
    hints = list(dict.fromkeys(hint(a, spec) for a in actions(spec)
                               if a["source"] == s["name"] and ("hint" in a or on_)))
    if not hints:
        return s
    return {**s, "subtitle": design.HINT_SEPARATOR.join(([s["subtitle"]] if s.get("subtitle") else []) + hints)}


def level_of(s, f):
    """The date level a source sheet shows the field f at (a bar's dimension or a heatmap's cols with date_level),
    else None: the marks of such a sheet are periods, so the action filters by the period (decisions/128)."""
    if s["type"] == "bar" and s.get("dimension") == f:
        return dates.bar_level(s)
    if s["type"] == "heatmap" and s.get("cols") == f:
        return dates.heat_level(s)
    return None


def _physical(b, names):
    return [p["name"] for n in names for p in b.physical[n]]


def _excluded(b, a, on_dash):
    """Dashboard sheets the action does not filter (Desktop's 'exclude' list), in reading order."""
    targets = a.get("targets", "all")
    if targets == "all":
        if all(b.owns(n) for n in on_dash):
            return []
        targets = [n for n in on_dash if b.owns(n)]  # all of its datasource's sheets (decisions/083)
    from .insight import dashboard_sheets  # a sheet's insight line goes with it: a filtered phrase has holes
    keep = set(_physical(b, targets)) | set(dashboard_sheets(b, set(targets)))
    return [n for n in _physical(b, on_dash) + dashboard_sheets(b, set(on_dash)) if n not in keep]


def _check_field(b, s, f, where, what="action fields"):
    if f not in dims(s):
        raise ValueError(f"{where}: '{f}' is not a dimension of the source sheet (dimensions: {dims(s)})")
    if f in b.calc_cols:
        raise ValueError(f"{where}: '{f}' is a calculated field; {what} take CSV columns only for now")


def check(b, on_dash):
    """Spec-level checks; on_dash = the dashboard's sheet names in reading order."""
    acts = actions(b.spec)
    if acts and not b.block_headers:
        raise ValueError("Dashboard actions are signed in the source block's subtitle: they need block_headers")
    sheets = {s["name"]: s for s in b.spec["sheets"]}
    for i, a in enumerate(acts, 1):
        src = a["source"]
        where = f"Action {i} (source '{src}')"
        if src not in on_dash:
            raise ValueError(f"{where}: the source sheet is not on the dashboard")
        s = sheets[src]
        if s["type"] not in SOURCE_TYPES:
            raise ValueError(f"{where}: a {s['type']} sheet has no dimension marks to click; the source must be "
                             f"one of {', '.join(SOURCE_TYPES)}")
        if kind(a) == "url":
            _check_url(b, s, a, where)
            continue
        if kind(a) == "parameter":
            _check_parameter(b, s, a, where)
            continue
        targets = a.get("targets", "all")
        if targets == "all" and len(on_dash) == 1:
            raise ValueError(f"{where}: the source is the only sheet on the dashboard, nothing to {kind(a)}")
        for t in [] if targets == "all" else targets:
            if t not in on_dash:
                raise ValueError(f"{where}: target '{t}' is not on the dashboard")
            if t == src:
                raise ValueError(f"{where}: a sheet is not filtered by its own action; remove it from targets")
        for f in a.get("fields", []):
            _check_field(b, s, f, where)
            if "~" in f:
                raise ValueError(f"{where}: field '{f}' contains '~', the separator of Tableau's action link")
            if kind(a) == "highlight" and "," in f:
                raise ValueError(f"{where}: field '{f}' contains ',', the separator of Tableau's highlight fields")
        for n in _excluded(b, a, on_dash):
            if "," in n:
                raise ValueError(f"{where}: sheet '{n}' contains ',', the separator of Tableau's exclude list; "
                                 f"rename it")


def _check_url(b, s, a, where):
    """The URL's <Field>s are plain dimensions of the clicked mark: a period of a date names no single value."""
    for f in URL_FIELD.findall(a["url"]):
        _check_field(b, s, f, where, "URL fields")
        if level_of(s, f):
            raise ValueError(f"{where}: the sheet shows '{f}' as periods; a URL takes the field as a value, not a "
                             f"period")


def _check_parameter(b, s, a, where):
    """A string parameter with a list of values gets the clicked member: every member of the field and the value on
    clearing must be in the list (Tableau sets a list parameter to its values only)."""
    f, name = a["field"], a["parameter"]
    _check_field(b, s, f, where, "parameter actions")
    if level_of(s, f):
        raise ValueError(f"{where}: the sheet shows '{f}' as periods; a parameter action takes a field of members")
    if name not in b.params:
        raise ValueError(f"{where}: parameter '{name}' is not declared (parameters: {sorted(b.params) or 'none'})")
    p = b.params[name]
    col = b.col(f)
    if p.datatype != "string" or p.values is None or col.datatype != "string":
        raise ValueError(f"{where}: a parameter action sets a string parameter with a list of values from a string "
                         f"field; '{name}' is {p.datatype}{'' if p.values is not None else ' (range)'}, '{f}' is "
                         f"{col.datatype}")
    missing = [v for v in col.distinct if v not in p.values]
    if missing:
        raise ValueError(f"{where}: values {missing[:5]} of '{f}' are not in the values of parameter '{name}'; a "
                         f"click on them would set nothing")
    if "clear" in a and a["clear"] not in p.values:
        raise ValueError(f"{where}: clear value {a['clear']!r} is not one of the values of parameter '{name}'")


def _caption(a, spec=None):
    if kind(a) == "url":
        return f"{a['source']} → {a['url']}"
    if kind(a) == "parameter":
        return f"{a['source']} → {a['parameter']}"
    targets = a.get("targets", "all")
    return f"{a['source']} → {strings.t(spec, 'all') if targets == 'all' else ', '.join(targets)}"


def _field_caption(sheet, f):
    """The field as Tableau captions it in a highlight action: the column, or 'MONTH(Order Date)' for a period."""
    level = level_of(sheet, f)
    return f"{CAPTION[level]}({f})" if level else f


def _ident(dash, i, a):
    return uuid.uuid5(_ID_NS, f"{dash}/{i}/{a['source']}").hex.upper()


def write(parent, b, dashes):
    """<actions> after the shared views, before the worksheets (Desktop 2025.1 order). dashes: [(dashboard spec,
    its sheet names in reading order)]; each dashboard's actions act on it alone (decisions/040), numbered on.
    Parameter actions come later (write_parameters), after the dependencies."""
    acts = [(d["name"], a, on_dash) for d, on_dash in dashes for a in d.get("actions", [])]
    if not any(kind(a) != "parameter" for _, a, _ in acts):
        return
    el = ET.SubElement(parent, "actions")
    used = {}
    for i, (dash, a, on_dash) in enumerate(acts, 1):
        if kind(a) == "parameter":
            continue
        with b._source_of(a["source"]):  # its datasource's fields and sheets (decisions/083)
            caption = _caption(a, b.spec)
            x = ET.SubElement(el, "action", caption=caption, name=f"[Action{i}_{_ident(dash, i, a)}]")
            if kind(a) == "url":
                _url(x, b, a, dash)
                continue
            if on(a) != "menu":
                ET.SubElement(x, "activation", {"auto-clear": "true", "type": "on-" + on(a)})
            ET.SubElement(x, "source", dashboard=dash, type="sheet", worksheet=a["source"])
            from .build import Field  # build imports this module
            sheet = next(s for s in b.spec["sheets"] if s["name"] == a["source"])
            if kind(a) == "highlight":
                cmd = ET.SubElement(x, "command", command="tsc:brush")
                captions = ",".join(_field_caption(sheet, f) for f in a.get("fields", []))
                params = [("exclude", ",".join(_excluded(b, a, on_dash))), ("field-captions", captions),
                          ("special-fields", "" if captions else "all"), ("target", dash)]
                for name, value in params:
                    if value:
                        ET.SubElement(cmd, "param", name=name, value=value)
                continue
            cols = [b.col(f) for f in a.get("fields", [])]
            insts = [Field(c, "date", level_of(sheet, f), discrete=True) if level_of(sheet, f) else None
                     for f, c in zip(a.get("fields", []), cols)]  # a period of a date: its column instance
            if cols:
                refs = [b.q(i.name if i else f"[{c.name}]") for c, i in zip(cols, insts)]
                expr = "&".join(f"{quote(r, safe='')}~s0=<{r}~na>" for r in refs)
                ET.SubElement(x, "link", {"caption": caption, "delimiter": ",", "escape": "\\",
                                          "expression": f"tsl:{quote(dash, safe='')}?{expr}", "include-null": "true",
                                          "multi-select": "true", "url-escape": "true"})
                u = used.setdefault(b.source_of(a["source"]), ({}, {}))
                u[0].update({c.name: c for c in cols})
                u[1].update({i.name: i for i in insts if i})
            cmd = ET.SubElement(x, "command", command="tsc:tsl-filter")
            params = [("exclude", ",".join(_excluded(b, a, on_dash))),  # Desktop writes the params by name
                      ("on-empty", "none" if a.get("clear", "show_all") == "exclude" else ""),
                      ("special-fields", "" if cols else "all"), ("target", dash)]
            for name, value in params:
                if value:
                    ET.SubElement(cmd, "param", name=name, value=value)
    for src in sorted(used):  # selected fields: their columns, as in a sheet's dependencies, by source
        with b._source(src):
            b._ds_ref(el)
            deps = ET.SubElement(el, "datasource-dependencies", datasource=b.ds)
            cols, insts = used[src]
            for name in sorted(cols):
                b.column(deps, cols[name])
            for name in sorted(insts):  # Desktop orders column-instances by name
                i = insts[name]
                ET.SubElement(deps, "column-instance", column=f"[{i.col.name}]", derivation=i.derivation, name=i.name,
                              pivot="key", type=i.type)


def _url(x, b, a, dash):
    """A URL action: <Field> becomes <[Field]> (as in the reference). No <url-action-type> in the link: Desktop 2025.1
    refuses it (the link is EMPTY in its schema), though RWFD Call Center (2022.1) wrote 'browser' there."""
    if on(a) != "menu":
        ET.SubElement(x, "activation", type="on-" + on(a))
    ET.SubElement(x, "source", dashboard=dash, type="sheet", worksheet=a["source"])
    ET.SubElement(x, "link", caption="", expression=URL_FIELD.sub(lambda m: f"<[{b.col(m.group(1)).name}]>", a["url"]))


def _clear_value(p, v):
    """A parameter value as a clear-option writes it: s:LROOT:<text> for a string (ER, press)."""
    return f"s:LROOT:{v}"


def write_parameters(parent, b, dashes):
    """<edit-parameter-action> per parameter action, after the filter actions and their dependencies (and after the
    buttons' ones, interact.write_actions): every edit-parameter-action in name order, as Desktop sorts them."""
    acts = [(d["name"], a) for d, _ in dashes for a in d.get("actions", [])]  # numbered as in write
    acts = [(dash, i, a) for i, (dash, a) in enumerate(acts, 1) if kind(a) == "parameter"]
    if not acts:
        return
    el = parent.find("actions")
    if el is None:
        el = ET.SubElement(parent, "actions")
    for dash, i, a in acts:
        with b._source_of(a["source"]):
            p = b.params[a["parameter"]]
            x = ET.SubElement(el, "edit-parameter-action", caption=_caption(a, b.spec),
                              name=f"[Action{i}_{_ident(dash, i, a)}]")
            ET.SubElement(x, "activation", type="on-select")
            ET.SubElement(x, "source", dashboard=dash, type="sheet", worksheet=a["source"])
            ET.SubElement(x, "agg-type", type="attr")
            if "clear" in a:
                ET.SubElement(x, "clear-option", type="assign-fixed-value", value=_clear_value(p, a["clear"]))
            else:  # keep the value when the selection is cleared
                ET.SubElement(x, "clear-option", type="do-nothing", value="s:LROOT:")
            ps = ET.SubElement(x, "params")
            ET.SubElement(ps, "param", name="source-field", value=b.q(f"[none:{b.col(a['field']).name}:nk]"))
            ET.SubElement(ps, "param", name="target-parameter", value=p.ref)
    epa = [e for e in el if e.tag == "edit-parameter-action"]
    for e in epa:
        el.remove(e)
    el.extend(sorted(epa, key=lambda e: e.get("name")))


def _insert_flags(manifest, flags):
    for flag in flags:
        if manifest.find(flag) is not None:
            continue
        later = [i for i, e in enumerate(manifest) if e.tag > flag]
        manifest.insert(later[0] if later else len(manifest), ET.Element(flag))


def manifest_flags(manifest, b):
    """Parameter action and Show/Hide button flags in Desktop's (alphabetical) order; others may have added them."""
    dashes = b.dashes
    if any(kind(a) == "parameter" for d in dashes for a in d.get("actions", [])):
        _insert_flags(manifest, PARAM_FLAGS)
    if any(d.get("filter_toggle") for d in dashes):
        _insert_flags(manifest, TOGGLE_FLAGS)
    if any(d.get("filter_toggle") == "hidden" for d in dashes):  # Desktop adds it for a zone hidden at open
        _insert_flags(manifest, ("ZoneVisibilityControl",))


# ---- Show/Hide button of the filter cards ----------------------------------------------------------------------
def toggle(d):
    """'shown' / 'hidden': the header's filter cards behind a Show/Hide button and their state at open; else None."""
    return d.get("filter_toggle")


def check_toggle(d, header_filters):
    if toggle(d) and not header_filters:
        raise ValueError(f"Dashboard '{d['name']}': filter_toggle shows and hides the filter cards of the dashboard "
                         f"header; it has none (a sidebar, no title, or no filter shown here)")


def toggle_px(spec=None):
    """Width of the button inside its margins: the longer caption, bold, at the button font, plus padding."""
    chars = max(len(strings.t(spec, c)) for c in TOGGLE_CAPTION)
    return round(chars * design.FONT["button"] * 4 / 3 * design.CHAR_EM) + 2 * design.NAV_TAB_PAD_PX


def toggle_button(b, parent, d, box, cards_zone):
    """The Show/Hide button (HelpDesk RWFD, StudentPortrait): a dashboard-object zone whose button toggles the cards'
    container (zone-ids); visual state 0 while the cards are shown, 1 while hidden (active-visual-state-index)."""
    from .build import _sub
    x, y, w, h = box
    z = _sub(parent, "zone", fixed_size=str(toggle_px(b.spec)), h=str(h), id=b._zid(), is_fixed="true",
             type_v2="dashboard-object", w=str(w), x=str(x), y=str(y))
    btn = _sub(z, "button", action="", **({"active_visual_state_index": "1"} if toggle(d) == "hidden" else {}),
               button_type="text")  # state 0 Desktop leaves unwritten
    _sub(btn, "toggle-action").text = (f'tabdoc:toggle-button-click-action window-id="{b.window_ids[d["name"]]}" '
                                       f'zone-id="{z.get("id")}" zone-ids=[{cards_zone.get("id")}]')
    for caption in TOGGLE_CAPTION:
        state = _sub(btn, "button-visual-state")
        _sub(state, "caption").text = strings.t(b.spec, caption)
        _sub(state, "button-caption-font-style", bold="true", fontcolor=design.COLOR["muted"])
    return z
