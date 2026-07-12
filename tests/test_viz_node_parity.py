"""Assert visible graph nodes are injected into viewer nodesData (no silent drops)."""

import glob
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from cli import graph_utils
from cli.visualizer import WorkflowVisualizer

VARIETY_DIR = os.path.join(ROOT, 'wf_xml_samples_variety')
GEOCODE = os.path.join(
    VARIETY_DIR, 'Workflow_Location__Location-Synchronous-GeocodeAddress.xml')
LEASE = os.path.join(
    VARIETY_DIR,
    'Workflow_Location_triBuilding_cst-triBuilding-Synchronous-OnchangeLeaseAuthority.xml',
)


def _load(path):
    eng = TririgaHybridEngine(None, None, None, offline_mode=True)
    eng.load_workflow_xml_file(path)
    return eng, eng.loaded_workflow_names[0]


def _nodes_data(html):
    marker = 'var nodesData = '
    idx = html.find(marker)
    if idx < 0:
        raise AssertionError('nodesData missing from HTML')
    data, _ = json.JSONDecoder().raw_decode(html[idx + len(marker):])
    return data


def _expected_visible_ids(graph):
    """Match visualizer.build_html skip: invisible with out-edges are omitted."""
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        out.append(str(nid))
    return out


class TestSwitchNodesRestored(unittest.TestCase):
    def test_geocode_switch_383577_in_canvas(self):
        if not os.path.isfile(GEOCODE):
            self.skipTest('GeocodeAddress sample missing')
        eng, wf = _load(GEOCODE)
        data = eng.graphs[wf].nodes['383577']
        self.assertEqual(str(data.get('type')), '14')
        self.assertFalse(graph_utils.is_invisible(data))
        self.assertEqual(data.get('name'), 'Switch')
        html = WorkflowVisualizer(eng).build_html(wf)
        nodes = _nodes_data(html)
        by_id = {n['id']: n for n in nodes}
        self.assertIn('383577', by_id)
        self.assertEqual(str(by_id['383577'].get('type')), '14')

    def test_lease_switch_214152_in_canvas(self):
        if not os.path.isfile(LEASE):
            self.skipTest('LeaseAuthority sample missing')
        eng, wf = _load(LEASE)
        data = eng.graphs[wf].nodes['214152']
        self.assertEqual(str(data.get('type')), '14')
        self.assertFalse(graph_utils.is_invisible(data))
        self.assertEqual(data.get('name'), 'Switch')
        html = WorkflowVisualizer(eng).build_html(wf)
        nodes = _nodes_data(html)
        self.assertIn('214152', {n['id'] for n in nodes})


class TestVarietyNodeParity(unittest.TestCase):
    def test_every_sample_nodesdata_matches_visible_graph(self):
        files = sorted(glob.glob(os.path.join(VARIETY_DIR, '*.xml')))
        if not files:
            self.skipTest('wf_xml_samples_variety empty')
        for path in files:
            with self.subTest(file=os.path.basename(path)):
                eng, wf = _load(path)
                graph = eng.graphs[wf]
                expected = set(_expected_visible_ids(graph))
                html = WorkflowVisualizer(eng).build_html(wf)
                actual = {n['id'] for n in _nodes_data(html)}
                self.assertEqual(
                    actual, expected,
                    f'missing={sorted(expected - actual)[:10]} '
                    f'extra={sorted(actual - expected)[:10]}')

    def test_junctions_still_hidden(self):
        files = sorted(glob.glob(os.path.join(VARIETY_DIR, '*.xml')))
        if not files:
            self.skipTest('wf_xml_samples_variety empty')
        for path in files:
            eng, wf = _load(path)
            html = WorkflowVisualizer(eng).build_html(wf)
            nodes = _nodes_data(html)
            for n in nodes:
                self.assertNotIn(str(n.get('type')), ('11', '12'), n)


class TestIsInvisibleRule(unittest.TestCase):
    def test_unnamed_switch_visible(self):
        self.assertFalse(graph_utils.is_invisible({
            'type': '14', 'name': 'Unnamed Component (1)'}))

    def test_junction_invisible(self):
        self.assertTrue(graph_utils.is_invisible({'type': '12', 'name': 'x'}))
        self.assertTrue(graph_utils.is_invisible({'type': '11', 'name': 'x'}))

    def test_generic_invisible(self):
        self.assertTrue(graph_utils.is_invisible({'type': 'Generic', 'name': 'x'}))

    def test_default_task_names(self):
        self.assertEqual(graph_utils.default_task_name('14', '1'), 'Switch')
        self.assertEqual(graph_utils.default_task_name('19', '1'), 'Continue')
        self.assertEqual(graph_utils.default_task_name('21', '1'), 'Break')
        self.assertEqual(graph_utils.default_task_name('13', '1'), 'Stop')


class TestIterAndCreateShapes(unittest.TestCase):
    def test_iter_svg_is_switch_scalene(self):
        from cli.visualizer import WorkflowVisualizer
        viz = WorkflowVisualizer(None)
        uri, _, _ = viz._build_svg_node('Iter Task', '24', 'BO', {}, False, False)
        import base64
        raw = base64.b64decode(uri.split(',', 1)[1]).decode('utf-8')
        self.assertIn('<polygon points=', raw)
        self.assertIn('fill="#00b0f0"', raw)

    def test_create_svg_uses_tan_fill(self):
        from cli.visualizer import WorkflowVisualizer
        viz = WorkflowVisualizer(None)
        uri, _, _ = viz._build_svg_node('Create X', '27', 'BO', {}, False, False)
        import base64
        raw = base64.b64decode(uri.split(',', 1)[1]).decode('utf-8')
        self.assertIn('#c4a574', raw)


if __name__ == '__main__':
    unittest.main()
