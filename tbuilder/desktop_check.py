"""Does a .twbx open cleanly in Tableau Desktop? (decisions/022)

Starts tableau.exe with the file as a separate, minimized, non-activated process (through WMI, so that it may not
take the foreground, decisions/054) and watches only that PID:
- windows (EnumWindows): the main window turns 'Tableau - <book>'; a titled window owned by it is a dialog
  ('Opening workbook ...' is the progress dialog; an error is 'Unable to complete action',
  UI Automation class UnifiedDetailedErrorDialog);
- the process's own log (My Tableau Repository/Logs/log*.txt, the one whose first line carries the PID):
  'end-workspace.open-workbook' = the workbook and its first view are loaded; 'detailed-error-msg' = the text
  of the error dialog (written when the dialog is closed);
- a crash: the process exits, Tableau's crash dumper writes crashdumps/*.crash/tableau.exe.<pid>.manifest.

OK = main window titled with the book + workbook loaded + no dialog, held for `settle` seconds.
The dialog is read and closed through UI Automation (Windows PowerShell), then the process is closed with
WM_CLOSE; only if it does not exit, that one PID is killed. Other Tableau processes are never touched.
"""
import argparse
import base64
import ctypes
import glob
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

TABLEAU_EXE = Path(r"C:\Program Files\Tableau\Tableau 2025.1\bin\tableau.exe")
LOGS = Path.home() / "Documents" / "My Tableau Repository" / "Logs"
TIMEOUT_S = 120     # launch -> verdict; a cold start here takes ~8 s
SETTLE_S = 3        # a loaded workbook must stay clean this long (no late dialog or crash)
DIALOG_GRACE_S = 1  # a dialog is read after it has been up this long (its UI Automation tree is filled)
LOG_WAIT_S = 5      # after closing an error dialog, wait this long for its text in the log
CLOSE_WAIT_S = 30   # WM_CLOSE -> process exit, else kill
PROGRESS = ("Opening workbook",)  # transient progress dialogs, not errors

OK, ERROR, CRASH, TIMEOUT = "OK", "ERROR", "CRASH", "TIMEOUT"
DIALOG, LOADED, WAIT = "dialog", "loaded", "wait"
LOG_KEYS = ("detailed-error-msg", "end-workspace.open-workbook")
INVALID_FIELD = "InvalidField"  # k=msg warn: the sheet draws blank, a resave is CLEAN anyway (decisions/180)


@dataclass
class Window:
    hwnd: int
    title: str
    owner: int = 0  # hwnd of the owner; 0 = a top-level (main) window


@dataclass
class Snapshot:
    """One poll of the launched process."""
    t: float                                    # seconds since launch
    windows: list = field(default_factory=list)  # visible top-level windows of the process
    events: list = field(default_factory=list)   # its log events with a key from LOG_KEYS
    exit_code: object = None                    # None while running
    crash: str = ""                             # crash dump folder naming the PID


@dataclass
class Result:
    path: str
    status: str        # OK | ERROR | CRASH | TIMEOUT
    message: str = ""
    seconds: float = 0.0
    pid: int = 0
    closed: str = ""   # how our process ended: closed | exited | killed

    def __str__(self):
        return f"{self.status:<7} {self.seconds:5.1f}s  {Path(self.path).name}" + (
            f"\n        {self.message}" if self.message else "")


# ---- verdict (pure: unit-tested on fake snapshots) -------------------------------------------------
def error_text(event):
    """'D2E8DA72: Error(203,247): attribute ... ' from a detailed-error-msg log event."""
    v = event.get("v") or {}
    if not isinstance(v, dict):
        return str(v)
    code = re.search(r"errorcode=([0-9a-fA-F]+)", v.get("support-help-link", ""))
    details = " | ".join(re.sub(r" \(id: [^)]*\)", "", d).replace("\n", " | ") for d in v.get("details", []))
    text = details or v.get("shortMessage", "")
    return f"{code.group(1).upper()}: {text}" if code else text


