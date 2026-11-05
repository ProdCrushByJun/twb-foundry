"""What did Desktop silently drop? Diff of a workbook against its re-save by Desktop (decisions/054).

Desktop opens a workbook without a word even when it cannot resolve parts of it (decisions/016: a palette map
without a column-instance) and drops those parts from its model. Only a save shows it: the re-saved XML lacks them.

diff(original, resaved) aligns the two XML trees element by element (an element is identified by its tag and its
identifying attributes, siblings with the same identity by their order) and lists what was dropped, added or
changed. COSMETIC rules then set aside what Desktop rewrites on every save of a good workbook (collected from the
hybrid goldens: generator output vs the same workbook saved by Desktop 2025.1). What is left is the report.

resave(book) does the Desktop part: desktop_check.check() opens the book in its own process; once it is loaded,
File > Save As... through UI Automation writes out/resave/<book>.resaved.twbx; then every sheet not shown at open
gets its own copy with that sheet shown, opened by check() (Desktop draws only the shown sheet, decisions/022).
CLI: python -m tbuilder check-desktop --resave <book.twbx> [...].
"""
import ctypes
import difflib
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import desktop_check as dc

ET.register_namespace("user", "http://www.tableausoftware.com/xml/user")  # the sheet copies keep Desktop's prefix
DROPPED, ADDED, CHANGED = "dropped", "added", "changed"
# attributes that name an element among its siblings (in this order); the rest of the attributes are its content
KEY_ATTRS = ("name", "column", "field", "attr", "scope", "class", "key", "id", "param", "type-v2", "data-class",
             "element", "to", "role", "function", "level", "member",
             "datasource",  # a dependencies block by its source: several are ordered by name (decisions/083)
             "node-guid")  # a datagraph node and its subgraph pair: Desktop writes the pairs in no set order (082)


def read_twb(path):
    """XML root of a .twb or of the .twb inside a .twbx."""
    path = Path(path)
    if path.suffix.lower() == ".twbx":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n)
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


@dataclass
class Item:
    kind: str           # dropped | added | changed
    path: str           # /workbook/worksheets/worksheet[name=Bar]/table/...
    el: object = None   # the element (dropped: the original's, added: the re-saved one's; changed: the original's)
    attr: str = ""      # changed: the attribute ('#text' = the text)
    old: object = None
    new: object = None
    other: object = None  # changed: the re-saved element
    parent: object = None  # the original's parent element (dropped/added: under which it is missing / new)
    size: tuple = None  # (width, height) px of the dashboard the item is in, if any
    rule: str = ""      # name of the COSMETIC rule that explains it, '' = not explained

    @property
    def tag(self):
        return self.el.tag if self.el is not None else ""

    def __str__(self):
        if self.kind == CHANGED:
            return f"{self.kind:<7} {self.path} @{self.attr}: {_short(self.old)!r} -> {_short(self.new)!r}"
        return f"{self.kind:<7} {self.path}" + (f"  {_short(_outline(self.el))}" if self.el is not None else "")


def _short(v, n=160):
    v = "" if v is None else str(v)
    return v if len(v) <= n else v[: n - 3] + "..."


def _outline(el):
    attrs = " ".join(f"{k}={v!r}" for k, v in el.attrib.items())
    return f"<{el.tag} {attrs}>".replace(" >", ">") + (f" {el.text.strip()}" if (el.text or "").strip() else "")


def _text(el):
    t = (el.text or "").strip()
    return t or None


def identity(el):
    return (el.tag,) + tuple((a, el.get(a)) for a in KEY_ATTRS if a in el.attrib)


def _label(ident):
    tag, *keys = ident
    return tag + "".join(f"[{a}={v}]" for a, v in keys[:2])


def dashboard_size(el):
    """(width, height) px of a <dashboard> (its <size>), None for a sheet or an automatic size."""
    s = el.find("size") if el.tag == "dashboard" else None
    w, h = (_num(s.get("maxwidth") or s.get("minwidth")), _num(s.get("maxheight") or s.get("minheight"))) \
        if s is not None else (None, None)
    return (w, h) if w and h else None


