"""No 'N nulls' badge on the lower bars: a click on the heatmap leaves months without bookings. Edits the book in place."""
import os, re, sys, zipfile
book = sys.argv[1]
FORMAT = '<format attr="show-null-value-warning" value="false" />'


def hide(m):
    w, n = re.subn(r"""<style-rule element=['"]table['"]>""", lambda r: r[0] + FORMAT, m[0], count=1)
    assert n == 1, m[0][:60]
    return w


zi = zipfile.ZipFile(book); tmp = book + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for it in zi.infolist():
        b = zi.read(it.filename)
        if it.filename.endswith(".twb"):
            t = b.decode("utf8")
            for sheet in ("Cancelled 2017 Bars", "Change Bars"):
                t, n = re.subn(rf'<worksheet name="{sheet}">.*?</worksheet>', hide, t, flags=re.S)
                assert n == 1, sheet
            b = t.encode("utf8")
        zo.writestr(it.filename, b)
zi.close(); os.replace(tmp, book)
