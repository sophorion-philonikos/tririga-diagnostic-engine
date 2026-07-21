"""Tests for multi-workflow sessions and /api/analyze helpers."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from web import server as web_server
from cli import analysis_api
from cli import simulation
from core.engine import TririgaHybridEngine

NOTIFICATION = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml',
)
FISCAL = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triPatchHelper_cst-triPatchHelper-triCalculate-UtilityWFUpdateFiscalMonths.xml',
)
BUILDING = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_Location_triBuilding_triBuilding-Synchronous-PermanentSaveValidation.xml',
)
VARIETY_ZIP = os.path.join(ROOT, 'WF_Variety_XML.zip')


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


@unittest.skipUnless(os.path.isfile(NOTIFICATION) and os.path.isfile(FISCAL), 'samples missing')
class TestMultiWorkflowSession(unittest.TestCase):
    def test_visualize_builds_per_wf_bundles(self):
        result = web_server.process_visualization_request([
            ('notification.xml', _read(NOTIFICATION)),
            ('fiscal.xml', _read(FISCAL)),
        ])
        self.assertEqual(len(result['detected_workflows']), 2)
        sid = result['session_id']
        with web_server._session_lock:
            sess = web_server._sessions[sid]
        self.assertIn('workflows', sess)
        self.assertEqual(len(sess['workflows']), 2)
        self.assertEqual(sess['active_workflow'], result['workflow'])
        # Only active map is eager
        mapped = sum(1 for b in sess['workflows'].values() if b.get('map_html'))
        self.assertEqual(mapped, 1)
        self.assertTrue(sess['map_html'])

    def test_switch_lazy_builds_map_and_mirrors(self):
        result = web_server.process_visualization_request([
            ('notification.xml', _read(NOTIFICATION)),
            ('fiscal.xml', _read(FISCAL)),
            ('building.xml', _read(BUILDING)),
        ])
        sid = result['session_id']
        other = next(
            d['workflow'] for d in result['detected_workflows']
            if d['workflow'] != result['workflow']
        )
        sw = web_server.switch_workflow(sid, other)
        self.assertEqual(sw['workflow'], other)
        self.assertTrue(sw['map_url'].startswith('/api/map/'))
        with web_server._session_lock:
            sess = web_server._sessions[sid]
            self.assertEqual(sess['active_workflow'], other)
            self.assertEqual(sess['workflow'], other)
            self.assertIsNotNone(sess['workflows'][other]['map_html'])
            self.assertEqual(sess['map_html'], sess['workflows'][other]['map_html'])

    def test_last_sim_persists_per_workflow(self):
        result = web_server.process_visualization_request([
            ('notification.xml', _read(NOTIFICATION)),
            ('fiscal.xml', _read(FISCAL)),
        ])
        sid = result['session_id']
        primary = result['workflow']
        other = next(
            d['workflow'] for d in result['detected_workflows']
            if d['workflow'] != primary
        )
        with web_server._session_lock:
            sess = web_server._sessions[sid]
        sim = simulation.run_simulation(
            sess['engine'], primary, 'what if switch is FALSE',
            trace_ids=sess['trace_ids'],
        )
        with web_server._session_lock:
            sess['workflows'][primary]['last_sim'] = sim
        web_server.switch_workflow(sid, other)
        back = web_server.switch_workflow(sid, primary)
        self.assertIsNotNone(back.get('last_sim'))
        self.assertEqual(back['last_sim'].get('mode'), sim.get('mode'))

    def test_switch_unknown_raises(self):
        result = web_server.process_visualization_request([
            ('notification.xml', _read(NOTIFICATION)),
        ])
        with self.assertRaises(ValueError):
            web_server.switch_workflow(result['session_id'], 'not-a-real-workflow')


@unittest.skipUnless(os.path.isfile(VARIETY_ZIP), 'variety zip missing')
class TestOmPackageMultiWf(unittest.TestCase):
    def test_zip_loads_multiple_and_switch(self):
        result = web_server.process_visualization_request([
            ('variety.zip', _read(VARIETY_ZIP)),
        ])
        self.assertGreaterEqual(len(result['detected_workflows']), 2)
        sid = result['session_id']
        other = next(
            d['workflow'] for d in result['detected_workflows']
            if d['workflow'] != result['workflow']
        )
        sw = web_server.switch_workflow(sid, other)
        self.assertEqual(sw['workflow'], other)


@unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
class TestAnalysisApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        cls.eng.load_workflow_xml_file(NOTIFICATION)
        cls.wf = cls.eng.loaded_workflow_names[0]
        from cli.router import TririgaNLPRouter
        cls.router = TririgaNLPRouter(cls.eng, offline_mode=True)
        cls.router.current_context_wf = cls.wf
        g = cls.eng.graphs[cls.wf]
        cls.node_id = next(iter(g.nodes()))

    def test_explain_task(self):
        out = analysis_api.run_analyze(
            self.router, self.wf, 'explain_task', {'task': str(self.node_id)})
        self.assertEqual(out['op'], 'explain_task')
        self.assertIn('html', out)
        self.assertIn('text', out)
        self.assertEqual(str(out['task_id']), str(self.node_id))

    def test_purpose(self):
        out = analysis_api.run_analyze(
            self.router, self.wf, 'purpose', {'path_limit': 2})
        self.assertEqual(out['op'], 'purpose')
        self.assertIn('summary', out)
        self.assertLessEqual(out['paths_returned'], 2)

    def test_orphans(self):
        out = analysis_api.run_analyze(self.router, self.wf, 'orphans', {})
        self.assertEqual(out['op'], 'orphans')
        self.assertIn('orphans', out)
        self.assertIn('healthy', out)

    def test_refs(self):
        out = analysis_api.run_analyze(
            self.router, self.wf, 'refs', {'term': 'triName'})
        self.assertEqual(out['op'], 'refs')
        self.assertIn('hits', out)

    def test_path_and_failure(self):
        g = self.eng.graphs[self.wf]
        nodes = list(g.nodes())
        start, end = nodes[0], nodes[min(3, len(nodes) - 1)]
        try:
            path = analysis_api.run_analyze(
                self.router, self.wf, 'path',
                {'from': str(start), 'to': str(end)})
            self.assertEqual(path['op'], 'path')
            self.assertGreaterEqual(path['length'], 1)
        except ValueError:
            # No directed path between arbitrary pair — still valid
            pass
        fail = analysis_api.run_analyze(
            self.router, self.wf, 'failure', {'task': str(self.node_id)})
        self.assertEqual(fail['op'], 'failure')
        self.assertIn('summary', fail)

    def test_unknown_op(self):
        with self.assertRaises(ValueError):
            analysis_api.run_analyze(self.router, self.wf, 'nope', {})


@unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
class TestAnalyzeViaVisualizeSession(unittest.TestCase):
    def test_analyze_against_session_router(self):
        result = web_server.process_visualization_request([
            ('notification.xml', _read(NOTIFICATION)),
        ])
        sid = result['session_id']
        with web_server._session_lock:
            sess = web_server._sessions[sid]
        out = analysis_api.run_analyze(
            sess['router'], sess['active_workflow'], 'purpose', {'path_limit': 1})
        self.assertEqual(out['workflow'], sess['active_workflow'])


if __name__ == '__main__':
    unittest.main()
