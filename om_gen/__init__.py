"""OM workflow generator — corpus-driven IR → flat TRIRIGA Object Migration zip."""

from __future__ import annotations

SUPPORTED_TASK_TYPES = frozenset({
    '1', '9', '12', '14', '20', '21', '22', '23', '24', '25', '26',
    '27', '28', '29', '30', '31', '38', '40', '41',
})

OBJECT_LABEL_FIXTURES = (
    'ObjectLabel_b037d8e4859a408ee21b48cc5787f6f3d1fa81c5.xml',  # Root 0.0
    'ObjectLabel_cfb478ea4b3c19a2077f1d82f3fb196c5534c0db.xml',  # In Progress 0.0
)

DEFAULT_OBJECT_LABEL = 'In Progress 0.0'

TYPE_NAMES = {
    '1': 'Start',
    '9': 'End',
    '12': 'Junction',
    '14': 'Switch',
    '20': 'Loop',
    '21': 'Break',
    '22': 'Query',
    '23': 'Modify Metadata',
    '24': 'Iterator',
    '25': 'Get Temp Record',
    '26': 'Save Permanent',
    '27': 'Create Record',
    '28': 'Modify Records',
    '29': 'Retrieve Records',
    '30': 'Associate',
    '31': 'Trigger Action',
    '38': 'Call Workflow',
    '40': 'Variable Definition',
    '41': 'Variable Assignment',
}
