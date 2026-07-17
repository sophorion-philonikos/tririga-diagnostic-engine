"""Task-relationship analysis over the workflow DiGraph.

Answers questions like "What does task 333395 have to do with the Start task?",
"How does X reach Y?", "Is X upstream of Y?", and "What must be true for
execution to reach task X?".

All analysis operates on the full networkx.DiGraph (the single source of truth);
when multiple routes connect two tasks we report the route count and enumerate a
bounded sample of distinct switch-verdict combinations rather than collapsing
the topology into one line.
"""

import networkx as nx
from cli import graph_utils

# Bounds for route enumeration between two specific tasks. Enumerating every
# simple path is exponential in the worst case, so we sample a bounded set and
# always report the true route count separately.
MAX_ROUTES_TO_SHOW = 5
MAX_ROUTES_TO_COUNT = 100


def _is_invisible(data, get_type_str=None):
    return graph_utils.is_invisible(data)


def _display_name(graph, node, get_type_str):
    data = graph.nodes[node]
    return f"'{data.get('name', f'Task {node}')}' (ID: {node}, Type {get_type_str(data)})"


def _switch_expression(data):
    exp = data.get('Expression', [])
    if isinstance(exp, str):
        exp = [exp]
    return ", ".join(exp) if exp else "its condition"


def _branch_verdict_for_next_hop(engine, graph, switch_node, next_hop):
    """Which verdict (TRUE/FALSE) does taking `next_hop` from `switch_node` imply?

    The truth map is keyed by raw TargetAssociation ids, which may be invisible
    junctions; we resolve each raw branch target forward (can it reach/equal the
    next hop without passing back through the switch?) to attribute the verdict.
    """
    truth_map = engine.get_switch_truth_map(graph.nodes[switch_node])
    for raw_target, verdict in truth_map.items():
        raw_target = str(raw_target)
        if raw_target == str(next_hop):
            return verdict
        if graph.has_node(raw_target):
            if nx.has_path(graph, raw_target, str(next_hop)):
                return verdict
    return 'FALSE'


def classify_relation(graph, a, b):
    """Classify the topological relationship between two nodes.

    Returns one of: 'same', 'downstream' (a reaches b), 'upstream' (b reaches a),
    'parallel' (share a common ancestor but neither reaches the other), 'unrelated'.
    """
    if str(a) == str(b):
        return 'same'
    if nx.has_path(graph, a, b):
        return 'downstream'
    if nx.has_path(graph, b, a):
        return 'upstream'
    anc_a = nx.ancestors(graph, a)
    anc_b = nx.ancestors(graph, b)
    if anc_a & anc_b:
        return 'parallel'
    return 'unrelated'


def _divergence_switch(graph, a, b, get_type_str):
    """For parallel tasks, find the deepest common-ancestor Switch where they diverge."""
    common = nx.ancestors(graph, a) & nx.ancestors(graph, b)
    switches = [n for n in common if get_type_str(graph.nodes[n]) == '14']
    if not switches:
        return None
    # Deepest = the switch with the most ancestors of its own (closest to a/b).
    return max(switches, key=lambda n: len(nx.ancestors(graph, n)))


def _enumerate_routes(graph, src, dst):
    """Bounded simple-path enumeration src->dst. Returns (sample_routes, true_or_capped_count, capped)."""
    routes = []
    count = 0
    capped = False
    try:
        for path in nx.all_simple_paths(graph, src, dst):
            count += 1
            if len(routes) < MAX_ROUTES_TO_SHOW:
                routes.append(path)
            if count >= MAX_ROUTES_TO_COUNT:
                capped = True
                break
    except nx.NodeNotFound:
        pass
    return routes, count, capped


def _describe_route(engine, graph, path, get_type_str):
    """Render one route as visible steps, annotating each switch hop with its verdict."""
    steps = []
    for i, node in enumerate(path):
        data = graph.nodes[node]
        if _is_invisible(data, get_type_str):
            continue
        label = _display_name(graph, node, get_type_str)
        if get_type_str(data) == '14' and i + 1 < len(path):
            verdict = _branch_verdict_for_next_hop(engine, graph, node, path[i + 1])
            label += f" -- {_switch_expression(data)} must be {verdict}"
        steps.append(label)
    return "\n".join(f"      {'-> ' if i else 'FROM '}{s}" for i, s in enumerate(steps))


