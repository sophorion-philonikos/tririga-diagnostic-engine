"""Validate WorkflowIR against dictionary ID / structure rules."""

from __future__ import annotations

from typing import List, Set

from om_gen import SUPPORTED_TASK_TYPES
from om_gen.dictionary import type_info
from om_gen.emit_workflow import allocate_ids, resolve_key_refs
from om_gen.ir import WorkflowIR


class ValidationError(ValueError):
    pass


def validate_ir(ir: WorkflowIR, *, allocate: bool = True) -> None:
    errors: List[str] = []
    if not ir.header.name:
        errors.append('Header.name is required.')
    if not ir.header.module:
        errors.append('Header.module is required.')
    if not ir.tasks:
        errors.append('Workflow must contain at least one task.')

    keys: Set[str] = set()
    for t in ir.tasks:
        if t.key in keys:
            errors.append(f'Duplicate task key: {t.key}')
        keys.add(t.key)
        if str(t.type) not in SUPPORTED_TASK_TYPES:
            errors.append(f'Unsupported task type {t.type} on key={t.key}')
            continue
        info = type_info(t.type)
        if info.get('requires_objmappings') and not t.mappings:
            errors.append(f'Type {t.type} ({t.key}) requires mappings.')
        if info.get('requires_filter_bo') and not t.filter_bo:
            errors.append(f'Type {t.type} ({t.key}) requires filter_bo.')
        if info.get('requires_target_assoc') and not t.target_association:
            errors.append(f'Type {t.type} ({t.key}) requires target_association.')
        if info.get('requires_condition') and t.type == '14' and t.condition is None:
            # Allow empty condition object; Start gets empty condition on emit
            if t.type == '14' and t.condition is None:
                # Switch without condition is weak but corpus almost always has one
                pass

    if allocate:
        key_to_id = allocate_ids(ir)
        resolve_key_refs(ir, key_to_id)
    else:
        key_to_id = {t.key: t.id for t in ir.tasks if t.id}

    ids = [t.id for t in ir.tasks if t.id]
    if len(ids) != len(set(ids)):
        errors.append('Task Ids must be unique.')

    id_set: Set[str] = set(ids) | {'0', '-1'}
    type_by_id = {t.id: t.type for t in ir.tasks if t.id}

    for t in ir.tasks:
        for ref in t.refs:
            if ref.ref_task_id not in id_set and ref.ref_task_id not in key_to_id:
                errors.append(f'TaskRef RefTaskId={ref.ref_task_id} unknown (task {t.key})')
        if t.condition:
            for p in t.condition.params:
                if p.p_data_id not in id_set and p.p_data_id not in key_to_id:
                    errors.append(f'Condition PDataId={p.p_data_id} unknown (task {t.key})')
        if t.type == '41' and t.trgt_task_id not in ('', '-1'):
            tid = t.trgt_task_id
            if tid in key_to_id:
                tid = key_to_id[tid]
            if type_by_id.get(tid) != '40':
                errors.append(f'Type 41 ({t.key}) TRGTTaskId must reference a Type 40 task.')
        if t.type == '24' and t.target_association:
            parts = [p for p in t.target_association.split(';') if p.strip()]
            if len(parts) < 2:
                errors.append(f'Type 24 ({t.key}) TargetAssociation needs body;exit.')
        if t.type in ('14', '21') and t.target_association:
            parts = [p for p in t.target_association.split(';') if p.strip()]
            if len(parts) < 2:
                errors.append(f'Type {t.type} ({t.key}) TargetAssociation needs two branch ids.')
        if t.mappings and t.map_id not in ('', '-1'):
            # MapId will be coupled on emit; ensure mappings non-empty already checked
            pass

    # Edge keys
    for e in ir.edges:
        if e.from_key not in keys:
            errors.append(f'Edge from_key unknown: {e.from_key}')
        if e.to_key not in keys:
            errors.append(f'Edge to_key unknown: {e.to_key}')

    starts = [t for t in ir.tasks if t.type == '1']
    ends = [t for t in ir.tasks if t.type == '9']
    if not starts:
        errors.append('Workflow should include a Start task (type 1).')
    if not ends:
        errors.append('Workflow should include an End task (type 9).')

    if errors:
        raise ValidationError('\n'.join(errors))
