"""Intent layer: plain-English (+ form) → recipe dict for om_gen.

Slot extraction (not sentence templates) → known topologies.
Dual path with constrained NL (`nl_to_recipe`). Fail closed — never invent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from om_gen.field_synonyms import known_field_phrases, resolve_field
from om_gen.module_bo_synonyms import (
    MODULE_BO_PHRASES,
    find_event_in_text,
    find_module_bo_in_text,
)
from om_gen.nl_recipe import SUPPORTED_NL_HELP, nl_to_recipe

_CONSTRAINED_HEADER_RE = re.compile(
    r'^\s*on\s+\w+\s*::\s*\w+\s+\S',
    re.IGNORECASE,
)

_PREAMBLE_RE = re.compile(
    r'^\s*(?:create|build|make|generate)\s+(?:a\s+|an\s+)?workflow\s+that\s+',
    re.IGNORECASE,
)

# Empty-family tokens used in field predicates
_EMPTY_WORDS = r'(?:null|empty|blank|missing|unset)'
# Field-null / empty predicate (blank/missing/unset/empty/null + negations)
_IF_FIELD_RE = re.compile(
    r'\bif\s+(?:the\s+)?(?P<sub>.*?)\s+'
    r'(?P<pred>is\s+not\s+' + _EMPTY_WORDS + r'|isn\'t\s+' + _EMPTY_WORDS
    + r'|not\s+' + _EMPTY_WORDS
    + r'|is\s+' + _EMPTY_WORDS
    + r'|equals?\s+(?:' + _EMPTY_WORDS + r'))\b',
    re.IGNORECASE | re.DOTALL,
)
_IF_OTHERWISE_RE = re.compile(r'\bif\b.*\b(?:otherwise|else)\b', re.IGNORECASE | re.DOTALL)
_ARTICLES = frozenset({'a', 'an', 'the'})

# Count gate: result count / count + comparison words + N
_COUNT_RE = re.compile(
    r'\b(?:(?:the\s+)?result\s+count|count)\s+'
    r'(?P<op_words>is\s+greater\s+than|is\s+more\s+than|greater\s+than|more\s+than|'
    r'at\s+least|is\s+at\s+least|is\s+less\s+than|less\s+than|'
    r'equals?(?:\s+to)?|is\s+equal\s+to|is|'
    r'>=|<=|!=|==|=|>|<)\s*'
    r'(?P<n>\d+)\b',
    re.IGNORECASE,
)

# Also: "result count > 0" compact form
_COUNT_SYM_RE = re.compile(
    r'\b(?:(?:the\s+)?result\s+count|count)\s*(?P<op>>=|<=|!=|==|=|>|<)\s*(?P<n>\d+)\b',
    re.IGNORECASE,
)

_RETRIEVE_RE = re.compile(
    r'\b(?:retrieve|retrieves|retrieving|get\s+list(?:\s+of)?|getlist|gets?|getting)\s+'
    r'(?:of\s+)?(?P<what>.+?)'
    r'(?=\s*,|\s+and\s+if\b|\s*;|\s+if\b|\s+then\b|$)',
    re.IGNORECASE,
)

_QUERY_RE = re.compile(
    r'\bquery\s+(?P<what>.+?)(?=\s*,|\s+and\s+if\b|\s*;|\s+if\b|\s+then\b|$)',
    re.IGNORECASE,
)

# modifies/updates <field> by adding/appending …
_MODIFY_BY_ADD_RE = re.compile(
    r'\b(?:modif(?:y|ies)|updates?)\s+(?:the\s+)?(?P<field>.+?)\s+'
    r'by\s+(?:append(?:ing)?|add(?:ing)?)\s+'
    r'(?:(?:the\s+)?(?:letter|character|characters)\s+)?'
    r'(?:(?:a|an|the)\s+)?'
    r'(?P<lit>"[^"]+"|\'[^\']+\'|[A-Za-z0-9_]+)\b',
    re.IGNORECASE,
)

_MODIFY_SET_RE = re.compile(
    r'\b(?:modify|set)\s+(?:the\s+)?(?P<field>.+?)\s*=\s*(?P<value>.+?)(?:\s*;|$)',
    re.IGNORECASE,
)

INTENT_NL_HELP = """
Intent (plain English) — slot extraction, paraphrases OK:

  On save for a building, append Z to the name
  Create a workflow that modifies the building record's name field by adding the letter Z when the user clicks save
  Make a workflow that retrieves building records, and if the result count is greater than 0, then append Z to the building's name field
  … gets building records … more than 0 … append 123GG to the building's name field
  If the building record's name field is not null, append Z to the name; otherwise do nothing
  Create a workflow so that if the building record's name field is blank, add a Z to it, otherwise don't do anything
  Query \"triBuilding - Existing Query\"; if result count > 0 then append Z to the name

