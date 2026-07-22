"""Constrained NL → recipe mapper (synonyms → task types).

Not a freeform planner. Unknown verbs raise ValueError listing supported verbs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from om_gen.schema import NL_VERBS, type_label

SUPPORTED_NL_HELP = """Constrained NL grammar for om_gen:

  On <Module>::<BO> <EventName>: <step>; <step>; ...

Steps (verbs → types):
  start                         → Type 1
  end                           → Type 9
  junction                      → Type 12
  switch [cond ...]             → Type 14  (needs target_association in recipe for branches)
  loop                          → Type 20
  break                         → Type 21
  query <QueryName>             → Type 22
  modify metadata ...           → Type 23
  iterator / iter               → Type 24
  get temp [record]             → Type 25
  save [permanent]              → Type 26
  create [record]               → Type 27
  modify [records] set F=V ...  → Type 28
  retrieve <label>              → Type 29
  associate / de-associate      → Type 30
  trigger <Action>              → Type 31
  call [workflow] <Name>        → Type 38
  define var <Name>             → Type 40
  assign var <Name>             → Type 41

Modify field sets:
  modify set triNameTX=Hello
  modify set triNameTX = triNameTX + "Z"

Example:
  On Location::triBuilding triSave: modify set triNameTX = triNameTX + "Z"
"""

_HEADER_RE = re.compile(
    r'on\s+(\w+)\s*::\s*(\w+)\s+(\S.+?)(?:\s*:|\s+then\b|\s*$)',
    re.IGNORECASE,
)

_SET_RE = re.compile(
    r'set\s+(\w+)\s*=\s*(.+)$',
    re.IGNORECASE,
)


def _supported_verb_list() -> str:
    verbs = sorted(set(NL_VERBS.keys()))
    return ', '.join(verbs)


def _split_steps(body: str) -> List[str]:
    body = body.strip()
    if not body:
        return []
    parts = re.split(r'\s*;\s*|\s+then\s+|\n+', body, flags=re.IGNORECASE)
    out = []
    for p in parts:
        p = p.strip(' .')
        if p:
            out.append(p)
    return out


def _parse_modify_sets(rest: str) -> List[Dict[str, str]]:
    """Parse 'set A=B, C=D' or 'set A = B + "Z'"."""
    rest = rest.strip()
    if rest.lower().startswith('set '):
        rest = rest[4:].strip()
    if not rest:
        return []
    # Split on commas not inside quotes
    chunks: List[str] = []
    cur = []
    in_q = False
    for ch in rest:
        if ch in '"\'':
            in_q = not in_q
            cur.append(ch)
        elif ch == ',' and not in_q:
            chunks.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        chunks.append(''.join(cur).strip())

    mappings = []
    for chunk in chunks:
        m = re.match(r'(\w+)\s*=\s*(.+)$', chunk.strip())
        if not m:
            raise ValueError(f'Bad modify assignment: {chunk!r}')
        field, value = m.group(1), m.group(2).strip()
        # Strip wrapping quotes for pure literals
        map_type = ''
        if re.search(r'[+\-*/()]', value) and re.search(r'[A-Za-z_]', value):
            map_type = '80'
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
            map_type = '40'
        else:
            map_type = '40'
        mappings.append({'field': field, 'value': value, 'map_type': map_type})
    return mappings


def _match_verb(raw: str) -> Tuple[str, str, str]:
    """Return (kind_code, verb_matched, remainder)."""
    text = raw.strip()
    lower = text.lower()
    # Longest verb match first
    for verb in sorted(NL_VERBS.keys(), key=len, reverse=True):
        if lower == verb or lower.startswith(verb + ' '):
            rest = text[len(verb):].strip()
            return NL_VERBS[verb], verb, rest
    raise ValueError(
        f'Unknown step verb in {raw!r}. Supported: {_supported_verb_list()}'
    )


