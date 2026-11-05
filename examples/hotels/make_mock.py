"""Mock of the showcase book: every number is counted from hotel_bookings.csv and written into the page."""
import csv, collections as C, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from tbuilder import profile_from
css = profile_from.css("hotels")
R = list(csv.DictReader(open(HERE / "data" / "hotel_bookings.csv", encoding="utf8")))
for r in R:
    r["c"] = int(r["Cancelled"]); r["ym"] = r["Arrival Date"][:7]; r["y"] = r["Arrival Date"][:4]
SEG = ["Groups", "Online agents", "Offline agents", "Corporate", "Direct", "Other"]
BAND = ["0-7 days", "8-30 days", "31-90 days", "91-180 days", "181+ days"]
MON = "Jan Feb Mar Apr May Jun Jul Aug".split()
def rate(rows): return sum(r["c"] for r in rows) / len(rows) if rows else None
def pct(x): return f"{x*100:.0f}%"
def by(k, rows=R):
    d = C.defaultdict(list)
    for r in rows: d[r[k]].append(r)
    return d
seg, band = by("Segment"), by("Lead Time Band")
lo, hi = (241, 241, 241), (244, 132, 46)
def col(x, m):
    t = min(x / m, 1)
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip(lo, hi))
cells = {(s, b): rate([r for r in seg[s] if r["Lead Time Band"] == b]) for s in SEG for b in BAND}
mx = max(v for v in cells.values() if v is not None)
heat = '<div class="heat"><div></div>'
top = max(rate(band[b]) for b in BAND)
for b in BAND:
    heat += f'<div class="m"><i style="height:{rate(band[b])/top*46:.0f}px"></i><b>{pct(rate(band[b]))}</b></div>'
heat += '<div></div><div></div>' + "".join(f'<div class="h">{b.replace(" days", "")}</div>' for b in BAND) + '<div class="h">All</div>'
smax = max(rate(seg[s]) for s in SEG)
for s in SEG:
    heat += f'<div class="r">{s}</div>'
    for b in BAND:
        x = cells[(s, b)]
        fg = "#fff" if x > .55 else "var(--tb-color-text)"
        heat += f'<div class="c" style="background:{col(x, mx)};color:{fg}">{pct(x)}</div>'
    heat += f'<div class="s"><i style="width:{rate(seg[s])/smax*70:.0f}px"></i><b>{pct(rate(seg[s]))}</b></div>'
heat += "</div>"
months = sorted({r["ym"] for r in R})
def bars(h):
    rows = [r for r in R if r["Hotel"] == h]; d = by("ym", rows); peak = max(len(v) for v in d.values())
    w = 400 / len(months); s = '<svg viewBox="0 0 400 130" class="ch" preserveAspectRatio="none">'
    for i, m in enumerate(months):
        a = len(d[m]); c = sum(r["c"] for r in d[m])
        s += f'<rect x="{i*w+.5:.1f}" y="{125-a/peak*120:.1f}" width="{w-1:.1f}" height="{a/peak*120:.1f}" fill="var(--tb-color-mark-muted)"/>'
        s += f'<rect x="{i*w+3:.1f}" y="{125-c/peak*120:.1f}" width="{w-6:.1f}" height="{c/peak*120:.1f}" fill="var(--tb-color-bad)"/>'
    return s + "</svg>"
def hotel(h):
    rows = [r for r in R if r["Hotel"] == h]; c = sum(r["c"] for r in rows)
    first = h.split()[0]
    return f'''<div class="row2"><div class="card kpi"><div class="k">{h}</div><div class="v">{rate(rows)*100:.1f}%</div><div class="n">{c:,} of {len(rows):,}</div></div>
<div class="card grow"><h3><b>{first}</b> by month</h3><p><em>cancelled</em> of all bookings</p>{bars(h)}</div></div>'''
def cnt(h, y, m): return sum(r["c"] for r in R if r["Hotel"] == h and r["y"] == y and r["Arrival Month"] == m)
hs = ["City hotel", "Resort hotel"]
c17 = {(h, m): cnt(h, "2017", m) for h in hs for m in MON}; c16 = {(h, m): cnt(h, "2016", m) for h in hs for m in MON}
tot17, tot16 = sum(c17.values()), sum(c16.values())
def panel(vals, delta):
    s = '<div class="pan">'
    peak = max(abs(v) for v in vals.values()); zero = 75 if delta else 125; sc = 60 if delta else 108
    for h in hs:
        s += f'<div class="p"><div class="pn">{h.split()[0]}</div><svg viewBox="0 0 320 150" class="ch2">'
        for i, m in enumerate(MON):
            v = vals[(h, m)]; bh = abs(v) / peak * sc; y = zero - bh if v >= 0 else zero
            f = ("var(--tb-color-bad)" if v > 0 else "var(--tb-color-good)") if delta else "var(--tb-color-accent)"
            s += f'<rect x="{i*40+5}" y="{y:.1f}" width="30" height="{bh:.1f}" fill="{f}"/>'
            s += f'<text x="{i*40+20}" y="147" text-anchor="middle" font-size="9" fill="var(--tb-color-muted)">{m}</text>'
        s += "</svg></div>"
    return s + "</div>"
