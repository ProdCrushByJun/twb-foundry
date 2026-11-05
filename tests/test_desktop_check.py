"""Desktop open check (decisions/022): the verdict from fake windows / log events; one real run in Desktop.

The real run is opt-in: TBUILDER_DESKTOP=1 and tableau.exe (it starts 3 Tableau processes, ~40 s, and must not
run while someone works in Desktop; take the Desktop queue out/desktop-queue.md first).
"""
import json
import os
import tempfile
import time
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path
from unittest import mock

from lxml import etree

from tbuilder import __main__ as cli
from tbuilder import desktop_check as dc
from tbuilder.desktop_check import CRASH, DIALOG, ERROR, LOADED, OK, TIMEOUT, WAIT, Snapshot, Window
from test_roundtrip import ROOT

GOLDEN = ROOT / "golden"
MAIN = 100


# ---- broken copies of golden workbooks (decisions/022 table): the gate passes (b) and (d), Desktop does not ----
def _repack(src, dst, mutate):
    with zipfile.ZipFile(src) as z:
        members = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in members if n.endswith(".twb"))
    root = etree.fromstring(members[twb])
    mutate(root)
    members[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)


def _drop_flag(name):
    def mutate(root):
        el = root.find(f"document-format-change-manifest/{name}")
        el.getparent().remove(el)
    return mutate


def _drop_addresses(root):
    """decisions/011: Difference without <address> crashes Desktop once the sheet is drawn."""
    for a in list(root.iter("address")):
        a.getparent().remove(a)


def _difference_without_address_shown_first(root):
    _drop_addresses(root)  # and show that sheet at open
    windows = root.find("windows")
    for w in windows:
        w.attrib.pop("maximized", None)
    target = next(w for w in windows if w.get("name") == "Region Difference")
    target.set("maximized", "true")
    windows.remove(target)
    windows.append(target)


