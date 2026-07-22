"""Pack flat OM zip: AllObjects + ObjectLabels + Workflow XML."""

from __future__ import annotations

import io
import os
import zipfile
from typing import Dict, Optional, Union

from om_gen import OBJECT_LABEL_FIXTURES
from om_gen.emit_allobjects import emit_allobjects_xml
from om_gen.emit_workflow import emit_workflow_xml, workflow_filename
from om_gen.ir import WorkflowIR

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load_fixtures() -> Dict[str, bytes]:
    out: Dict[str, bytes] = {}
    for name in OBJECT_LABEL_FIXTURES:
        path = os.path.join(_FIXTURES_DIR, name)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f'Missing ObjectLabel fixture: {path}. '
                'Copy ObjectLabel_*.xml from a TRIRIGA OM export into om_gen/fixtures/.'
            )
        with open(path, 'rb') as f:
            out[name] = f.read()
    return out


def pack_om_zip(ir: WorkflowIR, out_path: Optional[str] = None) -> Union[bytes, str]:
    """Build a flat OM zip. If out_path given, write and return path; else return bytes."""
    wf_xml = emit_workflow_xml(ir)
    all_xml = emit_allobjects_xml(ir)
    fixtures = _load_fixtures()
    wf_name = workflow_filename(ir)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # Flat members only — no directories
        zf.writestr('AllObjects.xml', all_xml.encode('utf-8'))
        for fname, data in fixtures.items():
            zf.writestr(fname, data)
        zf.writestr(wf_name, wf_xml.encode('utf-8'))

    data = buf.getvalue()
    # Sanity: no path separators in member names
    with zipfile.ZipFile(io.BytesIO(data), 'r') as zf:
        for info in zf.infolist():
            if '/' in info.filename or '\\' in info.filename:
                raise RuntimeError(f'Non-flat zip member: {info.filename}')

    if out_path:
        with open(out_path, 'wb') as f:
            f.write(data)
        return out_path
    return data
