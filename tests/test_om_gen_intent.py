"""Tests for om_gen intent layer + Condition Param emit fidelity."""

from __future__ import annotations

import io
import os
import sys
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.engine import TririgaHybridEngine
from om_gen.build import build_from_recipe
from om_gen.emit_workflow import emit_workflow_xml, ir_to_preview_graph
from om_gen.intent import IntentError, parse_prompt, strip_preamble
from om_gen.nl_recipe import nl_to_recipe
from om_gen.parse_recipe import recipe_to_ir
from om_gen.validate import validate_ir
from web import server as web_server


class TestPreamble(unittest.TestCase):
    def test_strip_preamble_not_type_27(self):
        body = strip_preamble(
            'Create a workflow that on save for a building, append Z to the name'
        )
        self.assertFalse(body.lower().startswith('create'))
        recipe = parse_prompt(
            'Create a workflow that on save for a building, append Z to the name',
            name='triBuilding - Synchronous - Append Z to Name',
            module='Location',
            bo='triBuilding',
        )
        types = [t['type'] for t in recipe['tasks']]
        self.assertNotIn('27', types)
        self.assertIn('28', types)


class TestAppendZRegression(unittest.TestCase):
    def test_constrained_still_works(self):
        recipe = nl_to_recipe(
            'On Location::triBuilding triSave: modify set triNameTX = triNameTX + "Z"',
            name='triBuilding - Synchronous - Append Z to Name',
        )
        self.assertEqual(recipe['header']['event_name'], 'triSave')
        mod = next(t for t in recipe['tasks'] if t['type'] == '28')
        self.assertEqual(mod['mappings'][0]['field'], 'triNameTX')

    def test_intent_paraphrase_append_z(self):
        recipe = parse_prompt(
            'On save for a building, append Z to the name',
            name='triBuilding - Synchronous - Append Z to Name',
            module='Location',
            bo='triBuilding',
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
        self.assertEqual(mod['mappings'][0]['map_type'], '80')
        self.assertIn('+"Z"', mod['mappings'][0]['value'].replace(' ', ''))
        data = build_from_recipe(recipe)
        self.assertEqual(data[:2], b'PK')
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            wf = [n for n in zf.namelist() if n.startswith('Workflow_')][0]
            xml = zf.read(wf).decode('utf-8')
        eng = TririgaHybridEngine(None, None, None, offline_mode=True)
        self.assertTrue(eng.load_workflow_xml_string(xml, source_label='intent_z'))


class TestFieldNullSwitch(unittest.TestCase):
    def test_name_not_null_append_z(self):
        recipe = parse_prompt(
            "If the building record's name field is not null, append Z to the name; "
            'otherwise do nothing',
            module='Location',
            bo='triBuilding',
            event_name='triSave',
        )
        types = {t['type'] for t in recipe['tasks']}
        self.assertEqual(types, {'1', '14', '28', '12', '9'})
        sw = next(t for t in recipe['tasks'] if t['type'] == '14')
        self.assertEqual(sw['condition']['expression'].strip(), 'p0 != ""')
        p0 = sw['condition']['params'][0]
        self.assertEqual(p0['p_type'], 'field')
        self.assertEqual(p0['p_data_id'], '0')
        self.assertEqual(p0['p_field'], 'triNameTX')
        self.assertEqual(p0['p_module'], 'Location')
        self.assertEqual(p0['p_bo'], 'triBuilding')
        self.assertIn(';', sw['target_association'])

        ir = recipe_to_ir(recipe)
        validate_ir(ir)
        xml = emit_workflow_xml(ir)
        self.assertIn('<PType><![CDATA[field]]>', xml)
        self.assertNotIn('PType="field"', xml)
        self.assertIn('<PDataId><![CDATA[0]]>', xml)
        self.assertIn('p0 != ""', xml)

        nodes, edges = ir_to_preview_graph(ir)
        edge_pairs = {(e['from'], e['to']) for e in edges}
        self.assertIn(('start', 'sw1'), edge_pairs)
        self.assertIn(('sw1', 'mod_true'), edge_pairs)
        self.assertIn(('sw1', 'j_false'), edge_pairs)


class TestCountSwitch(unittest.TestCase):
    def test_retrieve_then_count(self):
        recipe = parse_prompt(
            'Retrieve buildings; if result count > 0 then append Z to the name',
            module='Location',
            bo='triBuilding',
            event_name='triSave',
        )
        types = [t['type'] for t in recipe['tasks']]
        self.assertIn('29', types)
        self.assertIn('14', types)
        self.assertIn('28', types)
        sw = next(t for t in recipe['tasks'] if t['type'] == '14')
        self.assertEqual(sw['condition']['expression'].strip(), 'p0 > 0')
        p0 = sw['condition']['params'][0]
        self.assertEqual(p0['p_type'], 'item')
        self.assertEqual(p0['p_item'], 'Result Count')
        self.assertEqual(p0['p_data_id'], 'src1')

        ir = recipe_to_ir(recipe)
        validate_ir(ir)
        xml = emit_workflow_xml(ir)
        self.assertIn('<PType><![CDATA[item]]>', xml)
        self.assertIn('<PItem><![CDATA[Result Count]]>', xml)
        # PDataId resolved to Retrieve numeric id (not key)
        self.assertNotIn('<PDataId><![CDATA[src1]]>', xml)
        ret = next(t for t in ir.tasks if t.type == '29')
        self.assertIn(f'<PDataId><![CDATA[{ret.id}]]>', xml)

        nodes, edges = ir_to_preview_graph(ir)
        edge_pairs = {(e['from'], e['to']) for e in edges}
        self.assertIn(('start', 'src1'), edge_pairs)
        self.assertIn(('src1', 'sw1'), edge_pairs)

    def test_bare_count_fails(self):
        with self.assertRaises(IntentError) as ctx:
            parse_prompt(
                'If result count > 0 then append Z to the name',
                module='Location',
                bo='triBuilding',
            )
        self.assertEqual(ctx.exception.code, 'bare_result_count')

    def test_query_bo_only_fails(self):
        with self.assertRaises(IntentError) as ctx:
            parse_prompt(
                'Query buildings; if result count > 0 then append Z to the name',
                module='Location',
                bo='triBuilding',
            )
        self.assertEqual(ctx.exception.code, 'query_needs_name')

    def test_query_with_name_ok(self):
        recipe = parse_prompt(
            'Query "triBuilding - Existing Query"; if result count > 0 then append Z to the name',
            module='Location',
            bo='triBuilding',
        )
        q = next(t for t in recipe['tasks'] if t['type'] == '22')
        self.assertEqual(q['filter_bo'], 'triBuilding - Existing Query')
        ir = recipe_to_ir(recipe)
        validate_ir(ir)
        xml = emit_workflow_xml(ir)
        self.assertIn('<FilterClass>', xml)
        self.assertIn('<FilterBo><![CDATA[triBuilding - Existing Query]]>', xml)


class TestFieldErrors(unittest.TestCase):
    def test_unknown_field(self):
        with self.assertRaises(IntentError) as ctx:
            parse_prompt(
                'If the building record\'s flibbertigibbet field is not null, append Z to the name',
                module='Location',
                bo='triBuilding',
            )
        self.assertEqual(ctx.exception.code, 'unknown_field')
        self.assertIn('flibbertigibbet', ctx.exception.span.lower())


class TestEmitParamShape(unittest.TestCase):
    def test_field_param_children_not_attrs(self):
        recipe = {
            'header': {
                'name': 'Param Shape', 'module': 'Location', 'bo': 'triBuilding',
                'event_name': 'triSave',
            },
            'tasks': [
                {'key': 'start', 'type': '1', 'label': 'Start'},
                {
                    'key': 'sw1', 'type': '14', 'label': 'Switch',
                    'event_name': '0=true;1=false;',
                    'target_association': 'j_true;j_false;',
                    'condition': {
                        'expression': 'p0 == ""',
                        'params': [{
                            'p_id': '0', 'p_type': 'field', 'p_data_id': '0',
                            'p_field': 'triNameTX', 'p_section': 'General',
                            'p_module': 'Location', 'p_bo': 'triBuilding',
                        }],
                    },
                },
                {'key': 'j_true', 'type': '12', 'label': 'T'},
                {'key': 'j_false', 'type': '12', 'label': 'F'},
                {'key': 'end', 'type': '9', 'label': 'End'},
            ],
            'edges': [
                {'from': 'start', 'to': 'sw1'},
                {'from': 'sw1', 'to': 'j_true'},
                {'from': 'sw1', 'to': 'j_false'},
                {'from': 'j_true', 'to': 'end'},
                {'from': 'j_false', 'to': 'end'},
            ],
        }
        xml = emit_workflow_xml(recipe_to_ir(recipe))
        self.assertIn('<Param PId="0">', xml)
        self.assertIn('<PType><![CDATA[field]]>', xml)
        self.assertNotRegex(xml, r'<Param[^>]*PType=')


class TestGeneratorAPIIntent(unittest.TestCase):
    def test_parse_intent_append_z(self):
        parsed = web_server.generator_parse({
            'name': 'triBuilding - Synchronous - Append Z to Name',
            'module': 'Location',
            'bo': 'triBuilding',
            'prompt': 'On save for a building, append Z to the name',
        })
        self.assertIn('ir', parsed)
        types = [t['type'] for t in parsed['ir']['tasks']]
        self.assertIn('28', types)
        data, fname = web_server.generator_compile({'ir': parsed['ir']})
        self.assertTrue(fname.endswith('.zip'))
        self.assertEqual(data[:2], b'PK')


class TestSlotParaphrases(unittest.TestCase):
    """Slot-extraction paraphrases beyond narrow templates."""

    def _mod_value(self, recipe):
        mod = next(t for t in recipe['tasks'] if t['type'] == '28')
        return mod['mappings'][0]['value'].replace(' ', '')

    def test_modifies_by_adding_letter_z_clicks_save(self):
        recipe = parse_prompt(
            "Create a workflow that modifies the building record's name field "
            'by adding the letter Z when the user clicks save',
            module='Location',
            bo='triBuilding',
        )
        self.assertEqual([t['type'] for t in recipe['tasks']], ['1', '28', '9'])
        self.assertEqual(recipe['header']['event_name'], 'triSave')
        self.assertIn('triNameTX+"Z"', self._mod_value(recipe))

    def test_updates_by_appending_z_on_save(self):
        recipe = parse_prompt(
            "Make a workflow that updates the building record's name field "
            'by appending Z on save',
            module='Location',
            bo='triBuilding',
        )
        self.assertEqual(recipe['header']['event_name'], 'triSave')
        self.assertIn('28', [t['type'] for t in recipe['tasks']])
        self.assertIn('triNameTX+"Z"', self._mod_value(recipe))

    def test_retrieve_greater_than_then_append_z(self):
        recipe = parse_prompt(
            'Make a workflow that retrieves building records, and if the result '
            "count is greater than 0, then append Z to the building's name field",
            module='Location',
            bo='triBuilding',
        )
        types = [t['type'] for t in recipe['tasks']]
        self.assertEqual(types, ['1', '29', '14', '28', '12', '9'])
        sw = next(t for t in recipe['tasks'] if t['type'] == '14')
        self.assertEqual(sw['condition']['expression'].strip(), 'p0 > 0')
        self.assertEqual(sw['condition']['params'][0]['p_item'], 'Result Count')

    def test_gets_more_than_then_add_z(self):
        recipe = parse_prompt(
            'Make a workflow that gets building records, and if the result '
            "count is more than 0, then add Z to the building's name field",
            module='Location',
            bo='triBuilding',
        )
        types = [t['type'] for t in recipe['tasks']]
        self.assertIn('29', types)
        self.assertIn('14', types)
        self.assertIn('28', types)
        sw = next(t for t in recipe['tasks'] if t['type'] == '14')
        self.assertEqual(sw['condition']['expression'].strip(), 'p0 > 0')

    def test_append_literal_123gg(self):
        recipe = parse_prompt(
            "Retrieve buildings; if result count > 0 then append 123GG "
            "to the building's name field",
            module='Location',
            bo='triBuilding',
        )
        self.assertIn('triNameTX+"123GG"', self._mod_value(recipe))

    def test_pre_create_event(self):
        recipe = parse_prompt(
            'on pre-create, append Z to the name',
            module='Location',
            bo='triBuilding',
        )
        self.assertEqual(recipe['header']['event_name'], 'Pre-Create')
        self.assertIn('triNameTX+"Z"', self._mod_value(recipe))


class TestBlankPredicateAndLiterals(unittest.TestCase):
    def _mod_value(self, recipe):
        mod = next(t for t in recipe['tasks'] if t['type'] == '28')
        return mod['mappings'][0]['value'].replace(' ', '')

    def test_blank_switch_add_a_z_to_it(self):
        recipe = parse_prompt(
            "Create a workflow so that if the building record's name field is blank, "
            "add a Z to it, otherwise don't do anything.",
            module='Location',
            bo='triBuilding',
        )
        types = [t['type'] for t in recipe['tasks']]
        self.assertEqual(types, ['1', '14', '28', '12', '9'])
        sw = next(t for t in recipe['tasks'] if t['type'] == '14')
        self.assertEqual(sw['condition']['expression'].strip(), 'p0 == ""')
        self.assertEqual(sw['condition']['params'][0]['p_field'], 'triNameTX')
        self.assertIn('triNameTX+"Z"', self._mod_value(recipe))

    def test_add_a_z_literal_not_article(self):
        recipe = parse_prompt(
            'add a Z to the name',
            module='Location',
            bo='triBuilding',
        )
        self.assertIn('triNameTX+"Z"', self._mod_value(recipe))
        self.assertNotIn('+"a"', self._mod_value(recipe))

    def test_unrecognized_if_otherwise_fails(self):
        with self.assertRaises(IntentError) as ctx:
            parse_prompt(
                "Create a workflow so that if the building record's name field "
                "is flibbertigibbet, add a Z to it, otherwise don't do anything.",
                module='Location',
                bo='triBuilding',
            )
        self.assertEqual(ctx.exception.code, 'unrecognized_predicate')


if __name__ == '__main__':
    unittest.main()
