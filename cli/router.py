import re
import networkx as nx
from cli.formatters import wrap_ascii, format_path_narrative
from integrations.ssh_client import SSHClientManager

class TririgaNLPRouter:
    def __init__(self, diagnostic_engine, ssh_host=None, ssh_user=None, ssh_log_path=None, offline_mode=False, local_log_path=None):
        self.engine = diagnostic_engine
        self.ssh_manager = SSHClientManager(ssh_host, ssh_user, ssh_log_path, offline_mode, local_log_path) if (ssh_host or offline_mode) else None
        self.last_live_records = {} 
        self.last_live_record_counts = {} 
        self.current_context_wf = None 
        
        # Initialize the Semantic Dispatcher
        self._build_command_registry()

    def _build_command_registry(self):
        """
        The Semantic Dispatcher: Maps compiled regex patterns directly to handler methods.
        Order is critical: Most specific patterns must appear before general catch-alls.
        """
        self.command_registry = [
            (re.compile(r"why did it fail|check the log|scan log|what just failed|read log", re.IGNORECASE), self._cmd_scan_log),
            (re.compile(r"another workflow|trace ad hoc|ad hoc trace|ad-hoc trace|external workflow|not in omp", re.IGNORECASE), self._cmd_ad_hoc_trace),
            (re.compile(r"trace live|how did it execute|live execution|trace execution", re.IGNORECASE), self._cmd_live_trace),
            (re.compile(r"path.*from\s+['\"]?(.*?)['\"]?\s+to\s+['\"]?(.*?)['\"]?", re.IGNORECASE), self._cmd_trace_path),
            (re.compile(r"(?:what happens|trace).*(?:when|if)|(?:when|if).*(?:what happens|trace)", re.IGNORECASE), self._cmd_conditional_trace),
            (re.compile(r"fail|fix|broken", re.IGNORECASE), self._cmd_analyze_failure),
            (re.compile(r"updates|modifies|uses|where is|touches", re.IGNORECASE), self._cmd_find_references),
            (re.compile(r"purpose|what does this do|summary|summarize|explain this workflow|explain the workflow", re.IGNORECASE), self._cmd_explain_purpose),
            (re.compile(r"explain|what happens at|tell me about|look at|what is|diagnose|check|lap data|left data|right data", re.IGNORECASE), self._cmd_explain_task),
            (re.compile(r"orphan", re.IGNORECASE), self._cmd_find_orphans)
        ]

    def process_query(self, user_query):
        """Clean, robust semantic router replacing the legacy if/elif block."""
        for pattern, handler in self.command_registry:
            match = pattern.search(user_query)
            if match:
                return handler(user_query, match)
                
        return wrap_ascii(user_query, "I couldn't confidently parse that command. Try rephrasing, like 'Explain task 333376', or 'scan log'.")

    # ==========================================
    # COMMAND DISPATCH HANDLERS
    # ==========================================
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
        wf_name = self.current_context_wf
        
        if not wf_name:
            if len(self.engine.loaded_workflow_names) == 1:
                wf_name = self.engine.loaded_workflow_names[0]
                self.current_context_wf = wf_name
            else:
                return wrap_ascii(user_query, "Multiple workflows are loaded. Please run 'trace live execution' on one first so I know which context to explicitly explain.")
        
        base_summary = self._explain_purpose(wf_name)
        all_paths = self._generate_all_paths(wf_name)
        
        if not all_paths: return wrap_ascii(user_query, base_summary)
        
        total_paths = len(all_paths)
        current_idx = 1
        path_text = format_path_narrative(all_paths[0], 1, total_paths)
        
        if total_paths == 1:
            return wrap_ascii(user_query, base_summary + "\n\n" + path_text)
            
        print(wrap_ascii(user_query, base_summary + "\n\n" + path_text))
        
        while current_idx < total_paths:
            ans = input(f"\n[?] This workflow contains {total_paths - current_idx} other logical paths. Would you like to explore the next path? (Yes/No): ")
            if ans.strip().lower() in ['y', 'yes']:
                current_idx += 1
                path_text = format_path_narrative(all_paths[current_idx-1], current_idx, total_paths)
                if current_idx == total_paths:
                    return wrap_ascii(f"[Interactive] Exploring Path {current_idx}", path_text + "\n\n[!] All logic paths successfully explored.")
                else:
                    print(wrap_ascii(f"[Interactive] Exploring Path {current_idx}", path_text))
            elif ans.strip().lower() in ['n', 'no']:
                return wrap_ascii(f"[Interactive] Declined remaining paths", "Path exploration successfully closed.")
            else:
                print("\n[!] Please answer Yes or No.")
                
        return wrap_ascii("Exploration Complete", "All paths viewed.") 

    def _generate_all_paths(self, wf_name):
        graph = self.engine.graphs[wf_name]
        start_nodes = [n for n, d in graph.nodes(data=True) if self._get_type_str(d) in ['1', 'Trigger', 'Start']]
        if not start_nodes: 
            start_nodes = [n for n, d in graph.nodes(data=True) if graph.in_degree(n) == 0]
        
        all_paths = []
        
        def get_real_successors(node_id, visited_type12=None):
            if visited_type12 is None: visited_type12 = set()
            real_succs = []
            for succ in graph.successors(node_id):
                s_node = graph.nodes[succ]
                s_type = self._get_type_str(s_node)
                s_name = s_node.get('name', '').lower()
                
                is_invisible = s_type in ['12', '11'] or (s_name.startswith('unnamed') and s_type != '9') or s_type == 'generic'
                
                if is_invisible:
                    if succ not in visited_type12:
                        visited_type12.add(succ)
                        real_succs.extend(get_real_successors(succ, visited_type12))
                else:
                    real_succs.append(succ)
                    
            seen = set()
            return [x for x in real_succs if not (x in seen or seen.add(x))]
        
        def dfs(current_node, current_path_steps, visited):
            if current_node in visited: return
                
            node_data = graph.nodes[current_node]
            t_type = self._get_type_str(node_data)
            t_name = node_data.get('name', f"Task {current_node}")
            
            action_text = self._translate_task_to_action(current_node, node_data)
            step_info = {'id': current_node, 'name': t_name, 'type': t_type, 'action': action_text}
            new_path_steps = current_path_steps + [step_info]
            
            successors = get_real_successors(current_node)
            
            if not successors or t_type in ['9', '13', 'End']:
                all_paths.append(new_path_steps)
                return
                
            for succ in successors:
                step_info_copy = dict(step_info)
                if t_type == '14':
                    targets = node_data.get('TargetAssociation', '')
                    if isinstance(targets, list): targets = targets[0] if targets else ''
                    target_list = [t for t in targets.split(';') if t]
                    
                    is_true = False
                    if len(target_list) > 0:
                        true_raw_target = target_list[0]
                        if str(succ) == str(true_raw_target):
                            is_true = True
                        elif graph.has_node(true_raw_target):
                            tr_type = self._get_type_str(graph.nodes[true_raw_target])
                            tr_name = graph.nodes[true_raw_target].get('name', '').lower()
                            if tr_type in ['12', '11'] or (tr_name.startswith('unnamed') and tr_type != '9') or tr_type == 'generic':
                                if str(succ) in get_real_successors(true_raw_target):
                                    is_true = True
                                
                    path_str = "TRUE (Primary)" if is_true else "FALSE (Default)"
                    step_info_copy['action'] += f" Routed to the {path_str} path."
                    
                path_for_next = new_path_steps[:-1] + [step_info_copy]
                dfs(succ, path_for_next, visited | {current_node})

        for sn in start_nodes:
            dfs(sn, [], set())
            
        return all_paths

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
        m = re.search(r'["\'](.*?)["\']', query)
        if m: return m.group(1).strip()
        m = re.search(r'(?i)(?:task|called|at|about|in)\s+([a-zA-Z0-9_\?]+)', query)
        if m: return m.group(1).strip()
        return None

    def _extract_tririga_string(self, query):
        words = query.split()
        for word in words:
            clean_word = re.sub(r'[^a-zA-Z0-9_]', '', word)
            if clean_word.startswith('tri') or clean_word.startswith('cst') or len(clean_word) > 8:
                return clean_word
        return None

    def _translate_operator(self, op_code):
        if not op_code: return "Equals"
        if isinstance(op_code, list): op_code = op_code[0] if op_code else '10'
        op_map = {
            '10': 'Equals', '11': 'Does Not Equal', '12': 'Is Less Than', '13': 'Is Less Than or Equal To', 
            '14': 'Is Greater Than', '15': 'Is Greater Than or Equal To', '16': 'Contains', '17': 'Does Not Contain', 
            '18': 'Starts With', '19': 'Ends With', '20': 'Is Empty', '21': 'Is Not Empty', '22': 'Is In', '23': 'Is Not In'
        }
        return op_map.get(str(op_code).strip(), f"Unknown Operator ({str(op_code).strip()})")

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
        found_nodes = []
        for wf_name, graph in self._get_target_workflows().items():
            for node_id, data in graph.nodes(data=True):
                name = data.get('name', '').lower()
                if task_identifier.lower() in [name, name.strip('?'), str(node_id)]:
                    found_nodes.append((node_id, data, wf_name))
                
        if not found_nodes: return wrap_ascii(user_query, f"Error: Could not find task '{task_identifier}' in active workflow context.")
            
        output = []
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
        found_nodes = []
        for wf_name, graph in self._get_target_workflows().items():
            for node_id, data in graph.nodes(data=True):
                name = data.get('name', '').lower()
                if task_identifier.lower() in [name, name.strip('?'), str(node_id)]:
                    found_nodes.append((node_id, data, wf_name))
                
        if not found_nodes: return wrap_ascii(user_query, f"Error: Could not find task '{task_identifier}' in active workflow context.")
            
        output = []
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
                    items = list(payload.items())
                    for idx in range(0, len(items), 3):
                        chunk = items[idx:idx+3]
                        row_str = "  |  ".join([f"{k}: '{v}'" for k, v in chunk])
                        output.append(f"        * {row_str}")
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
        
        if len(spec_ids_to_query) > 1:
            print(wrap_ascii(user_query, output_str))
            
            while True:
                ans = input(f"\n[?] Would you like to see the remaining {len(spec_ids_to_query)-1} retrieved record payloads? (Yes/No): ")
                if ans.strip().lower() in ['y', 'yes']:
                    remainder_output = []
                    remainder_output.append(f"--- Remaining Payloads ---")
                    
                    for i in range(1, len(spec_ids_to_query)):
                        sid = spec_ids_to_query[i]
                        payload = self.engine.fetch_live_record_data(active_t_bo, sid)
                        
                        remainder_output.append(f"\n  [Record {i+1} of {len(spec_ids_to_query)} | Spec ID: {sid}]")
                        if payload:
                            true_bo = payload.pop('_True_BO_Name', active_t_bo)
                            if true_bo and active_t_bo and true_bo.lower() != active_t_bo.lower():
                                remainder_output.append(f"    [!] NOTE: Displaying Context Payload ({true_bo}).")

                            items = list(payload.items())
                            for idx in range(0, len(items), 3):
                                chunk = items[idx:idx+3]
                                row_str = "  |  ".join([f"{k}: '{v}'" for k, v in chunk])
                                remainder_output.append(f"      * {row_str}")
                        else:
                            remainder_output.append("      * Data payload could not be extracted from live tables.")
                            
                    return wrap_ascii("Yes (Displaying remaining records)", "\n".join(remainder_output))
                elif ans.strip().lower() in ['n', 'no']:
                    return wrap_ascii(ans, "Remaining payloads discarded.")
                else:
                    print("\n[!] Please answer Yes or No.")
        else:
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