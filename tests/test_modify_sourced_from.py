"""Modify diagnostics 'Sourced From' line from FilterTask (UseType=2)."""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import graph_utils
from cli.visualizer import WorkflowVisualizer

NOTIFICATION = os.path.join(
    ROOT,
    'wf_xml_samples_variety',
    'Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml',
)

UPDATE_LOCATION = '332710'
SOURCE_RETRIEVE = '334773'
SELF_MAP_MODIFY = '335072'  # FilterTask 0 — omit Sourced From


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


def _payload_for_task(html, task_id):
    marker = 'var nodesData = '
    idx = html.find(marker)
    nodes, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    for n in nodes:
        if n['id'] == task_id:
            return n['customPayload']
    raise AssertionError(f'task {task_id} missing from nodesData')


@unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
class TestUpdateLocationSourcedFrom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(NOTIFICATION)
        cls.graph = cls.eng.graphs[cls.wf]
        cls.html = WorkflowVisualizer(cls.eng).build_html(cls.wf)

    def test_update_location_sourced_from_retrieve(self):
        payload = _payload_for_task(self.html, UPDATE_LOCATION)
        self.assertIn('Sourced From:', payload)
        self.assertIn('Retrieve NEPA Request Location Records (Location)', payload)
        self.assertIn(f"window.focusNode('{SOURCE_RETRIEVE}')", payload)

    def test_self_map_modify_omits_sourced_from(self):
        data = self.graph.nodes[SELF_MAP_MODIFY]
        self.assertEqual(str(data.get('type')), '28')
        self.assertEqual([str(t) for t in (data.get('FilterTask') or [])], ['0'])
        payload = _payload_for_task(self.html, SELF_MAP_MODIFY)
        self.assertNotIn('Sourced From:', payload)

    def test_viewer_exposes_focus_node(self):
        self.assertIn('window.focusNode = focusNode', self.html)
        self.assertIn('.source-link', self.html)


class TestResolveModifySource(unittest.TestCase):
    def test_happy_path(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('334773', name='Retrieve NEPA Request Location Records', type='29')
        data = {
            'FilterTask': ['334773'],
            'ObjMappingRecords': [{'SrcBo': 'Location', 'TrgtFld': 'triInput4TX'}],
        }
        self.assertEqual(
            graph_utils.resolve_modify_source(data, g),
            ('334773', 'Retrieve NEPA Request Location Records (Location)'),
        )

    def test_missing_filter_task(self):
        import networkx as nx
        g = nx.DiGraph()
        self.assertIsNone(graph_utils.resolve_modify_source({}, g))

    def test_start_filter_task_omitted(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('0', name='Start', type='1')
        self.assertIsNone(graph_utils.resolve_modify_source({'FilterTask': ['0']}, g))

    def test_unnamed_source_omitted(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('99', name='Unnamed Component (99)', type='29')
        self.assertIsNone(graph_utils.resolve_modify_source({'FilterTask': ['99']}, g))


if __name__ == '__main__':
    unittest.main()
