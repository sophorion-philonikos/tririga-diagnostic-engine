"""Visualizer search-index fields, live-edge flags, and search matching."""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli.visualizer import WorkflowVisualizer

WF_BUILDING = os.path.join(ROOT, 'wf_building_rpim_status_ind.txt')


def _load():
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(WF_BUILDING)
    return eng, eng.loaded_workflow_names[0]


def _extract_json_array(html, which):
    """Pull nodesData or edgesData JSON from rendered viewer HTML."""
    marker = 'var nodesData = ' if which == 'nodes' else 'var edgesData = '
    idx = html.find(marker)
    if idx < 0:
        raise AssertionError(f'Could not find {marker!r} in HTML')
    start = idx + len(marker)
    data, _end = json.JSONDecoder().raw_decode(html[start:])
    return data


def find_matches(nodes, q):
    """Mirror of viewer.html findMatches (case-insensitive id/name substring)."""
    term = (q or '').strip().lower()
    if not term:
        return []
    return [
        n for n in nodes
        if term in str(n.get('id', '')).lower() or term in str(n.get('name', '')).lower()
    ]


class TestVisualizerSearchIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.viz = WorkflowVisualizer(cls.engine)
        cls.html = cls.viz.build_html(cls.wf, live_trace_ids=['333427', '333428'])
        cls.nodes = _extract_json_array(cls.html, 'nodes')
        cls.edges = _extract_json_array(cls.html, 'edges')

    def test_nodes_include_id_and_name(self):
        self.assertTrue(self.nodes)
        for n in self.nodes:
            self.assertIn('id', n)
            self.assertIn('name', n)
            self.assertTrue(str(n['id']))
            self.assertTrue(str(n['name']))

    def test_nodes_include_type(self):
        typed = [n for n in self.nodes if n.get('type')]
        self.assertTrue(typed)

    def test_html_contains_task_search_input(self):
        self.assertIn('id="taskSearch"', self.html)
        self.assertIn('id="searchStatus"', self.html)

    def test_live_edges_flagged_and_wide(self):
        live_edges = [e for e in self.edges if e.get('live')]
        self.assertTrue(live_edges, 'expected at least one live edge for 333427→333428')
        for e in live_edges:
            self.assertGreaterEqual(e.get('width', 0), 6)
            self.assertEqual(e.get('color'), '#00c3a5')
        keys = {(e['from'], e['to']) for e in live_edges}
        self.assertIn(('333427', '333428'), keys)


class TestSearchMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.viz = WorkflowVisualizer(cls.engine)
        html = cls.viz.build_html(cls.wf)
        cls.nodes = _extract_json_array(html, 'nodes')

    def test_empty_query(self):
        self.assertEqual(find_matches(self.nodes, ''), [])
        self.assertEqual(find_matches(self.nodes, '   '), [])

    def test_exact_id(self):
        hits = find_matches(self.nodes, '333428')
        self.assertTrue(hits)
        self.assertTrue(any(str(h['id']) == '333428' for h in hits))

    def test_case_insensitive_name_substring(self):
        sample = next(n for n in self.nodes if n.get('name') and len(n['name']) > 4)
        fragment = sample['name'][1:5].swapcase()
        hits = find_matches(self.nodes, fragment)
        self.assertTrue(hits)
        self.assertTrue(any(str(h['id']) == str(sample['id']) for h in hits))

    def test_unknown_term(self):
        self.assertEqual(find_matches(self.nodes, 'zzznomatch99999xyz'), [])


if __name__ == '__main__':
    unittest.main()