def make_broken(out_dir):
    """Write the broken workbooks into out_dir -> {name: path}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "dates_no_iso8601": (GOLDEN / "golden_dates_us_2025_1.twbx", _drop_flag("ISO8601PeriodTypes")),
        "format_no_sorttagcleanup": (GOLDEN / "golden_format_2025_1.twbx", _drop_flag("SortTagCleanup")),
        "tablecalcs_no_address": (GOLDEN / "golden_tablecalcs_2025_1.twbx", _difference_without_address_shown_first),
        # the limit: the dashboard is shown, the broken sheets on it stay empty, Desktop opens it (OK)
        "tablecalcs_no_address_dashboard": (GOLDEN / "golden_tablecalcs_2025_1.twbx", _drop_addresses),
    }
    paths = {}
    for name, (src, mutate) in files.items():
        paths[name] = out / f"{name}.twbx"
        _repack(src, paths[name], mutate)
    data = (GOLDEN / "golden_2025_1.twbx").read_bytes()
    paths["corrupt_zip"] = out / "corrupt_zip.twbx"
    paths["corrupt_zip"].write_bytes(data[: len(data) // 2])
    return paths


# ---- fake data, shaped as Desktop 2025.1 produced it (2026-10-20) ------------------------------------------
def log_error(details="Error(203,247): attribute 'period-type-v2' is not declared for element 'filter' "
                      "(id: C:\\Users\\V\\AppData\\Local\\Temp\\TableauTemp\\3427172200\\dates_no_iso8601.twb)",
              pid=44892):
    return {"ts": "2026-10-20T21:42:33.238", "pid": pid, "sev": "error", "k": "detailed-error-msg",
            "v": {"details": [details],
                  "shortMessage": "Errors occurred while trying to load the workbook \"C:/x/dates_no_iso8601.twbx\". "
                                  "The load was not able to complete successfully.",
                  "support-help-link": "https://help.tableau.com/forward/producthelp?build=20251.25.0313.2002"
                                       "&edition=pro&errorcode=d2e8da72&lang=en-us&platform=windows"}}


OPENED = {"k": "end-workspace.open-workbook", "pid": 44892, "ctx": {"wb": "book"}}
LOADING = [Window(MAIN, "Tableau")]
PROGRESS = [Window(MAIN, "Tableau"), Window(7, "Opening workbook 'book.twbx'...", owner=MAIN)]
ERROR_DIALOG = [Window(MAIN, "Tableau"), Window(8, "Unable to complete action", owner=MAIN)]
TITLED = [Window(MAIN, "Tableau - book")]
UIA_DUMP = "\n".join([
    "ROOT\tUnifiedDetailedErrorDialog\tUnable to complete action",
    "Custom\tUnifiedDetailedErrorDialog.mainFrame\t",
    "Text\tUnifiedDetailedErrorDialog.mainFrame.titleBar.titleContainer.defaultTitle\tUnable to complete action",
    "Button\tUnifiedDetailedErrorDialog.mainFrame.titleBar.closeButton\t",
    "Text\tUnifiedDetailedErrorDialog.mainFrame.contentContainer.DetailedErrorContents.shortErrorMessage\t"
    "Errors occurred while trying to load the workbook \"C:/x/book.twbx\". The load was not able to complete "
    "successfully.",
    "Text\tUnifiedDetailedErrorDialog.mainFrame.contentContainer.DetailedErrorContents.errorCode\tError Code: D2E8DA72",
    "Text\tUnifiedDetailedErrorDialog.mainFrame.contentContainer.DetailedErrorContents.detailsContainer.errorDetails\t",
    "Button\tUnifiedDetailedErrorDialog.mainFrame.contentContainer.DetailedErrorContents.copyButton\tCopy Error Message",
    "PRESSED\tUnifiedDetailedErrorDialog.mainFrame.titleBar.closeButton\t",
])


class Script:
    """poll() for watch(): the given snapshots at 0.5 s steps, then the last one again."""

    def __init__(self, *frames):
        self.frames, self.i, self.dismissed = list(frames), 0, []

    def poll(self):
        windows, events, exit_code, crash = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return Snapshot(self.i * 0.5, windows, events, exit_code, crash)

    def dismiss(self, hwnd):
        self.dismissed.append(hwnd)
        self.frames = [(f[0][:1], f[1] + [log_error()], f[2], f[3]) for f in self.frames]  # logged once closed
        return "dialog 'Unable to complete action' (UnifiedDetailedErrorDialog): text from the dialog"

    def run(self, timeout=30, settle=3):
        return dc.watch("book", self.poll, self.dismiss, timeout=timeout, settle=settle, sleep=lambda s: None)


def frame(windows, events=(), exit_code=None, crash=""):
    return (list(windows), list(events), exit_code, crash)


class AssessTest(unittest.TestCase):
    def state(self, windows, events=(), exit_code=None, crash=""):
        return dc.assess("book", Snapshot(1.0, list(windows), list(events), exit_code, crash))

    def test_loaded_needs_the_title_and_the_log(self):
        self.assertEqual(self.state(TITLED, [OPENED]), (LOADED, ""))
        self.assertEqual(self.state(TITLED)[0], WAIT)            # title set, first view not drawn yet
        self.assertEqual(self.state(LOADING, [OPENED])[0], WAIT)  # failed load ends in a blank book
        self.assertEqual(self.state([Window(MAIN, "Tableau - Book2")], [OPENED])[0], WAIT)
        self.assertEqual(self.state([Window(MAIN, "Tableau - book_v2")], [OPENED])[0], WAIT)

    def test_progress_dialog_is_not_an_error(self):
        self.assertEqual(self.state(PROGRESS)[0], WAIT)
        self.assertEqual(self.state(PROGRESS[1:] + TITLED, [OPENED])[0], LOADED)

    def test_untitled_owned_window_is_not_a_dialog(self):  # tooltips, popups
        self.assertEqual(self.state(TITLED + [Window(9, "", owner=MAIN)], [OPENED])[0], LOADED)

    def test_dialog(self):
        state, w = self.state(ERROR_DIALOG)
        self.assertEqual((state, w.hwnd), (DIALOG, 8))
        self.assertEqual(self.state(TITLED + ERROR_DIALOG[1:], [OPENED])[0], DIALOG)  # opened with an error

    def test_logged_error_wins(self):
        state, msg = self.state(TITLED, [OPENED, log_error()])
        self.assertEqual(state, ERROR)
        self.assertEqual(msg, "D2E8DA72: Error(203,247): attribute 'period-type-v2' is not declared for element "
                              "'filter'")

    def test_crash(self):
        self.assertEqual(self.state(TITLED, [OPENED], exit_code=3221225477),
                         (CRASH, "process exited with code 0xC0000005"))
        state, msg = self.state(TITLED, crash=r"C:\Logs\crashdumps\02F5.crash")
        self.assertEqual(state, CRASH)
        self.assertIn("02F5.crash", msg)


class WatchTest(unittest.TestCase):
    def test_ok_after_settle(self):
        s = Script(frame(LOADING), frame(PROGRESS), frame(TITLED, [OPENED]))
        status, msg, t = s.run(settle=3)
        self.assertEqual((status, msg, t), (OK, "", 1.5))
        self.assertEqual(s.i, 9)  # loaded at 1.5 s, held to 4.5 s

    def test_error_dialog_is_dismissed_and_the_log_text_used(self):
        s = Script(frame(LOADING), frame(ERROR_DIALOG))
        status, msg, _ = s.run()
        self.assertEqual(status, ERROR)
        self.assertEqual(s.dismissed, [8])
        self.assertTrue(msg.startswith("D2E8DA72: Error(203,247)"), msg)

    def test_dialog_text_when_nothing_is_logged(self):
        s = Script(frame(LOADING), frame(ERROR_DIALOG))
        s.dismiss = lambda hwnd: "dialog 'X' (Y): from the dialog"
        status, msg, _ = s.run()
        self.assertEqual((status, msg), (ERROR, "dialog 'X' (Y): from the dialog"))

    def test_short_dialog_is_not_read(self):  # gone before DIALOG_GRACE_S
        s = Script(frame(LOADING), frame(ERROR_DIALOG), frame(TITLED, [OPENED]))
        self.assertEqual(s.run()[0], OK)
        self.assertEqual(s.dismissed, [])

    def test_crash_while_settling(self):
        s = Script(frame(PROGRESS), frame(TITLED, [OPENED]), frame(TITLED, [OPENED]), frame([], [OPENED], 3221225477))
        status, msg, _ = s.run()
        self.assertEqual((status, msg), (CRASH, "process exited with code 0xC0000005"))

    def test_timeout(self):
        status, msg, t = Script(frame(PROGRESS)).run(timeout=10)
        self.assertEqual(status, TIMEOUT)
        self.assertGreaterEqual(t, 10)
        self.assertIn("Opening workbook 'book.twbx'...", msg)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, events):
        (self.dir / name).write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events),
                                     encoding="utf-8")

    def append(self, name, data):
        with open(self.dir / name, "ab") as f:
            f.write(data)

    def test_process_log_slot_appended_to(self):
        """log.txt keeps an earlier run with the same PID; ours is appended after the launch."""
        self.write("log.txt", [{"pid": 1, "k": "open-log"}, dict(OPENED, pid=44892)])
        self.write("log_2.txt", [{"pid": 7, "k": "open-log"}])  # another live process
        log = dc.ProcessLog(self.dir)
        log.pid = 44892
        self.assertEqual(log.read(), [])  # nothing of ours after the launch yet
        self.assertIsNone(log.path)
        self.append("log.txt", b'{"pid":44892,"k":"open-log"}\n{"pid":44892,"k":"msg"}\n')
        self.assertEqual(log.read(), [])
        self.assertEqual(log.path.name, "log.txt")
        line = json.dumps(log_error(), separators=(",", ":")).encode()
        self.append("log.txt", json.dumps(OPENED, separators=(",", ":")).encode() + b"\n" + line[:40])  # half-written
        self.assertEqual([e["k"] for e in log.read()], ["end-workspace.open-workbook"])
        self.append("log.txt", line[40:] + b"\n")
        self.assertEqual([e["k"] for e in log.read()], ["end-workspace.open-workbook", "detailed-error-msg"])

    def test_process_log_slot_rotated(self):
        """A large slot goes to *_bk.txt and a new file starts: read it from the start."""
        self.write("log_2.txt", [{"pid": 1, "k": "open-log", "v": "x" * 500}])
        log = dc.ProcessLog(self.dir)
        log.pid = 44892
        (self.dir / "log_2.txt").rename(self.dir / "log_2_bk.txt")
        self.write("log_2.txt", [{"pid": 44892, "k": "open-log", "v": "y" * 600}, OPENED])
        self.assertEqual([e["k"] for e in log.read()], ["end-workspace.open-workbook"])
        self.assertEqual(log.path.name, "log_2.txt")

    INVALID = {"k": "msg", "sev": "warn", "v": "InvalidField: [federated.abc].[none:wave:nk]: The field Wave can't be "
               "displayed in Tooltips because it can't be converted to a measure using ATTR()."}

    def test_invalid_field_of_this_open_is_an_error(self):
        """Desktop draws such a sheet blank and a resave is CLEAN (decisions/176, 180): the log line is the signal."""
        self.write("log.txt", [{"pid": 1, "k": "open-log"}])
        log = dc.ProcessLog(self.dir)
        log.pid = 44892
        self.append("log.txt", b"".join(json.dumps(e, separators=(",", ":")).encode() + b"\n" for e in (
            {"pid": 44892, "k": "open-log"}, dict(self.INVALID, pid=44892), {"pid": 44892, "k": "msg", "v": "other"},
            dict(OPENED))))
        events = log.read()
        state, text = dc.assess("book", Snapshot(1, [Window(1, "Tableau - book")], events))
        self.assertEqual(state, ERROR)
        self.assertIn("InvalidField [none:wave:nk]", text)
        self.assertIn("can't be displayed in Tooltips", text)

    def test_invalid_field_of_an_earlier_run_is_not_ours(self):
        self.write("log.txt", [dict(self.INVALID, pid=44892)])  # an earlier process with the same PID, same file
        log = dc.ProcessLog(self.dir)
        log.pid = 44892
        self.append("log.txt", json.dumps(dict(OPENED), separators=(",", ":")).encode() + b"\n")
        self.assertEqual([e["k"] for e in log.read()], ["end-workspace.open-workbook"])
        self.assertEqual(dc.invalid_fields(log.events), [])
        other = dict(self.INVALID, pid=99)  # a concurrent process writes to the same file
        self.append("log.txt", json.dumps(other, separators=(",", ":")).encode() + b"\n")
        self.assertEqual(dc.invalid_fields(log.read()), [])

    def test_no_invalid_field_is_ok(self):
        state, _ = dc.assess("book", Snapshot(1, [Window(1, "Tableau - book")], [dict(OPENED), {"k": "msg", "v": "x"}]))
        self.assertEqual(state, LOADED)

    def test_invalid_field_names_the_sheet(self):
        path = self.dir / "b.twbx"
        twb = ("<workbook><worksheets><worksheet name='Calm'><tooltip column='[d].[none:zone:nk]'/></worksheet>"
               "<worksheet name='Strip &amp; Co'><tooltip column='[d].[none:wave:nk]'/></worksheet></worksheets></workbook>")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("b.twb", twb)
        msgs = "; ".join(dc.invalid_fields([self.INVALID]))
        self.assertEqual(dc.sheets_with_fields(path, msgs), "Strip & Co")

    def test_crash_dump_by_pid(self):
        crash = self.dir / "crashdumps" / "02F5951AA9504EB9A3C1A0AB0F929DA6.crash"
        crash.mkdir(parents=True)
        (crash / "tableau.exe.19424.manifest").write_text("{}")
        self.assertEqual(dc.crash_dump(19424, self.dir), str(crash))
        self.assertEqual(dc.crash_dump(1942, self.dir), "")

    def old_dump(self, pid, age_s=86400):
        """A dump an earlier process with this PID left in crashdumps/ (Windows reuses PIDs)."""
        crash = self.dir / "crashdumps" / "B357DD4B0000000000000000000000AA.crash"
        crash.mkdir(parents=True)
        manifest = crash / f"tableau.exe.{pid}.manifest"
        manifest.write_text("{}")
        old = time.time() - age_s
        os.utime(manifest, (old, old))
        return crash

    def test_crash_dump_of_an_earlier_process_is_not_ours(self):
        crash = self.old_dump(18296)
        self.assertEqual(dc.crash_dump(18296, self.dir, since=time.time()), "")
        self.assertEqual(dc.crash_dump(18296, self.dir, since=time.time() - 2 * 86400), str(crash))
        os.utime(crash / "tableau.exe.18296.manifest")  # written now, after the launch: ours
        self.assertEqual(dc.crash_dump(18296, self.dir, since=time.time() - 5), str(crash))

    def test_check_ignores_an_old_dump_with_our_pid(self):
        """restyle-049, 2026-10-21: the new process got the PID of a dump from 20.10 -> CRASH in 0.0 s, and the check
        closed the window while it was loading. Reproduced with a fake process; the book loads -> OK."""
        self.old_dump(18296)
        self.write("log.txt", [{"pid": 1, "k": "open-log"}])

        class Proc:
            pid = 18296

            def poll(self):
                return None

        def launch(exe, path):
            self.append("log.txt", b'{"pid":18296,"k":"open-log"}\n'
                        + json.dumps(dict(OPENED, pid=18296), separators=(",", ":")).encode() + b"\n")
            return Proc()

        with mock.patch.object(dc, "_launch", launch), mock.patch.object(dc, "_close", return_value="closed"), \
                mock.patch.object(dc, "process_windows", return_value=[Window(MAIN, "Tableau - book")]):
            r = dc.check(self.dir / "book.twbx", exe=Path("tableau.exe"), settle=0.3, logs=self.dir)
        self.assertEqual((r.status, r.message), (OK, ""))

    def test_error_text(self):
        details = "Error(203,175): no declaration found for element 'computed-sort' (id: C:\\T\\x.twb)\n" \
                  "Error(203,175): attribute 'column' is not declared for element 'computed-sort' (id: C:\\T\\x.twb)"
        self.assertEqual(dc.error_text(log_error(details)),
                         "D2E8DA72: Error(203,175): no declaration found for element 'computed-sort' | "
                         "Error(203,175): attribute 'column' is not declared for element 'computed-sort'")
        self.assertEqual(dc.error_text({"v": {"shortMessage": "Bad"}}), "Bad")

    def test_parse_dialog(self):
        cls, title, texts, pressed = dc.parse_dialog(UIA_DUMP)
        self.assertEqual((cls, title, pressed), ("UnifiedDetailedErrorDialog", "Unable to complete action",
                                                 "closeButton"))
        self.assertEqual(texts[1], "Error Code: D2E8DA72")
        self.assertTrue(texts[0].startswith("Errors occurred while trying to load the workbook"))
        self.assertEqual(dc.parse_dialog(""), ("", "", [], ""))


class BuildFlagTest(unittest.TestCase):
    """build --desktop-check: a file Desktop does not open is not handed out (Desktop stubbed)."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "golden.twbx"

    def build(self, result):
        args = Namespace(spec=ROOT / "specs" / "golden.json", out=self.out, desktop_check=True, hyper_mb=None)
        with mock.patch.object(dc, "find_tableau", return_value=Path("tableau.exe")),                 mock.patch.object(dc, "check", return_value=result) as check, mock.patch("builtins.print"):
            try:
                cli._build(args)
            finally:
                self.assertEqual(check.call_args.args, (self.out,))

    def test_ok_keeps_the_file(self):
        self.build(dc.Result("x", OK))
        self.assertTrue(self.out.exists())

    def test_error_removes_the_file(self):
        with self.assertRaisesRegex(RuntimeError, "Desktop check ERROR: D2E8DA72"):
            self.build(dc.Result("x", ERROR, "D2E8DA72: no declaration found"))
        self.assertFalse(self.out.exists())

    def test_no_tableau_fails_before_building(self):
        with mock.patch.object(dc, "find_tableau", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "tableau.exe not found"):
                cli._build(Namespace(spec=ROOT / "specs" / "golden.json", out=self.out, desktop_check=True, hyper_mb=None))
        self.assertFalse(self.out.exists())


@unittest.skipUnless(dc.find_tableau() and os.environ.get("TBUILDER_DESKTOP") == "1",
                     "real Desktop run is opt-in: TBUILDER_DESKTOP=1 (needs tableau.exe)")
class DesktopOpenTest(unittest.TestCase):
    """Real Desktop 2025.1: a golden opens, a file the gate passes but Desktop refuses and a broken zip do not."""

    @classmethod
    def setUpClass(cls):
        cls.broken = make_broken(tempfile.mkdtemp())

    def test_golden_opens(self):
        r = dc.check(GOLDEN / "golden_2025_1.twbx")
        self.assertEqual(r.status, OK, r.message)
        self.assertEqual(r.closed, "closed")

    def test_refused_by_desktop(self):
        r = dc.check(self.broken["format_no_sorttagcleanup"])
        self.assertEqual(r.status, ERROR)
        self.assertIn("no declaration found for element 'computed-sort'", r.message)
        self.assertEqual(r.closed, "closed")

    def test_corrupt_zip(self):
        r = dc.check(self.broken["corrupt_zip"])
        self.assertEqual(r.status, ERROR)
        self.assertIn("Invalid twb or twbx file", r.message)


if __name__ == "__main__":
    unittest.main()
