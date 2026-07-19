"""What-If simulation internals — split for reviewability."""
from __future__ import annotations

import re
import difflib
from collections import defaultdict, deque
from dataclasses import dataclass, field

import networkx as nx

from cli import graph_utils
from cli.knowledge import type_display_name

from cli.simulation.lexicon import *  # noqa: F401,F403

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
    (re.compile(r"\bcreate(?:\s+records?)?\s+task\b|\bcreate\s+task\b", re.I), '27'),
    (re.compile(r"\bget\s+temp(?:\s+record)?(?:\s+task)?\b|\btemp\s+record\s+task\b", re.I), '25'),
    (re.compile(r"\bsave\s+permanent(?:\s+record)?(?:\s+task)?\b|\bpermanent\s+record\s+task\b", re.I), '26'),
    (re.compile(r"\bfork(?:\s+task)?\b", re.I), '10'),
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


