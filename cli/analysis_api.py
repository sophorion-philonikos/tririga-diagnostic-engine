"""Structured analysis helpers for the Web UI (and future CLI reuse).

Mirrors the simulation pattern: return JSON-serializable dicts; leave ASCII
formatting to CLI handlers. Operates on a single workflow context.
"""

from __future__ import annotations

import networkx as nx

from cli import graph_utils
from cli.formatters import format_path_narrative
from cli.visualizer import WorkflowVisualizer


def _set_context(router, wf_name):
    if wf_name not in router.engine.graphs:
        raise ValueError(f"Workflow '{wf_name}' is not loaded in this session.")
    router.current_context_wf = wf_name
    return router.engine.graphs[wf_name]


def _resolve_node(graph, token):
    """Resolve task id or name within one graph. Returns (node_id, data) or None."""
    token = str(token or '').strip()
    if not token:
        return None
    if graph.has_node(token):
        return token, graph.nodes[token]
    tl = token.lower()
    for nid, data in graph.nodes(data=True):
        name = str(data.get('name', '')).lower()
        if name == tl or str(nid) == token:
            return nid, data
    # Substring / fuzzy-lite: unique name contains
    hits = []
    for nid, data in graph.nodes(data=True):
        name = str(data.get('name', '')).lower()
        if tl in name or tl in str(nid).lower():
            hits.append((nid, data))
    if len(hits) == 1:
        return hits[0]
    return None


def explain_task(router, wf_name, task):
    graph = _set_context(router, wf_name)
    resolved = _resolve_node(graph, task)
    if not resolved:
        raise ValueError(f"Could not find task '{task}' in '{wf_name}'.")
    node_id, data = resolved
    t_type = graph_utils.get_type_str(data)
    t_name = data.get('name', f'Task {node_id}')
    t_bo = data.get('BO', data.get('BoName', ''))
    if isinstance(t_bo, list):
        t_bo = t_bo[0] if t_bo else ''
    viz = WorkflowVisualizer(router.engine)
    insight = viz._build_task_insight(node_id, data, t_type, t_name, t_bo, graph=graph)
    payload = insight.to_dict()
    payload['workflow'] = wf_name
    payload['op'] = 'explain_task'
    return payload


def purpose(router, wf_name, path_limit=12):
    graph = _set_context(router, wf_name)
    meta = router.engine.workflow_metadata.get(wf_name, {})
    summary_text = router._explain_purpose(wf_name)

    target_bos, evaluated_fields, modified_data_fields = set(), set(), set()
    modified_gui_fields, modified_gui_sections, actions_triggered = set(), set(), set()
    task_types_found = {}
    for _node, data in graph.nodes(data=True):
        t_type = graph_utils.get_type_str(data)
        task_types_found[t_type] = task_types_found.get(t_type, 0) + 1
        for f in data.get('PField', []):
            evaluated_fields.add(f)
        for f in data.get('LFldName', []):
            evaluated_fields.add(f)
        for f in data.get('TrgtFld', []):
            modified_data_fields.add(f)
        for a in data.get('Action', []):
            actions_triggered.add(a)
        for f in data.get('Field', []):
            if f != '^^':
                modified_gui_fields.add(f)
        for gm in data.get('GUIMappings', []):
            sec = gm.get('Section')
            fld = gm.get('Field')
            if sec and sec != '^^':
                modified_gui_sections.add(sec)
            if fld and fld != '^^':
                modified_gui_fields.add(fld)
        bo = data.get('BO', data.get('BoName', data.get('PBO', data.get('ChildBO', data.get('RefObject')))))
        if bo and isinstance(bo, str):
            target_bos.add(bo)
        elif bo and isinstance(bo, list):
            target_bos.update(bo)
    target_bos.discard('System')
    target_bos.discard('Workflow')
    target_bos.discard('Any')

    all_paths = router._generate_all_paths(wf_name)
    notes = []
    if router.last_path_cycle_edges:
        edge_str = ", ".join("{}->{}".format(e[0], e[1]) for e in router.last_path_cycle_edges)
        notes.append(f"Cyclic routing detected. Loop edge(s): {edge_str}.")
    if router.last_path_generation_truncated:
        notes.append(
            f"Branching exceeded enumeration bound; first {router.MAX_ENUMERATED_PATHS} "
            "paths materialized."
        )

    capped = all_paths[: max(0, int(path_limit))]
    path_payloads = []
    total = len(all_paths)
    for i, path in enumerate(capped):
        path_payloads.append({
            'index': i + 1,
            'total': total,
            'steps': path,
            'narrative': format_path_narrative(path, i + 1, total),
        })

    return {
        'op': 'purpose',
        'workflow': wf_name,
        'name': meta.get('Name', wf_name),
        'description': meta.get('Description', ''),
        'event': meta.get('EventName'),
        'module': meta.get('Module'),
        'bo': meta.get('BO'),
        'summary': summary_text,
        'task_type_counts': task_types_found,
        'target_bos': sorted(target_bos),
        'evaluated_fields': sorted(evaluated_fields)[:40],
        'modified_data_fields': sorted(modified_data_fields)[:40],
        'modified_gui_fields': sorted(modified_gui_fields)[:40],
        'modified_gui_sections': sorted(modified_gui_sections)[:40],
        'actions_triggered': sorted(actions_triggered),
        'notes': notes,
        'path_count': total,
        'paths_returned': len(path_payloads),
        'paths': path_payloads,
    }


