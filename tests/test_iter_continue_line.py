"""Iter/Loop continue edges: hidden body branches + perimeter container-continue."""

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
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml',
)

ITER = '334008'
SUM_REGION = '334015'       # EXIT target (inside Iter)
NEXT_AFTER = '334027'       # LOOP BODY → outside (Update Notification Helper)


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


def _edges(html):
    marker = 'var edgesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


class TestRestyleContainerBranchEdges(unittest.TestCase):
    def test_iter_inside_exit_hidden_outside_continue(self):
        edges = [
            {'from': 'iter', 'to': 'body', 'label': 'EXIT', 'constraint': True},
            {'from': 'iter', 'to': 'next', 'label': 'LOOP BODY', 'constraint': True},
        ]
        out = graph_utils.restyle_container_branch_edges(
            edges,
            parents={'body': 'iter'},
            wrapping_containers={'iter'},
            members_by_container={'iter': {'body'}},
            container_types={'iter': '24'},
        )
        by_to = {e['to']: e for e in out}
        self.assertEqual(by_to['body']['kind'], 'iter-branch-hidden')
        self.assertEqual(by_to['body']['label'], 'EXIT')
        self.assertEqual(by_to['next']['kind'], 'container-continue')
        self.assertEqual(by_to['next']['label'], '')
        self.assertEqual(by_to['next']['exitContainer'], 'iter')

    def test_loop_body_escape_tagged_container_continue(self):
        edges = [
            {'from': 'loop', 'to': 'body', 'label': '', 'constraint': True},
            {'from': 'body', 'to': 'outside', 'label': '', 'constraint': True},
            {'from': 'body', 'to': 'loop', 'label': '', 'constraint': False, 'kind': 'loop-back'},
        ]
        out = graph_utils.restyle_container_branch_edges(
            edges,
            parents={'body': 'loop'},
            wrapping_containers={'loop'},
            members_by_container={'loop': {'body'}},
            container_types={'loop': '20'},
        )
        continues = [e for e in out if e.get('kind') == 'container-continue']
        self.assertEqual(len(continues), 1)
        self.assertEqual(continues[0]['from'], 'loop')
        self.assertEqual(continues[0]['to'], 'outside')
        self.assertEqual(continues[0]['exitContainer'], 'loop')
        backs = [e for e in out if e.get('kind') == 'loop-back']
        self.assertEqual(len(backs), 1)


@unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
class TestIter334008ContinueLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(NOTIFICATION)
        cls.html = WorkflowVisualizer(cls.eng).build_html(cls.wf)
        cls.edges = _edges(cls.html)

    def test_exit_to_sum_hidden(self):
        hits = [e for e in self.edges if e['from'] == ITER and e['to'] == SUM_REGION]
        self.assertTrue(hits)
        self.assertEqual(hits[0].get('kind'), 'iter-branch-hidden')
        self.assertEqual(hits[0].get('label'), 'EXIT')

    def test_continue_to_334027(self):
        hits = [e for e in self.edges if e['from'] == ITER and e['to'] == NEXT_AFTER]
        self.assertTrue(hits)
        self.assertEqual(hits[0].get('kind'), 'container-continue')
        self.assertEqual(hits[0].get('label'), '')
        self.assertEqual(hits[0].get('exitContainer'), ITER)

    def test_no_visible_exit_or_loop_body_labels_from_iter(self):
        for e in self.edges:
            if e['from'] != ITER:
                continue
            if e.get('kind') == 'iter-branch-hidden':
                continue
            self.assertNotIn(e.get('label'), ('EXIT', 'LOOP BODY'), e)

    def test_viewer_skirts_continue_edges(self):
        self.assertIn('hideIterBranchEdges', self.html)
        self.assertIn('routeContainerContinueEdges', self.html)
        self.assertIn('iter-branch-hidden', self.html)
        self.assertIn('container-continue', self.html)


if __name__ == '__main__':
    unittest.main()
