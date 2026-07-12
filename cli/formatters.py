def wrap_ascii(query, response_text):
    """Wraps the response in a clean, left-aligned ASCII visual border."""
    lines = str(response_text).split('\n')
    output = f"\n┌── [User Query]: {query}\n│"
    for line in lines:
        output += f"\n│   {line}"
    output += "\n└" + "─" * 120
    return output

def format_path_narrative(path, current_idx, total_paths):
    """Formats the DFS path list into a readable chronological string."""
    from cli import graph_utils
    output = [f"--- Execution Path Analysis (Path {current_idx} of {total_paths}) ---"]
    step_num = 1
    for step in path:
        if graph_utils.is_invisible(step):
            continue
        output.append(f"Step {step_num}: '{step['name']}' (Type {step['type']})")
        output.append(f"  -> Action: {step['action']}")
        step_num += 1
    return "\n".join(output)