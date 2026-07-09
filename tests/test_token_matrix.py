"""Regression tests: OOB type matrix, token index, and cascade integrity."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import simulation
from cli.intents import build_registry

WF_BUILDING = os.path.join(ROOT, 'wf_building_rpim_status_ind.txt')
WF_ALL = os.path.join(ROOT, 'wf_all_tasks.txt')


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


class TestTypeHints(unittest.TestCase):
    def test_create_maps_to_25(self):
        req = simulation.parse_query('what if the create task fails')
        self.assertEqual(req.clauses[0].kind, 'task_failure')
        self.assertEqual(req.clauses[0].type_hint, '25')

    def test_associate_maps_to_30(self):
        req = simulation.parse_query('what if the associate task fails')
        self.assertEqual(req.clauses[0].type_hint, '30')

    def test_delete_reference_maps_to_32(self):
        req = simulation.parse_query('what if the delete reference task fails')
        self.assertEqual(req.clauses[0].type_hint, '32')

    def test_save_permanent_maps_to_26(self):
        req = simulation.parse_query('what if the save permanent task fails')
        self.assertEqual(req.clauses[0].type_hint, '26')

    def test_add_child_maps_to_33(self):
        req = simulation.parse_query('what if the add child task fails')
        self.assertEqual(req.clauses[0].type_hint, '33')


class TestTokenConsequences(unittest.TestCase):
    def test_create_25_is_fatal_producer(self):
        msg, fatal = simulation._TOKEN_CONSEQUENCES['25']
        self.assertTrue(fatal)
        self.assertIn('temporary', msg.lower())

    def test_save_permanent_26(self):
        msg, fatal = simulation._TOKEN_CONSEQUENCES['26']
        self.assertTrue(fatal)
        self.assertIn('save', msg.lower())

    def test_associate_30(self):
        msg, fatal = simulation._TOKEN_CONSEQUENCES['30']
        self.assertTrue(fatal)
        self.assertIn('association', msg.lower())

    def test_delete_reference_32(self):
        msg, fatal = simulation._TOKEN_CONSEQUENCES['32']
        self.assertTrue(fatal)
        self.assertIn('remove', msg.lower())


class TestBuildingWorkflowRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.wf = _load(WF_BUILDING)
        cls.intents = build_registry()

    def _match_intent(self, query):
        for intent in self.intents:
            for pat in intent.compiled:
                if pat.search(query):
                    return intent.id
        return None

    def test_modify_333433_failure(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 333433 fails?')
        self.assertEqual(result['failed_node_ids'], ['333433'])
        fields = result['field_impacts'][0]['fields']
        self.assertIn('triFedStatusCL', fields)

    def test_retrieve_333448_cascade(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'what if task 333448 fails')
        self.assertEqual(result['altered_node_ids'], ['333448'])
        self.assertIn('333449', result['impacted_node_ids'])

    def test_type23_summary_includes_sections(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 333376 fails?')
        self.assertEqual(result['failed_node_ids'], ['333376'])
        summary = ' '.join(result['summary'])
        self.assertIn('UI not updated', summary)
        self.assertTrue(
            'triGovUSFedDisposition02' in summary or 'triRecipient02' in summary,
            summary,
        )

    def test_token_index_keeps_nonzero_refs(self):
        idx = simulation.build_token_index(self.engine.graphs[self.wf])
        consumers = [c for c, _ in idx.get('333448', [])]
        self.assertIn('333449', consumers)

    def test_conditional_trace_intent(self):
        self.assertEqual(
            self._match_intent('what happens when triRPAOperationalStatusCodeCL is DISP'),
            'conditional_trace',
        )


class TestAllTasksTokenIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(WF_ALL):
            raise unittest.SkipTest('wf_all_tasks.txt not present')
        cls.engine, cls.wf = _load(WF_ALL)

    def test_create_to_save_permanent_edge(self):
        graph = self.engine.graphs[self.wf]
        self.assertTrue(graph.has_node('330894'))
        self.assertTrue(graph.has_node('330923'))
        data = graph.nodes['330923']
        from_tasks = [str(x) for x in (data.get('FromTask') or [])]
        self.assertIn('330894', from_tasks)
        idx = simulation.build_token_index(graph)
        consumers = [c for c, _ in idx.get('330894', [])]
        self.assertIn('330923', consumers)

    def test_create_failure_propagates_to_save(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What happens if task 330894 fails?')
        self.assertEqual(result['failed_node_ids'], ['330894'])
        self.assertIn('330923', result['impacted_node_ids'])
        sentences = ' '.join(i['sentence'] for i in result['impacts'])
        self.assertIn('temporary', sentences.lower())

    def test_ref_task_id_zero_indexed(self):
        graph = self.engine.graphs[self.wf]
        # At least one task should retain FromTask/FilterTask pointing at Start "0".
        has_zero = False
        for _, data in graph.nodes(data=True):
            for key in ('FromTask', 'FilterTask', 'AuxTask'):
                refs = data.get(key) or []
                if any(str(r) == '0' for r in refs):
                    has_zero = True
                    break
            if has_zero:
                break
        self.assertTrue(has_zero, 'Expected RefTaskId=0 to be retained on at least one task')
        idx = simulation.build_token_index(graph)
        self.assertIn('0', idx)


if __name__ == '__main__':
    unittest.main(verbosity=2)
