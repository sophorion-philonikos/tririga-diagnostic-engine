"""TRIRIGA domain glossary: task types, operator codes, and platform concepts.

This module is the single source of truth for TRIRIGA code -> meaning lookups.
It consolidates the operator map previously duplicated in the router's
`_translate_operator` and the engine's SQL branches, and powers the interactive
"What does Type 14 mean?" style questions with definitions PLUS live usage
scanned from the currently loaded workflow graphs.
"""

TASK_TYPE_GLOSSARY = {
    '1': {
        'name': 'Start Task',
        'shape': 'Green oval',
        'what': "The entry point of the workflow. It fires when the workflow's triggering "
                "event occurs (e.g. an OnChange event on the target Business Object) and "
                "carries the triggering record into the workflow as the initial context.",
        'failures': "Rarely fails itself; if a workflow never runs, verify the trigger event, "
                    "the BO/Module binding in the workflow header, and that the workflow is Active.",
    },
    '9': {
        'name': 'End Task',
        'shape': 'Red oval',
        'what': "Terminates the workflow instance and finalizes its logic. All execution paths "
                "eventually converge on an End task.",
        'failures': "Does not fail on its own. If execution never reaches End, a task upstream "
                    "threw an exception or a Stop task halted the flow.",
    },
    '11': {
        'name': 'Junction / Connector (invisible)',
        'shape': 'Not rendered',
        'what': "A structural connector TRIRIGA inserts between visible tasks. It carries no "
                "business logic; the diagnostic engine hops over these when tracing paths.",
        'failures': "Not a failure point. Errors attributed to a junction actually belong to "
                    "the neighboring visible task.",
    },
    '12': {
        'name': 'Junction / Connector (invisible)',
        'shape': 'Not rendered',
        'what': "Same as Type 11: a routing connector with no business logic, used by the "
                "workflow builder to merge or fan out transitions between visible tasks.",
        'failures': "Not a failure point. Errors attributed to a junction actually belong to "
                    "the neighboring visible task.",
    },
    '13': {
        'name': 'Stop Task',
        'shape': 'Red oval',
        'what': "Immediately halts workflow execution, ending the instance at that point. "
                "Often used on validation-failure branches.",
        'failures': "If records seem 'stuck', check whether a Stop task ended the flow before "
                    "the expected downstream tasks could run.",
    },
    '14': {
        'name': 'Switch Task (Decision Gate)',
        'shape': 'Blue pentagon/scalene',
        'what': "Evaluates a condition (an Expression like p0 == \"DISP\" over record fields) "
                "and routes execution down its TRUE branch or FALSE/default branch. TRIRIGA "
                "encodes the branch targets in TargetAssociation and the truth of each branch "
                "index in EventName (e.g. 0=true;1=false;).",
        'failures': "A NullPointerException here usually means the evaluated field or variable "
                    "was null at runtime. Wrong routing usually means the compared value did not "
                    "match expectations (case, whitespace, or classification path differences).",
    },
    '22': {
        'name': 'Query Task',
        'shape': 'Green chevron',
        'what': "Executes a saved system query (report) and returns its result records into the "
                "workflow context for downstream tasks to consume. The query's own internal "
                "filters act as a 'black box' unless the query XML is in the OM Package.",
        'failures': "Zero results is the most common issue: verify the query's internal filters "
                    "against live data. Also confirm the query still exists and its BO matches.",
    },
    '23': {
        'name': 'Modify Metadata Task',
        'shape': 'Purple notched rectangle',
        'what': "Dynamically alters the user interface of a form at runtime: showing/hiding "
                "tabs, sections, or fields, or toggling Read-Only/Required attributes via "
                "GUI mappings. It does not change database data.",
        'failures': "If the UI does not change, verify the Tab/Section/Field names in the GUI "
                    "mappings still match the current form layout exactly.",
    },
    '25': {
        'name': 'Create Record Task',
        'shape': 'Rectangle',
        'what': "Instantiates a record of the specified Business Object in memory (a 'temp' "
                "record) or permanently, which downstream tasks can populate and reference.",
        'failures': "Failures usually stem from required fields not being mapped, or the BO "
                    "definition having changed since the workflow was built.",
    },
    '28': {
        'name': 'Modify Records Task',
        'shape': 'Pink rectangle',
        'what': "Updates one or more target records: writes values into database fields "
                "(TrgtFld) sourced from other records/fields (SrcFld) or constants (FldVal), "
                "per its ordered object-mapping records.",
        'failures': "A NullPointerException usually means a Source Field was empty on the source "
                    "record. Silent no-ops usually mean the target record set was empty.",
    },
    '29': {
        'name': 'Retrieve Records Task',
        'shape': 'Light-blue pill',
        'what': "Fetches records by traversing the relational map: takes a 'From' record set "
                "(a prior task's output or the triggering record), optionally follows an "
                "association, and filters using Left field / Operator / Right value criteria.",
        'failures': "A NullPointerException usually means the 'From' contextual record was "
                    "missing or a filter field was blank. Zero results means the association "
                    "link does not exist or the filter criteria matched nothing.",
    },
    '39': {
        'name': 'Custom Task',
        'shape': 'Rectangle',
        'what': "Executes custom Java logic registered on the platform (a Custom Business "
                "Object Class). Its behavior is defined entirely by the custom class.",
        'failures': "Failures surface as Java exceptions from the custom class; check the "
                    "server log stack trace for the implementing class name.",
    },
    '17': {
        'name': 'Schedule Task',
        'shape': 'Rectangle',
        'what': "Creates or manages a scheduled Event record (via the Mail/Event machinery) so "
                "logic runs at a future date or on a recurrence pattern, rather than inline.",
        'failures': "If scheduled logic never fires, verify the generated Event record exists, "
                    "its date/recurrence values were mapped correctly, and the platform "
                    "scheduler agent is running.",
    },
    '19': {
        'name': 'Continue Task (loop control)',
        'shape': 'Small circle (unlabeled in exports)',
        'what': "Inside a loop/iterator body, immediately jumps to the next iteration, "
                "skipping the remaining tasks of the current pass. Exports carry no TaskLabel "
                "for it, so it appears unlabeled in raw XML.",
        'failures': "Not a failure point itself; if iterations seem skipped, check the switch "
                    "conditions that route execution into the Continue.",
    },
    '20': {
        'name': 'Loop Task',
        'shape': 'Rectangle with loop-back edge',
        'what': "Repeats a block of tasks while its condition holds, creating a deliberate "
                "cycle in the workflow graph back to the loop start.",
        'failures': "Infinite loops (condition never turns false) show up as runaway WFIIDs "
                    "in the server log; verify the loop's exit condition mutates on each pass.",
    },
    '21': {
        'name': 'Break Task (loop control)',
        'shape': 'Small circle',
        'what': "Immediately exits the enclosing loop/iterator, resuming execution at the "
                "loop's exit branch.",
        'failures': "Not a failure point itself; premature loop exits usually trace back to "
                    "the switch condition routing into the Break.",
    },
    '24': {
        'name': 'Iter Task (record iterator)',
        'shape': 'Rectangle with loop-back edge',
        'what': "Iterates over a record set (typically a prior Retrieve/Query result), running "
                "its body branch once per record. Like a Switch, it encodes its two branches in "
                "TargetAssociation: the FIRST id is the LOOP BODY, the SECOND is the EXIT taken "
                "when records are exhausted.",
        'failures': "Zero iterations means the input record set was empty -- check the feeding "
                    "Retrieve/Query task. Runaway iteration means the body re-queries and "
                    "regrows the set it iterates.",
    },
    '26': {
        'name': 'Save Permanent Record Task',
        'shape': 'Rectangle',
        'what': "Persists an in-memory (temp) record permanently to the database, making it a "
                "real record with its own SPEC_ID and lifecycle.",
        'failures': "Failures usually mean required fields were unmapped or a duplicate/"
                    "validation rule on the BO rejected the save.",
    },
    '30': {
        'name': 'Associate Records Task',
        'shape': 'Rectangle',
        'what': "Creates a named association link between two record sets (e.g. linking a "
                "building to its status classification) in IBS_SPEC_ASSIGNMENTS.",
        'failures': "If downstream Retrieves find nothing, verify this task ran and the "
                    "association string matches exactly what the Retrieve traverses.",
    },
    '31': {
        'name': 'Trigger Action Task',
        'shape': 'Rectangle',
        'what': "Fires a state-transition action (its EventName, e.g. 'triCreateDraft') on the "
                "target records, driving them through their BO state machine and firing any "
                "workflows bound to that action.",
        'failures': "If the record does not transition, verify the action name is valid for "
                    "the record's CURRENT state -- firing an action unavailable in that state "
                    "is silently ignored or errors.",
    },
    '32': {
        'name': 'Delete Reference Task',
        'shape': 'Rectangle',
        'what': "Removes an association link (or reference) between records without deleting "
                "the records themselves.",
        'failures': "No-ops usually mean the association name/direction did not match an "
                    "existing link.",
    },
    '33': {
        'name': 'Add Child Task',
        'shape': 'Rectangle',
        'what': "Adds a record as a child of another in a hierarchy (e.g. placing a space "
                "under a floor), maintaining the platform's hierarchical path.",
        'failures': "Failures typically mean the parent record was missing from context or "
                    "the hierarchy module rejected the placement.",
    },
    '34': {
        'name': 'Set Project Task',
        'shape': 'Rectangle',
        'what': "Switches the workflow's execution context into (or out of) a specific "
                "Project, so subsequent tasks operate on project-scoped data.",
        'failures': "Downstream tasks reading the wrong data set usually indicates the "
                    "project context was not set or cleared as expected.",
    },
    '35': {
        'name': 'Attach Format File Task',
        'shape': 'Rectangle',
        'what': "Attaches a format/template file (e.g. a document template) to the context "
                "record for later population.",
        'failures': "Verify the format file exists in the Document Manager path the task "
                    "references.",
    },
    '36': {
        'name': 'Populate File Task',
        'shape': 'Rectangle',
        'what': "Fills a previously attached template file with live record data (mail-merge "
                "style document generation).",
        'failures': "Blank or partial documents mean the template's merge fields no longer "
                    "match the BO's field names.",
    },
    '37': {
        'name': 'Distill File Task',
        'shape': 'Rectangle',
        'what': "Converts a populated document into its final distributable form (typically "
                "rendering to PDF).",
        'failures': "Check the server-side document conversion service if output files are "
                    "missing or corrupt.",
    },
    '38': {
        'name': 'Call Workflow Task',
        'shape': 'Rectangle',
        'what': "Synchronously invokes another workflow as a sub-routine, passing the current "
                "record context (via its TaskRef module/object binding), then resumes here "
                "when the sub-workflow completes.",
        'failures': "Failures inside the callee surface under a DIFFERENT workflow name in the "
                    "log but the same call chain; trace the callee's WFIID. Also verify the "
                    "called workflow is Active in the target environment.",
    },
    '40': {
        'name': 'Variable Definition Task',
        'shape': 'Rectangle',
        'what': "Declares a named workflow variable (with a type and optional initial value) "
                "that later tasks can read or assign.",
        'failures': "Referencing a variable before its definition task has executed yields "
                    "null -- a classic NullPointerException source in switches.",
    },
    '41': {
        'name': 'Variable Assignment Task',
        'shape': 'Rectangle',
        'what': "Assigns a new value (constant, field value, or expression result) to a "
                "previously defined workflow variable.",
        'failures': "Type mismatches between the assigned value and the variable's declared "
                    "type, or assigning from an empty source field.",
    },
    '43': {
        'name': 'Fact Condition Task (rules engine)',
        'shape': 'Pentagon',
        'what': "Evaluates a fact/rule condition against the rules engine (similar in spirit "
                "to a Switch but driven by fact definitions rather than field expressions).",
        'failures': "Verify the referenced fact definitions still exist and their inputs are "
                    "populated on the context record.",
    },
}

