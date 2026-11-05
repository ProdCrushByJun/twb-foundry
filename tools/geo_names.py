"""Extract the place names Tableau Desktop geocodes (decisions/046) into tbuilder/geo_names.json.gz.

Source: Desktop's own geocoding database, <Tableau>/Local/data/GeocodingData.hyper (the one its built-in geographic
roles read). Kept: every name (all synonyms, all locales) of each country and of each state / province, the
states keyed by their country's ISO 3166 alpha-3 code. Cities (233 000 names) are not kept: tbuilder.geo reports
them as unverified.

    python tools/geo_names.py [path/to/GeocodingData.hyper]

The .hyper is read-only under Program Files and Hyper opens a database read-write, so it is copied to a temp dir.
"""
import gzip
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from tableauhyperapi import Connection, CreateMode, HyperProcess, Telemetry

DEFAULT = Path(r"C:/Program Files/Tableau/Tableau 2025.1/Local/data/GeocodingData.hyper")
OUT = Path(__file__).resolve().parent.parent / "tbuilder" / "geo_names.json.gz"


def extract(src):
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "geo.hyper"
        shutil.copy(src, db)
        os.chmod(db, stat.S_IWRITE | stat.S_IREAD)
        with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, \
                Connection(hp.endpoint, db, CreateMode.NONE) as c:
            meta = dict(c.execute_list_query('SELECT "key", "value" FROM "Metadata"'))
            iso = dict(c.execute_list_query('SELECT "ID", "ISO3166_3" FROM "Country"'))
            countries = {}
            for pid, name in c.execute_list_query('SELECT "ParentID", "Name" FROM "CountrySynonyms"'):
                countries.setdefault(iso[pid], set()).add(name)
            states = {}
            for parent, name in c.execute_list_query(
                    'SELECT s."ParentID", n."Name" FROM "State" s JOIN "StateSynonyms" n ON n."ParentID" = s."ID"'):
                if parent in iso:
                    states.setdefault(iso[parent], set()).add(name)
    return {"source": f"GeocodingData.hyper version {meta.get('version')} ({meta.get('created_date')})",
            "country": {k: sorted(v) for k, v in sorted(countries.items())},
            "state": {k: sorted(v) for k, v in sorted(states.items())}}


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else DEFAULT
    data = extract(src)
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(OUT, "wb", mtime=0) as f:  # mtime 0: the same bytes on every run
        f.write(raw)
    print(f"{OUT}: {len(data['country'])} countries, {sum(map(len, data['state'].values()))} state names, "
          f"{OUT.stat().st_size} bytes; {data['source']}")


if __name__ == "__main__":
    main(sys.argv)
