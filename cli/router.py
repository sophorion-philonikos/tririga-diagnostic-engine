import re
import difflib
import networkx as nx
from cli.formatters import wrap_ascii, format_path_narrative
from cli.models import TaskInsight
from cli import knowledge
from cli import relations
from cli.intents import build_registry, render_help, suggest
from integrations.ssh_client import SSHClientManager
from cli.visualizer import WorkflowVisualizer

class TririgaNLPRouter:
    def __init__(self, diagnostic_engine, ssh_host=None, ssh_user=None, ssh_log_path=None, offline_mode=False, local_log_path=None):
        self.engine = diagnostic_engine
        self.ssh_manager = SSHClientManager(ssh_host, ssh_user, ssh_log_path, offline_mode, local_log_path) if (ssh_host or offline_mode) else None
        self.last_live_records = {} 
        self.last_live_record_counts = {} 
        self.current_context_wf = None 
        self.last_execution_trace_ids = [] # Added memory for the visualizer
        self.last_path_generation_truncated = False
        self.last_path_cycle_edges = []

        # Bounds for path enumeration. Root-to-leaf enumeration is inherently exponential
        # on branch-heavy TRIRIGA workflows, so we cap the number of materialized paths and
        # the traversal depth rather than pretending the topology collapses to one route.
        self.MAX_ENUMERATED_PATHS = 250

        self._build_command_registry()

    def _build_command_registry(self):
        # Structured, priority-ordered intent registry (see cli/intents.py). Explicit
        # priorities fix the shadowing problem of the old flat regex list, where broad
        # patterns like "what is" swallowed glossary questions like "what is Type 14".
        self.intents = build_registry()

    def process_query(self, user_query):
        for intent in self.intents:
            for pattern in intent.compiled:
                match = pattern.search(user_query)
                if match:
                    handler = getattr(self, intent.handler)
                    return handler(user_query, match)

        # Did-you-mean fallback: score keyword overlap against every intent's
        # vocabulary and offer the closest example phrasings.
        suggestions = suggest(user_query, self.intents)
        if suggestions:
            lines = ["I couldn't confidently parse that. Did you mean one of these?"]
            lines.extend([f"  - {s}" for s in suggestions])
            lines.append("\nType 'help' to see everything you can ask.")
            return wrap_ascii(user_query, "\n".join(lines))
        return wrap_ascii(user_query, "I couldn't confidently parse that command. Type 'help' to see everything you can ask.")

    # ==========================================
    # COMMAND DISPATCH HANDLERS
    # ==========================================
    def _cmd_visualize_workflow(self, q, match):
        wf_name, _graph, err = self._get_context_graph(q)
        if err: return err

        visualizer = WorkflowVisualizer(self.engine)
        return visualizer.generate_html_map(wf_name, q, live_trace_ids=self.last_execution_trace_ids)

    def _cmd_scan_log(self, q, match):
        if self.ssh_manager: return self.scan_live_log_ssh(user_query=q)
        return wrap_ascii(q, "I cannot scan the live logs because the SSH configuration is missing in the engine.")

    def _cmd_ad_hoc_trace(self, q, match):
        if self.ssh_manager: return self.trace_ad_hoc_live_execution_ssh(user_query=q)
        return wrap_ascii(q, "I cannot trace live logs because the SSH configuration is missing in the engine.")

    def _cmd_live_trace(self, q, match):
        if self.ssh_manager: return self.trace_live_execution_ssh(user_query=q)
        return wrap_ascii(q, "I cannot trace live logs because the SSH configuration is missing in the engine.")

    def _cmd_trace_path(self, q, match):
        return wrap_ascii(q, self._trace_path(match.group(1), match.group(2)))

    def _cmd_conditional_trace(self, q, match):
        field, val = self._parse_condition(q)
        if field and val: return self._trace_condition(field, val, q)
        return wrap_ascii(q, "Could not parse the condition. Please specify 'when [field] is [value]'.")

    def _cmd_analyze_failure(self, q, match):
        task_name = self._extract_task_identifier(q)
        if task_name: return self._analyze_failure(task_name, q)
        return wrap_ascii(q, "Could not identify a Task ID. Please specify the task number.")

    def _cmd_find_references(self, q, match):
        search_term = self._extract_tririga_string(q)
        if search_term: return self._find_references(search_term, q)
        return wrap_ascii(q, "Could not identify a valid TRIRIGA string to search for.")

    def _cmd_explain_purpose(self, q, match):
        return self._explain_purpose_with_paths(user_query=q)

    def _cmd_explain_task(self, q, match):
        task_name = self._extract_task_identifier(q)
        if task_name: return self._explain_task_logic(task_name, q)
        return wrap_ascii(q, "Could not identify a Task ID. Please specify the task number.")

    def _cmd_find_orphans(self, q, match):
        return wrap_ascii(q, self._find_orphans())

    # ==========================================
    # META / CONTEXT / KNOWLEDGE HANDLERS
    # ==========================================
    def _cmd_help(self, q, match):
        return wrap_ascii(q, render_help(self.intents))

    def _cmd_set_context(self, q, match):
        token = match.group(1).strip().strip("'\"?.,!")
        names = self.engine.loaded_workflow_names
        # Substring match first (case-insensitive), then fuzzy.
        candidates = [n for n in names if token.lower() in n.lower()]
        if not candidates:
            candidates = difflib.get_close_matches(token, names, n=1, cutoff=0.4)
        if not candidates:
            listing = "\n".join([f"  {i+1}) {n}" for i, n in enumerate(names)])
            return wrap_ascii(q, f"No loaded workflow matches '{token}'. Loaded workflows:\n{listing}")
        self.current_context_wf = candidates[0]
        return wrap_ascii(q, f"Context set. All questions now target:\n  '{candidates[0]}'\n\n"
                             "Try: 'what is the purpose', 'list all switches', or 'visualize'.")

    def _cmd_show_context(self, q, match):
        names = self.engine.loaded_workflow_names
        lines = [f"{len(names)} workflow(s) loaded from the OM Package:"]
        for i, n in enumerate(names):
            marker = "  * ACTIVE ->" if n == self.current_context_wf else "           -"
            lines.append(f"{marker} {i+1}) {n}")
        if not self.current_context_wf:
            lines.append("\nNo active context yet. Set one with: use workflow <name>")
        return wrap_ascii(q, "\n".join(lines))

    def _cmd_glossary_type(self, q, match):
        code = match.group(1)
        answer = knowledge.explain_task_type(code, self.engine.graphs, self._get_type_str)
        answer += ("\n\nYou can also ask: \"list all tasks\" to see every type in this workflow, "
                   f"or \"explain task <id>\" to dissect a specific Type {code} task.")
        return wrap_ascii(q, answer)

    def _cmd_glossary_operator(self, q, match):
        return wrap_ascii(q, knowledge.explain_operator(match.group(1)))

    def _cmd_glossary_concept(self, q, match):
        term = match.group(1)
        answer = knowledge.explain_concept(term)
        if answer is None:
            return wrap_ascii(q, f"'{term}' is not in my concept glossary yet.")
        return wrap_ascii(q, answer)

    # ==========================================
    # RELATIONSHIP / CONSTRAINT / INVENTORY HANDLERS
    # ==========================================
    def _cmd_relation(self, q, match):
        wf_name, graph, err = self._get_context_graph(q)
        if err: return err
        refs, note = self._resolve_task_refs(q, graph, max_refs=2)
        if len(refs) < 2:
            return wrap_ascii(q, "I need two tasks to compare. Reference them by ID or name, e.g. "
                                 "\"what does task 333395 have to do with the Start task?\"")
        answer = relations.describe_relation(self.engine, graph, wf_name, refs[0], refs[1], self._get_type_str)
        if note: answer = note + "\n\n" + answer
        # Suggest constraints for whichever referenced task is not the Start task.
        suggest_ref = refs[0]
        if self._get_type_str(graph.nodes[refs[0]]) in ['1', 'Trigger', 'Start']:
            suggest_ref = refs[1]
        answer += ("\n\nYou can also ask: \"what must be true to reach task "
                   f"{suggest_ref}\" or \"explain task {suggest_ref}\".")
        return wrap_ascii(q, answer)

    def _cmd_constraints(self, q, match):
        wf_name, graph, err = self._get_context_graph(q)
        if err: return err
        refs, note = self._resolve_task_refs(q, graph, max_refs=1)
        if not refs:
            return wrap_ascii(q, "I need a target task. Reference it by ID or name, e.g. "
                                 "\"what must be true to reach task 333449?\"")
        answer = relations.describe_constraints(self.engine, graph, wf_name, refs[0], self._get_type_str)
        if note: answer = note + "\n\n" + answer
        answer += f"\n\nYou can also ask: \"what does task {refs[0]} have to do with the Start task?\""
        return wrap_ascii(q, answer)

    def _cmd_inventory(self, q, match):
        wf_name, graph, err = self._get_context_graph(q)
        if err: return err
        return wrap_ascii(q, self._build_inventory(q, wf_name, graph))

    def _build_inventory(self, q, wf_name, graph):
        ql = q.lower()
        type_labels = {
            '1': 'Start', '9': 'End', '13': 'Stop', '14': 'Switch (Decision Gate)',
            '22': 'Query', '23': 'Modify Metadata (UI)', '25': 'Create Record',
            '28': 'Modify Records', '29': 'Retrieve Records', '39': 'Custom Task',
        }

        def visible_nodes():
            for node, data in graph.nodes(data=True):
                t = self._get_type_str(data)
                name = data.get('name', '').lower()
                if t in ['12', '11'] or (name.startswith('unnamed') and t != '9') or t == 'generic':
                    continue
                yield node, data, t

        # Fields touched across the workflow.
        if re.search(r"what fields|fields .*(touch|modif|updat|chang)", ql):
            field_writers = {}
            for node, data, t in visible_nodes():
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
            rows = [(n, d) for n, d, t in visible_nodes() if t == '28']
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
            rows = [(n, d) for n, d, t in visible_nodes() if t == '22']
            lines = [f"{len(rows)} Query task(s) in '{wf_name}':"]
            for n, d in rows:
                fb = d.get('FilterBo', ['?'])
                q_name = fb[0] if isinstance(fb, list) else fb
                lines.append(f"  - '{d.get('name','?')}' (ID: {n}) executes query '{q_name}'")
                q_data = self.engine.queries.get(q_name)
                if q_data:
                    lines.append(f"      Module '{q_data.get('Module')}' :: BO '{q_data.get('BO')}', "
                                 f"{len(q_data.get('Filters', []))} internal filter(s)")
            if not rows:
                lines = [f"No Query (Type 22) tasks exist in '{wf_name}'."]
            return "\n".join(lines)

        # Switches.
        if re.search(r"switch", ql):
            rows = [(n, d) for n, d, t in visible_nodes() if t == '14']
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
            rows = [(n, d) for n, d, t in visible_nodes() if t == '29']
            lines = [f"{len(rows)} Retrieve Records task(s) in '{wf_name}':"]
            for n, d in rows:
                bo = d.get('BO', ['?'])
                bo = bo[0] if isinstance(bo, list) else bo
                lines.append(f"  - '{d.get('name','?')}' (ID: {n}) targeting BO '{bo}'")
            return "\n".join(lines)

        # Default: full task census grouped by type.
        census = {}
        for n, d, t in visible_nodes():
            census.setdefault(t, []).append((n, d.get('name', '?')))
        lines = [f"Task census for '{wf_name}' ({sum(len(v) for v in census.values())} visible task(s)):"]
        for t in sorted(census, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0)):
            label = type_labels.get(t, f"Type {t}")
            entries = census[t]
            lines.append(f"\n  Type {t} - {label}: {len(entries)} task(s)")
            for n, name in entries[:10]:
                lines.append(f"    - '{name}' (ID: {n})")
            if len(entries) > 10:
                lines.append(f"    (+{len(entries)-10} more)")
        lines.append("\nYou can also ask: \"list all switches\", \"list queries\", or \"what is Type 29\".")
        return "\n".join(lines)

    # ==========================================
    # CONTEXT & TASK RESOLUTION HELPERS
    # ==========================================
    def _get_context_graph(self, q):
        """Resolve the active workflow graph, or return an actionable error response."""
        wf = self.current_context_wf
        if not wf:
            if len(self.engine.loaded_workflow_names) == 1:
                wf = self.engine.loaded_workflow_names[0]
                self.current_context_wf = wf
            else:
                names = "\n".join([f"  - {n}" for n in self.engine.loaded_workflow_names])
                return None, None, wrap_ascii(
                    q, f"Multiple workflows are loaded:\n{names}\n\n"
                       "Tell me which to use, e.g. \"use workflow triBuilding\".")
        return wf, self.engine.graphs[wf], None

    def _resolve_task_refs(self, query, graph, max_refs=2):
        """Extract up to max_refs task references from free text.

        Accepts, in priority order: bare numeric IDs (5+ digits) present in the graph,
        the keywords 'start'/'end' (mapped to the Start/End nodes), quoted task names
        (exact then fuzzy), and finally fuzzy matching of capitalized/known task names.
        Returns (refs, note) where note carries any 'did you mean' clarification.
        """
        refs, notes = [], []

        def add(node_id):
            node_id = str(node_id)
            if node_id not in refs:
                refs.append(node_id)

        for num in re.findall(r"\b(\d{4,})\b", query):
            if graph.has_node(num):
                add(num)

        ql = query.lower()
        if len(refs) < max_refs and re.search(r"\bstart(?:\s+task)?\b", ql):
            for n, d in graph.nodes(data=True):
                if self._get_type_str(d) in ['1', 'Trigger', 'Start']:
                    add(n)
                    break
        if len(refs) < max_refs and re.search(r"\bend(?:\s+task)?\b", ql):
            for n, d in graph.nodes(data=True):
                if self._get_type_str(d) in ['9', '13']:
                    add(n)
                    break

        if len(refs) < max_refs:
            name_map = {str(d.get('name', '')).lower(): n for n, d in graph.nodes(data=True) if d.get('name')}
            for quoted in re.findall(r"['\"]([^'\"]+)['\"]", query):
                key = quoted.lower()
                if key in name_map:
                    add(name_map[key])
                else:
                    close = difflib.get_close_matches(key, list(name_map.keys()), n=1, cutoff=0.6)
                    if close:
                        add(name_map[close[0]])
                        notes.append(f"[?] Interpreted '{quoted}' as task '{close[0]}'.")

        return refs[:max_refs], "\n".join(notes)

    # ==========================================
    # CORE LOGIC & ENGINE INTERACTIONS
    # ==========================================
    def _get_target_workflows(self):
        if self.current_context_wf and self.current_context_wf in self.engine.graphs:
            return {self.current_context_wf: self.engine.graphs[self.current_context_wf]}
        return self.engine.graphs

    def _get_type_str(self, data):
        t = data.get('type', data.get('Type', 'Generic'))
        if isinstance(t, list): return str(t[0])
        return str(t).strip()

    def _explain_purpose_with_paths(self, user_query):
        wf_name, _graph, err = self._get_context_graph(user_query)
        if err: return err

        base_summary = self._explain_purpose(wf_name)
        all_paths = self._generate_all_paths(wf_name)

        # Surface topology caveats explicitly rather than silently.
        notes = []
        if self.last_path_cycle_edges:
            edge_str = ", ".join(["{}->{}".format(e[0], e[1]) for e in self.last_path_cycle_edges])
            notes.append(
                f"[!] Cyclic routing detected (recurrence loop). Loop edge(s): {edge_str}. "
                "Each path is walked through the loop once, up to the point it re-enters a visited task."
            )
        if self.last_path_generation_truncated:
            notes.append(
                f"[!] This workflow's branching exceeds the enumeration bound; the first "
                f"{self.MAX_ENUMERATED_PATHS} logical paths were materialized. The complete topology "
                "remains intact in the graph model (no routes were collapsed)."
            )

        if not all_paths:
            body = base_summary
            if notes:
                body += "\n\n" + "\n".join(notes)
            return wrap_ascii(user_query, body)

        total_paths = len(all_paths)

        # Interactive path explorer: reveal paths in small batches so the user is never
        # flooded, and is always told how many remain and offered the choice to continue.
        PATH_BATCH_SIZE = 3

        def render_batch(start_idx, end_idx):
            return "\n\n".join(
                format_path_narrative(all_paths[i], i + 1, total_paths)
                for i in range(start_idx, end_idx)
            )

        header_segments = [base_summary]
        if notes:
            header_segments.append("\n".join(notes))

        first_end = min(PATH_BATCH_SIZE, total_paths)
        first_block = "\n\n".join(header_segments + [render_batch(0, first_end)])

        # If everything fits in the first batch, return it in one shot (no prompt needed).
        if total_paths <= PATH_BATCH_SIZE:
            return wrap_ascii(user_query, first_block)

        print(wrap_ascii(user_query, first_block))
        shown = first_end

        while shown < total_paths:
            remaining = total_paths - shown
            next_count = min(PATH_BATCH_SIZE, remaining)
            ans = input(
                f"\n[?] Showing {shown} of {total_paths} logical paths. {remaining} remaining. "
                f"Would you like to see the next {next_count}? (Yes/No): "
            )
            answer = ans.strip().lower()
            if answer in ['y', 'yes']:
                start_idx = shown
                end_idx = shown + next_count
                batch_text = render_batch(start_idx, end_idx)
                shown = end_idx
                if shown >= total_paths:
                    return wrap_ascii(
                        f"[Interactive] Paths {start_idx + 1}-{shown} of {total_paths}",
                        batch_text + f"\n\n[!] All {total_paths} logical paths have now been explored.",
                    )
                print(wrap_ascii(f"[Interactive] Paths {start_idx + 1}-{shown} of {total_paths}", batch_text))
            elif answer in ['n', 'no']:
                return wrap_ascii(
                    "[Interactive] Path exploration closed",
                    f"Stopped after {shown} of {total_paths} paths. "
                    f"{total_paths - shown} path(s) left unexplored. "
                    "Re-run the purpose command anytime to walk through them again.",
                )
            else:
                print("\n[!] Please answer Yes or No.")

        return wrap_ascii("[Interactive] Exploration complete", f"All {total_paths} logical paths viewed.")

    def _resolve_visible_successors(self, graph, node_id, cache):
        """Resolve the nearest *visible* successors of a node, hopping over invisible
        junction tasks (Type 11/12/generic/unnamed connectors) exactly once.

        Results are memoized per node because visibility resolution is purely
        topological (path-independent). This is the "junction-once / shared subgraph"
        optimization: each junction is expanded a single time regardless of how many
        distinct execution paths flow through it, which is what stops branch-heavy
        workflows from re-materializing the same downstream subgraph over and over.
        """
        if node_id in cache:
            return cache[node_id]

        result = []
        result_seen = set()
        visited_invisible = set()
        queue = list(graph.successors(node_id))
        i = 0
        while i < len(queue):
            succ = queue[i]
            i += 1
            s_node = graph.nodes[succ]
            s_type = self._get_type_str(s_node)
            s_name = s_node.get('name', '').lower()
            is_invisible = s_type in ['12', '11'] or (s_name.startswith('unnamed') and s_type != '9') or s_type == 'generic'

            if is_invisible:
                if succ not in visited_invisible:
                    visited_invisible.add(succ)
                    queue.extend(graph.successors(succ))
            elif succ not in result_seen:
                result_seen.add(succ)
                result.append(succ)

        cache[node_id] = result
        return result

    def _generate_all_paths(self, wf_name):
        graph = self.engine.graphs[wf_name]
        self.last_path_generation_truncated = False
        self.last_path_cycle_edges = []

        # Cycle awareness: TRIRIGA recurrence loops make the graph cyclic. Report the loop
        # explicitly instead of silently truncating it inside the traversal guard.
        if not nx.is_directed_acyclic_graph(graph):
            try:
                self.last_path_cycle_edges = list(nx.find_cycle(graph))
            except Exception:
                self.last_path_cycle_edges = []

        start_nodes = [n for n, d in graph.nodes(data=True) if self._get_type_str(d) in ['1', 'Trigger', 'Start']]
        if not start_nodes:
            start_nodes = [n for n, d in graph.nodes(data=True) if graph.in_degree(n) == 0]

        succ_cache = {}
        max_depth = graph.number_of_nodes() + 5
        all_paths = []

        # Explicit-stack iterative DFS. Each frame carries the path prefix that leads INTO
        # the node plus the per-path visited set (which safely terminates cycles). Using an
        # explicit stack avoids Python's recursion ceiling on deep topologies.
        stack = [(sn, [], frozenset()) for sn in reversed(start_nodes)]

        while stack:
            if len(all_paths) >= self.MAX_ENUMERATED_PATHS:
                self.last_path_generation_truncated = True
                break

            current_node, current_path_steps, visited = stack.pop()

            if current_node in visited:
                # Loop back-edge on this path: terminate the branch here (already recorded
                # globally via last_path_cycle_edges) rather than looping forever.
                if current_path_steps:
                    all_paths.append(current_path_steps)
                continue

            if len(current_path_steps) >= max_depth:
                self.last_path_generation_truncated = True
                if current_path_steps:
                    all_paths.append(current_path_steps)
                continue

            node_data = graph.nodes[current_node]
            t_type = self._get_type_str(node_data)
            t_name = node_data.get('name', f"Task {current_node}")
            action_text = self._translate_task_to_action(current_node, node_data)
            step_info = {'id': current_node, 'name': t_name, 'type': t_type, 'action': action_text}
            new_path_steps = current_path_steps + [step_info]

            successors = self._resolve_visible_successors(graph, current_node, succ_cache)

            if not successors or t_type in ['9', '13', 'End']:
                all_paths.append(new_path_steps)
                continue

            new_visited = visited | {current_node}
            truth_map = self.engine.get_switch_truth_map(node_data) if t_type == '14' else {}

            for succ in reversed(successors):
                if t_type == '14':
                    step_info_copy = dict(step_info)
                    verdict = self._classify_switch_branch(graph, node_data, succ, truth_map, succ_cache)
                    path_str = "TRUE (Primary)" if verdict == 'TRUE' else "FALSE (Default)"
                    step_info_copy['action'] += f" Routed to the {path_str} path."
                    path_for_next = new_path_steps[:-1] + [step_info_copy]
                else:
                    path_for_next = new_path_steps

                stack.append((succ, path_for_next, new_visited))

        return all_paths

    def _classify_switch_branch(self, graph, switch_data, visible_succ, truth_map, succ_cache):
        """Return 'TRUE' or 'FALSE' for a visible successor of a Switch (Type 14) task.

        Uses the EventName-derived truth map keyed by raw TargetAssociation ids, then
        resolves it forward through any invisible junctions to the concrete visible
        successor actually rendered on that branch.
        """
        if not truth_map:
            return 'FALSE'
        for raw_target, verdict in truth_map.items():
            if str(visible_succ) == str(raw_target):
                return verdict
            if graph.has_node(str(raw_target)):
                if str(visible_succ) in [str(x) for x in self._resolve_visible_successors(graph, str(raw_target), succ_cache)]:
                    return verdict
        return 'FALSE'

    def _translate_task_to_action(self, node_id, data):
        t_type = self._get_type_str(data)
        if t_type == '1': return "Initiates workflow execution."
        if t_type in ['9', '13']: return "Ends workflow execution and finalizes logic."
        if t_type == '25':
            bo = data.get('BO', 'Record')
            if isinstance(bo, list): bo = bo[0]
            return f"Instantiated a temporary '{bo}' record in memory."
        if t_type == '14':
            exp = data.get('Expression', [])
            exp_str = ', '.join(exp) if exp else 'decision gate'
            return f"Evaluated condition ({exp_str})."
        if t_type == '23':
            sec = []
            for gm in data.get('GUIMappings', []):
                if gm.get('Section') and gm.get('Section') != '^^': sec.append(gm.get('Section'))
            sec_str = f" targeting section(s) [{', '.join(set(sec))}]" if sec else ""
            return f"Dynamically altered UI form properties/metadata{sec_str}."
        if t_type == '29':
            bo = data.get('BO', 'Records')
            if isinstance(bo, list): bo = bo[0]
            l_fields = data.get('LFldName', [])
            constants = data.get('ConstantValue', [])
            if l_fields and constants: return f"Fetched '{bo}' records where {l_fields[0]} evaluates against '{constants[0]}'."
            return f"Retrieved associated '{bo}' records by traversing the relational map."
        if t_type == '22':
            q = data.get('FilterBo', ['system query'])
            q_name = q[0] if isinstance(q, list) else q
            return f"Executed system query '{q_name}' to fetch context records."
        if t_type == '28':
            bo = data.get('BO', 'Record')
            if isinstance(bo, list): bo = bo[0]
            flds = data.get('TrgtFld', [])
            fld_str = f" modifying fields [{', '.join(flds[:3])}{'...' if len(flds)>3 else ''}]" if flds else ""
            return f"Updated the target '{bo}' record{fld_str}."
        return "Executes standard system logic."

    def scan_live_log_ssh(self, lines_to_read=5000, user_query=""):
        log_data = self.ssh_manager.fetch_remote_log(lines_to_read, show_workflow_note=False)
        if isinstance(log_data, str) and log_data.startswith("ERROR:"): return wrap_ascii(user_query, log_data)
            
        log_text = "".join(log_data)
        exception_blocks = re.split(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}', log_text)
        relevant_errors = []
        
        for block in exception_blocks:
            if "Exception" in block or "ERROR" in block or "WARN" in block:
                task_match = re.search(r'(?i)(?:task|task\s+id|taskid|step)[\s:=#\-]*(\d{5,})', block)
                if task_match:
                    task_id = task_match.group(1)
                    node_data, wf_name = self.engine.get_node(task_id)
                    if node_data:
                        err_match = re.search(r'(?i)(java\.[a-zA-Z\.]*(?:Exception|Error)|ORA-\d{5}:?[^\n\r]*|Exception\s+caught|Failure\s+in[^\n\r]*)', block)
                        error_type = err_match.group(1).strip() if err_match else "General Logic Failure"
                        relevant_errors.append((task_id, error_type, wf_name))

        if not relevant_errors:
            return wrap_ascii(user_query, "Log scan complete. Good news: No recent errors in the log match any of the Task IDs in your loaded workflow. (Other developers' errors were successfully ignored).")

        latest_task_id, latest_error, wf_name = relevant_errors[-1]
        self.current_context_wf = wf_name 
        return wrap_ascii(user_query, self._synthesize_log_failure(latest_task_id, latest_error, wf_name))

    def trace_ad_hoc_live_execution_ssh(self, lines_to_read=15000, user_query=""):
        target_wf_name = input("\n[?] Enter the exact name of the workflow you want to trace: ").strip()
        if not target_wf_name: return wrap_ascii(user_query, "Ad-hoc trace cancelled. No workflow name provided.")

        log_lines = self.ssh_manager.fetch_remote_log(lines_to_read, show_workflow_note=True)
        if isinstance(log_lines, str) and log_lines.startswith("ERROR:"): return wrap_ascii(user_query, log_lines)

        relevant_wfiids = []
        for line in log_lines:
            if f"Name='{target_wf_name}'" in line:
                wfiid_match = re.search(r'WFIID=(\d+)', line)
                if wfiid_match:
                    wfiid = wfiid_match.group(1)
                    if wfiid not in relevant_wfiids: relevant_wfiids.append(wfiid)

        if not relevant_wfiids:
            return wrap_ascii(user_query, f"Ad-Hoc Profiler complete. No executions for '{target_wf_name}' were found in the recent log.\nEnsure Workflow Logging is enabled, check your spelling, trigger the workflow, and try again.")

        target_wfiid = relevant_wfiids[-1]
        execution_trace = []
        self.last_live_record_counts = {}
        
        for line in log_lines:
            if f"WFIID={target_wfiid}" in line:
                tsid_match = re.search(r'(?i)(?:TSID=|TaskId\s*=\s*)(\d+)', line)
                if tsid_match:
                    task_id = tsid_match.group(1)
                    label_match = re.search(r"Label='([^']*)'", line)
                    t_name = label_match.group(1) if label_match else ""
                    type_match = re.search(r'TaskStep:\s*[a-zA-Z\s]+\((\d+)\)', line)
                    t_type = type_match.group(1) if type_match else "Unknown"
                    
                    if not t_name:
                        type_map = {'1': 'Start', '9': 'End', '12': 'Unnamed Component', '14': 'Switch', '22': 'Query', '23': 'Modify Metadata', '25': 'Create Record', '28': 'Modify Records', '29': 'Retrieve', '39': 'Custom Task'}
                        t_name = type_map.get(t_type, f"Task Type {t_type}")
                    
                    status_match = re.search(r"Status='([^']+)'", line)
                    success_match = re.search(r"Success=([a-zA-Z]+)", line)
                    status_val = status_match.group(1) if status_match else "UNKNOWN"
                    success_val = success_match.group(1).lower() if success_match else "unknown"
                    context_parts = [f"Status: {status_val}", f"Success: {success_val}"]
                    
                    if t_type == '14':
                        ue_match = re.search(r"UserEvent='([^']*)'", line)
                        user_event = ue_match.group(1) if ue_match else ""
                        if "Edge-0" in user_event: context_parts.append("Switch Condition: PASSED (True Path)")
                        elif "Edge-1" in user_event or not user_event: context_parts.append("Switch Condition: FAILED (False/Default Path)")

                    if t_type in ['22', '29']:
                        results_match = re.search(r"Results=(\d+)", line)
                        if results_match: 
                            r_val = int(results_match.group(1))
                            context_parts.append(f"Records Retrieved: {r_val}")
                            self.last_live_record_counts[str(task_id)] = r_val

                    context_str = "[" + " | ".join(context_parts) + "]"
                    
                    if t_type != '12':
                        if not execution_trace or execution_trace[-1]['id'] != task_id:
                            execution_trace.append({'id': task_id, 'name': t_name, 'type': t_type, 'context': context_str})
                            
        self.last_execution_trace_ids = [step['id'] for step in execution_trace]

        output = [
            "--- Ad-Hoc Chronological Live Execution Trace (No OMP) ---",
            f"Isolated Workflow Instance ID (WFIID): {target_wfiid} for '{target_wf_name}'",
            f"Successfully tracked {len(execution_trace)} metadata steps routing in real-time.",
            "\n[!] NOTE: Because this workflow is not in the loaded OM Package, deep logic translations and payload fetching are disabled.\n"
        ]
        
        for index, step in enumerate(execution_trace):
            route_marker = "  -> " if index > 0 else "  START: "
            output.append(f"{route_marker}Task {step['id']} | Type {step['type']} | '{step['name']}' {step['context']}")

        print(wrap_ascii(user_query, "\n".join(output)))
        
        while True:
            ans = input("\n[?] If you would like deep logic analysis, as well as live payload fetching, please include the workflow in your OM Package before requesting a live trace.\nOtherwise, would you like to ask a question about one of the workflows detected in the loaded OM Package? (Yes/No): ")
            if ans.strip().lower() in ['y', 'yes']:
                return self.trace_live_execution_ssh(lines_to_read=15000, user_query="[Interactive] Trace live execution")
            elif ans.strip().lower() in ['n', 'no']:
                instructions = (
                    "\nType 'exit' to quit.\n"
                    "Type 'visualize' to generate an offline, interactive map of the workflow.\n"
                    "Type 'scan log' or 'what just failed' to securely scan the live logs for errors.\n"
                    "Type 'trace live execution' to map out exactly how your OMP workflow routed itself.\n"
                    "Type 'trace ad hoc live execution' or 'another workflow' to trace workflows not in the OMP."
                )
                return wrap_ascii("[Interactive] No", f"Resetting to main menu.\n{instructions}")
            else:
                print("\n[!] Please answer Yes or No.")

    def trace_live_execution_ssh(self, lines_to_read=15000, user_query=""):
        target_wf_name = None
        if len(self.engine.loaded_workflow_names) > 1:
            print(f"\n[?] Multiple workflows detected in the loaded OM Package:")
            for idx, name in enumerate(self.engine.loaded_workflow_names):
                print(f"    {idx + 1}) {name}")
            selection = input(f"\nWhich workflow would you like to trace? (1-{len(self.engine.loaded_workflow_names)}): ")
            try:
                target_wf_name = self.engine.loaded_workflow_names[int(selection) - 1]
            except (ValueError, IndexError):
                print("\n[!] Invalid selection. Defaulting to first workflow.")
                target_wf_name = self.engine.loaded_workflow_names[0]
        elif len(self.engine.loaded_workflow_names) == 1:
            target_wf_name = self.engine.loaded_workflow_names[0]
            
        log_lines = self.ssh_manager.fetch_remote_log(lines_to_read, show_workflow_note=True)
        if isinstance(log_lines, str) and log_lines.startswith("ERROR:"): return wrap_ascii(user_query, log_lines)

        relevant_wfiids = []
        for line in log_lines:
            if target_wf_name and f"Name='{target_wf_name}'" in line:
                wfiid_match = re.search(r'WFIID=(\d+)', line)
                if wfiid_match:
                    wfiid = wfiid_match.group(1)
                    if wfiid not in relevant_wfiids: relevant_wfiids.append(wfiid)
            elif not target_wf_name:
                task_match = re.search(r'(?i)(?:TSID=|TaskId\s*=\s*)(\d{5,})', line)
                wfiid_match = re.search(r'WFIID=(\d+)', line)
                if task_match and wfiid_match:
                    task_id = task_match.group(1)
                    if self.engine.get_node(task_id)[0]:
                        wfiid = wfiid_match.group(1)
                        if wfiid not in relevant_wfiids: relevant_wfiids.append(wfiid)

        if not relevant_wfiids:
            return wrap_ascii(user_query, "Execution Profiler complete. No tasks from the targeted OM Package workflow were found in the recent log.\nEnsure Workflow Logging is enabled, trigger your workflow in the front end, and try again.")

        self.current_context_wf = target_wf_name 
        target_wfiid = relevant_wfiids[-1]
        execution_trace = []
        self.last_live_records = {} 
        self.last_live_record_counts = {}
        
        for line in log_lines:
            if f"WFIID={target_wfiid}" in line:
                task_match = re.search(r'(?i)(?:TSID=|TaskId\s*=\s*)(\d{5,})', line)
                if task_match:
                    task_id = task_match.group(1)
                    
                    node_data, wf_name_trace = self.engine.get_node(task_id)
                    if node_data and (not target_wf_name or wf_name_trace == target_wf_name):
                        t_name = node_data.get('name', 'Unknown')
                        t_type = self._get_type_str(node_data)
                        
                        if str(task_id) not in self.last_live_records:
                            self.last_live_records[str(task_id)] = []
                            
                        so_match = re.search(r"SO=([-\d]+)", line)
                        if so_match:
                            spec_id = so_match.group(1)
                            if spec_id != '-1' and spec_id not in self.last_live_records[str(task_id)]:
                                self.last_live_records[str(task_id)].append(spec_id)

                        status_match = re.search(r"Status='([^']+)'", line)
                        success_match = re.search(r"Success=([a-zA-Z]+)", line)
                        status_val = status_match.group(1) if status_match else "UNKNOWN"
                        success_val = success_match.group(1).lower() if success_match else "unknown"
                        context_parts = [f"Status: {status_val}", f"Success: {success_val}"]
                        
                        if t_type == '14':
                            ue_match = re.search(r"UserEvent='([^']*)'", line)
                            user_event = ue_match.group(1) if ue_match else ""
                            if "Edge-0" in user_event: context_parts.append("Switch Condition: PASSED (True Path)")
                            elif "Edge-1" in user_event or not user_event: context_parts.append("Switch Condition: FAILED (False/Default Path)")

                        if t_type in ['22', '29']:
                            results_match = re.search(r"Results=(\d+)", line)
                            if results_match: 
                                r_val = int(results_match.group(1))
                                context_parts.append(f"Records Retrieved: {r_val}")
                                self.last_live_record_counts[str(task_id)] = r_val

                        context_str = "[" + " | ".join(context_parts) + "]"
                        
                        if t_type != '12':
                            if not execution_trace or execution_trace[-1]['id'] != task_id:
                                execution_trace.append({'id': task_id, 'name': t_name, 'type': t_type, 'context': context_str})

        self.last_execution_trace_ids = [step['id'] for step in execution_trace]

        output = ["--- Chronological Live Execution Trace ---"]
        if target_wf_name: output.append(f"Target Workflow: {target_wf_name}")
        output.append(f"Isolated Workflow Instance ID (WFIID): {target_wfiid}")
        output.append(f"Successfully tracked {len(execution_trace)} structural tasks routing in real-time.\n")
        
        for index, step in enumerate(execution_trace):
            route_marker = "  -> " if index > 0 else "  START: "
            output.append(f"{route_marker}Task {step['id']} | Type {step['type']} | '{step['name']}' {step['context']}")

        return wrap_ascii(user_query, "\n".join(output))

    def _synthesize_log_failure(self, task_id, error_msg, wf_name):
        output = [
            "--- Automated Graph-Filtered Log Trace ---",
            f"  [Match Found!]: Log error successfully correlated to loaded OM Package workflow '{wf_name}'.",
            f"  [Extracted Error Type]: {error_msg}",
            f"  [Failed Task ID]: {task_id}"
        ]
        
        node_data = self.engine.graphs[wf_name].nodes[str(task_id)]
        t_name = node_data.get('name', 'Unknown')
        t_type = self._get_type_str(node_data)
        
        output.extend([f"    -> Task Name: '{t_name}'", f"    -> Task Type: {t_type}", "\n  [Root-Cause Hypothesis]:"])
        
        if "NullPointer" in error_msg or "Null" in error_msg:
            output.append("    A NullPointerException means the task attempted to interact with a data record or property that did not actually exist at runtime.")
            if t_type == '29': output.append("    Because this is a Retrieve Task, it likely failed because the 'From' contextual record was missing, or a filtering field evaluating the Left/Right criteria was completely blank.")
            elif t_type == '14': output.append("    Because this is a Switch Task, it likely failed because the variable or specific field expression it is attempting to evaluate returned null.")
            elif t_type == '28': output.append("    Because this is a Modify Records Task, it likely attempted to map from a Source Field that was empty or not populated on the source record.")
            else: output.append("    Verify the underlying data payload triggering this task has the required fields populated.")
        elif "ORA-" in error_msg:
            output.append("    An Oracle 'ORA-' error indicates a database-level rejection. The TRIRIGA task successfully fired the logic, but the database rejected the resulting SQL statement.")
        
        output.append("\n  [Contextual Logic Deep-Dive]:")
        
        logic_explanation = self._explain_task_logic(task_id, "Generated Context Logic")
        logic_explanation = logic_explanation.replace("Deep Logic Analysis:", "Blueprint Mechanics for this Failed Task:")
        output.append(logic_explanation)
        
        return "\n".join(output)

    def _parse_condition(self, query):
        query_lower = query.lower()
        part = ""
        if " when " in query_lower: part = query[query_lower.index(" when ") + 6:]
        elif " if " in query_lower: part = query[query_lower.index(" if ") + 4:]
        else: return None, None
            
        operators = [" is equal to ", " equals ", " == ", " = ", " is "]
        for op in operators:
            if op in part.lower():
                idx = part.lower().index(op)
                field = part[:idx].strip()
                val = part[idx + len(op):].strip(" \t\n\r\"'?.,")
                return field, val
        return None, None

    def _extract_task_identifier(self, query):
        m = re.search(r'(?i)(?:id\s*[=:]?\s*["\']?|task\s+)[\#]?(\d{5,})', query)
        if m: return m.group(1).strip()
        # Bare numeric ID anywhere in the sentence.
        m = re.search(r'\b(\d{5,})\b', query)
        if m: return m.group(1).strip()
        m = re.search(r'["\'](.*?)["\']', query)
        if m: return m.group(1).strip()
        m = re.search(r'(?i)(?:task|called|at|about|in)\s+([a-zA-Z0-9_\?]+)', query)
        if m: return m.group(1).strip()
        return None

    def _find_task_nodes(self, task_identifier):
        """Locate tasks by ID or name across the active context; fuzzy-match names.

        Returns (found_nodes, note) where found_nodes is [(node_id, data, wf_name)]
        and note carries a 'did you mean' clarification when fuzzy matching fired.
        """
        found_nodes = []
        for wf_name, graph in self._get_target_workflows().items():
            for node_id, data in graph.nodes(data=True):
                name = data.get('name', '').lower()
                if task_identifier.lower() in [name, name.strip('?'), str(node_id)]:
                    found_nodes.append((node_id, data, wf_name))
        if found_nodes:
            return found_nodes, ""

        # Fuzzy fallback over task names.
        name_index = {}
        for wf_name, graph in self._get_target_workflows().items():
            for node_id, data in graph.nodes(data=True):
                n = str(data.get('name', '')).lower()
                if n and not n.startswith('unnamed'):
                    name_index.setdefault(n, []).append((node_id, data, wf_name))
        close = difflib.get_close_matches(task_identifier.lower(), list(name_index.keys()), n=1, cutoff=0.6)
        if close:
            matches = name_index[close[0]]
            display = matches[0][1].get('name', close[0])
            return matches, f"[?] No exact match for '{task_identifier}'; interpreting it as task '{display}'."
        return [], ""

    def _extract_tririga_string(self, query):
        words = query.split()
        for word in words:
            clean_word = re.sub(r'[^a-zA-Z0-9_]', '', word)
            if clean_word.startswith('tri') or clean_word.startswith('cst') or len(clean_word) > 8:
                return clean_word
        return None

    def _translate_operator(self, op_code):
        # Single source of truth for operator codes lives in cli/knowledge.py.
        return knowledge.translate_operator(op_code)

    def _trace_condition(self, field, value, user_query):
        val_clean = value.lower()
        pattern = re.compile(rf"\b{re.escape(val_clean)}\b")
        output = []
        
        for wf_name, graph in self._get_target_workflows().items():
            origin_nodes = []
            for node, data in graph.nodes(data=True):
                t_type = self._get_type_str(data)
                if t_type in ['14', '29'] and pattern.search(str(data).lower()):
                    origin_nodes.append(node)
                    
            for start_node in origin_nodes:
                node_data = graph.nodes[start_node]
                t_name = node_data.get('name', 'Unknown')
                t_type = self._get_type_str(node_data)
                
                downstream_nodes = list(nx.descendants(graph, start_node))
                if not downstream_nodes:
                    output.append(f"[{wf_name}] When condition '{value}' passes at Task '{t_name}' (ID: {start_node}), it hits a dead end.")
                    continue
                    
                mod_data, mod_gui, actions = set(), set(), set()
                for d_node in downstream_nodes:
                    d_data = graph.nodes[d_node]
                    for f in d_data.get('TrgtFld', []): mod_data.add(f)
                    for f in d_data.get('Field', []): mod_gui.add(f)
                    for a in d_data.get('Action', []): actions.add(a)
                    
                summary = f"[{wf_name}] When condition [{field} = '{value}'] passes at Task '{t_name}' (ID: {start_node}, Type: {t_type}):\n"
                summary += f"  -> Proceeds downstream through {len(downstream_nodes)} subsequent task(s).\n"
                if mod_data: summary += f"  -> Ultimately updates Database Fields: {', '.join(mod_data)}\n"
                
                real_mod_gui = [g for g in mod_gui if g != '^^']
                if real_mod_gui: summary += f"  -> Ultimately modifies GUI Properties: {', '.join(real_mod_gui)}\n"
                if actions: summary += f"  -> Ultimately triggers Actions: {', '.join(actions)}\n"
                output.append(summary)
                
        if not output: return wrap_ascii(user_query, f"Could not find any Decision Gate evaluating the condition '{value}' across active contexts.")
        return wrap_ascii(user_query, f"Forward Execution Trace:\n\n" + "\n\n".join(output))

    def _explain_purpose(self, wf_name):
        meta = self.engine.workflow_metadata.get(wf_name, {})
        name = meta.get('Name', wf_name)
        desc = meta.get('Description', 'No manual description provided.')
        
        target_bos, evaluated_fields, modified_data_fields, modified_gui_fields, modified_gui_sections, actions_triggered = set(), set(), set(), set(), set(), set()
        task_types_found = {}

        graph = self.engine.graphs[wf_name]
        for node, data in graph.nodes(data=True):
            t_type = self._get_type_str(data)
            task_types_found[t_type] = task_types_found.get(t_type, 0) + 1
            
            for f in data.get('PField', []): evaluated_fields.add(f)
            for f in data.get('LFldName', []): evaluated_fields.add(f)
            for f in data.get('TrgtFld', []): modified_data_fields.add(f)
            for a in data.get('Action', []): actions_triggered.add(a)
            for f in data.get('Field', []): 
                if f != '^^': modified_gui_fields.add(f)
            for gm in data.get('GUIMappings', []):
                sec = gm.get('Section')
                fld = gm.get('Field')
                if sec and sec != '^^': modified_gui_sections.add(sec)
                if fld and fld != '^^': modified_gui_fields.add(fld)
            
            bo = data.get('BO', data.get('BoName', data.get('PBO', data.get('ChildBO', data.get('RefObject')))))
            if bo and isinstance(bo, str): target_bos.add(bo)
            elif bo and isinstance(bo, list): target_bos.update(bo)

        target_bos.discard('System')
        target_bos.discard('Workflow')
        target_bos.discard('Any')

        eval_str = ", ".join(list(evaluated_fields)[:10]) if evaluated_fields else "various record properties"
        data_mod_str = ", ".join(list(modified_data_fields)[:10]) if modified_data_fields else "None detected"
        gui_mod_str = ", ".join(list(modified_gui_fields)[:10]) if modified_gui_fields else "None detected"
        sec_mod_str = ", ".join(list(modified_gui_sections)[:10]) if modified_gui_sections else "None detected"
        act_str = f" Triggers actions: [{', '.join(list(actions_triggered))}]." if actions_triggered else ""

        summary = (
            f"Workflow Name: {name}\n"
            f"Manual Description: {desc}\n\n"
            f"--- Auto-Generated Universal Purpose ---\n"
            f"Based on comprehensive structural mapping, this workflow utilizes {len(task_types_found)} different types of task logic. "
            f"It actively evaluates parameters (including {eval_str}) to filter data and drive execution.{act_str} "
            f"Across the targeted Business Objects ({', '.join(target_bos)}), the workflow affects the following:\n"
            f"  - Database Fields Updated: [{data_mod_str}]\n"
            f"  - GUI Fields Modified: [{gui_mod_str}]\n"
            f"  - GUI Sections Modified: [{sec_mod_str}]\n"
        )
        return summary

    def _find_references(self, search_term, user_query):
        output = []
        term = search_term.lower()
        
        for wf_name, graph in self._get_target_workflows().items():
            for node_id, data in graph.nodes(data=True):
                found_in = []
                for f in data.get('TrgtFld', []):
                    if term == f.lower(): found_in.append("Target Data Field (Modifies Record)")
                for f in data.get('Field', []):
                    if term == f.lower(): found_in.append("GUI Modifier (Changes Form View)")
                for gm in data.get('GUIMappings', []):
                    if term == gm.get('Section', '').lower() or term == gm.get('Field', '').lower() or term == gm.get('Tab', '').lower():
                        found_in.append("GUI Modifier (Changes Form View)")
                for f in data.get('PField', []) + data.get('LFldName', []) + data.get('SrcFld', []):
                    if term == f.lower(): found_in.append("Logic/Filter Evaluation (Reads Record)")
                for exp in data.get('Expression', []):
                    if term in exp.lower(): found_in.append("Custom Expression Formula")
                    
                if found_in:
                    t_name = data.get('name', 'Unknown')
                    t_type = self._get_type_str(data)
                    output.append(f"[{wf_name}] Task '{t_name}' (ID: {node_id}, Type: {t_type}) interacts with '{search_term}' as: {', '.join(set(found_in))}")
                    
        if not output: return wrap_ascii(user_query, f"No tasks in active workflow context currently reference or touch '{search_term}'.")
        return wrap_ascii(user_query, f"Reverse Search Results for '{search_term}':\n" + "\n".join(output))

    def _analyze_failure(self, task_identifier, user_query):
        found_nodes, fuzzy_note = self._find_task_nodes(task_identifier)
        if not found_nodes: return wrap_ascii(user_query, f"Error: Could not find task '{task_identifier}' in active workflow context.")
            
        output = []
        if fuzzy_note: output.append(fuzzy_note)
        for node_id, data, wf_name in found_nodes:
            output.append(f"Root-Cause Analysis for Failed Task: '{data.get('name')}' (ID: {node_id}, Type: {self._get_type_str(data)}) in '{wf_name}'")
            
            in_edges = list(self.engine.graphs[wf_name].predecessors(node_id))
            if not in_edges and self._get_type_str(data) not in ['1', 'Trigger', 'Start']:
                output.append("  [FAULT DETECTED]: Structural Orphan. No incoming logic routes exist.")
                continue
                
            output.append("  [Structure]: Reachable from previous tasks.")
            output.append("  [Prerequisite Constraints]:")
            
            for parent_id in in_edges:
                parent_data = self.engine.graphs[wf_name].nodes[parent_id]
                parent_name = parent_data.get('name', parent_id)
                p_type = self._get_type_str(parent_data)
                
                expressions = parent_data.get('Expression', [])
                fields = parent_data.get('PField', [])
                filters = parent_data.get('LFldName', [])
                queries = parent_data.get('QueryName', [])
                assocs = parent_data.get('AssociationName', parent_data.get('AssocName', []))
                
                output.append(f"    -> Dependent on Task: '{parent_name}' (Type {p_type})")
                if expressions: output.append(f"       Constraint (Condition): Ensure evaluation equals TRUE: {', '.join(expressions)}")
                if fields or filters:
                    combined_fields = fields + filters
                    output.append(f"       Constraint (Data Filtering): Verify targeted record contains correct data in field(s): {', '.join(combined_fields)}")
                if queries: output.append(f"       Constraint (Query): System must successfully return records from query: {', '.join(queries)}")
                if assocs:
                    a_list = assocs if isinstance(assocs, list) else [assocs]
                    output.append(f"       Constraint (Association): Requires active association link(s): {', '.join(a_list)}")
                    
            output.append("    -> If all preceding constraints are met, verify the active task's payload mapping contains valid source values.")
        return wrap_ascii(user_query, "\n".join(output))

    def _explain_task_logic(self, task_identifier, user_query):
        found_nodes, fuzzy_note = self._find_task_nodes(task_identifier)
        if not found_nodes: return wrap_ascii(user_query, f"Error: Could not find task '{task_identifier}' in active workflow context.")
            
        output = []
        if fuzzy_note: output.append(fuzzy_note)
        spec_ids_to_query = []
        active_t_bo = None
        
        for node_id, data, wf_name in found_nodes:
            self.current_context_wf = wf_name 
            t_type = self._get_type_str(data)
            t_name = data.get('name', 'Unknown')
            t_bo = data.get('BO', data.get('BoName', 'Unknown BO'))
            if isinstance(t_bo, list): t_bo = t_bo[0]
            active_t_bo = t_bo
            
            output.append(f"Deep Logic Analysis: '{t_name}' (ID: {node_id}, Type {t_type}, BO: {t_bo}) from '{wf_name}'")
            
            def get_task_context(task_ids):
                if not isinstance(task_ids, list): task_ids = [task_ids]
                contexts = []
                for tid in task_ids:
                    if str(tid) in ['-1', '0', '']: contexts.append("Start Task / Triggering Record")
                    elif self.engine.graphs[wf_name].has_node(str(tid)):
                        n = self.engine.graphs[wf_name].nodes[str(tid)]
                        n_name = n.get('name', f"Task {tid}")
                        n_bo = n.get('BO', n.get('BoName', 'Unknown BO'))
                        if isinstance(n_bo, list): n_bo = n_bo[0]
                        contexts.append(f"task '{n_name}' ({n_bo})")
                    else: contexts.append(f"Task ID {tid}")
                return contexts

            synopsis = ""

            if t_type == '22':
                filter_bo = data.get('FilterBo', ['Unknown Query'])
                q_name = filter_bo[0] if isinstance(filter_bo, list) else filter_bo
                output.append("  [Query Execution Mechanics]:")
                output.append(f"    - TARGET QUERY: Executes the system query named '{q_name}'")
                q_data = self.engine.queries.get(q_name)
                if q_data:
                    ret_cols = q_data.get('Columns', [])
                    q_filters = q_data.get('Filters', [])
                    q_mod = q_data.get('Module', 'Unknown Module')
                    q_bo = q_data.get('BO', 'Unknown BO')
                    if ret_cols: output.append(f"    - RETURNED DATA: Fetches {len(ret_cols)} fields, including [{', '.join(ret_cols[:3])}]")
                    if q_filters:
                        output.append("    - INTERNAL QUERY FILTERS (The 'Black Box'):")
                        for f in q_filters: output.append(f"        * Requires '{f['Field']}' {f['Operator']} '{f['Value']}' (Context: Module '{q_mod}' :: BO '{q_bo}')")
                    synopsis = f"\n  [Plain English Synopsis]:\n    This task triggers the '{q_name}' query to retrieve records."
                else:
                    output.append("    - INTERNAL QUERY FILTERS: [Query XML not found in the loaded OM Package]")
                    synopsis = f"\n  [Plain English Synopsis]:\n    This task executes the '{q_name}' query."

            elif t_type == '29':
                queries = data.get('QueryName', [])
                assocs = data.get('AssociationName', data.get('AssocName', []))
                from_tasks = data.get('FromTask', [])
                filter_tasks = data.get('FilterTask', [])
                output.append("  [Retrieve Task Mechanics]:")
                from_target = ""
                if queries:
                    from_target = f"query '{', '.join(queries)}'"
                    output.append(f"    - FROM RECORDS: Takes the business object of {from_target}")
                elif assocs:
                    from_target = f"association '{', '.join(assocs)}'"
                    output.append(f"    - FROM RECORDS: Traverses {from_target}")
                elif from_tasks:
                    from_target = ", ".join(get_task_context(from_tasks))
                    output.append(f"    - FROM RECORDS: Takes the business object of {from_target}")
                else:
                    from_target = "standard record context"
                    output.append(f"    - FROM RECORDS: Uses {from_target}.")
                    
                filter_target = ""
                if filter_tasks:
                    filter_target = ", ".join(get_task_context(filter_tasks))
                    output.append(f"    - FILTER RECORDS: Takes the business object of {filter_target}")
                else:
                    filter_target = "Current Workflow Record"
                    output.append(f"    - FILTER RECORDS: Takes the business object of {filter_target}")
                
                l_fields = data.get('LFldName', []) or data.get('PField', [])
                r_fields = data.get('RFldName', [])
                constants = data.get('ConstantValue', []) or data.get('Value', []) or data.get('RValue', [])
                l_str = ', '.join(l_fields) if l_fields else "Record ID"
                operators = data.get('Operator')
                op_raw = str(operators[0]) if isinstance(operators, list) and operators else operators if isinstance(operators, str) else '10' 
                op_str = self._translate_operator(op_raw)
                r_str = ""

                if l_fields or constants or r_fields:
                    output.append("    - FILTER USING:")
                    if l_fields: output.append(f"        * Left Data: '{l_str}' (Field on the From Records)")
                    else: output.append("        * Left Data: [Not Specified - Relies on Record ID]")
                    output.append(f"        * Operator: {op_raw} ({op_str})")
                        
                    if constants:
                        r_str = f"the exact string '{', '.join(constants)}'"
                        output.append(f"        * Right Data: '{', '.join(constants)}'")
                    elif r_fields:
                        r_ctx = ", ".join(get_task_context(data.get('RTask', data.get('RTaskId', [])))) or filter_target
                        r_str = f"the '{', '.join(r_fields)}' field from {r_ctx}"
                        output.append(f"        * Right Data: '{', '.join(r_fields)}' (Pulled dynamically from {r_ctx})")
                    else:
                        r_str = "[Not Specified]"
                        output.append("        * Right Data: [Not Specified]")
                
                op_lower = op_str.lower()
                if op_raw in ['20', '21']: synopsis = f"\n  [Plain English Synopsis]:\n    This task fetches records from {from_target} WHERE their '{l_str}' field {op_lower}."
                else: synopsis = f"\n  [Plain English Synopsis]:\n    This task fetches records from {from_target} WHERE their '{l_str}' field {op_lower} {r_str}."

            elif t_type == '14':
                expressions = data.get('Expression', [])
                output.append("  [Switch Task Mechanics]:")
                output.append("    - DECISION GATE: The workflow evaluates conditions here to route the execution path.")
                if expressions:
                    output.append(f"    - Formula Evaluated: {', '.join(expressions)}")
                    synopsis = f"\n  [Plain English Synopsis]:\n    This task evaluates if the formula ({', '.join(expressions)}) is true to decide where to route the workflow."
                    
                l_fields = data.get('LFldName', data.get('PField', []))
                r_fields = data.get('RFldName', [])
                constants = data.get('ConstantValue', []) or data.get('Value', []) or data.get('RValue', [])
                l_tasks = data.get('LTask', data.get('LTaskId', []))
                
                if l_fields or constants or r_fields:
                    output.append("    - FILTER USING:")
                    l_ctx = ", ".join(get_task_context(l_tasks)) if l_tasks else "Workflow Default Context"
                    l_str = ', '.join(l_fields) if l_fields else "Record ID"
                    if l_fields: output.append(f"        * Left Data: '{l_str}' (Pulled from {l_ctx})")
                    operators = data.get('Operator')
                    op_raw = str(operators[0]) if isinstance(operators, list) and operators else operators if isinstance(operators, str) else '10' 
                    op_str = self._translate_operator(op_raw)
                    output.append(f"        * Operator: {op_raw} ({op_str})")
                    r_str = ""
                    if constants:
                        r_str = f"the exact value '{', '.join(constants)}'"
                        output.append(f"        * Right Data: '{', '.join(constants)}'")
                    elif r_fields:
                        r_ctx = ", ".join(get_task_context(data.get('RTask', data.get('RTaskId', [])))) or "System Default Context"
                        r_str = f"the '{', '.join(r_fields)}' field from {r_ctx}"
                        output.append(f"        * Right Data: '{', '.join(r_fields)}' (Pulled dynamically from {r_ctx})")

                    if not synopsis:
                        op_lower = op_str.lower()
                        if op_raw in ['20', '21']: synopsis = f"\n  [Plain English Synopsis]:\n    This task checks if the '{l_str}' field from {l_ctx} {op_lower} to determine workflow routing."
                        else: synopsis = f"\n  [Plain English Synopsis]:\n    This task checks if the '{l_str}' field from {l_ctx} {op_lower} {r_str} to determine workflow routing."

            elif t_type == '23':
                gui_mappings = data.get('GUIMappings', [])
                output.append("  [Modify Metadata Mechanics]:")
                if not gui_mappings:
                    output.append("    - No GUI mappings found in this task.")
                    synopsis = "\n  [Plain English Synopsis]:\n    This task is intended to modify the UI but contains no explicit mappings."
                else:
                    state_changes, target_sections, target_fields, target_tabs = [], set(), set(), set()
                    for gm in gui_mappings:
                        tab, sec, fld = gm.get('Tab', ''), gm.get('Field', '')
                        p_type, p_val = gm.get('PropType', ''), gm.get('PropVal', '').lower()
                        if tab and tab != '^^': target_tabs.add(tab)
                        if sec and sec != '^^': target_sections.add(sec)
                        if fld and fld != '^^': target_fields.add(fld)
                        
                        prop_str = "'Visible' attribute" if p_type == '1' else "'Read-Only' attribute" if p_type == '3' else "'Required' attribute" if p_type == '8' else f"Property {p_type}"
                        val_str = "'No'" if p_val == 'false' else "'Yes'" if p_val == 'true' else p_val
                        state_changes.append(f"{prop_str} updated to {val_str}")
                        
                    unique_states = list(set(state_changes))
                    hierarchy = []
                    if target_tabs: hierarchy.append(f"Tab(s): [{', '.join(target_tabs)}]")
                    if target_sections: hierarchy.append(f"Section(s): [{', '.join(target_sections)}]")
                    if target_fields: hierarchy.append(f"Field(s): [{', '.join(target_fields)}]")
                    
                    if hierarchy: output.append(f"    - UI TARGETS: {', '.join(hierarchy)}")
                    else: output.append("    - UI TARGETS: General Form Context")
                    output.append(f"    - PROPERTY CHANGES: {', '.join(unique_states)}")
                    
                    targets_text_parts = []
                    if target_sections: targets_text_parts.append(f"section(s) '{', '.join(target_sections)}'")
                    if target_fields: targets_text_parts.append(f"field(s) '{', '.join(target_fields)}'")
                    targets_text = " and ".join(targets_text_parts) if targets_text_parts else f"tab(s) '{', '.join(target_tabs)}'" if target_tabs else "form properties"
                    synopsis = f"\n  [Plain English Synopsis]:\n    This task dynamically alters the user interface. It targets the {targets_text} and sets {', '.join(unique_states)}."

            elif t_type == '28':
                mod_data = data.get('TrgtFld', [])
                mod_gui = [g for g in data.get('Field', []) if g != '^^']
                src_data = data.get('SrcFld', [])
                
                output.append("  [Modify Records Mechanics]:")
                if mod_data: output.append(f"    - MAPPED DATA FIELDS: Updates database values for [{', '.join(mod_data)}]")
                if mod_gui: output.append(f"    - MAPPED GUI FIELDS: Modifies form properties for [{', '.join(mod_gui)}]")
                if src_data: output.append(f"    - SOURCE FIELDS: Pulls new dynamic values from [{', '.join(src_data)}]")
                    
                synopsis = f"\n  [Plain English Synopsis]:\n    This task updates the target record by modifying data fields ({', '.join(mod_data[:3]) if mod_data else 'None'})"
                if mod_gui: synopsis += f" and/or form visibility ({', '.join(mod_gui[:3])})."
                else: synopsis += "."
                if src_data: synopsis += f" It pulls the new values dynamically from fields like ({', '.join(src_data[:3])})."

            else:
                for key, label in [('Expression', 'Conditions'), ('PField', 'Evaluated Fields'), ('LFldName', 'Data Filters Applied'), ('SrcFld', 'Source Mapping Fields'), ('TrgtFld', 'Data Fields Modified'), ('Field', 'GUI Fields Modified'), ('QueryName', 'Queries Executed'), ('Action', 'Triggered Actions')]:
                    vals = data.get(key, [])
                    if vals: output.append(f"  - {label}: {', '.join(vals)}")
            
            if synopsis: output.append(synopsis)

            spec_ids = []
            if t_type in ['22', '29']: spec_ids = self.engine.fetch_retrieved_spec_ids(wf_name, node_id)
            if not spec_ids and str(node_id) in getattr(self, 'last_live_records', {}): spec_ids = self.last_live_records[str(node_id)]
            spec_ids_to_query = spec_ids    
            
            if spec_ids:
                first_id = spec_ids[0]
                payload = self.engine.fetch_live_record_data(t_bo, first_id)
                output.append(f"\n  [Live Execution Payload Data]:")
                
                true_bo = None
                if payload:
                    true_bo = payload.pop('_True_BO_Name', t_bo)
                    if true_bo and t_bo and true_bo.lower() != t_bo.lower():
                        output.append(f"    [!] NOTE: TRIRIGA logged the Context Record for this task. Displaying Context Payload ({true_bo}).")
                
                if t_type in ['22', '29'] and (not true_bo or true_bo.lower() == t_bo.lower()):
                    output.append(f"    - Extracted via Blueprint SQL Strike! (Record 1 of {len(spec_ids)} | Spec ID: {first_id})")
                else:
                    output.append(f"    - Captured from recent trace! (Record 1 of {len(spec_ids)} | Spec ID: {first_id})")

                expected_results = self.last_live_record_counts.get(str(node_id), 0)
                if expected_results > 1 and len(spec_ids) == 1:
                    output.append(f"    [!] WARNING: TRIRIGA successfully fetched {expected_results} records, but only logged the Context ID.")
                    output.append(f"                 Dynamic SQL extraction is required to view the individual targets.")

                if payload:
                    output.extend(TaskInsight.format_payload_rows_cli(payload.items()))
                else:
                    output.append("        * Data payload could not be extracted from live tables.")
                
            out_edges = list(self.engine.graphs[wf_name].successors(node_id))
            if out_edges:
                target_strings = []
                for n in out_edges:
                    child_data = self.engine.graphs[wf_name].nodes[n]
                    c_name = child_data.get('name', n)
                    c_type = self._get_type_str(child_data)
                    
                    if c_type in ['12', '11'] or (c_name.lower().startswith('unnamed') and c_type != '9') or c_type == 'generic':
                        pass
                    else:
                        target_strings.append(c_name)
                
                if target_strings:
                    output.append(f"  - Routes To: {', '.join(target_strings)}")

        output_str = "\n".join(output)

        # Render remaining retrieved payloads inline (bounded), replacing the previous
        # blocking input() prompt so the handler returns a single complete result.
        if len(spec_ids_to_query) > 1:
            MAX_EXTRA_RECORDS = 10
            remaining = spec_ids_to_query[1:]
            shown = remaining[:MAX_EXTRA_RECORDS]

            extra = [f"\n--- Additional Retrieved Payloads ({len(remaining)} further record(s)) ---"]
            for offset, sid in enumerate(shown):
                record_index = offset + 2
                payload = self.engine.fetch_live_record_data(active_t_bo, sid)
                extra.append(f"\n  [Record {record_index} of {len(spec_ids_to_query)} | Spec ID: {sid}]")
                if payload:
                    true_bo = payload.pop('_True_BO_Name', active_t_bo)
                    if true_bo and active_t_bo and true_bo.lower() != active_t_bo.lower():
                        extra.append(f"    [!] NOTE: Displaying Context Payload ({true_bo}).")
                    extra.extend(TaskInsight.format_payload_rows_cli(payload.items(), indent="      "))
                else:
                    extra.append("      * Data payload could not be extracted from live tables.")

            if len(remaining) > MAX_EXTRA_RECORDS:
                extra.append(f"\n  [!] {len(remaining) - MAX_EXTRA_RECORDS} additional record(s) omitted for brevity.")

            output_str = output_str + "\n" + "\n".join(extra)

        return wrap_ascii(user_query, output_str)

    def _find_orphans(self):
        output = []
        for wf_name, graph in self.engine.graphs.items():
            orphans = [data.get('name', 'Unknown') for node, data in graph.nodes(data=True) if graph.in_degree(node) == 0 and self._get_type_str(data) not in ['1', 'Trigger', 'Start']]
            if orphans:
                output.append(f"Found {len(orphans)} orphans in '{wf_name}':\n" + "\n".join([f"  - {o}" for o in orphans]))
        return "\n\n".join(output) if output else "Healthy. No orphans in any loaded workflow."

    def _trace_path(self, start_name, end_name):
        output = []
        for wf_name, graph in self.engine.graphs.items():
            start_id, end_id = None, None
            for node, data in graph.nodes(data=True):
                if data.get('name', '').lower() == start_name.lower() or str(node) == start_name: start_id = node
                if data.get('name', '').lower() == end_name.lower() or str(node) == end_name: end_id = node
                    
            if start_id and end_id:
                if nx.has_path(graph, start_id, end_id):
                    path = nx.shortest_path(graph, start_id, end_id)
                    path_names = [graph.nodes[n].get('name', n) for n in path]
                    output.append(f"[{wf_name}] Path confirmed:\n  {' -> '.join(path_names)}")
        return "\n\n".join(output) if output else "Could not locate a valid transition path between targets in any loaded workflow."