OPERATOR_GLOSSARY = {
    '10': 'Equals',
    '11': 'Does Not Equal',
    '12': 'Is Less Than',
    '13': 'Is Less Than or Equal To',
    '14': 'Is Greater Than',
    '15': 'Is Greater Than or Equal To',
    '16': 'Contains',
    '17': 'Does Not Contain',
    '18': 'Starts With',
    '19': 'Ends With',
    '20': 'Is Empty',
    '21': 'Is Not Empty',
    '22': 'Is In',
    '23': 'Is Not In',
}

CONCEPT_GLOSSARY = {
    'bo': (
        "Business Object (BO)",
        "The data blueprint for a type of record in TRIRIGA (e.g. triBuilding, triFedStatus). "
        "A BO defines the fields, sections, and state transitions its records have. Workflows "
        "are bound to a BO and operate on its records; in the database each BO's data lives in "
        "a T_<BONAME> table keyed by SPEC_ID."
    ),
    'module': (
        "Module",
        "The top-level grouping that owns Business Objects (e.g. Location owns triBuilding and "
        "triLand). Workflows, queries, and associations are all scoped by Module::BO."
    ),
    'association': (
        "Association",
        "A named, directional link between two records (e.g. 'Is Classified By'). Retrieve "
        "tasks traverse associations to move from a 'From' record to related records. In the "
        "database, associations live in IBS_SPEC_ASSIGNMENTS."
    ),
    'spec_id': (
        "SPEC_ID",
        "The unique database identifier of a single record instance. Every record row in a "
        "T_<BO> table and in IBS_SPEC is keyed by SPEC_ID; the engine uses it to fetch live "
        "payload data for a task."
    ),
    'wfiid': (
        "WFIID (Workflow Instance ID)",
        "The unique id of one execution of a workflow. Every server-log line for a given run "
        "carries the same WFIID, which is how the live-trace commands isolate a single "
        "chronological execution from a busy log."
    ),
    'om package': (
        "OM Package (Object Migration Package)",
        "A zip export of TRIRIGA objects (workflows, queries, BOs, forms) used to migrate "
        "content between environments. This engine parses the workflow and query XML inside "
        "an OM Package to build its diagnostic graph."
    ),
    'omp': (
        "OM Package (Object Migration Package)",
        "A zip export of TRIRIGA objects (workflows, queries, BOs, forms) used to migrate "
        "content between environments. This engine parses the workflow and query XML inside "
        "an OM Package to build its diagnostic graph."
    ),
    'smart section': (
        "Smart Section",
        "A form section backed by an association rather than flat fields: it displays records "
        "linked to the current record (e.g. a building's linked RPIM asset). Workflow tasks "
        "read from and write to smart sections via their association names."
    ),
    'switch': (
        "Switch Task (Type 14)",
        "See 'Type 14': the decision gate that evaluates an expression and routes execution "
        "down its TRUE or FALSE branch."
    ),
    'expression': (
        "Expression",
        "The formula a Switch task evaluates, written over parameters bound to record fields "
        "(e.g. p0 == \"DISP\" where p0 is a field like triRPAOperationalStatusCodeCL)."
    ),
    'trigger': (
        "Trigger / Event",
        "The condition that launches a workflow: a record event (Pre-Create, OnChange, "
        "state-transition action) on the workflow's bound Business Object."
    ),
    'guimapping': (
        "GUI Mapping",
        "An instruction inside a Modify Metadata task describing one UI change: which "
        "Tab/Section/Field to target and which property (Visible, Read-Only, Required) to set."
    ),
    'variable': (
        "Workflow Variable",
        "A named value scoped to one workflow execution: declared by a Variable Definition "
        "task (Type 40), written by Variable Assignment tasks (Type 41), and readable in "
        "switch expressions and mappings. Referencing one before its definition runs yields null."
    ),
    'loop': (
        "Loop / Iteration",
        "Repetition constructs in TRIRIGA workflows: a Loop task (Type 20) repeats while a "
        "condition holds, an Iter task (Type 24) runs its body once per record in a record "
        "set, and Break (21) / Continue (19) tasks exit or short-circuit the current pass. "
        "These create legitimate cycles in the workflow graph."
    ),
    'iteration': (
        "Loop / Iteration",
        "Repetition constructs in TRIRIGA workflows: a Loop task (Type 20) repeats while a "
        "condition holds, an Iter task (Type 24) runs its body once per record in a record "
        "set, and Break (21) / Continue (19) tasks exit or short-circuit the current pass. "
        "These create legitimate cycles in the workflow graph."
    ),
    'trigger action': (
        "Trigger Action",
        "A Trigger Action task (Type 31) fires a state-transition action (e.g. 'triCreateDraft') "
        "on target records, moving them through their BO state machine and cascading any "
        "workflows bound to that action."
    ),
    'fact': (
        "Fact / Rule Condition",
        "A Fact Condition task (Type 43) evaluates a rules-engine fact definition against the "
        "context record -- rule-driven routing, as opposed to a Switch's field expression."
    ),
}


