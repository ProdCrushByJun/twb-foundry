"""Everything that stops a build, in one list, before the first build (decisions/198).

The build stops at its first error, and its checks are spread over the generator and the gate: the design rules cannot
see them, and a copy of each would drift. So the build itself runs here, into a temporary file and without a Hyper
extract. A block it refuses is set aside: a plain bar takes its name and its cell, and the build goes again, so the
other blocks and the gate are still judged. One error per block per run.

A spec that builds has an empty list, whatever a stand-in would have done. Once a block is set aside, what the list
adds may be a stand-in's doing (a parameter left unused): the next run says. Nothing is listed about a stand-in itself.
"""
import copy
import json
import re
import tempfile
from pathlib import Path

from . import build as build_mod, expected, gate, nav, registry, spec as spec_mod

NO_HYPER_MB = float("inf")


def _named(text, names):
    """The block a message is about: its name in quotes, or a part of it ('KPI · Sales')."""
    return next((n for n in sorted(names, key=len, reverse=True) if f"'{n}'" in text or f"'{n} · " in text), None)


def _using(text, spec):
    """The first block with a field the message quotes: 'no such column' does not know whose it is."""
    for word in re.findall(r"'([^']+)'", text):
        for s in spec["sheets"]:
            if json.dumps(word) in json.dumps(s):
                return s["name"]
    return None


def _stand_in(s, parts):
    """A plain bar of the block's data source, or None when the source has no text and no number column."""
    source = s.get("datasource")
    prof = next((p for sub, _, p in parts if any(x["name"] == s["name"] for x in sub["sheets"])), None)
    columns = prof.columns if prof else []
    dim = next((c.name for c in columns if c.datatype == "string"), None)
    num = next((c.name for c in columns if c.datatype in ("integer", "real")), None)
    if not (dim and num):
        return None
    return {"name": s["name"], "type": "bar", "dimension": dim, "measure": {"field": num},
            **({"datasource": source} if source else {})}


def _set_aside(spec, name, parts):
    """The spec with this block replaced, and without the clicks that start from it; None when it cannot be."""
    i = next((i for i, s in enumerate(spec["sheets"]) if s["name"] == name), None)
    other = _stand_in(spec["sheets"][i], parts) if i is not None else None
    if other is None:
        return None
    spec = copy.deepcopy(spec)
    spec["sheets"][i] = other
    for d in nav.dashboards(spec):
        if "actions" in d:
            d["actions"] = [a for a in d["actions"] if a.get("source") != name]
    return spec


def _without_extract(spec):
    spec = copy.deepcopy(spec)
    for ds in spec_mod.sources(spec):
        ds.pop("hyper", None)
    return spec


def problems(spec, base_dir="."):
    """-> the messages of everything that stops this spec's build, [] when it builds. The spec is not changed."""
    found, aside = [], set()
    with tempfile.TemporaryDirectory() as tmp, expected.cached():
        try:
            spec_mod.validate(spec)
            spec = _without_extract(registry.expand(spec))
            parts = expected.parts(spec, base_dir)
        except Exception as e:  # not a spec yet, or no data: nothing more can be said
            return [str(e)]
        for _ in spec["sheets"] + [None]:  # a round more than blocks: each round sets one aside or ends
            try:
                build_mod.build(spec, Path(tmp) / "trial.twbx", base_dir, NO_HYPER_MB)
            except gate.GateError as e:
                return found + [str(i) for i in e.issues if not _named(i.where + " " + i.message, aside)]
            except Exception as e:  # a generator bug stops a build as well as a refusal does
                text = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
                name = _named(text, [s["name"] for s in spec["sheets"]]) or _using(text, spec)
                if name in aside:  # a stand-in's own
                    return found
                found.append(text)
                if name is None:  # the book's own: no way past it
                    return found
                aside.add(name)
                spec = _set_aside(spec, name, parts)
                if spec is None:
                    return found
            else:
                return found
    return found
