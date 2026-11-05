"""Maps (todo 7.1, decisions/046): a symbol map and a filled map on Tableau's built-in geocoding.

Spec: {type: map, geo: {field, role: country | state | city, country?}, measure, style?: symbol | filled, labels?}
- symbol (default): a circle per member, its size the measure (Admissions 'Map - Nationality', Cutest Financial);
- filled: the member's polygon colored by the measure on the house sequential scale (Superstore 'Map'); Tableau has
  polygons for countries and states, not for cities;
- geo.country: the country a state or a city is looked up in (the workbook's [Country].[Name] semantic value; our
  template's default is the author's locale, Russia, so a US state would not be found without it);
- labels (default true): the measure's value on each mark, overlaps culled;
- color (decisions/137): the colorScale of a heatmap (decisions/041) on the marks, by the measure or by
  color.measure (a second one); a symbol map's circles take it instead of the accent, a filled map may be diverging.
  Sequential on a map starts FILLED_LOW of the way to the accent (the Light map's land is the scale's light end);
- size (symbol, default true): false draws every circle the same size (the color carries the measure);
- geo {field, lat, lon} instead of a role: a symbol map on the data's own coordinates, AVG on the shelves (one point
  per place, checked), the columns' roles [Geographical].[Latitude] / [Longitude] (form kept 1:1 by Desktop's Save
  As in golden_maps).

XML (forms from the reference books, not guessed):
- the column's geographic role: semantic-role='[State].[Name]' (Country, City) on the datasource column and in
  each sheet's dependencies, between role and type (Superstore, Admissions);
- the shelves: [Latitude (generated)] on Rows, [Longitude (generated)] on Columns, fields Tableau makes for a
  geographic role (not declared in the datasource); the member on Detail (<lod>); a filled map's polygon is
  <geometry column=[Geometry (generated)]> after the other encodings;
- the map source: <mapsources><mapsource name='Tableau' /></mapsources> after the workbook's <datasources> and in the
  sheet's view after its <datasources> (Superstore; Admissions names its own Mapbox source there);
- the background: style-rule 'map' map-style 'light' (Tableau.tms 'Light'), washout 0, after the other rules.

Geocoding: tbuilder/geo_names.json.gz (made on first use from the local Desktop, not shipped) holds every name (all synonyms and locales) Desktop 2025.1 geocodes for a
country and for a state of each country (tools/geo_names.py, from Desktop's GeocodingData.hyper). A value outside
it is an error before the build: Desktop would leave it off the map ('N unknown'), the map would not show the
data's numbers. City names are not kept (233 000) and a city whose name repeats in the country (Houston, Miami) is
'unknown' without its state: a city map is a lint error (G2).
"""
import difflib
import functools
import gzip
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .design import COLOR, SCALE_SEQ_COLORS

ROLES = {"country": "[Country].[Name]", "state": "[State].[Name]", "city": "[City].[Name]",
         "latitude": "[Geographical].[Latitude]", "longitude": "[Geographical].[Longitude]"}
RANGE = {"lat": (-90, 90), "lon": (-180, 180)}
FILLED = ("country", "state")  # Tableau's polygons; a city is a point
LAT, LON, GEOMETRY = "[Latitude (generated)]", "[Longitude (generated)]", "[Geometry (generated)]"
GENERATED = (LAT, LON, GEOMETRY)
MAPSOURCE = "Tableau"
MAP_STYLE = "light"
# the slider's default circles were 4-12px in a 380px map (Desktop): bigger, 75% opaque, a white rim keeps
# overlapping circles apart
SYMBOL_SIZE = "2"
FILLED_LOW = 0.3  # where on scale_low -> accent the filled map's lightest color is
NAMES = Path(__file__).with_name("geo_names.json.gz")


def is_map(s):
    return s["type"] == "map"


def style(s):
    return s.get("style", "symbol")


def labels(s):
    return s.get("labels", True)


def color(s):
    """A map's color scale spec (decisions/137), or None."""
    return s.get("color") if is_map(s) else None


