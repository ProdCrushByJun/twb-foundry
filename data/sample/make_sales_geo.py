"""Deterministic sample for maps (decisions/046): orders of a US company by the customer's State and City (built-in
geocoding, country context United States) and by the Ship Country they go to (a filled map of countries), with the
city's Latitude / Longitude (a map from the data's own coordinates).
Run: python data/sample/make_sales_geo.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

# state -> (city, latitude, longitude); 12 states, one city each
CITIES = {"California": ("Los Angeles", 34.0522, -118.2437), "Texas": ("Houston", 29.7604, -95.3698),
          "New York": ("Buffalo", 42.8864, -78.8784), "Florida": ("Miami", 25.7617, -80.1918),
          "Illinois": ("Chicago", 41.8781, -87.6298), "Washington": ("Seattle", 47.6062, -122.3321),
          "Colorado": ("Denver", 39.7392, -104.9903), "Georgia": ("Atlanta", 33.7490, -84.3880),
          "Massachusetts": ("Boston", 42.3601, -71.0589), "Arizona": ("Phoenix", 33.4484, -112.0740),
          "Ohio": ("Columbus", 39.9612, -82.9988), "Minnesota": ("Minneapolis", 44.9778, -93.2650)}
WEIGHT = {"California": 9, "Texas": 7, "New York": 6, "Florida": 5, "Illinois": 4, "Washington": 3,
          "Colorado": 2, "Georgia": 3, "Massachusetts": 3, "Arizona": 2, "Ohio": 2, "Minnesota": 1}
COUNTRIES = {"United States": 10, "Canada": 4, "Mexico": 3, "United Kingdom": 3, "Germany": 3, "France": 2,
             "Japan": 2, "Brazil": 2, "Australia": 1}


def main():
    rnd = random.Random(46)
    states, countries = list(WEIGHT), list(COUNTRIES)
    rows = []
    start = dt.date(2025, 1, 1)
    for _ in range(600):
        state = rnd.choices(states, [WEIGHT[s] for s in states])[0]
        city, lat, lon = CITIES[state]
        country = rnd.choices(countries, [COUNTRIES[c] for c in countries])[0]
        sales = round(rnd.uniform(20, 900), 2)
        rows.append([(start + dt.timedelta(days=rnd.randrange(365))).isoformat(), state, city, lat, lon, country,
                     sales, round(sales * rnd.uniform(-0.15, 0.35), 2)])
    rows.sort()
    out = Path(__file__).with_name("sales_geo.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "State", "City", "Latitude", "Longitude", "Ship Country", "Sales", "Profit"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
