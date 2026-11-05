"""Spacing between dashboard objects (todo 3.7, the design rules): nothing touches another object
or the dashboard edge, and every margin is a design.SPACE token.

A block is one cell of the dashboard grid (its header text and the zones of its sheet), the dashboard header row
or the side panel of legends. The sides of a zone on its block's edge get block_margin, so blocks are 2 x 12 = 24px
apart and 8 + 12 = 20px from the dashboard edge (reference Reports Usage: margin-top 24 between two blocks on one
card, dashboard padding 20). The parts of one block (KPI tiles, a card's value and history) are zone_margin apart.
Under a block header its margin-bottom is the gap (header_gap) and the zone below gets margin-top 0, as the reference
writes it. Specs with block_headers false (the early goldens) keep zone_margin on every side.
In the card theme (decisions/030) a block is a card: its padding keeps the parts off the border, so their sides on
the block's edge get edge 0; the header row and the side panel stay on the canvas with the card's margin.
"""
from .design import SPACE

SIDES = ("top", "right", "bottom", "left")  # the order Desktop writes margin-<side> in (as in the reference)


def margins(box, cell, block=True, under_header=False, edge=None):
    """{side: px} of a zone with box inside its block's cell; both (x, y, w, h) in zone units. edge: the margin on
    the block's edge when it is not block_margin / zone_margin (the card theme)."""
    x, y, w, h = box
    cx, cy, cw, ch = cell
    if edge is None:
        edge = SPACE["block_margin"] if block else SPACE["zone_margin"]
    inner = SPACE["zone_margin"]
    return {"top": (0 if under_header else edge) if y == cy else inner,
            "right": edge if x + w == cx + cw else inner,
            "bottom": edge if y + h == cy + ch else inner,
            "left": edge if x == cx else inner}


def header(box, cell, block=True, edge=None):
    """A block header: block margins outside, header_gap under it."""
    m = margins(box, cell, block, edge=edge)
    if block:
        m["bottom"] = SPACE["header_gap"]
    return m


def formats(m):
    """[(attr, px)] of a margin: one 'margin' (the most frequent side) and the sides that differ from it."""
    if not isinstance(m, dict):
        return [("margin", m)]
    values = [m[s] for s in SIDES]
    base = max(sorted(set(values)), key=values.count)
    return [("margin", base)] + [(f"margin-{s}", m[s]) for s in SIDES if m[s] != base]