def color_measure(s):
    """The measure the map's colors show: color.measure, else the map's own; None without colors (symbol)."""
    c = color(s)
    if c is not None:
        return c.get("measure", s["measure"])
    return s["measure"] if style(s) == "filled" else None


def second_measure(s):
    """color.measure: a measure of its own on Color, besides the size / label one."""
    c = color(s)
    return c["measure"] if c is not None and "measure" in c else None


def sized(s):
    """The circles sized by the measure (a symbol map without size: false)."""
    return style(s) == "symbol" and s.get("size", True)


def color_record(name):
    """expected.py key of a map's color measure by place (color.measure: the scale's range is checked on it)."""
    return f"{name} · Color"


@functools.cache
def names():
    if not NAMES.is_file():  # read from the local Desktop on first use: not shipped, it is Tableau's data
        tool = NAMES.parent.parent / "tools" / "geo_names.py"
        subprocess.run([sys.executable, str(tool)], check=True)
    with gzip.open(NAMES, "rt", encoding="utf-8") as f:
        return json.load(f)


def _folded(values):
    return {v.casefold() for v in values}


def country_code(name):
    """ISO alpha-3 of a country name Desktop knows (any synonym, any case), else None."""
    if name is None:
        return None
    key = name.casefold()
    return next((iso for iso, ns in names()["country"].items() if key in _folded(ns)), None)


def known(role, country=None):
    """The names Desktop geocodes for a role (in a country's context for a state), None when not kept (city)."""
    if role == "country":
        return {n for ns in names()["country"].values() for n in ns}
    if role == "state":
        return set(names()["state"].get(country_code(country), []))
    return None


def unknown(role, values, country=None):
    """Values Desktop would not place on the map (case-insensitive, as its geocoding), None when unverifiable."""
    ref = known(role, country)
    if ref is None:
        return None
    folded = _folded(ref)
    return [v for v in values if v.casefold() not in folded]


def _hint(v, ref):
    close = difflib.get_close_matches(v, sorted(ref), n=1, cutoff=0.75)
    return f"'{v}' (did you mean '{close[0]}'?)" if close else f"'{v}'"


def coords(s):
    """A map on the data's own latitude / longitude columns (geo {field, lat, lon})."""
    return "lat" in s["geo"]


def roles(spec):
    """{column: role} of the maps' geo fields, or of their latitude / longitude columns."""
    out = {}
    for s in spec["sheets"]:
        if is_map(s):
            g = s["geo"]
            out.update({g["lat"]: "latitude", g["lon"]: "longitude"} if coords(s) else {g["field"]: g["role"]})
    return out


def context_country(spec):
    """The country states and cities are looked up in, None when no map needs one."""
    cs = {s["geo"]["country"] for s in spec["sheets"] if is_map(s) and "country" in s["geo"]}
    return next(iter(cs)) if cs else None


def shown(spec, prof, s, field):
    """Values of the field a map draws when the book opens: the rows after the dashboard's filters and the sheet's
    own (decisions/067; a public book's Sales by State: Country/Region = United States leaves Canada's provinces out)."""
    from . import filters
    calc = filters.calc_values(spec, prof)
    rows = filters.split_rows(spec, prof, calc=calc)[1]
    return sorted({r[field] for r in filters.sheet_rows(s, rows, calc) if r[field] != ""})