def invalid_fields(events):
    """One 'InvalidField [none:wave:nk]: The field ... can't be displayed ...' per such log message."""
    out = []
    for e in events:
        v = e.get("v")
        if e.get("k") != "msg" or not isinstance(v, str) or not v.startswith(INVALID_FIELD):
            continue
        m = re.match(r"InvalidField:\s*(?:\[[^\]]*\]\.)?(\[[^\]]+\]):\s*(.*)", v, re.S)
        out.append(f"{INVALID_FIELD} {m.group(1)}: {m.group(2)}" if m else v)
    return out


def sheets_with_fields(path, messages):
    """Worksheets of the .twbx that use the field instances named in `messages` -> 'sheet A, sheet B' (the log
    line has the field but not the sheet). '' if the book cannot be read."""
    import zipfile
    inst = set(re.findall(r"InvalidField (\[[^\]]+\])", messages))
    try:
        with zipfile.ZipFile(path) as z:
            twb = next(n for n in z.namelist() if n.endswith(".twb"))
            xml = z.read(twb).decode("utf-8", "replace")
    except (OSError, StopIteration, zipfile.BadZipFile):
        return ""
    names = []
    for m in re.finditer(r"<worksheet name=(?:'([^']*)'|\"([^\"]*)\").*?</worksheet>", xml, re.S):
        if any(re.search(r"<tooltip column=[\"'][^\"']*" + re.escape(i), m.group(0)) for i in inst):
            n = m.group(1) if m.group(1) is not None else m.group(2)
            names.append(n.replace("&apos;", "'").replace("&quot;", '"').replace("&amp;", "&"))
    return ", ".join(names)


def main_title(book):
    return f"Tableau - {book}"


def dialogs(windows):
    return [w for w in windows if w.owner and w.title and not w.title.startswith(PROGRESS)]


def assess(book, s):
    """One snapshot -> (state, detail): CRASH / ERROR (message), DIALOG (Window), LOADED, WAIT."""
    if s.crash or s.exit_code is not None:
        code = "" if s.exit_code is None else f"process exited with code 0x{s.exit_code & 0xFFFFFFFF:08X}"
        return CRASH, "; ".join(x for x in (code, f"crash dump {s.crash}" if s.crash else "") if x)
    errors = [e for e in s.events if e.get("k") == "detailed-error-msg"]
    if errors:
        return ERROR, error_text(errors[0])
    bad = invalid_fields(s.events)
    if bad:
        return ERROR, "; ".join(bad)
    d = dialogs(s.windows)
    if d:
        return DIALOG, d[0]
    loaded = any(e.get("k") == "end-workspace.open-workbook" for e in s.events)
    if loaded and any(not w.owner and w.title == main_title(book) for w in s.windows):
        return LOADED, ""
    return WAIT, ""


def watch(book, poll, dismiss, timeout=TIMEOUT_S, settle=SETTLE_S, sleep=time.sleep, step=0.25):
    """Poll the process until a verdict -> (status, message, seconds).
    poll() -> Snapshot; dismiss(hwnd) -> the dialog's text, after pressing its button."""
    loaded_at, seen = None, {}
    while True:
        s = poll()
        state, detail = assess(book, s)
        if state in (CRASH, ERROR):
            return state, detail, s.t
        if state == DIALOG:
            first = seen.setdefault(detail.hwnd, s.t)
            if s.t - first >= DIALOG_GRACE_S:
                text = dismiss(detail.hwnd)
                return ERROR, _logged_error(poll, sleep, step) or text, s.t
        if state == LOADED:
            loaded_at = s.t if loaded_at is None else loaded_at
            if s.t - loaded_at >= settle:
                return OK, "", loaded_at
        else:
            loaded_at = None
        if s.t >= timeout:
            titles = ", ".join(repr(w.title) for w in s.windows) or "none"
            return TIMEOUT, (f"no '{main_title(book)}' with the workbook loaded after {timeout}s "
                             f"(windows: {titles})"), s.t
        sleep(step)


def _logged_error(poll, sleep, step):
    """The error text Desktop logs once its dialog is closed ('' if it does not come in LOG_WAIT_S)."""
    start = None
    while True:
        s = poll()
        start = s.t if start is None else start
        errors = [e for e in s.events if e.get("k") == "detailed-error-msg"]
        if errors:
            return error_text(errors[0])
        if s.t - start >= LOG_WAIT_S:
            return ""
        sleep(step)


