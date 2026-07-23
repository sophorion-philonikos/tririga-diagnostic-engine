"""Emit Workflow XML from WorkflowIR using the corpus dictionary scaffold."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from om_gen.dictionary import HEADER_DEFAULTS, TASK_ATTR_DEFAULTS, type_info
from om_gen.ir import (
    ConditionIR,
    EdgeIR,
    GuiMappingIR,
    MappingIR,
    TaskIR,
    TaskRefIR,
    WorkflowIR,
)
from om_gen.schema import default_event_for


def _cdata(text: str) -> str:
    text = text or ''
    if ']]>' in text:
        text = text.replace(']]>', ']]]]><![CDATA[>')
    return f'<![CDATA[{text}]]>'


def _attr_escape(v: str) -> str:
    return escape(str(v), {'"': '&quot;', '<': '&lt;', '&': '&amp;'})


def _tag(name: str, text: str = '', attrs: Optional[Dict[str, str]] = None) -> str:
    attr_s = ''
    if attrs:
        attr_s = ''.join(f' {k}="{_attr_escape(v)}"' for k, v in attrs.items())
    if text is None:
        text = ''
    return f'<{name}{attr_s}>{_cdata(text)}</{name}>'


def _empty_tag(name: str, attrs: Optional[Dict[str, str]] = None) -> str:
    attr_s = ''
    if attrs:
        attr_s = ''.join(f' {k}="{_attr_escape(v)}"' for k, v in attrs.items())
    return f'<{name}{attr_s}></{name}>'


def allocate_ids(ir: WorkflowIR, start_id: int = 100000) -> Dict[str, str]:
    """Assign numeric Task.Id values; Start prefers id 0 if key is 'start'."""
    key_to_id: Dict[str, str] = {}
    next_id = start_id
    for task in ir.tasks:
        if task.id:
            key_to_id[task.key] = str(task.id)
            continue
        if task.type == '1' and task.key == 'start' and '0' not in key_to_id.values():
            tid = '0'
        else:
            tid = str(next_id)
            next_id += 1
        task.id = tid
        key_to_id[task.key] = tid
    return key_to_id


def _resolve_ref(token: str, key_to_id: Dict[str, str]) -> str:
    if token in ('', '0', '-1'):
        return token or '0'
    if token in key_to_id:
        return key_to_id[token]
    if token.isdigit() or (token.startswith('-') and token[1:].isdigit()):
        return token
    # Unknown key — leave as-is for validator to catch
    return key_to_id.get(token, token)


def resolve_key_refs(ir: WorkflowIR, key_to_id: Dict[str, str]) -> None:
    """Resolve key-based refs in tasks to numeric ids."""
    for task in ir.tasks:
        if task.src_task_id not in ('', '-1'):
            task.src_task_id = _resolve_ref(task.src_task_id, key_to_id)
        if task.trgt_task_id not in ('', '-1'):
            task.trgt_task_id = _resolve_ref(task.trgt_task_id, key_to_id)
        if task.assignee_task_id and task.assignee_task_id not in ('0',):
            task.assignee_task_id = _resolve_ref(task.assignee_task_id, key_to_id)
        if task.target_association:
            parts = []
            for p in task.target_association.split(';'):
                p = p.strip()
                if not p:
                    continue
                parts.append(_resolve_ref(p, key_to_id))
            if parts:
                task.target_association = ';'.join(parts) + (
                    ';' if task.target_association.rstrip().endswith(';') or len(parts) >= 1 else ''
                )
                if not task.target_association.endswith(';'):
                    task.target_association += ';'
        for ref in task.refs:
            ref.ref_task_id = _resolve_ref(ref.ref_task_id, key_to_id)
        if task.condition:
            for p in task.condition.params:
                p.p_data_id = _resolve_ref(p.p_data_id, key_to_id)


def _infer_map_type(m: MappingIR) -> str:
    if m.map_type:
        return m.map_type
    if m.src_field:
        return '10'
    val = (m.value or '').strip()
    if any(op in val for op in ('+', '-', '*', '/', '(', ')')) and not (
        val.startswith('"') and val.endswith('"') and '+' not in val
    ):
        # formula-like (includes field + "Z")
        if re.search(r'[A-Za-z_]', val) and any(c in val for c in '+-*/()'):
            return '80'
    return '40'


def _emit_obj_mappings(task: TaskIR, map_id: str, module: str, bo: str) -> str:
    lines = ['<ObjMappings>']
    for m in task.mappings:
        mt = _infer_map_type(m)
        trgt_mod = m.trgt_module or module
        trgt_bo = m.trgt_bo or bo
        src_mod = m.src_module or (module if m.src_field else '')
        src_bo = m.src_bo or (bo if m.src_field else '')
        kids = [
            _tag('FldVal', m.value if mt != '10' else (m.value or '')),
            _tag('SrcFldVal', ''),
            _tag('TrgtModule', trgt_mod),
            _tag('TrgtBo', trgt_bo),
            _tag('SrcModule', src_mod),
            _tag('SrcBo', src_bo),
        ]
        if mt == '80':
            kids.append(_tag('EFormula', ''))
        kids.extend([
            _tag('TrgtTab', m.trgt_tab or 'General'),
            _tag('TrgtSec', m.trgt_sec or 'General'),
            _tag('TrgtFld', m.field),
            _tag('SrcTab', m.src_tab if m.src_field else ''),
            _tag('SrcSec', m.src_sec if m.src_field else ''),
            _tag('SrcFld', m.src_field),
        ])
        lines.append(f'<ObjMapping Id="{escape(map_id)}" Type="{escape(mt)}">')
        lines.extend(kids)
        lines.append('</ObjMapping>')
    lines.append('</ObjMappings>')
    return '\n'.join(lines)


def _emit_task_refs(refs: List[TaskRefIR]) -> str:
    if not refs:
        return '<TaskRefs></TaskRefs>'
    parts = ['<TaskRefs>']
    for r in refs:
        parts.append(
            f'<TaskRef RefType="{escape(r.ref_type)}" UseType="{escape(r.use_type)}" '
            f'TaskRefType="0" CtxType="-1" RefTaskId="{escape(r.ref_task_id)}">'
        )
        parts.append(_tag('RefSec', r.ref_sec))
        parts.append(_tag('RefField', r.ref_field))
        parts.append(_tag('RefAssoc', r.ref_assoc))
        parts.append(_tag('RefModule', r.module))
        parts.append(_tag('RefObject', r.bo))
        parts.append('</TaskRef>')
    parts.append('</TaskRefs>')
    return '\n'.join(parts)


def _emit_condition(cond: Optional[ConditionIR]) -> str:
    """Emit Condition with corpus Param child-element shape (not attr PType/PDataId)."""
    if cond is None:
        return (
            '<Condition>'
            '<Expression><![CDATA[]]></Expression>'
            '<Params></Params>'
            '</Condition>'
        )
    lines = ['<Condition>', _tag('Expression', cond.expression or ''), '<Params>']
    for p in cond.params:
        # Corpus: <Param PId="n"><PType/><PDataId/> then field kids or PItem
        lines.append(f'<Param PId="{escape(p.p_id)}">')
        lines.append(_tag('PType', p.p_type or 'field'))
        lines.append(_tag('PDataId', p.p_data_id or '0'))
        if (p.p_type or 'field') == 'item' or p.p_item:
            lines.append(_tag('PItem', p.p_item or 'Result Count'))
        else:
            lines.append(_tag('PField', p.p_field))
            lines.append(_tag('PSection', p.p_section))
            lines.append(_tag('PModule', p.p_module))
            lines.append(_tag('PBO', p.p_bo))
        lines.append('</Param>')
    lines.append('</Params></Condition>')
    return '\n'.join(lines)


def _emit_gui_mappings(items: List[GuiMappingIR]) -> str:
    if not items:
        return ''
    lines = ['<GUIMappings>']
    for g in items:
        lines.append(
            f'<GUIMapping PropType="{escape(g.prop_type)}" '
            f'TaskId="0" ActId="0">'
        )
        lines.append(_tag('PropVal', g.prop_val))
        lines.append(_tag('Tab', g.tab))
        lines.append(_tag('Section', g.section))
        lines.append(_tag('Field', g.field))
        lines.append(_tag('Bo', g.bo))
        lines.append(_tag('BoModule', g.bo_module))
        lines.append(_tag('GUI', g.gui))
        lines.append(_tag('Module', g.module))
        lines.append('</GUIMapping>')
    lines.append('</GUIMappings>')
    return '\n'.join(lines)


def _ensure_default_refs(task: TaskIR, header_mod: str, header_bo: str) -> None:
    info = type_info(task.type)
    if task.refs:
        return
    mod = task.module or header_mod
    bo = task.bo or header_bo
    if info.get('dual_taskrefs'):
        task.refs = [
            TaskRefIR(ref_task_id='0', ref_type='0', use_type='1', module=mod, bo=bo),
            TaskRefIR(ref_task_id='0', ref_type='1', use_type='2', module=mod, bo=bo),
        ]
    elif task.type in ('1', '25', '26', '27', '23', '24', '31', '38', '22'):
        task.refs = [
            TaskRefIR(ref_task_id='0', ref_type='0', use_type='1', module=mod, bo=bo),
        ]


def _emit_task(task: TaskIR, header_mod: str, header_bo: str) -> str:
    info = type_info(task.type)
    mod = task.module if task.module is not None else header_mod
    bo = task.bo if task.bo is not None else header_bo
    if task.type in ('9', '12'):
        mod, bo = '', ''

    event = task.event_name
    if not event:
        event = default_event_for(task.type)

    # MapId coupling for mappings (must be known before Task attrs)
    map_id = task.map_id if task.map_id not in ('',) else '-1'
    if task.mappings:
        if map_id in ('', '-1'):
            map_id = str(100000 + (abs(hash(task.key)) % 900000))
        task.map_id = map_id

    _ensure_default_refs(task, header_mod, header_bo)

    attrs = dict(TASK_ATTR_DEFAULTS)
    attrs.update({
        'Id': task.id,
        'Type': task.type,
        'MapId': map_id,
        'SRCTaskId': task.src_task_id or '-1',
        'TRGTTaskId': task.trgt_task_id or '-1',
        'AssigneeTaskId': task.assignee_task_id or '0',
        'UseMap': task.use_map or '1',
    })
    if task.type == '24' and task.target_association:
        body = task.target_association.split(';')[0].strip()
        if body:
            attrs['AssigneeTaskId'] = body

    attr_s = ' '.join(f'{k}="{escape(str(v))}"' for k, v in attrs.items())
    lines = [f'<Task {attr_s}>']

    label = task.label or info['name']
    lines.append(_tag('TaskLabel', label))
    lines.append(_tag('EventName', event))
    lines.append(_tag('Description', task.description))
    lines.append(_tag('DeleteSection', ''))
    lines.append(_tag('SumSection', ''))
    lines.append(_tag('SumField', ''))
    lines.append(_tag('FilterSection', ''))
    lines.append(_tag('FilterField', ''))
    lines.append(_tag('FilterValue', ''))
    lines.append(_tag('ServiceAssociation', task.service_association))
    lines.append(_tag('TargetAssociation', task.target_association))
    lines.append(_tag('TransactionType', '0'))
    lines.append(_tag('Status', '0'))
    pmap = '-1'
    if task.type == '38' and task.extras.get('parameters'):
        pmap = task.id
    lines.append(_tag('ParametersMapId', pmap))
    lines.append(_tag('FormulaRecalc', task.formula_recalc or '0'))
    lines.append(_tag('Module', mod))
    lines.append(_tag('BO', bo))

    if 'AssociatedModule' in info.get('always_extra_children', []) or task.associated_module:
        lines.append(_tag('AssociatedModule', task.associated_module or mod))
    if 'AssociatedBO' in info.get('always_extra_children', []) or task.associated_bo:
        if task.type == '41':
            lines.append(_tag('AssociatedBO', task.associated_bo or '0'))
        else:
            lines.append(_tag('AssociatedBO', task.associated_bo or bo))

    lines.append(_tag('AssignToUserMod', ''))
    lines.append(_tag('AssignToUserBO', ''))
    lines.append(_tag('AssignToUser', ''))

    if info.get('requires_filter_bo') or task.filter_bo:
        lines.append(_tag('FilterBo', task.filter_bo))
        lines.append(_tag('FilterBoBO', task.filter_bo_bo or bo))
        lines.append(_tag('FilterModule', task.filter_module or mod))
        # Type 22 always emits FilterClass (empty if unknown); others only when set
        if task.type == '22' or task.filter_class:
            lines.append(_tag('FilterClass', task.filter_class))

    if (
        info.get('requires_condition')
        or 'Condition' in info.get('always_extra_children', [])
        or task.condition is not None
    ):
        lines.append(_emit_condition(task.condition))

    if task.mappings:
        lines.append(_emit_obj_mappings(
            task, map_id, mod or header_mod, bo or header_bo,
        ))

    if task.gui_mappings:
        lines.append(_emit_gui_mappings(task.gui_mappings))

    lines.append(_emit_task_refs(task.refs))
    lines.append('</Task>')
    return '\n'.join(lines)


def _linear_edges(ir: WorkflowIR) -> List[EdgeIR]:
    if ir.edges:
        return list(ir.edges)
    edges: List[EdgeIR] = []
    for a, b in zip(ir.tasks, ir.tasks[1:]):
        edges.append(EdgeIR(from_key=a.key, to_key=b.key))
    return edges


def _wf_steps(ir: WorkflowIR, key_to_id: Dict[str, str]) -> str:
    edges = _linear_edges(ir)
    # ParId = predecessor task id
    pred: Dict[str, str] = {t.key: '-1' for t in ir.tasks}
    for e in edges:
        # last edge wins if multiple preds — first Start edge sets child
        if pred.get(e.to_key, '-1') == '-1' or e.from_key:
            pred[e.to_key] = key_to_id[e.from_key]
    # Start always -1
    for t in ir.tasks:
        if t.type == '1':
            pred[t.key] = '-1'

    lines = ['<WFSteps>']
    for t in ir.tasks:
        par = pred.get(t.key, '-1')
        lines.append(
            f'<WFStep Id="{escape(t.id)}" Type="{escape(t.type)}" ParId="{escape(par)}"></WFStep>'
        )
    lines.append('</WFSteps>')
    return '\n'.join(lines)


def workflow_filename(ir: WorkflowIR) -> str:
    h = ir.header
    safe = re.sub(r'[^\w.\-]+', '', h.name.replace(' ', ''))[:80] or 'Generated'
    mod = re.sub(r'[^\w]+', '', h.module) or 'Module'
    bo = re.sub(r'[^\w]+', '', h.bo) or 'BO'
    return f'Workflow_{mod}_{bo}_{safe}.xml'


def emit_workflow_xml(ir: WorkflowIR) -> str:
    """Compile WorkflowIR to XML string."""
    key_to_id = allocate_ids(ir)
    # Fill Start event from header
    for t in ir.tasks:
        if t.type == '1' and not t.event_name:
            t.event_name = ir.header.event_name
        if t.type == '1':
            t.module = t.module or ir.header.module
            t.bo = t.bo or ir.header.bo
            t.associated_module = t.associated_module or ir.header.associated_module or ir.header.module
            t.associated_bo = t.associated_bo or ir.header.associated_bo or ir.header.bo
        if t.type in ('27', '28') and not t.module:
            t.module = ir.header.module
            t.bo = ir.header.bo
        if t.type == '28' and not t.event_name:
            t.event_name = 'Append'
        if t.type == '14' and not t.event_name:
            t.event_name = '0=true;1=false;'
        if t.type == '29' and not t.event_name:
            t.event_name = 'GETLIST'

    resolve_key_refs(ir, key_to_id)

    h = ir.header
    header_attrs = {
        'Type': h.header_type or HEADER_DEFAULTS['Type'],
        'WfStatus': h.wf_status or HEADER_DEFAULTS['WfStatus'],
        'IgnoreModuleLevel': HEADER_DEFAULTS['IgnoreModuleLevel'],
        'InstanceData': h.instance_data or HEADER_DEFAULTS['InstanceData'],
        'LockRecord': HEADER_DEFAULTS['LockRecord'],
        'Modifier': HEADER_DEFAULTS['Modifier'],
    }
    ha = ' '.join(f'{k}="{escape(str(v))}"' for k, v in header_attrs.items())

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!-- Generated by om_gen -->',
        '<Workflow>',
        f'<Header {ha}>',
        _tag('ObjectLabelName', h.object_label_name or 'In Progress 0.0'),
        _tag('Name', h.name),
        _tag('Module', h.module),
        _tag('BO', h.bo),
        _tag('EventName', h.event_name),
        _tag('Description', h.description),
        _tag('AssociationName', h.association_name),
        _tag('UpdatedBy', h.updated_by or 'om_gen'),
        _tag('AssociatedBO', h.associated_bo),
        _tag('AssociatedModule', h.associated_module),
        '</Header>',
        '<Tasks>',
    ]
    for t in ir.tasks:
        parts.append(_emit_task(t, h.module, h.bo))
    parts.append('</Tasks>')
    parts.append(_wf_steps(ir, key_to_id))
    parts.append('</Workflow>')
    return '\n'.join(parts)


def ir_to_preview_graph(ir: WorkflowIR) -> Tuple[List[dict], List[dict]]:
    """Nodes/edges for the Generator preview map (keys, not live task ids)."""
    allocate_ids(ir)
    nodes = []
    for t in ir.tasks:
        info = type_info(t.type)
        nodes.append({
            'id': t.key,
            'label': t.label or info['name'],
            'type': t.type,
            'typeName': info['name'],
        })
    edges = []
    for e in _linear_edges(ir):
        edges.append({'from': e.from_key, 'to': e.to_key})
    return nodes, edges
