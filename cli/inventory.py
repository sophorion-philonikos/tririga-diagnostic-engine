"""Workflow inventory and census reporting.

Houses the "list/what/which" style censuses over a loaded workflow graph:
tasks by type, switches, queries, modified fields, variables, loops,
associations, the full task-type index, workflow-header trigger info, and a
two-workflow comparison. Kept out of the router to avoid monolith growth.
"""

import re
import networkx as nx
from cli import knowledge


def _visible_nodes(graph, get_type_str):
    for node, data in graph.nodes(data=True):
        t = get_type_str(data)
        name = str(data.get('name', '')).lower()
        if t in ['12', '11'] or (name.startswith('unnamed') and t != '9') or t == 'generic':
            continue
        yield node, data, t


def build_inventory(q, engine, wf_name, graph, get_type_str):
    """Dispatch an inventory question to the right census. Returns plain text."""
    ql = q.lower()

    if re.search(r"variable", ql):
        return list_variables(wf_name, graph, get_type_str)
    if re.search(r"\bloops?\b|iterat", ql):
        return list_loops(engine, wf_name, graph, get_type_str)
    if re.search(r"association", ql):
        return list_associations(wf_name, graph, get_type_str)
    if re.search(r"task types|types? of task|what types", ql):
        return task_type_index(engine, get_type_str)

    # Fields touched across the workflow.
    if re.search(r"what fields|fields .*(touch|modif|updat|chang)", ql):
        field_writers = {}
        for node, data, t in _visible_nodes(graph, get_type_str):
            for f in data.get('TrgtFld', []):
                field_writers.setdefault(f, []).append(f"{data.get('name','?')} ({node})")
        if not field_writers:
            return f"No database fields are modified by '{wf_name}'."
        lines = [f"'{wf_name}' modifies {len(field_writers)} database field(s):"]
        for f, writers in sorted(field_writers.items()):
            lines.append(f"  - {f}  <- written by {len(writers)} task(s): {', '.join(writers[:4])}"
                         + (f" (+{len(writers)-4} more)" if len(writers) > 4 else ""))
        lines.append("\nYou can also ask: \"which tasks update <field>\" for the full reverse search.")
        return "\n".join(lines)

    # Tasks that modify the database.
    if re.search(r"which tasks (modify|update|change|write)|modif(?:y|ies|ications?)", ql):
        rows = [(n, d) for n, d, t in _visible_nodes(graph, get_type_str) if t == '28']
        if not rows:
            return f"No Modify Records (Type 28) tasks exist in '{wf_name}'."
        lines = [f"{len(rows)} Modify Records task(s) in '{wf_name}':"]
        for n, d in rows:
            flds = d.get('TrgtFld', [])
            lines.append(f"  - '{d.get('name','?')}' (ID: {n}) writes [{', '.join(flds[:5])}"
                         + (f", +{len(flds)-5} more]" if len(flds) > 5 else "]"))
        return "\n".join(lines)

    # Queries.
    if re.search(r"quer(?:y|ies)", ql):
        rows = [(n, d) for n, d, t in _visible_nodes(graph, get_type_str) if t == '22']
        lines = [f"{len(rows)} Query task(s) in '{wf_name}':"]
        for n, d in rows:
            fb = d.get('FilterBo', ['?'])
            q_name = fb[0] if isinstance(fb, list) else fb
            lines.append(f"  - '{d.get('name','?')}' (ID: {n}) executes query '{q_name}'")
            q_data = engine.queries.get(q_name)
            if q_data:
                lines.append(f"      Module '{q_data.get('Module')}' :: BO '{q_data.get('BO')}', "
                             f"{len(q_data.get('Filters', []))} internal filter(s)")
        if not rows:
            lines = [f"No Query (Type 22) tasks exist in '{wf_name}'."]
        return "\n".join(lines)

    # Switches.
    if re.search(r"switch", ql):
        rows = [(n, d) for n, d, t in _visible_nodes(graph, get_type_str) if t == '14']
        lines = [f"{len(rows)} Switch task(s) in '{wf_name}':"]
        for n, d in rows:
            exp = d.get('Expression', [])
            exp_str = ", ".join(exp) if exp else "condition not captured"
            lines.append(f"  - '{d.get('name','?')}' (ID: {n}) evaluates ({exp_str})")
        lines.append("\nYou can also ask: \"what must be true to reach task <id>\" to see which of "
                     "these gates govern a specific task.")
        return "\n".join(lines)

    # Retrieves.
    if re.search(r"retrieve", ql):
        rows = [(n, d) for n, d, t in _visible_nodes(graph, get_type_str) if t == '29']
        lines = [f"{len(rows)} Retrieve Records task(s) in '{wf_name}':"]
        for n, d in rows:
            bo = d.get('BO', ['?'])
            bo = bo[0] if isinstance(bo, list) else bo
            lines.append(f"  - '{d.get('name','?')}' (ID: {n}) targeting BO '{bo}'")
        return "\n".join(lines)

    # Default: full task census grouped by type.
    census = {}
    for n, d, t in _visible_nodes(graph, get_type_str):
        census.setdefault(t, []).append((n, d.get('name', '?')))
    lines = [f"Task census for '{wf_name}' ({sum(len(v) for v in census.values())} visible task(s)):"]
    for t in sorted(census, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0)):
        entries = census[t]
        lines.append(f"\n  Type {t} - {knowledge.type_display_name(t)}: {len(entries)} task(s)")
        for n, name in entries[:10]:
            lines.append(f"    - '{name}' (ID: {n})")
        if len(entries) > 10:
            lines.append(f"    (+{len(entries)-10} more)")
    lines.append("\nYou can also ask: \"list all switches\", \"list loops\", \"list variables\", "
                 "or \"what is Type 29\".")
    return "\n".join(lines)


