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

# ============================================================
# 4. DETERMINISTIC PATHFINDING (bounded, cycle-aware)
# ============================================================

def _start_nodes(graph):
    roots = [n for n in graph.nodes() if graph.in_degree(n) == 0]
    starters = [n for n in roots
                if graph_utils.get_type_str(graph.nodes[n]) in ('1', 'Trigger', 'Start')]
    return sorted(starters or roots)


def path_to_task(graph, target_id):
    """Shortest simple path from a Start node to ``target_id`` (string node ids).

    Returns a list of node ids including start and target, or [] if unreachable.
    """
    target_id = str(target_id)
    if not graph.has_node(target_id):
        return []
    best = None
    for start in _start_nodes(graph):
        start = str(start)
        if start == target_id:
            return [start]
        try:
            path = nx.shortest_path(graph, start, target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        path = [str(n) for n in path]
        if best is None or len(path) < len(best):
            best = path
    return best or []


def path_edges_from_nodes(path_ids):
    """Consecutive [from, to] pairs for a node id list."""
    return [[path_ids[i], path_ids[i + 1]] for i in range(len(path_ids) - 1)]


def _dedupe_impacts(impacts):
    """Keep each discrete impact relationship exactly once (by sentence)."""
    seen, out = set(), []
    for imp in impacts:
        key = imp.get('sentence') or (
            imp.get('producer_id'), imp.get('consumer_id'), imp.get('ref_kind'))
        if key in seen:
            continue
        seen.add(key)
        out.append(imp)
    return out


def _task_label(type_name, t_type, name, tid):
    if not type_name:
        type_name = type_display_name(t_type) if t_type else 'Task'
    if t_type:
        return f"{type_name} (Type {t_type}) '{name}' (ID: {tid})"
    return f"{type_name} '{name}' (ID: {tid})"


def build_impact_tree(impacts, root_ids, failed_tasks=None, altered_tasks=None):
    """Nest flat impacts by producer→consumer under altered/failed root ids.

    Returns a list of tree nodes:
      {task_id, task_name, task_type, task_type_name, label, badge, sentence,
       ref_kind, fatal, informational, direct_count, nested_count, children}
    """
    failed_tasks = failed_tasks or []
    altered_tasks = altered_tasks or []
    meta = {}

    for ft in failed_tasks:
        tid = str(ft['node_id'])
        meta[tid] = {
            'task_name': ft.get('node_name', f'Task {tid}'),
            'task_type': ft.get('node_type', ''),
            'task_type_name': ft.get('node_type_name', ''),
            'badge': 'failed',
        }
    for a in altered_tasks:
        tid = str(a['node_id'])
        if tid not in meta:
            meta[tid] = {
                'task_name': a.get('node_name', f'Task {tid}'),
                'task_type': a.get('node_type', ''),
                'task_type_name': a.get('node_type_name', ''),
                'badge': 'altered',
            }

    for imp in impacts:
        for id_key, name_key, type_key in (
            ('producer_id', 'producer_name', 'producer_type'),
            ('consumer_id', 'consumer_name', 'consumer_type'),
        ):
            tid = imp.get(id_key)
            if not tid:
                continue
            tid = str(tid)
            if tid in meta:
                continue
            t_type = str(imp.get(type_key) or '')
            meta[tid] = {
                'task_name': imp.get(name_key) or f'Task {tid}',
                'task_type': t_type,
                'task_type_name': type_display_name(t_type) if t_type else 'Task',
                'badge': 'broken',
            }

    children_map = {}
    root_sentences = {}
    for imp in impacts:
        pid = str(imp.get('producer_id') or '')
        if not pid:
            continue
        cid = imp.get('consumer_id')
        if cid is None or cid == '':
            root_sentences.setdefault(pid, imp)
            continue
        children_map.setdefault(pid, []).append(imp)

    def _count_descendants(node):
        total = 0
        for child in node.get('children') or []:
            total += 1 + _count_descendants(child)
        return total

    def _make_node(task_id, edge_imp=None, depth=0):
        tid = str(task_id)
        m = meta.get(tid, {})
        if edge_imp and depth > 0:
            t_type = str(edge_imp.get('consumer_type') or m.get('task_type') or '')
            name = edge_imp.get('consumer_name') or m.get('task_name') or f'Task {tid}'
        else:
            t_type = str(m.get('task_type') or '')
            name = m.get('task_name') or f'Task {tid}'
        type_name = m.get('task_type_name') or (type_display_name(t_type) if t_type else 'Task')

        if depth == 0:
            badge = m.get('badge', 'info')
        elif (edge_imp or {}).get('informational'):
            badge = 'info'
        else:
            badge = 'broken'

        node = {
            'task_id': tid,
            'task_name': name,
            'task_type': t_type,
            'task_type_name': type_name,
            'label': _task_label(type_name, t_type, name, tid),
            'badge': badge,
            'sentence': '',
            'ref_kind': (edge_imp or {}).get('ref_kind') or '',
            'fatal': (edge_imp or {}).get('fatal'),
            'informational': (edge_imp or {}).get('informational'),
            'children': [],
        }
        if depth == 0 and tid in root_sentences:
            rs = root_sentences[tid]
            node['sentence'] = rs.get('sentence') or ''
            node['ref_kind'] = rs.get('ref_kind') or node['ref_kind']
            node['informational'] = rs.get('informational')
        elif edge_imp:
            node['sentence'] = edge_imp.get('sentence') or ''

        for child_imp in children_map.get(tid, []):
            child_id = str(child_imp['consumer_id'])
            node['children'].append(_make_node(child_id, child_imp, depth + 1))

        node['direct_count'] = len(node['children'])
        node['nested_count'] = _count_descendants(node)
        return node

    roots = []
    seen_roots = set()
    for rid in root_ids:
        rid = str(rid)
        if not rid or rid in seen_roots:
            continue
        seen_roots.add(rid)
        roots.append(_make_node(rid, None, 0))

    reachable = set()

    def _collect(node):
        reachable.add(node['task_id'])
        for child in node.get('children') or []:
            _collect(child)

    for root in roots:
        _collect(root)

    for pid in sorted(children_map.keys()):
        if pid not in reachable and pid not in seen_roots:
            seen_roots.add(pid)
            roots.append(_make_node(pid, None, 0))

    return roots


def force_verdicts_for_path(engine, wf_name, path_ids):
    """Derive Switch/Iter forced verdicts so ``simulate`` follows ``path_ids``.

    For each branching node on the path, pick the branch label whose resolved
    visible target continues along the path. Returns node_id -> verdict map.
    """
    graph = engine.graphs[wf_name]
    path_set = {str(n) for n in path_ids}
    path_list = [str(n) for n in path_ids]
    forced = {}

    for i, nid in enumerate(path_list):
        if not graph.has_node(nid):
            continue
        data = graph.nodes[nid]
        t_type = graph_utils.get_type_str(data)
        if t_type not in ('14', '24'):
            continue
        # Prefer the next path node after this gate (skipping invisible hops).
        remaining = set(path_list[i + 1:])
        branch_map = engine.get_branch_map(data)
        chosen_label = None
        for raw_target, label in branch_map.items():
            visibles = graph_utils.resolve_to_visible(graph, raw_target)
            if any(str(v) in remaining or str(v) in path_set for v in visibles):
                # Prefer a visible successor that is the immediate next on path.
                if any(str(v) in remaining for v in visibles):
                    chosen_label = label
                    break
                if chosen_label is None:
                    chosen_label = label
        if chosen_label is None:
            continue
        if t_type == '14':
            forced[nid] = chosen_label if chosen_label in ('TRUE', 'FALSE') else chosen_label
        else:
            # Iter: TRUE means LOOP BODY, FALSE/other means EXIT
            forced[nid] = 'TRUE' if chosen_label == 'LOOP BODY' else 'FALSE'
    return forced


def simulate(engine, wf_name, forced):
    """Replay the workflow under forced branch verdicts.

    ``forced`` maps node_id -> 'TRUE'/'FALSE'. Switches not forced follow the
    FALSE/default spine; Iter tasks take LOOP BODY when forced TRUE, otherwise
    EXIT. Traversal is a worklist walk over VISIBLE nodes only (junctions are
    resolved through), guarded by a traversed-edge set so cycles terminate.

    Returns dict(path_node_ids, path_edges, decisions, bypassed).
    """
    graph = engine.graphs[wf_name]
    starts = _start_nodes(graph)
    if not starts:
        return {'path_node_ids': [], 'path_edges': [], 'decisions': [], 'bypassed': []}

    path_nodes, path_edges, decisions = [], [], []
    seen_nodes, seen_edges = set(), set()

    # Resolve possibly-invisible start to the first visible node(s).
    queue = []
    for s in starts:
        for vid in ([s] if not graph_utils.is_invisible(graph.nodes[s])
                    else graph_utils.resolve_to_visible(graph, s)):
            if vid not in seen_nodes:
                seen_nodes.add(vid)
                queue.append(vid)

    while queue:
        nid = queue.pop(0)
        data = graph.nodes[nid]
        path_nodes.append(nid)
        t_type = graph_utils.get_type_str(data)
        name = str(data.get('name', f'Task {nid}'))

        if t_type in ('14', '24'):
            branch_map = engine.get_branch_map(data)  # raw target id -> label
            if t_type == '14':
                desired = forced.get(nid, 'FALSE')
                origin = 'forced' if nid in forced else 'default'
            else:
                desired = 'LOOP BODY' if forced.get(nid) == 'TRUE' else 'EXIT'
                origin = 'forced' if nid in forced else 'default'

            chosen_raw = None
            for raw_target, label in branch_map.items():
                if label == desired:
                    chosen_raw = raw_target
                    break
            if chosen_raw is None and branch_map:
                chosen_raw = sorted(branch_map.keys())[0]
                desired = branch_map[chosen_raw]

            gate = 'Switch' if t_type == '14' else 'Iter'
            decisions.append(f"{gate} '{name}' ({nid}): {origin} {desired}")

            targets = graph_utils.resolve_to_visible(graph, chosen_raw) if chosen_raw else []
        else:
            targets = sorted(str(t) for t in graph_utils.visible_successors(graph, nid))

        for target in targets:
            edge = (nid, target)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            path_edges.append([nid, target])
            if target not in seen_nodes:
                seen_nodes.add(target)
                queue.append(target)

    visible_ids = {str(n) for n, d in graph.nodes(data=True)
                   if not (graph_utils.is_invisible(d) and graph.out_degree(n) > 0)}
    bypassed = sorted(
        (str(graph.nodes[n].get('name', f'Task {n}')) for n in visible_ids - set(path_nodes)),
    )

    return {
        'path_node_ids': path_nodes,
        'path_edges': path_edges,
        'decisions': decisions,
        'bypassed': bypassed,
    }


