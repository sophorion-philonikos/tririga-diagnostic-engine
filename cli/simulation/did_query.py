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
from cli.simulation.matching import match_task
from cli.simulation.impacts import path_to_task
from cli.simulation.parse import _tokenize, _expand_domain_tokens

# ============================================================
# 5. "DID X TRIGGER?" QUERY ANSWERER
# ============================================================

def answer_did_query(engine, wf_name, subject, trace_ids):
    """Answer 'did <subject> trigger?' against a live/simulated trace."""
    graph = engine.graphs[wf_name]
    s_tokens = _tokenize(subject) | _expand_domain_tokens(subject)

    best = None
    for nid, data in sorted(graph.nodes(data=True), key=lambda x: str(x[0])):
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        bag = _node_token_bag(data)
        overlap = len(s_tokens & bag)
        ratio = difflib.SequenceMatcher(
            None, subject.lower(), str(data.get('name', '')).lower()).ratio()
        score = overlap + 2.0 * ratio
        if best is None or score > best[0]:
            best = (score, str(nid), data)

    # The workflow itself may be the subject ("did the RE lease activation trigger?").
    wf_ratio = difflib.SequenceMatcher(None, subject.lower(), wf_name.lower()).ratio()
    wf_overlap = len(s_tokens & _tokenize(wf_name))

    if (best is None or best[0] < _MATCH_THRESHOLD) and (wf_overlap + 2.0 * wf_ratio) < _MATCH_THRESHOLD:
        return {
            'mode': 'did_query',
            'answer': f"I could not confidently map '{subject}' to a task in '{wf_name}'.",
            'evidence': "Try naming the task as it appears on the map, e.g. 'did Modify Records trigger?'.",
            'node_id': None,
            'executed': None,
        }

    if not trace_ids:
        return {
            'mode': 'did_query',
            'answer': "No live trace is loaded, so runtime execution cannot be confirmed.",
            'evidence': "Upload/scan a server log (or run 'trace live execution') first, then ask again.",
            'node_id': best[1] if best else None,
            'executed': None,
        }

    trace_set = {str(t) for t in trace_ids}

    if best and best[0] >= _MATCH_THRESHOLD and (wf_overlap + 2.0 * wf_ratio) <= best[0]:
        score, nid, data = best
        name = str(data.get('name', f'Task {nid}'))
        executed = nid in trace_set
        verdict = 'YES' if executed else 'NO'
        return {
            'mode': 'did_query',
            'answer': f"{verdict} - Task '{name}' ({nid}) {'appears' if executed else 'does NOT appear'} in the traced execution.",
            'evidence': f"Trace contains {len(trace_set)} executed task(s); matched '{subject}' to '{name}' (score {score:.2f}).",
            'node_id': nid,
            'executed': executed,
        }

    # Workflow-level answer.
    executed = bool(trace_set)
    return {
        'mode': 'did_query',
        'answer': f"{'YES' if executed else 'NO'} - workflow '{wf_name}' {'executed' if executed else 'did not execute'} in the traced log window.",
        'evidence': f"Trace contains {len(trace_set)} executed task(s) belonging to this workflow.",
        'node_id': None,
        'executed': executed,
    }


