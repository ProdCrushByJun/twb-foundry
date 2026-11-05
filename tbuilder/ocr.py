"""Text on a picture by Windows' own OCR (decisions/076): Windows.Media.Ocr through PowerShell 5.1, no install.

words(paths) -> {path: [Word]}: every word the engine reads, with its box in the picture's pixels, in reading order
(line by line). One PowerShell process reads every picture. The engine is en-US (digits and the separators of any
locale read alike) unless lang says otherwise; RuntimeError when Windows has no OCR engine for it.
"""
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT = r"""
param([string]$List, [string]$Lang = 'en-US')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Lang))
if ($null -eq $engine) { throw "no Windows OCR engine for $Lang" }
$out = @{}
foreach ($path in (Get-Content -LiteralPath $List -Encoding UTF8)) {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $words = @()
    $i = 0
    foreach ($line in $res.Lines) {
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            $words += ,@($w.Text, [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height, $i)
        }
        $i += 1
    }
    $stream.Dispose()
    $out[$path] = $words
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$out | ConvertTo-Json -Depth 5 -Compress
"""


@dataclass
class Word:
    text: str
    x: int
    y: int
    w: int
    h: int
    line: int  # the engine's line number in its picture


def words(paths, lang="en-US"):
    """{path: [Word]} for PNG pictures; one PowerShell run for all of them. lang: the engine's language ('ru' reads
    the '1' of a '10%' the en-US one drops, decisions/098); RuntimeError when Windows has none for it."""
    paths = [str(Path(p).resolve()) for p in paths]
    if not paths:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        script, listing = Path(tmp) / "ocr.ps1", Path(tmp) / "pictures.txt"
        script.write_text(SCRIPT, encoding="utf-8-sig")  # a BOM: PowerShell 5.1 reads the script as UTF-8
        listing.write_text("\n".join(paths), encoding="utf-8")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                            "-List", str(listing), "-Lang", lang], capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"Windows OCR failed: {r.stderr.decode('utf-8', 'replace').strip()[:500]}")
    raw = json.loads(r.stdout.decode("utf-8-sig") or "{}")
    out = {}
    for p in paths:
        items = raw.get(p) or []
        if items and not isinstance(items[0], list):  # ConvertTo-Json unwraps a single word
            items = [items]
        out[p] = [Word(str(t), x, y, w, h, line) for t, x, y, w, h, line in items]
    return out
