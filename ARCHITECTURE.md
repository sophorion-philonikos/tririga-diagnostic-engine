# Architecture

TRIRIGA Diagnostic Engine — offline/live workflow diagnostics.

## Packages

| Path | Responsibility |
|------|----------------|
| `core/` | XML/OM ingest → `networkx` graphs; Oracle live lookups |
| `cli/graph_utils.py` | Visibility, container nesting, branch labels (single topology source) |
| `cli/visualizer.py` + `cli/templates/viewer.html` | Dagre compound HTML map |
| `cli/simulation/` | What-If NL parse, tokens, starvation, impact trees |
| `cli/router.py` + `cli/intents.py` | NLP chat dispatch |
| `cli/inventory.py` / `cli/relations.py` / `cli/knowledge.py` | Inventory, routes, glossary |
| `web/` | Local upload UI + `/api/visualize`, `/api/map/<session>`, `/api/simulate`; Generator page `/generator.html` + `/api/generator/*` |
| `om_gen/` | Constrained NL/JSON IR → flat OM zip (isolated from diagnostic map) |
| `integrations/` | SSH log client |

## Hard rules (layout)

- **Never put edges on compound parents** (`c_*` cluster wrappers). Real Iter/Loop ids stay leaf nodes; edges touch leaves only. Violating this crashes dagre (`setting 'rank'`).
- Container parent links among Iter/Loop must form a **DAG** (Loop outer over Iter when mutual cycle membership).
- Switch branch labels: resolve through **invisible** TargetAssociation anchors only (no dual-TRUE via diamond merge).

## Data flow

```
Upload/OM/XML → TririgaHybridEngine.graphs
             → WorkflowVisualizer.build_html (nodes/edges/payloads)
             → viewer.html (post-render: skirts, loop-back merge, forks)
             → What-If via simulation.run_simulation
```

## Web sessions

`POST /api/visualize` returns `session_id` + `map_url` (HTML is **not** stuffed into JSON).
`GET /api/map/<session_id>` serves the map. `POST /api/simulate` takes `{query, session_id}`.
