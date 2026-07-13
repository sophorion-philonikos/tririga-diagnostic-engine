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
    '20': 'Loop',
    '21': 'Break',
    '24': 'Iter',
}

CONTAINER_TYPES = frozenset({'20', '24'})
CLUSTER_ID_PREFIX = 'c_'


def cluster_wrapper_id(container_id):
    """Synthetic Dagre cluster id — must not be used as an edge endpoint.

    Dagre throws ``Cannot set properties of undefined (setting 'rank')`` when an
    edge touches a compound parent. Real Iter/Loop task ids stay leaf nodes;
    this wrapper is the setParent target only.
    """
    return f'{CLUSTER_ID_PREFIX}{container_id}'


def is_cluster_wrapper_id(node_id):
    return str(node_id).startswith(CLUSTER_ID_PREFIX)


def default_task_name(t_type, node_id):
    """Type-aware fallback label when TaskLabel is missing."""
    code = str(t_type or '').strip()
    if code in _EMPTY_LABEL_NAMES:
        return _EMPTY_LABEL_NAMES[code]
    return f"Unnamed Component ({node_id})"


def _nx_has_path(graph, source, target):
    import networkx as nx
    return nx.has_path(graph, source, target)


def _cycle_members(graph, container_id):
    """Nodes that participate in a directed cycle with container_id (incl. invisible).

    BFS outward from the container; keep n iff n can reach the container again.
    TargetAssociation EXIT ids are NOT excluded — cycling tasks (e.g. Retrieve
    330919) nest inside even when labeled EXIT for edge text.
    """
    container_id = str(container_id)
    if not graph.has_node(container_id):
        return set()

    reachable = set()
    stack = [str(s) for s in graph.successors(container_id)]
    seen = set(stack)
    while stack:
        cur = stack.pop()
        if cur == container_id:
            continue
        reachable.add(cur)
        for succ in graph.successors(cur):
            s = str(succ)
            if s == container_id or s in seen:
                continue
            seen.add(s)
            stack.append(s)

    members = set()
    for n in reachable:
        try:
            if _nx_has_path(graph, n, container_id):
                members.add(n)
        except Exception:
            continue
    return members


def iter_body_members(graph, iter_id):
    """Cycle-based body of an Iter (24). Type 11 junctions may appear for walking."""
    return _cycle_members(graph, iter_id)


def loop_body_members(graph, loop_id):
    """Cycle-based body of a Loop (20). Break escapes (no return) are excluded."""
    return _cycle_members(graph, loop_id)


def compute_container_parents(graph, branch_map_fn=None):
    """Map visible child id -> nearest enclosing Iter/Loop container id.

    Returns (parents, container_ids, members_by_container).
    Invisible junctions are walked for membership but omitted from parents.
    branch_map_fn is accepted for API compatibility; nesting ignores TA labels.
    """
    del branch_map_fn  # nesting is cycle-based, not TargetAssociation-based
    container_ids = set()
    members_by_container = {}

    for node_id, data in graph.nodes(data=True):
        nid = str(node_id)
        t = get_type_str(data)
        if t not in CONTAINER_TYPES:
            continue
        container_ids.add(nid)
        members_by_container[nid] = (
            iter_body_members(graph, nid) if t == '24' else loop_body_members(graph, nid)
        )

    claims = {}
    for cid, members in members_by_container.items():
        for mid in members:
            claims.setdefault(str(mid), set()).add(cid)

    def _is_viz_child(child):
        if not graph.has_node(child):
            return False
        if is_invisible(graph.nodes[child]) and child not in container_ids:
            return False
        return True

    def _nearest(child, candidates):
        inner = [
            c for c in candidates
            if any(c in members_by_container.get(o, ()) for o in candidates if o != c)
        ]
        pool = inner if inner else list(candidates)
        return min(pool, key=lambda c: len(members_by_container.get(c, ())))

    parents = {}
    for child, candidates in claims.items():
        if not _is_viz_child(child):
            continue
        parent = _nearest(child, candidates)
        if parent != child:
            parents[child] = parent

    return parents, container_ids, members_by_container


def is_loop_back_edge(src, dst, parents, container_ids, members_by_container,
                      container_successors=None):
    """True when edge src→dst returns into a container (DAG layout exception)."""
    src, dst = str(src), str(dst)
    if dst not in container_ids:
        return False
    if src == dst:
        return True
    if src in members_by_container.get(dst, ()):
        return True
    if parents.get(src) == dst:
        return True
    if container_successors and src in container_successors.get(dst, ()):
        return True
    return False
