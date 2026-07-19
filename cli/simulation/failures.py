"""What-If simulation internals — split for reviewability."""
from __future__ import annotations

import re
import difflib
from collections import defaultdict, deque
from dataclasses import dataclass, field

import networkx as nx

from cli import graph_utils
from cli.knowledge import type_display_name

from cli.simulation.lexicon import *  # noqa: F401,F403
from cli.simulation.parse import Clause, _tokenize, _expand_domain_tokens
from cli.simulation.matching import match_task, match_clauses
from cli.simulation.tokens import build_token_index, propagate_null_token

# ============================================================
# 3c. TASK FAILURE PROFILES (execution failure / skip)
# ============================================================

def extract_modify_ledger(data):
    """Field ledger for Modify/Create tasks from ObjMappingRecords metadata."""
    target_bo = ''
    fields = []
    sources = []
    seen = set()

    for rec in data.get('ObjMappingRecords', []) or []:
        t_bo = str(rec.get('TrgtBo') or rec.get('TrgtBoName') or '').strip()
        t_fld = str(rec.get('TrgtFld') or '').strip()
        if t_bo and not target_bo:
            target_bo = t_bo
        if t_fld and t_fld not in seen:
            seen.add(t_fld)
            fields.append(t_fld)
        src_bo = str(rec.get('SrcBo') or '').strip()
        src_fld = str(rec.get('SrcFld') or '').strip()
        if src_bo or src_fld:
            sources.append({'bo': src_bo, 'field': src_fld})

    for f in data.get('TrgtFld', []) or []:
        fld = str(f).strip()
        if fld and fld not in seen:
            seen.add(fld)
            fields.append(fld)

    return {'target_bo': target_bo, 'fields': fields, 'sources': sources}


def extract_query_ledger(data):
    """Filter/BO context for Retrieve/Query tasks."""
    filters = []
    for key in ('LFldName', 'RFldName', 'ConstantValue', 'Expression'):
        for val in data.get(key, []) or []:
            v = str(val).strip()
            if v:
                filters.append(v)
    return {
        'filter_bo': str(data.get('FilterBo') or data.get('Bo') or '').strip(),
        'filters': filters,
        'bo': str(data.get('Bo') or '').strip(),
    }


def extract_associations(data):
    """Association names referenced by Associate/De-Associate tasks."""
    names = []
    for key in ('AssociationName', 'Association'):
        for val in data.get(key, []) or []:
            v = str(val).strip()
            if v:
                names.append(v)
    for rec in data.get('TaskRefRecords', []) or []:
        v = str(rec.get('AssociationName') or '').strip()
        if v:
            names.append(v)
    return names


_PROP_TYPE_LABELS = {
    '1': 'Visible',
    '3': 'Read-Only',
    '8': 'Required',
}


def _format_prop_value(val):
    low = str(val or '').strip().lower()
    if low == 'false':
        return 'No'
    if low == 'true':
        return 'Yes'
    return str(val or '').strip()


def extract_metadata_ledger(data):
    """UI/metadata ledger for Modify Metadata (Type 23) tasks from GUIMappings."""
    tabs, sections, fields = set(), set(), set()
    property_changes = []
    bo = str(data.get('BO') or data.get('Bo') or '').strip()

    for gm in data.get('GUIMappings', []) or []:
        tab = str(gm.get('Tab') or '').strip()
        sec = str(gm.get('Section') or '').strip()
        fld = str(gm.get('Field') or '').strip()
        if tab and tab != '^^':
            tabs.add(tab)
        if sec and sec != '^^':
            sections.add(sec)
        if fld and fld != '^^':
            fields.add(fld)
        p_type = str(gm.get('PropType') or '').strip()
        p_val = str(gm.get('PropVal') or '').strip()
        prop_label = _PROP_TYPE_LABELS.get(p_type, f'Property {p_type}' if p_type else 'Property')
        property_changes.append({
            'prop_type': p_type,
            'prop_label': prop_label,
            'value': p_val,
            'tab': tab,
            'section': sec,
            'field': fld,
        })

    return {
        'bo': bo,
        'tabs': sorted(tabs),
        'sections': sorted(sections),
        'fields': sorted(fields),
        'property_changes': property_changes,
    }


