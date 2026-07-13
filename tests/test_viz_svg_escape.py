"""SVG node labels must be XML-safe or browsers show broken <img> tiles."""
import base64
import os
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli.visualizer import WorkflowVisualizer, _svg_text

CAPITAL = os.path.join(
    ROOT,
    'wf_xml_samples_variety',
    'Workflow_triProject_triCapitalProject_'
    'triCapitalProject-Synchronous-PermanentSaveValidation.xml',
)


def _decode_svg(uri: str) -> str:
    return base64.b64decode(uri.split(',', 1)[1]).decode('utf-8')


def _assert_valid_svg(xml_str: str):
    ET.fromstring(xml_str)


class TestSvgTextEscape(unittest.TestCase):
    def test_ampersand_escaped(self):
        self.assertEqual(_svg_text('Bid & Construction'), 'Bid &amp; Construction')

    def test_less_than_escaped(self):
        self.assertEqual(_svg_text('a < b'), 'a &lt; b')

    def test_type38_ampersand_name_parses(self):
        viz = WorkflowVisualizer(None)
        uri, _, _ = viz._build_svg_node(
            'Call OnChange Bid & Construction', '38', 'triCapitalProject', {}, False, False,
        )
        raw = _decode_svg(uri)
        self.assertIn('&amp;', raw)
        self.assertNotIn('Bid & Construction', raw)
        _assert_valid_svg(raw)


@unittest.skipUnless(os.path.isfile(CAPITAL), 'triCapitalProject sample missing')
class TestCapitalProjectCallWorkflowTiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        eng.load_workflow_xml_file(CAPITAL)
        cls.wf = eng.loaded_workflow_names[0]
        cls.viz = WorkflowVisualizer(eng)
        cls.graph = eng.graphs[cls.wf]

    def test_all_type38_nodes_produce_valid_svg(self):
        failures = []
        for nid, data in self.graph.nodes(data=True):
            if str(data.get('type')) != '38':
                continue
            name = data.get('name', '')
            bo = data.get('BO', data.get('BoName', 'Context BO'))
            if isinstance(bo, list):
                bo = bo[0]
            try:
                uri, _, _ = self.viz._build_svg_node(name, '38', bo, data, False, False)
                _assert_valid_svg(_decode_svg(uri))
            except Exception as exc:
                failures.append(f"{nid} '{name}': {exc}")
        self.assertEqual(failures, [], failures)

    def test_task_331510_specifically(self):
        data = self.graph.nodes['331510']
        self.assertIn('&', data['name'])
        uri, _, _ = self.viz._build_svg_node(
            data['name'], '38', 'triCapitalProject', data, False, False,
        )
        raw = _decode_svg(uri)
        _assert_valid_svg(raw)
        self.assertIn('&amp;', raw)
        self.assertNotRegex(raw, r'Bid &[^a]')


if __name__ == '__main__':
    unittest.main()
