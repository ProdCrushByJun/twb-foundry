"""Dashboard shell (decisions/029): the brand sidebar, the app top bar with "Welcome, <name>", export buttons.

References (reference books): ER Operation, Call Center, Cutest Financial and Admissions put the brand
color on a left sidebar with a logo, the filters, PDF / PPT / Image buttons and a "Created by / Data source" footer;
SOC and Admissions run a dark app bar over the whole dashboard. The brand color stays in the shell, marks keep the
meaning colors (context/design-rules.md C7, C8).

XML shapes are Desktop's: export buttons from ER (2026.1) and Admissions (2024.3), text buttons and bitmap zones from
Citizen (2025.1, Desktop's own build), the quick-filter title color from Citizen's worksheet styles.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from . import colors, design, filters, params
from .design import COLOR, FONT, SPACE

EXPORT = {"pdf": "pdf", "ppt": "powerpoint", "image": "image"}  # spec -> Desktop's export type
CAPTION = {"pdf": "PDF", "ppt": "PPT", "image": "Image"}
WELCOME_SHEET = "Welcome"
FULL_NAME = "Full Name"  # calc FULLNAME(): the signed-in user's name (Desktop: the Windows user)
IMAGE_DIR = "Image"  # where Desktop packages dashboard images in a .twbx
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
# Desktop writes these with an export button (ER, Admissions) and with a text button (Citizen)
BUTTON_FLAGS = ("BasicButtonObject", "BasicButtonObjectTextSupport", "DashboardExportButton")


def brand(d):
    """The brand sidebar of a dashboard spec, None for none or the grey one (sidebar: true)."""
    s = d.get("sidebar")
    return s if isinstance(s, dict) else None


def welcome(spec):
    return bool(spec["dashboard"].get("topbar", {}).get("welcome"))


# ---- color -----------------------------------------------------------------------------------------------
def _luminance(hex_color):
    """WCAG relative luminance of '#rrggbb'."""
    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(hex_color[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG contrast ratio of two colors, 1..21."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_color(band):
    """Text on a brand color: the spec's own, otherwise white or dark, whichever reads better."""
    if band.get("text"):
        return band["text"]
    return max((COLOR["shell_light"], COLOR["shell_dark"]), key=lambda t: contrast(t, band["color"]))


def bands(spec):
    """(where, band) of every brand-colored part of the dashboard: its sidebar and its top bar."""
    d = spec["dashboard"]
    out = [("sidebar", brand(d)), ("topbar", d.get("topbar"))]
    return [(w, b) for w, b in out if b]


# ---- spec hooks -------------------------------------------------------------------------------------------
def calcs(spec):
    return [{"name": FULL_NAME, "formula": "FULLNAME()"}] if welcome(spec) else []


def sheets(b):
    """Worksheets the shell adds (not in spec.sheets): the top bar's "Welcome, <name>"."""
    if not welcome(b.spec):
        return []
    if any(s["name"] == WELCOME_SHEET for s in b.spec["sheets"]) or b.spec["dashboard"]["name"] == WELCOME_SHEET:
        raise ValueError(f"topbar.welcome adds a sheet named '{WELCOME_SHEET}': rename the sheet or dashboard "
                         f"that has this name")
    return [{"name": WELCOME_SHEET, "type": "welcome"}]


def shape(b):
    """sheet_shape of the welcome sheet: FULLNAME() on Text."""
    f = b._dim(FULL_NAME)
    return [f], None, None, [("text", b.q(f.name))], True, None


def files(spec, base_dir):
    """[(path in the package, source file)]: the logo picture, next to the spec."""
    logo = (brand(spec["dashboard"]) or {}).get("logo", {})
    if "image" not in logo:
        return []
    src = Path(base_dir) / logo["image"]
    if src.suffix.lower() not in IMAGE_TYPES:
        raise ValueError(f"sidebar.logo.image '{logo['image']}': not a picture Tableau shows "
                         f"({', '.join(IMAGE_TYPES)})")
    if not src.is_file():
        raise ValueError(f"sidebar.logo.image '{logo['image']}' not found next to the spec ({src})")
    return [(f"{IMAGE_DIR}/{src.name}", src)]


