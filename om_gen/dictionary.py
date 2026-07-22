"""Per-type emitter dictionary derived from corpus analysis (158 Workflow_*.xml).

Corpora: wf_xml_samples_variety/, Land_OnChange_RPIM_Status_Ind/,
WF_100Plus_XML_withObjectLabel/, WF_Variety_XML_wObjectLabel/.

Emitters MUST emit every invariant child tag (even when empty) and the
variant blocks required when the IR supplies the corresponding data.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional

# Shared Task attribute defaults (always present on corpus Tasks).
TASK_ATTR_DEFAULTS: Dict[str, str] = {
    'FilterOperator': '10',
    'RecurrenceId': '0',
    'MapId': '-1',
    'SRCTaskId': '-1',
    'TRGTTaskId': '-1',
    'AssigneeTaskId': '0',
    'SortCount': '1',
    'UseMap': '1',
    'LockUser': '0',
    'AssignToFlag': '1',
    'EstEndInDays': '0',
    'EstEndInHrs': '0',
    'EstEndInMins': '0',
    'DateContext': '0',
    'ServiceContext': '1',
}

# Child tags always present (>=99%) across core types — emit even if empty.
SHARED_CHILD_TAGS: List[str] = [
    'TaskLabel',
    'EventName',
    'Description',
    'DeleteSection',
    'SumSection',
    'SumField',
    'FilterSection',
    'FilterField',
    'FilterValue',
    'ServiceAssociation',
    'TargetAssociation',
    'TransactionType',
    'Status',
    'ParametersMapId',
    'FormulaRecalc',
    'Module',
    'BO',
    'AssignToUserMod',
    'AssignToUserBO',
    'AssignToUser',
    'TaskRefs',
]

# Scalar children that use plain text (not CDATA-required for engine ingest).
# Emitters wrap most values in CDATA to match IBM export style.
CDATA_CHILDREN: FrozenSet[str] = frozenset(SHARED_CHILD_TAGS) | frozenset({
    'AssociatedModule', 'AssociatedBO',
    'FilterBo', 'FilterBoBO', 'FilterModule', 'FilterClass',
})

# Header defaults from corpus.
HEADER_DEFAULTS: Dict[str, str] = {
    'Type': '0',
    'WfStatus': '10',
    'IgnoreModuleLevel': '0',
    'InstanceData': '0',
    'LockRecord': '0',
    'Modifier': '0',
}


def _base(
    *,
    name: str,
    default_event: str = '',
    always_extra: Optional[List[str]] = None,
    variants: Optional[List[str]] = None,
    requires_objmappings: bool = False,
    requires_condition: bool = False,
    requires_target_assoc: bool = False,
    requires_filter_bo: bool = False,
    dual_taskrefs: bool = False,
    notes: str = '',
) -> Dict[str, Any]:
    return {
        'name': name,
        'default_event_name': default_event,
        'always_extra_children': always_extra or [],
        'variant_blocks': variants or [],
        'requires_objmappings': requires_objmappings,
        'requires_condition': requires_condition,
        'requires_target_assoc': requires_target_assoc,
        'requires_filter_bo': requires_filter_bo,
        'dual_taskrefs': dual_taskrefs,
        'notes': notes,
    }


# Corpus-backed per-type inventory.
TASK_TYPES: Dict[str, Dict[str, Any]] = {
    '1': _base(
        name='Start',
        always_extra=['AssociatedModule', 'AssociatedBO', 'Condition'],
        variants=['Parameters'],
        requires_condition=True,
        notes='EventName mirrors Header.EventName. Id often 0. WFStep ParId=-1.',
    ),
    '9': _base(name='End', notes='Terminal. MapId=-1. Empty Module/BO.'),
    '12': _base(name='Junction', notes='Invisible routing; edges via WFSteps only.'),
    '14': _base(
        name='Switch',
        default_event='0=true;1=false;',
        always_extra=['Condition'],
        requires_condition=True,
        requires_target_assoc=True,
        notes='TargetAssociation="trueId;falseId;". EventName indices align 1:1.',
    ),
    '20': _base(name='Loop', notes='TRGTTaskId → body; cycle via WFSteps.'),
    '21': _base(
        name='Break',
        default_event='0=true;1=false;',
        variants=['Condition'],
        requires_target_assoc=True,
        notes='TargetAssociation two ids (continue vs exit).',
    ),
    '22': _base(
        name='Query',
        always_extra=['FilterBo', 'FilterBoBO', 'FilterModule'],
        variants=['FilterClass', 'TaskFilters'],
        requires_filter_bo=True,
        dual_taskrefs=True,
        notes='FilterBo=query name. Query Type-4 not packaged by om_gen.',
    ),
    '23': _base(
        name='Modify Metadata',
        always_extra=['AssociatedModule', 'AssociatedBO'],
        variants=['GUIMappings'],
        notes='GUIMappings/GUIMapping PropType/PropVal/Tab/Section/Field.',
    ),
    '24': _base(
        name='Iterator',
        requires_target_assoc=True,
        notes='TargetAssociation="bodyId;exitId;". AssigneeTaskId == bodyId.',
    ),
    '25': _base(name='Get Temp Record', notes='One From TaskRef; Module/BO = temp type.'),
    '26': _base(name='Save Permanent', notes='From TaskRef = temp/created token.'),
    '27': _base(
        name='Create Record',
        default_event='triCreate',
        always_extra=['AssociatedModule', 'AssociatedBO', 'ObjMappings'],
        requires_objmappings=True,
        notes='MapId == first ObjMapping/@Id. EventName=create action.',
    ),
    '28': _base(
        name='Modify Records',
        default_event='Append',
        always_extra=['ObjMappings'],
        requires_objmappings=True,
        dual_taskrefs=True,
        notes='EventName always Append in corpus. MapId == first ObjMapping/@Id.',
    ),
    '29': _base(
        name='Retrieve Records',
        default_event='GETLIST',
        variants=['FilterClass', 'TaskFilters', 'ObjMappings'],
        dual_taskrefs=True,
        notes='TargetAssociation may hold association name when traversing.',
    ),
    '30': _base(
        name='Associate',
        default_event='Associate',
        dual_taskrefs=True,
        notes='EventName Associate|De-Associate. ServiceAssociation=assoc name.',
    ),
    '31': _base(
        name='Trigger Action',
        notes='EventName=state action (triRemove, NOTIFY, …). TaskRefs 1–2.',
    ),
    '38': _base(
        name='Call Workflow',
        always_extra=['FilterBo', 'FilterBoBO', 'FilterModule'],
        variants=['FilterClass', 'Parameters'],
        requires_filter_bo=True,
        notes='FilterBo=callee workflow Name. Optional Parameters; ParametersMapId=Task.Id.',
    ),
    '40': _base(
        name='Variable Definition',
        notes='TaskLabel=variable name. Module/BO=typed binding. MapId=-1.',
    ),
    '41': _base(
        name='Variable Assignment',
        always_extra=['AssociatedBO'],
        variants=['Condition'],
        notes='TRGTTaskId → Type 40 Id. SRCTaskId → source record task.',
    ),
}

# ObjMapping @Type shapes (empirical).
OBJMAPPING_TYPES: Dict[str, str] = {
    '10': 'Field←field copy (SrcFld + TrgtFld)',
    '40': 'Literal FldVal → TrgtFld',
    '80': 'Formula FldVal → TrgtFld (e.g. AddDay(...), concat expressions)',
    '90': 'Special / classification-style FldVal → TrgtFld',
    '70': 'Source token / special mapping',
    '6': 'Value-only / flag',
    '5': 'Value-only / flag',
    '20': 'Sparse / special',
    '30': 'Sparse / special',
    '60': 'Sparse / special',
}

# ID integrity rules enforced by validate.py.
ID_RULES: List[str] = [
    'Every Task.Id is unique within the workflow.',
    'Every Task has a matching WFStep with Id=Task.Id, Type=Task.Type, ParId=predecessor.',
    'Start WFStep ParId=-1.',
    'When ObjMappings present: Task.MapId == first ObjMapping/@Id.',
    'TaskRef RefTaskId and Condition Param PDataId ∈ {task ids ∪ {0, -1}}.',
    'Type 41 TRGTTaskId must reference a Type 40 task Id.',
    'Type 24 AssigneeTaskId must equal the first TargetAssociation id (body).',
    'Type 14/21 TargetAssociation must list two semicolon-separated task ids.',
]


def type_info(type_code: str) -> Dict[str, Any]:
    info = TASK_TYPES.get(str(type_code))
    if not info:
        raise KeyError(f'Unsupported task type: {type_code}')
    return info


def supported_type_codes() -> List[str]:
    return sorted(TASK_TYPES.keys(), key=int)