def type_display_name(type_code):
    """Short display name for a task type code; single source of truth for all UI maps."""
    code = str(type_code).strip()
    entry = TASK_TYPE_GLOSSARY.get(code)
    if entry:
        return entry['name']
    if code in ('11', '12'):
        return 'Junction'
    if code.lower() in ('1', 'trigger', 'start'):
        return 'Start Task'
    return f"Type {code}"


def _type_usage_in_graphs(graphs, type_code, get_type_str, limit=8):
    """Scan loaded graphs for tasks of the given type; return usage lines."""
    lines = []
    for wf_name, graph in graphs.items():
        names = []
        for _node, data in graph.nodes(data=True):
            if get_type_str(data) == str(type_code):
                names.append(data.get('name', 'Unnamed'))
        if names:
            sample = ", ".join(f"'{n}'" for n in names[:limit])
            more = f" (+{len(names) - limit} more)" if len(names) > limit else ""
            lines.append(f"[{wf_name}] {len(names)} task(s) of this type: {sample}{more}")
    return lines


def explain_task_type(type_code, graphs=None, get_type_str=None):
    """Full glossary answer for a task type code, with live usage if graphs given."""
    code = str(type_code).strip()
    entry = TASK_TYPE_GLOSSARY.get(code)
    if not entry:
        known = ", ".join(sorted(TASK_TYPE_GLOSSARY.keys(), key=int))
        return (f"Type {code} is not in my TRIRIGA task-type glossary. "
                f"Known type codes: {known}.")

    out = [
        f"Type {code} = {entry['name']}",
        f"  Map shape: {entry['shape']}",
        f"  What it does: {entry['what']}",
        f"  Common failure modes: {entry['failures']}",
    ]

    if graphs and get_type_str:
        usage = _type_usage_in_graphs(graphs, code, get_type_str)
        if usage:
            out.append("")
            out.append("  In your loaded workflow(s):")
            out.extend([f"    {u}" for u in usage])
        else:
            out.append("")
            out.append("  This task type does not appear in the currently loaded workflow(s).")
    return "\n".join(out)