# ---- Tableau's files ----------------------------------------------------------------------------------
class ProcessLog:
    """Events of one Tableau process from its log file. Desktop writes to a free slot log.txt / log_N.txt and
    appends to what earlier processes left there, rotating it to *_bk.txt only when it is large; so the slot
    is the file that gets a line with our PID after the launch. Create before the launch, set .pid after."""

    def __init__(self, logs=LOGS):
        self.logs, self.pid, self.path, self.pos, self.events = Path(logs), None, None, 0, []
        self.marks = {f: self._mark(f) for f in self._files()}  # what is there before the launch is not ours

    def _files(self):
        return [f for f in glob.glob(str(self.logs / "log*.txt")) if not f.endswith("_bk.txt")]

    @staticmethod
    def _mark(f):
        try:
            with open(f, "rb") as fh:
                return os.path.getsize(f), fh.readline()
        except OSError:  # rotated away meanwhile
            return 0, b""

    def _find(self):
        tag = f'"pid":{self.pid},'.encode()
        for f in self._files():
            size, first = self.marks.get(f, (0, b""))
            start = size if self._mark(f)[1] == first else 0  # another first line: rotated, a new file
            with open(f, "rb") as fh:
                fh.seek(start)
                if tag in fh.read():
                    self.path, self.pos = Path(f), start
                    return

    def read(self):
        if self.path is None:
            self._find()
        if self.path:
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                chunk = fh.read()
            end = chunk.rfind(b"\n") + 1  # complete lines only; the rest is still being written
            self.pos += end
            for line in chunk[:end].splitlines():
                if any(f'"k":"{k}"'.encode() in line for k in LOG_KEYS) or (
                        b'"k":"msg"' in line and INVALID_FIELD.encode() in line):
                    e = parse_line(line)
                    if e and e.get("pid") == self.pid:
                        self.events.append(e)
        return self.events


def parse_line(line):
    try:
        return json.loads(line.decode("utf-8", "replace") if isinstance(line, bytes) else line)
    except ValueError:
        return None


DUMP_SLACK_S = 2  # file-time granularity / clock skew between our time.time() and the dump's mtime


def crash_dump(pid, logs=LOGS, since=0.0):
    """Folder of the crash dump Tableau wrote for this PID after `since` (epoch seconds; the launch), or ''.
    Windows reuses PIDs and crashdumps/ keeps old dumps: a dump of an earlier process with the same PID is not
    ours (restyle-049, 2026-10-21: PID 18296 matched a dump of 20.10 -> a false CRASH in 0.0 s)."""
    for m in glob.glob(str(Path(logs) / "crashdumps" / "*.crash" / f"tableau.exe.{pid}.manifest")):
        try:
            if os.path.getmtime(m) >= since - DUMP_SLACK_S:
                return str(Path(m).parent)
        except OSError:  # removed meanwhile
            pass
    return ""


def find_tableau():
    exe = Path(os.environ.get("TABLEAU_EXE", TABLEAU_EXE))
    return exe if exe.is_file() else None


# ---- Win32 (ctypes) -----------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _user32():
    from ctypes import wintypes as wt
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u.GetWindowThreadProcessId.restype = wt.DWORD
    u.IsWindowVisible.argtypes = [wt.HWND]
    u.GetWindowTextLengthW.argtypes = [wt.HWND]
    u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.GetWindow.argtypes = [wt.HWND, wt.UINT]
    u.GetWindow.restype = wt.HWND
    u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return u


def process_windows(pid):
    """Visible top-level windows of a process."""
    from ctypes import wintypes as wt
    u, out = _user32(), []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(u.GetWindowTextLengthW(h) + 1)
            u.GetWindowTextW(h, buf, len(buf))
            out.append(Window(h, buf.value, u.GetWindow(h, 4) or 0))  # GW_OWNER
        return True

    u.EnumWindows(each, 0)
    return out


def post_close(hwnd):
    _user32().PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