def signature(el, memo):
    """Hashable content of a subtree (attribute order does not count)."""
    k = id(el)
    if k not in memo:
        memo[k] = (el.tag, tuple(sorted(el.attrib.items())), _text(el), tuple(signature(c, memo) for c in el))
    return memo[k]


def pairs(xs, ys, memo):
    """Align two lists of siblings with the same identity -> [(x or None, y or None)]: equal subtrees by the longest
    common subsequence (a dropped <run> in the middle of a text does not shift the rest), the rest in order."""
    if len(xs) == 1 and len(ys) == 1:
        return [(xs[0], ys[0])]
    out = []
    sm = difflib.SequenceMatcher(None, [signature(x, memo) for x in xs], [signature(y, memo) for y in ys],
                                 autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        a, b = xs[i1:i2], ys[j1:j2]
        n = min(len(a), len(b)) if op in ("equal", "replace") else 0
        out += list(zip(a[:n], b[:n])) + [(x, None) for x in a[n:]] + [(None, y) for y in b[n:]]
    return out


def diff(a, b):
    """Two XML roots (original, re-saved) -> [Item], unfiltered. Attribute order, quoting, CRLF, the XML
    declaration, the build comment and whitespace around text do not exist after parsing."""
    items, memo = [], {}

    def walk(x, y, path, size, parent):
        size = dashboard_size(x) or size
        for k in sorted(set(x.attrib) | set(y.attrib)):
            if x.get(k) != y.get(k):
                items.append(Item(CHANGED, path, x, k, x.get(k), y.get(k), y, parent=parent, size=size))
        if _text(x) != _text(y):
            items.append(Item(CHANGED, path, x, "#text", _text(x), _text(y), y, parent=parent, size=size))
        xs, ys = {}, {}
        for c in x:
            xs.setdefault(identity(c), []).append(c)
        for c in y:
            ys.setdefault(identity(c), []).append(c)
        for ident in list(xs) + [i for i in ys if i not in xs]:
            many = len(xs.get(ident, ())) > 1
            for c, d in pairs(xs.get(ident, []), ys.get(ident, []), memo):
                n = xs[ident].index(c) + 1 if c is not None else 0
                p = f"{path}/{_label(ident)}" + (f"#{n}" if many and n else "")
                if c is None:
                    items.append(Item(ADDED, p, d, parent=x, size=size))
                elif d is None:
                    items.append(Item(DROPPED, p, c, parent=x, size=size))
                else:
                    walk(c, d, p, size, x)

    walk(a, b, "/" + a.tag, None, None)
    return items


# ---- what Desktop rewrites on every save (collected from the hybrid goldens, decisions/054) ---------------------
@dataclass
class Rule:
    name: str
    why: str
    match: object  # Item -> bool


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _moved(it, *kinds):
    return it.kind in (kinds or (DROPPED, ADDED))


def _ui_state(it):
    # thumbnails: the pictures of the sheets; devicelayouts + its manifest flag: the phone layout Desktop generates
    # itself; highlight: the legend items highlighted in a window
    return _moved(it) and it.tag in ("thumbnails", "devicelayouts", "AutoCreateAndUpdateDSDPhoneLayouts", "highlight")


def _active_zone(it):
    return _moved(it) and it.tag == "active" and it.parent is not None and it.parent.tag == "window"


def _empty_viewpoint(it):
    return (_moved(it) and it.tag == "viewpoint" and it.parent is not None and it.parent.tag == "window"
            and it.parent.get("class") == "worksheet" and not it.el.attrib and len(it.el) == 0)


def _flow_card_height(it):
    return (it.kind == CHANGED and it.tag == "zone" and it.attr in ("h", "y")
            and it.el.get("type-v2") in ("color", "filter"))


def _flow_text_height(it):
    p = it.parent
    return (it.kind == CHANGED and it.tag == "zone" and it.attr in ("h", "y") and it.el.get("type-v2") == "text"
            and p is not None and p.get("type-v2") == "layout-flow" and p.get("param") == "vert")


def _in_vert_flow(it):
    p = it.parent
    return p is not None and p.get("type-v2") == "layout-flow" and p.get("param") == "vert"


def _flow_restack(it):
    """A vertical flow (sidebar) is a stack: Desktop recomputes each child's y from the heights above it (the text
    and card heights it measures itself), a zone inside a child moves with it, and the empty spacer gets what is
    left (decisions/092). A height of any other child (a button, a picture) still counts."""
    if not (it.kind == CHANGED and it.tag == "zone"):
        return False
    if it.attr == "y":
        return _in_vert_flow(it) or "[param=vert]/" in it.path  # a vertical flow above it
    return it.attr == "h" and it.el.get("type-v2") == "empty" and _in_vert_flow(it)


ZONE_GEOMETRY = ("x", "y", "w", "h")


def _pixel_snap(it):
    """Zone units are 1/100000 of the dashboard; Desktop stores each edge on the pixel grid (card_lefts: a chain
    of header cards back from the row's right edge). A change below one pixel is that snapping."""
    if not (it.kind == CHANGED and it.tag == "zone" and it.attr in ZONE_GEOMETRY and it.size):
        return False
    a, b = _num(it.old), _num(it.new)
    if a is None or b is None:
        return False
    px = it.size[0] if it.attr in ("x", "w") else it.size[1]
    return abs(a - b) * px / 100000 < 1


def _approx_count(it):
    """<approx-count> of a column metadata-record: Desktop's estimate of the column's distinct values, recomputed
    from the data on every open (decisions/080). A Hyper column gets one always (exact on small data, an estimate on
    1M rows), a CSV column only when it has no value at all (1), an Excel column never; a value written in the
    workbook is overwritten (Hyper) or dropped (CSV)."""
    p = it.parent  # dropped / added: the record it is missing from / new in; changed: the record it is in
    return it.tag == "approx-count" and p is not None and p.tag == "metadata-record" and p.get("class") == "column"


COSMETIC = [
    Rule("ui-state", "thumbnails, the generated phone layout (devicelayouts + AutoCreateAndUpdateDSDPhoneLayouts), "
         "highlighted legend items: Desktop writes them from its own UI state", _ui_state),
    Rule("active-zone", "<active id> of a dashboard window = the selected zone, a UI state", _active_zone),
    Rule("empty-viewpoint", "an empty <viewpoint/> of a worksheet window exists only once that tab was shown",
         _empty_viewpoint),
    Rule("flow-card-height", "legend and filter card heights (and the y of the cards below) are "
         "recomputed from Desktop's own text metrics", _flow_card_height),
    Rule("flow-text-height", "a text zone in a vertical flow panel (sidebar) gets its height from Desktop's text "
         "metrics", _flow_text_height),
    Rule("flow-restack", "a child's y in a vertical flow and the empty spacer's height: Desktop restacks the flow "
         "after measuring its texts and cards (decisions/092)", _flow_restack),
    Rule("pixel-snap", "zone edges moved by less than one pixel of the dashboard: Desktop's pixel grid "
         "(card_lefts)", _pixel_snap),
    Rule("approx-count", "a column's approx-count: Desktop's distinct-value estimate, recomputed from the data on "
         "every open (decisions/080)", _approx_count),
]


def explain(items, rules=None):
    """Mark items a rule explains (item.rule) -> the items no rule explains."""
    rules = COSMETIC if rules is None else rules
    left = []
    for it in items:
        it.rule = next((r.name for r in rules if r.match(it)), "")
        if not it.rule:
            left.append(it)
    return left


@dataclass
class Report:
    original: str
    resaved: str
    items: list = field(default_factory=list)     # every difference
    left: list = field(default_factory=list)      # the ones no COSMETIC rule explains

    @property
    def clean(self):
        return not self.left

    def text(self, limit=60):
        lines = [f"{Path(self.original).name} vs Desktop re-save {Path(self.resaved).name}: "
                 f"{len(self.items)} differences, {len(self.items) - len(self.left)} cosmetic (Desktop's own "
                 f"rewrites), {len(self.left)} by meaning"]
        if self.clean:
            lines.append("nothing dropped or changed by meaning")
        for kind in (DROPPED, CHANGED, ADDED):
            xs = [i for i in self.left if i.kind == kind]
            if xs:
                lines.append(f"{kind}: {len(xs)}")
                lines += [f"  {i}" for i in xs[:limit]] + ([f"  ... {len(xs) - limit} more"] if len(xs) > limit else [])
        return "\n".join(lines)


def compare(original, resaved, rules=None):
    items = diff(read_twb(original), read_twb(resaved))
    return Report(str(original), str(resaved), items, explain(items, rules))



# ---- the re-save in Desktop, without mouse or keyboard ------------------------------------------------------------
# Tableau's own widgets are Qt: reachable through UI Automation only (menu bar 'mainMenu' -> MenuItem 'File' with
# ExpandCollapse -> MenuItem 'Save As...' with Invoke). The Save As dialog is the Windows common file dialog
# (#32770): plain Win32 controls, driven by window messages (WM_SETTEXT to the file name Edit 1001, WM_COMMAND IDOK).
# No mouse, no keys. Opening the Qt menu does activate Tableau's window for ~2-3 s (decisions/054).
SAVE_TIMEOUT_S = 60    # IDOK -> the file written and the dialog gone
DIALOG_WAIT_S = 10     # Save As invoked -> its dialog up
QUIET_S = 1.0          # after the save, the process log is this long quiet before we close...
QUIET_TIMEOUT_S = 20   # ...but not waited for longer than this
MENU_TRIES = 3         # a menu UIA cannot see is looked at again after 1 s
FILE_NAME_ID, FILE_TYPE_ID, IDOK, IDCANCEL = 1001, 0x470, 1, 2
WM_GETTEXT, WM_GETTEXTLENGTH, WM_SETTEXT, WM_COMMAND = 0x000D, 0x000E, 0x000C, 0x0111

_UIA_MENU = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$T = [System.Windows.Automation.TreeScope]
$P = [System.Windows.Automation.PropertyCondition]
$root = $A::FromHandle([IntPtr]%HWND%)
$MI = New-Object $P($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::MenuItem)
$menu = $root.FindAll($T::Descendants, $MI) | Where-Object { $_.Current.Name -eq '%MENU%' } | Select-Object -First 1
if (-not $menu) { "NOMENU"; exit }
$ec = $menu.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
$ec.Expand()
Start-Sleep -Milliseconds 300
$pick = $null
foreach ($x in $menu.FindAll($T::Descendants, $MI)) {
  $n = $x.Current.Name
  "ITEM`t$($x.Current.IsEnabled)`t$n"
  if (-not $pick -and $n -eq '%ITEM%' -and $x.Current.IsEnabled) { $pick = $x }
}
if ($pick) {
  $pick.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  "INVOKED"
} else {
  $ec.Collapse()
}
"""


def _ps(script, timeout=60):
    """Run a Windows PowerShell script -> its stdout ('' if it fails)."""
    import base64
    import subprocess
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                               base64.b64encode(script.encode("utf-16-le")).decode()],
                              capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW
                              ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def parse_menu(out):
    """UIA menu dump -> [(name, enabled)]."""
    items = []
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == "ITEM" and len(parts) == 3:
            items.append((parts[2], parts[1] == "True"))
    return items


def menu(hwnd, top, item):
    """Open menu `top` of a Tableau main window and invoke its `item`; if there is no such enabled item, close the
    menu again -> ([(name, enabled)] of its items, invoked?)."""
    q = lambda s: s.replace("'", "''")  # noqa: E731  (a PowerShell '...' string)
    script = _UIA_MENU.replace("%HWND%", str(hwnd)).replace("%MENU%", q(top)).replace("%ITEM%", q(item))
    for _ in range(MENU_TRIES):
        out = _ps(script)
        if "ITEM\t" in out:
            break
        time.sleep(1)
    return parse_menu(out), "INVOKED" in out.splitlines()


@lru_cache(maxsize=1)
def _win32():
    from ctypes import wintypes as wt
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumChildWindows.argtypes = [wt.HWND, ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
    u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetDlgCtrlID.argtypes = [wt.HWND]
    u.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, ctypes.c_void_p]
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return u, wt


def class_name(hwnd):
    u, _ = _win32()
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, 256)
    return buf.value


def child_controls(hwnd):
    """[(hwnd, control id, class)] of all descendants of a window."""
    u, wt = _win32()
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _):
        out.append((h, u.GetDlgCtrlID(h), class_name(h)))
        return True

    u.EnumChildWindows(hwnd, each, 0)
    return out


def get_text(hwnd):
    u, _ = _win32()
    n = u.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, None)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.SendMessageW(hwnd, WM_GETTEXT, n + 1, ctypes.cast(buf, ctypes.c_void_p))
    return buf.value


def set_text(hwnd, text):
    buf = ctypes.create_unicode_buffer(text)
    _win32()[0].SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.cast(buf, ctypes.c_void_p))


def command(hwnd, cmd):
    _win32()[0].PostMessageW(hwnd, WM_COMMAND, cmd, 0)


def file_dialog(pid, main):
    """The common file dialog our main window owns -> (dialog, file name Edit, file type combo or None) or None."""
    for w in dc.process_windows(pid):
        if w.owner == main and class_name(w.hwnd) == "#32770":
            ctrls = child_controls(w.hwnd)
            edit = next((h for h, i, c in ctrls if i == FILE_NAME_ID and c == "Edit"), None)
            kind = next((h for h, i, c in ctrls if i == FILE_TYPE_ID and c == "ComboBox"), None)
            if edit:
                return w.hwnd, edit, kind
    return None


def find_log(pid, logs=dc.LOGS, tail=4 << 20):
    """The log slot our process writes to (decisions/022), found after the launch: of the log*.txt with a line of
    this PID in their last `tail` bytes, the one written last (an older process with the same PID may have used
    another slot). None if there is none yet."""
    tag, hits = f'"pid":{pid},'.encode(), []
    for f in Path(logs).glob("log*.txt"):
        if f.name.endswith("_bk.txt"):
            continue
        try:
            with open(f, "rb") as fh:
                fh.seek(max(0, f.stat().st_size - tail))
                if tag in fh.read():
                    hits.append((f.stat().st_mtime, f))
        except OSError:
            pass
    return max(hits)[1] if hits else None


def wait_quiet(pid, logs=dc.LOGS, quiet=QUIET_S, timeout=QUIET_TIMEOUT_S):
    """Wait until the process log has not grown for `quiet` seconds."""
    deadline, log, last, since = time.time() + timeout, None, None, time.time()
    while time.time() < deadline:
        log = log or find_log(pid, logs)
        try:
            size = os.path.getsize(log) if log else None
        except OSError:
            size = None
        if size != last:
            last, since = size, time.time()
        elif size is not None and time.time() - since >= quiet:
            return True
        time.sleep(0.2)
    return False


class ResaveError(RuntimeError):
    pass


def _problem(pid, start, logs, allow=()):
    """'' or what went wrong with our process: it is gone / a dialog came up (read and closed)."""
    crash = dc.crash_dump(pid, logs, since=start)
    windows = dc.process_windows(pid)
    if crash or not windows:
        return "Tableau exited" + (f"; crash dump {crash}" if crash else "")
    for d in dc.dialogs(windows):
        if d.hwnd not in allow:
            time.sleep(dc.DIALOG_GRACE_S)
            if any(w.hwnd == d.hwnd for w in dc.process_windows(pid)):
                return dc.dismiss(d.hwnd)
    return ""


def save_as(pid, main, target, start=0.0, logs=dc.LOGS):
    """File > Save As... in our window, the dialog filled through window messages -> the target written.
    Lessons: Save (Ctrl+S) does not write an unchanged book; Save As blind is dangerous, so nothing is typed unless
    the common file dialog of our window is there, and a dialog offering anything but .twbx is cancelled."""
    target = Path(target).resolve()
    if target.exists():
        target.unlink()  # our own output of an earlier run; no 'replace?' prompt
    items, invoked = menu(main, "File", "Save As...")
    if not invoked:
        raise ResaveError(f"File > Save As... not reached through UI Automation "
                          f"(items: {', '.join(n for n, _ in items) or 'none'})")
    deadline, dlg = time.time() + DIALOG_WAIT_S, None
    while dlg is None:
        dlg = file_dialog(pid, main)
        if dlg is None:
            if time.time() > deadline:
                p = _problem(pid, start, logs)
                raise ResaveError("the Save As dialog did not open" + (f": {p}" if p else ""))
            time.sleep(0.25)
    hwnd, edit, kind = dlg
    kind_text = get_text(kind) if kind else ""
    if kind and "twbx" not in kind_text:
        command(hwnd, IDCANCEL)
        raise ResaveError(f"the Save As dialog offers {kind_text!r}, not a packaged workbook (.twbx); cancelled")
    set_text(edit, str(target))
    if get_text(edit) != str(target):
        command(hwnd, IDCANCEL)
        raise ResaveError("the file name did not get into the Save As dialog; cancelled")
    command(hwnd, IDOK)  # = the Save button
    deadline = time.time() + SAVE_TIMEOUT_S
    while True:
        windows = dc.process_windows(pid)
        up = any(w.hwnd == hwnd for w in windows)
        if not up and target.exists() and dc.main_title(target.stem) in [w.title for w in windows]:
            break
        p = _problem(pid, start, logs, allow=(hwnd,))
        if p:
            raise ResaveError(f"while saving: {p}")
        if time.time() > deadline:
            raise ResaveError(f"no {target.name} after {SAVE_TIMEOUT_S} s"
                              + (" (the Save As dialog is still up)" if up else ""))
        time.sleep(0.25)
    wait_quiet(pid, logs)
    return target


# ---- every sheet: Desktop draws only the sheet shown at open --------------------------------------------------------
def windows_of(root):
    """Names of the workbook's windows (the sheets with a tab) and the one shown at open (maximized='true', else
    the last)."""
    ws = list(root.find("windows") if root.find("windows") is not None else [])
    names = [w.get("name") for w in ws]
    shown = next((w.get("name") for w in ws if w.get("maximized") == "true"), names[-1] if names else "")
    return names, shown


def show_first(root, name):
    """The workbook with window `name` shown at open: maximized and last (decisions/022, the crash mutant)."""
    ws = root.find("windows")
    target = next(w for w in ws if w.get("name") == name)
    for w in ws:
        w.attrib.pop("maximized", None)
    target.set("maximized", "true")
    ws.remove(target)
    ws.append(target)
    return root


def sheet_copies(book, out_dir):
    """A copy of the book per sheet not shown at open, with that sheet shown -> [(sheet, path)]."""
    book, out_dir = Path(book), Path(out_dir)
    with zipfile.ZipFile(book) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    twb = next(i.filename for i, _ in members if i.filename.lower().endswith(".twb") and "/" not in i.filename)
    data = dict((i.filename, b) for i, b in members)
    names, shown = windows_of(ET.fromstring(data[twb]))
    out = []
    for n, name in enumerate(x for x in names if x != shown):
        root = show_first(ET.fromstring(data[twb]), name)
        path = out_dir / f"{book.stem}.sheet{n + 1}.twbx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for i, b in members:
                z.writestr(i, ET.tostring(root, encoding="utf-8", xml_declaration=True) if i.filename == twb else b)
        out.append((name, path))
    return out


@dataclass
class Resave:
    book: str
    status: str                 # OK = re-saved, diff in .report | ERROR / CRASH / TIMEOUT (open or re-save failed)
    message: str = ""
    resaved: str = ""
    report: Report = None
    sheets: list = field(default_factory=list)  # [(sheet, dc.Result)] for the sheets not shown at open
    seconds: float = 0.0

    @property
    def bad_sheets(self):
        return [(s, r) for s, r in self.sheets if r.status != dc.OK]

    @property
    def clean(self):
        return self.status == dc.OK and self.report is not None and self.report.clean and not self.bad_sheets

    def text(self):
        head = "CLEAN" if self.clean else "DIFF" if self.status == dc.OK else self.status
        lines = [f"{head:<7} {self.seconds:5.1f}s  {Path(self.book).name}"]
        if self.message:
            lines.append(f"        {self.message}")
        if self.report is not None:
            lines += ["        " + x for x in self.report.text().splitlines()]
        if self.sheets:
            lines.append(f"        every sheet shown at open: {len(self.sheets) - len(self.bad_sheets)}/"
                         f"{len(self.sheets)} OK")
        lines += [f"        sheet {s!r}: {r.status} {r.message}" for s, r in self.bad_sheets]
        return "\n".join(lines)


def resave(book, out_dir, sheets=True, exe=None, timeout=dc.TIMEOUT_S, logs=dc.LOGS):
    """Open the book in its own Tableau process, File > Save As into out_dir, diff -> Resave. sheets: also open a
    copy per sheet not shown at open, with that sheet shown (check-desktop of each; no UI)."""
    book = Path(book).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{book.stem}.resaved.twbx"
    state, t0 = {}, time.time()

    def on_loaded(pid):
        main = next(w.hwnd for w in dc.process_windows(pid) if not w.owner)
        try:
            state["saved"] = save_as(pid, main, target, t0, logs)
        except ResaveError as e:
            state["error"] = str(e)

    r = dc.check(book, exe=exe, timeout=timeout, logs=logs, on_loaded=on_loaded)
    res = Resave(str(book), r.status, r.message)
    if r.status == dc.OK:
        if "error" in state:
            res.status, res.message = dc.ERROR, state["error"]
        else:
            res.resaved = str(state["saved"])
            res.report = compare(book, state["saved"])
    if sheets and r.status == dc.OK:
        for name, path in sheet_copies(book, out_dir):
            res.sheets.append((name, dc.check(path, exe=exe, timeout=timeout, logs=logs)))
    res.seconds = round(time.time() - t0, 1)
    return res


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="check-desktop --resave", description="Re-save each .twbx in Tableau Desktop "
                                 "(File > Save As through UI Automation) and diff it with the original, then open a "
                                 "copy per sheet with that sheet shown; exit 1 unless nothing was dropped or changed "
                                 "by meaning and every sheet opens (decisions/054).")
    ap.add_argument("twbx", nargs="+", type=Path)
    ap.add_argument("-d", "--out-dir", type=Path, default=Path("out") / "resave")
    ap.add_argument("--no-sheets", action="store_true", help="do not open a copy per sheet")
    ap.add_argument("--timeout", type=float, default=dc.TIMEOUT_S)
    a = ap.parse_args(argv)
    if dc.no_file(a.twbx):
        return 2
    if dc.find_tableau() is None:
        print(f"ERROR: tableau.exe not found ({dc.TABLEAU_EXE}; set TABLEAU_EXE)", file=sys.stderr)
        return 2
    results = []
    for p in a.twbx:
        r = resave(p, a.out_dir, sheets=not a.no_sheets, timeout=a.timeout)
        results.append(r)
        text = r.text()
        print(text, flush=True)
        (a.out_dir / f"{Path(p).stem}.resave.txt").write_text(text + "\n", encoding="utf-8")
    bad = [r for r in results if not r.clean]
    print(f"{len(results) - len(bad)}/{len(results)} clean")
    return 1 if bad else 0
