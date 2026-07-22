"""Tests for om_gen OM zip generator + generator web API helpers."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from om_gen.build import build_from_ir, build_from_nl, build_from_recipe, minimal_start_end_ir
from om_gen.emit_workflow import emit_workflow_xml, ir_to_preview_graph
from om_gen.nl_recipe import nl_to_recipe
from om_gen.parse_recipe import load_recipe_file, recipe_to_ir
from om_gen.validate import ValidationError, validate_ir
from web import server as web_server


class TestOmGenMinimal(unittest.TestCase):
    def test_minimal_zip_flat_and_loads(self):
        ir = minimal_start_end_ir()
        data = build_from_ir(ir)
        self.assertIsInstance(data, (bytes, bytearray))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            self.assertIn('AllObjects.xml', names)
            self.assertTrue(any(n.startswith('Workflow_') for n in names))
            self.assertTrue(any(n.startswith('ObjectLabel_') for n in names))
            for n in names:
                self.assertNotIn('/', n)
                self.assertNotIn('\\', n)
            wf = [n for n in names if n.startswith('Workflow_')][0]
            xml = zf.read(wf).decode('utf-8')
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        self.assertTrue(eng.load_workflow_xml_string(xml, source_label='om_gen_minimal'))
        self.assertEqual(len(eng.graphs), 1)


class TestOmGenDemoModify(unittest.TestCase):
    def test_demo_recipe(self):
        recipe_path = os.path.join(ROOT, 'om_gen', 'examples', 'demo_modify.json')
        recipe = load_recipe_file(recipe_path)
        data = build_from_recipe(recipe)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            wf = [n for n in zf.namelist() if n.startswith('Workflow_')][0]
            xml = zf.read(wf).decode('utf-8')
        self.assertIn('triNameTX', xml)
        self.assertIn('Append', xml)
        self.assertIn('ObjMappings', xml)
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        self.assertTrue(eng.load_workflow_xml_string(xml, source_label='demo'))


class TestOmGenCoreTypes(unittest.TestCase):
    def test_all_core_types_emit(self):
        recipe_path = os.path.join(ROOT, 'om_gen', 'examples', 'core_types.json')
        recipe = load_recipe_file(recipe_path)
        ir = recipe_to_ir(recipe)
        validate_ir(ir)
        xml = emit_workflow_xml(ir)
        for code in [
            '1', '9', '12', '14', '20', '21', '22', '23', '24', '25', '26',
            '27', '28', '29', '30', '31', '38', '40', '41',
        ]:
            self.assertIn(f'Type="{code}"', xml)
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        self.assertTrue(eng.load_workflow_xml_string(xml, source_label='core'))
        g = eng.graphs[list(eng.graphs)[0]]
        self.assertGreaterEqual(g.number_of_nodes(), 20)


class TestOmGenNL(unittest.TestCase):
    def test_nl_append_z(self):
        recipe = nl_to_recipe(
            'On Location::triBuilding triSave: modify set triNameTX = triNameTX + "Z"',
            name='triBuilding - Synchronous - Append Z to Name',
        )
        self.assertEqual(recipe['header']['module'], 'Location')
        self.assertEqual(recipe['header']['bo'], 'triBuilding')
        self.assertEqual(recipe['header']['event_name'], 'triSave')
        types = [t['type'] for t in recipe['tasks']]
        self.assertEqual(types[0], '1')
        self.assertEqual(types[-1], '9')
        self.assertIn('28', types)
        mod = next(t for t in recipe['tasks'] if t['type'] == '28')
        self.assertEqual(mod['mappings'][0]['field'], 'triNameTX')
        data = build_from_recipe(recipe)
        self.assertTrue(data[:2] == b'PK')

    def test_nl_unknown_verb(self):
        with self.assertRaises(ValueError) as ctx:
            nl_to_recipe('On Location::triBuilding Pre-Create: teleport to mars')
        self.assertIn('Unknown step verb', str(ctx.exception))
        self.assertIn('modify', str(ctx.exception))


class TestOmGenValidate(unittest.TestCase):
    def test_missing_mappings(self):
        recipe = {
            'header': {'name': 'x', 'module': 'Location', 'bo': 'triBuilding'},
            'tasks': [
                {'key': 'start', 'type': '1'},
                {'key': 'mod1', 'type': '28', 'label': 'bad'},
                {'key': 'end', 'type': '9'},
            ],
        }
        with self.assertRaises(ValidationError):
            validate_ir(recipe_to_ir(recipe))


class TestGeneratorAPI(unittest.TestCase):
    def test_parse_and_compile(self):
        parsed = web_server.generator_parse({
            'name': 'triBuilding - Synchronous - Append Z to Name',
            'module': 'Location',
            'bo': 'triBuilding',
            'prompt': 'On Location::triBuilding triSave: modify set triNameTX = triNameTX + "Z"',
        })
        self.assertIn('ir', parsed)
        self.assertIn('nodes', parsed)
        self.assertIn('edges', parsed)
        self.assertGreaterEqual(len(parsed['nodes']), 3)
        self.assertGreaterEqual(len(parsed['edges']), 2)
        data, fname = web_server.generator_compile({'ir': parsed['ir']})
        self.assertTrue(fname.endswith('.zip'))
        self.assertTrue(data[:2] == b'PK')
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertIn('AllObjects.xml', zf.namelist())

    def test_cli_minimal_outfile(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'min.zip')
            path = build_from_ir(minimal_start_end_ir(), out_path=out)
            self.assertEqual(path, out)
            self.assertTrue(os.path.isfile(out))


class TestPreviewGraph(unittest.TestCase):
    def test_preview_nodes(self):
        ir = minimal_start_end_ir()
        nodes, edges = ir_to_preview_graph(ir)
        ids = {n['id'] for n in nodes}
        self.assertEqual(ids, {'start', 'end'})
        self.assertEqual(edges, [{'from': 'start', 'to': 'end'}])


if __name__ == '__main__':
    unittest.main()
