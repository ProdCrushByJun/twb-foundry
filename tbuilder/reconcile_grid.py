"""Cells of a grid of numbers named by their axis labels (decisions/127, 200).

A chart library draws a heatmap cell as an svg <text> holding only the number, a page can draw one as a div in a css
grid; the row and column labels are other elements, so the cell had no words around it and went to reconcile as an
anonymous small number. Here the number-only texts of one svg (or one html scope, outline.js) that form a grid are
paired with the labels of the same scope by position (the label centered on the column / the row, outside the grid),
and get item["cell"] = {row, col}, the same as a table cell: reconcile then names the cell like a table's. A number
outside an html grid, centered on one of its rows or columns, is that row's or column's total: {row, col: ""} or
{row: "", col}. A grid with an unlabelled row or column stays as it was: nothing is guessed.
"""
import re

TOL = 4  # px: a label is centered on its column / row within this
MIN_LINES = 3
MIN_FILL = 0.7  # the share of a line's crossings that hold a number
_NUM = re.compile(r"^[\s\-−+$€£¥(]*[\d.,]+\s*[%)kKmMbB]?\s*$")  # the same as NUMBER_ONLY in outline.js


def _center(box):
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def _clusters(values, tol=TOL):
    """Sorted values -> the lists of values closer than `tol` to their neighbour."""
    out = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def _index(clusters, v):
    for i, c in enumerate(clusters):
        if c[0] - TOL <= v <= c[-1] + TOL:
            return i
    return None


def _nearest(labels, ok, key):
    best = [lb for lb in labels if ok(lb)]
    return min(best, key=key)["text"] if best else None


def _core(items):
    """(rows, cols): the lines of the grid, without the numbers around it: a marginal total sits on a line of the grid
    in one direction only, at its own place in the other, so its line is too short to be one."""
    points = [_center(i["box"]) for i in items]

    def count(line, other, axis):
        return sum(1 for p in points if line[0] <= p[axis] <= line[-1] and _index(other, p[1 - axis]) is not None)
    rows = [r for r in _clusters(p[1] for p in points) if len(r) >= MIN_LINES]
    cols = [c for c in _clusters(p[0] for p in points) if count(c, rows, 0) >= max(MIN_LINES, MIN_FILL * len(rows))]
    rows = [r for r in rows if count(r, cols, 1) >= max(MIN_LINES, MIN_FILL * len(cols))]
    return rows, cols


def _scopes(outline):
    """[(kind, the number-only texts of one svg or html scope, its labels)]."""
    out = {}
    for item in outline.get("texts", []):
        key = ("svg", item["svg"]) if item.get("svg") is not None else ("grid", item.get("grid"))
        if key[1] is not None and "cell" not in item and _NUM.match(item["text"]):
            out.setdefault(key, []).append(item)
    return [(key[0], items, [lb for lb in outline.get(f"{key[0]}_labels") or []
                             if lb.get(key[0]) == key[1] and not _NUM.match(lb["text"])])
            for key, items in out.items()]


def annotate(outline):
    """Set item["cell"] on the number-only texts that form a grid with labelled rows and columns, and on the totals
    around an html grid. Idempotent."""
    for kind, items, mine in _scopes(outline):
        if not mine:
            continue
        rows, cols = _core(items)
        if len(rows) < MIN_LINES or len(cols) < MIN_LINES:
            continue
        cells = [i for i in items if _index(rows, _center(i["box"])[1]) is not None
                 and _index(cols, _center(i["box"])[0]) is not None]
        if len(cells) < MIN_FILL * len(cols) * len(rows):
            continue
        left = min(i["box"][0] for i in cells)
        right = max(i["box"][0] + i["box"][2] for i in cells)
        top = min(i["box"][1] for i in cells)
        bottom = max(i["box"][1] + i["box"][3] for i in cells)
        col_label = [_nearest(
            mine, lambda lb, x=sum(c) / len(c): abs(_center(lb["box"])[0] - x) <= TOL
            and (lb["box"][1] + lb["box"][3] <= top + TOL or lb["box"][1] >= bottom - TOL),
            lambda lb: min(abs(lb["box"][1] + lb["box"][3] - top), abs(lb["box"][1] - bottom))) for c in cols]
        row_label = [_nearest(
            mine, lambda lb, y=sum(r) / len(r): abs(_center(lb["box"])[1] - y) <= TOL
            and (lb["box"][0] + lb["box"][2] <= left + TOL or lb["box"][0] >= right - TOL),
            lambda lb: min(abs(lb["box"][0] + lb["box"][2] - left), abs(lb["box"][0] - right))) for r in rows]
        if None in col_label or None in row_label:
            continue  # a grid whose axes are not all labelled stays as it was: nothing is guessed
        for i in items:
            cx, cy = _center(i["box"])
            r, c = _index(rows, cy), _index(cols, cx)
            if r is not None and c is not None:
                i["cell"] = {"row": row_label[r], "col": col_label[c]}
            elif kind != "grid":  # an svg's other numbers are its axis ticks
                continue
            elif c is not None and (cy < top or cy > bottom):
                i["cell"] = {"row": "", "col": col_label[c]}
            elif r is not None and (cx < left or cx > right):
                i["cell"] = {"row": row_label[r], "col": ""}
    return outline
