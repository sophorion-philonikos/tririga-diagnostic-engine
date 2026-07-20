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
from cli.simulation.parse import (
    Clause, SimulationRequest, parse_query,
    _tokenize, _expand_domain_tokens,
)

# ============================================================
# 3. CLAUSE -> BRANCHING-NODE MATCHER
# ============================================================

_MATCH_THRESHOLD = 1.5


def _node_token_bag(data):
    parts = [str(data.get('name', ''))]
    for key in ('Expression', 'LFldName', 'PField', 'RFldName', 'ConstantValue',
                'RValue', 'Value', 'BO', 'BoName', 'FilterBo', 'QueryName', 'VariableName'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        parts.extend(str(v) for v in val)
    return _tokenize(' '.join(parts))


def _node_constants(data):
    consts = []
    for key in ('ConstantValue', 'RValue', 'Value'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        consts.extend(str(v).strip().upper() for v in val if str(v).strip())
    return consts


def _field_tokens(data):
    parts = []
    for key in ('LFldName', 'PField', 'RFldName'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        parts.extend(str(v) for v in val)
    return _tokenize(' '.join(parts))


_BRANCH_TYPES = ('14', '24')
_TYPE_NOISE_TOKENS = frozenset({
    'switch', 'switches', 'gate', 'gates', 'decision', 'iter', 'iterator',
    'iteration', 'loop', 'task', 'tasks', 'true', 'false', 'forced', 'force',
})
_GENERIC_GATE_NAMES = frozenset({'switch', 'iter', 'iterator', 'loop', 'gate'})


def _branching_nodes(graph):
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.get_type_str(data) in _BRANCH_TYPES:
            out.append((str(nid), data))
    return sorted(out, key=lambda x: x[0])


def _branch_by_id(graph, nid):
    """Return (nid, data) if nid is a Switch/Iter node, else (None, None)."""
    nid = str(nid)
    if not graph.has_node(nid):
        return None, None
    data = graph.nodes[nid]
    if graph_utils.get_type_str(data) not in _BRANCH_TYPES:
        return None, None
    return nid, data


def match_clauses(engine, wf_name, clauses):
    """Deterministically bind each clause to Switch/Iter nodes with a forced verdict.

    Priority: explicit task id > constant/value assertions > semantic name/tokens.
    Returns (matched, unmatched): matched entries are dicts
    {node_id, node_name, verdict, clause, score, reason}.
    """
    graph = engine.graphs[wf_name]
    branch_nodes = _branching_nodes(graph)
    matched, unmatched = [], []
    forced_ids = set()

    def add_match(nid, data, verdict, clause, score, reason):
        if nid in forced_ids:
            return
        forced_ids.add(nid)
        matched.append({
            'node_id': nid,
            'node_name': str(data.get('name', f'Task {nid}')),
            'verdict': verdict,
            'clause': clause.text,
            'score': round(score, 2),
            'reason': reason,
        })

    for clause in clauses:
        c_tokens = _tokenize(clause.text) | _expand_domain_tokens(clause.text)
        if clause.value:
            c_tokens.add(clause.value.lower())
        c_field_tokens = _tokenize(clause.field_hint) if clause.field_hint else set()

        # --- Explicit task id (same contract as match_task) ---
        id_match = re.search(r'\b(\d{5,})\b', clause.text)
        if id_match:
            nid, data = _branch_by_id(graph, id_match.group(1))
            if nid is None:
                unmatched.append(clause.text)
                continue
            if clause.type_hint and graph_utils.get_type_str(data) != clause.type_hint:
                unmatched.append(clause.text)
                continue
            add_match(nid, data, clause.verdict, clause, 10.0, 'explicit task id')
            continue

        # --- Value assertions: force EVERY switch comparing that constant ---
        if clause.value:
            hit_any = False
            null_tokens = {'null', 'empty', 'blank'}
            for nid, data in branch_nodes:
                consts = _node_constants(data)
                node_fields = _field_tokens(data)
                node_bag = _node_token_bag(data)
                field_related = bool((c_field_tokens or c_tokens) & node_fields)
                if clause.value != 'NULL' and clause.value in consts:
                    # Switch tests the asserted constant: the comparison holds.
                    add_match(nid, data, clause.verdict, clause, 5.0,
                              f"constant '{clause.value}' matches this gate's comparison")
                    hit_any = True
                elif clause.value == 'NULL' and (node_bag & null_tokens):
                    add_match(nid, data, clause.verdict, clause, 3.0,
                              "null-check gate over the asserted field")
                    hit_any = True
                elif field_related and consts and clause.verdict == 'TRUE':
                    # Field definitively holds another value: mutually exclusive
                    # constant comparisons (including NULL assertions) must fail.
                    add_match(nid, data, 'FALSE', clause, 2.5,
                              f"gate compares the same field to a different constant ({', '.join(consts[:3])})")
                    hit_any = True
            if hit_any:
                continue

        # --- Semantic scoring (optional type_hint filter) ---
        candidates = branch_nodes
        if clause.type_hint:
            typed = [(nid, d) for nid, d in branch_nodes
                     if graph_utils.get_type_str(d) == clause.type_hint]
            if typed:
                candidates = typed

        content_tokens = c_tokens - _TYPE_NOISE_TOKENS
        name_hint = (clause.target_hint or '').strip().lower()
        scored = []
        for nid, data in candidates:
            name = str(data.get('name', ''))
            name_low = name.lower().strip()
            bag = _node_token_bag(data)
            overlap = len(content_tokens & bag)
            # Prefer label similarity to the gate name, not the whole clause
            # (avoids "switch … is true" ≈ TaskLabel "Switch").
            label_src = name_hint or ' '.join(sorted(content_tokens)) or clause.text.lower()
            name_ratio = difflib.SequenceMatcher(None, label_src, name_low).ratio()
            clause_ratio = difflib.SequenceMatcher(
                None, clause.text.lower(), name_low).ratio()
            score = overlap + 2.0 * max(name_ratio, clause_ratio * 0.5)
            if name_hint:
                if name_hint == name_low:
                    score += 4.0
                else:
                    score += 3.0 * difflib.SequenceMatcher(None, name_hint, name_low).ratio()
            elif name_low and name_low in clause.text.lower():
                score += 3.5  # bare label mention, e.g. "ACT? is true"
            scored.append((score, nid, data, name_low))

        if not scored:
            unmatched.append(clause.text)
            continue

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_nid, best_data, best_name = scored[0]

        # Ambiguous generic "Switch"/"Iter" labels with no real name/content hint:
        # refuse to guess (caller can supply an id).
        near = [t for t in scored if abs(t[0] - best_score) < 0.35 and t[0] >= _MATCH_THRESHOLD]
        generic_cluster = (
            len(near) > 1
            and all(t[3] in _GENERIC_GATE_NAMES for t in near)
            and not name_hint
            and not (content_tokens - _GENERIC_GATE_NAMES)
        )
        # Also: sole winner is generic label but query only had type noise + verdict.
        bare_type_guess = (
            best_name in _GENERIC_GATE_NAMES
            and not name_hint
            and not content_tokens
            and best_score < 4.0
        )
        if generic_cluster or bare_type_guess:
            unmatched.append(clause.text)
            continue

        if best_score >= _MATCH_THRESHOLD:
            add_match(best_nid, best_data, clause.verdict, clause, best_score,
                      'semantic token/name match')
        else:
            unmatched.append(clause.text)

    return matched, unmatched


# ============================================================
# 3b. ANY-TASK RESOLVER (data-state clauses)
# ============================================================

def _visible_nodes(graph):
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        out.append((str(nid), data))
    return sorted(out, key=lambda x: x[0])


def match_task(engine, wf_name, clause):
    """Resolve a data-state clause to a single task of ANY type.

    Scoring priority: explicit task id in the clause > quoted-label similarity
    (heavily weighted) > token overlap; a type hint filters candidates when it
    leaves at least one.
    """
    graph = engine.graphs[wf_name]
    candidates = _visible_nodes(graph)

    if clause.type_hint:
        typed = [(nid, d) for nid, d in candidates
                 if graph_utils.get_type_str(d) == clause.type_hint]
        if typed:
            candidates = typed

    id_match = re.search(r'\b(\d{5,})\b', clause.text)
    if id_match and graph.has_node(id_match.group(1)):
        nid = id_match.group(1)
        return nid, graph.nodes[nid], 10.0

    best = None
    c_tokens = _tokenize(clause.text) | _expand_domain_tokens(clause.text)
    for nid, data in candidates:
        name = str(data.get('name', ''))
        score = 0.0
        if clause.target_hint:
            label_ratio = difflib.SequenceMatcher(
                None, clause.target_hint.lower(), name.lower()).ratio()
            score += 6.0 * label_ratio
            if clause.target_hint.lower() == name.lower():
                score += 4.0
        bag = _node_token_bag(data)
        score += len(c_tokens & bag)
        score += 1.5 * difflib.SequenceMatcher(None, clause.text.lower(), name.lower()).ratio()
        if best is None or score > best[2]:
            best = (nid, data, score)

    if best and best[2] >= (_MATCH_THRESHOLD + 1.0 if clause.target_hint else _MATCH_THRESHOLD):
        return best
    return None, None, 0.0


