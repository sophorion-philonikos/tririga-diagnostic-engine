"""Regression tests: Type 23 GUIMapping unpack fix and metadata failure simulation."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli.router import TririgaNLPRouter
from cli import simulation
from cli.intents import build_registry

WF_FILE = os.path.join(ROOT, 'wf_building_rpim_status_ind.txt')


def _load_router():
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(WF_FILE)
    router = TririgaNLPRouter(eng, offline_mode=True)
    router.current_context_wf = eng.loaded_workflow_names[0]
    return router, eng


class TestType23RouterExplain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router, cls.engine = _load_router()
        cls.wf = cls.engine.loaded_workflow_names[0]

    def test_explain_task_347466_no_crash(self):
        out = self.router.process_query('Explain task 347466')
        self.assertIsInstance(out, str)
        self.assertIn('Modify Metadata', out)

    def test_explain_task_333376_no_crash(self):
        out = self.router.process_query('Explain task 333376')
        self.assertIsInstance(out, str)
        self.assertIn('Modify Metadata', out)
        self.assertTrue(
            'triRPIM' in out or 'triGovUSFedDisposition02' in out or 'triRecipient02' in out,
            'Expected tab/section metadata in explain output',
        )


class TestType23FailureSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router, cls.engine = _load_router()
        cls.wf = cls.engine.loaded_workflow_names[0]

    def test_task_333376_failure_metadata_ledger(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 333376 fails?')
        self.assertEqual(result['failed_node_ids'], ['333376'])
        self.assertFalse(result['unmatched_phrases'])
        ledger_impacts = [i for i in result['impacts'] if i.get('ref_kind') == 'metadata_ledger']
        self.assertTrue(ledger_impacts)
        sentence = ledger_impacts[0]['sentence']
        self.assertIn('333376', sentence)
        self.assertTrue(
            'triGovUSFedDisposition02' in sentence or 'triRecipient02' in sentence,
            sentence,
        )

    def test_extract_metadata_ledger(self):
        data = self.engine.graphs[self.wf].nodes['333376']
        ledger = simulation.extract_metadata_ledger(data)
        self.assertIn('triRPIM', ledger['tabs'])
        self.assertTrue(
            'triGovUSFedDisposition02' in ledger['sections']
            or 'triRecipient02' in ledger['sections'],
        )
        self.assertEqual(ledger['bo'], 'triBuilding')


class TestFailureRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router, cls.engine = _load_router()
        cls.wf = cls.engine.loaded_workflow_names[0]
        cls.intents = build_registry()

    def _match_intent(self, query):
        for intent in self.intents:
            for pat in intent.compiled:
                if pat.search(query):
                    return intent.id
        return None

    def test_modify_records_failure_333433(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 333433 fails?')
        self.assertEqual(result['failed_node_ids'], ['333433'])
        fields = result['field_impacts'][0]['fields']
        self.assertIn('triFedStatusCL', fields)
        self.assertIn('triFedStatusIDTX', fields)

    def test_retrieve_failure_333448_cascade(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'what if task 333448 fails')
        self.assertEqual(result['altered_node_ids'], ['333448'])
        self.assertIn('333449', result['impacted_node_ids'])

    def test_conditional_trace_intent_unchanged(self):
        intent = self._match_intent('what happens when triRPAOperationalStatusCodeCL is DISP')
        self.assertEqual(intent, 'conditional_trace')

    def test_simulate_intent_for_task_failure(self):
        intent = self._match_intent('What happens if task 333433 fails?')
        self.assertEqual(intent, 'simulate')


if __name__ == '__main__':
    unittest.main(verbosity=2)
