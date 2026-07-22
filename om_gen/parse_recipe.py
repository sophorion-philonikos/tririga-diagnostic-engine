"""Parse JSON recipe dict/file → WorkflowIR."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from om_gen.ir import (
    ConditionIR,
    ConditionParamIR,
    EdgeIR,
    GuiMappingIR,
    HeaderIR,
    MappingIR,
    TaskIR,
    TaskRefIR,
    WorkflowIR,
)


def _mapping(m: Dict[str, Any]) -> MappingIR:
    return MappingIR(
        field=str(m.get('field') or m.get('trgt_fld') or ''),
        value=str(m.get('value') or m.get('fld_val') or ''),
        src_field=str(m.get('src_field') or m.get('src_fld') or ''),
        map_type=str(m.get('map_type') or m.get('type') or ''),
        trgt_module=str(m.get('trgt_module') or ''),
        trgt_bo=str(m.get('trgt_bo') or ''),
        trgt_tab=str(m.get('trgt_tab') or 'General'),
        trgt_sec=str(m.get('trgt_sec') or 'General'),
        src_module=str(m.get('src_module') or ''),
        src_bo=str(m.get('src_bo') or ''),
        src_tab=str(m.get('src_tab') or ''),
        src_sec=str(m.get('src_sec') or ''),
    )


def _ref(r: Dict[str, Any]) -> TaskRefIR:
    return TaskRefIR(
        ref_task_id=str(r.get('ref_task_id', r.get('ref_task', '0'))),
        ref_type=str(r.get('ref_type', '0')),
        use_type=str(r.get('use_type', '1')),
        module=str(r.get('module') or ''),
        bo=str(r.get('bo') or ''),
        ref_sec=str(r.get('ref_sec') or ''),
        ref_field=str(r.get('ref_field') or ''),
        ref_assoc=str(r.get('ref_assoc') or ''),
    )


def _condition(c: Optional[Dict[str, Any]]) -> Optional[ConditionIR]:
    if not c:
        return None
    params = []
    for p in c.get('params') or []:
        params.append(ConditionParamIR(
            p_id=str(p.get('p_id', p.get('id', '0'))),
            p_type=str(p.get('p_type', p.get('type', 'field'))),
            p_data_id=str(p.get('p_data_id', p.get('data_id', '0'))),
            p_field=str(p.get('p_field', p.get('field', ''))),
            p_section=str(p.get('p_section', p.get('section', ''))),
            p_module=str(p.get('p_module', p.get('module', ''))),
            p_bo=str(p.get('p_bo', p.get('bo', ''))),
        ))
    return ConditionIR(expression=str(c.get('expression') or ''), params=params)


def _gui(g: Dict[str, Any]) -> GuiMappingIR:
    return GuiMappingIR(
        prop_type=str(g.get('prop_type', '1')),
        prop_val=str(g.get('prop_val', 'true')),
        tab=str(g.get('tab') or ''),
        section=str(g.get('section') or ''),
        field=str(g.get('field') or ''),
        bo=str(g.get('bo') or ''),
        bo_module=str(g.get('bo_module') or ''),
        gui=str(g.get('gui') or ''),
        module=str(g.get('module') or ''),
    )


def _task(t: Dict[str, Any]) -> TaskIR:
    return TaskIR(
        key=str(t['key']),
        type=str(t['type']),
        label=str(t.get('label') or ''),
        event_name=str(t.get('event_name') or ''),
        description=str(t.get('description') or ''),
        module=str(t.get('module') or ''),
        bo=str(t.get('bo') or ''),
        associated_module=str(t.get('associated_module') or ''),
        associated_bo=str(t.get('associated_bo') or ''),
        filter_bo=str(t.get('filter_bo') or ''),
        filter_bo_bo=str(t.get('filter_bo_bo') or ''),
        filter_module=str(t.get('filter_module') or ''),
        filter_class=str(t.get('filter_class') or ''),
        target_association=str(t.get('target_association') or ''),
        service_association=str(t.get('service_association') or ''),
        formula_recalc=str(t.get('formula_recalc') or '0'),
        use_map=str(t.get('use_map') or '1'),
        map_id=str(t.get('map_id') or '-1'),
        src_task_id=str(t.get('src_task_id') or '-1'),
        trgt_task_id=str(t.get('trgt_task_id') or '-1'),
        assignee_task_id=str(t.get('assignee_task_id') or '0'),
        mappings=[_mapping(m) for m in (t.get('mappings') or [])],
        refs=[_ref(r) for r in (t.get('refs') or [])],
        condition=_condition(t.get('condition')),
        gui_mappings=[_gui(g) for g in (t.get('gui_mappings') or [])],
        id=str(t.get('id') or ''),
        extras=dict(t.get('extras') or {}),
    )


def recipe_to_ir(recipe: Dict[str, Any]) -> WorkflowIR:
    h = recipe.get('header') or {}
    header = HeaderIR(
        name=str(h.get('name') or ''),
        module=str(h.get('module') or ''),
        bo=str(h.get('bo') or ''),
        event_name=str(h.get('event_name') or ''),
        description=str(h.get('description') or ''),
        object_label_name=str(h.get('object_label_name') or 'In Progress 0.0'),
        header_type=str(h.get('header_type') or h.get('type') or '0'),
        wf_status=str(h.get('wf_status') or '10'),
        instance_data=str(h.get('instance_data') or '0'),
        associated_module=str(h.get('associated_module') or ''),
        associated_bo=str(h.get('associated_bo') or ''),
        updated_by=str(h.get('updated_by') or 'om_gen'),
        association_name=str(h.get('association_name') or ''),
    )
    tasks = [_task(t) for t in (recipe.get('tasks') or [])]
    edges: List[EdgeIR] = []
    for e in recipe.get('edges') or []:
        edges.append(EdgeIR(from_key=str(e['from']), to_key=str(e['to'])))
    return WorkflowIR(header=header, tasks=tasks, edges=edges)


def load_recipe_file(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def ir_to_recipe_dict(ir: WorkflowIR) -> Dict[str, Any]:
    """Serialize IR back to JSON-friendly recipe (for API preview)."""
    def mapping_d(m):
        return {
            'field': m.field, 'value': m.value, 'src_field': m.src_field,
            'map_type': m.map_type, 'trgt_module': m.trgt_module, 'trgt_bo': m.trgt_bo,
            'trgt_tab': m.trgt_tab, 'trgt_sec': m.trgt_sec,
        }

    def task_d(t: TaskIR) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            'key': t.key, 'type': t.type, 'label': t.label,
            'event_name': t.event_name, 'module': t.module, 'bo': t.bo,
        }
        if t.mappings:
            d['mappings'] = [mapping_d(m) for m in t.mappings]
        if t.refs:
            d['refs'] = [{
                'ref_task_id': r.ref_task_id, 'ref_type': r.ref_type,
                'use_type': r.use_type, 'module': r.module, 'bo': r.bo,
            } for r in t.refs]
        if t.filter_bo:
            d['filter_bo'] = t.filter_bo
            d['filter_module'] = t.filter_module
            d['filter_bo_bo'] = t.filter_bo_bo
        if t.target_association:
            d['target_association'] = t.target_association
        if t.service_association:
            d['service_association'] = t.service_association
        if t.trgt_task_id not in ('', '-1'):
            d['trgt_task_id'] = t.trgt_task_id
        if t.src_task_id not in ('', '-1'):
            d['src_task_id'] = t.src_task_id
        if t.condition:
            d['condition'] = {
                'expression': t.condition.expression,
                'params': [{
                    'p_id': p.p_id, 'p_type': p.p_type, 'p_data_id': p.p_data_id,
                    'p_field': p.p_field, 'p_section': p.p_section,
                    'p_module': p.p_module, 'p_bo': p.p_bo,
                } for p in t.condition.params],
            }
        if t.gui_mappings:
            d['gui_mappings'] = [{
                'prop_type': g.prop_type, 'prop_val': g.prop_val,
                'tab': g.tab, 'section': g.section, 'field': g.field,
            } for g in t.gui_mappings]
        return d

    h = ir.header
    out: Dict[str, Any] = {
        'header': {
            'name': h.name, 'module': h.module, 'bo': h.bo,
            'event_name': h.event_name, 'description': h.description,
            'object_label_name': h.object_label_name,
        },
        'tasks': [task_d(t) for t in ir.tasks],
    }
    if ir.edges:
        out['edges'] = [{'from': e.from_key, 'to': e.to_key} for e in ir.edges]
    return out