# ---- dialogs through UI Automation (Qt widgets are not Win32 child windows) -------------------------------
PRESS = ("Don't Save", "No", "OK", "Close")  # buttons to press, in this order; else the title-bar close button
_UIA = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$e = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]%HWND%)
"ROOT`t$($e.Current.ClassName)`t$($e.Current.Name -replace '\s+', ' ')"
$press = @(%PRESS%)
$buttons = @()
foreach ($x in $e.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
  $c = $x.Current
  $t = $c.ControlType.ProgrammaticName -replace '^ControlType\.', ''
  "$t`t$($c.AutomationId)`t$($c.Name -replace '\s+', ' ')"
  if ($t -eq 'Button') { $buttons += $x }
}
$pick = $null
foreach ($p in $press) { if (-not $pick) { $pick = $buttons | Where-Object { $_.Current.Name -eq $p } | Select-Object -First 1 } }
if (-not $pick) { $pick = $buttons | Where-Object { $_.Current.AutomationId -like '*closeButton' } | Select-Object -First 1 }
if ($pick) {
  $pick.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
  "PRESSED`t$($pick.Current.AutomationId)`t$($pick.Current.Name)"
}
"""


def parse_dialog(out):
    """PowerShell UIA dump -> (class, title, texts, pressed)."""
    cls = title = pressed = ""
    texts = []
    for line in out.splitlines():
        kind, _, rest = line.partition("\t")
        first, _, name = rest.partition("\t")
        if kind == "ROOT":
            cls, title = first, name
        elif kind == "Text" and name and name != title:
            texts.append(name)
        elif kind == "PRESSED":
            pressed = name or first.rsplit(".", 1)[-1]
    return cls, title, texts, pressed


def dismiss(hwnd):
    """Read a dialog's text and press its button (WM_CLOSE if it has none) -> 'dialog <title> (<class>): text'."""
    press = ", ".join("'" + p.replace("'", "''") + "'" for p in PRESS)
    script = _UIA.replace("%HWND%", str(hwnd)).replace("%PRESS%", press)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                              base64.b64encode(script.encode("utf-16-le")).decode()],
                             capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW
                             ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    cls, title, texts, pressed = parse_dialog(out)
    if not pressed:
        post_close(hwnd)
    return f"dialog '{title}' ({cls or 'no UI Automation'}): " + " | ".join(texts)


# ---- one check ---------------------------------------------------------------------------------------------
class _Process:
    """The Popen interface (pid, poll, kill, wait) over a PID we did not create ourselves."""

    def __init__(self, pid):
        from ctypes import wintypes as wt
        self.pid, self._k = pid, ctypes.WinDLL("kernel32", use_last_error=True)
        self._k.OpenProcess.restype = wt.HANDLE
        self._k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        self._k.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        self._k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        self._k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
        # SYNCHRONIZE | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
        self._h = self._k.OpenProcess(0x00100000 | 0x0001 | 0x1000, False, pid)

    def poll(self):
        from ctypes import wintypes as wt
        if not self._h:
            return -1  # gone before we could open it
        code = wt.DWORD()
        self._k.GetExitCodeProcess(self._h, ctypes.byref(code))
        return None if code.value == 259 else code.value  # STILL_ACTIVE

    def kill(self):
        if self._h:
            self._k.TerminateProcess(self._h, 1)

    def wait(self, timeout=None):
        if self._h:
            self._k.WaitForSingleObject(self._h, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
        return self.poll()


_WMI_CREATE = ("$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]%SHOW%}; "
               "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
               "@{CommandLine='%CMD%'; ProcessStartupInformation=$si}; \"$($r.ReturnValue) $($r.ProcessId)\"")


def wmi_start(args, show=7):
    """Start a process through WMI -> _Process, or None if WMI fails. Its parent is then WmiPrvSE, not us: a process
    started by the foreground app (here: the shell of the session the user types in) may take the foreground and
    pass that right on (UI Automation calls hand it to the app they drive); one started by WMI may not. Measured
    2026-10-21 (decisions/054): a child Tableau took the foreground on 'Opening workbook' and kept it; started
    through WMI, it never got it. show: SW_* of the first window (7 = minimized, not activated; 0 = hidden)."""
    cmd = subprocess.list2cmdline([str(a) for a in args]).replace("'", "''")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                              _WMI_CREATE.replace("%CMD%", cmd).replace("%SHOW%", str(int(show)))],
                             capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW
                             ).stdout.decode("utf-8", "replace").split()
        if len(out) == 2 and out[0] == "0":
            return _Process(int(out[1]))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _launch(exe, path):
    """Tableau with the workbook, minimized and not activated, without the right to take the foreground (wmi_start);
    a plain child process if WMI fails."""
    return wmi_start([exe, path]) or _popen(exe, path)


