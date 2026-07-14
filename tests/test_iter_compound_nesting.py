"""Cycle-based Iter/Loop compound nesting (OOB Retrieve-inside-Iter)."""

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

VARIETY = os.path.join(ROOT, 'wf_xml_samples_variety')
BASELINE = os.path.join(VARIETY, 'Workflow_triMaintenance__cstCustomWorkflowBaseline.xml')
RENT = os.path.join(
    VARIETY,
    'Workflow_triHelper_triPatchHelper_cst-triPatchHelper-triCalculate-UpdateOperatingCostsRentComponent.xml',
)

ITER = '330916'
RETRIEVE = '330919'
ATTACH = '330906'
JUNCTION = '330917'
SET_PROJECT = '330905'


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


def _nodes_data(html):
    marker = 'var nodesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


def _edges_data(html):
    marker = 'var edgesData = '
    idx = html.find(marker)
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


@unittest.skipUnless(os.path.isfile(BASELINE), 'baseline sample missing')
class TestBaselineIterCycleNesting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng, cls.wf = _load(BASELINE)
        cls.graph = cls.eng.graphs[cls.wf]
        cls.members = graph_utils.iter_body_members(cls.graph, ITER)
        cls.parents, cls.containers, cls.by_c = graph_utils.compute_container_parents(
            cls.graph, branch_map_fn=cls.eng.get_branch_map,
        )
        cls.html = WorkflowVisualizer(cls.eng).build_html(cls.wf)
        cls.nodes = {n['id']: n for n in _nodes_data(cls.html)}
        cls.edges = _edges_data(cls.html)

    def test_retrieve_cycles_inside_iter(self):
        self.assertIn(RETRIEVE, self.members)
        self.assertEqual(self.parents.get(RETRIEVE), ITER)

    def test_attach_format_outside_iter(self):
        self.assertNotIn(ATTACH, self.members)
        self.assertNotEqual(self.parents.get(ATTACH), ITER)

    def test_type11_junction_not_in_nodesdata(self):
        self.assertNotIn(JUNCTION, self.nodes)

    def test_iter_is_cluster_with_retrieve_child(self):
        cluster_id = graph_utils.cluster_wrapper_id(ITER)
        self.assertTrue(self.nodes[cluster_id].get('isCluster'))
        self.assertEqual(self.nodes[cluster_id].get('taskId'), ITER)
        self.assertFalse(self.nodes[ITER].get('isCluster'))
        self.assertEqual(self.nodes[ITER].get('parent'), cluster_id)
        self.assertEqual(self.nodes[RETRIEVE].get('parent'), cluster_id)

    def test_set_project_outside(self):
        self.assertNotEqual(self.nodes.get(SET_PROJECT, {}).get('parent'),
                            graph_utils.cluster_wrapper_id(ITER))

    def test_back_edge_retrieve_to_iter(self):
        backs = [
            e for e in self.edges
            if e['from'] == RETRIEVE and e['to'] == ITER and e.get('constraint') is False
        ]
        self.assertTrue(backs)
        self.assertEqual(backs[0].get('kind'), 'loop-back')

    def test_no_edges_touch_cluster_wrappers(self):
        """Dagre crashes with rank errors if edges touch compound parents."""
        cluster_ids = {n['id'] for n in self.nodes.values() if n.get('isCluster')}
        for e in self.edges:
            self.assertNotIn(e['from'], cluster_ids)
            self.assertNotIn(e['to'], cluster_ids)

    def test_viewer_compound_hooks(self):
        self.assertIn('compound: true', self.html)
        self.assertIn('setParent', self.html)
        self.assertIn('decorateClusterCaps', self.html)
        # Modest denser packing so more tasks fit on screen.
        self.assertIn('nodesep: 55', self.html)
        self.assertIn('ranksep: 55', self.html)
        self.assertIn('edgesep: 25', self.html)


@unittest.skipUnless(os.path.isfile(RENT), 'Rent sample missing')
class TestRentIterHasCycleChild(unittest.TestCase):
    def test_iter_332620_has_visible_cycle_member(self):
        eng, wf = _load(RENT)
        g = eng.graphs[wf]
        members = graph_utils.iter_body_members(g, '332620')
        # Modify 332623 cycles back to Iter
        self.assertIn('332623', members)
        parents, _, _ = graph_utils.compute_container_parents(g)
        self.assertEqual(parents.get('332623'), '332620')
        html = WorkflowVisualizer(eng).build_html(wf)
        nodes = {n['id']: n for n in _nodes_data(html)}
        cluster_id = graph_utils.cluster_wrapper_id('332620')
        self.assertTrue(nodes[cluster_id].get('isCluster'))
        self.assertEqual(nodes['332623'].get('parent'), cluster_id)
        self.assertEqual(nodes['332620'].get('parent'), cluster_id)
        edges = _edges_data(html)
        for e in edges:
            self.assertNotEqual(e['from'], cluster_id)
            self.assertNotEqual(e['to'], cluster_id)


class TestEmptyClusterFallback(unittest.TestCase):
    def test_iter_without_cycle_is_leaf(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node('1', type='1', name='Start')
        g.add_node('24', type='24', name='Lonely Iter', TargetAssociation='9;')
        g.add_node('9', type='9', name='End')
        g.add_edge('1', '24')
        g.add_edge('24', '9')
        members = graph_utils.iter_body_members(g, '24')
        self.assertEqual(members, set())
        parents, _, _ = graph_utils.compute_container_parents(g)
        self.assertNotIn('9', parents)


if __name__ == '__main__':
    unittest.main()
