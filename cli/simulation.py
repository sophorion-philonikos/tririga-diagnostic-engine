"""Zero-dependency What-If Simulation and natural-language Query layer.

No external LLMs: semantic routing is a hard-coded, in-memory rule engine.
A TRIRIGA lexicon (OOB module/BO/form synonyms, state-transition verbs and
status codes, approve/deny verdict vocabularies) expands each natural-language
clause into canonical tokens.

Two clause kinds are simulated:
  - GATE clauses force branch verdicts on Switch (Type 14) / Iter (Type 24)
    nodes; a bounded, cycle-aware traversal replays the workflow under them.
  - DATA-STATE clauses ("retrieve task X returns no records") target ANY task
    and simulate a null object token. TRIRIGA task-to-task dataflow is read
    from the parsed <TaskRef> links (FromTask = primary record context,
    FilterTask = source record token) and the starvation is propagated
    transitively to every dependent consumer, with a type-aware consequence
    per casualty (Modify fails for lack of target context, Iter loops zero
    times, Trigger Action skips, ...).
"""

import re
import difflib
from dataclasses import dataclass, field

import networkx as nx

from cli import graph_utils
from cli.knowledge import type_display_name

# ============================================================
# 1. SEMANTIC LEXICONS (hard-coded, zero-dependency)
# ============================================================

# Words asserting that a gate's condition HOLDS (branch verdict TRUE).
_TRUE_WORDS = {
    'approved', 'approve', 'approves', 'approval-granted', 'granted', 'grant', 'grants',
    'passed', 'passes', 'pass', 'passing', 'accepted', 'accepts', 'accept',
    'issued', 'issues', 'issue', 'activated', 'activates', 'activate', 'active', 'activation',
    'completed', 'completes', 'complete', 'finalized', 'finalizes', 'finalize',
    'succeeded', 'succeeds', 'succeed', 'successful', 'success',
    'valid', 'validated', 'validates', 'satisfied', 'satisfies', 'met', 'meets', 'matches',
    'matched', 'true', 'yes', 'confirmed', 'confirms', 'authorized', 'authorizes',
    'executed', 'triggered', 'fired', 'ran', 'enabled', 'exists', 'present', 'populated',
    'filled', 'signed', 'ratified', 'certified', 'commissioned', 'onboarded', 'occupied',
    'leased', 'awarded', 'funded', 'reserved', 'checked-in', 'dispatched', 'assigned',
}

# Words asserting that a gate's condition FAILS (branch verdict FALSE).
_FALSE_WORDS = {
    'denied', 'denies', 'deny', 'rejected', 'rejects', 'reject', 'rejection',
    'failed', 'fails', 'fail', 'failing', 'failure',
    'retired', 'retires', 'retire', 'revoked', 'revokes', 'revoke',
    'returned', 'returns', 'return', 'cancelled', 'canceled', 'cancels', 'cancel',
    'withdrawn', 'withdraws', 'withdraw', 'declined', 'declines', 'decline',
    'draft', 'missing', 'null', 'empty', 'blank', 'unset', 'false', 'unmet',
    'unsatisfied', 'invalid', 'disposed', 'disposal', 'inactive', 'skipped', 'skips',
    'bypassed', 'void', 'voided', 'terminated', 'terminates', 'terminate',
    'expired', 'expires', 'expire', 'overdue', 'unfunded', 'unassigned', 'vacant',
    'unoccupied', 'unsigned', 'stopped', 'halted', 'blocked', 'suspended', 'on-hold',
}

# Tokens that flip the detected verdict ("is NOT approved" => FALSE).
_NEGATORS = {'not', "n't", 'never', 'no', 'without', 'isnt', 'doesnt', 'wasnt', 'wont', 'didnt'}

# OOB TRIRIGA terminology -> canonical matching tokens. Phrases are scanned
# longest-first inside the query; every hit injects its canonical tokens into
# the clause token bag so hundreds of phrasings resolve to the same targets.
TRIRIGA_DOMAIN_LEXICON = {
    # ---- Capital Projects ----
    'capital project': ['tricapitalproject', 'triproject', 'project', 'capital'],
    'cap project': ['tricapitalproject', 'triproject', 'project', 'capital'],
    'capital program': ['tricapitalprogram', 'triprogram', 'program', 'capital'],
    'funding': ['trifunding', 'budget', 'cost', 'funding'],
    'budget': ['tribudget', 'budget', 'cost', 'funding'],
    'financial approval': ['approval', 'review', 'triapproval', 'financial', 'approve'],
    'approval': ['approval', 'review', 'triapproval', 'approve'],
    'change order': ['trichangeorder', 'change', 'order'],
    'work task': ['triworktask', 'work', 'task'],
    'schedule': ['trischedule', 'schedule', 'gantt'],
    # ---- Real Estate ----
    'real estate contract': ['trirealestatecontract', 'trilease', 'lease', 'contract', 'realestate'],
    're lease': ['trirealestatecontract', 'trilease', 'lease', 'contract', 'realestate'],
    're contract': ['trirealestatecontract', 'trilease', 'lease', 'contract', 'realestate'],
    'lease activation': ['trilease', 'lease', 'activate', 'activation', 'contract'],
    'lease abstract': ['trileaseabstract', 'lease', 'abstract'],
    'lease': ['trilease', 'lease', 'contract'],
    'owned agreement': ['triownedagreement', 'owned', 'agreement'],
    'lease clause': ['trileaseclause', 'clause', 'lease'],
    'rent payment': ['trirentpayment', 'rent', 'payment'],
    'landlord': ['trilandlord', 'landlord', 'contact'],
    # ---- Portfolio / Locations ----
    'building': ['tribuilding', 'building', 'location'],
    'land': ['triland', 'land', 'location'],
    'property': ['triproperty', 'property', 'location'],
    'floor': ['trifloor', 'floor', 'location'],
    'space': ['trispace', 'space', 'location'],
    'structure': ['tristructure', 'structure', 'location'],
    'retail location': ['triretaillocation', 'retail', 'location'],
    'real property': ['trirpimrealpropertyasset', 'rpim', 'rpa', 'realproperty', 'asset'],
    'rpim': ['trirpimrealpropertyasset', 'rpim', 'rpa', 'realproperty'],
    'rpa': ['trirpimrealpropertyasset', 'rpim', 'rpa', 'realproperty'],
    # ---- Assets / Facilities ----
    'asset': ['triasset', 'tribuildingequipment', 'trirpimrealpropertyasset', 'asset'],
    'building equipment': ['tribuildingequipment', 'equipment', 'asset'],
    'fixed asset': ['trifixedasset', 'asset', 'fixed'],
    'work order': ['triworkorder', 'work', 'order', 'maintenance'],
    'service request': ['triservicerequest', 'request', 'service', 'maintenance'],
    'preventive maintenance': ['tripm', 'preventive', 'maintenance', 'pm'],
    'inspection': ['triinspection', 'inspection', 'audit'],
    # ---- People / Organizations ----
    'people record': ['tripeople', 'people', 'person', 'employee'],
    'employee': ['tripeople', 'triemployee', 'employee', 'person'],
    'organization': ['triorganization', 'organization', 'org'],
    'contact': ['tricontact', 'contact', 'person'],
    # ---- Status / state machinery ----
    'operational status': ['trirpaoperationalstatuscodecl', 'operational', 'status', 'code'],
    'status indicator': ['statusind', 'status', 'indicator', 'ind'],
    'fed status': ['trifedstatuscl', 'fed', 'status', 'fedstatus'],
    'federal status': ['trifedstatuscl', 'fed', 'status', 'fedstatus'],
    'status classification': ['trifedstatuscl', 'tristatuscl', 'status', 'classification'],
    'status': ['tristatuscl', 'status', 'state'],
    'state transition': ['transition', 'state', 'status', 'trigger'],
    'record id': ['trirecordidsy', 'record', 'id'],
    'null check': ['null', 'empty', 'blank'],
    # ---- Workflow machinery ----
    'switch': ['switch', 'decision', 'gate', 'condition'],
    'decision gate': ['switch', 'decision', 'gate', 'condition'],
    'query task': ['query', 'filter', 'retrieve'],
    'retrieve task': ['retrieve', 'get', 'fetch'],
    'modify records': ['modify', 'records', 'update'],
    'trigger action': ['trigger', 'action', 'transition'],
}

# Natural state words -> TRIRIGA classification / list codes.
STATE_CODE_MAP = {
    'active': 'ACT', 'activated': 'ACT', 'activate': 'ACT', 'activation': 'ACT',
    'disposed': 'DISP', 'disposal': 'DISP', 'dispose': 'DISP', 'disposition': 'DISP',
    'retired': 'RET', 'retire': 'RET', 'retirement': 'RET',
    'excess': 'EXC', 'excessed': 'EXC',
    'null': 'NULL', 'empty': 'NULL', 'blank': 'NULL', 'none': 'NULL',
}