def list_variables(wf_name, graph, get_type_str):
    """Census of workflow variables: definitions (Type 40) and assignments (Type 41)."""
    defs, assigns = [], []
    for n, d, t in _visible_nodes(graph, get_type_str):
        var_names = d.get('VariableName', [])
        if isinstance(var_names, str): var_names = [var_names]
        label = f"'{d.get('name','?')}' (ID: {n})" + (f" -> variable(s) [{', '.join(var_names)}]" if var_names else "")
        if t == '40': defs.append(label)
        elif t == '41': assigns.append(label)

    if not defs and not assigns:
        return (f"'{wf_name}' declares no workflow variables (no Variable Definition/Assignment "
                "tasks, Types 40/41).")
    lines = [f"Workflow variables in '{wf_name}':"]
    if defs:
        lines.append(f"\n  {len(defs)} Variable Definition task(s) (Type 40):")
        lines.extend([f"    - {s}" for s in defs])
    if assigns:
        lines.append(f"\n  {len(assigns)} Variable Assignment task(s) (Type 41):")
        lines.extend([f"    - {s}" for s in assigns])
    lines.append("\n[!] Remember: reading a variable before its Definition task executes yields "
                 "null -- a classic NullPointerException source in switches.")
    return "\n".join(lines)


def list_loops(engine, wf_name, graph, get_type_str):
    """Census of loop constructs: cycles in the graph plus loop-control tasks (19/20/21/24)."""
    loop_tasks = {'19': [], '20': [], '21': [], '24': []}
    for n, d, t in _visible_nodes(graph, get_type_str):
        if t in loop_tasks:
            loop_tasks[t].append((n, d))
    # Loop-control junction types 19/21 are often unlabeled -> also scan invisible nodes.
    for n, d in graph.nodes(data=True):
        t = get_type_str(d)
        if t in ('19', '21') and not any(n == x[0] for x in loop_tasks[t]):
            loop_tasks[t].append((n, d))

    cycle_edges = []
    if not nx.is_directed_acyclic_graph(graph):
        try:
            cycle_edges = list(nx.find_cycle(graph))
        except Exception:
            cycle_edges = []

    total = sum(len(v) for v in loop_tasks.values())
    if total == 0 and not cycle_edges:
        return f"'{wf_name}' contains no loop constructs and its graph is fully acyclic."

    lines = [f"Loop analysis for '{wf_name}':"]
    for t, rows in loop_tasks.items():
        if not rows:
            continue
        lines.append(f"\n  Type {t} - {knowledge.type_display_name(t)}: {len(rows)} task(s)")
        for n, d in rows:
            entry = f"    - '{d.get('name', knowledge.type_display_name(t))}' (ID: {n})"
            if t == '24':
                branch_map = engine.get_branch_map(d)
                for tgt, label in branch_map.items():
                    tgt_name = graph.nodes[tgt].get('name', tgt) if graph.has_node(tgt) else tgt
                    entry += f"\n        {label} -> '{tgt_name}' ({tgt})"
            lines.append(entry)
    if cycle_edges:
        edge_str = ", ".join([f"{a}->{b}" for a, b in cycle_edges])
        lines.append(f"\n  Cycle detected in the graph (expected for loops): {edge_str}")
    else:
        lines.append("\n  Note: no back-edge cycle detected; loop bodies may exit forward only.")
    lines.append("\nYou can also ask: \"what is Type 24\" for iterator mechanics.")
    return "\n".join(lines)


