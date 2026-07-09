"""Impact tree nesting for multi-hop token starvation (e.g. 333378)."""

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


def _find_child(node, task_id):
    tid = str(task_id)
    for child in node.get('children') or []:
        if str(child.get('task_id')) == tid:
            return child
    return None


def _direct_child_ids(node):
    return {str(c['task_id']) for c in (node.get('children') or [])}


class TestImpactTree333378(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()
        cls.result = simulation.run_simulation(
            cls.engine, cls.wf, 'What if task 333378 fails?')

    def test_root_is_333378(self):
        tree = self.result['impact_tree']
        self.assertTrue(tree, 'impact_tree should be non-empty')
        self.assertEqual(tree[0]['task_id'], '333378')

    def test_333417_nests_333418(self):
        root = self.result['impact_tree'][0]
        r417 = _find_child(root, '333417')
        self.assertIsNotNone(r417, '333417 should be a direct child of 333378')
        m418 = _find_child(r417, '333418')
        self.assertIsNotNone(m418, '333418 should nest under 333417')

    def test_333418_not_direct_child_of_root(self):
        root = self.result['impact_tree'][0]
        self.assertNotIn('333418', _direct_child_ids(root))

    def test_333384_nests_333402_nests_333405(self):
        root = self.result['impact_tree'][0]
        r384 = _find_child(root, '333384')
        self.assertIsNotNone(r384, '333384 should be a direct child of 333378')
        r402 = _find_child(r384, '333402')
        self.assertIsNotNone(r402, '333402 should nest under 333384')
        m405 = _find_child(r402, '333405')
        self.assertIsNotNone(m405, '333405 should nest under 333402')

    def test_flat_impacts_dedupe_intact(self):
        impacts = self.result['impacts']
        edges = {
            (str(i.get('producer_id')), str(i.get('consumer_id')))
            for i in impacts
            if i.get('consumer_id')
        }
        self.assertIn(('333378', '333417'), edges)
        self.assertIn(('333417', '333418'), edges)
        sentences_417 = [
            i['sentence'] for i in impacts
            if str(i.get('producer_id')) == '333378'
            and str(i.get('consumer_id')) == '333417'
        ]
        sentences_418 = [
            i['sentence'] for i in impacts
            if str(i.get('producer_id')) == '333417'
            and str(i.get('consumer_id')) == '333418'
        ]
        self.assertEqual(len(sentences_417), 1)
        self.assertEqual(len(sentences_418), 1)


class TestImpactTreeRegression333427(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()

    def test_path_and_single_cascade(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333427 fails?')
        self.assertIn('333427', result['path_node_ids'])
        self.assertIn('333428', result['impacted_node_ids'])
        cascades = [
            i for i in result['impacts']
            if str(i.get('producer_id')) == '333427'
            and str(i.get('consumer_id')) == '333428'
        ]
        self.assertEqual(len(cascades), 1)
        tree = result.get('impact_tree') or []
        self.assertTrue(tree)
        self.assertEqual(tree[0]['task_id'], '333427')
        self.assertIsNotNone(_find_child(tree[0], '333428'))


if __name__ == '__main__':
    unittest.main()
