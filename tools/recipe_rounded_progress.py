"""Rounded progress on the reference '7. Rounded Progress Bar' mechanics.

Takes a generator book with one bar sheet and swaps its marks for one thick Line through 1 -> share -> 0 -> share.
Base: tb build a spec with a bar sheet (dimension, SUM of a measure, sort desc).
python tools/recipe_rounded_progress.py <base.twbx> <out.twbx> <sheet> <dimension> <measure> [mark size]
"""
import sys, zipfile
from pathlib import Path
from lxml import etree

BASE, OUT, SHEET, DIM, MEASURE = Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:6]
SIZE = sys.argv[6] if len(sys.argv) > 6 else '7.5'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tbuilder import design

ONE, ZERO, SHARE, END = ('Calculation_9100000000000000001', 'Calculation_9100000000000000002',
                         'Calculation_9100000000000000003', 'Calculation_9100000000000000004')
SHARE_F = f'SUM([{MEASURE}])/TOTAL(SUM([{MEASURE}]))'
DIM_I = f'[none:{DIM}:nk]'


def sub(parent, tag, **attrs):
    return etree.SubElement(parent, tag, {k.replace('_', '-'): v for k, v in attrs.items()})


def calc(parent, name, caption, datatype, formula, table_calc=False, fmt=None):
    a = {'caption': caption, 'datatype': datatype, 'name': f'[{name}]', 'role': 'measure', 'type': 'quantitative'}
    if fmt:
        a['default-format'] = fmt
    c = etree.SubElement(parent, 'column', a)
    f = sub(c, 'calculation', **{'class': 'tableau'}, formula=formula)
    if table_calc:
        sub(f, 'table-calc', ordering_field=f'[{DS_NAME}].{DIM_I}', ordering_type='Field')
    return c


def calcs(parent):
    return [calc(parent, ONE, 'Track end', 'integer', 'MIN(1)'), calc(parent, ZERO, 'Zero', 'integer', 'MIN(0)'),
            calc(parent, SHARE, 'Share', 'real', SHARE_F, True, 'p0.0%'),
            calc(parent, END, 'Share (end)', 'real', SHARE_F, True, 'p0.0%')]


def instances(parent):
    for col, inst in ((ONE, f'[usr:{ONE}:qk]'), (ZERO, f'[usr:{ZERO}:qk]')):  # MIN(1), not SUM of a 1: that counts the rows
        sub(parent, 'column-instance', column=f'[{col}]', derivation='User', name=inst, pivot='key', type='quantitative')
    for col, inst in ((SHARE, f'[usr:{SHARE}:qk]'), (END, f'[usr:{END}:qk]')):
        ci = sub(parent, 'column-instance', column=f'[{col}]', derivation='User', name=inst, pivot='key', type='quantitative')
        sub(ci, 'table-calc', ordering_field=f'[{DS_NAME}].{DIM_I}', ordering_type='Field')


with zipfile.ZipFile(BASE) as z:
    members = {n: z.read(n) for n in z.namelist()}
twb = next(n for n in members if n.endswith('.twb'))
root = etree.fromstring(members[twb])
ds = root.find('.//datasources/datasource')
name = DS_NAME = ds.get('name')
q = lambda f: f'[{name}].{f}'
order = [f'[usr:{ONE}:qk]', f'[usr:{SHARE}:qk]', f'[usr:{ZERO}:qk]', f'[usr:{END}:qk]']  # the line's points
bucket = lambda f: f'"{q(f)}"'
track, fill = design.COLOR['track'], design.COLOR['accent']

# the datasource: the calcs, then the instances and the palette the Measure Names map refers to
last = ds.findall('column')[-1]
at = list(ds).index(last) + 1
holder = etree.Element('x')
calcs(holder)
sub(holder, 'column', datatype='string', name=f'[{DIM}]', role='dimension', type='nominal')
sub(holder, 'column-instance', column=f'[{DIM}]', derivation='None', name=DIM_I, pivot='key', type='nominal')
instances(holder)
for i, e in enumerate(list(holder)):
    ds.insert(at + i, e)
style = etree.Element('style')
rule = sub(style, 'style-rule', element='mark')
enc = sub(rule, 'encoding', attr='color', field='[:Measure Names]', type='palette')
for b, c in sorted([(order[0], track), (order[1], fill), (order[2], fill), (order[3], track)], key=lambda x: (x[1], x[0])):
    sub(sub(enc, 'map', to=c), 'bucket').text = bucket(b)
ds.insert(list(ds).index(ds.find('layout')) + 1, style)

# the sheet
ws = next(w for w in root.iterfind('.//worksheet') if w.get('name') == SHEET)
table = ws.find('table')
view = table.find('view')
deps = view.find('datasource-dependencies')
calcs(deps)
instances(deps)
sort = view.find('computed-sort')  # by SUM of the measure: Desktop refuses a table calc here
at = list(view).index(sort)
flt = etree.Element('filter', {'class': 'categorical', 'column': q('[:Measure Names]')})
union = sub(flt, 'groupfilter', function='union')
for b in order:
    sub(union, 'groupfilter', function='member', level='[:Measure Names]', member=bucket(b))
view.insert(at, flt)
ms = etree.Element('manual-sort', column=q('[:Measure Names]'), direction='ASC')
d = sub(ms, 'dictionary')
for b in order:
    sub(d, 'bucket').text = bucket(b)
view.insert(at + 1, ms)
view.insert(list(view).index(sort) + 1, etree.fromstring(f'<slices><column>{q("[:Measure Names]")}</column></slices>'))

for f in table.findall('style/style-rule/format'):
    if f.get('field') == q(f'[sum:{MEASURE}:qk]'):
        f.set('field', q('[Multiple Values]'))
pane = table.find('panes/pane')
pane.find('mark').set('class', 'Line')
mark = pane.find('mark')
mark.addnext(etree.fromstring('<mark-sizing mark-sizing-setting="marks-scaling-off"/>'))
encodings = etree.Element('encodings')
sub(encodings, 'color', column=q('[:Measure Names]'))
sub(encodings, 'text', column=q(f'[usr:{SHARE}:qk]'))
sub(encodings, 'lod', column=q('[:Measure Names]'))
sub(encodings, 'path', column=q('[:Measure Names]'))
pane.find('mark-sizing').addnext(encodings)
pane_style = pane.find('style')
cell = etree.Element('style-rule', element='cell')  # the label beside the fill's end, in the row
sub(cell, 'format', attr='vertical-align', value='center')
sub(cell, 'format', attr='text-align', value='right')
pane_style.insert(0, cell)
label = etree.Element('style-rule', element='datalabel')
sub(label, 'format', attr='color', value=design.COLOR['text'])
sub(label, 'format', attr='font-weight', value='bold')
pane_style.insert(1, label)
m = pane.find('style/style-rule[@element="mark"]')
for f in list(m):
    m.remove(f)
for a, v in (('size', SIZE), ('mark-labels-show', 'true'), ('mark-labels-cull', 'false'), ('mark-labels-mode', 'line-ends'),
             ('mark-labels-line-first', 'false'), ('line-interpolation', 'step')):  # step: one color per segment, no gradient
    sub(m, 'format', attr=a, value=v)
table.find('cols').text = q('[Multiple Values]')

members[twb] = etree.tostring(root, xml_declaration=True, encoding='utf-8')
OUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    for n, b in members.items():
        z.writestr(n, b)
print(OUT)