Rules:
  - Form Name/Module/BO win when filled; prose may imply Module/BO when form empty.
  - \"Create/Make a workflow that…\" is a preamble (not Type 27 Create Record).
  - Events: save/clicks save → triSave; pre-create → Pre-Create; see om_gen/module_bo_synonyms.py.
  - Fields: name → triNameTX; unknown phrases error — add synonyms in om_gen/field_synonyms.py.
  - Null/empty/blank/missing/unset → Expression p0 == \"\" / p0 != \"\" with Param field binding.
  - \"add a Z\" → literal Z (article skipped). Pronoun \"it\" → last mentioned field.
  - if … otherwise with unrecognized predicate → error (no silent Modify-only).
  - Result count ONLY after Query(22) or Retrieve(29) that names WHAT.
  - Query needs an existing Query object name (FilterBo); BO-only → error (use retrieve).
  - Module→BO dropdown catalog: tririga_modules_bos.json via /api/generator/catalog.

Add synonyms: edit EVENT_SYNONYMS / MODULE_BO_PHRASES in module_bo_synonyms.py
or _GLOBAL / _BY_BO in field_synonyms.py (lowercase phrase keys; longest match wins).
Refresh Module/BO lists by replacing tririga_modules_bos.json at the repo root.

""" + SUPPORTED_NL_HELP


class IntentError(ValueError):
    """Structured intent failure — never invent missing facts."""

    def __init__(self, message: str, *, code: str = 'unsupported_intent', span: str = ''):
        super().__init__(message)
        self.code = code
        self.span = span
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        d = {'error': self.message, 'code': self.code}
        if self.span:
            d['span'] = self.span
        return d


@dataclass
class SourceSlot:
    kind: str  # retrieve | query
    key: str = 'src1'
    filter_bo: str = ''
    module: str = ''
    bo: str = ''
    span: str = ''


@dataclass
class CountSlot:
    op: str
    n: int
    span: str = ''


@dataclass
class FieldPredSlot:
    field: str
    section: str
    expression: str
    span: str = ''


@dataclass
class ModifySlot:
    field: str
    section: str
    literal: str
    formula: str
    span: str = ''


@dataclass
class IntentSlots:
    event: str = ''
    module: str = ''
    bo: str = ''
    source: Optional[SourceSlot] = None
    count: Optional[CountSlot] = None
    field_pred: Optional[FieldPredSlot] = None
    modify: Optional[ModifySlot] = None
    raw_text: str = ''


def strip_preamble(text: str) -> str:
    """Remove 'Create/Make a workflow that…' style preambles (not Type 27)."""
    return _PREAMBLE_RE.sub('', (text or '').strip(), count=1).strip()


def looks_constrained(prompt: str) -> bool:
    return bool(_CONSTRAINED_HEADER_RE.match(prompt or ''))


def parse_prompt(
    prompt: str,
    *,
    name: str = '',
    module: str = '',
    bo: str = '',
    event_name: str = '',
) -> Dict[str, Any]:
    """Dual-path: constrained grammar OR intent → recipe dict."""
    text = (prompt or '').strip()
    if not text:
        raise IntentError('Empty prompt.', code='unsupported_intent')

    if looks_constrained(text):
        return nl_to_recipe(
            text, name=name, module=module, bo=bo, event_name=event_name,
        )

    body = strip_preamble(text)
    recipe = intent_to_recipe(
        body, name=name, module=module, bo=bo, event_name=event_name,
    )
    if name:
        recipe['header']['name'] = name
    if module:
        recipe['header']['module'] = module
    if bo:
        recipe['header']['bo'] = bo
    if event_name and not recipe['header'].get('event_name'):
        recipe['header']['event_name'] = event_name
    return recipe


def intent_to_recipe(
    prompt: str,
    *,
    name: str = '',
    module: str = '',
    bo: str = '',
    event_name: str = '',
) -> Dict[str, Any]:
    text = (prompt or '').strip()
    if not text:
        raise IntentError('Empty prompt.', code='unsupported_intent')

    slots = extract_slots(text, form_module=module, form_bo=bo, form_event=event_name)
    return compile_slots(slots, name=name, original_text=text)


def extract_slots(
    text: str,
    *,
    form_module: str = '',
    form_bo: str = '',
    form_event: str = '',
) -> IntentSlots:
    slots = IntentSlots(raw_text=text)

    # Module/BO
    mod, bob, conflict = _resolve_header_module_bo(text, form_module, form_bo)
    if conflict:
        raise IntentError(
            f'Form Module/BO ({form_module}/{form_bo}) conflicts with prose '
            f'({conflict[0]}/{conflict[1]}). Clear the form or align the description.',
            code='ambiguous_span',
            span=conflict[2] if len(conflict) > 2 else '',
        )
    if not mod or not bob:
        raise IntentError(
            'Could not determine Module/BO. Fill the Module and BO form fields '
            '(see Generator catalog from tririga_modules_bos.json), '
            'or name a known record type (e.g. building, land).',
            code='module_bo_unresolved',
        )
    slots.module, slots.bo = mod, bob

    # Event
    if form_event:
        slots.event = form_event
    else:
        found_ev = find_event_in_text(text)
        if found_ev:
            slots.event = found_ev[0]

    # Source (retrieve / query)
    slots.source = _extract_source(text, mod, bob)

    # Count gate
    slots.count = _extract_count(text)
    if slots.count and not slots.source:
        raise IntentError(
            'Result-count gate needs a Query or Retrieve that names WHAT. '
            'Example: "retrieve buildings; if result count is greater than 0 then …" '
            'or "query \\"Existing Query Name\\"; if result count > 0 then …".',
            code='bare_result_count',
            span=slots.count.span,
        )

    # Field-null predicate (skip when count gate present — count takes precedence for "if")
    if not slots.count:
        slots.field_pred = _extract_field_pred(text, mod, bob)

    # if … otherwise/else without a recognized predicate or count → fail closed
    if (
        not slots.count
        and not slots.field_pred
        and _IF_OTHERWISE_RE.search(text)
    ):
        span = _unrecognized_if_span(text)
        raise IntentError(
            f'Unrecognized if/otherwise condition {span!r}. '
            f'Use blank/empty/null/missing/unset (or not …), or a result-count gate after retrieve/query.',
            code='unrecognized_predicate',
            span=span,
        )

    # Modify / append (uses field_pred for pronoun "it")
    slots.modify = _extract_modify(text, mod, bob, field_pred=slots.field_pred)

    # Default event when modify-like and no event found
    if not slots.event and slots.modify:
        slots.event = 'triSave'

    return slots


def compile_slots(
    slots: IntentSlots,
    *,
    name: str = '',
    original_text: str = '',
) -> Dict[str, Any]:
    text = original_text or slots.raw_text
    mod, bob, ev = slots.module, slots.bo, slots.event or 'triSave'

    # Source + count + modify
    if slots.source and slots.count:
        if not slots.modify:
            raise IntentError(
                'Count Switch needs a TRUE-branch action (e.g. append Z to the name).',
                code='unsupported_intent',
                span=slots.count.span,
            )
        return _compile_count_topology(slots, name=name, text=text)

    # Field-null Switch + modify
    if slots.field_pred:
        if not slots.modify:
            raise IntentError(
                'Field Switch needs a TRUE-branch action (e.g. append Z to the name).',
                code='unsupported_intent',
                span=slots.field_pred.span,
            )
        return _compile_field_switch_topology(slots, name=name, text=text)

    # Modify only
    if slots.modify:
        return _compile_modify_topology(slots, name=name, text=text)

    # Standalone retrieve / query
    if slots.source and not slots.count:
        return _compile_source_only(slots, name=name, text=text)

    raise IntentError(
        'Could not map description to a supported intent. '
        'Use constrained NL (On Module::BO Event: …) or see nl-help for intent examples.',
        code='unsupported_intent',
        span=text[:80],
    )


# ----- extractors -----

def _resolve_header_module_bo(
    text: str, form_mod: str, form_bo: str,
) -> Tuple[str, str, Optional[Tuple[str, str, str]]]:
    found = find_module_bo_in_text(text)
    if form_mod and form_bo:
        if found and (found[0] != form_mod or found[1] != form_bo):
            return form_mod, form_bo, (found[0], found[1], found[2])
        return form_mod, form_bo, None
    if found:
        return found[0], found[1], None
    return form_mod or '', form_bo or '', None


def _op_from_words(raw: str) -> str:
    w = ' '.join(raw.lower().split())
    mapping = {
        'is greater than': '>', 'greater than': '>', 'is more than': '>', 'more than': '>',
        'at least': '>=', 'is at least': '>=',
        'is less than': '<', 'less than': '<',
        'equals': '==', 'equal': '==', 'equals to': '==', 'is equal to': '==', 'is': '==',
        '>=': '>=', '<=': '<=', '!=': '!=', '==': '==', '=': '==', '>': '>', '<': '<',
    }
    return mapping.get(w, w if w in ('>', '>=', '<', '<=', '==', '!=') else '>')


def _extract_count(text: str) -> Optional[CountSlot]:
    m = _COUNT_RE.search(text) or _COUNT_SYM_RE.search(text)
    if not m:
        return None
    op_raw = m.group('op_words') if 'op_words' in m.groupdict() and m.group('op_words') else m.group('op')
    op = _op_from_words(op_raw)
    if op == '=':
        op = '=='
    return CountSlot(op=op, n=int(m.group('n')), span=m.group(0))


def _query_what_is_bo_only(what: str, mod: str, bob: str) -> bool:
    w = what.strip().strip('"\'')
    if not w:
        return True
    if ' - ' in w:
        return False
    if w.lower() in MODULE_BO_PHRASES:
        return True
    if w in (bob, mod) or w.lower() in (bob.lower(), 'buildings', 'lands', 'spaces', 'records'):
        return True
    if re.match(r'^tri\w+$', w) and ' ' not in w:
        return True
    if re.match(r'^[a-z]+s$', w.lower()) and len(w) < 24:
        return True
    # "building records" style
    if find_module_bo_in_text(w):
        return True
    return False


def _extract_source(text: str, mod: str, bob: str) -> Optional[SourceSlot]:
    qm = _QUERY_RE.search(text)
    rm = _RETRIEVE_RE.search(text)

    # Prefer retrieve when both somehow match overlapping; query keyword is explicit
    if qm and (not rm or qm.start() <= rm.start()):
        # If retrieve also matches and query "what" looks like BO — might be false positive
        what = qm.group('what').strip().strip('"\'')
        # Avoid matching "query" inside other words — already word-bound
        if _query_what_is_bo_only(what, mod, bob):
            raise IntentError(
                f'Query requires an existing Query object name (FilterBo), not only a BO. '
                f'Provide the Query name in quotes, or rephrase as "retrieve {what}" for Type 29.',
                code='query_needs_name',
                span=what,
            )
        return SourceSlot(
            kind='query', key='src1', filter_bo=what,
            module=mod, bo=bob, span=qm.group(0),
        )

    if rm:
        what = rm.group('what').strip().strip('"\'')
        # Trim trailing "records" noise for BO lookup
        what_clean = re.sub(r'\s+records?\s*$', '', what, flags=re.I).strip() or what
        rmod, rbob = mod, bob
        found = find_module_bo_in_text(what_clean) or find_module_bo_in_text(what)
        if found:
            rmod, rbob = found[0], found[1]
        return SourceSlot(
            kind='retrieve', key='src1',
            module=rmod, bo=rbob, span=rm.group(0),
        )
    return None


def _null_expression(pred: str) -> str:
    p = pred.lower()
    # Negations: is not blank, isn't empty, not null, …
    if re.search(r'\bnot\b|isn\'t|isnt', p):
        return 'p0 != ""'
    return 'p0 == ""'


def _unrecognized_if_span(text: str) -> str:
    m = re.search(
        r'\bif\b(.{0,80}?)(?:\botherwise\b|\belse\b)',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return ('if' + m.group(1)).strip()[:100]
    return text[:80]


def _resolve_field_phrase(phrase: str, mod: str, bob: str) -> Tuple[str, str]:
    cleaned = phrase.strip()
    cleaned = re.sub(
        r'^(?:the\s+)?(?:building|land|space|property|floor|people|person|project|'
        r'contract|lease)(?:\s+record)?(?:\'s|’s)?\s+',
        '',
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r'^record\'s\s+', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+field$', '', cleaned, flags=re.I).strip()
    cleaned = cleaned.strip()
    for cand in (cleaned, phrase.strip()):
        got = resolve_field(cand, module=mod, bo=bob)
        if got:
            return got
        # "building's name" already in catalog; try "name" if phrase ends with name
        if 'name' in cand.lower():
            got = resolve_field('name', module=mod, bo=bob)
            if got:
                return got
    known = ', '.join(known_field_phrases(mod, bob)[:12])
    raise IntentError(
        f'Unknown field phrase {phrase!r}. Use a TRIRIGA field name (e.g. triNameTX) '
        f'or a known synonym ({known}, …).',
        code='unknown_field',
        span=phrase.strip(),
    )


def _extract_field_pred(text: str, mod: str, bob: str) -> Optional[FieldPredSlot]:
    m = _IF_FIELD_RE.search(text)
    if not m:
        return None
    field, section = _resolve_field_phrase(m.group('sub'), mod, bob)
    return FieldPredSlot(
        field=field,
        section=section,
        expression=_null_expression(m.group('pred')),
        span=m.group(0),
    )


def _normalize_literal(lit: str) -> str:
    lit = lit.strip()
    if (lit.startswith('"') and lit.endswith('"')) or (lit.startswith("'") and lit.endswith("'")):
        return lit[1:-1]
    return lit


def _reject_article_literal(lit: str) -> str:
    """Reject articles mistaken as literals; raise unknown_literal if empty."""
    lit = _normalize_literal(lit)
    if lit.lower() in _ARTICLES or not lit:
        raise IntentError(
            f'Could not determine append/add literal (got {lit!r}). '
            f'Use e.g. "add a Z", "append \\"123GG\\"", or "adding the letter Z".',
            code='unknown_literal',
            span=lit or '',
        )
    return lit


def _extract_append_literal(
    text: str,
) -> Optional[Tuple[str, Optional[str], str]]:
    """Return (literal, field_phrase_or_None, span) with article-safe priority."""
    # 1) letter/character(s) X
    m = re.search(
        r'\b(?:append(?:ing)?|add(?:ing)?)\s+'
        r'(?:(?:the\s+)?(?:letter|character|characters)\s+)'
        r'(?P<lit>"[^"]+"|\'[^\']+\'|\S+)'
        r'(?:\s+to\s+(?:the\s+)?(?P<field>.+?))?'
        r'(?=\s+when\b|\s+on\s+save\b|\s+on\s+pre|\s*;|\s+otherwise|\s+else|,?\s+and\s+if\b|$)',
        text,
        re.I,
    )
    if m:
        lit = _reject_article_literal(m.group('lit'))
        fld = (m.group('field') or '').strip() or None
        return lit, fld, m.group(0)

    # 2) quoted after append/add
    m = re.search(
        r'\b(?:append(?:ing)?|add(?:ing)?)\s+(?P<lit>"[^"]+"|\'[^\']+\')'
        r'(?:\s+to\s+(?:the\s+)?(?P<field>.+?))?'
        r'(?=\s+when\b|\s+on\s+save\b|\s+on\s+pre|\s*;|\s+otherwise|\s+else|,?\s+and\s+if\b|$)',
        text,
        re.I,
    )
    if m:
        lit = _reject_article_literal(m.group('lit'))
        fld = (m.group('field') or '').strip() or None
        return lit, fld, m.group(0)

    # 3) add/append a|an|the TOKEN  (token after article = literal)
    m = re.search(
        r'\b(?:append(?:ing)?|add(?:ing)?)\s+(?:a|an|the)\s+'
        r'(?P<lit>"[^"]+"|\'[^\']+\'|[A-Za-z0-9_]+)'
        r'(?:\s+to\s+(?:the\s+)?(?P<field>.+?))?'
        r'(?=\s+when\b|\s+on\s+save\b|\s+on\s+pre|\s*;|\s+otherwise|\s+else'
        r'|,?\s+and\s+if\b|\s*,|\s*$)',
        text,
        re.I,
    )
    if m:
        lit = _reject_article_literal(m.group('lit'))
        fld = (m.group('field') or '').strip() or None
        if fld:
            fld = re.sub(r'\s+when\s+the\s+user\s+clicks\s+save.*$', '', fld, flags=re.I).strip()
        return lit, fld, m.group(0)

    # 4) add/append TOKEN to field (TOKEN not an article)
    m = re.search(
        r'\b(?:append(?:ing)?|add(?:ing)?)\s+(?!a\b|an\b|the\b)'
        r'(?P<lit>"[^"]+"|\'[^\']+\'|[A-Za-z0-9_]+)\s+'
        r'to\s+(?:the\s+)?(?P<field>.+?)'
        r'(?=\s+when\b|\s+on\s+save\b|\s+on\s+pre|\s*;|\s+otherwise|\s+else|,?\s+and\s+if\b|$)',
        text,
        re.I,
    )
    if m:
        lit = _reject_article_literal(m.group('lit'))
        fld = m.group('field').strip()
        fld = re.sub(r'\s+when\s+the\s+user\s+clicks\s+save.*$', '', fld, flags=re.I).strip()
        return lit, fld, m.group(0)

    # 5) bare add/append TOKEN (no "to") — not article
    m = re.search(
        r'\b(?:append(?:ing)?|add(?:ing)?)\s+(?!a\b|an\b|the\b)'
        r'(?P<lit>"[^"]+"|\'[^\']+\'|[A-Za-z0-9_]+)\b',
        text,
        re.I,
    )
    if m:
        lit = _reject_article_literal(m.group('lit'))
        return lit, None, m.group(0)

    return None


def _resolve_modify_field(
    field_phrase: Optional[str],
    text: str,
    mod: str,
    bob: str,
    field_pred: Optional[FieldPredSlot],
) -> Tuple[str, str]:
    """Resolve target field; pronoun 'it' → pred field or name."""
    phrase = (field_phrase or '').strip()
    if not phrase or phrase.lower() in ('it', 'itself'):
        if field_pred:
            return field_pred.field, field_pred.section
        if re.search(r'\bname\b', text, re.I):
            return _resolve_field_phrase('name', mod, bob)
        return 'triNameTX', 'General'
    phrase = re.sub(r'\s+when\s+the\s+user\s+clicks\s+save.*$', '', phrase, flags=re.I).strip()
    return _resolve_field_phrase(phrase, mod, bob)


def _extract_modify(
    text: str,
    mod: str,
    bob: str,
    *,
    field_pred: Optional[FieldPredSlot] = None,
) -> Optional[ModifySlot]:
    m = _MODIFY_BY_ADD_RE.search(text)
    if m:
        lit = _reject_article_literal(m.group('lit'))
        field, section = _resolve_field_phrase(m.group('field'), mod, bob)
        return ModifySlot(
            field=field, section=section, literal=lit,
            formula=f'{field} + "{lit}"', span=m.group(0),
        )

    got = _extract_append_literal(text)
    if got:
        lit, field_phrase, span = got
        field, section = _resolve_modify_field(field_phrase, text, mod, bob, field_pred)
        return ModifySlot(
            field=field, section=section, literal=lit,
            formula=f'{field} + "{lit}"', span=span,
        )

    mm = _MODIFY_SET_RE.search(text)
    if mm:
        fld_phrase = mm.group('field').strip()
        val = mm.group('value').strip().strip(';')
        field, section = _resolve_field_phrase(fld_phrase, mod, bob)
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            lit = val[1:-1]
            if re.search(r'[+\-*/]', val):
                return ModifySlot(
                    field=field, section=section, literal='',
                    formula=val.strip('"\''), span=mm.group(0),
                )
            return ModifySlot(
                field=field, section=section, literal=lit,
                formula=lit, span=mm.group(0),
            )
        return ModifySlot(
            field=field, section=section, literal='',
            formula=val, span=mm.group(0),
        )

    return None


# ----- compilers -----

def _header(name: str, mod: str, bob: str, event: str, desc: str) -> Dict[str, Any]:
    wf_name = name or f'{bob} - Synchronous - {event or "Generated"}'
    return {
        'name': wf_name,
        'module': mod,
        'bo': bob,
        'event_name': event or '',
        'description': desc[:200],
        'object_label_name': 'In Progress 0.0',
    }


def _modify_task_from_slot(key: str, slots: IntentSlots) -> Dict[str, Any]:
    assert slots.modify is not None
    m = slots.modify
    mod, bob = slots.module, slots.bo
    if m.literal != '' or (m.formula and '+' in m.formula):
        value = m.formula if m.formula else f'{m.field} + "{m.literal}"'
        map_type = '80'
        sec = 'General'
    else:
        value = m.formula
        map_type = '40'
        sec = m.section or 'General'
    return {
        'key': key,
        'type': '28',
        'label': 'Modify Records',
        'event_name': 'Append',
        'module': mod,
        'bo': bob,
        'mappings': [{
            'field': m.field,
            'value': value,
            'map_type': map_type,
            'trgt_module': mod,
            'trgt_bo': bob,
            'trgt_tab': 'General',
            'trgt_sec': sec,
        }],
        'refs': [
            {'ref_task_id': '0', 'ref_type': '0', 'use_type': '1', 'module': mod, 'bo': bob},
            {'ref_task_id': '0', 'ref_type': '1', 'use_type': '2', 'module': mod, 'bo': bob},
        ],
    }


def _compile_modify_topology(slots: IntentSlots, *, name: str, text: str) -> Dict[str, Any]:
    mod_task = _modify_task_from_slot('mod1', slots)
    return {
        'header': _header(
            name, slots.module, slots.bo, slots.event or 'triSave',
            f'Generated from intent: {text[:160]}',
        ),
        'tasks': [
            {'key': 'start', 'type': '1', 'label': 'Start'},
            mod_task,
            {'key': 'end', 'type': '9', 'label': 'End'},
        ],
        'edges': [
            {'from': 'start', 'to': 'mod1'},
            {'from': 'mod1', 'to': 'end'},
        ],
    }


def _compile_field_switch_topology(slots: IntentSlots, *, name: str, text: str) -> Dict[str, Any]:
    assert slots.field_pred and slots.modify
    fp = slots.field_pred
    true_task = _modify_task_from_slot('mod_true', slots)
    j_false = {'key': 'j_false', 'type': '12', 'label': 'Junction False'}
    switch = {
        'key': 'sw1',
        'type': '14',
        'label': 'Switch',
        'event_name': '0=true;1=false;',
        'target_association': 'mod_true;j_false;',
        'trgt_task_id': 'j_false',
        'condition': {
            'expression': fp.expression,
            'params': [{
                'p_id': '0', 'p_type': 'field', 'p_data_id': '0',
                'p_field': fp.field, 'p_section': fp.section,
                'p_module': slots.module, 'p_bo': slots.bo,
            }],
        },
    }
    return {
        'header': _header(
            name, slots.module, slots.bo, slots.event or 'triSave',
            f'Generated from intent: {text[:160]}',
        ),
        'tasks': [
            {'key': 'start', 'type': '1', 'label': 'Start'},
            switch, true_task, j_false,
            {'key': 'end', 'type': '9', 'label': 'End'},
        ],
        'edges': [
            {'from': 'start', 'to': 'sw1'},
            {'from': 'sw1', 'to': 'mod_true'},
            {'from': 'sw1', 'to': 'j_false'},
            {'from': 'mod_true', 'to': 'end'},
            {'from': 'j_false', 'to': 'end'},
        ],
    }


def _compile_count_topology(slots: IntentSlots, *, name: str, text: str) -> Dict[str, Any]:
    assert slots.source and slots.count and slots.modify
    src = slots.source
    cnt = slots.count
    tasks: List[Dict[str, Any]] = [{'key': 'start', 'type': '1', 'label': 'Start'}]
    if src.kind == 'query':
        tasks.append({
            'key': src.key, 'type': '22', 'label': src.filter_bo[:48],
            'filter_bo': src.filter_bo, 'filter_module': src.module,
            'filter_bo_bo': src.bo, 'filter_class': '',
            'module': src.module, 'bo': src.bo,
        })
    else:
        tasks.append({
            'key': src.key, 'type': '29', 'label': f'Retrieve {src.bo}',
            'event_name': 'GETLIST', 'module': src.module, 'bo': src.bo,
        })
    true_task = _modify_task_from_slot('mod_true', slots)
    j_false = {'key': 'j_false', 'type': '12', 'label': 'Junction False'}
    expr = f'p0 {cnt.op} {cnt.n}'
    switch = {
        'key': 'sw1',
        'type': '14',
        'label': 'Switch',
        'event_name': '0=true;1=false;',
        'target_association': 'mod_true;j_false;',
        'trgt_task_id': 'j_false',
        'condition': {
            'expression': expr,
            'params': [{
                'p_id': '0', 'p_type': 'item',
                'p_data_id': src.key, 'p_item': 'Result Count',
            }],
        },
    }
    tasks.extend([switch, true_task, j_false, {'key': 'end', 'type': '9', 'label': 'End'}])
    return {
        'header': _header(
            name, slots.module, slots.bo, slots.event or 'triSave',
            f'Generated from intent: {text[:160]}',
        ),
        'tasks': tasks,
        'edges': [
            {'from': 'start', 'to': src.key},
            {'from': src.key, 'to': 'sw1'},
            {'from': 'sw1', 'to': 'mod_true'},
            {'from': 'sw1', 'to': 'j_false'},
            {'from': 'mod_true', 'to': 'end'},
            {'from': 'j_false', 'to': 'end'},
        ],
    }


def _compile_source_only(slots: IntentSlots, *, name: str, text: str) -> Dict[str, Any]:
    assert slots.source
    src = slots.source
    if src.kind == 'query':
        task = {
            'key': 'q1', 'type': '22', 'label': src.filter_bo[:48],
            'filter_bo': src.filter_bo, 'filter_module': src.module,
            'filter_bo_bo': src.bo, 'filter_class': '',
            'module': src.module, 'bo': src.bo,
        }
        key = 'q1'
    else:
        task = {
            'key': 'r1', 'type': '29', 'label': f'Retrieve {src.bo}',
            'event_name': 'GETLIST', 'module': src.module, 'bo': src.bo,
        }
        key = 'r1'
    return {
        'header': _header(
            name, slots.module, slots.bo, slots.event or 'triSave',
            f'Generated from intent: {text[:160]}',
        ),
        'tasks': [
            {'key': 'start', 'type': '1', 'label': 'Start'},
            task,
            {'key': 'end', 'type': '9', 'label': 'End'},
        ],
        'edges': [
            {'from': 'start', 'to': key},
            {'from': key, 'to': 'end'},
        ],
    }
