"""Switch TRUE/FALSE labels: no dual-TRUE via diamond merge through visible TRUE hop."""

import json
import os
import sys
import unittest

import networkx as nx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import graph_utils
from cli.visualizer import WorkflowVisualizer

VARIETY = os.path.join(ROOT, 'wf_xml_samples_variety')
MYPROFILE = os.path.join(
    VARIETY,
    'Workflow_triPeople_MyProfile_MyProfile-Synchronous-RequirePasswordChangePortalUpdate.xml',
)
CAPITAL = os.path.join(
    VARIETY,
    'Workflow_triProject_triCapitalProject_triCapitalProject-triCopy-CreatesaCopy.xml',
)


def _edges(html):
    marker = 'var edgesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


class TestBranchLabelForVisibleHelper(unittest.TestCase):
    def test_diamond_invisible_false_not_claimed_by_true(self):
        g = nx.DiGraph()
        g.add_node('sw', Type='14')
        g.add_node('mod', Type='28')          # visible TRUE target
        g.add_node('end', Type='12')          # invisible FALSE target
        g.add_node('merge', Type='31')        # visible merge
        g.add_edges_from([
            ('sw', 'mod'), ('sw', 'end'),
            ('mod', 'end'), ('end', 'merge'),
        ])
        branch_map = {'mod': 'TRUE', 'end': 'FALSE'}
        self.assertEqual(
            graph_utils.branch_label_for_visible(g, branch_map, 'mod'), 'TRUE',
        )
        self.assertEqual(
            graph_utils.branch_label_for_visible(g, branch_map, 'merge'), 'FALSE',
        )


@unittest.skipUnless(os.path.isfile(MYPROFILE), 'MyProfile sample missing')
class TestMyProfileSwitchLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(MYPROFILE)
        cls.edges = _edges(WorkflowVisualizer(cls.eng).build_html(cls.wf))

    def test_265985_true_and_false(self):
        by_to = {
            e['to']: e.get('label')
            for e in self.edges if e['from'] == '265985'
        }
        self.assertEqual(by_to.get('220642'), 'TRUE')
        self.assertEqual(by_to.get('498837'), 'FALSE')


@unittest.skipUnless(os.path.isfile(CAPITAL), 'Capital sample missing')
class TestCapitalSwitchLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(CAPITAL)
        cls.edges = _edges(WorkflowVisualizer(cls.eng).build_html(cls.wf))

    def test_346492_true_and_false(self):
        by_to = {
            e['to']: e.get('label')
            for e in self.edges if e['from'] == '346492'
        }
        self.assertEqual(by_to.get('346496'), 'TRUE')
        self.assertEqual(by_to.get('346212'), 'FALSE')


if __name__ == '__main__':
    unittest.main()
