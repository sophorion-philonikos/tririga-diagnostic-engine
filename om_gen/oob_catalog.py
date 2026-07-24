"""Authoritative Module→BO catalog from tririga_modules_bos.json.

Used by Generator cascading dropdowns, /api/generator/catalog, and intent helpers.
Do not invent Modules/BOs absent from the JSON. Free-typed custom values remain
allowed at the UI/API layer for parse/compile.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict, List, Optional

# Repo root: …/tririga-diagnostic-engine/tririga_modules_bos.json
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CATALOG_PATH = os.path.join(_REPO_ROOT, 'tririga_modules_bos.json')


@lru_cache(maxsize=1)
def load_modules_bos(path: Optional[str] = None) -> Dict[str, List[str]]:
    """Load {Module: [BO, …]} from JSON. Cached. Path defaults to repo root file."""
    catalog_path = path or DEFAULT_CATALOG_PATH
    with open(catalog_path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f'Catalog root must be an object: {catalog_path}')
    out: Dict[str, List[str]] = {}
    for mod, bos in data.items():
        if not isinstance(mod, str) or not isinstance(bos, list):
            continue
        out[mod] = [str(b) for b in bos if b is not None and str(b).strip()]
    return out


def list_modules(path: Optional[str] = None) -> List[str]:
    return sorted(load_modules_bos(path).keys())


def list_bos(module: str, path: Optional[str] = None) -> List[str]:
    catalog = load_modules_bos(path)
    return list(catalog.get(module, []))


def is_known_module(module: str, path: Optional[str] = None) -> bool:
    return bool(module) and module in load_modules_bos(path)


def is_known_bo(module: str, bo: str, path: Optional[str] = None) -> bool:
    if not module or not bo:
        return False
    return bo in load_modules_bos(path).get(module, [])


def catalog_payload(path: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
    """JSON shape for GET /api/generator/catalog."""
    return {'modules': load_modules_bos(path)}


def clear_cache() -> None:
    """Test helper — clear cached catalog."""
    load_modules_bos.cache_clear()
