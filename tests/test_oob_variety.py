"""Load every wf_xml_samples_variety XML; assert OOB type coverage and smoke paths."""

import glob
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import knowledge, simulation
from cli.visualizer import WorkflowVisualizer

VARIETY_DIR = os.path.join(ROOT, 'wf_xml_samples_variety')
EMAIL_WF = os.path.join(
    VARIETY_DIR,
    'Workflow_triIntegration_triIntegrationNotification_'
    'triIntegrationNotification-SEND-CreateEmailIntegrationNotification.xml',
)


def _variety_files():
    return sorted(glob.glob(os.path.join(VARIETY_DIR, '*.xml')))


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    ok = eng.load_workflow_xml_file(path)
    if not ok:
        raise RuntimeError(f'Failed to load {path}')
    return eng, eng.loaded_workflow_names[0]


class TestVarietyIngestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = _variety_files()
        if not cls.files:
            raise unittest.SkipTest('wf_xml_samples_variety is empty or missing')

    def test_every_sample_loads(self):
        types_seen = set()
        for path in self.files:
            eng, wf = _load(path)
            g = eng.graphs[wf]
            self.assertGreater(g.number_of_nodes(), 0, path)
            for _, data in g.nodes(data=True):
                t = str(data.get('type', data.get('Type', '')))
                if t.isdigit():
                    types_seen.add(t)
        unknown = sorted(t for t in types_seen if t not in knowledge.TASK_TYPE_GLOSSARY)
        self.assertEqual(unknown, [], f'types missing from glossary: {unknown}')
        self.assertIn('27', types_seen)
        self.assertIn('10', types_seen)

    def test_every_sample_builds_searchable_html(self):
        for path in self.files:
            eng, wf = _load(path)
            html = WorkflowVisualizer(eng).build_html(wf)
            self.assertIn('id="taskSearch"', html, path)
            self.assertIn('var nodesData =', html)

    def test_every_sample_start_what_if(self):
        for path in self.files:
            eng, wf = _load(path)
            g = eng.graphs[wf]
            starts = [n for n, d in g.in_degree() if d == 0]
            self.assertTrue(starts, path)
            sid = str(starts[0])
            result = simulation.run_simulation(eng, wf, f'What if task {sid} fails?')
            self.assertEqual(result['mode'], 'what_if')
            self.assertIn('impact_tree', result)


class TestCreateAndForkSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(EMAIL_WF):
            raise unittest.SkipTest('email notification sample missing')
        cls.engine, cls.wf = _load(EMAIL_WF)

    def test_191445_is_create_type_27(self):
        data = self.engine.graphs[self.wf].nodes['191445']
        self.assertEqual(str(data.get('type')), '27')
        self.assertEqual(knowledge.type_display_name('27'), 'Create Record Task')

    def test_create_failure_impacts_modify(self):
        result = simulation.run_simulation(
            self.engine, self.wf, 'What if task 191445 fails?')
        self.assertEqual(result['failed_node_ids'], ['191445'])
        self.assertIn('191448', result['impacted_node_ids'])
        self.assertTrue(any(i.get('ref_kind') == 'create_failure' for i in result['impacts']))

    def test_fork_named(self):
        data = self.engine.graphs[self.wf].nodes['191437']
        self.assertEqual(str(data.get('type')), '10')
        self.assertEqual(data.get('name'), 'Fork')
        self.assertEqual(knowledge.type_display_name('10'), 'Fork Task')


class TestGlossaryCorrections(unittest.TestCase):
    def test_25_is_get_temp(self):
        self.assertEqual(knowledge.type_display_name('25'), 'Get Temp Record Task')

    def test_27_is_create(self):
        self.assertEqual(knowledge.type_display_name('27'), 'Create Record Task')


if __name__ == '__main__':
    unittest.main()
