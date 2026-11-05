"""Hotel Booking Demand (António, de Almeida, Nunes 2019, CC BY 4.0) -> one row per booking, English labels."""
import csv
from pathlib import Path
DATA = Path(__file__).resolve().parent / "data"
M = "January February March April May June July August September October November December".split()
SEG = {"Online TA": "Online agents", "Offline TA/TO": "Offline agents", "Groups": "Groups", "Direct": "Direct", "Corporate": "Corporate"}
def band(d):
    return "0-7 days" if d <= 7 else "8-30 days" if d <= 30 else "31-90 days" if d <= 90 else "91-180 days" if d <= 180 else "181+ days"
with open(DATA / "raw_hotels.csv", encoding="utf8", newline="") as f, open(DATA / "hotel_bookings.csv", "w", encoding="utf8", newline="") as g:
    w = csv.writer(g)
    w.writerow(["Booking ID", "Hotel", "Arrival Date", "Arrival Month", "Arrival Period", "Lead Time Days", "Lead Time Band", "Segment", "Deposit Type", "Cancelled", "Outcome", "Nights", "Daily Rate", "Booked Value"])
    for i, r in enumerate(csv.DictReader(f), 1):
        m = M.index(r["arrival_date_month"]) + 1
        n = int(r["stays_in_weekend_nights"]) + int(r["stays_in_week_nights"])
        d = int(r["lead_time"])
        w.writerow([i, r["hotel"].replace(" Hotel", " hotel"), f'{r["arrival_date_year"]}-{m:02d}-{int(r["arrival_date_day_of_month"]):02d}', M[m - 1][:3], f'{M[m - 1][:3]} {r["arrival_date_year"][2:]}', d, band(d),
                    SEG.get(r["market_segment"], "Other"), r["deposit_type"], r["is_canceled"], "Cancelled" if r["is_canceled"] == "1" else "Stayed", n, r["adr"], round(float(r["adr"]) * n, 2)])
