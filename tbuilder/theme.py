"""Card theme (decisions/030, todo 3.12): dashboard.theme "cards" and the workbook font dashboard.theme_font.

All 12 workbooks of reference set 3 (reference books) put their blocks on cards: a light canvas, white
blocks with a 1px cool-grey border and a padding inside. In the theme every block of the grid (its header and its
sheet, or a KPI group) is a card; the dashboard header row and the legend panel stay on the canvas. The theme also
has its own type scale (design.FONT_CARDS), a 1px divider and the KPI strip (kpi.arrange "strip": one card,
vertical dividers between the measures, books 4 and 11). The theme is the default (decisions/168): a spec without
dashboard.theme is drawn on cards; dashboard.theme "flat" is the plain look without cards (white page, blocks without
borders, the plain type scale), and the only one a sidebar, a topbar or block_headers false can have.

XML shapes are Desktop's (scratchpad analysis of the references, decisions/030):
- card: layout-flow vert with zone-style border-color / border-style solid / border-width 1 / margin / padding /
  background-color (RETAIL-POS 2021.4, Customer Support 2023.1); its one child is a layout-basic holding the
  block's zones as before (a layout-basic inside a layout-flow: Bonus Project, ER, Release Navigator);
- divider: an empty zone with a background and margins, drawn 1px thick (RETAIL-POS: margin 8, #e9ecef);
- canvas: the dashboard's style-rule table background-color (Regional Overview 2024.1);
- font: the workbook's style-rule element="all" font-family (RETAIL-POS, Customer Support, Insurance, Help Desk).
"""
import xml.etree.ElementTree as ET

from . import design
from .design import COLOR, FONT, SPACE

CARDS = "cards"
FLAT = "flat"
DIVIDER = {"name": None, "type": "divider"}  # a part of _part_boxes that is a 1px rule, not a sheet
FONTS = ("Arial",)  # web-safe only (no Poppins: style-references-3.md)
TRANSPARENT_FLAG = "WorksheetBackgroundTransparency"


def on(spec):
    return spec["dashboard"].get("theme", design.BOOK["theme"]) == CARDS


def strip(s):
    return s.get("arrange") == "strip"


def check(spec):
    """Theme options the generator cannot draw yet fail the build (ValueError)."""
    d = spec["dashboard"]
    if on(spec):
        if d.get("sidebar"):
            raise ValueError(f"Dashboard '{d['name']}': theme 'cards' (the default) with a sidebar is not supported yet "
                             f"(the grey sidebar is the canvas color; a brand sidebar is not checked in Desktop); "
                             f"set dashboard.theme 'flat'")
        if d.get("topbar"):
            raise ValueError(f"Dashboard '{d['name']}': theme 'cards' (the default) with a topbar is not supported yet; "
                             f"set dashboard.theme 'flat'")
        if not spec.get("block_headers", True):
            raise ValueError(f"Dashboard '{d['name']}': theme 'cards' (the default) needs block_headers (a card holds "
                             f"its header); set dashboard.theme 'flat' or drop block_headers false")
    for s in spec["sheets"]:
        if strip(s) and not on(spec):
            raise ValueError(f"KPI '{s['name']}': arrange 'strip' is one card with dividers; it cannot be drawn with "
                             f"dashboard.theme 'flat'")


# ---- tokens ------------------------------------------------------------------------------------------------
def font(spec):
    """The type scale: FONT, with the theme's sizes in the card theme."""
    return {**FONT, **(design.FONT_CARDS if on(spec) else {})}


def kpi_value_pt(b, s):
    """The KPI number: 24, or in the theme 24 for up to KPI_WIDE_MAX side by side and 18 stacked or denser."""
    if not b.theme or "measures" not in s:
        return FONT["kpi_value"]
    if s.get("separate_cards"):  # a card each, the number beside its sparkline (decisions/178)
        return design.KPI_VALUE_SEPARATE
    wide = s.get("arrange", "row") != "column" and len(s["measures"]) <= design.KPI_WIDE_MAX
    return design.KPI_VALUE_WIDE if wide else design.KPI_VALUE_DENSE


def title_color(b):
    return COLOR["text"] if b.theme else None


def subtitle_color(b, dashboard=False):
    return COLOR["subtitle"] if b.theme and dashboard else COLOR["muted"]


