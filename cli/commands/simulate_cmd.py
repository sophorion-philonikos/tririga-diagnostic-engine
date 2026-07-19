"""What-If simulate command handler (CLI formatting)."""

from cli import simulation
from cli.formatters import wrap_ascii


def cmd_simulate(router, q, match):
    wf_name, _graph, err = router._get_context_graph(q)
    if err: return err

    try:
        result = simulation.run_simulation(
            router.engine, wf_name, q, trace_ids=router.last_execution_trace_ids)
    except Exception as e:
        return wrap_ascii(q, f"Simulation failed: {e}")

    if result['mode'] == 'did_query':
        return wrap_ascii(q, f"{result['answer']}\n{result['evidence']}")

    router.last_simulation_trace_ids = list(result['path_node_ids'])

    output = [f"--- What-If Simulation: {wf_name} ---", ""]
    output.append("[Interpreted Conditions]")
    for ft in result.get('failed_tasks', []):
        line = (f"  - {ft['node_type_name']} (Type {ft['node_type']}) '{ft['node_name']}' "
                f"(ID: {ft['node_id']}) FAILED / skipped")
        if ft.get('fields') and ft.get('node_type') != '23':
            line += f" — fields not updated: {', '.join(ft['fields'])}"
            if ft.get('bo'):
                line += f" on {ft['bo']}"
        elif ft.get('node_type') == '23':
            meta_parts = []
            if ft.get('sections'):
                meta_parts.append(f"sections: {', '.join(ft['sections'])}")
            if ft.get('tabs'):
                meta_parts.append(f"tabs: {', '.join(ft['tabs'])}")
            if ft.get('fields'):
                meta_parts.append(f"fields: {', '.join(ft['fields'])}")
            if meta_parts:
                line += f" — UI not updated ({'; '.join(meta_parts)})"
                if ft.get('bo'):
                    line += f" on {ft['bo']}"
        output.append(line)
    for a in result.get('altered_tasks', []):
        output.append(f"  - {a['node_type_name']} (Type {a['node_type']}) '{a['node_name']}' "
                      f"(ID: {a['node_id']}) simulated with ZERO records / null object token")
    if result['matched_conditions']:
        for m in result['matched_conditions']:
            output.append(f"  - Gate '{m['node_name']}' ({m['node_id']}) forced {m['verdict']}  ({m['reason']})")
    if not result['matched_conditions'] and not result.get('altered_tasks') and not result.get('failed_tasks'):
        output.append("  - None matched; simulating the default (FALSE-spine) route.")
    for phrase in result['unmatched_phrases']:
        output.append(f"  - [?] Could not map: '{phrase}'")

    if result.get('impact_tree'):
        output.append("")
        output.append("[Dataflow Impact Analysis]")

        def _print_impact_node(node, depth=0):
            indent = "  " + ("    " * depth)
            badge = node.get('badge') or ''
            badge_tag = f" [{badge}]" if badge and depth == 0 else ""
            label = node.get('label') or (
                f"{node.get('task_type_name', 'Task')} "
                f"'{node.get('task_name', '')}' ({node.get('task_id')})"
            )
            sentence = node.get('sentence') or ''
            if depth == 0:
                output.append(f"{indent}- {label}{badge_tag}")
                if sentence:
                    output.append(f"{indent}    {sentence}")
            elif sentence:
                output.append(f"{indent}- {label}: {sentence}")
            else:
                output.append(f"{indent}- {label}")
            for child in node.get('children') or []:
                _print_impact_node(child, depth + 1)

        for root in result['impact_tree']:
            _print_impact_node(root, 0)
    elif result.get('impacts'):
        output.append("")
        output.append("[Dataflow Impact Analysis]")
        for imp in result['impacts']:
            output.append(f"  - {imp['sentence']}")

    output.append("")
    output.append("[Decision Log]")
    for d in result['decisions']:
        output.append(f"  {d}")

    output.append("")
    output.append("[Simulated Execution Path]")
    for idx, name in enumerate(result['executed_names']):
        marker = "  START: " if idx == 0 else "  -> "
        output.append(f"{marker}{name}")

    # Keep route/bypass lines from summary; skip impact sentences already printed above.
    impact_sentences = {imp['sentence'] for imp in result.get('impacts', [])}
    skip_prefixes = (
        'Simulated execution failure for ',
        'Simulated a zero-records / null-token state for the ',
        "Gate '",
        'Unmatched phrase(s):',
        'No specific condition matched',
    )
    route_lines = []
    for line in result.get('summary', []):
        if line in impact_sentences:
            continue
        if any(line.startswith(p) for p in skip_prefixes):
            continue
        route_lines.append(line)
    if route_lines:
        output.append("")
        for line in route_lines:
            output.append(line)
    output.append("")
    output.append("Type 'visualize' to see this simulated path highlighted on the map.")
    return wrap_ascii(q, "\n".join(output))

