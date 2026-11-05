"""sales.csv as an Excel workbook for the Excel source (decisions/025).

The table is on the second sheet 'Orders 2025' (the first one is a note: the spec must name the sheet), dates are
real Excel date cells (Order Date) and date-time cells (Shipped At), every 50th Profit is empty.
Run: python data/sample/make_sales_xlsx.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

import openpyxl


def main():
    here = Path(__file__).parent
    with open(here / "sales.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rnd = random.Random(2025)
    wb = openpyxl.Workbook()
    note = wb.active
    note.title = "README"
    note.append(["Sample sales for tableau-builder: the data is on the sheet 'Orders 2025'."])
    ws = wb.create_sheet("Orders 2025")
    ws.append(["Order Date", "Shipped At", "Region", "Category", "Sales", "Profit", "Quantity"])
    for i, r in enumerate(rows):
        day = dt.date.fromisoformat(r["Order Date"])
        shipped = dt.datetime(day.year, day.month, day.day) + dt.timedelta(hours=rnd.randint(20, 96),
                                                                            minutes=rnd.randint(0, 59))
        profit = None if i % 50 == 49 else float(r["Profit"])
        ws.append([day, shipped, r["Region"], r["Category"], float(r["Sales"]), profit, int(r["Quantity"])])
    for row in ws.iter_rows(min_row=2, max_col=2):
        row[0].number_format = "dd.mm.yyyy"
        row[1].number_format = "dd.mm.yyyy hh:mm"
    wb.save(here / "sales.xlsx")


if __name__ == "__main__":
    main()
