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


def _branching_nodes(graph):
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.get_type_str(data) in ('14', '24'):
            out.append((str(nid), data))
    return sorted(out, key=lambda x: x[0])


def match_clauses(engine, wf_name, clauses):
    """Deterministically bind each clause to Switch/Iter nodes with a forced verdict.

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

        # --- Semantic scoring against each branching node ---
        best = None
        for nid, data in branch_nodes:
            bag = _node_token_bag(data)
            overlap = len(c_tokens & bag)
            name_ratio = difflib.SequenceMatcher(
                None, clause.text.lower(), str(data.get('name', '')).lower()).ratio()
            score = overlap + 2.0 * name_ratio
            if best is None or score > best[0]:
                best = (score, nid, data)

        if best and best[0] >= _MATCH_THRESHOLD:
            score, nid, data = best
            add_match(nid, data, clause.verdict, clause, score,
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


