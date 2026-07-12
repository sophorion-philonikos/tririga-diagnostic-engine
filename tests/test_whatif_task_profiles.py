"""What-If simulator coverage across OOB task types in wf_all_tasks + variety."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import knowledge, simulation
from cli.knowledge import type_display_name

WF_ALL = os.path.join(ROOT, 'wf_all_tasks.txt')
VARIETY_DIR = os.path.join(ROOT, 'wf_xml_samples_variety')
EMAIL_WF = os.path.join(
    VARIETY_DIR,
    'Workflow_triIntegration_triIntegrationNotification_'
    'triIntegrationNotification-SEND-CreateEmailIntegrationNotification.xml',
)
BUILDING_SAVE = os.path.join(
    VARIETY_DIR,
    'Workflow_Location_triBuilding_triBuilding-Synchronous-PermanentSaveValidation.xml',
)


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


# Representative tasks from cstCustomWorkflowBaseline (wf_all_tasks.txt)
_ALL_TASKS = [
    ('14', '330920', 'Switch'),
    ('17', '330908', 'Schedule'),
    ('20', '330911', 'Loop'),
    ('21', '330910', 'Break'),
    ('22', '330907', 'Query'),
    ('23', '330915', 'Modify Metadata'),
    ('24', '330916', 'Iter'),
    ('25', '330894', 'Get Temp'),
    ('26', '330923', 'Save Permanent'),
    ('28', '330895', 'Modify Records'),
    ('29', '330897', 'Retrieve'),
    ('30', '330901', 'Associate'),
    ('31', '330902', 'Trigger Action'),
    ('32', '330903', 'Delete Reference'),
    ('33', '330904', 'Add Child'),
    ('34', '330905', 'Set Project'),
    ('35', '330906', 'Attach Format File'),
    ('36', '330909', 'Populate File'),
    ('37', '330913', 'Distill File'),
    ('38', '330924', 'Call Workflow'),
    ('39', '330930', 'Custom'),
    ('40', '330931', 'Variable Definition'),
    ('41', '330932', 'Variable Assignment'),
    ('43', '330933', 'Fact Condition'),
]


class TestWhatIfAllTasksBaseline(unittest.TestCase):
    """Run What-If failure against every major OOB type in the baseline WF."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(WF_ALL):
            raise unittest.SkipTest('wf_all_tasks.txt missing')
        cls.engine, cls.wf = _load(WF_ALL)

    def test_each_type_what_if_runs(self):
        for type_code, task_id, label in _ALL_TASKS:
            with self.subTest(type=type_code, task=task_id, label=label):
                data = self.engine.graphs[self.wf].nodes[task_id]
                self.assertEqual(str(data.get('type')), type_code)
                result = simulation.run_simulation(
                    self.engine, self.wf, f'What if task {task_id} fails?')
                self.assertEqual(result['mode'], 'what_if')
                # Matched as failed or altered (Retrieve/Query/Iter-style) or at least ran
                matched = (
                    task_id in result.get('failed_node_ids', [])
                    or task_id in result.get('altered_node_ids', [])
                )
                self.assertTrue(
                    matched or result.get('impacts') is not None,
                    f'{label} ({task_id}) produced no simulation payload',
                )
                display = type_display_name(type_code)
                self.assertNotEqual(display, f'Type {type_code}')
                blob = ' '.join(result.get('summary', []))
                self.assertTrue(blob)

    def test_get_temp_starves_save_permanent(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 330894 fails?')
        self.assertEqual(result['failed_node_ids'], ['330894'])
        self.assertIn('330923', result['impacted_node_ids'])

    def test_iter_failure_profile(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 330916 fails?')
        self.assertTrue(
            '330916' in result['failed_node_ids']
            or '330916' in result['altered_node_ids']
        )

    def test_associate_failure_profile(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 330901 fails?')
        self.assertIn('330901', result['failed_node_ids'])

    def test_trigger_action_failure_profile(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 330902 fails?')
        self.assertIn('330902', result['failed_node_ids'])

    def test_variable_definition_failure_runs(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 330931 fails?')
        self.assertEqual(result['mode'], 'what_if')
        self.assertTrue(result['summary'])


class TestWhatIfCreateAndForkVariety(unittest.TestCase):
    def test_create_record_cascade(self):
        if not os.path.isfile(EMAIL_WF):
            self.skipTest('email sample missing')
        eng, wf = _load(EMAIL_WF)
        result = simulation.run_simulation(eng, wf, 'What if task 191445 fails?')
        self.assertEqual(result['failed_node_ids'], ['191445'])
        self.assertIn('191448', result['impacted_node_ids'])
        self.assertIn('Create Record', type_display_name('27'))

    def test_create_helper_in_building_save(self):
        if not os.path.isfile(BUILDING_SAVE):
            self.skipTest('building save sample missing')
        eng, wf = _load(BUILDING_SAVE)
        data = eng.graphs[wf].nodes['330593']
        self.assertEqual(str(data.get('type')), '27')
        result = simulation.run_simulation(eng, wf, 'What if task 330593 fails?')
        self.assertIn('330593', result['failed_node_ids'])
        self.assertTrue(any(i.get('ref_kind') == 'create_failure' for i in result['impacts']))

    def test_fork_what_if(self):
        if not os.path.isfile(EMAIL_WF):
            self.skipTest('email sample missing')
        eng, wf = _load(EMAIL_WF)
        result = simulation.run_simulation(eng, wf, 'What if task 191437 fails?')
        self.assertEqual(result['mode'], 'what_if')
        self.assertEqual(eng.graphs[wf].nodes['191437'].get('name'), 'Fork')


class TestTypeHintPhrases(unittest.TestCase):
    def test_phrases(self):
        cases = [
            ('what if the create record task fails', '27'),
            ('what if the get temp record task fails', '25'),
            ('what if the iter task fails', '24'),
            ('what if the associate records task fails', '30'),
            ('what if the trigger action task fails', '31'),
            ('what if the call workflow task fails', '38'),
            ('what if the fork task fails', '10'),
            ('what if the variable definition task fails', '40'),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                req = simulation.parse_query(query)
                self.assertTrue(req.clauses)
                self.assertEqual(req.clauses[0].type_hint, expected)


if __name__ == '__main__':
    unittest.main()
