"""High-level build entrypoints for om_gen."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from om_gen.ir import EdgeIR, HeaderIR, TaskIR, WorkflowIR
from om_gen.nl_recipe import nl_to_recipe
from om_gen.pack_om import pack_om_zip
from om_gen.parse_recipe import load_recipe_file, recipe_to_ir
from om_gen.validate import validate_ir


def build_from_ir(ir: WorkflowIR, out_path: Optional[str] = None) -> Union[bytes, str]:
    validate_ir(ir)
    return pack_om_zip(ir, out_path=out_path)


def build_from_recipe(recipe: Dict[str, Any], out_path: Optional[str] = None) -> Union[bytes, str]:
    ir = recipe_to_ir(recipe)
    return build_from_ir(ir, out_path=out_path)


def build_from_recipe_file(path: str, out_path: Optional[str] = None) -> Union[bytes, str]:
    return build_from_recipe(load_recipe_file(path), out_path=out_path)


def build_from_nl(
    prompt: str,
    out_path: Optional[str] = None,
    *,
    name: str = '',
    module: str = '',
    bo: str = '',
    event_name: str = '',
) -> Union[bytes, str]:
    recipe = nl_to_recipe(
        prompt, name=name, module=module, bo=bo, event_name=event_name,
    )
    return build_from_recipe(recipe, out_path=out_path)


def minimal_start_end_ir(
    name: str = 'cst om_gen Minimal Start End',
    module: str = 'Location',
    bo: str = 'triBuilding',
    event_name: str = 'Pre-Create',
) -> WorkflowIR:
    return WorkflowIR(
        header=HeaderIR(
            name=name, module=module, bo=bo, event_name=event_name,
            description='Minimal Start→End smoke workflow',
        ),
        tasks=[
            TaskIR(key='start', type='1', label='Start'),
            TaskIR(key='end', type='9', label='End'),
        ],
        edges=[EdgeIR(from_key='start', to_key='end')],
    )