def list_associations(wf_name, graph, get_type_str):
    """Census of association names traversed or created by the workflow."""
    assoc_usage = {}
    for n, d, t in _visible_nodes(graph, get_type_str):
        names = []
        for key in ('AssociationName', 'AssocName'):
            vals = d.get(key, [])
            if isinstance(vals, str): vals = [vals]
            names.extend(vals)
        for ref in d.get('TaskRefRecords', []):
            if ref.get('RefAssoc'):
                names.append(ref['RefAssoc'])
        for a in names:
            assoc_usage.setdefault(a, []).append(f"'{d.get('name','?')}' ({n})")

    if not assoc_usage:
        return f"No named associations are traversed or created by '{wf_name}'."
    lines = [f"'{wf_name}' uses {len(assoc_usage)} association(s):"]
    for a, users in sorted(assoc_usage.items()):
        lines.append(f"  - '{a}'  used by: {', '.join(users[:4])}"
                     + (f" (+{len(users)-4} more)" if len(users) > 4 else ""))
    return "\n".join(lines)


def task_type_index(engine, get_type_str):
    """Full glossary index of task types, marking which appear in loaded workflows."""
    present = {}
    for wf_name, graph in engine.graphs.items():
        for _n, d in graph.nodes(data=True):
            present.setdefault(get_type_str(d), set()).add(wf_name)

    lines = ["TRIRIGA task-type index (types present in your loaded workflow(s) marked with *):"]
    for code in sorted(knowledge.TASK_TYPE_GLOSSARY.keys(), key=int):
        entry = knowledge.TASK_TYPE_GLOSSARY[code]
        marker = "*" if code in present else " "
        lines.append(f"  {marker} Type {code:>2} - {entry['name']}")
    lines.append("\nAsk \"what is Type <n>\" for the full definition, shape, and failure modes.")
    return "\n".join(lines)


def describe_trigger(wf_name, meta):
    """Answer 'what triggers this workflow?' from the parsed header metadata."""
    if not meta:
        return f"No header metadata was captured for '{wf_name}'."
    lines = [f"Trigger profile for '{wf_name}':"]
    event = meta.get('EventName') or "(no event captured)"
    module, bo = meta.get('Module'), meta.get('BO')
    scope = f"{module}::{bo}" if module and bo else (module or bo or "(unknown scope)")
    lines.append(f"  - Fires on: {event}")
    lines.append(f"  - Bound to: {scope}")
    if meta.get('ObjectLabelName'):
        lines.append(f"  - Version label: {meta['ObjectLabelName']}")
    if meta.get('UpdatedBy'):
        lines.append(f"  - Last updated by: {meta['UpdatedBy']}")
    if meta.get('Description') and meta['Description'] != "No description provided.":
        lines.append(f"  - Description: {meta['Description']}")
    return "\n".join(lines)


def compare_workflows(engine, name_a, name_b, get_type_str):
    """Side-by-side structural comparison of two loaded workflows."""
    graph_a, graph_b = engine.graphs[name_a], engine.graphs[name_b]

    def profile(graph):
        counts, fields = {}, set()
        for _n, d, t in _visible_nodes(graph, get_type_str):
            counts[t] = counts.get(t, 0) + 1
            fields.update(d.get('TrgtFld', []))
        return counts, fields

    counts_a, fields_a = profile(graph_a)
    counts_b, fields_b = profile(graph_b)
    meta_a = engine.workflow_metadata.get(name_a, {})
    meta_b = engine.workflow_metadata.get(name_b, {})

    lines = ["Workflow comparison:", f"  A = '{name_a}'", f"  B = '{name_b}'", ""]
    lines.append(f"  Trigger: A fires on '{meta_a.get('EventName','?')}' ({meta_a.get('Module','?')}::{meta_a.get('BO','?')}) | "
                 f"B fires on '{meta_b.get('EventName','?')}' ({meta_b.get('Module','?')}::{meta_b.get('BO','?')})")

    lines.append("\n  Task counts by type:")
    all_types = sorted(set(counts_a) | set(counts_b), key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0))
    for t in all_types:
        ca, cb = counts_a.get(t, 0), counts_b.get(t, 0)
        diff = " <-- differs" if ca != cb else ""
        lines.append(f"    Type {t:>2} ({knowledge.type_display_name(t)}): A={ca}, B={cb}{diff}")

    only_a, only_b = sorted(fields_a - fields_b), sorted(fields_b - fields_a)
    shared = sorted(fields_a & fields_b)
    lines.append(f"\n  Database fields modified: {len(shared)} shared" +
                 (f"; only in A: [{', '.join(only_a)}]" if only_a else "") +
                 (f"; only in B: [{', '.join(only_b)}]" if only_b else ""))
    if shared:
        lines.append(f"    Shared: [{', '.join(shared[:10])}{', ...' if len(shared) > 10 else ''}]")
    return "\n".join(lines)