# ============================================================
# 2. QUERY PARSING
# ============================================================

_HYPOTHETICAL_RE = re.compile(
    r"(?:\bwhat[\s-]+if\b|\bwhat\s+happens\s+if\b|\bwhat\s+would\s+happen\s+if\b"
    r"|\bsimulat\w*\b|\bsuppose\b|\bassum\w*\b|\bhypothetic\w*\b|\bpretend\b)",
    re.IGNORECASE)
# Backwards-compatible alias used by did-query guard logic.
_WHAT_IF_RE = _HYPOTHETICAL_RE
_DID_QUERY_RE = re.compile(
    r"\b(?:did|has|have|was|were|is)\b\s+(.+?)\s*(?:\bget\b\s+|\bbeen\b\s+|\bever\b\s+)?"
    r"\b(?:trigger(?:ed)?|fire(?:d)?|run|ran|execute(?:d)?|happen(?:ed)?|occur(?:red)?|reached|invoked?)\b",
    re.IGNORECASE)
_VALUE_RE = re.compile(
    r"(?:([A-Za-z_][\w:]*)\s+)?(?:is set to|set to|becomes?|equals?|=|is)\s+"
    r"(?:(not|no longer)\s+)?['\"]?([A-Za-z0-9_-]{2,})['\"]?",
    re.IGNORECASE)
_CAMEL_RE = re.compile(r'[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+')
_WORD_RE = re.compile(r"[A-Za-z0-9_?']+")

# Zero-record / null-object-token phrasings. A STRONG match turns the clause
# into a DATA-STATE clause targeting any task's record output. WEAK phrasings
# ("is null/empty") are ambiguous with field null-checks on switches, so they
# only count as data-state when the clause clearly names a task.
_DATA_STATE_STRONG_RE = re.compile(
    r"(?:"
    r"do(?:es)?\s*(?:not|n't)\s+(?:retrieve|fetch|pull)(?:\s+(?:any|a))?(?:\s+(?:records?|results?|rows?|data))?"
    r"|do(?:es)?\s*(?:not|n't)\s+(?:return|find|yield|get)(?:\s+(?:any|a))?\s+(?:records?|results?|rows?|data)"
    r"|(?:retrieves?|returns?|finds?|fetches?|pulls?|yields?)\s+(?:nothing|no(?:thing)?|zero|0|empty)(?:\s+(?:records?|results?|rows?|data))?"
    r"|returns?\s+empty"
    r"|fails?\s+to\s+(?:find|retrieve|return|fetch|pull)"
    r"|com(?:es?|ing)\s+back\s+empty"
    r"|no\s+matching\s+records?"
    r"|(?:record\s*set|result\s*set)\s+(?:is|are|com(?:es?|ing)\s+back)\s+(?:null|empty|blank)"
    r"|has\s+(?:no|zero|0)\s+(?:records?|results?|rows?)"
    r")",
    re.IGNORECASE)
_DATA_STATE_WEAK_RE = re.compile(r"(?:is|are|comes?\s+back)\s+(?:null|empty|blank)\b", re.IGNORECASE)

# Generalized task execution failure / skip phrasings ("task 333433 fails").
_FAILURE_VERBS_RE = (
    r"(?:fails?|errors?|throws?\s+an?\s+error|is\s+skipped|is\s+not\s+executed"
    r"|does\s+not\s+(?:run|execute)|abort(?:s|ed)?)"
)
_TASK_FAILURE_RES = [
    re.compile(rf'\b(?:task\s+)?(\d{{5,}})\s+{_FAILURE_VERBS_RE}\b', re.I),
    re.compile(r'\bwhat\s+happens\s+(?:to|with)?\s+task\s+(\d{5,})\b', re.I),
    re.compile(
        rf'\b(?:the\s+)?(?:modify|retrieve|query|create|switch|metadata|trigger|associate|'
        rf'de-?associate|loop|iter|call|variable|get)?\s*task\s+["\']?(.+?)["\']?\s+'
        rf'{_FAILURE_VERBS_RE}\b', re.I),
    re.compile(rf'^(?:the\s+)?(.+?)\s+{_FAILURE_VERBS_RE}\s*$', re.I),
]

# Task-type words in the query -> TRIRIGA type codes, used to filter/boost
# candidate tasks during resolution ("the retrieve task X" -> Type 29).
_TYPE_HINTS = [
    (re.compile(r"\bretrieve(?:\s+records?)?\s+task\b|\bretrieve\s+task\b|\bget\s+task\b", re.I), '29'),
    (re.compile(r"\bquery\s+task\b", re.I), '22'),
    (re.compile(r"\bmodify(?:\s+records?)?\s+task\b|\bmodify\s+task\b|\bupdate\s+task\b", re.I), '28'),
    (re.compile(r"\bcreate(?:\s+records?)?\s+task\b|\bcreate\s+task\b|\btemp\s+record\s+task\b", re.I), '25'),
    (re.compile(r"\bsave\s+permanent(?:\s+record)?(?:\s+task)?\b|\bpermanent\s+record\s+task\b", re.I), '26'),
    (re.compile(r"\bswitch(?:\s+task)?\b|\bdecision\s+gate\b", re.I), '14'),
    (re.compile(r"\bmodify\s+metadata\s+task\b|\bmetadata\s+task\b", re.I), '23'),
    (re.compile(r"\btrigger\s+action(?:\s+task)?\b", re.I), '31'),
    (re.compile(r"\bassociate(?:\s+records?)?(?:\s+task)?\b|\bassociation\s+task\b", re.I), '30'),
    (re.compile(r"\bde-?associate(?:\s+task)?\b|\bdelete\s+reference(?:\s+task)?\b", re.I), '32'),
    (re.compile(r"\badd\s+child(?:\s+task)?\b", re.I), '33'),
    (re.compile(r"\biter(?:ator|ation)?\s+task\b", re.I), '24'),
    (re.compile(r"\bloop\s+task\b", re.I), '20'),
    (re.compile(r"\bcall\s+workflow\s+task\b|\bsub-?workflow\s+task\b", re.I), '38'),
    (re.compile(r"\bvariable\s+(?:definition|assignment)\s+task\b", re.I), '40'),
]

# Extract quoted task labels; supports double quotes wrapping embedded single
# quotes (Get 'Report of Excess Accepted' FedStatus) and the reverse.
_QUOTED_RE = re.compile(r'"([^"]{3,})"|\u201c([^\u201d]{3,})\u201d|\'([^\']{3,})\'')

_STOPWORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'do', 'does',
    'did', 'to', 'of', 'in', 'on', 'for', 'it', 'this', 'that', 'and', 'or', 'if',
    'what', 'when', 'get', 'gets', 'my', 'our', 'with', 'at', 'from', 'by', 'as',
    'then', 'than', 'would', 'happen', 'happens', 'please', 'can', 'you', 'we',
    'simulate', 'simulation', 'suppose', 'assume', 'assuming', 'scenario',
}


@dataclass
class Clause:
    text: str
    verdict: str = 'TRUE'          # branch verdict the user asserts
    field_hint: str = ''
    value: str = ''
    kind: str = 'gate'             # 'gate' | 'data_state' | 'task_failure'
    target_hint: str = ''          # quoted task label, if the user supplied one
    type_hint: str = ''            # TRIRIGA type code inferred from "retrieve task", etc.
    failure_mode: str = 'fail'     # 'fail' | 'skip' | 'error' for task_failure clauses


@dataclass
class SimulationRequest:
    mode: str                      # 'what_if' | 'did_query'
    raw: str
    clauses: list = field(default_factory=list)
    subject: str = ''              # did_query target phrase


def _tokenize(text):
    """Lowercased token bag with camelCase decomposition (triStatusCL -> tri/status/cl)."""
    out = set()
    for raw in _WORD_RE.findall(str(text)):
        low = raw.lower().strip("'")
        if not low or low in _STOPWORDS:
            continue
        out.add(low)
        for part in _CAMEL_RE.findall(raw):
            p = part.lower()
            if p and p not in _STOPWORDS:
                out.add(p)
    return out


def _expand_domain_tokens(text):
    """Inject canonical TRIRIGA tokens for every lexicon phrase found in the text."""
    padded = ' ' + re.sub(r'\s+', ' ', text.lower()) + ' '
    extra = set()
    for phrase in sorted(TRIRIGA_DOMAIN_LEXICON, key=len, reverse=True):
        if ' ' + phrase + ' ' in padded or padded.strip().startswith(phrase):
            extra.update(TRIRIGA_DOMAIN_LEXICON[phrase])
    return extra


