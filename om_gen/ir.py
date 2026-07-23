"""Intermediate representation for generated TRIRIGA workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MappingIR:
    """One ObjMapping row (Create/Modify)."""
    field: str
    value: str = ''
    src_field: str = ''
    map_type: str = ''  # auto: 10 if src_field, 80 if formula-like, else 40
    trgt_module: str = ''
    trgt_bo: str = ''
    trgt_tab: str = 'General'
    trgt_sec: str = 'General'
    src_module: str = ''
    src_bo: str = ''
    src_tab: str = ''
    src_sec: str = ''


@dataclass
class TaskRefIR:
    ref_task_id: str = '0'  # '0' = trigger/start record; or task id / key resolved later
    ref_type: str = '0'
    use_type: str = '1'  # 1=From, 2=Filter
    module: str = ''
    bo: str = ''
    ref_sec: str = ''
    ref_field: str = ''
    ref_assoc: str = ''


@dataclass
class ConditionParamIR:
    p_id: str = '0'
    p_type: str = 'field'  # field | item
    p_data_id: str = '0'
    p_field: str = ''
    p_section: str = ''
    p_module: str = ''
    p_bo: str = ''
    p_item: str = ''  # e.g. "Result Count" when p_type=item


@dataclass
class ConditionIR:
    expression: str = ''
    params: List[ConditionParamIR] = field(default_factory=list)


@dataclass
class GuiMappingIR:
    prop_type: str = '1'
    prop_val: str = 'true'
    tab: str = ''
    section: str = ''
    field: str = ''
    bo: str = ''
    bo_module: str = ''
    gui: str = ''
    module: str = ''


@dataclass
class TaskIR:
    key: str
    type: str
    label: str = ''
    event_name: str = ''
    description: str = ''
    module: str = ''
    bo: str = ''
    associated_module: str = ''
    associated_bo: str = ''
    filter_bo: str = ''
    filter_bo_bo: str = ''
    filter_module: str = ''
    filter_class: str = ''
    target_association: str = ''
    service_association: str = ''
    formula_recalc: str = '0'
    use_map: str = '1'
    map_id: str = '-1'
    src_task_id: str = '-1'
    trgt_task_id: str = '-1'
    assignee_task_id: str = '0'
    mappings: List[MappingIR] = field(default_factory=list)
    refs: List[TaskRefIR] = field(default_factory=list)
    condition: Optional[ConditionIR] = None
    gui_mappings: List[GuiMappingIR] = field(default_factory=list)
    # Resolved numeric id (filled by allocate_ids)
    id: str = ''
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeIR:
    """Control-flow edge: from_key → to_key (becomes WFStep ParId linkage)."""
    from_key: str
    to_key: str


@dataclass
class HeaderIR:
    name: str
    module: str
    bo: str
    event_name: str = ''
    description: str = ''
    object_label_name: str = 'In Progress 0.0'
    header_type: str = '0'
    wf_status: str = '10'
    instance_data: str = '0'
    associated_module: str = ''
    associated_bo: str = ''
    updated_by: str = 'om_gen'
    association_name: str = ''


@dataclass
class WorkflowIR:
    header: HeaderIR
    tasks: List[TaskIR]
    edges: List[EdgeIR] = field(default_factory=list)

    def task_by_key(self, key: str) -> Optional[TaskIR]:
        for t in self.tasks:
            if t.key == key:
                return t
        return None
