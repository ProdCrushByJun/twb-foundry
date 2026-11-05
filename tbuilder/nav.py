"""Several dashboards and the navigation between them (decisions/040).

References (reference books): Citizen Service (Desktop 2025.1) runs a row of tabs over 4 dashboards,
the current one in the text color over an accent underline; Admissions (2024.3) and Cutest put the buttons in the
sidebar, the current one bold on its own face; E-Commerce a rail of icon buttons. All of them: a text button
(dashboard-object) with action 'tabdoc:goto-sheet window-id="{uuid}"', where the uuid is the simple-id of the target's
<window>, not of the <dashboard>.

Here every nav item is such a button, the current dashboard's one included (it goes to itself, as in Admissions):
one shape the gate can check on every dashboard.
"""
import json
import math
import uuid
import xml.etree.ElementTree as ET

from . import design, shell, theme
from .design import COLOR, FONT, SPACE

TABS, SIDEBAR = "tabs", "sidebar"
# Dashboard options that make the workbook's shell: one value for all dashboards (the shell is built once: its
# sheets, calcs, images and manifest flags)
SHELL_KEYS = ("sidebar", "topbar", "theme", "theme_font", "accent", "data_as_of")
BUTTON_FLAGS = ("BasicButtonObject", "BasicButtonObjectTextSupport")  # Citizen's text buttons
GOTO = 'tabdoc:goto-sheet window-id="{}"'


def dashboards(spec):
    """The dashboard specs: 'dashboards', or the one 'dashboard'."""
    return spec["dashboards"] if "dashboards" in spec else [spec["dashboard"]]


def primary(spec):
    """The spec as the single-dashboard code reads it: 'dashboard' is the first dashboard (the one that opens; the
    shell is the same on all, see SHELL_KEYS)."""
    if "dashboards" not in spec:
        return spec
    return {**spec, "dashboard": spec["dashboards"][0]}


def style(spec):
    return spec.get("nav", {}).get("style")


def items(spec):
    """[(dashboard name, caption)] of the nav buttons in order."""
    if "nav" not in spec:
        return []
    given = spec["nav"].get("items")
    if given is None:
        return [(d["name"], d["name"]) for d in dashboards(spec)]
    return [(i["dashboard"], i.get("label", i["dashboard"])) for i in given]


def check(spec):
    """Spec checks of several dashboards and the nav (ValueError)."""
    dashes = dashboards(spec)
    names = [d["name"] for d in dashes]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f"Two dashboards are named {dup}: Tableau keeps one object per name")
    for k in SHELL_KEYS:
        values = {json.dumps(d.get(k, theme.CARDS if k == "theme" else None), sort_keys=True) for d in dashes}
        if len(values) > 1:
            raise ValueError(f"Dashboards differ in '{k}': the shell (sidebar, topbar, theme, theme_font, accent, "
                             f"data_as_of) is one for the workbook; give every dashboard the same '{k}'")
    if "nav" not in spec:
        return
    if "dashboards" not in spec:
        raise ValueError("nav needs 'dashboards' (two or more) to navigate between")
    got = [n for n, _ in items(spec)]
    for n in got:
        if n not in names:
            raise ValueError(f"nav item '{n}' is not a dashboard (dashboards: {names})")
    dup = sorted({n for n in got if got.count(n) > 1})
    if dup:
        raise ValueError(f"nav lists the dashboards {dup} twice")
    missing = [n for n in names if n not in got]
    if missing:
        raise ValueError(f"Dashboards {missing} have no nav button: nothing leads to them, and their own nav would "
                         f"not mark where the user is; list every dashboard in nav.items")
    if style(spec) == SIDEBAR and not dashes[0].get("sidebar"):
        raise ValueError("nav style 'sidebar' puts the buttons in the dashboard sidebar; give the dashboards a "
                         "sidebar (true or a brand one) or use style 'tabs'")


def window_ids(spec):
    """{dashboard name: simple-id uuid of its <window>}: the buttons' targets, made before any dashboard is drawn."""
    return {d["name"]: "{" + str(uuid.uuid4()).upper() + "}" for d in dashboards(spec)}


def manifest_flags(manifest, spec):
    """Text button flags in Desktop's (alphabetical) order; the shell may have added them already."""
    if "nav" not in spec:
        return
    for flag in BUTTON_FLAGS:
        if manifest.find(flag) is not None:
            continue
        later = [i for i, e in enumerate(manifest) if e.tag > flag]
        manifest.insert(later[0] if later else len(manifest), ET.Element(flag))


