"""Structured intent registry for the interactive CLI.

Replaces the router's bare ordered-regex list with declarative entries carrying
explicit priority (fixing pattern shadowing, e.g. glossary 'what is type 14'
must outrank the broad explain-task 'what is ...'), help text, and example
phrasings. The same registry powers:
  - dispatch (priority-ordered matching),
  - the auto-generated 'help' response grouped by category,
  - the did-you-mean fallback when nothing matches.
"""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Intent:
    id: str
    category: str
    handler: str                      # name of the handler method on the router
    patterns: List[str]               # regex alternatives (any match dispatches)
    help_line: str
    examples: List[str]
    priority: int = 100               # lower = matched earlier
    keywords: List[str] = field(default_factory=list)  # extra terms for did-you-mean
    compiled: List = field(default_factory=list)

    def compile(self):
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.patterns]
        return self


def build_registry():
    """Return the compiled intent list, sorted by priority (stable)."""
    intents = [
        # ---------- Meta / discoverability ----------
        Intent(
            id='help', category='Getting Started', handler='_cmd_help', priority=5,
            patterns=[r"^\s*help\s*$", r"what can i ask", r"what can you do",
                      r"list (?:the )?commands", r"show (?:me )?(?:the )?commands", r"how do i use"],
            help_line="Show every question category with examples.",
            examples=["help", "what can I ask?"],
            keywords=['help', 'commands', 'usage'],
        ),

        # ---------- Context management ----------
        Intent(
            id='set_context', category='Workflow Context', handler='_cmd_set_context', priority=10,
            patterns=[r"(?:use|switch to|select|set(?: the)? (?:context|workflow) to?)\s+(?:the\s+)?workflow\s+(.+)",
                      r"(?:use|switch to|select)\s+(tri\w+)"],
            help_line="Point all questions at a specific loaded workflow.",
            examples=["use workflow triBuilding", "switch to triLand"],
            keywords=['use', 'switch', 'select', 'context', 'workflow'],
        ),
        Intent(
            id='show_context', category='Workflow Context', handler='_cmd_show_context', priority=11,
            patterns=[r"(?:which|what) workflow(?:s)? (?:am i|are loaded|is (?:active|selected|current))",
                      r"current (?:workflow|context)", r"^\s*list workflows\s*$", r"show (?:loaded )?workflows"],
            help_line="Show the loaded workflows and which one is active.",
            examples=["which workflow am I on?", "list workflows"],
            keywords=['current', 'loaded', 'workflows', 'context'],
        ),

        Intent(
            id='load_workflow_file', category='Workflow Context', handler='_cmd_load_workflow_file', priority=12,
            patterns=[r"load (?:workflow |wf )?(?:xml )?file\s+['\"]?(.+?)['\"]?\s*$",
                      r"load workflow\s+['\"]?(\S+\.(?:xml|txt))['\"]?\s*$"],
            help_line="Load a bare workflow XML export (outside an OM Package) for analysis.",
            examples=["load workflow file wf_all_tasks.txt"],
            keywords=['load', 'file', 'xml', 'import'],
        ),

        # ---------- Trigger / header metadata (must outrank glossary 'trigger' concept) ----------
        Intent(
            id='trigger_info', category='Workflow Understanding', handler='_cmd_trigger_info', priority=19,
            patterns=[r"what (?:triggers|fires|starts|launches|kicks off)\s+(?:this|the|it)",
                      r"when does (?:this|the|it)(?: workflow)? (?:run|fire|execute|start)",
                      r"what event (?:fires|triggers|starts|launches)",
                      r"what is the trigger\b", r"trigger (?:info|profile|event)\b",
                      r"who (?:last )?(?:updated|modified|edited) (?:this|the) workflow",
                      r"(?:which|what) (?:module|bo|business object) is (?:this|the|it)(?: workflow)? (?:on|bound to|attached to|for)"],
            help_line="Show what fires the workflow: trigger event, Module::BO, version label, last editor.",
            examples=["what triggers this workflow?", "when does it run?"],
            keywords=['trigger', 'fires', 'event', 'runs', 'module', 'updated by'],
        ),

        # ---------- Glossary (must outrank broad explain-task) ----------
        Intent(
            id='glossary_type', category='TRIRIGA Knowledge', handler='_cmd_glossary_type', priority=20,
            patterns=[r"(?:what\s+(?:is|does|do)|meaning of|define|explain)\s+(?:a\s+|the\s+)?type\s*[- ]?(\d+)",
                      r"type\s*[- ]?(\d+)\s+mean"],
            help_line="Define a task type code and show where it appears in your workflow.",
            examples=["what is Type 14?", "what does Type 23 mean?"],
            keywords=['type', 'mean', 'definition', 'task type'],
        ),
        Intent(
            id='glossary_operator', category='TRIRIGA Knowledge', handler='_cmd_glossary_operator', priority=21,
            patterns=[r"(?:what\s+(?:is|does|do)|meaning of|define|explain)\s+(?:an?\s+|the\s+)?operator\s*[- ]?(\d+)",
                      r"operator\s*[- ]?(\d+)\s+mean"],
            help_line="Define a filter/comparison operator code (10=Equals, 16=Contains, ...).",
            examples=["what does operator 16 mean?"],
            keywords=['operator', 'comparison', 'filter code'],
        ),
        Intent(
            id='glossary_concept', category='TRIRIGA Knowledge', handler='_cmd_glossary_concept', priority=22,
            patterns=[r"(?:what\s+(?:is|are)|define|meaning of)\s+(?:a\s+|an\s+|the\s+)?"
                      r"(business object|bo|module|association|spec[_ ]?id|wfiid|om package|omp|"
                      r"smart section|expression|trigger action|trigger|gui ?mapping|switch|"
                      r"variable|loop|iteration|fact)\b(?!\s*\d)"],
            help_line="Define a TRIRIGA concept (BO, association, variable, loop, WFIID, OM Package, ...).",
            examples=["what is a BO?", "what is a WFIID?"],
            keywords=['concept', 'definition', 'association', 'spec id', 'module'],
        ),

        # ---------- Workflow comparison (must outrank relation's 'compared to') ----------
        Intent(
            id='compare_workflows', category='Workflow Understanding', handler='_cmd_compare_workflows', priority=29,
            patterns=[r"compare (?:the )?workflows?\b", r"compare\s+.*\bworkflows?\b",
                      r"difference between\s+.+\s+and\s+.+", r"how (?:do|does)\s+.+\s+differ"],
            help_line="Structural diff of two loaded workflows: triggers, task counts by type, fields modified.",
            examples=["compare workflows", "what is the difference between triBuilding and triLand?"],
            keywords=['compare', 'difference', 'diff', 'versus'],
        ),

        # ---------- Relationships (must outrank broad explain-task) ----------
        Intent(
            id='relation', category='Task Relationships', handler='_cmd_relation', priority=30,
            patterns=[r"(?:have to do with|related to|relationship (?:between|of|with)|relation between|"
                      r"connected to|connection between|compared? (?:to|with))",
                      r"is\s+.+\s+(?:upstream|downstream)\s+(?:of|from)",
                      r"(?:does|can|how does)\s+.+\s+reach\s+.+"],
            help_line="Explain how two tasks relate: upstream/downstream, parallel branches, or the routes between them.",
            examples=["what does task 333395 have to do with the Start task?",
                      "is task 333449 downstream of task 333543?"],
            keywords=['relationship', 'related', 'upstream', 'downstream', 'reach', 'connected'],
        ),
        Intent(
            id='constraints', category='Task Relationships', handler='_cmd_constraints', priority=31,
            patterns=[r"what must (?:be true|happen|pass)", r"conditions?\s+.*\breach\b",
                      r"(?:required|needed|necessary)\s+to reach", r"why (?:would|does|doesn't|didn'?t)\s+.+\s+(?:run|fire|execute)",
                      r"how (?:do i|can|does execution) get to"],
            help_line="List every switch verdict that must hold for execution to reach a task.",
            examples=["what must be true to reach task 333449?",
                      "why didn't task 333454 run?"],
            keywords=['constraints', 'conditions', 'reach', 'gate', 'must be true'],
        ),

        # ---------- Inventory ----------
        Intent(
            id='list_variables', category='Workflow Inventory', handler='_cmd_list_variables', priority=36,
            patterns=[r"(?:list|show|any|what|which)\b.*\bvariables?\b",
                      r"variables? (?:used|defined|declared|assigned)"],
            help_line="List workflow variables: Definition (Type 40) and Assignment (Type 41) tasks.",
            examples=["list variables", "which tasks use variables?"],
            keywords=['variables', 'variable', 'definition', 'assignment'],
        ),
        Intent(
            id='list_loops', category='Workflow Inventory', handler='_cmd_list_loops', priority=37,
            patterns=[r"(?:list|show|any|are there|find)\b.*\bloops?\b",
                      r"does (?:this|the|it)\b.*\bloop\b", r"(?:list|show|any)\b.*\biterat"],
            help_line="Report loop constructs: Loop/Iter/Break/Continue tasks plus any cycles in the graph.",
            examples=["are there any loops?", "list loops"],
            keywords=['loops', 'loop', 'iterator', 'cycle', 'iteration'],
        ),
        Intent(
            id='task_type_index', category='Workflow Inventory', handler='_cmd_task_type_index', priority=38,
            patterns=[r"(?:list|show|what|which)\b.*\btask types\b", r"what types (?:of tasks? )?(?:exist|are there)",
                      r"task[- ]type index", r"all (?:the )?task types"],
            help_line="Full task-type index (all known type codes), marking types present in your workflows.",
            examples=["list task types", "what task types exist?"],
            keywords=['task types', 'types', 'index', 'codes'],
        ),
        Intent(
            id='list_associations', category='Workflow Inventory', handler='_cmd_list_associations', priority=39,
            patterns=[r"(?:list|show|what|which)\b.*\bassociations?\b(?!\s+mean)",
                      r"associations? (?:used|traversed|created)"],
            help_line="List every association name the workflow traverses or creates, and by which tasks.",
            examples=["what associations does it use?"],
            keywords=['associations', 'association', 'links'],
        ),
        Intent(
            id='inventory', category='Workflow Inventory', handler='_cmd_inventory', priority=40,
            patterns=[r"list (?:all |the )?(tasks?|switch(?:es)?|quer(?:y|ies)|retrieves?|end tasks?|"
                      r"modif(?:y|ies|ications?)(?: tasks?)?|creates?(?: tasks?)?)\b",
                      r"(?:show|what) (?:are )?(?:all )?(?:the )?(switch(?:es)?|quer(?:y|ies)|tasks?)\b.*(?:in|of)? ?(?:this|the)? ?workflow",
                      r"which tasks (?:modify|update|change|write)", r"what fields (?:does|do|get).*(?:touch|modif|updat|chang)",
                      r"how many (?:tasks|switches|queries)"],
            help_line="Inventory the workflow: list tasks by type, queries used, or every field it modifies.",
            examples=["list all switches", "which tasks modify the database?", "what fields does this workflow touch?"],
            keywords=['list', 'inventory', 'switches', 'queries', 'fields', 'tasks'],
        ),

        # ---------- What-If simulation (must outrank conditional_trace 55 and
        # analyze_failure 56, whose broad patterns would swallow "what if ... fails") ----------
        Intent(
            id='simulate', category='Logic Tracing', handler='_cmd_simulate', priority=45,
            # The did-query alternative excludes bare pronoun subjects ("how did it
            # execute") so live_trace keeps owning that phrasing.
            patterns=[r"\bwhat[\s-]+if\b", r"\bwhat\s+happens\s+if\b", r"\bwhat\s+would\s+happen\s+if\b",
                      r"\bsimulat\w*\b", r"\bsuppose\b", r"\bassume\b",
                      r"\b(?:did|has|have|was|were)\b\s+(?!it\b)\S.*?\s+\b(?:trigger(?:ed)?|fire(?:d)?|run|ran|execute(?:d)?|happen(?:ed)?|occur(?:red)?)\b"],
            help_line="Simulate a hypothetical data state and see the resulting execution path, or ask if a task ran.",
            examples=["what if the operational status is DISP?", "what happens if task 333433 fails?",
                      "did Modify Records trigger?"],
            keywords=['simulate', 'what if', 'what happens if', 'hypothetical', 'scenario', 'suppose', 'assume', 'did', 'trigger'],
        ),

        # ---------- Existing capabilities ----------
        Intent(
            id='visualize', category='Visualization', handler='_cmd_visualize_workflow', priority=50,
            patterns=[r"visualize|draw graph|show map|render map|generate map"],
            help_line="Generate the interactive HTML blueprint map.",
            examples=["visualize"],
            keywords=['map', 'draw', 'blueprint', 'visualize'],
        ),
        Intent(
            id='scan_log', category='Live Diagnostics', handler='_cmd_scan_log', priority=51,
            patterns=[r"why did it fail|check the log|scan log|what just failed|read log"],
            help_line="Scan the server log for errors correlated to your loaded workflow.",
            examples=["scan log", "what just failed?"],
            keywords=['log', 'error', 'failed', 'scan'],
        ),
        Intent(
            id='ad_hoc_trace', category='Live Diagnostics', handler='_cmd_ad_hoc_trace', priority=52,
            patterns=[r"another workflow|trace ad hoc|ad hoc trace|ad-hoc trace|external workflow|not in omp"],
            help_line="Trace a live execution of a workflow that is NOT in the loaded OM Package.",
            examples=["trace ad hoc live execution"],
            keywords=['ad hoc', 'external', 'trace'],
        ),
        Intent(
            id='live_trace', category='Live Diagnostics', handler='_cmd_live_trace', priority=53,
            patterns=[r"trace live|how did it execute|live execution|trace execution"],
            help_line="Chronological trace of how your OMP workflow actually routed at runtime.",
            examples=["trace live execution"],
            keywords=['trace', 'live', 'execution', 'runtime'],
        ),
        Intent(
            id='trace_path', category='Task Relationships', handler='_cmd_trace_path', priority=54,
            # Anchor to end-of-line so the lazy destination group cannot match empty.
            patterns=[r"path.*from\s+['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?\s*[?.!]?\s*$"],
            help_line="Show the transition path between two named tasks.",
            examples=["path from 'Start' to 'End'"],
            keywords=['path', 'from', 'to'],
        ),
        Intent(
            id='conditional_trace', category='Logic Tracing', handler='_cmd_conditional_trace', priority=55,
            patterns=[r"(?:what happens|trace).*(?:when|if)|(?:when|if).*(?:what happens|trace)"],
            help_line="Forward-trace what happens when a field holds a specific value.",
            examples=["what happens when triRPAOperationalStatusCodeCL is DISP?"],
            keywords=['when', 'if', 'condition', 'happens'],
        ),
        Intent(
            id='analyze_failure', category='Live Diagnostics', handler='_cmd_analyze_failure', priority=56,
            patterns=[r"\bfail\w*\b|\bfix\b|\bbroken\b"],
            help_line="Root-cause analysis of a failing task's prerequisites.",
            examples=["why is task 333377 failing?"],
            keywords=['fail', 'fix', 'broken', 'root cause'],
        ),
        Intent(
            id='find_references', category='Workflow Inventory', handler='_cmd_find_references', priority=57,
            patterns=[r"updates|modifies|uses|where is|touches"],
            help_line="Reverse-search every task that reads or writes a given field.",
            examples=["which tasks update triFedStatusCL?"],
            keywords=['updates', 'uses', 'references', 'field'],
        ),
        Intent(
            id='explain_purpose', category='Workflow Understanding', handler='_cmd_explain_purpose', priority=58,
            patterns=[r"purpose|what does this do|summary|summarize|explain this workflow|explain the workflow"],
            help_line="Auto-generated purpose summary plus an interactive walk of every logical path.",
            examples=["what is the purpose of this workflow?"],
            keywords=['purpose', 'summary', 'overview'],
        ),
        Intent(
            id='explain_task', category='Workflow Understanding', handler='_cmd_explain_task', priority=90,
            patterns=[r"explain|what happens at|tell me about|look at|what is|diagnose|check|lap data|left data|right data"],
            help_line="Deep logic analysis of one task: mechanics, filters, payload, routing.",
            examples=["explain task 333543", "tell me about the 'ACT?' task"],
            keywords=['explain', 'task', 'details', 'logic'],
        ),
        Intent(
            id='orphans', category='Workflow Inventory', handler='_cmd_find_orphans', priority=91,
            patterns=[r"orphan"],
            help_line="Find tasks with no incoming transitions.",
            examples=["are there any orphans?"],
            keywords=['orphan', 'unreachable'],
        ),
    ]
    intents.sort(key=lambda i: i.priority)
    return [i.compile() for i in intents]


