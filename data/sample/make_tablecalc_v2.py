"""data/sample/tablecalc_v2.csv: 2 regions x 6 months, ties in Sales and NULL Refunds (decisions/147)."""
from pathlib import Path

SALES = {"A": [40, 25, 25, 60, 10, 25], "B": [30, 30, 70, 20, 20, 50]}
REFUNDS = {"A": [5, None, 8, None, None, 3], "B": [None, 4, None, 6, 6, None]}
lines = ["Region,Month,Sales,Refunds"]
for r in "AB":
    for i in range(6):
        v = REFUNDS[r][i]
        lines.append(f"{r},M{i + 1},{SALES[r][i]},{'' if v is None else v}")
Path(__file__).with_name("tablecalc_v2.csv").write_text("\n".join(lines) + "\n", encoding="utf8", newline="\n")
