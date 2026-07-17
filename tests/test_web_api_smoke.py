"""Web API smoke + roadmap regression hooks."""

import io
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from web import server as web_server
from cli.visualizer import WorkflowVisualizer
from core.engine import TririgaHybridEngine

NOTIFICATION = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml',
)
FISCAL = os.path.join(
    ROOT, 'wf_xml_samples_variety',
    'Workflow_triHelper_triPatchHelper_cst-triPatchHelper-triCalculate-UtilityWFUpdateFiscalMonths.xml',
)


@unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
class TestWebVisualizeSmoke(unittest.TestCase):
    def test_visualize_returns_session_and_map_url(self):
        with open(NOTIFICATION, 'rb') as f:
            data = f.read()
        result = web_server.process_visualization_request([
            ('notification.xml', data),
        ])
        self.assertIn('session_id', result)
        self.assertTrue(result['session_id'])
        self.assertTrue(result['map_url'].startswith('/api/map/'))
        self.assertIsNone(result.get('map_html'))
        self.assertIn('sim_chips', result)
        self.assertTrue(isinstance(result['sim_chips'], list))
        sid = result['session_id']
        with web_server._session_lock:
            sess = web_server._sessions.get(sid)
        self.assertIsNotNone(sess)
        self.assertIn('map_html', sess)
        self.assertIn('assertAcyclicParents', sess['map_html'])
        self.assertIn('viz-error-banner', sess['map_html'])
        self.assertIn('modeStrip', sess['map_html'])
        self.assertIn('d3@5.16.0', sess['map_html'])
        self.assertIn('dagre-d3@0.6.4', sess['map_html'])
        self.assertIn('var payloadsData =', sess['map_html'])
        self.assertNotIn('GRAPH_PAYLOADS_DATA_PLACEHOLDER', sess['map_html'])


@unittest.skipUnless(os.path.isfile(FISCAL), 'fiscal sample missing')
class TestWebFiscalSmoke(unittest.TestCase):
    def test_fiscal_visualize_ok(self):
        with open(FISCAL, 'rb') as f:
            data = f.read()
        result = web_server.process_visualization_request([
            ('fiscal.xml', data),
        ])
        self.assertTrue(result['session_id'])
        with web_server._session_lock:
            html = web_server._sessions[result['session_id']]['map_html']
        self.assertIn('btnPathHere', html)
        self.assertIn('Copy deep link', html)
        self.assertIn('assertAcyclicParents', html)
        self.assertIn('c_332552', html)


class TestPayloadsSeparated(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(NOTIFICATION), 'notification sample missing')
    def test_nodes_omit_custom_payload_key(self):
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        eng.load_workflow_xml_file(NOTIFICATION)
        wf = eng.loaded_workflow_names[0]
        html = WorkflowVisualizer(eng).build_html(wf)
        marker = 'var nodesData = '
        idx = html.find(marker)
        nodes, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
        for n in nodes[:20]:
            self.assertNotIn('customPayload', n)


if __name__ == '__main__':
    unittest.main()
