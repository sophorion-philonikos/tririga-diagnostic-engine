# TRIRIGA Diagnostic Engine — Runbook

Central command reference for setup, CLI, web UI, and tests.

## Environment setup

```bash
cd /path/to/tririga-diagnostic-engine
pip install -r requirements.txt
```

Python **3.9+** required. Credentials (live mode only) come from environment variables — see the table in [`README.md`](README.md). Nothing sensitive is stored in source.

Optional offline defaults:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `TRIRIGA_OM_PACKAGE` | `Land_OnChange_RPIM_Status_Ind.zip` | OM Package for offline CLI |
| `TRIRIGA_LOCAL_LOG` | `server (23).log` | Local server log for offline CLI |

## Entry points

### Live CLI (Oracle + SSH when configured)

```bash
python3 main.py
```

### Offline CLI (no DB/SSH)

```bash
python3 main.py --offline
```

Uses the bundled OM Package and local log (or paths from the env vars above).

### Web UI

```bash
python3 main.py --web
```

Custom port:

```bash
python3 main.py --web --port 8000
```

Then open `http://127.0.0.1:<port>/` in a browser.

#### Web flow

1. Drag/drop or browse: `.zip` OM Package, `.log` server log (optional), `.xml` / `.txt` workflow export(s).
2. Click **Visualize** — map loads in the workspace iframe; Analysis Dock opens on the right.
3. Click tasks on the map → Focus Context updates (selection sync via `postMessage`).
4. Run **What-If** from the dock (typed query or suggestion chips) → **Simulate**.
5. Use viewer modes: Topology / Live Trace / What-If / Diff; **Isolate** dims outside a task neighborhood.
6. **Open map in new tab** for a full-window viewer; **Hide dock** collapses the analysis column.

#### Workflow Generator page

From the diagnostic header click **Workflow Generator →**, or open `http://127.0.0.1:<port>/generator.html`.

1. Enter **Workflow Name**, **Module**, **BO**, and a description — either constrained NL (`On Module::BO Event: …`) or plain-English intent (see `python3 -m om_gen nl-help`).
2. Click **Parse & Preview** — JSON IR appears and a **dedicated** Dagre map shows Start → tasks → End (separate from the diagnostic viewer).
3. If the map does not match intent, revise the description and parse again.
4. Click **Export OM Zip** — downloads a flat package (`AllObjects.xml` + `ObjectLabel_*.xml` + `Workflow_*.xml`).
5. Import in TRIRIGA Object Migration. If ObjectLabel import fails, swap fixtures per [`om_gen/IMPORT.md`](om_gen/IMPORT.md).

**Dual path:** prompts matching `On Module::BO Event:` use constrained grammar; otherwise the intent layer uses **slot extraction** (paraphrases OK — e.g. *modifies…by adding the letter Z when the user clicks save*, *gets building records…greater than 0…append 123GG*). Form Name/Module/BO win when filled. Query tasks need an existing Query object name (`FilterBo`) — naming only a BO fails with guidance to provide the name or say *retrieve*. Bare “result count > 0” without a Query/Retrieve target fails. Unknown field/event phrases fail closed.

**Add synonyms:** lowercase phrase keys in [`om_gen/module_bo_synonyms.py`](om_gen/module_bo_synonyms.py) (`EVENT_SYNONYMS`, `MODULE_BO_PHRASES`) and [`om_gen/field_synonyms.py`](om_gen/field_synonyms.py) (`_GLOBAL` / `_BY_BO`). Longest match wins; do not invent unresolved phrases at parse time.

## Interactive CLI commands (after prompt)

Typical prompts once the engine is loaded:

| Intent | Example |
| ------ | ------- |
| Build map | `visualize` |
| Task deep-dive | `explain task 333449` |
| Workflow summary | `what does this workflow do` |
| Log correlation | `scan log` / `what just failed` |
| Live instance | `trace live execution` |
| What-If | natural-language scenarios naming switches/tasks/fields |

Exact NLP routing lives in `cli/router.py` / `cli/commands/`.

## OM workflow generator (`om_gen`)

Isolated package: JSON recipe, constrained NL, or plain-English intent → flat TRIRIGA OM `.zip`.
Does **not** change diagnostic visualize/simulate/map contracts.

```bash
# Minimal Start→End smoke zip
python3 -m om_gen minimal --out /tmp/minimal.zip

# From JSON recipe
python3 -m om_gen build --recipe om_gen/examples/demo_modify.json --out /tmp/demo.zip

# From constrained NL
python3 -m om_gen nl --prompt 'On Location::triBuilding triSave: modify set triNameTX = triNameTX + "Z"' --out /tmp/nl.zip

# From intent paraphrase (slots — wording may vary)
python3 -m om_gen nl --prompt 'On save for a building, append Z to the name' \
  --name 'triBuilding - Synchronous - Append Z to Name' --module Location --bo triBuilding --out /tmp/intent.zip

python3 -m om_gen nl --prompt 'Create a workflow that modifies the building record name field by adding the letter Z when the user clicks save' \
  --module Location --bo triBuilding --out /tmp/intent2.zip

python3 -m om_gen types
python3 -m om_gen nl-help
```

Per-type emitter dictionary: [`docs/om_gen_task_dictionary.md`](docs/om_gen_task_dictionary.md).

**Limits (v1):** Query/Call name objects that must already exist (no Query Type-4 packaging). Freeform LLM planning is out of scope. Extend phrase catalogs in `om_gen/module_bo_synonyms.py` and `om_gen/field_synonyms.py`.

## Tests

Run the full unit suite:

```bash
python3 -m unittest discover -s tests -v
```

Targeted (examples):

```bash
python3 -m unittest tests.test_viz_shapes tests.test_viz_node_parity tests.test_viz_svg_escape -v
python3 -m unittest tests.test_om_gen tests.test_om_gen_intent -v
python3 -m unittest tests.test_runbook -v
```

## Architecture notes (web map)

- Layout is computed once by dagre-d3; pan/zoom only transforms the SVG inner `<g>`.
- What-If / Live / Diff / Isolate apply **class toggles** on existing DOM nodes (no re-render).
- Expensive CSS filters are avoided; glows use outline/stroke. During zoom, `#svg-canvas.is-zooming` disables outlines/animations.
