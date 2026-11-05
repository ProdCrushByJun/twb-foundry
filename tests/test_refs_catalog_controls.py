"""Parameters, filters and actions of a dashboard: said in the gallery, not picked by number."""
import shutil
import tempfile
import unittest
from pathlib import Path

from tbuilder import refs_catalog

BOOK = """<workbook><datasources>
  <datasource name='Parameters'><column name='[Parameter 1]' caption='Currency' datatype='string'/></datasource>
  <datasource name='ds'><column name='[Calculation_1]' caption='Game'><calculation formula='1'/></column></datasource></datasources>
  <actions>
    <action name='a'><activation type='on-select'/><source type='sheet' dashboard='One' worksheet='S'/><command command='tsc:tsl-filter'/></action>
    <action name='b'><activation type='on-select'/><source type='sheet' dashboard='One' worksheet='S'/><command command='tsc:tsl-filter'/></action>
    <action name='c'><activation type='on-hover'/><source type='sheet' dashboard='One' worksheet='S'/><command command='tsc:brush'/></action>
    <action name='d'><activation type='on-select'/><source type='sheet' dashboard='One' worksheet='S'/><link expression='http://x'/></action>
    <nav-action name='e'><activation type='on-select'/><source type='sheet' dashboard='One'/></nav-action>
    <edit-parameter-action name='f'><activation type='on-select'/><source type='sheet' dashboard='One'/></edit-parameter-action>
    <action name='g'><activation type='on-select'/><source type='sheet' dashboard='Two' worksheet='S'/><command command='tsc:brush'/></action>
    <datasources/>
  </actions>
  <worksheets><worksheet name='S'><table><panes><pane><mark class='Bar'/></pane></panes><rows>[ds].[none:A:nk]</rows><cols>[ds].[sum:X:qk]</cols></table></worksheet></worksheets>
  <dashboards>
    <dashboard name='One'><size maxheight='800' maxwidth='1400'/><zones><zone type-v2='layout-basic' x='0' y='0' w='100000' h='100000'>
      <zone name='S' x='0' y='0' w='100000' h='80000'/>
      <zone type-v2='paramctrl' param='[Parameters].[Parameter 1]' mode='compact' x='0' y='80000' w='50000' h='20000'/>
      <zone type-v2='filter' param='[ds].[none:Calculation_1:nk]' mode='slider' x='50000' y='80000' w='50000' h='20000'/>
    </zone></zones></dashboard>
    <dashboard name='Two'><size maxheight='800' maxwidth='1400'/><zones><zone name='S' x='0' y='0' w='100000' h='100000'/></zones></dashboard>
  </dashboards></workbook>"""


class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "b.twb").write_text(BOOK, encoding="utf-8")

    def catalog(self):
        return refs_catalog.number({"version": 1, "books": [refs_catalog.read_book(self.tmp / "b.twb")]})

    def test_each_kind_on_its_own_dashboard(self):
        one, two = refs_catalog.read_book(self.tmp / "b.twb")["dashboards"]
        self.assertEqual(one["controls"]["parameters"], [{"name": "Currency", "control": "dropdown"}])
        self.assertEqual(one["controls"]["filters"], [{"name": "Game", "control": "slider"}])
        self.assertEqual({(a["kind"], a["on"]): a["count"] for a in one["controls"]["actions"]},
                         {("filter", "click"): 2, ("highlight", "hover"): 1, ("url", "click"): 1,
                          ("navigation", "click"): 1, ("parameter", "click"): 1})
        self.assertEqual(two["controls"], {"parameters": [], "filters": [],
                                           "actions": [{"kind": "highlight", "on": "click", "count": 1}]})

    def test_the_gallery_says_them_and_gives_no_number(self):
        text = refs_catalog.gallery(self.catalog())
        self.assertIn("### Controls and clicks", text)
        self.assertIn("Not picked by number", text)
        self.assertIn("| One | Currency (dropdown) | Game (slider) | ", text)
        self.assertIn("2 filter on click", text)
        self.assertIn("1 highlight on hover", text)

    def test_an_old_catalog_prints_no_section(self):
        cat = self.catalog()
        for d in cat["books"][0]["dashboards"]:
            del d["controls"]
        self.assertNotIn("Controls and clicks", refs_catalog.gallery(cat))


if __name__ == "__main__":
    unittest.main()
