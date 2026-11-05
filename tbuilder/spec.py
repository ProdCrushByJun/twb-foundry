"""Load and schema-validate a spec. Data-dependent checks happen later in the builder."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).parent / "spec.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)


class SpecError(ValueError):
    pass


def _where(err):
    return "/".join(str(p) for p in err.absolute_path) or "(root)"


def validate(spec):
    """Raise SpecError listing every schema violation (not just the first)."""
    errors = sorted(_VALIDATOR.iter_errors(spec), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        raise SpecError("Spec is invalid:\n" + "\n".join(f"  - {_where(e)}: {e.message}" for e in errors))


def sources(spec):
    """The spec's data sources: [the datasource] or its datasources (decisions/083)."""
    return spec["datasources"] if "datasources" in spec else [spec["datasource"]]


def split(spec, columns_of):
    """[(datasource, sub-spec)] of a spec with several datasources (decisions/083): each sub-spec is the spec of one
    source, with 'datasource' and the sheets, calcs, filters and fields of that source; the rest (dashboards, nav,
    parameters, ...) is shared. A sheet and a calc name their source (default the first), a filter goes with its
    show_on sheet, a field with every source that has a column (or calc) of that name. The sheet, calc and filter
    dicts are the spec's own objects. columns_of(datasource) -> its column names. A spec with one datasource:
    [(datasource, spec)]."""
    if "datasources" not in spec:
        return [(spec["datasource"], spec)]
    srcs = spec["datasources"]
    names = [d["name"] for d in srcs]
    if len(set(names)) != len(names):
        raise SpecError(f"datasources: duplicate names {names}")
    paths = [d["path"] for d in srcs]
    if len(set(paths)) != len(paths):
        raise SpecError(f"datasources: two sources read the same file {paths}")

    def source(item, where):
        name = item.get("datasource", names[0])
        if name not in names:
            raise SpecError(f"{where}: datasource '{name}' is not one of the datasources {names}")
        return name
    of_sheet = {s["name"]: source(s, f"Sheet '{s['name']}'") for s in spec["sheets"]}
    of_calc = {c["name"]: source(c, f"Calc '{c['name']}'") for c in spec.get("calcs", [])}
    of_filter = []
    for f in spec.get("filters", []):
        where = f"Filter on '{f['field']}'"
        src = of_sheet.get(f["show_on"], names[0])  # an unknown show_on: the builder says so
        other = sorted({n for n in f.get("sheets", []) if of_sheet.get(n, src) != src})
        if other:
            raise SpecError(f"{where}: sheets {other} take another datasource than its show_on '{f['show_on']}'; a "
                            f"filter acts on the sheets of one source (decisions/083)")
        of_filter.append(src)
    cols = {d["name"]: set(columns_of(d)) | {c for c, n in of_calc.items() if n == d["name"]} for d in srcs}
    out = []
    for d in srcs:
        n = d["name"]
        sub = {k: v for k, v in spec.items() if k != "datasources"}
        sub["datasource"] = {k: v for k, v in d.items() if k != "name"}
        sub["sheets"] = [s for s in spec["sheets"] if of_sheet[s["name"]] == n]
        for key, items, of in (("calcs", spec.get("calcs"), [of_calc[c["name"]] for c in spec.get("calcs", [])]),
                               ("filters", spec.get("filters"), of_filter)):
            if items is not None:
                sub[key] = [x for x, src in zip(items, of) if src == n]
        if "fields" in spec:  # a field no source has stays with the first, where the builder names it
            sub["fields"] = {k: v for k, v in spec["fields"].items()
                             if k in cols[n] or (n == names[0] and not any(k in c for c in cols.values()))}
        out.append((d, sub))
    return out


def load(path):
    path = Path(path)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SpecError(f"{path.name}: not valid JSON ({e})") from None
    validate(spec)
    return spec