def nl_to_recipe(
    prompt: str,
    *,
    name: str = '',
    module: str = '',
    bo: str = '',
    event_name: str = '',
) -> Dict[str, Any]:
    text = (prompt or '').strip()
    if not text:
        raise ValueError('Empty prompt.')

    mod, bob, event, body = module or 'Location', bo or 'triBuilding', event_name, text
    m = _HEADER_RE.search(text)
    if m:
        mod, bob, event = m.group(1), m.group(2), m.group(3).strip().rstrip(':')
        body = text[m.end():].strip().lstrip(':').strip()
    elif module and bo:
        body = text
        event = event_name or event

    # If body still looks like full sentence without verbs, try to find "modify"
    steps_raw = _split_steps(body)
    if not steps_raw and body:
        steps_raw = [body]

    # Auto-wrap with start/end if missing
    tasks: List[Dict[str, Any]] = []
    key_i = 0

    def next_key(prefix: str) -> str:
        nonlocal key_i
        key_i += 1
        return f'{prefix}{key_i}'

    parsed_steps: List[Tuple[str, str, str]] = []
    for raw in steps_raw:
        # Allow bare "modify set ..." without requiring "start"
        try:
            parsed_steps.append(_match_verb(raw))
        except ValueError:
            # Try prepend modify if looks like set
            if re.match(r'^set\s+\w+', raw, re.I):
                parsed_steps.append(_match_verb('modify ' + raw))
            else:
                raise

    has_start = any(c == '1' for c, _, _ in parsed_steps)
    has_end = any(c == '9' for c, _, _ in parsed_steps)
    if not has_start:
        tasks.append({'key': 'start', 'type': '1', 'label': 'Start'})
    for code, verb, rest in parsed_steps:
        if code == '1':
            tasks.append({'key': 'start', 'type': '1', 'label': 'Start'})
        elif code == '9':
            tasks.append({'key': 'end', 'type': '9', 'label': 'End'})
        elif code == '28':
            mappings = _parse_modify_sets(rest) if rest else []
            if not mappings and rest.lower().startswith('set'):
                mappings = _parse_modify_sets(rest)
            t: Dict[str, Any] = {
                'key': next_key('mod'),
                'type': '28',
                'label': 'Modify Records',
                'event_name': 'Append',
                'module': mod,
                'bo': bob,
                'mappings': [
                    {
                        'field': mp['field'],
                        'value': mp['value'],
                        'map_type': mp['map_type'],
                        'trgt_module': mod,
                        'trgt_bo': bob,
                        'trgt_tab': 'General',
                        'trgt_sec': 'General',
                    }
                    for mp in mappings
                ],
                'refs': [
                    {'ref_task_id': '0', 'ref_type': '0', 'use_type': '1',
                     'module': mod, 'bo': bob},
                    {'ref_task_id': '0', 'ref_type': '1', 'use_type': '2',
                     'module': mod, 'bo': bob},
                ],
            }
            tasks.append(t)
        elif code == '27':
            tasks.append({
                'key': next_key('cr'), 'type': '27',
                'label': (rest or 'Create Record')[:48],
                'event_name': 'triCreate', 'module': mod, 'bo': bob,
                'mappings': [{
                    'field': 'triNameTX', 'value': '', 'map_type': '40',
                    'trgt_module': mod, 'trgt_bo': bob,
                }],
            })
        elif code == '22':
            qname = rest.strip().strip('"\'') or 'Query'
            tasks.append({
                'key': next_key('q'), 'type': '22', 'label': qname[:48],
                'filter_bo': qname, 'filter_module': mod, 'filter_bo_bo': bob,
                'module': mod, 'bo': bob,
            })
        elif code == '29':
            tasks.append({
                'key': next_key('r'), 'type': '29',
                'label': (rest or 'Retrieve')[:48],
                'event_name': 'GETLIST', 'module': mod, 'bo': bob,
            })
        elif code == '25':
            tasks.append({
                'key': next_key('tmp'), 'type': '25',
                'label': 'Get Temp Record', 'module': mod, 'bo': bob,
            })
        elif code == '26':
            tasks.append({'key': next_key('sv'), 'type': '26', 'label': 'Save Permanent'})
        elif code == '38':
            callee = rest.strip().strip('"\'')
            if not callee:
                raise ValueError('call requires a workflow name')
            tasks.append({
                'key': next_key('call'), 'type': '38', 'label': callee[:48],
                'filter_bo': callee, 'filter_module': mod, 'filter_bo_bo': bob,
                'module': mod, 'bo': bob,
            })
        elif code == '31':
            action = rest.split()[0] if rest else 'triUpdate'
            tasks.append({
                'key': next_key('trig'), 'type': '31',
                'label': f'Trigger {action}', 'event_name': action,
                'module': mod, 'bo': bob,
            })
        elif code == '30':
            ev = 'De-Associate' if 'de' in verb else 'Associate'
            assoc = rest.strip() or 'Has'
            tasks.append({
                'key': next_key('asc'), 'type': '30', 'label': ev,
                'event_name': ev, 'service_association': assoc,
                'module': mod, 'bo': bob,
            })
        elif code == '14':
            # Branches need explicit keys — create junctions placeholders
            j_true = next_key('j')
            j_false = next_key('j')
            tasks.append({
                'key': next_key('sw'), 'type': '14', 'label': 'Switch',
                'event_name': '0=true;1=false;',
                'target_association': f'{j_true};{j_false};',
                'condition': {'expression': rest or 'true', 'params': []},
            })
            tasks.append({'key': j_true, 'type': '12', 'label': 'Junction True'})
            tasks.append({'key': j_false, 'type': '12', 'label': 'Junction False'})
        elif code == '12':
            tasks.append({'key': next_key('j'), 'type': '12', 'label': 'Junction'})
        elif code == '20':
            tasks.append({'key': next_key('lp'), 'type': '20', 'label': 'Loop Task'})
        elif code == '21':
            tasks.append({
                'key': next_key('br'), 'type': '21', 'label': 'Break',
                'event_name': '0=true;1=false;',
                'target_association': 'end;end;',
            })
        elif code == '23':
            tasks.append({
                'key': next_key('md'), 'type': '23', 'label': 'Modify Metadata',
                'module': mod, 'bo': bob,
                'gui_mappings': [{
                    'prop_type': '1', 'prop_val': 'true',
                    'tab': 'General', 'section': 'General', 'field': '',
                    'bo': bob, 'bo_module': mod,
                }],
            })
        elif code == '24':
            body_k = next_key('j')
            exit_k = next_key('j')
            tasks.append({
                'key': next_key('it'), 'type': '24', 'label': 'Iterator',
                'target_association': f'{body_k};{exit_k};',
                'assignee_task_id': body_k,
                'module': mod, 'bo': bob,
            })
            tasks.append({'key': body_k, 'type': '12', 'label': 'Iter Body'})
            tasks.append({'key': exit_k, 'type': '12', 'label': 'Iter Exit'})
        elif code == '40':
            vname = rest.strip() or 'VAR1'
            tasks.append({
                'key': next_key('var'), 'type': '40', 'label': vname,
                'module': mod, 'bo': bob,
            })
        elif code == '41':
            vname = rest.strip().split()[0] if rest else 'VAR1'
            # Find prior type 40 with that label
            trgt = '0'
            for prev in reversed(tasks):
                if prev.get('type') == '40' and (
                    prev.get('label') == vname or not rest
                ):
                    trgt = prev['key']
                    break
            tasks.append({
                'key': next_key('asg'), 'type': '41', 'label': f'Assign {vname}',
                'trgt_task_id': trgt, 'src_task_id': '0',
            })
        else:
            raise ValueError(f'Unhandled type {code} for verb {verb}')

    if not has_end:
        tasks.append({'key': 'end', 'type': '9', 'label': 'End'})

    wf_name = name or f'{bob} - Synchronous - {event or "Generated"}'
    return {
        'header': {
            'name': wf_name,
            'module': mod,
            'bo': bob,
            'event_name': event or event_name or '',
            'description': f'Generated from NL: {text[:200]}',
            'object_label_name': 'In Progress 0.0',
        },
        'tasks': tasks,
    }