def manifest_flags(manifest, spec):
    """Button flags in Desktop's (alphabetical) order, when the sidebar has export buttons."""
    if not (brand(spec["dashboard"]) or {}).get("download"):
        return
    for flag in BUTTON_FLAGS:
        later = [i for i, e in enumerate(manifest) if e.tag > flag]
        manifest.insert(later[0] if later else len(manifest), ET.Element(flag))


def sheet_style(b, style, s):
    """The welcome sheet on the top bar color; the filter card titles of a brand sidebar in its text color
    (a filter card's title is formatted on the sheet it belongs to: Citizen, Desktop 2025.1)."""
    if s["type"] == "welcome":
        rule = colors._rule(style, "table", before=("worksheet", "dropline", "refline", "gridline", "zeroline",
                                                    "table-div"))
        ET.SubElement(rule, "format", attr="background-color", value=b.spec["dashboard"]["topbar"]["color"])
    sb = brand(b.spec["dashboard"])
    owners = b.filter_owners  # on every dashboard (decisions/040)
    if sb and s["name"] in owners:
        ET.SubElement(ET.SubElement(style, "style-rule", element="quick-filter-title"), "format", attr="color",
                      value=text_color(sb))  # the last rule in Desktop's order


def label(b, pane, s, fields):
    """"Welcome, <name>" in the top bar's text color."""
    fg = text_color(b.spec["dashboard"]["topbar"])
    ft = ET.SubElement(ET.SubElement(pane, "customized-label"), "formatted-text")
    ET.SubElement(ft, "run", fontcolor=fg, fontsize=str(FONT["shell_label"])).text = "Welcome, "
    ET.SubElement(ft, "run", bold="true", fontcolor=fg,
                  fontsize=str(FONT["shell_label"])).text = f"<{b.q(fields[0].name)}>"


# ---- zones ------------------------------------------------------------------------------------------------
def _text(b, parent, box, lines, color):
    """A text zone in one color: lines = [(text, pt, bold)]; '**' marks the bold words of a bold line."""
    from .build import _bold_parts, _sub  # build imports this module
    x, y, w, h = box
    z = _sub(parent, "zone", forceUpdate="true", h=str(h), id=b._zid(), type_v2="text", w=str(w), x=str(x), y=str(y))
    ft = _sub(z, "formatted-text")
    for i, (text, pt, bold) in enumerate(lines):
        if i:
            _sub(ft, "run").text = "Æ\n"  # Tableau's line-break run
        for part, strong in (_bold_parts(text) if bold else [(text, False)]):
            _sub(ft, "run", **({"bold": "true"} if strong else {}), fontcolor=color,
                 fontsize=str(pt)).text = params.text(part, b.params)
    b._zone_style(z)


def _lines_px(b, lines, width_px, where):
    """Height of a text zone of lines [(text, pt, bold)] wrapped in width_px, with its margins."""
    out = []
    for text, pt, _ in lines:
        n = design.text_lines(params.shown(text, b.params).replace("**", ""), pt, width_px)
        if n > design.MAX_TEXT_LINES:
            raise ValueError(f"{where}: '{text}' needs ~{n} lines at {pt}pt in {width_px}px "
                             f"(max {design.MAX_TEXT_LINES}): shorten it")
        out.append((pt, n))
    return design.header_px(out)


