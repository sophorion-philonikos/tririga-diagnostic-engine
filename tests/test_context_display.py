"""Diagnostic panel Context line shows BO plus source task when uniquely known."""

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

RETRIEVE_APPROVAL = '346314'
VAR_APPROVAL = '346425'
MODIFY_SUBMITTED_BY = '332295'  # Type 28 — proves non-Retrieve coverage


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
class TestNotificationContextDisplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(NOTIFICATION)
        cls.graph = cls.eng.graphs[cls.wf]
        cls.html = WorkflowVisualizer(cls.eng).build_html(cls.wf)

    def test_retrieve_approval_shows_source_task(self):
        payload = _payload_for_task(self.html, RETRIEVE_APPROVAL)
        self.assertIn('triApproval (INNVarApproval)', payload)
        self.assertIn(f'<b>ID:</b> {RETRIEVE_APPROVAL}', payload)

    def test_modify_shows_source_task(self):
        """Type 28 Modify — same FromTask rule, not Retrieve-only."""
        data = self.graph.nodes[MODIFY_SUBMITTED_BY]
        self.assertEqual(str(data.get('type')), '28')
        payload = _payload_for_task(self.html, MODIFY_SUBMITTED_BY)
        self.assertIn(
            'triNotificationHelper (Modify Content Request Info and  Project ID)',
            payload,
        )

    def test_source_variable_shows_bo_only(self):
        payload = _payload_for_task(self.html, VAR_APPROVAL)
        self.assertIn('<b>Context:</b> triApproval', payload)
        self.assertNotIn('INNVarApproval)', payload)


class TestFormatContextDisplay(unittest.TestCase):
    def test_single_from_task(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('346425', name='INNVarApproval', type='40')
        data = {'FromTask': ['346425']}
        self.assertEqual(
            graph_utils.format_context_display('triApproval', data, g),
            'triApproval (INNVarApproval)',
        )

    def test_no_from_task(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('346425', name='INNVarApproval', type='40')
        self.assertEqual(
            graph_utils.format_context_display('triApproval', {}, g),
            'triApproval',
        )

    def test_multiple_from_tasks_ambiguous(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('1', name='Start', type='1')
        g.add_node('2', name='Other', type='28')
        data = {'FromTask': ['1', '2']}
        self.assertEqual(
            graph_utils.format_context_display('triApproval', data, g),
            'triApproval',
        )

    def test_start_from_task_ambiguous(self):
        import networkx as nx
        g = nx.DiGraph()
        data = {'FromTask': ['0']}
        self.assertEqual(
            graph_utils.format_context_display('triApproval', data, g),
            'triApproval',
        )

    def test_missing_source_node(self):
        import networkx as nx
        g = nx.DiGraph()
        data = {'FromTask': ['999']}
        self.assertEqual(
            graph_utils.format_context_display('triApproval', data, g),
            'triApproval',
        )

    def test_unnamed_source_ambiguous(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('99', name='Unnamed Component (99)', type='28')
        data = {'FromTask': ['99']}
        self.assertEqual(
            graph_utils.format_context_display('triApproval', data, g),
            'triApproval',
        )


if __name__ == '__main__':
    unittest.main()