def describe_relation(engine, graph, wf_name, a, b, get_type_str):
    """Full plain-text answer for 'what does task A have to do with task B?'."""
    a, b = str(a), str(b)
    name_a = _display_name(graph, a, get_type_str)
    name_b = _display_name(graph, b, get_type_str)
    relation = classify_relation(graph, a, b)

    out = [f"Relationship analysis in '{wf_name}':", f"  A = {name_a}", f"  B = {name_b}", ""]

    if relation == 'same':
        out.append("  These are the same task.")
        return "\n".join(out)

    if relation == 'unrelated':
        out.append("  [VERDICT]: No structural relationship. Neither task can reach the other,")
        out.append("  and they share no common upstream ancestor. They live on fully independent")
        out.append("  branches of the workflow (or one of them is orphaned).")
        return "\n".join(out)

    if relation == 'parallel':
        out.append("  [VERDICT]: Parallel branches. Neither task executes before the other;")
        out.append("  they sit on mutually exclusive (or independent) routes.")
        div = _divergence_switch(graph, a, b, get_type_str)
        if div is not None:
            div_data = graph.nodes[div]
            out.append(f"  They diverge at Switch {_display_name(graph, div, get_type_str)},")
            out.append(f"  which evaluates: {_switch_expression(div_data)}.")
            out.append("  The verdict of that switch decides which of the two branches runs.")
        return "\n".join(out)

    # upstream / downstream: normalize so we always walk src -> dst.
    if relation == 'downstream':
        src, dst = a, b
        out.append("  [VERDICT]: A executes BEFORE B. Execution flows from A downstream to B.")
    else:
        src, dst = b, a
        out.append("  [VERDICT]: B executes BEFORE A. Execution flows from B downstream to A.")

    routes, count, capped = _enumerate_routes(graph, src, dst)
    count_str = f"{count}+" if capped else str(count)
    out.append(f"  Distinct route(s) connecting them: {count_str}")

    for idx, route in enumerate(routes):
        out.append("")
        out.append(f"    Route {idx + 1} of {count_str}:")
        out.append(_describe_route(engine, graph, route, get_type_str))

    if count > len(routes):
        out.append("")
        out.append(f"    [!] {count - len(routes)}{'+' if capped else ''} additional route(s) not "
                   "shown. Ask 'what must be true to reach task <id>' to see the governing "
                   "switch constraints instead of raw routes.")
    return "\n".join(out)


def constraints_to_reach(engine, graph, target, get_type_str):
    """Every upstream Switch whose verdict gates whether execution can reach `target`.

    For each ancestor Switch, we test which of its branches can still reach the
    target. If exactly one branch reaches it, that branch's verdict is a HARD
    requirement. If every branch reaches it, the switch does not constrain the
    target. This reads the real topology directly -- no path enumeration, so it
    cannot blow up or collapse routes.
    """
    target = str(target)
    ancestors = nx.ancestors(graph, target)
    constraints = []
    for node in ancestors:
        data = graph.nodes[node]
        if get_type_str(data) != '14':
            continue
        truth_map = engine.get_switch_truth_map(data)
        reaching_verdicts = set()
        for raw_target, verdict in truth_map.items():
            raw_target = str(raw_target)
            if raw_target == target:
                reaching_verdicts.add(verdict)
            elif graph.has_node(raw_target) and nx.has_path(graph, raw_target, target):
                reaching_verdicts.add(verdict)
        if len(reaching_verdicts) == 1:
            constraints.append((node, data, reaching_verdicts.pop()))
    return constraints


def describe_constraints(engine, graph, wf_name, target, get_type_str):
    """Full plain-text answer for 'what must be true for execution to reach task X?'."""
    target = str(target)
    name_t = _display_name(graph, target, get_type_str)
    constraints = constraints_to_reach(engine, graph, target, get_type_str)

    out = [f"Reachability constraints in '{wf_name}' for {name_t}:", ""]

    if graph.in_degree(target) == 0:
        t_type = get_type_str(graph.nodes[target])
        if t_type in ['1', 'Trigger', 'Start']:
            out.append("  This is the Start task: it runs whenever the workflow's trigger event fires.")
        else:
            out.append("  [FAULT]: This task is a structural orphan -- no incoming routes exist,")
            out.append("  so no switch settings can ever make execution reach it.")
        return "\n".join(out)

    if not constraints:
        out.append("  No gating switches: every upstream decision gate can still reach this task")
        out.append("  on both of its branches (or there are no switches upstream). Execution")
        out.append("  arrives here on every run that reaches this region of the workflow.")
        return "\n".join(out)

    out.append(f"  {len(constraints)} switch verdict(s) MUST hold for execution to arrive here:")
    for node, data, verdict in sorted(constraints, key=lambda c: len(nx.ancestors(graph, c[0]))):
        out.append(f"    -> Switch {_display_name(graph, node, get_type_str)}:")
        out.append(f"       condition ({_switch_expression(data)}) must evaluate {verdict}.")
    out.append("")
    out.append("  If the task is not firing at runtime, verify the live record data drives each")
    out.append("  of the above conditions to the required verdict.")
    return "\n".join(out)