def _detect_verdict(clause_text):
    """Scan clause words for verdict vocabulary; negators flip the result."""
    words = [w.lower().strip("'") for w in _WORD_RE.findall(clause_text)]
    verdict = None
    negated = False
    for w in words:
        if w in _NEGATORS:
            negated = True
        if verdict is None:
            if w in _TRUE_WORDS:
                verdict = 'TRUE'
            elif w in _FALSE_WORDS:
                verdict = 'FALSE'
    if verdict is None:
        verdict = 'TRUE'  # bare assertion ("what if status is DISP") means "condition holds"
    if negated:
        verdict = 'FALSE' if verdict == 'TRUE' else 'TRUE'
    return verdict


def _extract_value(clause_text):
    """Pull an explicit field/value assertion, normalizing through STATE_CODE_MAP.

    Returns (field_hint, value, matched_span, negated). ``matched_span`` lets
    the caller exclude the value words from verdict detection, so "status is
    null" reads as an assertion that the null-check HOLDS; ``negated`` covers
    "status is NOT null" (the assertion fails).
    """
    for m in _VALUE_RE.finditer(clause_text):
        field_hint = (m.group(1) or '').strip()
        negated = bool(m.group(2))
        value = m.group(3).strip()
        low = value.lower()
        is_state_word = low in STATE_CODE_MAP
        if not is_state_word and (low in _TRUE_WORDS or low in _FALSE_WORDS or low in _NEGATORS):
            continue  # "is denied" is a verdict, not a data value
        mapped = STATE_CODE_MAP.get(low)
        if mapped:
            return field_hint, mapped, m.group(0), negated
        if value.isupper() or low in STATE_CODE_MAP.values() or re.match(r'^[A-Z][A-Z0-9_-]+$', value):
            return field_hint, value.upper(), m.group(0), negated
    return '', '', '', False


def _detect_failure_mode(clause_text):
    """Classify how the user described the task failure."""
    low = clause_text.lower()
    if re.search(r'\b(?:skip(?:ped)?|does\s+not\s+(?:run|execute)|is\s+not\s+executed)\b', low):
        return 'skip'
    if re.search(r'\b(?:error(?:s|ed)?|throws?\s+an?\s+error)\b', low):
        return 'error'
    return 'fail'


def _parse_task_failure(part, target_hint):
    """Return (is_task_failure, resolved_target_hint, failure_mode) for a clause."""
    if _DATA_STATE_STRONG_RE.search(part) or _DATA_STATE_WEAK_RE.search(part):
        return False, target_hint, 'fail'

    for pat in _TASK_FAILURE_RES:
        m = pat.search(part)
        if not m:
            continue
        cap = (m.group(1) or '').strip()
        if cap.isdigit():
            resolved = cap
        elif cap and not target_hint:
            resolved = cap.strip('"\'')
        else:
            resolved = target_hint
        return True, resolved, _detect_failure_mode(part)

    if re.search(rf'\b{_FAILURE_VERBS_RE}\b', part, re.I):
        if target_hint or re.search(r'\btask\b', part, re.I) or re.search(r'\b\d{5,}\b', part):
            return True, target_hint, _detect_failure_mode(part)
    return False, target_hint, 'fail'


def parse_query(text):
    """Classify the question and decompose it into condition clauses."""
    raw = text.strip()

    did = _DID_QUERY_RE.search(raw)
    if did and not _WHAT_IF_RE.search(raw):
        return SimulationRequest(mode='did_query', raw=raw, subject=did.group(1).strip())

    # Strip the hypothetical trigger words and polite framing, keep the condition body.
    body = _HYPOTHETICAL_RE.sub(' ', raw)
    body = re.sub(r'^\s*(?:can|could|would|will)\s+you\s+(?:please\s+)?', ' ', body, flags=re.IGNORECASE)
    body = re.sub(r'\bplease\b', ' ', body, flags=re.IGNORECASE)
    body = re.sub(r'^\s*(?:that|the scenario where)\b', ' ', body, flags=re.IGNORECASE)
    body = re.sub(r'\s+', ' ', body).strip(' ?.!,')

    # Mask quoted task labels BEFORE clause splitting so names containing
    # commas or 'and' (e.g. "Get 'Report of Excess Accepted' FedStatus")
    # survive intact, then restore them per-clause.
    quoted_labels = []

    def _mask(m):
        label = next(g for g in m.groups() if g)
        quoted_labels.append(label)
        return f" QLBL{len(quoted_labels) - 1}TOKEN "

    masked_body = _QUOTED_RE.sub(_mask, body)

    def _unmask(text):
        for i, label in enumerate(quoted_labels):
            text = text.replace(f"QLBL{i}TOKEN", f'"{label}"')
        return re.sub(r'\s+', ' ', text).strip()

    clauses = []
    for part in re.split(r'\band\b|;|,', masked_body, flags=re.IGNORECASE):
        part = _unmask(part.strip(' ?.!,'))
        if not part:
            continue

        target_hint = ''
        q = _QUOTED_RE.search(part)
        if q:
            target_hint = next(g for g in q.groups() if g)

        type_hint = ''
        for pattern, code in _TYPE_HINTS:
            if pattern.search(part):
                type_hint = code
                break

        is_task_failure, tf_target, failure_mode = _parse_task_failure(part, target_hint)
        if is_task_failure:
            clauses.append(Clause(text=part, kind='task_failure',
                                  target_hint=tf_target, type_hint=type_hint,
                                  failure_mode=failure_mode))
            continue

        # A zero-record phrasing targets a task's DATA output, not a switch
        # verdict. Strong phrasings ("does not retrieve any records") always
        # qualify; weak ones ("is empty") only when the clause explicitly
        # names a task, since bare "status is null" belongs to the gate matcher.
        is_data_state = False
        if type_hint != '14' and not re.search(r'\bswitch\b|\bgate\b', part, re.I):
            if _DATA_STATE_STRONG_RE.search(part):
                is_data_state = True
            elif _DATA_STATE_WEAK_RE.search(part) and (target_hint or type_hint or
                                                       re.search(r'\btask\b', part, re.I)):
                is_data_state = True
        if is_data_state:
            clauses.append(Clause(text=part, kind='data_state',
                                  target_hint=target_hint, type_hint=type_hint))
            continue

        field_hint, value, value_span, value_negated = _extract_value(part)
        # Verdict words inside the value assertion (e.g. "is null") describe DATA,
        # not the gate outcome, so exclude them from verdict detection.
        if value_span:
            verdict = 'FALSE' if value_negated else 'TRUE'
        else:
            verdict = _detect_verdict(part)
        clauses.append(Clause(text=part, verdict=verdict,
                              field_hint=field_hint, value=value,
                              target_hint=target_hint, type_hint=type_hint))
    return SimulationRequest(mode='what_if', raw=raw, clauses=clauses)


# ============================================================
# 3. CLAUSE -> BRANCHING-NODE MATCHER
# ============================================================

_MATCH_THRESHOLD = 1.5