def word_color(b, role):
    """A colored word or a KPI change as text: good / bad darkened to the contrast floor in the theme (C9)."""
    return COLOR[f"{role}_text"] if b.theme and role in ("good", "bad") else COLOR[role]


def history(b):
    return COLOR["history"] if b.theme else COLOR["mark_muted"]


def card_value_w(b):
    return design.CARD_VALUE_W_CARDS_PX if b.theme else design.CARD_VALUE_W_PX


def registry_header_px(b):
    return design.TABLE_HEADER_CARDS_PX if b.theme else design.REGISTRY_HEADER_PX


# ---- spacing -----------------------------------------------------------------------------------------------
def root_margin(b):
    """The dashboard edge: 6 + the card's 6 = 12px to a card in the theme, the same as the gap (decisions/187)."""
    return SPACE["theme_edge"] if b.theme else SPACE["outer_margin"]


def block_edge(b):
    """Margin of a block's part on the block's edge: 0 inside a card (its padding keeps the distance)."""
    return 0 if b.theme else None


def canvas_edge(b):
    """Margin of the header row and the legend panel on the canvas: the card's margin, so their text lines up
    with the card borders."""
    return SPACE["card_margin"] if b.theme else None


def padding(s):
    """A card's inner padding by its weight (decisions/070): a KPI card card_padding_kpi, a chart or table card
    card_padding. Both at least half the gap between cards (card_margin)."""
    return SPACE["card_padding_kpi"] if s.get("type") == "kpi" else SPACE["card_padding"]


def border_px(b):
    """The card's border: 1px, 0 with dashboard.card_border false (the card is told from the canvas by its tone
    only, decisions/089)."""
    return design.CARD_BORDER_PX if b.spec["dashboard"].get("card_border", True) else 0


def inset(b, s):
    """px between the card's zone box of sheet s and its content: margin, border, padding."""
    return SPACE["card_margin"] + border_px(b) + padding(s)


def inset_units(b, size, s):
    """inset in zone units across and down as Desktop writes a card's inner layout-basic on Save As (decisions/070):
    margin, border and padding each rounded to units, then added (27px at 1200: 833 + 83 + 1333 = 2249, not 2250;
    23px at 960: 1042 + 104 + 1250 = 2396; ten resaved points, four books)."""
    parts = (SPACE["card_margin"], border_px(b), padding(s))
    return tuple(sum(b._units(px, size_px) for px in parts) for size_px in size)


# ---- XML ---------------------------------------------------------------------------------------------------
def workbook_style(b, wb):
    """The workbook font (style-rule element="all"), right after <preferences> as Desktop writes it."""
    family = b.spec["dashboard"].get("theme_font", design.BOOK["theme_font"])
    if not family:
        return
    st = ET.Element("style")
    ET.SubElement(ET.SubElement(st, "style-rule", element="all"), "format", attr="font-family", value=family)
    wb.insert(list(wb).index(wb.find("preferences")) + 1, st)


def dashboard_style(b, style):
    """The canvas: the dashboard's background (Format > Dashboard > shading)."""
    if b.theme:
        ET.SubElement(ET.SubElement(style, "style-rule", element="table"), "format", attr="background-color",
                      value=COLOR["canvas"])


def card(b, parent, box, inner, s):
    """A card at box (a grid cell): a vertical layout-flow with the card's border, margin, padding and face, and in
    it one layout-basic at inner (box less inset_units) for the block's zones. Returns the layout-basic."""
    from .build import _sub  # build imports this module
    x, y, w, h = box
    z = _sub(parent, "zone", h=str(h), id=b._zid(), param="vert", type_v2="layout-flow", w=str(w), x=str(x),
             y=str(y))
    x, y, w, h = inner
    basic = _sub(z, "zone", h=str(h), id=b._zid(), type_v2="layout-basic", w=str(w), x=str(x), y=str(y))
    st = _sub(z, "zone-style")  # after the child zones, as Desktop writes it
    border = [("border-color", COLOR["card_border"]), ("border-style", "solid"),
              ("border-width", design.CARD_BORDER_PX)] if border_px(b) else []
    for a, v in border + [("margin", SPACE["card_margin"]), ("padding", padding(s)),
                          ("background-color", COLOR["card_bg"])]:
        _sub(st, "format", attr=a, value=str(v))
    return basic