def _button(b, parent, kind, box, color):
    """An export button (ER, Admissions) drawn as a text button (Citizen): the brand color on a white face. Fixed to
    its height inside its margins in the vertical sidebar, as the nav buttons (a free button grows to 52px, 092)."""
    from .build import _sub
    x, y, w, h = box
    z = _sub(parent, "zone", fixed_size=str(design.BUTTON_PX), h=str(h), id=b._zid(), is_fixed="true",
             type_v2="dashboard-object", w=str(w), x=str(x), y=str(y))
    btn = _sub(z, "button", action="", button_click_action_metadata=EXPORT[kind], button_type="text")
    _sub(btn, "export-button-action").text = (f'tabdoc:abstract-dashboard-button-export-wrapper '
                                              f'dashboard-button-export-type="{EXPORT[kind]}" '
                                              f'dashboarddoc-id="{b.dash_uuid}"')
    state = _sub(btn, "button-visual-state")
    _sub(state, "caption").text = CAPTION[kind]
    _sub(state, "button-caption-font-style", bold="true", fontcolor=color, fontsize=str(FONT["button"]))
    _sub(state, "format", attr="background-color", value=COLOR["button_bg"])
    b._zone_style(z)


def topbar(b, root, d, box, size):
    """App bar over the whole dashboard (SOC, Admissions): the app name left, "Welcome, <name>" right.
    Returns its height in zone units, 0 without one."""
    from .build import _sub
    t = d.get("topbar")
    if not t:
        return 0
    x, y, w = box
    width, height = size
    pad, m = SPACE["zone_margin"], SPACE["zone_margin"]
    fg = text_color(t)
    ww = b._units(design.WELCOME_PX, width) if t.get("welcome") else 0
    text_px = (w - ww) * width // 100000 - 2 * pad - 2 * m
    lines = [(t["title"], FONT["topbar_title"], True)]
    h = b._units(max(_lines_px(b, lines, text_px, f"Dashboard '{d['name']}' topbar"),
                     design.header_px([(FONT["shell_label"], 1)])) + 2 * pad, height)
    band = _sub(root, "zone", h=str(h), id=b._zid(), param="horz", type_v2="layout-flow", w=str(w), x=str(x),
                y=str(y))
    ix, iy = x + b._units(pad, width), y + b._units(pad, height)
    iw, ih = w - 2 * b._units(pad, width), h - 2 * b._units(pad, height)
    _text(b, band, (ix, iy, iw - ww, ih), lines, fg)
    if ww:
        # fixed: in a flow Desktop sizes a free sheet to its content on Save As (60px, "Wel..": decisions/092);
        # fixed-size is the zone inside its margins
        b._zone_style(_sub(band, "zone", fixed_size=str(design.WELCOME_PX - 2 * m), h=str(ih), id=b._zid(), is_fixed="true",
                           name=WELCOME_SHEET, show_title="false", w=str(ww), x=str(ix + iw - ww), y=str(iy)))
    b._zone_style(band, margin=None, padding=pad, background=t["color"])
    return h


