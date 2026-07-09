"""Graph traversal helpers: visible successors and path reachability."""

import os
import sys
import unittest

import networkx as nx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import graph_utils
from cli import simulation

WF_BUILDING = os.path.join(ROOT, 'wf_building_rpim_status_ind.txt')


def _load():
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(WF_BUILDING)
    return eng, eng.loaded_workflow_names[0]


class TestVisibleSuccessors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.graph = cls.engine.graphs[cls.wf]

    def test_start_has_visible_successors(self):
        starts = [n for n, d in self.graph.in_degree() if d == 0]
        self.assertTrue(starts)
        start = starts[0]
        targets = graph_utils.visible_successors(self.graph, start)
        self.assertTrue(targets)
        for tid in targets:
            data = self.graph.nodes[tid]
            self.assertFalse(graph_utils.is_invisible(data), tid)

    def test_invisible_junctions_skipped(self):
        for nid, data in self.graph.nodes(data=True):
            if not graph_utils.is_invisible(data):
                continue
            for succ in graph_utils.visible_successors(self.graph, nid):
                self.assertFalse(
                    graph_utils.is_invisible(self.graph.nodes[succ]),
                    f"visible successor {succ} of invisible {nid} is invisible")

    def test_resolve_to_visible_identity(self):
        for nid, data in list(self.graph.nodes(data=True))[:20]:
            if graph_utils.is_invisible(data):
                continue
            resolved = graph_utils.resolve_to_visible(self.graph, nid)
            self.assertEqual(resolved, [str(nid)])


class TestPathReachability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.graph = cls.engine.graphs[cls.wf]

    def test_path_to_333428(self):
        path = simulation.path_to_task(self.graph, '333428')
        self.assertTrue(path)
        self.assertEqual(path[-1], '333428')
        self.assertIn('333427', path)

    def test_path_to_333378(self):
        path = simulation.path_to_task(self.graph, '333378')
        self.assertTrue(path)
        self.assertEqual(path[-1], '333378')

    def test_shortest_path_exists_start_to_end(self):
        starts = [n for n, d in self.graph.in_degree() if d == 0]
        ends = [
            n for n, data in self.graph.nodes(data=True)
            if graph_utils.get_type_str(data) in ('9', '13')
        ]
        self.assertTrue(starts and ends)
        reachable = False
        for s in starts:
            for e in ends:
                try:
                    nx.shortest_path(self.graph, s, e)
                    reachable = True
                    break
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
            if reachable:
                break
        self.assertTrue(reachable)


if __name__ == '__main__':
    unittest.main()
