"""sales_nulls.csv: data/sample/sales.csv with empty dimension values (decisions/056).

Each kind of empty sits in its own column and its own rows (no row has two), so each mark shows one kind:
- Region: unquoted empty field (`,,`), rows i % 25 == 3 (20 rows);
- Category: quoted empty string (`,"",`), rows i % 40 == 7 (13 rows);
- Channel (new, Online / Store by row parity): a single space (`, ,`), rows i % 30 == 11 (17 rows);
- Order Date: unquoted empty, rows i % 50 == 13 (10 rows).
Written by hand, not by csv.writer, so the quoting is exactly the one described.
"""
import csv
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE.parent.parent / "data" / "sample" / "sales.csv"


def main():
    with open(SRC, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    lines = ["Order Date,Region,Category,Channel,Sales,Profit,Quantity"]
    for i, r in enumerate(rows):
        date = "" if i % 50 == 13 else r["Order Date"]
        region = "" if i % 25 == 3 else r["Region"]
        category = '""' if i % 40 == 7 else r["Category"]
        channel = " " if i % 30 == 11 else ("Online" if i % 2 else "Store")
        lines.append(",".join([date, region, category, channel, r["Sales"], r["Profit"], r["Quantity"]]))
    (HERE / "sales_nulls.csv").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


if __name__ == "__main__":
    main()
