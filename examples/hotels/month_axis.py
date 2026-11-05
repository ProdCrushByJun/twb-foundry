"""Months as a continuous axis on the two month sheets: 26 discrete headers get cut to 'Au..'.
Writes the mark sizing Desktop adds to such a sheet on save. Edits the book in place."""
import os, re, sys, zipfile
book = sys.argv[1]
SIZE = '<mark-sizing custom-mark-size-in-axis-units="1.0" mark-alignment="mark-alignment-left" mark-sizing-setting="marks-scaling-on" use-custom-mark-size="false" />'
zi = zipfile.ZipFile(book); tmp = book + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for it in zi.infolist():
        b = zi.read(it.filename)
        if it.filename.endswith(".twb"):
            t = b.decode("utf8")
            t = t.replace('name="[tmn:Arrival Date:ok]" pivot="key" type="ordinal"', 'name="[tmn:Arrival Date:qk]" pivot="key" type="quantitative"')
            t = t.replace("tmn:Arrival Date:ok", "tmn:Arrival Date:qk")
            for sheet in ("City Months", "Resort Months"):
                i = t.index(f'<worksheet name="{sheet}"'); j = t.index("</worksheet>", i)
                t = t[:i] + re.sub(r'(<mark class="Bar" />)', r"\1" + SIZE, t[i:j], count=1) + t[j:]
            b = t.encode("utf8")
        zo.writestr(it.filename, b)
zi.close(); os.replace(tmp, book)
