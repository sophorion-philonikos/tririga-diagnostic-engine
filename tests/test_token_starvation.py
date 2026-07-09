"""Token starvation: index edges and null-token cascade hops."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import simulation

WF_BUILDING = os.path.join(ROOT, 'wf_building_rpim_status_ind.txt')


def _load():
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(WF_BUILDING)
    return eng, eng.loaded_workflow_names[0]


class TestTokenIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.graph = cls.engine.graphs[cls.wf]
        cls.index = simulation.build_token_index(cls.graph)

    def test_index_nonempty(self):
        self.assertTrue(self.index)

    def test_333427_feeds_333428(self):
        consumers = {str(c) for c, _kind in self.index.get('333427', [])}
        self.assertIn('333428', consumers)

    def test_333378_feeds_333417(self):
        consumers = {str(c) for c, _kind in self.index.get('333378', [])}
        self.assertIn('333417', consumers)

    def test_333417_feeds_333418(self):
        consumers = {str(c) for c, _kind in self.index.get('333417', [])}
        self.assertIn('333418', consumers)


class TestPropagateNullToken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.graph = cls.engine.graphs[cls.wf]
        cls.index = simulation.build_token_index(cls.graph)

    def test_single_hop_333427(self):
        impacted, impacts = simulation.propagate_null_token(
            self.graph, ['333427'], self.index)
        self.assertIn('333428', impacted)
        edges = {
            (str(i['producer_id']), str(i['consumer_id']))
            for i in impacts if i.get('consumer_id')
        }
        self.assertIn(('333427', '333428'), edges)
        self.assertTrue(all(i.get('origin_id') == '333427' for i in impacts
                            if i.get('consumer_id')))

    def test_multi_hop_333378_to_418(self):
        impacted, impacts = simulation.propagate_null_token(
            self.graph, ['333378'], self.index)
        self.assertIn('333417', impacted)
        self.assertIn('333418', impacted)
        edges = {
            (str(i['producer_id']), str(i['consumer_id']))
            for i in impacts if i.get('consumer_id')
        }
        self.assertIn(('333378', '333417'), edges)
        self.assertIn(('333417', '333418'), edges)
        hop2 = [
            i for i in impacts
            if str(i.get('producer_id')) == '333417'
            and str(i.get('consumer_id')) == '333418'
        ]
        self.assertEqual(len(hop2), 1)
        self.assertEqual(hop2[0].get('origin_id'), '333378')


if __name__ == '__main__':
    unittest.main()
