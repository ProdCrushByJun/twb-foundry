"""Large CSVs: the package holds a Hyper file instead of the text file (decisions/026).

A CSV bigger than the threshold is written to a .hyper with the types the profiler gave its columns (the same
types the workbook declares for a CSV), values parsed the same way (dates.py: the profiler's ISO values), so the
extract, the workbook and expected.py all agree. The workbook connects to the .hyper as its own source
(connection class 'hyper', table [Extract].[Extract]), the shape Desktop 2025.1 saves for a .hyper file.
"""
import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter, NULLABLE, SqlType, TableDefinition,
                             TableName, Telemetry)

DEFAULT_THRESHOLD_MB = 20
SCHEMA = TABLE = "Extract"  # Tableau's own extracts use "Extract"."Extract"
OBJECT = f"{TABLE} ({SCHEMA}.{TABLE})"  # object-graph id prefix of the table
COLLATION = "binary"  # a string column of a Hyper table created without a collation
SQL_TYPE = {"date": SqlType.date, "datetime": SqlType.timestamp, "string": SqlType.text,
            "integer": SqlType.big_int, "real": SqlType.double}
_PARSE = {"date": dt.date.fromisoformat, "datetime": dt.datetime.fromisoformat, "string": str,
          "integer": int, "real": float}


def wanted(csv_path, threshold_mb):
    """Package this CSV as Hyper? threshold_mb None -> the default; 0 -> always."""
    limit = DEFAULT_THRESHOLD_MB if threshold_mb is None else threshold_mb
    return Path(csv_path).stat().st_size > limit * 2**20


def table_definition(columns):
    return TableDefinition(TableName(SCHEMA, TABLE),
                           [TableDefinition.Column(c.name, SQL_TYPE[c.datatype](), NULLABLE) for c in columns])


def write(prof, out_path):
    """Profiled CSV -> .hyper with one table "Extract"."Extract"; empty values are NULL."""
    parse = [(c.name, _PARSE[c.datatype]) for c in prof.columns]
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""}) as hp:  # no hyperd.log
        with Connection(hp.endpoint, out_path, CreateMode.CREATE_AND_REPLACE) as con:
            con.catalog.create_schema(SCHEMA)
            table = table_definition(prof.columns)
            con.catalog.create_table(table)
            with Inserter(con, table) as ins:
                for r in prof.rows:
                    ins.add_row([None if (v := r[n]) == "" else fn(v) for n, fn in parse])
                ins.execute()
    return out_path


# ---- workbook XML ----------------------------------------------------------------------------
def connection(named_connection, dbname):
    """The named connection's own connection: the packaged .hyper, path inside the package."""
    ET.SubElement(named_connection, "connection", {
        "authentication": "auth-none", "author-locale": "en_US", "class": "hyper", "dbname": dbname,
        "default-settings": "yes", "sslmode": "", "username": "", "workgroup-auth-mode": "as-is"})


def relation(parent, conn):
    return ET.SubElement(parent, "relation", {"connection": conn, "name": TABLE, "table": f"[{SCHEMA}].[{TABLE}]",
                                              "type": "table"})
