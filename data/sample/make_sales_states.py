"""Deterministic sample for tile grids (decisions/154): orders of a US company in every state and DC, with the
state's code, census region and its tile on a US tile map (Tile Row / Tile Col, 1-based: the geographic layout comes
from the data, as the reference's 'US States Tilemap' sheet).
Run: python data/sample/make_sales_states.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

# code -> (state, region, tile row, tile col): a common 8 x 11 US tile layout
STATES = {
    "AK": ("Alaska", "West", 1, 1), "ME": ("Maine", "Northeast", 1, 11),
    "VT": ("Vermont", "Northeast", 2, 10), "NH": ("New Hampshire", "Northeast", 2, 11),
    "WA": ("Washington", "West", 3, 1), "ID": ("Idaho", "West", 3, 2), "MT": ("Montana", "West", 3, 3),
    "ND": ("North Dakota", "Midwest", 3, 4), "MN": ("Minnesota", "Midwest", 3, 5), "IL": ("Illinois", "Midwest", 3, 6),
    "WI": ("Wisconsin", "Midwest", 3, 7), "MI": ("Michigan", "Midwest", 3, 8), "NY": ("New York", "Northeast", 3, 9),
    "RI": ("Rhode Island", "Northeast", 3, 10), "MA": ("Massachusetts", "Northeast", 3, 11),
    "OR": ("Oregon", "West", 4, 1), "NV": ("Nevada", "West", 4, 2), "WY": ("Wyoming", "West", 4, 3),
    "SD": ("South Dakota", "Midwest", 4, 4), "IA": ("Iowa", "Midwest", 4, 5), "IN": ("Indiana", "Midwest", 4, 6),
    "OH": ("Ohio", "Midwest", 4, 7), "PA": ("Pennsylvania", "Northeast", 4, 8), "NJ": ("New Jersey", "Northeast", 4, 9),
    "CT": ("Connecticut", "Northeast", 4, 10),
    "CA": ("California", "West", 5, 1), "UT": ("Utah", "West", 5, 2), "CO": ("Colorado", "West", 5, 3),
    "NE": ("Nebraska", "Midwest", 5, 4), "MO": ("Missouri", "Midwest", 5, 5), "KY": ("Kentucky", "South", 5, 6),
    "WV": ("West Virginia", "South", 5, 7), "VA": ("Virginia", "South", 5, 8), "MD": ("Maryland", "South", 5, 9),
    "DE": ("Delaware", "South", 5, 10),
    "AZ": ("Arizona", "West", 6, 2), "NM": ("New Mexico", "West", 6, 3), "KS": ("Kansas", "Midwest", 6, 4),
    "AR": ("Arkansas", "South", 6, 5), "TN": ("Tennessee", "South", 6, 6), "NC": ("North Carolina", "South", 6, 7),
    "SC": ("South Carolina", "South", 6, 8), "DC": ("District of Columbia", "South", 6, 9),
    "OK": ("Oklahoma", "South", 7, 4), "LA": ("Louisiana", "South", 7, 5), "MS": ("Mississippi", "South", 7, 6),
    "AL": ("Alabama", "South", 7, 7), "GA": ("Georgia", "South", 7, 8),
    "HI": ("Hawaii", "West", 8, 1), "TX": ("Texas", "South", 8, 4), "FL": ("Florida", "South", 8, 9),
}
BIG = {"CA": 12, "TX": 9, "FL": 7, "NY": 7, "PA": 4, "IL": 4, "OH": 4, "GA": 3, "NC": 3, "MI": 3, "NJ": 3, "VA": 3,
       "WA": 3, "AZ": 2, "MA": 2, "TN": 2, "IN": 2, "MO": 2, "MD": 2, "WI": 2, "CO": 2, "MN": 2}


def main():
    rnd = random.Random(154)
    codes = list(STATES)
    weights = [BIG.get(c, 1) for c in codes]
    start = dt.date(2025, 1, 1)
    rows = []
    for i in range(1500):
        code = codes[i] if i < len(codes) else rnd.choices(codes, weights)[0]  # every state has orders
        state, region, r, c = STATES[code]
        sales = round(rnd.uniform(20, 900), 2)
        rows.append([(start + dt.timedelta(days=rnd.randrange(365))).isoformat(), state, code, region, r, c,
                     sales, round(sales * rnd.uniform(-0.15, 0.35), 2)])
    rows.sort()
    out = Path(__file__).with_name("sales_states.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "State", "Code", "Region", "Tile Row", "Tile Col", "Sales", "Profit"])
        w.writerows(rows)
    print(out, len(rows))


if __name__ == "__main__":
    main()
