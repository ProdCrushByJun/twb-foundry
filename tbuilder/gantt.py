"""Gantt / timeline (polish-26): a bar per task from its start date for its length in days.

Spec: {type: gantt, task, start, end, color?}
- task: a row per member (in its order: fields.<task>.order, else by name);
- start, end: date columns; the bar starts at start and runs DATEDIFF('day', start, end) days;
- color: a text column whose members carry fields.<color>.color (status: done / in progress / planned); without it
  the bars are the book's accent.

XML (AdsCampaignsOverview 'ROAS - spark': <mark class='GanttBar'/> on a continuous day [tdy:date:qk] on Columns;
waterfall, decisions/139: the bar's length on <size>): the start's day on Columns, the task on Rows, the length calc
on Size, the status on Color.
"""

TYPE = "gantt"


def is_gantt(s):
    return s["type"] == TYPE


def days_calc(s):
    return f"{s['name']} · Days"


def check(spec, prof):
    for s in spec["sheets"]:
        if not is_gantt(s):
            continue
        for k in ("start", "end"):
            if prof.col(s[k]).datatype not in ("date", "datetime"):
                raise ValueError(f"Sheet '{s['name']}': {k} '{s[k]}' must be a date column")
        if "color" in s and "color" not in spec.get("fields", {}).get(s["color"], {}):
            raise ValueError(f"Sheet '{s['name']}': color '{s['color']}' needs fields.{s['color']}.color, a color per "
                             f"status (the house: a status by its meaning, not Tableau's palette)")


def calcs(spec):
    return [{"name": days_calc(s), "formula": f"DATEDIFF('day', [{s['start']}], [{s['end']}])"}
            for s in spec["sheets"] if is_gantt(s)]


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape)."""
    from .build import Field
    task, start = b._dim(s["task"]), Field(b.col(s["start"]), "date", "day")
    days = b._measure({"field": days_calc(s)})
    fields, enc = [task, start, days], [("size", b.q(days.name))]
    if "color" in s:
        c = b._dim(s["color"])
        fields.append(c)
        enc.insert(0, ("color", b.q(c.name)))
    return fields, task.name, start.name, enc, False, None


def expected(s, rows, dim, value, grouped):
    """task -> its length in days (the bar Desktop draws)."""
    from . import dates
    out = {}
    for r in rows:
        a, z = r[s["start"]], r[s["end"]]
        if a and z:
            key = r[s["task"]]
            out[key] = out.get(key, 0) + (dates.to_date(z) - dates.to_date(a)).days
    return out
