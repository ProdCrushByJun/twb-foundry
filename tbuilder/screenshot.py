"""HTML page vs Tableau dashboard, by pictures (decisions/048): the second half of the acceptance criterion.

  python -m tbuilder compare-shots <page.html> <book.twbx> [-d out/shots_<name>] [--tableau-png x.png]

1. HTML: headless Chrome screenshot + the outline's heading boxes (tbuilder/html_outline.py).
2. Tableau: the book is opened in its own Desktop process (desktop_check.check, decisions/022); once it is
   loaded, its main window is restored *without activation* at the bottom of the z-order and captured with
   PrintWindow(PW_RENDERFULLCONTENT). No clicks, no keys, no computer use. The dashboard is cut out of the window
   by its size from the .twb (<size>) and the workspace margin around it.
3. Both are cropped to their content (what differs from the page background) and resized to one grid.
4. Scores, each 0..1:
   - structure: SSIM of the grey images on a coarse grid (24 cells wide, 4 x 4-cell windows);
   - layout:    mean of (a) the page's headings (outline) found among the dashboard's text zones (.twb) by their
                words and compared by position, (b) the correlation of "ink" (edge) density on an 8 x 8 grid;
   - color:     histogram intersection of the quantized colors (whole image and its chromatic part).
   similar = every score >= its threshold (THRESHOLDS; why these numbers: decisions/048).
Report: report.json + diff.png (page | dashboard | difference) in the output folder.

Images are plain RGB byte strings (Image); PNG is read with GDI+ (Windows) and written with zlib, so no Pillow or
numpy is needed. The metric functions are pure and tested on synthetic images (tests/test_screenshot.py).
"""
import argparse
import ctypes
import json
import re
import struct
import sys
import tempfile
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

WORK_W = 320              # working width (ink, color, diff picture); the height follows the page's aspect ratio
SSIM_W, SSIM_WIN = 24, 4  # structure: SSIM on a grid 24 cells wide (a cell ~ 52 px of a 1250 px page), 4x4 windows
INK_CELLS = 8             # layout: ink density on an 8 x 8 grid
COLOR_LEVELS = 6          # per channel: 216 color bins
THRESHOLDS = {"structure": 0.33, "layout": 0.35, "color": 0.50}  # decisions/048


@dataclass
class Image:
    w: int
    h: int
    px: bytes  # RGB, row-major

    def pixel(self, x, y):
        i = (y * self.w + x) * 3
        return tuple(self.px[i:i + 3])


# ---- image basics ----------------------------------------------------------------------------------------
def solid(w, h, rgb):
    return Image(w, h, bytes(rgb) * (w * h))


def paint(img, box, rgb):
    """A copy of img with the rectangle (x, y, w, h) filled."""
    x, y, w, h = box
    x0, y0, x1, y1 = max(0, x), max(0, y), min(img.w, x + w), min(img.h, y + h)
    px = bytearray(img.px)
    row = bytes(rgb) * max(0, x1 - x0)
    for yy in range(y0, y1):
        i = (yy * img.w + x0) * 3
        px[i:i + len(row)] = row
    return Image(img.w, img.h, bytes(px))


def crop(img, box):
    x, y, w, h = box
    rows = [img.px[((y + r) * img.w + x) * 3:((y + r) * img.w + x + w) * 3] for r in range(h)]
    return Image(w, h, b"".join(rows))


