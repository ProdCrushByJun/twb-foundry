"""Field folders in the Data pane (decisions/146): calcs[].folder and fields.<name>.folder.

Desktop 2025.1 form (EnterpriseRiskDashboard 2025.1.2, TableauBootcamp 2023.3, re-saved golden_folders): a
<folders-common> child of the datasource, after its columns and column instances, one <folder name='..'> per folder
with <folder-item name='[Column]' type='field'/> children; a calc by its internal Calculation_... name. With folders
the Data pane groups by folder (<layout show-structure='false'>)."""
import re
import xml.etree.ElementTree as ET

_NAME = re.compile(r"^[^\[\]'\"<>&]{1,100}$")


def of(b):
    """{folder: [spec field names]} of this datasource's spec, checked against its columns and calcs. A field is in
    at most one folder; no folders: {}."""
    spec = b.spec
    where_of = {}
    for c in spec.get("calcs", []):
        if "folder" in c:
            where_of[c["name"]] = (c["folder"], f"Calc '{c['name']}'")
    calcs = {c["name"] for c in spec.get("calcs", [])}
    columns = {c.name for c in b.prof.columns}
    for name, p in (spec.get("fields") or {}).items():
        if "folder" not in p:
            continue
        where = f"fields '{name}'"
        if name in where_of and where_of[name][0] != p["folder"]:
            raise ValueError(f"{where}: folder '{p['folder']}', but calc '{name}' has folder '{where_of[name][0]}'; "
                             f"a field is in one folder")
        if name in b.fields.groups:
            raise ValueError(f"{where}: a folder for a group is not verified in Tableau yet; put its source column "
                             f"'{b.fields.groups[name].source}' in the folder")
        if name not in columns and name not in calcs:
            raise ValueError(f"{where}: folder of an unknown field; columns: {sorted(columns)}, calcs: {sorted(calcs)}")
        where_of[name] = (p["folder"], where)
    out = {}
    for name, (folder, where) in where_of.items():
        if not _NAME.match(folder) or folder != folder.strip():
            raise ValueError(f"{where}: folder name {folder!r} must be 1-100 characters without [ ] ' \" < > & and "
                             f"without leading or trailing spaces")
        out.setdefault(folder, []).append(name)
    return out


def column_name(b, name):
    """The field's column in the workbook: a calc's internal Calculation_..., a column of the data its own name."""
    return b.calc_cols[name].name if name in {c["name"] for c in b.spec.get("calcs", [])} else name


def write(b, ds):
    """<folders-common> in the datasource, folders and their items in name order as Desktop writes them."""
    if not b.folders:
        return
    common = ET.SubElement(ds, "folders-common")
    for folder in sorted(b.folders):
        el = ET.SubElement(common, "folder", name=folder)
        for col in sorted(f"[{column_name(b, n)}]" for n in b.folders[folder]):
            ET.SubElement(el, "folder-item", name=col, type="field")
