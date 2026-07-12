"""Shared graph-topology helpers for the visualizer and the simulator.

TRIRIGA workflow XML contains invisible plumbing nodes (junction Types 11/12
and generic scaffolding) that the visualizer never renders. Unnamed *business*
tasks (Switch, Continue, Break, Stop, etc.) remain visible even when their
TaskLabel is empty. Both the HTML map and the What-If simulator must resolve
routing *through* junctions identically, or simulated paths would reference
nodes that do not exist on screen. This module is the single source of truth
for that rule.
"""


def get_type_str(data):
    t = data.get('type', data.get('Type', 'Generic'))
    if isinstance(t, list):
        return str(t[0])
    return str(t).strip()


def is_invisible(data):
    """True when a node is layout plumbing that the visualizer does not render.

    Only junction Types 11/12 and generic stubs are hidden. Empty-label Switch
    (14), Continue (19), Break (21), Stop (13), etc. stay visible.
    """
    t_type = get_type_str(data)
    return t_type in ('11', '12') or t_type.lower() == 'generic'


def visible_successors(graph, start_id, visited=None):
    """Resolve the visible successor set of a node, skipping invisible junctions.

    Preserves the visualizer's historical contract exactly (deduplicated,
    unordered list); callers needing determinism should sort the result.
    """
    if visited is None:
        visited = set()
    targets = []
    for succ in graph.successors(start_id):
        succ_data = graph.nodes[succ]
        if is_invisible(succ_data):
            if succ not in visited:
                visited.add(succ)
                targets.extend(visible_successors(graph, succ, visited))
        else:
            targets.append(succ)
    return list(set(targets))


def resolve_to_visible(graph, node_id):
    """Map a raw target id to the visible node id(s) it lands on, sorted."""
    if graph.has_node(str(node_id)) and not is_invisible(graph.nodes[str(node_id)]):
        return [str(node_id)]
    if not graph.has_node(str(node_id)):
        return []
    return sorted(str(t) for t in visible_successors(graph, str(node_id)))


# Short display names used when TaskLabel is empty in the XML export.
_EMPTY_LABEL_NAMES = {
    '1': 'Start',
    '9': 'End',
    '10': 'Fork',
    '13': 'Stop',
    '14': 'Switch',
    '19': 'Continue',
    '21': 'Break',
    '24': 'Iter',
}


def default_task_name(t_type, node_id):
    """Type-aware fallback label when TaskLabel is missing."""
    code = str(t_type or '').strip()
    if code in _EMPTY_LABEL_NAMES:
        return _EMPTY_LABEL_NAMES[code]
    return f"Unnamed Component ({node_id})"