def sidebar(b, flow, d, items, box, size):
    """Brand sidebar (ER, Call Center): logo, title, filter dropdowns, export buttons, footer at the bottom, on the
    brand color with its text in a contrasting color."""
    from .build import _sub
    sb = brand(d)
    x, y, w, h = box
    width, height = size
    where = f"Dashboard '{d['name']}'"
    if any(i[0] == "color" for i in items):
        raise ValueError(f"{where}: a color legend card is drawn in black on the brand sidebar; give the colors a "
                         f"meaning (highlight, good) and name them in a block subtitle, or use sidebar: true")
    if d.get("subtitle") and any(role for _, role in colors.runs(d["subtitle"], where)):
        raise ValueError(f"{where}: colored words of the subtitle do not read on the brand sidebar; name the "
                         f"colors in a block subtitle")
    if any(b.part[sheet]["type"] == "registry" for _, sheet, _, _ in items):  # its title color has no sheet style
        raise ValueError(f"{where}: a filter on the brand sidebar shows on a registry; set its show_on to a chart "
                         f"sheet (the card's title color is part of that sheet's style)")
    fg = text_color(sb)
    pad, m = SPACE["panel_padding"], SPACE["zone_margin"]
    ux, uy = (lambda px: b._units(px, width)), (lambda px: b._units(px, height))
    cx, cw, cy, bottom = x + ux(pad), w - 2 * ux(pad), y + uy(pad), y + h - uy(pad)
    text_px = design.SIDEBAR_PX - 2 * pad - 2 * m
    side = _sub(flow, "zone", fixed_size=str(design.SIDEBAR_PX), h=str(h), id=b._zid(), is_fixed="true",
                param="vert", type_v2="layout-flow", w=str(w), x=str(x), y=str(y))
    logo = sb.get("logo")
    if logo and "text" in logo:  # a monogram: "C calls.", "S."
        lines = [(logo["text"], FONT["logo"], True)]
        zh = uy(_lines_px(b, lines, text_px, f"{where} logo"))
        _text(b, side, (cx, cy, cw, zh), lines, fg)
        cy += zh
    elif logo:
        zh = uy(design.LOGO_IMAGE_PX + 2 * m)  # fixed: a free picture gets its own height (decisions/092)
        b._zone_style(_sub(side, "zone", fixed_size=str(design.LOGO_IMAGE_PX), h=str(zh), id=b._zid(),
                           is_fixed="true", is_scaled="1",
                           param=f"{IMAGE_DIR}/{Path(logo['image']).name}", type_v2="bitmap", w=str(cw), x=str(cx),
                           y=str(cy)))
        cy += zh
    lines = [(t, pt, bold) for t, pt, bold in [(d.get("title"), FONT["dash_title"], True),
                                               (d.get("subtitle"), FONT["dash_subtitle"], False)] if t]
    if lines:
        zh = uy(_lines_px(b, lines, text_px, where))
        _text(b, side, (cx, cy, cw, zh), [(colors.plain(t), pt, bold) for t, pt, bold in lines], fg)
        cy += zh
    from . import nav  # nav imports this module
    cy = nav.sidebar(b, side, d, (cx, cy, cw), size, sb["color"])  # dashboard buttons (decisions/040)
    for _, sheet, ref, _ in items:  # filter dropdowns, as on the grey sidebar
        zh = uy(filters.card_h(b.filter_spec[ref]))  # a slider is taller (decisions/162)
        card = filters.card_attrs(b.filter_spec[ref], "sidebar")  # mode, values (decisions/035), show-apply (162)
        b._zone_style(_sub(side, "zone", h=str(zh), id=b._zid(), mode=card["mode"], name=sheet,
                           **({"values": card["values"]} if "values" in card else {}), param=ref,
                           **({"show_apply": card["show_apply"]} if "show_apply" in card else {}),
                           type_v2="filter", w=str(cw), x=str(cx), y=str(cy)))
        cy += zh
    if sb.get("download"):
        lines = [("Download", FONT["shell_label"], True)]
        zh = uy(_lines_px(b, lines, text_px, where))
        _text(b, side, (cx, cy, cw, zh), lines, fg)
        cy += zh
        # stacked at the sidebar's width: three in a row at 64px each cut the captions to "P..." (decisions/167)
        zh = uy(design.BUTTON_PX + 2 * m)
        face = sb["color"] if contrast(sb["color"], COLOR["button_bg"]) >= design.MIN_CONTRAST else COLOR["shell_dark"]
        for kind in sb["download"]:
            _button(b, side, kind, (cx, cy, cw, zh), face)
            cy += zh
    footer = [(t, FONT["footer"], False) for t in sb.get("footer", [])]
    fh = uy(_lines_px(b, footer, text_px, f"{where} footer")) if footer else 0
    if cy > bottom - fh:
        raise ValueError(f"{where}: the sidebar content (logo, title, filters, buttons, footer) is taller than the "
                         f"dashboard; use fewer filters or a taller dashboard")
    if footer:  # at the bottom: an empty zone fills the gap above it (the reference's spacers)
        if cy < bottom - fh:
            b._zone_style(_sub(side, "zone", h=str(bottom - fh - cy), id=b._zid(), type_v2="empty", w=str(cw),
                               x=str(cx), y=str(cy)))
        _text(b, side, (cx, bottom - fh, cw, fh), footer, fg)
    b._zone_style(side, margin=None, padding=pad, background=sb["color"])


def dashboard_sheets(b):
    """Shell worksheets shown on the dashboard (a viewpoint each in its window)."""
    return [WELCOME_SHEET] if welcome(b.spec) else []