def render_help(intents):
    """Auto-generate the grouped help text from the registry."""
    by_category = {}
    for intent in intents:
        by_category.setdefault(intent.category, []).append(intent)

    order = ['Getting Started', 'Workflow Context', 'Workflow Understanding', 'TRIRIGA Knowledge',
             'Task Relationships', 'Workflow Inventory', 'Logic Tracing', 'Visualization', 'Live Diagnostics']
    lines = ["Here is everything you can ask, grouped by category:"]
    for cat in order:
        if cat not in by_category:
            continue
        lines.append("")
        lines.append(f"[{cat}]")
        for intent in by_category[cat]:
            example = intent.examples[0] if intent.examples else ""
            lines.append(f"  - {intent.help_line}")
            if example:
                lines.append(f"      e.g. \"{example}\"")
    lines.append("")
    lines.append("Type 'exit' to quit.")
    return "\n".join(lines)


_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {'the', 'a', 'an', 'is', 'are', 'do', 'does', 'of', 'to', 'in', 'on', 'for',
              'i', 'me', 'my', 'this', 'that', 'it', 'and', 'or', 'be', 'was', 'what', 'how'}


def suggest(query, intents, max_suggestions=3):
    """Score keyword overlap between the query and each intent; return best examples."""
    q_words = set(_WORD_RE.findall(query.lower())) - _STOPWORDS
    scored = []
    for intent in intents:
        vocab = set()
        for kw in intent.keywords:
            vocab.update(_WORD_RE.findall(kw.lower()))
        for ex in intent.examples:
            vocab.update(_WORD_RE.findall(ex.lower()))
        vocab -= _STOPWORDS
        overlap = len(q_words & vocab)
        if overlap:
            scored.append((overlap, intent))
    scored.sort(key=lambda s: -s[0])
    suggestions = []
    for _score, intent in scored[:max_suggestions]:
        if intent.examples:
            suggestions.append(f"\"{intent.examples[0]}\" ({intent.help_line})")
    return suggestions
