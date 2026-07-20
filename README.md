# TRIRIGA Diagnostic Engine

A diagnostic suite that parses, analyzes, and visualizes complex IBM TRIRIGA
workflow XML files (delivered as OM Packages). It builds a directed graph of every
workflow task, translates task logic into plain English, correlates live server
logs and Oracle records, and renders an interactive HTML blueprint of the
execution topology.

## Features

- **OM Package parsing** — extracts workflows and queries directly from a `.zip`
  OM Package and builds one `networkx.DiGraph` per workflow.
- **Structured payload extraction** — `<ObjMapping>` blocks are parsed as ordered,
  self-contained records so target/source field mappings stay correctly paired.
- **Execution-path tracing** — enumerates logical routes through the workflow with
  bounded, cycle-aware traversal (no combinatorial blow-up on large workflows).
- **Live correlation** — optional SSH log scanning and Oracle payload lookups.
- **Interactive visualization** — generates a self-contained HTML map (Dagre + D3)
  with a diagnostics side panel.

## Requirements

- Python 3.9+
- Dependencies in [`requirements.txt`](requirements.txt):

```bash
pip install -r requirements.txt
```

## Configuration

All credentials and environment-specific settings are read from environment
variables at runtime. **Nothing sensitive is stored in source.**

| Variable                | Required        | Description                                  |
| ----------------------- | --------------- | -------------------------------------------- |
| `TRIRIGA_DB_USER`       | LIVE mode only  | Oracle username                              |
| `TRIRIGA_DB_PASS`       | LIVE mode only  | Oracle password                              |
| `TRIRIGA_DB_DSN`        | LIVE mode only  | Oracle DSN, e.g. `host:port/service`         |
| `TRIRIGA_SSH_HOST`      | LIVE log scans  | TRIRIGA app server hostname                  |
| `TRIRIGA_SSH_USER`      | LIVE log scans  | SSH username                                 |
| `TRIRIGA_SSH_LOG_PATH`  | optional        | Remote log path (default `/usr/local/tririga/log/server.log`) |
| `TRIRIGA_OM_PACKAGE`    | optional        | OM Package to load (default `Land_OnChange_RPIM_Status_Ind.zip`) |
| `TRIRIGA_LOCAL_LOG`     | optional        | Local log file for `--offline` (default `server (23).log`) |

Example:

```bash
export TRIRIGA_DB_USER=your_user
export TRIRIGA_DB_PASS=your_password
export TRIRIGA_DB_DSN=host:port/service
export TRIRIGA_SSH_HOST=app-server.example.com
export TRIRIGA_SSH_USER=your_ssh_user
```

## Usage

For the full command list (web, offline, ports, tests), see [`RUNBOOK.md`](RUNBOOK.md).

Live mode (Oracle + SSH active):

```bash
python3 main.py
```

Offline mode (uses the bundled OM Package and a local log file, no DB/SSH):

```bash
python3 main.py --offline
```

Web UI:

```bash
python3 main.py --web
```

Once the chat prompt appears, try:

- `visualize` — generate an interactive blueprint map
- `explain task 333449` — deep logic analysis of a specific task
- `what does this workflow do` — auto-generated purpose summary with execution paths
- `scan log` / `what just failed` — correlate recent log errors to loaded tasks
- `trace live execution` — chronological trace of a real workflow instance

## Project layout

```
core/            Graph-building engine and Oracle integration
cli/             NLP router, formatters, visualizer, HTML template
integrations/    SSH log client
main.py          Entry point / interactive loop
```