long_ = band["181+ days"]; wk = band["0-7 days"]
page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Hotel cancellations</title><style>
{css}
*{{box-sizing:border-box}} body{{margin:0;background:var(--tb-color-canvas);font-family:Arial,sans-serif;color:var(--tb-color-text);width:1400px}}
.wrap{{padding:4px;width:1400px;height:900px;display:flex;flex-direction:column;gap:4px}}
h1{{margin:0;font-size:var(--tb-font-dash-title);font-weight:400}} h1 b{{font-weight:700}} .sub{{color:var(--tb-color-subtitle);font-size:11pt;margin-top:3px}}
.card{{background:var(--tb-color-card-bg);border:1px solid var(--tb-color-card-border);padding:12px}}
.card h3{{margin:0;font-size:var(--tb-font-block-title);font-weight:400}} .card p{{margin:2px 0 4px;font-size:var(--tb-font-block-subtitle);color:var(--tb-color-muted)}}
em{{font-style:normal;font-weight:700;color:var(--tb-color-bad-text)}} em.g{{color:var(--tb-color-good-text)}} .ins{{font-size:10pt;margin:2px 0 6px;color:var(--tb-color-subtitle)}}
.top{{display:grid;grid-template-columns:7fr 6fr;gap:4px;flex:5;min-height:0}} .bot{{display:grid;grid-template-columns:1fr 1fr;gap:4px;flex:3;min-height:0}}
.right{{display:flex;flex-direction:column;gap:4px;min-height:0}} .row2{{display:flex;gap:4px;flex:1;min-height:0}} .grow{{flex:1;display:flex;flex-direction:column;min-width:0}} .kpi{{width:150px}}
.k{{font-size:11pt;color:var(--tb-color-subtitle)}} .v{{font-size:24pt;font-weight:700;margin:8px 0 4px}} .n{{font-size:9pt;color:var(--tb-color-muted)}}
.ch{{width:100%;flex:1;min-height:0}} .ch2{{width:100%;height:150px}}
.heat{{display:grid;grid-template-columns:96px repeat(5,1fr) 110px;gap:2px;font-size:10pt}}
.heat .c{{height:34px;display:flex;align-items:center;justify-content:center}} .heat .r{{display:flex;align-items:center}} .heat .h{{font-size:9pt;color:var(--tb-color-muted);text-align:center}}
.heat .m{{height:60px;display:flex;flex-direction:column-reverse;align-items:center;font-size:9pt}} .heat .m i{{display:block;width:60%;background:var(--tb-color-mark-muted)}}
.heat .s{{display:flex;align-items:center;gap:4px;font-size:9pt}} .heat .s i{{display:block;height:16px;background:var(--tb-color-mark-muted)}}
.pan{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .pn{{font-size:10pt}}
.foot{{font-size:8pt;color:var(--tb-color-muted)}}
</style></head><body><div class="wrap">
<header><h1><b>Hotel cancellations</b>: booked earlier, cancelled more</h1>
<div class="sub">{len(R):,} bookings, two hotels in Portugal, Jul 2015 to Aug 2017</div></header>
<div class="top"><div class="card"><h3><b>Lead time</b></h3><p>% cancelled, by days booked ahead | Click to filter</p>
<div class="ins">Within a week <b>{pct(rate(wk))}</b>; 181+ days <b>{pct(rate(long_))}</b>, <b>{pct(rate([r for r in long_ if r["Deposit Type"] != "Non Refund"]))}</b> without non-refund</div>{heat}</div>
<div class="right">{hotel("City hotel")}{hotel("Resort hotel")}</div></div>
<div class="bot"><div class="card"><h3><b>2017</b> cancellations</h3><div class="ins"><b>+{(tot17-tot16)/tot16*100:.0f}%</b> vs Jan-Aug 2016</div>{panel(c17, False)}</div>
<div class="card"><h3><b>Change vs 2016</b></h3><p><em>more</em> or <em class="g">fewer</em> cancelled</p><div class="ins">&nbsp;</div>{panel({k: c17[k]-c16[k] for k in c17}, True)}</div></div>
</div></body></html>'''
open(HERE / "data" / "page.html", "w", encoding="utf8").write(page)
print(len(R), sum(r["c"] for r in R), tot17, tot16, rate(long_), rate(wk))
