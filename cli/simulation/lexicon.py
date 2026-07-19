"""What-If simulation internals — split for reviewability."""
from __future__ import annotations

import re
import difflib
from collections import defaultdict, deque
from dataclasses import dataclass, field

import networkx as nx

from cli import graph_utils
from cli.knowledge import type_display_name

__all__ = [
    '_TRUE_WORDS',
    '_FALSE_WORDS',
    '_NEGATORS',
    'TRIRIGA_DOMAIN_LEXICON',
    'STATE_CODE_MAP',
]

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

