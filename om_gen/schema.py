"""JSON recipe schema helpers and type constants."""

from __future__ import annotations

from om_gen import SUPPORTED_TASK_TYPES, TYPE_NAMES
from om_gen.dictionary import TASK_TYPES

# Types allowed in recipes (must match SUPPORTED_TASK_TYPES).
ALLOWED_TYPES = SUPPORTED_TASK_TYPES

NL_VERBS = {
    'start': '1',
    'end': '9',
    'junction': '12',
    'switch': '14',
    'loop': '20',
    'break': '21',
    'query': '22',
    'metadata': '23',
    'modify metadata': '23',
    'iter': '24',
    'iterator': '24',
    'temp': '25',
    'get temp': '25',
    'get temp record': '25',
    'save': '26',
    'save permanent': '26',
    'create': '27',
    'create record': '27',
    'modify': '28',
    'modify records': '28',
    'retrieve': '29',
    'associate': '30',
    'deassociate': '30',
    'de-associate': '30',
    'trigger': '31',
    'trigger action': '31',
    'call': '38',
    'call workflow': '38',
    'define var': '40',
    'define variable': '40',
    'assign var': '41',
    'assign variable': '41',
}


def type_label(code: str) -> str:
    return TYPE_NAMES.get(str(code), f'Type {code}')


def default_event_for(type_code: str) -> str:
    info = TASK_TYPES.get(str(type_code), {})
    return str(info.get('default_event_name') or '')
