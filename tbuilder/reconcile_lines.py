"""Points of an svg line without labels, read against its value axis (decisions/123).

A line drawn as a polyline / M-L path has numbers only on its axis. The y of a vertex is a value on that axis: the
ticks (number-only svg texts, already marked 'axis tick') snapped to the gridlines give the scale, each vertex is
read from it, and the series of points is compared with the workbook's series of the same length. A line whose
scale cannot be read is one skipped fact with the reason, not silence."""
from .match import SCALES

SNAP = 6         # px: a gridline this close to the middle of a tick text belongs to it
TOL_RULE = 0.75  # px of the scale a point may be off when the ticks sit on gridlines
TOL_TEXT = 2.5   # px when only the middle of the tick text is known


def _fact(svg, n, text, status, reason=None, value=None, i=None, tol=None, pt=None):
    f = {"number": "line" if value is None else f"{value:.6g}", "text": text, "context": text,
         "box": [round(pt[0]), round(pt[1]), 1, 1] if pt else [0, 0, 1, 1], "start": None, "status": status,
         "line": f"svg{svg}/line{n}"}
    if reason:
        f["reason"] = reason
    if value is not None:
        f.update(value=value, step=2 * tol, suffix="", pct=False, shown=f["number"], paren=False, index=i)
    return f


def _scale(ticks, hlines):
    """((a, b, tol), None) with value = a * y + b from the ticks of one column, or (None, reason)."""
    if any(t["pct"] for t in ticks):
        return None, "percent axis"
    ys = [t["box"][1] + t["box"][3] / 2 for t in ticks]
    snapped = []
    for y in ys:
        near = sorted(hlines, key=lambda h: abs(h - y))
        snapped.append(near[0] if near and abs(near[0] - y) <= SNAP else None)
    ruled = None not in snapped and len(set(snapped)) == len(snapped)
    ys, tol = (snapped, TOL_RULE) if ruled else (ys, TOL_TEXT)
    vs = [t["value"] * SCALES.get(t["suffix"], 1) for t in ticks]
    my, mv = sum(ys) / len(ys), sum(vs) / len(vs)
    var = sum((y - my) ** 2 for y in ys)
    if var < 1:
        return None, "ticks at one height"
    a = sum((y - my) * (v - mv) for y, v in zip(ys, vs)) / var
    b = mv - a * my
    if any(abs(a * y + b - v) > tol * abs(a) for y, v in zip(ys, vs)):
        return None, "ticks not evenly placed (log or broken scale)"
    return (a, b, tol * abs(a)), None


def _column(ticks):
    """The ticks of one value axis: the biggest set of tick texts sharing an edge, at 3+ different heights."""
    best = []
    for edge in (lambda b: b[0], lambda b: b[0] + b[2] / 2, lambda b: b[0] + b[2]):
        for t in ticks:
            col = [u for u in ticks if abs(edge(u["box"]) - edge(t["box"])) <= 2]
            if len(col) > len(best) and len({round(u["box"][1] / 3) for u in col}) >= 3:
                best = col
    return best


def facts(outline, fs):
    """Facts of the points of every line of the outline whose svg has no number labels of its own."""
    out = []
    for item in outline.get("lines", []):
        svg = item["svg"]
        mine = [f for f in fs if f.get("svg") == svg]
        if any(f["status"] is None for f in mine):  # the line is labelled: its numbers are facts already
            continue
        ticks = _column([f for f in mine if f.get("reason") == "axis tick"])
        for n, pts in enumerate(item["polylines"]):
            name = f"line {n + 1} of chart {svg + 1}"
            scale, why = _scale(ticks, item.get("hlines", [])) if len(ticks) >= 3 else (None, "no value axis ticks")
            if not scale:
                out.append(_fact(svg, n, name, "skipped", f"line without labels: {why}, its points are not read"))
                continue
            a, b, tol = scale
            for i, p in enumerate(sorted(pts)):
                out.append(_fact(svg, n, f"{name}, point {i + 1}", None, value=a * p[1] + b, i=i, tol=tol, pt=p))
    return out


def match(fs, ents, where):
    """The points of each line against a workbook sheet that is one value per date with as many dates as the line has
    points (the sheet's series in date order = the line left to right). The best sheet decides; a line no sheet fits
    in length is skipped with the reason."""
    lines = {}
    for f in fs:
        if f.get("line") and f["status"] is None:
            lines.setdefault(f["line"], []).append(f)
    sheets = {}
    for e in ents:
        if e["key"] and not e.get("part") and "phrase" not in e and not e["members"] \
                and isinstance(e["value"], (int, float)):
            sheets.setdefault(e["sheet"], []).append(e)
    sheets = [sorted(es, key=lambda e: e["key"]) for es in sheets.values()]
    for pts in lines.values():
        fit = [es for es in sheets if len(es) == len(pts)]
        if not fit:
            for f in pts:
                f["status"] = "skipped"
                f["reason"] = f"line without labels: no sheet of the workbook has {len(pts)} dated points"
            continue

        def off(es):
            return sum(abs(f["value"] - e["value"]) > f["step"] / 2 + 1e-9 for f, e in zip(pts, es))
        for f, e in zip(pts, min(fit, key=off)):
            ok = abs(f["value"] - e["value"]) <= f["step"] / 2 + 1e-9
            f["status"], f["workbook"] = ("matched" if ok else "mismatch"), where(e)
