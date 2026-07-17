"""Fiscal Months: break Iter/Loop mutual nesting; viz error UX hooks."""

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

FISCAL = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triPatchHelper_cst-triPatchHelper-triCalculate-UtilityWFUpdateFiscalMonths.xml',
)

ITER = '332095'
LOOP = '332552'


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


def _nodes(html):
    marker = 'var nodesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


def _edges(html):
    marker = 'var edgesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


def _container_parent_cycle(parents, container_ids):
    for start in container_ids:
        seen = []
        cur = start
        while cur and cur in container_ids:
            if cur in seen:
                return seen[seen.index(cur):] + [cur]
            seen.append(cur)
            cur = parents.get(cur) if parents.get(cur) in container_ids else None
    return None


class TestBreakContainerParentCycles(unittest.TestCase):
    def test_loop_outer_breaks_mutual_pair(self):
        g = nx.DiGraph()
        # Minimal cycle: Iter <-> Loop share body node
        for nid, t in (('iter', '24'), ('loop', '20'), ('body', '28')):
            g.add_node(nid, Type=t, type=t, name=nid)
        g.add_edges_from([
            ('iter', 'body'), ('body', 'loop'), ('loop', 'iter'),
            ('loop', 'body'), ('body', 'iter'),
        ])
        parents, cids, _ = graph_utils.compute_container_parents(g)
        self.assertIn('iter', cids)
        self.assertIn('loop', cids)
        self.assertEqual(parents.get('iter'), 'loop')
        self.assertNotEqual(parents.get('loop'), 'iter')
        self.assertIsNone(_container_parent_cycle(parents, cids))


@unittest.skipUnless(os.path.isfile(FISCAL), 'Fiscal Months sample missing')
class TestFiscalMonthsNest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(FISCAL)
        cls.graph = cls.eng.graphs[cls.wf]
        cls.parents, cls.cids, _ = graph_utils.compute_container_parents(
            cls.graph, branch_map_fn=cls.eng.get_branch_map,
        )
        cls.html = WorkflowVisualizer(cls.eng).build_html(cls.wf)
        cls.nodes = _nodes(cls.html)
        cls.edges = _edges(cls.html)

    def test_iter_inside_loop_no_cycle(self):
        self.assertEqual(self.parents.get(ITER), LOOP)
        self.assertNotEqual(self.parents.get(LOOP), ITER)
        self.assertIsNone(_container_parent_cycle(self.parents, self.cids))

    def test_cluster_wrappers_acyclic(self):
        by_id = {n['id']: n for n in self.nodes}
        # Loop outer cluster wraps Iter cluster; no mutual parent cycle.
        self.assertTrue(by_id['c_' + LOOP].get('isCluster'))
        self.assertTrue(by_id['c_' + ITER].get('isCluster'))
        self.assertEqual(by_id['c_' + ITER].get('parent'), 'c_' + LOOP)
        self.assertIsNone(by_id['c_' + LOOP].get('parent'))
        self.assertEqual(by_id[ITER].get('parent'), 'c_' + ITER)

    def test_no_edges_on_cluster_wrappers(self):
        clusters = {n['id'] for n in self.nodes if n.get('isCluster')}
        for e in self.edges:
            self.assertNotIn(e['from'], clusters)
            self.assertNotIn(e['to'], clusters)

    def test_viewer_error_ux_hooks(self):
        self.assertIn('assertAcyclicParents', self.html)
        self.assertIn('viz-error-banner', self.html)
        self.assertIn('showRenderFailure', self.html)
        self.assertIn('window.onerror', self.html)
        self.assertIn('onunhandledrejection', self.html)


if __name__ == '__main__':
    unittest.main()