def check(spec, prof):
    """Spec and data checks the schema cannot make; unknown places fail before the build (the places the map draws
    at open: after the filters, decisions/067)."""
    maps = [s for s in spec["sheets"] if is_map(s)]
    seen, countries = {}, set()
    for s in maps:
        where, g = f"Map '{s['name']}'", s["geo"]
        if coords(s):
            _check_coords(s, prof, where)
            continue
        if "role" not in g:
            raise ValueError(f"{where}: geo needs a role (country, state, city) or the data's lat and lon columns")
        role, field = g["role"], g["field"]
        if seen.setdefault(field, role) != role:
            raise ValueError(f"{where}: '{field}' is both a {seen[field]} and a {role}; a field has one geographic "
                             f"role")
        if style(s) == "filled" and role not in FILLED:
            raise ValueError(f"{where}: Tableau has no {role} polygons; a filled map takes a country or a state, a "
                             f"{role} is a symbol map")
        if "size" in s and style(s) == "filled":
            raise ValueError(f"{where}: 'size' is a symbol map's; a filled map's polygons have no size")
        if role == "country" and "country" in g:
            raise ValueError(f"{where}: 'country' is the context of a state or a city map, not of a country map")
        if role != "country":
            if "country" not in g:
                raise ValueError(f"{where}: a {role} map needs geo.country, the country Tableau looks the {role} "
                                 f"names up in (e.g. 'United States')")
            if country_code(g["country"]) is None:
                raise ValueError(f"{where}: Tableau does not know the country '{g['country']}'")
            countries.add(g["country"])
        col = prof.col(field)
        if col.datatype != "string":
            raise ValueError(f"{where}: '{field}' is {col.datatype}; a {role} is a text field of place names")
        values = shown(spec, prof, s, field) if spec.get("filters") or s.get("filters") else col.distinct
        bad = unknown(role, values, g.get("country"))
        if bad:
            ref = known(role, g.get("country"))
            raise ValueError(f"{where}: Tableau's geocoding does not know {len(bad)} value(s) of '{field}' as a "
                             f"{role}{' of ' + g['country'] if 'country' in g else ''}: "
                             f"{', '.join(_hint(v, ref) for v in bad[:10])}{' ...' if len(bad) > 10 else ''}. "
                             f"Desktop would leave them off the map; fix the data")
    if len(countries) > 1:
        raise ValueError(f"Maps look places up in {sorted(countries)}: one country context per workbook")


def _check_coords(s, prof, where):
    g = s["geo"]
    if "size" in s and style(s) == "filled":
        raise ValueError(f"{where}: 'size' is a symbol map's; a filled map's polygons have no size")
    if "role" in g or "country" in g or "lon" not in g:
        raise ValueError(f"{where}: a map on the data's coordinates takes geo {{field, lat, lon}}, no role or country")
    if style(s) == "filled":
        raise ValueError(f"{where}: a point (lat / lon) has no polygon; a filled map takes a country or a state")
    if prof.col(g["field"]).datatype != "string":
        raise ValueError(f"{where}: '{g['field']}' is not a text field; its members are the map's marks")
    for k in ("lat", "lon"):
        col, (lo, hi) = prof.col(g[k]), RANGE[k]
        if col.datatype not in ("real", "integer"):
            raise ValueError(f"{where}: {k} '{g[k]}' is {col.datatype}, not a number")
        if any(r[g[k]] == "" for r in prof.rows):
            raise ValueError(f"{where}: '{g[k]}' has empty values; Tableau leaves those rows off the map")
        bad = sorted({r[g[k]] for r in prof.rows if not lo <= float(r[g[k]]) <= hi})
        if bad:
            raise ValueError(f"{where}: {k} '{g[k]}' outside {lo}..{hi}: {bad[:5]}")
    places = {}
    for r in prof.rows:  # one place, one point: AVG of differing coordinates would put it between them
        places.setdefault(r[g["field"]], set()).add((r[g["lat"]], r[g["lon"]]))
    moved = sorted(p for p, xy in places.items() if len(xy) > 1)
    if moved:
        raise ValueError(f"{where}: {moved[:5]} have several coordinates; the map would draw their average")


# ---- the role Desktop gives a column by its name (decisions/092) --------------------------------------------------
# Desktop 2025.1 on Save As, when no column of the data source has a role yet: every data column with one of these
# words in its name (any case; words split at anything but letters: "Ship City", "STATE", "Province2",
# "Country/Region") gets the role, in the datasource and in the sheets' dependencies, whatever its values are (ITSM's
# incident State). A word inside a word does not count (Velocity, Statement, Countryside, Platform). A role written
# in the workbook stops it: then Desktop adds none (lab: one map role, nothing added). Forms from the lab's
# re-saves; Desktop's Country role is ISO3166_2 even for country names. No role: Region, Airport, Continent, Town,
# Municipality. Zip / Postal Code / Postcode / Area Code (integers: Desktop makes them ordinal with a default
# format) are not written: a string role written by us blocks them.
AUTO_STRING = {"country": "[Country].[ISO3166_2]", "nation": "[Country].[ISO3166_2]", "city": "[City].[Name]",
               "county": "[County].[Name]", "prefecture": "[County].[Name]", "state": "[State].[Name]",
               "province": "[State].[Name]"}
