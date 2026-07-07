"""Shared graph-topology helpers for the visualizer and the simulator.

TRIRIGA workflow XML contains invisible plumbing nodes (junction Types 11/12,
unnamed placeholders, generic scaffolding) that the visualizer never renders.
Both the HTML map and the What-If simulator must resolve routing *through*
those junctions identically, or simulated paths would reference nodes that do
not exist on screen. This module is the single source of truth for that rule.
"""


def get_type_str(data):
    t = data.get('type', data.get('Type', 'Generic'))
    if isinstance(t, list):
        return str(t[0])
    return str(t).strip()


def is_invisible(data):
    """True when a node is layout plumbing that the visualizer does not render."""
    t_type = get_type_str(data)
    name = str(data.get('name', ''))
    return t_type in ('12', '11') or (name.lower().startswith('unnamed') and t_type != '9') or t_type == 'generic'


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
