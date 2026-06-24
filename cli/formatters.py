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
    output = [f"--- Execution Path Analysis (Path {current_idx} of {total_paths}) ---"]
    step_num = 1
    for step in path:
        s_type = str(step.get('type', ''))
        s_name = step.get('name', '').lower()
        if s_type in ['12', '11'] or (s_name.startswith('unnamed') and s_type != '9') or s_type == 'generic': continue
        output.append(f"Step {step_num}: '{step['name']}' (Type {step['type']})")
        output.append(f"  -> Action: {step['action']}")
        step_num += 1
    return "\n".join(output)