AUTO_NUMBER = {"latitude": ROLES["latitude"], "lat": ROLES["latitude"], "longitude": ROLES["longitude"],
               "lon": ROLES["longitude"]}


def name_role(col):
    """The role Desktop gives a data column by its name alone, None for none."""
    words = AUTO_STRING if col.datatype == "string" else AUTO_NUMBER if col.datatype == "real" else {}
    return next((words[w] for w in re.findall(r"[^\W\d_]+", col.name.casefold()) if w in words), None)


def auto_roles(b):
    """{column: semantic role} Desktop would add on Save As: by name, when the spec gives none of the source's
    columns a role (a map's geo field)."""
    declared = roles(b.spec)
    if any(c.name in declared for c in b.prof.columns):
        return {}
    return {c.name: r for c in b.prof.columns if (r := name_role(c))}


# ---- workbook (build.py) -------------------------------------------------------------------------------------------
def column(el, col, b):
    """The geographic role on a datasource / dependency column, where Desktop writes it: before 'type'."""
    role = roles(b.spec).get(col.name)
    role = ROLES[role] if role else auto_roles(b).get(col.name)
    if role is None:
        return
    attrs = dict(el.attrib)
    el.attrib.clear()
    for k, v in attrs.items():
        if k == "type":
            el.set("semantic-role", role)
        el.set(k, v)


def columns(b):
    """The data columns the datasource declares for their role (Desktop declares every column it gives one)."""
    return [b.prof.col(f) for f in [*roles(b.spec), *auto_roles(b)]]


def semantic_values(ds_el, spec):
    """The country states and cities are looked up in (Superstore: "United States")."""
    c = context_country(spec)
    sv = ds_el.find("semantic-values/semantic-value[@key='[Country].[Name]']")
    if c is not None and sv is not None:
        sv.set("value", f'"{c}"')


def mapsources(parent, index=None):
    el = ET.Element("mapsources")
    ET.SubElement(el, "mapsource", name=MAPSOURCE)
    if index is None:
        parent.append(el)
    else:
        parent.insert(index, el)


def workbook(wb, spec):
    """<mapsources> right after the workbook's <datasources>."""
    if any(is_map(s) for s in spec["sheets"]):
        mapsources(wb, list(wb).index(wb.find("datasources")) + 1)


def manifest_flags(manifest, spec):
    """Desktop 2025.1 writes MapboxVectorStylesAndLayers with a map (golden_maps; Superstore 2023.3 too), in the
    manifest's alphabetical order: before MarkAnimation."""
    if any(is_map(s) for s in spec["sheets"]):
        mark = manifest.find("MarkAnimation")
        manifest.insert(list(manifest).index(mark), ET.Element("MapboxVectorStylesAndLayers"))