def _node_read_field_text(data):
    """Concatenate read-side field metadata only (excludes TrgtFld write targets)."""
    parts = []
    for key in ('LFldName', 'PField', 'Expression', 'ConstantValue', 'SrcFld'):
        for val in data.get(key, []) or []:
            parts.append(str(val))
    for rec in data.get('ObjMappingRecords', []) or []:
        if rec.get('SrcFld'):
            parts.append(str(rec['SrcFld']))
    return ' '.join(parts)


def find_field_dependent_nodes(graph, field_names, failed_id, failed_name):
    """Informational impacts: graph-descendant nodes that READ failed Modify fields.

    Peer Modifies that only write the same TrgtFld are excluded. Results are
    never added to impacted_map — they are informational only.
    """
    if not field_names:
        return []
    failed_id = str(failed_id)
    if not graph.has_node(failed_id):
        return []
    try:
        reachable = {str(n) for n in nx.descendants(graph, failed_id)}
    except Exception:
        reachable = set()
    if not reachable:
        return []

    notes = []
    for nid in sorted(reachable):
        if not graph.has_node(nid):
            continue
        data = graph.nodes[nid]
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        blob = _node_read_field_text(data).lower()
        hits = [f for f in field_names if f and f.lower() in blob]
        if not hits:
            continue
        t_type = graph_utils.get_type_str(data)
        t_name = type_display_name(t_type)
        node_name = str(data.get('name', f'Task {nid}'))
        sentence = (
            f"{t_name} '{node_name}' ({nid}) evaluates or references field "
            f"'{hits[0]}' which would remain unmodified if task {failed_id} "
            f"('{failed_name}') fails."
        )
        notes.append({
            'producer_id': failed_id,
            'consumer_id': str(nid),
            'consumer_name': node_name,
            'consumer_type': t_type,
            'ref_kind': 'field_reference',
            'fatal': False,
            'informational': True,
            'sentence': sentence,
        })
    return notes