def divider_px():
    """Width of a divider's zone: the 1px line and its margins."""
    return 1 + 2 * SPACE["rule_margin"]


def divide(b, x, w, n, width):
    """Split [x, x+w) into n parts with a divider between neighbours -> ([(x, w)] parts, [(x, w)] dividers)."""
    from .build import _split
    du = b._units(divider_px(), width)
    parts, rules = [], []
    for k, (px, pw) in enumerate(_split(x, w - (n - 1) * du, [1] * n)):
        parts.append((px + k * du, pw))
        if k < n - 1:
            rules.append((px + k * du + pw, du))
    return parts, rules


def divider(b, parent, box):
    """A 1px rule: an empty zone in the rule color, its margins around the line."""
    from .build import _sub
    x, y, w, h = box
    z = _sub(parent, "zone", h=str(h), id=b._zid(), type_v2="empty", w=str(w), x=str(x), y=str(y))
    b._zone_style(z, margin=SPACE["rule_margin"], background=COLOR["rule"])


SHEET_TEXT = ("bar", "line", "area", "table", "heatmap", "treemap", "combo", "lollipop", "scatter", "dumbbell", "waterfall", "funnel",
              "bubbles", "slope", "boxplot")  # decisions/141


def sheet_text(b, style, s):
    """A chart's own text (axes, mark labels, headers) 8pt in the muted color in the theme: the worksheet's
    style-rule, as Desktop writes Format > Worksheet > Font (reference, 74 sheets; decisions/089). Field-level
    rules of other modules (bar headers 10pt, total cells) stay above it. A heatmap gets the size only: its labels'
    color is the automatic contrast on the cell."""
    if not b.theme or s["type"] not in SHEET_TEXT:
        return
    from .colors import _rule
    rule = _rule(style, "worksheet", before=("refline", "gridline", "zeroline", "table-div"))
    attrs = [("font-size", str(design.SHEET_TEXT_PT))]
    if s["type"] not in ("heatmap", "treemap", "bubbles"):
        attrs.append(("color", COLOR["muted"]))
    for i, (a, v) in enumerate(attrs):  # before the rule's display-field-labels, as Desktop writes it
        rule.insert(i, ET.Element("format", attr=a, value=v))


def colored_card(b):
    return b.theme and COLOR["card_bg"] != "#ffffff"


def manifest_flags(manifest, b):
    """A transparent sheet comes with this flag: Desktop adds it on save (--resave, decisions/194)."""
    if colored_card(b):
        later = [i for i, e in enumerate(manifest) if e.tag > TRANSPARENT_FLAG]
        manifest.insert(later[0] if later else len(manifest), ET.Element(TRANSPARENT_FLAG))


def sheet_background(b, ws):
    """A sheet is white over a card that is not (decisions/194): worksheet shading None, the table rule's background
    #00000000 as Desktop writes it (hundreds of reference sheets, e.g. Insurance: 39). The face and the canvas show
    through. A white card writes nothing: the books of the house stay as they are."""
    if not colored_card(b):
        return
    from .colors import _rule
    table = ws.find("table")
    style = table.find("style")
    if style is None:
        style = ET.Element("style")
        table.insert(list(table).index(table.find("view")) + 1, style)
    rule = _rule(style, "table", before=("worksheet", "refline", "gridline", "zeroline", "table-div"))
    rule.insert(0, ET.Element("format", attr="background-color", value="#00000000"))
    # A reference line's label has a box of its own: on a transparent sheet Desktop draws it in the canvas color. In the
    # card's face it reads as before, the form E-Commerce and Enterprise Risk have
    for line in style.findall("style-rule[@element='refline']"):
        ids = dict.fromkeys(f.get("id") for f in line.findall("format") if f.get("id"))
        for i in ids:
            ET.SubElement(line, "format", attr="background-color", id=i, value=COLOR["card_bg"])


def row_height(b, style, field):
    """Table and registry rows 30px in the theme: style-rule cell, height by the row field (Demo wealth and
    banking, Insurance: cell height 30), field formats first."""
    if not b.theme:
        return
    from .colors import _rule
    rule = _rule(style, "cell", before=("header", "label", "mark", "pane", "worksheet", "refline", "gridline", "zeroline",
                                        "table-div"))
    rule.insert(0, ET.Element("format", attr="height", field=b.q(field.name), value=str(design.TABLE_ROW_CARDS_PX)))