def view(view_el, s):
    """<mapsources> in the sheet's view, after its <datasources>."""
    if is_map(s):
        mapsources(view_el, list(view_el).index(view_el.find("datasources")) + 1)


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape); table() writes the shelves."""
    fields = [b._dim(s["geo"]["field"]), b._measure(s["measure"])]
    if coords(s):  # AVG of the data's latitude / longitude on the shelves (one point per place: check)
        from .build import Field
        fields += [Field(b.col(s["geo"][k]), "agg", "avg") for k in ("lat", "lon")]
    if second_measure(s):  # the color's own measure, last (decisions/137)
        fields.append(b._measure(second_measure(s)))
    return fields, None, None, [], False, None


def _runs(parent, runs):
    ft = ET.SubElement(parent, "formatted-text")
    for text, attrs in runs:
        ET.SubElement(ft, "run", attrs).text = text


def palette(c):
    """(palette type, colors) of a map's scale: sequential from FILLED_LOW of the way (filled_palette), diverging as a
    heatmap's (its grey middle stands out from the Light map's land)."""
    from .heatmap import palette as heat_palette
    if c is None or c["scale"] == "sequential":
        return "ordered-sequential", filled_palette()
    return heat_palette(c)


def filled_palette():
    """The house sequential scale (decisions/041) from FILLED_LOW of the way: its own light end (scale_low #f1f1f1)
    is the land of the Light map, the smallest countries vanished (Desktop: Japan, Australia)."""
    from .heatmap import _mix
    lo = _mix(COLOR["scale_low"], COLOR["accent"], FILLED_LOW)
    return [_mix(lo, COLOR["accent"], k / (SCALE_SEQ_COLORS - 1)) for k in range(SCALE_SEQ_COLORS)]


def symbol():
    """A circle's look: the book's accent read at build time (decisions/137), 75% opaque, a white rim."""
    return {"size": SYMBOL_SIZE, "mark-color": COLOR["accent"], "mark-transparency": "191", "has-stroke": "true",
            "stroke-color": COLOR["card_bg"]}


def table(b, table_el, style_el, s, fields):
    """The color scale (filled, color), the map background, the pane, the generated latitude / longitude shelves."""
    from .heatmap import encoding
    d, m = fields[:2]
    cm = fields[-1] if second_measure(s) else m  # the measure on Color (decisions/137)
    filled = style(s) == "filled"
    if color_measure(s):  # the house scales (decisions/041), not Tableau's default blue
        encoding(style_el, color(s) or {}, b.q(cm.name), *palette(color(s)))
    mp = ET.SubElement(style_el, "style-rule", element="map")
    ET.SubElement(mp, "format", attr="map-style", value=MAP_STYLE)
    ET.SubElement(mp, "format", attr="washout", value="0")
    ET.SubElement(mp, "format", attr="map-snap-zoom", value="true")  # Desktop adds it on save (golden_maps)
    pane = ET.SubElement(ET.SubElement(table_el, "panes"), "pane",
                         {"selection-relaxation-option": "selection-relaxation-allow"})
    ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
    ET.SubElement(pane, "mark", {"class": "Multipolygon" if filled else "Circle"})
    e = ET.SubElement(pane, "encodings")
    if color_measure(s):
        ET.SubElement(e, "color", column=b.q(cm.name))
    if sized(s):
        ET.SubElement(e, "size", column=b.q(m.name))
    if labels(s):
        ET.SubElement(e, "text", column=b.q(m.name))
    ET.SubElement(e, "lod", column=b.q(d.name))
    if filled:
        ET.SubElement(e, "geometry", column=b.q(GEOMETRY))
    runs = [(f"<{b.q(d.name)}>", {"bold": "true"})]
    for spec_m, f in [(s["measure"], m)] + ([(second_measure(s), cm)] if second_measure(s) else []):
        label = spec_m.get("label") or getattr(f.col, "caption", f.col.name)
        runs += [("Æ\n", {}), (f"{label}:\t", {"fontcolor": COLOR["muted"]}), (f"<{b.q(f.name)}>", {"bold": "true"})]
    _runs(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), runs)
    rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
    fmts = dict({"has-stroke": "true", "stroke-color": COLOR["card_bg"]} if filled else symbol())  # white borders (Superstore)
    if color_measure(s):  # the scale paints the circles (decisions/137)
        fmts.pop("mark-color", None)
    if "size" in fmts:  # the size first, as in the dual-axis panes (decisions/044)
        ET.SubElement(rule, "format", attr="size", value=fmts.pop("size"))
    if labels(s):
        ET.SubElement(rule, "format", attr="mark-labels-show", value="true")
        ET.SubElement(rule, "format", attr="mark-labels-cull", value="true")
    for attr, value in fmts.items():
        ET.SubElement(rule, "format", attr=attr, value=value)
    lat, lon = (b.q(f.name) for f in fields[2:4]) if coords(s) else (b.q(LAT), b.q(LON))
    ET.SubElement(table_el, "rows").text = lat
    ET.SubElement(table_el, "cols").text = lon