def analyze_task_failures(engine, wf_name, clauses):
    """Resolve task-failure clauses and apply type-specific operational profiles."""
    graph = engine.graphs[wf_name]
    failed_tasks = []
    failed_ids = []
    altered_from_failure = []
    field_impacts = []
    impacts = []
    forced_overrides = {}
    unmatched = []
    impacted_map = {}

    if not clauses:
        return {
            'failed_tasks': failed_tasks,
            'failed_ids': failed_ids,
            'altered_from_failure': altered_from_failure,
            'field_impacts': field_impacts,
            'impacts': impacts,
            'forced_overrides': forced_overrides,
            'impacted_map': impacted_map,
            'unmatched': unmatched,
        }

    token_index = build_token_index(graph)

    for clause in clauses:
        nid, data, score = match_task(engine, wf_name, clause)
        if nid is None:
            unmatched.append(clause.text)
            continue

        t_type = graph_utils.get_type_str(data)
        t_type_name = type_display_name(t_type)
        name = str(data.get('name', f'Task {nid}'))
        mode = clause.failure_mode

        if t_type == '28':
            ledger = extract_modify_ledger(data)
            fields = ledger['fields']
            bo = ledger['target_bo']
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
                'fields': fields,
                'bo': bo,
            })
            failed_ids.append(nid)
            if fields:
                field_impacts.append({'task_id': nid, 'bo': bo, 'fields': fields})
                fld_str = ', '.join(fields)
                bo_part = f" on BO '{bo}'" if bo else ''
                impacts.append({
                    'producer_id': nid,
                    'producer_name': name,
                    'producer_type': t_type,
                    'consumer_id': None,
                    'consumer_name': '',
                    'consumer_type': '',
                    'ref_kind': 'field_ledger',
                    'fatal': False,
                    'sentence': (
                        f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                        f"will result in the failure to update the target field(s) ({fld_str}){bo_part}. "
                        f"Any downstream tasks relying on this task's output object token will be affected."
                    ),
                })
            else:
                impacts.append({
                    'producer_id': nid,
                    'producer_name': name,
                    'producer_type': t_type,
                    'consumer_id': None,
                    'consumer_name': '',
                    'consumer_type': '',
                    'ref_kind': 'execution_failure',
                    'fatal': False,
                    'sentence': (
                        f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) "
                        f"would not execute successfully."
                    ),
                })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)
            impacts.extend(find_field_dependent_nodes(graph, fields, nid, name))

        elif t_type == '25':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'get_temp_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would not load temporary form data for downstream consumers."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type == '27':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'create_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would not create a record token for downstream consumers."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type == '26':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'save_permanent_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would not persist the temporary record to a permanent record."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type in ('29', '22'):
            altered_from_failure.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'clause': clause.text,
                'score': round(score, 2),
            })
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'execution_failure',
                'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would produce no record token for downstream consumers."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(graph, [nid], token_index)
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type == '14':
            forced_overrides[nid] = 'FALSE'
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'switch_failure',
                'fatal': False,
                'sentence': (
                    f"The Switch (Type 14) '{name}' (ID: {nid}) would fail to evaluate; "
                    f"simulation forces the FALSE/default branch."
                ),
            })

        elif t_type == '31':
            actions = data.get('Action', []) or []
            action_str = ', '.join(str(a) for a in actions[:3]) if actions else 'state transition'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'trigger_failure', 'fatal': False,
                'sentence': (
                    f"The Trigger Action (Type 31) '{name}' (ID: {nid}) would be skipped; "
                    f"action(s) not fired: {action_str}."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '30':
            assocs = extract_associations(data)
            assoc_str = ', '.join(assocs[:3]) if assocs else 'association'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'association_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"{assoc_str} not formed."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '32':
            assocs = extract_associations(data)
            assoc_str = ', '.join(assocs[:3]) if assocs else 'association'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'association_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"{assoc_str} not removed."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '33':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'add_child_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"child record would not be added."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type in ('24', '20'):
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'loop_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"loop body would never be entered."
                ),
            })

        elif t_type == '23':
            ledger = extract_metadata_ledger(data)
            tabs = ledger['tabs']
            sections = ledger['sections']
            fields = ledger['fields']
            bo = ledger['bo']
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
                'tabs': tabs,
                'sections': sections,
                'fields': fields,
                'bo': bo,
                'property_changes': ledger['property_changes'],
            })
            failed_ids.append(nid)
            field_impacts.append({
                'task_id': nid,
                'bo': bo,
                'tabs': tabs,
                'sections': sections,
                'fields': fields,
                'kind': 'metadata',
            })
            target_parts = []
            if sections:
                target_parts.append(f"section(s) ({', '.join(sections)})")
            if fields:
                target_parts.append(f"field(s) ({', '.join(fields)})")
            if tabs and not target_parts:
                target_parts.append(f"tab(s) ({', '.join(tabs)})")
            targets_str = ' and '.join(target_parts) if target_parts else 'form properties'
            bo_part = f" on BO '{bo}'" if bo else ''
            prop_labels = sorted({
                f"{pc['prop_label']}={_format_prop_value(pc['value'])}"
                for pc in ledger['property_changes']
            })
            prop_part = f" ({', '.join(prop_labels)})" if prop_labels else ''
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'metadata_ledger',
                'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"will not apply UI changes to {targets_str}{bo_part}{prop_part}. "
                    f"Visibility, read-only, and required states will not propagate."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        else:
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'execution_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) "
                    f"would be skipped during execution."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

    return {
        'failed_tasks': failed_tasks,
        'failed_ids': failed_ids,
        'altered_from_failure': altered_from_failure,
        'field_impacts': field_impacts,
        'impacts': impacts,
        'forced_overrides': forced_overrides,
        'impacted_map': impacted_map,
        'unmatched': unmatched,
    }