def _node_token_bag(data):
    parts = [str(data.get('name', ''))]
    for key in ('Expression', 'LFldName', 'PField', 'RFldName', 'ConstantValue',
                'RValue', 'Value', 'BO', 'BoName', 'FilterBo', 'QueryName', 'VariableName'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        parts.extend(str(v) for v in val)
    return _tokenize(' '.join(parts))


def _node_constants(data):
    consts = []
    for key in ('ConstantValue', 'RValue', 'Value'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        consts.extend(str(v).strip().upper() for v in val if str(v).strip())
    return consts


def _field_tokens(data):
    parts = []
    for key in ('LFldName', 'PField', 'RFldName'):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        parts.extend(str(v) for v in val)
    return _tokenize(' '.join(parts))


def _branching_nodes(graph):
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.get_type_str(data) in ('14', '24'):
            out.append((str(nid), data))
    return sorted(out, key=lambda x: x[0])


def match_clauses(engine, wf_name, clauses):
    """Deterministically bind each clause to Switch/Iter nodes with a forced verdict.

    Returns (matched, unmatched): matched entries are dicts
    {node_id, node_name, verdict, clause, score, reason}.
    """
    graph = engine.graphs[wf_name]
    branch_nodes = _branching_nodes(graph)
    matched, unmatched = [], []
    forced_ids = set()

    def add_match(nid, data, verdict, clause, score, reason):
        if nid in forced_ids:
            return
        forced_ids.add(nid)
        matched.append({
            'node_id': nid,
            'node_name': str(data.get('name', f'Task {nid}')),
            'verdict': verdict,
            'clause': clause.text,
            'score': round(score, 2),
            'reason': reason,
        })

    for clause in clauses:
        c_tokens = _tokenize(clause.text) | _expand_domain_tokens(clause.text)
        if clause.value:
            c_tokens.add(clause.value.lower())
        c_field_tokens = _tokenize(clause.field_hint) if clause.field_hint else set()

        # --- Value assertions: force EVERY switch comparing that constant ---
        if clause.value:
            hit_any = False
            null_tokens = {'null', 'empty', 'blank'}
            for nid, data in branch_nodes:
                consts = _node_constants(data)
                node_fields = _field_tokens(data)
                node_bag = _node_token_bag(data)
                field_related = bool((c_field_tokens or c_tokens) & node_fields)
                if clause.value != 'NULL' and clause.value in consts:
                    # Switch tests the asserted constant: the comparison holds.
                    add_match(nid, data, clause.verdict, clause, 5.0,
                              f"constant '{clause.value}' matches this gate's comparison")
                    hit_any = True
                elif clause.value == 'NULL' and (node_bag & null_tokens):
                    add_match(nid, data, clause.verdict, clause, 3.0,
                              "null-check gate over the asserted field")
                    hit_any = True
                elif field_related and consts and clause.verdict == 'TRUE':
                    # Field definitively holds another value: mutually exclusive
                    # constant comparisons (including NULL assertions) must fail.
                    add_match(nid, data, 'FALSE', clause, 2.5,
                              f"gate compares the same field to a different constant ({', '.join(consts[:3])})")
                    hit_any = True
            if hit_any:
                continue

        # --- Semantic scoring against each branching node ---
        best = None
        for nid, data in branch_nodes:
            bag = _node_token_bag(data)
            overlap = len(c_tokens & bag)
            name_ratio = difflib.SequenceMatcher(
                None, clause.text.lower(), str(data.get('name', '')).lower()).ratio()
            score = overlap + 2.0 * name_ratio
            if best is None or score > best[0]:
                best = (score, nid, data)

        if best and best[0] >= _MATCH_THRESHOLD:
            score, nid, data = best
            add_match(nid, data, clause.verdict, clause, score,
                      'semantic token/name match')
        else:
            unmatched.append(clause.text)

    return matched, unmatched


# ============================================================
# 3b. ANY-TASK RESOLVER (data-state clauses)
# ============================================================

def _visible_nodes(graph):
    out = []
    for nid, data in graph.nodes(data=True):
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        out.append((str(nid), data))
    return sorted(out, key=lambda x: x[0])


def match_task(engine, wf_name, clause):
    """Resolve a data-state clause to a single task of ANY type.

    Scoring priority: explicit task id in the clause > quoted-label similarity
    (heavily weighted) > token overlap; a type hint filters candidates when it
    leaves at least one.
    """
    graph = engine.graphs[wf_name]
    candidates = _visible_nodes(graph)

    if clause.type_hint:
        typed = [(nid, d) for nid, d in candidates
                 if graph_utils.get_type_str(d) == clause.type_hint]
        if typed:
            candidates = typed

    id_match = re.search(r'\b(\d{5,})\b', clause.text)
    if id_match and graph.has_node(id_match.group(1)):
        nid = id_match.group(1)
        return nid, graph.nodes[nid], 10.0

    best = None
    c_tokens = _tokenize(clause.text) | _expand_domain_tokens(clause.text)
    for nid, data in candidates:
        name = str(data.get('name', ''))
        score = 0.0
        if clause.target_hint:
            label_ratio = difflib.SequenceMatcher(
                None, clause.target_hint.lower(), name.lower()).ratio()
            score += 6.0 * label_ratio
            if clause.target_hint.lower() == name.lower():
                score += 4.0
        bag = _node_token_bag(data)
        score += len(c_tokens & bag)
        score += 1.5 * difflib.SequenceMatcher(None, clause.text.lower(), name.lower()).ratio()
        if best is None or score > best[2]:
            best = (nid, data, score)

    if best and best[2] >= (_MATCH_THRESHOLD + 1.0 if clause.target_hint else _MATCH_THRESHOLD):
        return best
    return None, None, 0.0


# ============================================================
# 3c. TOKEN DEPENDENCY INDEX + NULL-TOKEN PROPAGATION
# ============================================================

# How each consumer type reacts to a starved (null/empty) object token.
# fatal=True means the task cannot perform its work and is bypassed.
_TOKEN_CONSEQUENCES = {
    '28': ('fail/bypass execution because it lacks the required target record context', True),
    '25': ('produce an empty temporary record context for its own consumers', True),
    '26': ('fail/bypass execution because there is no source record to save permanently', True),
    '30': ('be unable to form the association because the record token is missing', True),
    '32': ('be unable to remove the association because the record token is missing', True),
    '33': ('be unable to add the child record because the parent token is missing', True),
    '31': ('skip the state transition because there is no record to act on', True),
    '23': ('skip its metadata changes because the target record context is empty', True),
    '29': ('retrieve against an empty source context and likely return zero records itself', True),
    '22': ('run its query over an empty source context and likely return zero records itself', True),
    '24': ('iterate zero times, so its LOOP BODY branch is never entered', True),
    '20': ('loop zero times, so its body is never entered', True),
    '14': ('evaluate its condition over a null token, so its verdict may flip to the FALSE/default branch', False),
    '38': ('invoke the sub-workflow with an empty record context', False),
    '40': ('define a workflow variable without a usable source value', False),
    '41': ('assign a null value to its workflow variable', False),
    '43': ('evaluate its fact condition over a null token', False),
    '17': ('schedule an event without a usable record context', False),
    '34': ('set the project context without a usable record token', False),
    '35': ('attach a format file without a usable record context', False),
    '36': ('populate a file without a usable record context', False),
    '37': ('distill a file without a usable record context', False),
    '39': ('invoke custom logic with an empty record context', False),
}
_DEFAULT_CONSEQUENCE = ('receive an empty object token from its source task', False)


def build_token_index(graph):
    """Map producer task id -> [(consumer id, ref kind)] from parsed TaskRefs.

    ``FromTask`` (UseType=1) is the consumer's primary record context;
    ``FilterTask`` (UseType=2) is its source/filter record token;
    ``AuxTask`` (UseType=3) is a tertiary context (e.g. Populate File).
    ``RefTaskId="0"`` is the workflow Start / trigger record and is indexed.
    """
    consumers = {}
    for nid, data in graph.nodes(data=True):
        for key, kind in (('FromTask', 'primary record context'),
                          ('FilterTask', 'source record token'),
                          ('AuxTask', 'auxiliary record context')):
            refs = data.get(key, [])
            if isinstance(refs, str):
                refs = [refs]
            for ref in refs:
                ref = str(ref)
                if ref in ('-1', ''):
                    continue
                consumers.setdefault(ref, []).append((str(nid), kind))
    return consumers


def propagate_null_token(graph, altered_ids, token_index, starve_cause='zero_records'):
    """BFS the consumer index from the altered tasks, classifying each casualty.

    ``starve_cause`` selects the narrative for why the producer's token is
    missing: ``zero_records`` (Retrieve/Query empty set) or ``task_failure``
    (Modify/Create or generic execution failure).

    Returns (impacted, impacts): ``impacted`` maps task id -> fatal flag;
    ``impacts`` is an ordered list of structured impact records with the
    context-aware narrative sentence.
    """
    cause_phrases = {
        'zero_records': 'were it to not retrieve any records',
        'task_failure': 'were it to fail or be skipped during execution',
    }
    origin_cause = cause_phrases.get(starve_cause, starve_cause)
    impacted = {}
    impacts = []
    queue = [(aid, aid) for aid in altered_ids]
    seen = set(altered_ids)

    def describe(nid):
        data = graph.nodes[nid]
        t_type = graph_utils.get_type_str(data)
        return data, t_type, type_display_name(t_type), str(data.get('name', f'Task {nid}'))

    while queue:
        producer_id, origin_id = queue.pop(0)
        for consumer_id, ref_kind in sorted(token_index.get(producer_id, [])):
            if consumer_id in seen or not graph.has_node(consumer_id):
                continue
            seen.add(consumer_id)

            _c_data, c_type, c_type_name, c_name = describe(consumer_id)
            p_data, p_type, p_type_name, p_name = describe(producer_id)
            consequence, fatal = _TOKEN_CONSEQUENCES.get(c_type, _DEFAULT_CONSEQUENCE)

            if producer_id == origin_id:
                cause = origin_cause
            else:
                cause = f"starved of records by upstream task {origin_id}"

            sentence = (
                f"The {p_type_name} (Type {p_type}) '{p_name}' (ID: {producer_id}), {cause}, "
                f"will cause the subsequent {c_type_name} (Type {c_type}) '{c_name}' "
                f"(ID: {consumer_id}) to {consequence} (it references task {producer_id} "
                f"as its {ref_kind})."
            )

            impacted[consumer_id] = fatal
            impacts.append({
                'producer_id': producer_id,
                'producer_name': p_name,
                'producer_type': p_type,
                'consumer_id': consumer_id,
                'consumer_name': c_name,
                'consumer_type': c_type,
                'ref_kind': ref_kind,
                'fatal': fatal,
                'origin_id': origin_id,
                'sentence': sentence,
            })

            # Fatal starvation propagates: a task with no record context
            # produces no token for its own downstream consumers.
            if fatal:
                queue.append((consumer_id, origin_id))

    return impacted, impacts


# ============================================================
# 3c. TASK FAILURE PROFILES (execution failure / skip)
# ============================================================

def extract_modify_ledger(data):
    """Field ledger for Modify/Create tasks from ObjMappingRecords metadata."""
    target_bo = ''
    fields = []
    sources = []
    seen = set()

    for rec in data.get('ObjMappingRecords', []) or []:
        t_bo = str(rec.get('TrgtBo') or rec.get('TrgtBoName') or '').strip()
        t_fld = str(rec.get('TrgtFld') or '').strip()
        if t_bo and not target_bo:
            target_bo = t_bo
        if t_fld and t_fld not in seen:
            seen.add(t_fld)
            fields.append(t_fld)
        src_bo = str(rec.get('SrcBo') or '').strip()
        src_fld = str(rec.get('SrcFld') or '').strip()
        if src_bo or src_fld:
            sources.append({'bo': src_bo, 'field': src_fld})

    for f in data.get('TrgtFld', []) or []:
        fld = str(f).strip()
        if fld and fld not in seen:
            seen.add(fld)
            fields.append(fld)

    return {'target_bo': target_bo, 'fields': fields, 'sources': sources}


def extract_query_ledger(data):
    """Filter/BO context for Retrieve/Query tasks."""
    filters = []
    for key in ('LFldName', 'RFldName', 'ConstantValue', 'Expression'):
        for val in data.get(key, []) or []:
            v = str(val).strip()
            if v:
                filters.append(v)
    return {
        'filter_bo': str(data.get('FilterBo') or data.get('Bo') or '').strip(),
        'filters': filters,
        'bo': str(data.get('Bo') or '').strip(),
    }


def extract_associations(data):
    """Association names referenced by Associate/De-Associate tasks."""
    names = []
    for key in ('AssociationName', 'Association'):
        for val in data.get(key, []) or []:
            v = str(val).strip()
            if v:
                names.append(v)
    for rec in data.get('TaskRefRecords', []) or []:
        v = str(rec.get('AssociationName') or '').strip()
        if v:
            names.append(v)
    return names


_PROP_TYPE_LABELS = {
    '1': 'Visible',
    '3': 'Read-Only',
    '8': 'Required',
}


def _format_prop_value(val):
    low = str(val or '').strip().lower()
    if low == 'false':
        return 'No'
    if low == 'true':
        return 'Yes'
    return str(val or '').strip()


def extract_metadata_ledger(data):
    """UI/metadata ledger for Modify Metadata (Type 23) tasks from GUIMappings."""
    tabs, sections, fields = set(), set(), set()
    property_changes = []
    bo = str(data.get('BO') or data.get('Bo') or '').strip()

    for gm in data.get('GUIMappings', []) or []:
        tab = str(gm.get('Tab') or '').strip()
        sec = str(gm.get('Section') or '').strip()
        fld = str(gm.get('Field') or '').strip()
        if tab and tab != '^^':
            tabs.add(tab)
        if sec and sec != '^^':
            sections.add(sec)
        if fld and fld != '^^':
            fields.add(fld)
        p_type = str(gm.get('PropType') or '').strip()
        p_val = str(gm.get('PropVal') or '').strip()
        prop_label = _PROP_TYPE_LABELS.get(p_type, f'Property {p_type}' if p_type else 'Property')
        property_changes.append({
            'prop_type': p_type,
            'prop_label': prop_label,
            'value': p_val,
            'tab': tab,
            'section': sec,
            'field': fld,
        })

    return {
        'bo': bo,
        'tabs': sorted(tabs),
        'sections': sorted(sections),
        'fields': sorted(fields),
        'property_changes': property_changes,
    }


def _node_read_field_text(data):
    """Concatenate read-side field metadata only (excludes TrgtFld write targets)."""
    parts = []
    for key in ('LFldName', 'PField', 'Expression', 'ConstantValue', 'SrcFld'):
        for val in data.get(key, []) or []:
            parts.append(str(val))
    for rec in data.get('ObjMappingRecords', []) or []:
        if rec.get('SrcFld'):
            parts.append(str(rec['SrcFld']))
    return ' '.join(parts)


def find_field_dependent_nodes(graph, field_names, failed_id, failed_name):
    """Informational impacts: graph-descendant nodes that READ failed Modify fields.

    Peer Modifies that only write the same TrgtFld are excluded. Results are
    never added to impacted_map — they are informational only.
    """
    if not field_names:
        return []
    failed_id = str(failed_id)
    if not graph.has_node(failed_id):
        return []
    try:
        reachable = {str(n) for n in nx.descendants(graph, failed_id)}
    except Exception:
        reachable = set()
    if not reachable:
        return []

    notes = []
    for nid in sorted(reachable):
        if not graph.has_node(nid):
            continue
        data = graph.nodes[nid]
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        blob = _node_read_field_text(data).lower()
        hits = [f for f in field_names if f and f.lower() in blob]
        if not hits:
            continue
        t_type = graph_utils.get_type_str(data)
        t_name = type_display_name(t_type)
        node_name = str(data.get('name', f'Task {nid}'))
        sentence = (
            f"{t_name} '{node_name}' ({nid}) evaluates or references field "
            f"'{hits[0]}' which would remain unmodified if task {failed_id} "
            f"('{failed_name}') fails."
        )
        notes.append({
            'producer_id': failed_id,
            'consumer_id': str(nid),
            'consumer_name': node_name,
            'consumer_type': t_type,
            'ref_kind': 'field_reference',
            'fatal': False,
            'informational': True,
            'sentence': sentence,
        })
    return notes


def analyze_task_failures(engine, wf_name, clauses):
    """Resolve task-failure clauses and apply type-specific operational profiles."""
    graph = engine.graphs[wf_name]
    failed_tasks = []
    failed_ids = []
    altered_from_failure = []
    field_impacts = []
    impacts = []
    forced_overrides = {}
    unmatched = []
    impacted_map = {}

    if not clauses:
        return {
            'failed_tasks': failed_tasks,
            'failed_ids': failed_ids,
            'altered_from_failure': altered_from_failure,
            'field_impacts': field_impacts,
            'impacts': impacts,
            'forced_overrides': forced_overrides,
            'impacted_map': impacted_map,
            'unmatched': unmatched,
        }

    token_index = build_token_index(graph)

    for clause in clauses:
        nid, data, score = match_task(engine, wf_name, clause)
        if nid is None:
            unmatched.append(clause.text)
            continue

        t_type = graph_utils.get_type_str(data)
        t_type_name = type_display_name(t_type)
        name = str(data.get('name', f'Task {nid}'))
        mode = clause.failure_mode

        if t_type == '28':
            ledger = extract_modify_ledger(data)
            fields = ledger['fields']
            bo = ledger['target_bo']
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
                'fields': fields,
                'bo': bo,
            })
            failed_ids.append(nid)
            if fields:
                field_impacts.append({'task_id': nid, 'bo': bo, 'fields': fields})
                fld_str = ', '.join(fields)
                bo_part = f" on BO '{bo}'" if bo else ''
                impacts.append({
                    'producer_id': nid,
                    'producer_name': name,
                    'producer_type': t_type,
                    'consumer_id': None,
                    'consumer_name': '',
                    'consumer_type': '',
                    'ref_kind': 'field_ledger',
                    'fatal': False,
                    'sentence': (
                        f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                        f"will result in the failure to update the target field(s) ({fld_str}){bo_part}. "
                        f"Any downstream tasks relying on this task's output object token will be affected."
                    ),
                })
            else:
                impacts.append({
                    'producer_id': nid,
                    'producer_name': name,
                    'producer_type': t_type,
                    'consumer_id': None,
                    'consumer_name': '',
                    'consumer_type': '',
                    'ref_kind': 'execution_failure',
                    'fatal': False,
                    'sentence': (
                        f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) "
                        f"would not execute successfully."
                    ),
                })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)
            impacts.extend(find_field_dependent_nodes(graph, fields, nid, name))

        elif t_type == '25':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'create_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would not create a temporary record token for downstream consumers."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type == '26':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'save_permanent_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would not persist the temporary record to a permanent record."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(
                graph, [nid], token_index, starve_cause='task_failure')
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type in ('29', '22'):
            altered_from_failure.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'clause': clause.text,
                'score': round(score, 2),
            })
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'execution_failure',
                'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"would produce no record token for downstream consumers."
                ),
            })
            imp_map, tok_impacts = propagate_null_token(graph, [nid], token_index)
            for cid, fatal in imp_map.items():
                impacted_map[cid] = impacted_map.get(cid, False) or fatal
            impacts.extend(tok_impacts)

        elif t_type == '14':
            forced_overrides[nid] = 'FALSE'
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'switch_failure',
                'fatal': False,
                'sentence': (
                    f"The Switch (Type 14) '{name}' (ID: {nid}) would fail to evaluate; "
                    f"simulation forces the FALSE/default branch."
                ),
            })

        elif t_type == '31':
            actions = data.get('Action', []) or []
            action_str = ', '.join(str(a) for a in actions[:3]) if actions else 'state transition'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'trigger_failure', 'fatal': False,
                'sentence': (
                    f"The Trigger Action (Type 31) '{name}' (ID: {nid}) would be skipped; "
                    f"action(s) not fired: {action_str}."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '30':
            assocs = extract_associations(data)
            assoc_str = ', '.join(assocs[:3]) if assocs else 'association'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'association_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"{assoc_str} not formed."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '32':
            assocs = extract_associations(data)
            assoc_str = ', '.join(assocs[:3]) if assocs else 'association'
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'association_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"{assoc_str} not removed."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type == '33':
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'add_child_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"child record would not be added."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        elif t_type in ('24', '20'):
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'loop_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) would fail; "
                    f"loop body would never be entered."
                ),
            })

        elif t_type == '23':
            ledger = extract_metadata_ledger(data)
            tabs = ledger['tabs']
            sections = ledger['sections']
            fields = ledger['fields']
            bo = ledger['bo']
            failed_tasks.append({
                'node_id': nid,
                'node_name': name,
                'node_type': t_type,
                'node_type_name': t_type_name,
                'failure_mode': mode,
                'clause': clause.text,
                'score': round(score, 2),
                'tabs': tabs,
                'sections': sections,
                'fields': fields,
                'bo': bo,
                'property_changes': ledger['property_changes'],
            })
            failed_ids.append(nid)
            field_impacts.append({
                'task_id': nid,
                'bo': bo,
                'tabs': tabs,
                'sections': sections,
                'fields': fields,
                'kind': 'metadata',
            })
            target_parts = []
            if sections:
                target_parts.append(f"section(s) ({', '.join(sections)})")
            if fields:
                target_parts.append(f"field(s) ({', '.join(fields)})")
            if tabs and not target_parts:
                target_parts.append(f"tab(s) ({', '.join(tabs)})")
            targets_str = ' and '.join(target_parts) if target_parts else 'form properties'
            bo_part = f" on BO '{bo}'" if bo else ''
            prop_labels = sorted({
                f"{pc['prop_label']}={_format_prop_value(pc['value'])}"
                for pc in ledger['property_changes']
            })
            prop_part = f" ({', '.join(prop_labels)})" if prop_labels else ''
            impacts.append({
                'producer_id': nid,
                'producer_name': name,
                'producer_type': t_type,
                'consumer_id': None,
                'consumer_name': '',
                'consumer_type': '',
                'ref_kind': 'metadata_ledger',
                'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}), were it to fail, "
                    f"will not apply UI changes to {targets_str}{bo_part}{prop_part}. "
                    f"Visibility, read-only, and required states will not propagate."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

        else:
            failed_tasks.append({
                'node_id': nid, 'node_name': name, 'node_type': t_type,
                'node_type_name': t_type_name, 'failure_mode': mode,
                'clause': clause.text, 'score': round(score, 2),
            })
            failed_ids.append(nid)
            impacts.append({
                'producer_id': nid, 'producer_name': name, 'producer_type': t_type,
                'consumer_id': None, 'consumer_name': '', 'consumer_type': '',
                'ref_kind': 'execution_failure', 'fatal': False,
                'sentence': (
                    f"The {t_type_name} (Type {t_type}) '{name}' (ID: {nid}) "
                    f"would be skipped during execution."
                ),
            })
            if token_index.get(nid):
                imp_map, tok_impacts = propagate_null_token(
                    graph, [nid], token_index, starve_cause='task_failure')
                for cid, fatal in imp_map.items():
                    impacted_map[cid] = impacted_map.get(cid, False) or fatal
                impacts.extend(tok_impacts)

    return {
        'failed_tasks': failed_tasks,
        'failed_ids': failed_ids,
        'altered_from_failure': altered_from_failure,
        'field_impacts': field_impacts,
        'impacts': impacts,
        'forced_overrides': forced_overrides,
        'impacted_map': impacted_map,
        'unmatched': unmatched,
    }


# ============================================================
# 4. DETERMINISTIC PATHFINDING (bounded, cycle-aware)
# ============================================================

def _start_nodes(graph):
    roots = [n for n in graph.nodes() if graph.in_degree(n) == 0]
    starters = [n for n in roots
                if graph_utils.get_type_str(graph.nodes[n]) in ('1', 'Trigger', 'Start')]
    return sorted(starters or roots)


def path_to_task(graph, target_id):
    """Shortest simple path from a Start node to ``target_id`` (string node ids).

    Returns a list of node ids including start and target, or [] if unreachable.
    """
    target_id = str(target_id)
    if not graph.has_node(target_id):
        return []
    best = None
    for start in _start_nodes(graph):
        start = str(start)
        if start == target_id:
            return [start]
        try:
            path = nx.shortest_path(graph, start, target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        path = [str(n) for n in path]
        if best is None or len(path) < len(best):
            best = path
    return best or []


def path_edges_from_nodes(path_ids):
    """Consecutive [from, to] pairs for a node id list."""
    return [[path_ids[i], path_ids[i + 1]] for i in range(len(path_ids) - 1)]


def _dedupe_impacts(impacts):
    """Keep each discrete impact relationship exactly once (by sentence)."""
    seen, out = set(), []
    for imp in impacts:
        key = imp.get('sentence') or (
            imp.get('producer_id'), imp.get('consumer_id'), imp.get('ref_kind'))
        if key in seen:
            continue
        seen.add(key)
        out.append(imp)
    return out


def _task_label(type_name, t_type, name, tid):
    if not type_name:
        type_name = type_display_name(t_type) if t_type else 'Task'
    if t_type:
        return f"{type_name} (Type {t_type}) '{name}' (ID: {tid})"
    return f"{type_name} '{name}' (ID: {tid})"


def build_impact_tree(impacts, root_ids, failed_tasks=None, altered_tasks=None):
    """Nest flat impacts by producer→consumer under altered/failed root ids.

    Returns a list of tree nodes:
      {task_id, task_name, task_type, task_type_name, label, badge, sentence,
       ref_kind, fatal, informational, direct_count, nested_count, children}
    """
    failed_tasks = failed_tasks or []
    altered_tasks = altered_tasks or []
    meta = {}

    for ft in failed_tasks:
        tid = str(ft['node_id'])
        meta[tid] = {
            'task_name': ft.get('node_name', f'Task {tid}'),
            'task_type': ft.get('node_type', ''),
            'task_type_name': ft.get('node_type_name', ''),
            'badge': 'failed',
        }
    for a in altered_tasks:
        tid = str(a['node_id'])
        if tid not in meta:
            meta[tid] = {
                'task_name': a.get('node_name', f'Task {tid}'),
                'task_type': a.get('node_type', ''),
                'task_type_name': a.get('node_type_name', ''),
                'badge': 'altered',
            }

    for imp in impacts:
        for id_key, name_key, type_key in (
            ('producer_id', 'producer_name', 'producer_type'),
            ('consumer_id', 'consumer_name', 'consumer_type'),
        ):
            tid = imp.get(id_key)
            if not tid:
                continue
            tid = str(tid)
            if tid in meta:
                continue
            t_type = str(imp.get(type_key) or '')
            meta[tid] = {
                'task_name': imp.get(name_key) or f'Task {tid}',
                'task_type': t_type,
                'task_type_name': type_display_name(t_type) if t_type else 'Task',
                'badge': 'broken',
            }

    children_map = {}
    root_sentences = {}
    for imp in impacts:
        pid = str(imp.get('producer_id') or '')
        if not pid:
            continue
        cid = imp.get('consumer_id')
        if cid is None or cid == '':
            root_sentences.setdefault(pid, imp)
            continue
        children_map.setdefault(pid, []).append(imp)

    def _count_descendants(node):
        total = 0
        for child in node.get('children') or []:
            total += 1 + _count_descendants(child)
        return total

    def _make_node(task_id, edge_imp=None, depth=0):
        tid = str(task_id)
        m = meta.get(tid, {})
        if edge_imp and depth > 0:
            t_type = str(edge_imp.get('consumer_type') or m.get('task_type') or '')
            name = edge_imp.get('consumer_name') or m.get('task_name') or f'Task {tid}'
        else:
            t_type = str(m.get('task_type') or '')
            name = m.get('task_name') or f'Task {tid}'
        type_name = m.get('task_type_name') or (type_display_name(t_type) if t_type else 'Task')

        if depth == 0:
            badge = m.get('badge', 'info')
        elif (edge_imp or {}).get('informational'):
            badge = 'info'
        else:
            badge = 'broken'

        node = {
            'task_id': tid,
            'task_name': name,
            'task_type': t_type,
            'task_type_name': type_name,
            'label': _task_label(type_name, t_type, name, tid),
            'badge': badge,
            'sentence': '',
            'ref_kind': (edge_imp or {}).get('ref_kind') or '',
            'fatal': (edge_imp or {}).get('fatal'),
            'informational': (edge_imp or {}).get('informational'),
            'children': [],
        }
        if depth == 0 and tid in root_sentences:
            rs = root_sentences[tid]
            node['sentence'] = rs.get('sentence') or ''
            node['ref_kind'] = rs.get('ref_kind') or node['ref_kind']
            node['informational'] = rs.get('informational')
        elif edge_imp:
            node['sentence'] = edge_imp.get('sentence') or ''

        for child_imp in children_map.get(tid, []):
            child_id = str(child_imp['consumer_id'])
            node['children'].append(_make_node(child_id, child_imp, depth + 1))

        node['direct_count'] = len(node['children'])
        node['nested_count'] = _count_descendants(node)
        return node

    roots = []
    seen_roots = set()
    for rid in root_ids:
        rid = str(rid)
        if not rid or rid in seen_roots:
            continue
        seen_roots.add(rid)
        roots.append(_make_node(rid, None, 0))

    reachable = set()

    def _collect(node):
        reachable.add(node['task_id'])
        for child in node.get('children') or []:
            _collect(child)

    for root in roots:
        _collect(root)

    for pid in sorted(children_map.keys()):
        if pid not in reachable and pid not in seen_roots:
            seen_roots.add(pid)
            roots.append(_make_node(pid, None, 0))

    return roots


def force_verdicts_for_path(engine, wf_name, path_ids):
    """Derive Switch/Iter forced verdicts so ``simulate`` follows ``path_ids``.

    For each branching node on the path, pick the branch label whose resolved
    visible target continues along the path. Returns node_id -> verdict map.
    """
    graph = engine.graphs[wf_name]
    path_set = {str(n) for n in path_ids}
    path_list = [str(n) for n in path_ids]
    forced = {}

    for i, nid in enumerate(path_list):
        if not graph.has_node(nid):
            continue
        data = graph.nodes[nid]
        t_type = graph_utils.get_type_str(data)
        if t_type not in ('14', '24'):
            continue
        # Prefer the next path node after this gate (skipping invisible hops).
        remaining = set(path_list[i + 1:])
        branch_map = engine.get_branch_map(data)
        chosen_label = None
        for raw_target, label in branch_map.items():
            visibles = graph_utils.resolve_to_visible(graph, raw_target)
            if any(str(v) in remaining or str(v) in path_set for v in visibles):
                # Prefer a visible successor that is the immediate next on path.
                if any(str(v) in remaining for v in visibles):
                    chosen_label = label
                    break
                if chosen_label is None:
                    chosen_label = label
        if chosen_label is None:
            continue
        if t_type == '14':
            forced[nid] = chosen_label if chosen_label in ('TRUE', 'FALSE') else chosen_label
        else:
            # Iter: TRUE means LOOP BODY, FALSE/other means EXIT
            forced[nid] = 'TRUE' if chosen_label == 'LOOP BODY' else 'FALSE'
    return forced


def simulate(engine, wf_name, forced):
    """Replay the workflow under forced branch verdicts.

    ``forced`` maps node_id -> 'TRUE'/'FALSE'. Switches not forced follow the
    FALSE/default spine; Iter tasks take LOOP BODY when forced TRUE, otherwise
    EXIT. Traversal is a worklist walk over VISIBLE nodes only (junctions are
    resolved through), guarded by a traversed-edge set so cycles terminate.

    Returns dict(path_node_ids, path_edges, decisions, bypassed).
    """
    graph = engine.graphs[wf_name]
    starts = _start_nodes(graph)
    if not starts:
        return {'path_node_ids': [], 'path_edges': [], 'decisions': [], 'bypassed': []}

    path_nodes, path_edges, decisions = [], [], []
    seen_nodes, seen_edges = set(), set()

    # Resolve possibly-invisible start to the first visible node(s).
    queue = []
    for s in starts:
        for vid in ([s] if not graph_utils.is_invisible(graph.nodes[s])
                    else graph_utils.resolve_to_visible(graph, s)):
            if vid not in seen_nodes:
                seen_nodes.add(vid)
                queue.append(vid)

    while queue:
        nid = queue.pop(0)
        data = graph.nodes[nid]
        path_nodes.append(nid)
        t_type = graph_utils.get_type_str(data)
        name = str(data.get('name', f'Task {nid}'))

        if t_type in ('14', '24'):
            branch_map = engine.get_branch_map(data)  # raw target id -> label
            if t_type == '14':
                desired = forced.get(nid, 'FALSE')
                origin = 'forced' if nid in forced else 'default'
            else:
                desired = 'LOOP BODY' if forced.get(nid) == 'TRUE' else 'EXIT'
                origin = 'forced' if nid in forced else 'default'

            chosen_raw = None
            for raw_target, label in branch_map.items():
                if label == desired:
                    chosen_raw = raw_target
                    break
            if chosen_raw is None and branch_map:
                chosen_raw = sorted(branch_map.keys())[0]
                desired = branch_map[chosen_raw]

            gate = 'Switch' if t_type == '14' else 'Iter'
            decisions.append(f"{gate} '{name}' ({nid}): {origin} {desired}")

            targets = graph_utils.resolve_to_visible(graph, chosen_raw) if chosen_raw else []
        else:
            targets = sorted(str(t) for t in graph_utils.visible_successors(graph, nid))

        for target in targets:
            edge = (nid, target)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            path_edges.append([nid, target])
            if target not in seen_nodes:
                seen_nodes.add(target)
                queue.append(target)

    visible_ids = {str(n) for n, d in graph.nodes(data=True)
                   if not (graph_utils.is_invisible(d) and graph.out_degree(n) > 0)}
    bypassed = sorted(
        (str(graph.nodes[n].get('name', f'Task {n}')) for n in visible_ids - set(path_nodes)),
    )

    return {
        'path_node_ids': path_nodes,
        'path_edges': path_edges,
        'decisions': decisions,
        'bypassed': bypassed,
    }


# ============================================================
# 5. "DID X TRIGGER?" QUERY ANSWERER
# ============================================================

def answer_did_query(engine, wf_name, subject, trace_ids):
    """Answer 'did <subject> trigger?' against a live/simulated trace."""
    graph = engine.graphs[wf_name]
    s_tokens = _tokenize(subject) | _expand_domain_tokens(subject)

    best = None
    for nid, data in sorted(graph.nodes(data=True), key=lambda x: str(x[0])):
        if graph_utils.is_invisible(data) and graph.out_degree(nid) > 0:
            continue
        bag = _node_token_bag(data)
        overlap = len(s_tokens & bag)
        ratio = difflib.SequenceMatcher(
            None, subject.lower(), str(data.get('name', '')).lower()).ratio()
        score = overlap + 2.0 * ratio
        if best is None or score > best[0]:
            best = (score, str(nid), data)

    # The workflow itself may be the subject ("did the RE lease activation trigger?").
    wf_ratio = difflib.SequenceMatcher(None, subject.lower(), wf_name.lower()).ratio()
    wf_overlap = len(s_tokens & _tokenize(wf_name))

    if (best is None or best[0] < _MATCH_THRESHOLD) and (wf_overlap + 2.0 * wf_ratio) < _MATCH_THRESHOLD:
        return {
            'mode': 'did_query',
            'answer': f"I could not confidently map '{subject}' to a task in '{wf_name}'.",
            'evidence': "Try naming the task as it appears on the map, e.g. 'did Modify Records trigger?'.",
            'node_id': None,
            'executed': None,
        }

    if not trace_ids:
        return {
            'mode': 'did_query',
            'answer': "No live trace is loaded, so runtime execution cannot be confirmed.",
            'evidence': "Upload/scan a server log (or run 'trace live execution') first, then ask again.",
            'node_id': best[1] if best else None,
            'executed': None,
        }

    trace_set = {str(t) for t in trace_ids}

    if best and best[0] >= _MATCH_THRESHOLD and (wf_overlap + 2.0 * wf_ratio) <= best[0]:
        score, nid, data = best
        name = str(data.get('name', f'Task {nid}'))
        executed = nid in trace_set
        verdict = 'YES' if executed else 'NO'
        return {
            'mode': 'did_query',
            'answer': f"{verdict} - Task '{name}' ({nid}) {'appears' if executed else 'does NOT appear'} in the traced execution.",
            'evidence': f"Trace contains {len(trace_set)} executed task(s); matched '{subject}' to '{name}' (score {score:.2f}).",
            'node_id': nid,
            'executed': executed,
        }

    # Workflow-level answer.
    executed = bool(trace_set)
    return {
        'mode': 'did_query',
        'answer': f"{'YES' if executed else 'NO'} - workflow '{wf_name}' {'executed' if executed else 'did not execute'} in the traced log window.",
        'evidence': f"Trace contains {len(trace_set)} executed task(s) belonging to this workflow.",
        'node_id': None,
        'executed': executed,
    }


# ============================================================
# 6. TOP-LEVEL ENTRY POINT (shared by CLI and Web)
# ============================================================

def run_simulation(engine, wf_name, query_text, trace_ids=None):
    """Parse -> match -> simulate. Returns a JSON-serializable result dict."""
    if wf_name not in engine.graphs:
        raise ValueError(f"Cannot simulate: workflow '{wf_name}' is not loaded.")

    request = parse_query(query_text)

    if request.mode == 'did_query':
        result = answer_did_query(engine, wf_name, request.subject, trace_ids)
        result['workflow'] = wf_name
        return result

    graph = engine.graphs[wf_name]
    gate_clauses = [c for c in request.clauses if c.kind == 'gate']
    data_clauses = [c for c in request.clauses if c.kind == 'data_state']
    failure_clauses = [c for c in request.clauses if c.kind == 'task_failure']

    matched, unmatched = match_clauses(engine, wf_name, gate_clauses)

    # --- Task failure simulation ---
    failure_result = analyze_task_failures(engine, wf_name, failure_clauses)
    failed_tasks = failure_result['failed_tasks']
    failed_ids = failure_result['failed_ids']
    field_impacts = failure_result['field_impacts']
    impacts = list(failure_result['impacts'])
    impacted_map = dict(failure_result['impacted_map'])
    unmatched.extend(failure_result['unmatched'])
    forced = {m['node_id']: m['verdict'] for m in matched}
    forced.update(failure_result['forced_overrides'])

    # --- Dataflow token simulation for zero-record clauses ---
    # Type 29/22 task_failure already propagated inside analyze_task_failures;
    # only data_state clauses need a fresh propagate_null_token pass.
    altered_from_failure = list(failure_result['altered_from_failure'])
    altered_from_failure_ids = {a['node_id'] for a in altered_from_failure}
    altered = list(altered_from_failure)
    for clause in data_clauses:
        nid, data, score = match_task(engine, wf_name, clause)
        if nid is None:
            unmatched.append(clause.text)
            continue
        t_type = graph_utils.get_type_str(data)
        altered.append({
            'node_id': nid,
            'node_name': str(data.get('name', f'Task {nid}')),
            'node_type': t_type,
            'node_type_name': type_display_name(t_type),
            'clause': clause.text,
            'score': round(score, 2),
        })

    data_state_altered = [a for a in altered if a['node_id'] not in altered_from_failure_ids]
    if data_state_altered:
        token_index = build_token_index(graph)
        extra_map, extra_impacts = propagate_null_token(
            graph, [a['node_id'] for a in data_state_altered], token_index)
        for cid, fatal in extra_map.items():
            impacted_map[cid] = impacted_map.get(cid, False) or fatal
        impacts.extend(extra_impacts)

    impacts = _dedupe_impacts(impacts)

    altered_ids = [a['node_id'] for a in altered]
    impacted_ids = sorted(impacted_map.keys())
    fatal_ids = {nid for nid, fatal in impacted_map.items() if fatal}

    # Path overlay target: explicit failed task, else primary altered (Retrieve/Query).
    path_forced_note = None
    failure_path = []
    path_target = None
    path_kind = 'failed'
    if failed_ids:
        path_target = str(failed_ids[0])
        path_kind = 'failed'
    elif altered:
        path_target = str(altered[0]['node_id'])
        path_kind = 'altered'

    if path_target:
        failure_path = path_to_task(graph, path_target)
        if failure_path:
            path_forced = force_verdicts_for_path(engine, wf_name, failure_path)
            for nid, verdict in path_forced.items():
                if nid not in forced:
                    forced[nid] = verdict

    walk = simulate(engine, wf_name, forced)

    # Ensure the highlighted path reaches the simulation target (failed or altered).
    if path_target and failure_path:
        if path_target not in {str(n) for n in walk['path_node_ids']}:
            walk = {
                'path_node_ids': list(failure_path),
                'path_edges': path_edges_from_nodes(failure_path),
                'decisions': walk['decisions'] + [
                    f"Highlighted path to {path_kind} task {path_target}; "
                    f"structural FALSE-spine may differ."
                ],
                'bypassed': walk['bypassed'],
            }
            path_forced_note = (
                f"Highlighted path to {path_kind} task {path_target}; "
                f"structural FALSE-spine may differ."
            )
        else:
            ids = [str(n) for n in walk['path_node_ids']]
            cut = ids.index(path_target) + 1
            trimmed = ids[:cut]
            walk['path_node_ids'] = trimmed
            walk['path_edges'] = path_edges_from_nodes(trimmed)
            visible_ids = {str(n) for n, d in graph.nodes(data=True)
                           if not (graph_utils.is_invisible(d) and graph.out_degree(n) > 0)}
            walk['bypassed'] = sorted(
                str(graph.nodes[n].get('name', f'Task {n}'))
                for n in visible_ids - set(trimmed)
            )

    # --- Narrative summary: failure + impact sentences lead ---
    summary = []
    for ft in failed_tasks:
        fld_part = ''
        if ft.get('node_type') == '23':
            meta_parts = []
            if ft.get('sections'):
                meta_parts.append(f"sections: {', '.join(ft['sections'])}")
            if ft.get('tabs'):
                meta_parts.append(f"tabs: {', '.join(ft['tabs'])}")
            if ft.get('fields'):
                meta_parts.append(f"fields: {', '.join(ft['fields'])}")
            if meta_parts:
                fld_part = f" — UI not updated ({'; '.join(meta_parts)})"
                if ft.get('bo'):
                    fld_part += f" on {ft['bo']}"
        elif ft.get('fields'):
            fld_part = f" — fields not updated: {', '.join(ft['fields'])}"
            if ft.get('bo'):
                fld_part += f" on {ft['bo']}"
        summary.append(
            f"Simulated execution failure for {ft['node_type_name']} (Type {ft['node_type']}) "
            f"'{ft['node_name']}' (ID: {ft['node_id']}){fld_part}."
        )
    for a in altered:
        summary.append(f"Simulated a zero-records / null-token state for the "
                       f"{a['node_type_name']} (Type {a['node_type']}) '{a['node_name']}' (ID: {a['node_id']}).")
    for imp in impacts:
        summary.append(imp['sentence'])
    for m in matched:
        summary.append(f"Gate '{m['node_name']}' ({m['node_id']}) forced {m['verdict']} - {m['reason']}.")
    if path_forced_note:
        summary.append(path_forced_note)
    if not matched and not altered and not failed_tasks:
        summary.append("No specific condition matched a decision gate or task; showing the default (FALSE-spine) route.")
    if unmatched:
        summary.append("Unmatched phrase(s): " + '; '.join(f"'{u}'" for u in unmatched))

    executed_names = [str(graph.nodes[n].get('name', n)) for n in walk['path_node_ids']
                      if graph.has_node(n)]
    end_reached = any(graph_utils.get_type_str(graph.nodes[n]) in ('9', '13')
                      for n in walk['path_node_ids'] if graph.has_node(n))
    on_path_fatal = [n for n in walk['path_node_ids'] if n in fatal_ids]
    if path_target and path_target in {str(n) for n in walk['path_node_ids']}:
        route_line = (
            f"Highlighted path to {path_kind} task {path_target} "
            f"({len(walk['path_node_ids'])} task(s) from Start)."
        )
    else:
        route_line = f"Simulated route executes {len(walk['path_node_ids'])} task(s)"
        if on_path_fatal:
            route_line += (f", of which {len(on_path_fatal)} would fail or bypass "
                           f"due to the missing record token")
        route_line += " and reaches an End task." if end_reached else " and stops before any End task."
    summary.append(route_line)
    if walk['bypassed']:
        shown = walk['bypassed'][:8]
        more = len(walk['bypassed']) - len(shown)
        summary.append("Bypassed: " + ', '.join(f"'{b}'" for b in shown)
                       + (f" (+{more} more)" if more > 0 else "") + ".")

    root_ids = list(failed_ids) + [a for a in altered_ids if a not in failed_ids]
    impact_tree = build_impact_tree(
        impacts, root_ids, failed_tasks=failed_tasks, altered_tasks=altered)

    return {
        'mode': 'what_if',
        'workflow': wf_name,
        'matched_conditions': matched,
        'unmatched_phrases': unmatched,
        'altered_tasks': altered,
        'altered_node_ids': altered_ids,
        'failed_tasks': failed_tasks,
        'failed_node_ids': failed_ids,
        'field_impacts': field_impacts,
        'impacted_node_ids': impacted_ids,
        'impacts': impacts,
        'impact_tree': impact_tree,
        'path_node_ids': walk['path_node_ids'],
        'path_edges': walk['path_edges'],
        'decisions': walk['decisions'],
        'bypassed': walk['bypassed'],
        'summary': summary,
        'executed_names': executed_names,
    }
