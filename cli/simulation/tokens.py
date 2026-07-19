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
from cli.knowledge import type_display_name as _tdn  # keep

# ============================================================
# 3c. TOKEN DEPENDENCY INDEX + NULL-TOKEN PROPAGATION
# ============================================================

# How each consumer type reacts to a starved (null/empty) object token.
# fatal=True means the task cannot perform its work and is bypassed.
_TOKEN_CONSEQUENCES = {
    '28': ('fail/bypass execution because it lacks the required target record context', True),
    '25': ('fail to expose temporary form data, leaving consumers without a usable temp token', True),
    '27': ('produce no created record token for its own consumers', True),
    '26': ('fail/bypass execution because there is no source record to save permanently', True),
    '30': ('be unable to form the association because the record token is missing', True),
    '32': ('be unable to remove the association because the record token is missing', True),
    '33': ('be unable to add the child record because the parent token is missing', True),
    '31': ('skip the state transition because there is no record to act on', True),
    '23': ('skip its metadata changes because the target record context is empty', True),
    '29': ('retrieve against an empty source context and likely return zero records itself', True),
    '22': ('run its query over an empty source context and likely return zero records itself', True),
    '24': ('iterate zero times, so its LOOP BODY branch is never entered', True),
    '20': ('loop zero times, so its body is never entered', True),
    '14': ('evaluate its condition over a null token, so its verdict may flip to the FALSE/default branch', False),
    '10': ('pass through as a structural fork/join without producing a record token', False),
    '38': ('invoke the sub-workflow with an empty record context', False),
    '40': ('define a workflow variable without a usable source value', False),
    '41': ('assign a null value to its workflow variable', False),
    '43': ('evaluate its fact condition over a null token', False),
    '17': ('schedule an event without a usable record context', False),
    '34': ('set the project context without a usable record token', False),
    '35': ('attach a format file without a usable record context', False),
    '36': ('populate a file without a usable record context', False),
    '37': ('distill a file without a usable record context', False),
    '39': ('invoke custom logic with an empty record context', False),
}
_DEFAULT_CONSEQUENCE = ('receive an empty object token from its source task', False)


def build_token_index(graph):
    """Map producer task id -> [(consumer id, ref kind)] from parsed TaskRefs.

    ``FromTask`` (UseType=1) is the consumer's primary record context;
    ``FilterTask`` (UseType=2) is its source/filter record token;
    ``AuxTask`` (UseType=3) is a tertiary context (e.g. Populate File).
    ``RefTaskId="0"`` is the workflow Start / trigger record and is indexed.
    """
    consumers = {}
    for nid, data in graph.nodes(data=True):
        for key, kind in (('FromTask', 'primary record context'),
                          ('FilterTask', 'source record token'),
                          ('AuxTask', 'auxiliary record context')):
            refs = data.get(key, [])
            if isinstance(refs, str):
                refs = [refs]
            for ref in refs:
                ref = str(ref)
                if ref in ('-1', ''):
                    continue
                consumers.setdefault(ref, []).append((str(nid), kind))
    return consumers


def propagate_null_token(graph, altered_ids, token_index, starve_cause='zero_records'):
    """BFS the consumer index from the altered tasks, classifying each casualty.

    ``starve_cause`` selects the narrative for why the producer's token is
    missing: ``zero_records`` (Retrieve/Query empty set) or ``task_failure``
    (Modify/Create or generic execution failure).

    Returns (impacted, impacts): ``impacted`` maps task id -> fatal flag;
    ``impacts`` is an ordered list of structured impact records with the
    context-aware narrative sentence.
    """
    cause_phrases = {
        'zero_records': 'were it to not retrieve any records',
        'task_failure': 'were it to fail or be skipped during execution',
    }
    origin_cause = cause_phrases.get(starve_cause, starve_cause)
    impacted = {}
    impacts = []
    queue = [(aid, aid) for aid in altered_ids]
    seen = set(altered_ids)

    def describe(nid):
        data = graph.nodes[nid]
        t_type = graph_utils.get_type_str(data)
        return data, t_type, type_display_name(t_type), str(data.get('name', f'Task {nid}'))

    while queue:
        producer_id, origin_id = queue.pop(0)
        for consumer_id, ref_kind in sorted(token_index.get(producer_id, [])):
            if consumer_id in seen or not graph.has_node(consumer_id):
                continue
            seen.add(consumer_id)

            _c_data, c_type, c_type_name, c_name = describe(consumer_id)
            p_data, p_type, p_type_name, p_name = describe(producer_id)
            consequence, fatal = _TOKEN_CONSEQUENCES.get(c_type, _DEFAULT_CONSEQUENCE)

            if producer_id == origin_id:
                cause = origin_cause
            else:
                cause = f"starved of records by upstream task {origin_id}"

            sentence = (
                f"The {p_type_name} (Type {p_type}) '{p_name}' (ID: {producer_id}), {cause}, "
                f"will cause the subsequent {c_type_name} (Type {c_type}) '{c_name}' "
                f"(ID: {consumer_id}) to {consequence} (it references task {producer_id} "
                f"as its {ref_kind})."
            )

            impacted[consumer_id] = fatal
            impacts.append({
                'producer_id': producer_id,
                'producer_name': p_name,
                'producer_type': p_type,
                'consumer_id': consumer_id,
                'consumer_name': c_name,
                'consumer_type': c_type,
                'ref_kind': ref_kind,
                'fatal': fatal,
                'origin_id': origin_id,
                'sentence': sentence,
            })

            # Fatal starvation propagates: a task with no record context
            # produces no token for its own downstream consumers.
            if fatal:
                queue.append((consumer_id, origin_id))

    return impacted, impacts