def find_refs(router, wf_name, term):
    graph = _set_context(router, wf_name)
    term = str(term or '').strip()
    if not term:
        raise ValueError('Provide a field, section, or expression term to search.')
    tl = term.lower()
    hits = []
    for node_id, data in graph.nodes(data=True):
        roles = []
        for f in data.get('TrgtFld', []):
            if tl == str(f).lower():
                roles.append('target_field')
        for f in data.get('Field', []):
            if tl == str(f).lower():
                roles.append('gui_field')
        for gm in data.get('GUIMappings', []):
            if tl in (
                str(gm.get('Section', '')).lower(),
                str(gm.get('Field', '')).lower(),
                str(gm.get('Tab', '')).lower(),
            ):
                roles.append('gui_mapping')
        for f in list(data.get('PField', [])) + list(data.get('LFldName', [])) + list(data.get('SrcFld', [])):
            if tl == str(f).lower():
                roles.append('filter_or_source')
        for exp in data.get('Expression', []):
            if tl in str(exp).lower():
                roles.append('expression')
        # Also match task name / id loosely for discoverability
        name = str(data.get('name', ''))
        if tl in name.lower() or tl == str(node_id).lower():
            roles.append('task_identity')
        if roles:
            hits.append({
                'id': str(node_id),
                'name': name or f'Task {node_id}',
                'type': graph_utils.get_type_str(data),
                'roles': sorted(set(roles)),
            })
    return {
        'op': 'refs',
        'workflow': wf_name,
        'term': term,
        'count': len(hits),
        'hits': hits,
    }


def trace_path(router, wf_name, from_task, to_task):
    graph = _set_context(router, wf_name)
    start = _resolve_node(graph, from_task)
    end = _resolve_node(graph, to_task)
    if not start:
        raise ValueError(f"Could not find start task '{from_task}'.")
    if not end:
        raise ValueError(f"Could not find end task '{to_task}'.")
    start_id, _ = start
    end_id, _ = end
    if not nx.has_path(graph, start_id, end_id):
        raise ValueError(
            f"No directed path from '{graph.nodes[start_id].get('name', start_id)}' "
            f"to '{graph.nodes[end_id].get('name', end_id)}' in '{wf_name}'."
        )
    path = nx.shortest_path(graph, start_id, end_id)
    path_names = [graph.nodes[n].get('name', n) for n in path]
    return {
        'op': 'path',
        'workflow': wf_name,
        'from_id': str(start_id),
        'to_id': str(end_id),
        'path_ids': [str(n) for n in path],
        'path_names': path_names,
        'length': len(path),
    }


