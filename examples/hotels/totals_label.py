"""'All' over the heatmap's row total bars: the bottom of the empty zone above them becomes a text zone, level with the
band labels. Edits the book in place."""
import os, re, sys, zipfile
book = sys.argv[1]
TEXT_H = 2700  # of the dashboard's 100000: one line of 8pt with the text zone's own padding, 24 px of 900
ZONE = '<zone forceUpdate="true" h="{h}" id="{id}" type-v2="text" w="{w}" x="{x}" y="{y}"><formatted-text><run fontcolor="#868686" fontsize="8">All</run></formatted-text><zone-style><format attr="border-color" value="#000000" /><format attr="border-style" value="none" /><format attr="border-width" value="0" /><format attr="margin" value="0" /></zone-style></zone>'
zi = zipfile.ZipFile(book); tmp = book + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
    for it in zi.infolist():
        b = zi.read(it.filename)
        if it.filename.endswith(".twb"):
            t = b.decode("utf8")
            bars = re.search(r'<zone h="\d+" id="\d+" name="Lead Time Heat · Row Totals" show-title="false" w="(\d+)" x="(\d+)" y="(\d+)"', t)
            w, x, y = map(int, bars.groups())
            m = next(m for m in re.finditer(rf'<zone h="(\d+)" (id="\d+" type-v2="empty" w="{w}" x="{x}" y="(\d+)">.*?</zone>)', t, re.S) if int(m[1]) + int(m[3]) == y)
            new_id = max(map(int, re.findall(r'<zone [^>]*?\bid="(\d+)"', t))) + 1
            label = ZONE.format(h=TEXT_H, id=new_id, w=w, x=x, y=y - TEXT_H)
            t = t[:m.start()] + f'<zone h="{int(m[1]) - TEXT_H}" {m[2]}' + label + t[m.end():]
            b = t.encode("utf8")
        zo.writestr(it.filename, b)
zi.close(); os.replace(tmp, book)