def explain_operator(op_code):
    """Glossary answer for a filter/comparison operator code."""
    code = str(op_code).strip()
    name = OPERATOR_GLOSSARY.get(code)
    if not name:
        listing = ", ".join(f"{k}={v}" for k, v in sorted(OPERATOR_GLOSSARY.items(), key=lambda kv: int(kv[0])))
        return (f"Operator {code} is not in my operator glossary. Known operators: {listing}.")
    return (f"Operator {code} = '{name}'. It is used in Retrieve/Switch filter criteria to "
            f"compare the Left field against the Right value/field.")


def explain_concept(term):
    """Glossary answer for a TRIRIGA platform concept; None if unknown."""
    key = term.strip().lower()
    entry = CONCEPT_GLOSSARY.get(key)
    if not entry:
        # Tolerate simple variations like trailing 's' or embedded underscores.
        normalized = key.rstrip('s').replace('_', ' ')
        entry = CONCEPT_GLOSSARY.get(normalized)
    if not entry:
        return None
    title, body = entry
    return f"{title}:\n  {body}"


def translate_operator(op_code):
    """Compatibility helper mirroring the router's historical _translate_operator output."""
    if not op_code:
        return "Equals"
    if isinstance(op_code, list):
        op_code = op_code[0] if op_code else '10'
    code = str(op_code).strip()
    return OPERATOR_GLOSSARY.get(code, f"Unknown Operator ({code})")