def _popen(exe, path):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7  # SW_SHOWMINNOACTIVE: Tableau honours it, its windows do not take the focus
    return subprocess.Popen([str(exe), str(path)], startupinfo=si)


def _close(proc):
    """WM_CLOSE to our main window, press through any prompt, kill our PID only as the last resort."""
    if proc.poll() is not None:
        return "exited"
    deadline, next_close, seen, done = time.time() + CLOSE_WAIT_S, 0, {}, set()
    while time.time() < deadline:
        if proc.poll() is not None:
            return "closed"
        windows = process_windows(proc.pid)
        up = dialogs(windows)
        for d in up:  # an error left open, a save prompt (Don't Save)
            if d.hwnd not in done and time.time() - seen.setdefault(d.hwnd, time.time()) >= DIALOG_GRACE_S:
                dismiss(d.hwnd)
                done.add(d.hwnd)
        if not up and time.time() >= next_close:  # a modal dialog swallows WM_CLOSE: repeat once it is gone
            for w in windows:
                if not w.owner:
                    post_close(w.hwnd)
            next_close = time.time() + 5
        time.sleep(0.25)
    proc.kill()
    proc.wait(10)
    return "killed"


def check(path, exe=None, timeout=TIMEOUT_S, settle=SETTLE_S, logs=LOGS, on_loaded=None):
    """Open one workbook in its own Tableau process -> Result.
    on_loaded(pid): called on OK before the process is closed (screenshot.capture_tableau, decisions/048)."""
    exe = exe or find_tableau()
    if exe is None:
        raise RuntimeError(f"tableau.exe not found ({TABLEAU_EXE}; set TABLEAU_EXE)")
    path = Path(path).resolve()
    log = ProcessLog(logs)
    start = time.time()
    proc = _launch(exe, path)
    log.pid = proc.pid

    def poll():
        return Snapshot(time.time() - start, process_windows(proc.pid), log.read(), proc.poll(),
                        crash_dump(proc.pid, logs, since=start))

    try:
        status, message, t = watch(path.stem, poll, dismiss, timeout, settle)
        if status == OK and on_loaded:
            on_loaded(proc.pid)
    finally:
        closed = _close(proc)
    if status == ERROR and INVALID_FIELD in message:
        message = f"sheet(s) drawn blank: {sheets_with_fields(path, message) or '?'}; {message}"
    if status == TIMEOUT and log.path is None:
        message += f"; no log of PID {proc.pid} in {logs}"
    return Result(str(path), status, message, round(t, 1), proc.pid, closed)


def no_file(paths):
    """Print the books that are not there -> True if any: Desktop given a missing path opens an empty Book1 and waits
    out its timeout, no verdict about any book (decisions/194)."""
    missing = [p for p in paths if not Path(p).is_file()]
    for p in missing:
        print(f"ERROR: no such file: {p}", file=sys.stderr)
    return bool(missing)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="desktop_check", description="Open .twbx files in Tableau Desktop, one "
                                 "process each; exit 1 unless all are OK (decisions/022).")
    ap.add_argument("twbx", nargs="+", type=Path)
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S)
    a = ap.parse_args(argv)
    if no_file(a.twbx):
        return 2
    if find_tableau() is None:
        print(f"ERROR: tableau.exe not found ({TABLEAU_EXE}; set TABLEAU_EXE)", file=sys.stderr)
        return 2
    results = []
    for p in a.twbx:
        results.append(check(p, timeout=a.timeout))
        print(results[-1], flush=True)
    bad = [r for r in results if r.status != OK]
    print(f"{len(results) - len(bad)}/{len(results)} OK")
    return 1 if bad else 0
