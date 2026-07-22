# OM Gen — Per-Type Task Dictionary

Corpus: 158 `Workflow_*.xml` across `wf_xml_samples_variety/`, `Land_OnChange_RPIM_Status_Ind/`,
`WF_100Plus_XML_withObjectLabel/`, `WF_Variety_XML_wObjectLabel/`.

Machine-readable source of truth: [`om_gen/dictionary.py`](../om_gen/dictionary.py).

## Shared Task scaffolding

**Attributes (always):** `Id`, `Type`, `FilterOperator=10`, `RecurrenceId=0`, `MapId`, `SRCTaskId`,
`TRGTTaskId`, `AssigneeTaskId=0`, `SortCount=1`, `UseMap=1`, `LockUser=0`, `AssignToFlag=1`,
`EstEndInDays/Hrs/Mins=0`, `DateContext=0`, `ServiceContext=1`.

**Children (always emit, often empty):** `TaskLabel`, `EventName`, `Description`, `DeleteSection`,
`SumSection`, `SumField`, `FilterSection`, `FilterField`, `FilterValue`, `ServiceAssociation`,
`TargetAssociation`, `TransactionType=0`, `Status=0`, `ParametersMapId=-1`, `FormulaRecalc=0`,
`Module`, `BO`, `AssignToUserMod/BO/User`, `TaskRefs`.

**WFSteps:** one `{Id, Type, ParId}` per Task. Start `ParId=-1`. Control-flow edges come from ParId.

## Per-type summary

| Type | Name | Default EventName | Required variants | Notes |
|------|------|-------------------|-------------------|-------|
| 1 | Start | (header trigger) | Condition; optional Parameters | Id often 0 |
| 9 | End | "" | — | Terminal |
| 12 | Junction | "" | — | Invisible |
| 14 | Switch | `0=true;1=false;` | Condition + TargetAssociation | TA=`trueId;falseId;` |
| 20 | Loop | "" | — | TRGT → body |
| 21 | Break | `0=true;1=false;` | TargetAssociation; optional Condition | |
| 22 | Query | "" | FilterBo* | Query objects must exist in env |
| 23 | Modify Metadata | "" | GUIMappings | |
| 24 | Iterator | "" | TargetAssociation `body;exit` | AssigneeTaskId=body |
| 25 | Get Temp | "" | TaskRefs From | |
| 26 | Save Permanent | "" | TaskRefs From | |
| 27 | Create | `triCreate` | ObjMappings; MapId=first | |
| 28 | Modify | **`Append`** | ObjMappings; MapId=first; 2 TaskRefs | |
| 29 | Retrieve | **`GETLIST`** | TaskRefs; optional TA assoc | |
| 30 | Associate | Associate\|De-Associate | ServiceAssociation; 2 TaskRefs | |
| 31 | Trigger Action | (action name) | TaskRefs | |
| 38 | Call Workflow | "" | FilterBo=callee Name | |
| 40 | Variable Def | "" | TaskLabel=var name | |
| 41 | Variable Assign | "" | TRGTTaskId→40 | |

## ObjMapping types

| Type | Shape |
|------|-------|
| 10 | Field←field (`SrcFld` + `TrgtFld`) |
| 40 | Literal `FldVal` → `TrgtFld` |
| 80 | Formula `FldVal` → `TrgtFld` |
| 90 | Special FldVal → TrgtFld |

**Coupling:** `Task.@MapId == ObjMappings/ObjMapping[1]/Id` whenever mappings exist.

## ID integrity

See `ID_RULES` in `om_gen/dictionary.py`. Validator enforces unique Task Ids, WFStep coverage,
MapId coupling, TaskRef/PDataId membership, Type 41→40, Iterator AssigneeTaskId.
