"""Regression: scoped field impacts + path-to-failed-task highlighting."""

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


class TestScopedImpacts333428(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()

    def test_failed_id(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333428 fails?')
        self.assertEqual(result['failed_node_ids'], ['333428'])

    def test_no_peer_modify_field_noise(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333428 fails?')
        peers = {'333464', '333471', '333547', '333459', '333377'}
        consumers = {
            i['consumer_id'] for i in result['impacts']
            if i.get('ref_kind') == 'field_reference'
        }
        self.assertFalse(peers & consumers, consumers)

    def test_no_token_starvation_without_consumers(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333428 fails?')
        self.assertEqual(result['impacted_node_ids'], [])

    def test_path_reaches_failed_task(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333428 fails?')
        path = set(result['path_node_ids'])
        self.assertIn('333428', path)
        self.assertIn('333427', path)
        self.assertIn('333424', path)

    def test_field_ledger_present(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333428 fails?')
        ledgers = [i for i in result['impacts'] if i.get('ref_kind') == 'field_ledger']
        self.assertEqual(len(ledgers), 1)
        self.assertIn('triFedStatusCL', ledgers[0]['sentence'])


class TestRetrieveFailure333427(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()

    def test_altered_and_cascade(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333427 fails?')
        self.assertEqual(result['altered_node_ids'], ['333427'])
        self.assertEqual(result['failed_node_ids'], [])
        self.assertIn('333428', result['impacted_node_ids'])

    def test_path_reaches_retrieve(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333427 fails?')
        path = set(result['path_node_ids'])
        self.assertIn('333427', path)
        self.assertIn('333424', path)

    def test_single_cascade_sentence(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 333427 fails?')
        cascade = [
            i['sentence'] for i in result['impacts']
            if '333427' in i['sentence'] and '333428' in i['sentence']
        ]
        self.assertEqual(len(cascade), 1, cascade)
        # Summary must not reprint the same cascade sentence twice.
        summary_hits = [s for s in result['summary'] if '333427' in s and '333428' in s
                        and 'source record token' in s]
        self.assertEqual(len(summary_hits), 1, summary_hits)


class TestScopedRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load()

    def test_retrieve_cascade_unchanged(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'what if task 333448 fails')
        self.assertEqual(result['altered_node_ids'], ['333448'])
        self.assertIn('333449', result['impacted_node_ids'])
        cascade = [
            i['sentence'] for i in result['impacts']
            if '333448' in i['sentence'] and '333449' in i['sentence']
        ]
        self.assertEqual(len(cascade), 1, cascade)
        path = set(result['path_node_ids'])
        self.assertIn('333448', path)

    def test_data_state_retrieve_cascades_once(self):
        result = simulation.run_simulation(
            self.engine, self.wf,
            'What if the retrieve task "Get \'Report of Excess Accepted\' FedStatus" '
            'does not retrieve any records?')
        self.assertEqual(result['altered_node_ids'], ['333448'])
        self.assertIn('333449', result['impacted_node_ids'])
        cascade = [
            i['sentence'] for i in result['impacts']
            if '333448' in i['sentence'] and '333449' in i['sentence']
        ]
        self.assertEqual(len(cascade), 1, cascade)

    def test_modify_333433_ledger(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 333433 fails?')
        self.assertEqual(result['failed_node_ids'], ['333433'])
        self.assertTrue(result['field_impacts'])
        fields = result['field_impacts'][0]['fields']
        self.assertIn('triFedStatusCL', fields)
        # Peer writers must not appear as field_reference consumers.
        consumers = {
            i['consumer_id'] for i in result['impacts']
            if i.get('ref_kind') == 'field_reference'
        }
        self.assertNotIn('333464', consumers)
        self.assertNotIn('333547', consumers)


if __name__ == '__main__':
    unittest.main(verbosity=2)