def resize(img, w, h):
    """Area average (downscaling) / nearest (upscaling) -> Image w x h."""
    xs = [(img.w * i // w, max(img.w * (i + 1) // w, img.w * i // w + 1)) for i in range(w)]
    out = bytearray(w * h * 3)
    for j in range(h):
        y0, y1 = img.h * j // h, max(img.h * (j + 1) // h, img.h * j // h + 1)
        sums = [[0] * w for _ in range(3)]
        for y in range(y0, y1):
            row = img.px[y * img.w * 3:(y + 1) * img.w * 3]
            for c in range(3):
                ch = row[c::3]
                s = sums[c]
                for i, (a, b) in enumerate(xs):
                    s[i] += sum(ch[a:b])
        for i, (a, b) in enumerate(xs):
            n = (b - a) * (y1 - y0)
            k = (j * w + i) * 3
            out[k], out[k + 1], out[k + 2] = (sums[0][i] // n, sums[1][i] // n, sums[2][i] // n)
    return Image(w, h, bytes(out))


def gray(img):
    p = img.px
    return [(299 * p[i] + 587 * p[i + 1] + 114 * p[i + 2]) / 1000 for i in range(0, len(p), 3)]


def background(img):
    """The most common color of the image border (the page / dashboard background)."""
    counts = {}
    for x in range(img.w):
        for y in (0, img.h - 1):
            c = img.pixel(x, y)
            counts[c] = counts.get(c, 0) + 1
    for y in range(img.h):
        for x in (0, img.w - 1):
            c = img.pixel(x, y)
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=counts.get)


def content_box(img, tol=10, step=2):
    """Bounding box (x, y, w, h) of what differs from the background by more than tol (sampled every step px)."""
    bg = background(img)
    plain = bytes(bg) * img.w

    def ink(x, y):
        c = img.pixel(x, y)
        return max(abs(c[0] - bg[0]), abs(c[1] - bg[1]), abs(c[2] - bg[2])) > tol
    xs, ys = [], []
    for y in range(0, img.h, step):
        if img.px[y * img.w * 3:(y + 1) * img.w * 3] == plain:
            continue
        left = next((x for x in range(0, img.w, step) if ink(x, y)), None)  # scan in from both ends only
        if left is not None:
            xs += [left, next((x for x in range(img.w - 1, left, -step) if ink(x, y)), left)]
            ys.append(y)
    if not xs:
        return 0, 0, img.w, img.h
    x0, y0 = max(0, min(xs) - step), max(0, min(ys) - step)
    x1, y1 = min(img.w, max(xs) + step + 1), min(img.h, max(ys) + step + 1)
    return x0, y0, x1 - x0, y1 - y0


# ---- metrics (pure) ---------------------------------------------------------------------------------------
def ssim(a, b, win=SSIM_WIN):
    """Mean SSIM of two same-size images over win x win windows with stride win/2 (grey, 0..255)."""
    assert (a.w, a.h) == (b.w, b.h)
    ga, gb, w = gray(a), gray(b), a.w
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    step, vals = max(1, win // 2), []
    for y0 in range(0, max(1, a.h - win + 1), step):
        for x0 in range(0, max(1, a.w - win + 1), step):
            xa, xb = [], []
            for y in range(y0, min(a.h, y0 + win)):
                xa += ga[y * w + x0:y * w + min(w, x0 + win)]
                xb += gb[y * w + x0:y * w + min(w, x0 + win)]
            n = len(xa)
            ma, mb = sum(xa) / n, sum(xb) / n
            va = sum((v - ma) ** 2 for v in xa) / n
            vb = sum((v - mb) ** 2 for v in xb) / n
            cov = sum((p - ma) * (q - mb) for p, q in zip(xa, xb)) / n
            vals.append(((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2)))
    return sum(vals) / len(vals)


def ink_density(img, cells=INK_CELLS, edge=24):
    """Share of 'ink' pixels (grey step > edge to the right or below) per cell of a cells x cells grid, row by
    row. Edges, not colors: the same layout in another theme gives the same map."""
    g, w, h = gray(img), img.w, img.h
    out = []
    for cy in range(cells):
        for cx in range(cells):
            x0, x1 = w * cx // cells, min(w - 1, w * (cx + 1) // cells)
            y0, y1 = h * cy // cells, min(h - 1, h * (cy + 1) // cells)
            hits = n = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    v = g[y * w + x]
                    n += 1
                    hits += abs(v - g[y * w + x + 1]) > edge or abs(v - g[(y + 1) * w + x]) > edge
            out.append(hits / n if n else 0.0)
    return out


def correlation(a, b):
    """Pearson correlation; 0 when either side is flat."""
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) if va and vb else 0.0


def words(text):
    return set(re.findall(r"\w+", text.lower()))


def match_headings(headings, zones, min_share=0.6, near=0.15):
    """Page headings vs dashboard text zones, both [{text, box (x, y, w, h) normalized 0..1}].
    A heading matches the zone holding most of its words (>= min_share); its score falls linearly with the
    distance between the two top-left corners (0 at `near` of the frame). -> (score 0..1, details)."""
    rows = []
    for hd in headings:
        hw = words(hd["text"])
        best, share = None, 0.0
        for z in zones:
            s = len(hw & words(z["text"])) / len(hw) if hw else 0.0
            if s > share:
                best, share = z, s
        if best is None or share < min_share:
            rows.append({"heading": hd["text"], "zone": None, "score": 0.0})
            continue
        d = ((hd["box"][0] - best["box"][0]) ** 2 + (hd["box"][1] - best["box"][1]) ** 2) ** 0.5
        rows.append({"heading": hd["text"], "zone": best["text"][:80], "distance": round(d, 3),
                     "score": round(max(0.0, 1 - d / near), 3)})
    score = sum(r["score"] for r in rows) / len(rows) if rows else None
    return score, rows


def color_hist(img, levels=COLOR_LEVELS, chromatic=False):
    """Share of pixels per quantized color; chromatic=True keeps only colored pixels (max-min channel > 40)."""
    counts, n, p = {}, 0, img.px
    for i in range(0, len(p), 3):
        r, g, b = p[i], p[i + 1], p[i + 2]
        if chromatic and max(r, g, b) - min(r, g, b) <= 40:
            continue
        k = (r * levels // 256, g * levels // 256, b * levels // 256)
        counts[k] = counts.get(k, 0) + 1
        n += 1
    return {k: v / n for k, v in counts.items()} if n else {}


def hist_intersection(a, b):
    if not a and not b:
        return 1.0
    return sum(min(v, b.get(k, 0.0)) for k, v in a.items())


def color_score(a, b):
    """Mean of the whole-image and the chromatic-part intersections (the accent palette counts as much as the
    background, which covers most of the picture)."""
    whole = hist_intersection(color_hist(a), color_hist(b))
    chroma = hist_intersection(color_hist(a, chromatic=True), color_hist(b, chromatic=True))
    return (whole + chroma) / 2, whole, chroma


def palette(img, n=6, levels=8):
    """The n most common colors as hex (quantized; the bin's mean color)."""
    acc, p = {}, img.px
    for i in range(0, len(p), 3):
        k = (p[i] * levels // 256, p[i + 1] * levels // 256, p[i + 2] * levels // 256)
        s = acc.setdefault(k, [0, 0, 0, 0])
        s[0] += p[i]; s[1] += p[i + 1]; s[2] += p[i + 2]; s[3] += 1
    total = len(p) // 3
    top = sorted(acc.values(), key=lambda s: -s[3])[:n]
    return [{"color": "#%02x%02x%02x" % (s[0] // s[3], s[1] // s[3], s[2] // s[3]),
             "share": round(s[3] / total, 3)} for s in top]


def compare(page, dash, page_headings=(), dash_zones=()):
    """Two content-cropped images (+ headings / zones normalized to them) -> (report, page, dashboard), the two
    pictures at the working size (the dashboard is stretched to the page's aspect ratio)."""
    def at(width):
        height = max(4, round(width * page.h / page.w))
        return resize(page, width, height), resize(dash, width, height)
    sa, sb = at(SSIM_W)
    a, b = at(WORK_W)
    structure = ssim(sa, sb, SSIM_WIN)
    ink = max(0.0, correlation(ink_density(a), ink_density(b)))
    anchors, rows = match_headings(list(page_headings), list(dash_zones))
    layout = ink if anchors is None else (anchors + ink) / 2
    color, whole, chroma = color_score(a, b)
    scores = {"structure": round(structure, 3), "layout": round(layout, 3), "color": round(color, 3)}
    return {
        "similar": all(scores[k] >= t for k, t in THRESHOLDS.items()),
        "scores": scores,
        "thresholds": THRESHOLDS,
        "parts": {"ink_correlation": round(ink, 3),
                  "heading_anchors": None if anchors is None else round(anchors, 3),
                  "color_whole": round(whole, 3), "color_chromatic": round(chroma, 3)},
        "headings": rows,
        "palette": {"page": palette(a), "dashboard": palette(b)},
    }, a, b


def diff_image(a, b, scale=1):
    """page | dashboard | difference (red where the grey levels differ), each scaled up `scale` times."""
    ga, gb = gray(a), gray(b)
    d = bytearray(a.w * a.h * 3)
    for i, (p, q) in enumerate(zip(ga, gb)):
        t = min(255, int(abs(p - q) * 2))
        base = int(200 + (p - 128) * 0.2)  # the page, faded
        d[i * 3], d[i * 3 + 1], d[i * 3 + 2] = max(base, t), max(0, base - t), max(0, base - t)
    diff = Image(a.w, a.h, bytes(d))
    gap = 4
    w, h = a.w * 3 + gap * 2, a.h
    rows = []
    sep = b"\xff\xff\xff" * gap
    for y in range(h):
        s = slice(y * a.w * 3, (y + 1) * a.w * 3)
        rows.append(a.px[s] + sep + b.px[s] + sep + diff.px[s])
    joined = Image(w, h, b"".join(rows))
    return joined if scale == 1 else resize(joined, w * scale, h * scale)


# ---- PNG ------------------------------------------------------------------------------------------------------
def save_png(img, path):
    raw = b"".join(b"\x00" + img.px[y * img.w * 3:(y + 1) * img.w * 3] for y in range(img.h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _bgra_to_image(buf, w, h, stride):
    rows = [buf[y * stride:y * stride + w * 4] for y in range(h)]
    b = b"".join(rows)
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = b[2::4], b[1::4], b[0::4]
    return Image(w, h, bytes(rgb))


def load_png(path):
    """Any image GDI+ reads (PNG from Chrome) -> Image."""
    from ctypes import wintypes as wt
    gdip = ctypes.WinDLL("gdiplus")

    class StartupInput(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("callback", ctypes.c_void_p),
                    ("no_thread", wt.BOOL), ("no_codecs", wt.BOOL)]

    class Rect(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]

    class BitmapData(ctypes.Structure):
        _fields_ = [("w", ctypes.c_uint), ("h", ctypes.c_uint), ("stride", ctypes.c_int), ("fmt", ctypes.c_int),
                    ("scan0", ctypes.c_void_p), ("reserved", ctypes.c_void_p)]

    token = ctypes.c_size_t()
    si = StartupInput(1, None, False, False)
    if gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(si), None):
        raise RuntimeError("GDI+ did not start")
    bmp = ctypes.c_void_p()
    try:
        if gdip.GdipCreateBitmapFromFile(ctypes.c_wchar_p(str(Path(path).resolve())), ctypes.byref(bmp)):
            raise RuntimeError(f"cannot read image {path}")
        w, h = ctypes.c_uint(), ctypes.c_uint()
        gdip.GdipGetImageWidth(bmp, ctypes.byref(w))
        gdip.GdipGetImageHeight(bmp, ctypes.byref(h))
        rect, data = Rect(0, 0, w.value, h.value), BitmapData()
        if gdip.GdipBitmapLockBits(bmp, ctypes.byref(rect), 1, 0x26200A, ctypes.byref(data)):  # read, 32bppARGB
            raise RuntimeError(f"cannot decode image {path}")
        buf = ctypes.string_at(data.scan0, data.stride * h.value)
        gdip.GdipBitmapUnlockBits(bmp, ctypes.byref(data))
        return _bgra_to_image(buf, w.value, h.value, data.stride)
    finally:
        if bmp:
            gdip.GdipDisposeImage(bmp)
        gdip.GdiplusShutdown(token)


# ---- Tableau Desktop window -------------------------------------------------------------------------------------
PAINT_WAIT_S = 20  # restored window -> two equal captures in a row


def _win32():
    from ctypes import wintypes as wt
    u, g = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("gdi32")
    u.GetWindowDC.restype = wt.HDC
    u.GetWindowDC.argtypes = [wt.HWND]
    u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    u.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    g.CreateCompatibleDC.restype = wt.HDC
    g.CreateCompatibleDC.argtypes = [wt.HDC]
    g.CreateCompatibleBitmap.restype = wt.HBITMAP
    g.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    g.DeleteObject.argtypes = [wt.HGDIOBJ]
    g.DeleteDC.argtypes = [wt.HDC]
    g.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]
    return u, g, wt


def print_window(hwnd):
    """The window's pixels, rendered by itself (PW_RENDERFULLCONTENT: also GPU-drawn content), even when it is
    covered by other windows. It must be on screen: Qt does not paint the parts outside the monitors."""
    u, g, wt = _win32()
    r = wt.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        if not u.PrintWindow(hwnd, mdc, 2):
            raise RuntimeError("PrintWindow failed")
        header = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # BITMAPINFOHEADER, top-down
        bi = ctypes.create_string_buffer(header, 40 + 16)
        buf = ctypes.create_string_buffer(w * h * 4)
        g.GetDIBits(mdc, bmp, 0, h, buf, bi, 0)
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(hwnd, hdc)
    return _bgra_to_image(buf.raw, w, h, w * 4)


def show_behind(hwnd, width, height):
    """Restore a minimized window without activating it, at the top-left of the primary monitor's work area and
    at the bottom of the z-order (the user's windows stay on top and keep the focus). Windows clamps the size to
    about the screen."""
    u, _, wt = _win32()
    work = wt.RECT()
    u.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
    u.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    flags = 0x10 | 0x40  # SWP_NOACTIVATE | SWP_SHOWWINDOW
    u.SetWindowPos(hwnd, 1, work.left, work.top, width, height, flags)  # HWND_BOTTOM
    _no_hover(hwnd)


def _no_hover(hwnd):
    """Desktop outlines the zone under the cursor (a frame, the container's dashes, a tooltip) while its window is
    the active one, and it can take the focus as it loads: a cursor left over it would be in the picture
    (N8, decisions/168). Then the cursor goes to the title bar; a window that is not active draws no hover."""
    u, _, wt = _win32()
    if u.GetForegroundWindow() != hwnd:
        return
    r, at = wt.RECT(), wt.POINT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    u.GetCursorPos(ctypes.byref(at))
    if r.left <= at.x < r.right and r.top <= at.y < r.bottom:
        u.SetCursorPos(r.left + (r.right - r.left) // 2, r.top + 8)


def _main_window(pid):
    from . import desktop_check as dc
    mains = [w for w in dc.process_windows(pid) if not w.owner]
    if not mains:
        raise RuntimeError(f"no main window of Tableau PID {pid}")
    return mains[0].hwnd


def _settled(hwnd, wait):
    """PrintWindow of hwnd once two captures 1 s apart are equal (or at the deadline)."""
    deadline, last = time.time() + wait, None
    while True:
        time.sleep(1)
        shot = print_window(hwnd)
        if last is not None and shot.px == last.px or time.time() > deadline:
            return shot
        last = shot


def capture_tableau(pid, width, height, wait=PAINT_WAIT_S):
    """The main window of a loaded Tableau process -> Image, once two captures 1 s apart are equal."""
    u, _, _ = _win32()
    old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: physical pixels
    try:
        hwnd = _main_window(pid)
        show_behind(hwnd, width, height)
        return _settled(hwnd, wait)
    finally:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


# The dashboard through UI Automation (decisions/078). Qt exposes Desktop 2025.1's dashboard view as the group
# 'DashboardWidget', every zone as a 'ZoneWidget' with its box on the screen (the largest one is the dashboard itself),
# and the view's vertical scroll bar as 'DashboardWidget.m_yScrollbar' with a RangeValue pattern in px of the dashboard
# (0..225 for a 1500 px dashboard in a 1276 px view): SetValue scrolls the view without a click, a key or the focus.
_VIEW = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$S = [System.Windows.Automation.TreeScope]::Descendants
$e = $A::FromHandle([IntPtr]%HWND%)
function box($r) { "$($r.Left)`t$($r.Top)`t$($r.Width)`t$($r.Height)" }
$bar = $e.FindFirst($S, (New-Object System.Windows.Automation.PropertyCondition($A::AutomationIdProperty, 'DashboardWidget.m_yScrollbar')))
if ($bar) {
  $rv = $bar.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern)
  $want = %VALUE%
  if ($want -ge 0) { $rv.SetValue([Math]::Min([double]$want, $rv.Current.Maximum)) }
  "SCROLL`t$($rv.Current.Value)`t$($rv.Current.Maximum)`t$(box $bar.Current.BoundingRectangle)"
}
$root = $null; $area = 0
foreach ($z in $e.FindAll($S, (New-Object System.Windows.Automation.PropertyCondition($A::ClassNameProperty, 'ZoneWidget')))) {
  $r = $z.Current.BoundingRectangle
  if (-not [double]::IsInfinity($r.Width) -and $r.Width * $r.Height -gt $area) { $root = $r; $area = $r.Width * $r.Height }
}
if ($root) { "ROOT`t$(box $root)" }
"""
SCROLL_OVERLAP = 40  # px of the dashboard seen twice: the next view must repeat them, else it is not stitched


def dashboard_view(hwnd, scroll=-1):
    """{'root': (x, y, w, h) of the dashboard on the screen, 'scroll': (value, maximum, x, y, w, h of the bar) or
    None} after setting the scroll bar to `scroll` px (clamped to its maximum; -1 only reads); None when UI
    Automation does not show the dashboard."""
    import base64
    import subprocess
    script = _VIEW.replace("%HWND%", str(int(hwnd))).replace("%VALUE%", str(int(scroll)))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                              base64.b64encode(script.encode("utf-16-le")).decode()], capture_output=True,
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_view(out)


def parse_view(out):
    """dashboard_view's PowerShell output -> its dict (None without the dashboard's zone)."""
    got = {}
    for line in out.splitlines():
        kind, *vals = line.strip().split("\t")
        if kind in ("ROOT", "SCROLL"):
            try:
                got[kind.lower()] = tuple(round(float(v.replace(",", "."))) for v in vals)
            except ValueError:
                pass
    return {"root": got["root"], "scroll": got.get("scroll")} if "root" in got else None


def stitch(first, rest):
    """first: the dashboard's top as seen (Image w x h0); rest: [(scroll offset px, Image w x hv of the view then)].
    -> Image of the rows seen, top down. A next view is kept only when its rows above what is already there repeat
    them pixel for pixel (it did scroll by its offset), else stitching stops there."""
    w, rows, seen = first.w, first.px, first.h
    for offset, view in rest:
        repeat = seen - offset  # rows of this view already seen
        if not 0 < repeat < view.h or view.w != w or view.px[:repeat * w * 3] != rows[offset * w * 3:seen * w * 3]:
            break
        rows += view.px[repeat * w * 3:]
        seen = offset + view.h
    return Image(w, seen, rows)


def capture_dashboard(pid, w, h, wait=PAINT_WAIT_S):
    """(window Image, dashboard Image w x seen h) of a loaded Tableau process showing a w x h dashboard.
    Where: the dashboard's own zone in UI Automation (dashboard_view; on any theme - the cards theme's grey dashboard
    on the grey workspace defeats locate_visible), else locate_visible. A dashboard taller than the view (the window
    is not taller than the screen, decisions/076) is scrolled through its scroll bar and the views are stitched
    (stitch); seen h < h only when that fails."""
    u, _, wt = _win32()
    old = u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        hwnd = _main_window(pid)
        show_behind(hwnd, w + 700, h + 400)
        win = _settled(hwnd, wait)
        r = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        view = dashboard_view(hwnd)
        bar = view and view["scroll"]
        if view is None or view["root"][2:] != (w, h) or bar and bar[0] != 0:  # not 1:1 pixels; scrolled on open
            x, y, _, vis = locate_visible(win, w, h)
            return win, crop(win, (x, y, w, vis))
        x, y = view["root"][0] - r.left, view["root"][1] - r.top
        if bar is None or bar[1] <= 0:
            return win, crop(win, (x, y, w, min(h, win.h - y)))
        vis = bar[3] + bar[5] - r.top - y  # the view ends with its scroll bar; below are the sheet tabs
        dash, rest, seen = crop(win, (x, y, w, vis)), [], vis
        while seen < h:
            got = dashboard_view(hwnd, seen - SCROLL_OVERLAP)
            if got is None or got["scroll"] is None or got["scroll"][0] <= (rest[-1][0] if rest else 0):
                break
            rest.append((got["scroll"][0], crop(_settled(hwnd, wait), (x, y, w, vis))))
            seen = got["scroll"][0] + vis
        full = stitch(dash, rest)
        return win, crop(full, (0, 0, w, min(h, full.h)))
    finally:
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


def most_common(img, box):
    x, y, w, h = box
    counts = {}
    for yy in range(y, y + h, 2):
        for xx in range(x, x + w, 2):
            c = img.pixel(xx, yy)
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=counts.get)


def locate_dashboard(win, w, h):
    """(x, y, w, h) of a w x h dashboard in a Tableau window capture. The dashboard sits at the top-left of the
    view, the rest of the view is the workspace grey: the dashboard's right edge is the last column (from the
    right) that is not mostly grey, its bottom the first row below which a grey row spans it."""
    grey = most_common(win, (int(win.w * 0.85), int(win.h * 0.3), int(win.w * 0.1), int(win.h * 0.4)))

    def share(xs, ys):
        n = hit = 0
        for y in ys:
            for x in xs:
                n += 1
                hit += win.pixel(x, y) == grey
        return hit / n
    rows = range(int(win.h * 0.15), int(win.h * 0.85), 4)
    right = next((x for x in range(int(win.w * 0.97), w - 1, -1) if share([x], rows) < 0.5), None)
    if right is None:
        raise RuntimeError("dashboard not found in the Tableau window (no workspace margin to its right)")
    left = right - w + 1
    cols = range(left, right + 1, 4)
    below = next((y for y in range(int(win.h * 0.1) + h // 2, win.h) if share(cols, [y]) > 0.95), None)
    if below is None or below - h < 0:
        raise RuntimeError(f"the {w}x{h} dashboard does not fit the Tableau window ({win.w}x{win.h}): "
                           "no workspace margin below it")
    return left, below - h, w, h


def locate_visible(win, w, h):
    """(x, y, w, visible h) of a w x h dashboard in a Tableau window capture, also when it is taller than the window
    (decisions/076): its right edge as locate_dashboard; its top the first row under the toolbar - a band of at least
    10 rows mostly workspace grey across the dashboard's columns - that is not; its height what the window shows."""
    grey = most_common(win, (int(win.w * 0.85), int(win.h * 0.3), int(win.w * 0.1), int(win.h * 0.4)))

    def share(xs, ys):
        return sum(win.pixel(x, y) == grey for y in ys for x in xs) / (len(xs) * len(ys))
    rows = range(int(win.h * 0.15), int(win.h * 0.85), 4)
    right = next((x for x in range(int(win.w * 0.97), w - 1, -1) if share([x], rows) < 0.5), None)
    if right is None:
        raise RuntimeError("dashboard not found in the Tableau window (no workspace margin to its right)")
    left = right - w + 1
    cols = range(left, right + 1, 4)
    grey_rows = [share(cols, [y]) >= 0.5 for y in range(win.h)]
    band = next((y for y in range(win.h - 10) if all(grey_rows[y:y + 10])), None)
    top = next((y for y in range(band, win.h) if not grey_rows[y]), None) if band is not None else None
    if top is None:
        raise RuntimeError("dashboard not found in the Tableau window (no toolbar band above it)")
    return left, top, w, min(h, win.h - top)


# ---- the workbook's dashboard -------------------------------------------------------------------------------
def _twb_root(book):
    book = Path(book)
    if book.suffix.lower() == ".twb":
        return etree.parse(str(book)).getroot()
    with zipfile.ZipFile(book) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n.strip("/"))
        return etree.fromstring(z.read(name))


def dashboard_info(book, name=None):
    """-> (name, width, height, text zones [{text, box px}]) of the dashboard (the first one, or `name`)."""
    root = _twb_root(book)
    dashes = root.findall("./dashboards/dashboard")
    if not dashes:
        raise RuntimeError(f"{Path(book).name}: no dashboard")
    d = next((x for x in dashes if x.get("name") == name), None) if name else dashes[0]
    if d is None:
        raise RuntimeError(f"{Path(book).name}: no dashboard {name!r}")
    size = d.find("size")
    if size is None or not size.get("maxwidth"):
        raise RuntimeError(f"{Path(book).name}: dashboard {d.get('name')!r} has no fixed size")
    w, h = int(size.get("maxwidth")), int(size.get("maxheight"))
    zones = []
    for z in d.iter("zone"):
        if z.get("type-v2") == "text":
            runs = z.iter("run")
        elif z.get("type-v2") is None and z.get("name") and z.get("show-title") != "false":  # a sheet with its title
            sheet = next((s for s in root.iterfind("./worksheets/worksheet") if s.get("name") == z.get("name")), None)
            title = sheet.find("./layout-options/title") if sheet is not None else None
            runs = list(title.iter("run")) if title is not None else [etree.Element("run")]
            if title is None:
                runs[0].text = z.get("name")
        else:
            continue
        text = " ".join(" ".join((r.text or "") for r in runs).replace("Æ", " ").split())
        if text:
            box = [int(z.get(k, 0)) for k in ("x", "y", "w", "h")]
            zones.append({"text": text, "box": [box[0] * w / 100000, box[1] * h / 100000,
                                                box[2] * w / 100000, box[3] * h / 100000]})
    return d.get("name"), w, h, zones


# ---- the HTML page ----------------------------------------------------------------------------------------------
MUTANTS = {  # deliberately different pages for calibrating the thresholds (decisions/048): --mutate
    "dark": ":root{--bg:#0e1117;--panel:#161b22;--ink:#e6edf3;--muted:#8b949e;--faint:#6e7681;--line:#30363d;"
            "--head:#1c2128;--accent:#ffb347;--inc:#ffb347;--sr:#ff7f50;--task:#ffd8a8}",
    "swapped": ".wrap{display:flex;flex-direction:column}.wrap>*{order:1}.wrap>.r2{order:2}.wrap>.r1{order:3}"
               ".wrap>footer{order:4}.row>.panel:first-child{order:2}.r1{grid-template-columns:1fr 2fr}",
}


def mutate(html, css, out):
    """A copy of the page with extra CSS at the end of <head>; a <base> keeps its relative links pointing next to
    the original."""
    raw = Path(html).read_text(encoding="utf-8", errors="replace")
    i = raw.lower().find("</head>")
    tag = f'<base href="{Path(html).resolve().parent.as_uri()}/"><style>{css}</style>'
    raw = raw[:i] + tag + raw[i:] if i >= 0 else tag + raw
    Path(out).write_text(raw, encoding="utf-8")
    return Path(out)


def page_shot(html, png):
    """Screenshot of the page at its own size + its headings with boxes [{text, box}] at that size."""
    from . import html_outline as ho

    def raw_outline(tmp, width, height):
        copy = ho._instrumented_copy(html, tmp)
        res = ho._run_chrome([f"--window-size={width},{height}", "--dump-dom", copy.as_uri()])
        node = etree.HTML(res.stdout or "<html/>").find(".//script[@id='tb-outline']")
        if node is None:
            raise RuntimeError(f"outline script did not run for {html}: {res.stderr[-400:]}")
        return json.loads(node.text)
    with tempfile.TemporaryDirectory() as tmp:
        pw, ph = raw_outline(tmp, 1600, 1000)["page"]
        pw, ph = max(pw, 400), min(max(ph, 300), 6000)
        raw = raw_outline(tmp, pw, ph)  # the boxes at the screenshot's window size
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    ho._run_chrome([f"--window-size={pw},{ph}", f"--screenshot={Path(png).resolve()}", Path(html).resolve().as_uri()])
    return load_png(png), [{"text": hd["text"], "box": hd["box"]} for hd in raw["headings"]]


def _normalize(items, frame):
    fx, fy, fw, fh = frame
    return [{"text": i["text"], "box": [(i["box"][0] - fx) / fw, (i["box"][1] - fy) / fh,
                                        i["box"][2] / fw, i["box"][3] / fh]} for i in items]


# ---- one comparison --------------------------------------------------------------------------------------------
def run(html, book, out_dir, tableau_png=None, dashboard=None, mutant=None):
    """compare-shots -> report dict (also written to out_dir/report.json, with diff.png and the two pictures)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name, w, h, zones = dashboard_info(book, dashboard)
    if mutant:
        html = mutate(html, MUTANTS[mutant], out / f"page.{mutant}.html")
    page, headings = page_shot(html, out / "page.png")
    if tableau_png:
        dash = load_png(tableau_png)
    else:
        from . import desktop_check as dc
        shots = {}
        r = dc.check(book, on_loaded=lambda pid: shots.setdefault("got", capture_dashboard(pid, w, h)))
        if r.status != dc.OK:
            raise RuntimeError(f"Desktop {r.status}: {r.message}")
        window, dash = shots["got"]  # a dashboard taller than the window is scrolled and stitched (decisions/091)
        save_png(window, out / "window.png")
        save_png(dash, out / "tableau.png")
    if (dash.w, dash.h) != (w, h):
        raise RuntimeError(f"dashboard picture is {dash.w}x{dash.h}, the book says {w}x{h}")
    pf, df = content_box(page), content_box(dash)
    report, a, b = compare(crop(page, pf), crop(dash, df), _normalize(headings, pf), _normalize(zones, df))
    save_png(diff_image(a, b), out / "diff.png")
    report = {"page": str(Path(html)), "book": str(Path(book)), "dashboard": name, "mutant": mutant,
              "page_content": list(pf), "dashboard_content": list(df), **report}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def report_text(r):
    s = r["scores"]
    lines = [f"{'SIMILAR' if r['similar'] else 'DIFFERENT'}  structure {s['structure']:.3f} / layout "
             f"{s['layout']:.3f} / color {s['color']:.3f}  (thresholds " +
             " / ".join(f"{v:.2f}" for v in r["thresholds"].values()) + ")"]
    p = r["parts"]
    lines.append(f"  layout: ink correlation {p['ink_correlation']:.3f}, heading anchors {p['heading_anchors']}; "
                 f"color: whole {p['color_whole']:.3f}, chromatic {p['color_chromatic']:.3f}")
    for row in r["headings"]:
        where = f"-> zone '{row['zone']}' d={row['distance']}" if row["zone"] else "-> no zone with its words"
        lines.append(f"  {row['score']:.2f}  {row['heading'][:50]!r} {where}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="compare-shots", description="HTML page vs Tableau dashboard by pictures "
                                 "(decisions/048); exit 1 unless similar.")
    ap.add_argument("html", type=Path)
    ap.add_argument("book", type=Path)
    ap.add_argument("-d", "--dir", type=Path, help="output folder (default out/shots_<book>)")
    ap.add_argument("--tableau-png", type=Path, help="a dashboard picture captured before (tableau.png): no Desktop")
    ap.add_argument("--dashboard", help="dashboard name (default: the first)")
    ap.add_argument("--mutate", choices=sorted(MUTANTS), help="compare a deliberately changed page (calibration)")
    a = ap.parse_args(argv)
    out = a.dir or Path("out") / f"shots_{a.book.stem}{'_' + a.mutate if a.mutate else ''}"
    r = run(a.html, a.book, out, a.tableau_png, a.dashboard, a.mutate)
    print(report_text(r))
    print(out / "report.json")
    return 0 if r["similar"] else 1
