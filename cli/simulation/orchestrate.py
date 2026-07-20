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
from cli.simulation.parse import parse_query, SimulationRequest
from cli.simulation.matching import match_clauses, match_task
from cli.simulation.tokens import build_token_index, propagate_null_token
from cli.simulation.failures import analyze_task_failures, find_field_dependent_nodes
from cli.simulation.impacts import (
    build_impact_tree, force_verdicts_for_path, path_edges_from_nodes,
    path_to_task, simulate, _dedupe_impacts, _start_nodes,
)
from cli.simulation.did_query import answer_did_query

# ============================================================
# 6. TOP-LEVEL ENTRY POINT (shared by CLI and Web)
# ============================================================

def run_simulation(engine, wf_name, query_text, trace_ids=None):
    """Parse -> match -> simulate. Returns a JSON-serializable result dict."""
    if wf_name not in engine.graphs:
        raise ValueError(f"Cannot simulate: workflow '{wf_name}' is not loaded.")

    request = parse_query(query_text)

    if request.mode == 'did_query':
        result = answer_did_query(engine, wf_name, request.subject, trace_ids)
        result['workflow'] = wf_name
        return result

    graph = engine.graphs[wf_name]
    gate_clauses = [c for c in request.clauses if c.kind == 'gate']
    data_clauses = [c for c in request.clauses if c.kind == 'data_state']
    failure_clauses = [c for c in request.clauses if c.kind == 'task_failure']

    matched, unmatched = match_clauses(engine, wf_name, gate_clauses)

    # --- Task failure simulation ---
    failure_result = analyze_task_failures(engine, wf_name, failure_clauses)
    failed_tasks = failure_result['failed_tasks']
    failed_ids = failure_result['failed_ids']
    field_impacts = failure_result['field_impacts']
    impacts = list(failure_result['impacts'])
    impacted_map = dict(failure_result['impacted_map'])
    unmatched.extend(failure_result['unmatched'])
    forced = {m['node_id']: m['verdict'] for m in matched}
    forced.update(failure_result['forced_overrides'])

    # Matched gates must be reachable: default FALSE-spine often never visits a
    # nested Switch. Force ancestor Switch/Iter verdicts along a path to each
    # matched gate (same helper used for failed/altered targets). Never override
    # an explicit user/failure force already in ``forced``.
    for m in matched:
        reach = path_to_task(graph, str(m['node_id']))
        if not reach:
            continue
        for nid, verdict in force_verdicts_for_path(engine, wf_name, reach).items():
            if nid not in forced:
                forced[nid] = verdict

    # --- Dataflow token simulation for zero-record clauses ---
    # Type 29/22 task_failure already propagated inside analyze_task_failures;
    # only data_state clauses need a fresh propagate_null_token pass.
    altered_from_failure = list(failure_result['altered_from_failure'])
    altered_from_failure_ids = {a['node_id'] for a in altered_from_failure}
    altered = list(altered_from_failure)
    for clause in data_clauses:
        nid, data, score = match_task(engine, wf_name, clause)
        if nid is None:
            unmatched.append(clause.text)
            continue
        t_type = graph_utils.get_type_str(data)
        altered.append({
            'node_id': nid,
            'node_name': str(data.get('name', f'Task {nid}')),
            'node_type': t_type,
            'node_type_name': type_display_name(t_type),
            'clause': clause.text,
            'score': round(score, 2),
        })

    data_state_altered = [a for a in altered if a['node_id'] not in altered_from_failure_ids]
    if data_state_altered:
        token_index = build_token_index(graph)
        extra_map, extra_impacts = propagate_null_token(
            graph, [a['node_id'] for a in data_state_altered], token_index)
        for cid, fatal in extra_map.items():
            impacted_map[cid] = impacted_map.get(cid, False) or fatal
        impacts.extend(extra_impacts)

    impacts = _dedupe_impacts(impacts)

    altered_ids = [a['node_id'] for a in altered]
    impacted_ids = sorted(impacted_map.keys())
    fatal_ids = {nid for nid, fatal in impacted_map.items() if fatal}

    # Path overlay target: explicit failed task, else primary altered (Retrieve/Query).
    path_forced_note = None
    failure_path = []
    path_target = None
    path_kind = 'failed'
    if failed_ids:
        path_target = str(failed_ids[0])
        path_kind = 'failed'
    elif altered:
        path_target = str(altered[0]['node_id'])
        path_kind = 'altered'

    if path_target:
        failure_path = path_to_task(graph, path_target)
        if failure_path:
            path_forced = force_verdicts_for_path(engine, wf_name, failure_path)
            for nid, verdict in path_forced.items():
                if nid not in forced:
                    forced[nid] = verdict

    walk = simulate(engine, wf_name, forced)

    # Ensure the highlighted path reaches the simulation target (failed or altered).
    if path_target and failure_path:
        if path_target not in {str(n) for n in walk['path_node_ids']}:
            walk = {
                'path_node_ids': list(failure_path),
                'path_edges': path_edges_from_nodes(failure_path),
                'decisions': walk['decisions'] + [
                    f"Highlighted path to {path_kind} task {path_target}; "
                    f"structural FALSE-spine may differ."
                ],
                'bypassed': walk['bypassed'],
            }
            path_forced_note = (
                f"Highlighted path to {path_kind} task {path_target}; "
                f"structural FALSE-spine may differ."
            )
        else:
            ids = [str(n) for n in walk['path_node_ids']]
            cut = ids.index(path_target) + 1
            trimmed = ids[:cut]
            walk['path_node_ids'] = trimmed
            walk['path_edges'] = path_edges_from_nodes(trimmed)
            visible_ids = {str(n) for n, d in graph.nodes(data=True)
                           if not (graph_utils.is_invisible(d) and graph.out_degree(n) > 0)}
            walk['bypassed'] = sorted(
                str(graph.nodes[n].get('name', f'Task {n}'))
                for n in visible_ids - set(trimmed)
            )

    # --- Narrative summary: failure + impact sentences lead ---
    summary = []
    for ft in failed_tasks:
        fld_part = ''
        if ft.get('node_type') == '23':
            meta_parts = []
            if ft.get('sections'):
                meta_parts.append(f"sections: {', '.join(ft['sections'])}")
            if ft.get('tabs'):
                meta_parts.append(f"tabs: {', '.join(ft['tabs'])}")
            if ft.get('fields'):
                meta_parts.append(f"fields: {', '.join(ft['fields'])}")
            if meta_parts:
                fld_part = f" — UI not updated ({'; '.join(meta_parts)})"
                if ft.get('bo'):
                    fld_part += f" on {ft['bo']}"
        elif ft.get('fields'):
            fld_part = f" — fields not updated: {', '.join(ft['fields'])}"
            if ft.get('bo'):
                fld_part += f" on {ft['bo']}"
        summary.append(
            f"Simulated execution failure for {ft['node_type_name']} (Type {ft['node_type']}) "
            f"'{ft['node_name']}' (ID: {ft['node_id']}){fld_part}."
        )
    for a in altered:
        summary.append(f"Simulated a zero-records / null-token state for the "
                       f"{a['node_type_name']} (Type {a['node_type']}) '{a['node_name']}' (ID: {a['node_id']}).")
    for imp in impacts:
        summary.append(imp['sentence'])
    for m in matched:
        summary.append(f"Gate '{m['node_name']}' ({m['node_id']}) forced {m['verdict']} - {m['reason']}.")
    if path_forced_note:
        summary.append(path_forced_note)
    if not matched and not altered and not failed_tasks:
        summary.append("No specific condition matched a decision gate or task; showing the default (FALSE-spine) route.")
    if unmatched:
        summary.append("Unmatched phrase(s): " + '; '.join(f"'{u}'" for u in unmatched))

    executed_names = [str(graph.nodes[n].get('name', n)) for n in walk['path_node_ids']
                      if graph.has_node(n)]
    end_reached = any(graph_utils.get_type_str(graph.nodes[n]) in ('9', '13')
                      for n in walk['path_node_ids'] if graph.has_node(n))
    on_path_fatal = [n for n in walk['path_node_ids'] if n in fatal_ids]
    if path_target and path_target in {str(n) for n in walk['path_node_ids']}:
        route_line = (
            f"Highlighted path to {path_kind} task {path_target} "
            f"({len(walk['path_node_ids'])} task(s) from Start)."
        )
    else:
        route_line = f"Simulated route executes {len(walk['path_node_ids'])} task(s)"
        if on_path_fatal:
            route_line += (f", of which {len(on_path_fatal)} would fail or bypass "
                           f"due to the missing record token")
        route_line += " and reaches an End task." if end_reached else " and stops before any End task."
    summary.append(route_line)
    if walk['bypassed']:
        shown = walk['bypassed'][:8]
        more = len(walk['bypassed']) - len(shown)
        summary.append("Bypassed: " + ', '.join(f"'{b}'" for b in shown)
                       + (f" (+{more} more)" if more > 0 else "") + ".")

    root_ids = list(failed_ids) + [a for a in altered_ids if a not in failed_ids]
    impact_tree = build_impact_tree(
        impacts, root_ids, failed_tasks=failed_tasks, altered_tasks=altered)

    return {
        'mode': 'what_if',
        'workflow': wf_name,
        'matched_conditions': matched,
        'unmatched_phrases': unmatched,
        'altered_tasks': altered,
        'altered_node_ids': altered_ids,
        'failed_tasks': failed_tasks,
        'failed_node_ids': failed_ids,
        'field_impacts': field_impacts,
        'impacted_node_ids': impacted_ids,
        'impacts': impacts,
        'impact_tree': impact_tree,
        'path_node_ids': walk['path_node_ids'],
        'path_edges': walk['path_edges'],
        'decisions': walk['decisions'],
        'bypassed': walk['bypassed'],
        'summary': summary,
        'executed_names': executed_names,
    }