# ---- zones ------------------------------------------------------------------------------------------------
def _button(b, parent, target, caption, box, active, fg, face=None, margin=design.ZONE, fixed=None):
    """A text button that opens the target dashboard (Citizen's tabs, Admissions' sidebar buttons). fixed: its
    height in px inside its margins, in a vertical flow (a free button there grows to 52px on Desktop's Save As,
    decisions/092)."""
    from .build import _sub  # build imports this module
    x, y, w, h = box
    z = _sub(parent, "zone", **({"fixed_size": str(fixed)} if fixed else {}), h=str(h), id=b._zid(),
             **({"is_fixed": "true"} if fixed else {}), type_v2="dashboard-object", w=str(w), x=str(x), y=str(y))
    btn = _sub(z, "button", action=GOTO.format(b.window_ids[target]), button_type="text")
    state = _sub(btn, "button-visual-state")
    _sub(state, "caption").text = caption
    # no fontsize: Desktop 2025.1 drops fontsize='10' from the caption on Save As (decisions/061); FONT["nav"] still
    # sizes the tab widths below
    _sub(state, "button-caption-font-style", **({"bold": "true"} if active else {}), fontcolor=fg)
    if face:
        _sub(state, "format", attr="background-color", value=face)
    b._zone_style(z, margin)


def tab_px(spec):
    """Width of one tab, its margins included: the longest caption at the nav font plus padding (equal tabs)."""
    chars = max(len(c) for _, c in items(spec))
    text = math.ceil(chars * FONT["nav"] * 4 / 3 * design.CHAR_EM) + 2 * design.NAV_TAB_PAD_PX
    return max(design.NAV_TAB_MIN_PX, text) + 2 * SPACE["zone_margin"]


def tabs_px():
    """Height of the tab row: the button with its margins, the underline under it with its bottom margin."""
    m = SPACE["zone_margin"]
    return design.NAV_BUTTON_PX + 2 * m + design.NAV_UNDERLINE_PX + m


def tabs(b, root, d, box, size):
    """Row of tabs at the top of the dashboard (Citizen Service): each a vertical flow of the button and a line
    under it, the accent line under the current dashboard; an empty zone fills the row after the tabs. Returns the
    row height in zone units, 0 without tabs."""
    from .build import _sub
    if style(b.spec) != TABS:
        return 0
    x, y, w = box
    width, height = size
    nav, m = items(b.spec), SPACE["zone_margin"]
    tw = tab_px(b.spec)
    if len(nav) * tw > w * width // 100000:
        raise ValueError(f"Dashboard '{d['name']}': {len(nav)} tabs of {tw}px are wider than the dashboard; shorten "
                         f"the nav labels or widen the dashboard")
    h = b._units(tabs_px(), height)
    bh = b._units(design.NAV_BUTTON_PX + 2 * m, height)
    row = _sub(root, "zone", h=str(h), id=b._zid(), param="horz", type_v2="layout-flow", w=str(w), x=str(x),
               y=str(y))
    for k, (target, caption) in enumerate(nav):
        tx, tx1 = x + b._units(k * tw, width), x + b._units((k + 1) * tw, width)
        tab = _sub(row, "zone", fixed_size=str(tw), h=str(h), id=b._zid(), is_fixed="true", param="vert",
                   type_v2="layout-flow", w=str(tx1 - tx), x=str(tx), y=str(y))
        active = target == d["name"]
        _button(b, tab, target, caption, (tx, y, tx1 - tx, bh), active, COLOR["text"] if active else COLOR["muted"])
        line = _sub(tab, "zone", fixed_size=str(design.NAV_UNDERLINE_PX), h=str(h - bh), id=b._zid(),
                    is_fixed="true", type_v2="empty", w=str(tx1 - tx), x=str(tx), y=str(y + bh))
        b._zone_style(line, {"top": 0, "right": m, "bottom": m, "left": m},
                      background=COLOR["accent"] if active else None)
    end = x + b._units(len(nav) * tw, width)
    if end < x + w:
        b._zone_style(_sub(row, "zone", h=str(h), id=b._zid(), type_v2="empty", w=str(x + w - end), x=str(end),
                           y=str(y)))
    return h


def sidebar_px(spec):
    """Height of the nav buttons in a sidebar, 0 without them."""
    if style(spec) != SIDEBAR:
        return 0
    return len(items(spec)) * (design.NAV_BUTTON_PX + 2 * SPACE["zone_margin"])


def sidebar(b, side, d, box, size, panel):
    """Nav buttons stacked in the sidebar under the title (Admissions): the current one bold on a white face, the
    others on the panel's own color. panel: the sidebar's background. Returns the new top (zone units)."""
    cx, cy, cw = box
    if style(b.spec) != SIDEBAR:
        return cy
    zh = b._units(design.NAV_BUTTON_PX + 2 * SPACE["zone_margin"], size[1])
    brand = shell.brand(d)
    rest = shell.text_color(brand) if brand else COLOR["text"]
    if brand:
        ok = shell.contrast(brand["color"], COLOR["button_bg"]) >= design.MIN_CONTRAST
        current = brand["color"] if ok else COLOR["shell_dark"]
    else:
        current = COLOR["text"]
    for target, caption in items(b.spec):
        active = target == d["name"]
        _button(b, side, target, caption, (cx, cy, cw, zh), active, current if active else rest,
                face=COLOR["button_bg"] if active else panel, fixed=design.NAV_BUTTON_PX)
        cy += zh
    return cy