def find_orphans(router, wf_name):
    graph = _set_context(router, wf_name)
    orphans = []
    for node, data in graph.nodes(data=True):
        t = graph_utils.get_type_str(data)
        if graph.in_degree(node) == 0 and t not in ('1', 'Trigger', 'Start'):
            orphans.append({
                'id': str(node),
                'name': data.get('name', f'Task {node}'),
                'type': t,
            })
    return {
        'op': 'orphans',
        'workflow': wf_name,
        'count': len(orphans),
        'orphans': orphans,
        'healthy': len(orphans) == 0,
    }


def analyze_failure(router, wf_name, task=None):
    graph = _set_context(router, wf_name)
    if not task:
        raise ValueError('Provide a task id or name for failure analysis.')
    resolved = _resolve_node(graph, task)
    if not resolved:
        raise ValueError(f"Could not find task '{task}' in '{wf_name}'.")
    node_id, data = resolved
    t_type = graph_utils.get_type_str(data)
    t_name = data.get('name', f'Task {node_id}')
    predecessors = []
    structural_orphan = False
    in_edges = list(graph.predecessors(node_id))
    if not in_edges and t_type not in ('1', 'Trigger', 'Start'):
        structural_orphan = True
    for parent_id in in_edges:
        parent_data = graph.nodes[parent_id]
        parent_name = parent_data.get('name', parent_id)
        p_type = graph_utils.get_type_str(parent_data)
        constraints = []
        expressions = parent_data.get('Expression', [])
        fields = parent_data.get('PField', [])
        filters = parent_data.get('LFldName', [])
        queries = parent_data.get('QueryName', [])
        assocs = parent_data.get('AssociationName', parent_data.get('AssocName', []))
        if expressions:
            constraints.append({
                'kind': 'condition',
                'detail': ', '.join(expressions),
            })
        if fields or filters:
            constraints.append({
                'kind': 'data_filter',
                'detail': ', '.join(list(fields) + list(filters)),
            })
        if queries:
            constraints.append({
                'kind': 'query',
                'detail': ', '.join(queries),
            })
        if assocs:
            a_list = assocs if isinstance(assocs, list) else [assocs]
            constraints.append({
                'kind': 'association',
                'detail': ', '.join(a_list),
            })
        predecessors.append({
            'id': str(parent_id),
            'name': parent_name,
            'type': p_type,
            'constraints': constraints,
        })
    summary_lines = [
        f"Root-cause analysis for '{t_name}' (ID: {node_id}, Type {t_type}).",
    ]
    if structural_orphan:
        summary_lines.append('Structural orphan: no incoming logic routes.')
    elif predecessors:
        summary_lines.append(f'{len(predecessors)} predecessor constraint source(s) to verify.')
    else:
        summary_lines.append('Start/Trigger node — no upstream prerequisites.')
    summary_lines.append(
        "If preceding constraints are met, verify this task's payload mapping has valid sources."
    )
    return {
        'op': 'failure',
        'workflow': wf_name,
        'task_id': str(node_id),
        'task_name': t_name,
        'type': t_type,
        'structural_orphan': structural_orphan,
        'predecessors': predecessors,
        'summary': summary_lines,
    }


OPS = {
    'explain_task': lambda router, wf, payload: explain_task(router, wf, payload.get('task')),
    'purpose': lambda router, wf, payload: purpose(
        router, wf, path_limit=int(payload.get('path_limit') or 12)
    ),
    'refs': lambda router, wf, payload: find_refs(router, wf, payload.get('term')),
    'path': lambda router, wf, payload: trace_path(
        router, wf, payload.get('from') or payload.get('from_task'),
        payload.get('to') or payload.get('to_task'),
    ),
    'orphans': lambda router, wf, payload: find_orphans(router, wf),
    'failure': lambda router, wf, payload: analyze_failure(router, wf, payload.get('task')),
}


def run_analyze(router, wf_name, op, payload=None):
    """Dispatch an analysis op. Raises ValueError for bad input."""
    payload = payload or {}
    op = str(op or '').strip().lower()
    if op not in OPS:
        raise ValueError(
            f"Unknown analyze op '{op}'. "
            f"Supported: {', '.join(sorted(OPS))}."
        )
    return OPS[op](router, wf_name, payload)
