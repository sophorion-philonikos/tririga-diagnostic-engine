"""Local Web UI server for the TRIRIGA Diagnostic Engine.

Zero-dependency backend built on the Python standard library only
(http.server + email for multipart parsing). Uploaded files never touch
disk: they are streamed into the existing engine as in-memory objects.
"""

import io
import json
import os
import secrets
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core.engine import TririgaHybridEngine
from cli.router import TririgaNLPRouter
from cli.visualizer import WorkflowVisualizer
from cli import simulation
from cli import graph_utils

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

ALLOWED_EXTENSIONS = {'.zip', '.log', '.xml', '.txt'}

# Per-browser session store (token -> session dict). Multi-tab safe.
_session_lock = threading.Lock()
_sessions = {}


def _new_session_id():
    return secrets.token_urlsafe(18)


def _classify_upload(filename):
    """Route an uploaded file to its ingestion role purely by extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.zip':
        return 'om_package'
    if ext == '.log':
        return 'server_log'
    if ext in ('.xml', '.txt'):
        return 'workflow_xml'
    return None


def _parse_multipart(content_type, body):
    """Parse a multipart/form-data body into [(filename, bytes)] using stdlib email."""
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode('utf-8')
    message = BytesParser(policy=default_email_policy).parsebytes(header + body)
    if not message.is_multipart():
        return []

    uploads = []
    for part in message.iter_parts():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        uploads.append((os.path.basename(filename), payload))
    return uploads


def _build_sim_chips(engine, wf_name, limit=12):
    """One-click What-If prompts derived from Switch/Query/Retrieve structure."""
    if wf_name not in engine.graphs:
        return []
    graph = engine.graphs[wf_name]
    chips = []
    for nid, data in graph.nodes(data=True):
        if len(chips) >= limit:
            break
        if graph_utils.is_invisible(data):
            continue
        t = graph_utils.get_type_str(data)
        name = str(data.get('name', f'Task {nid}'))
        if t == '14':
            chips.append({
                'label': f"Force FALSE · {name[:40]}",
                'query': f"what if switch {nid} is FALSE",
            })
            if len(chips) >= limit:
                break
            chips.append({
                'label': f"Force TRUE · {name[:40]}",
                'query': f"what if switch {nid} is TRUE",
            })
        elif t in ('22', '29'):
            chips.append({
                'label': f"Zero records · {name[:40]}",
                'query': f"what if {name} returns zero records",
            })
    return chips[:limit]


def _build_sim_placeholder(chips, wf_name):
    """Placeholder text tailored to the loaded workflow's suggested queries."""
    def _short(q, n=72):
        q = (q or "").strip()
        return q if len(q) <= n else q[: n - 1] + "…"

    if chips:
        q1 = _short(chips[0].get('query', ''))
        if len(chips) > 1:
            q2 = _short(chips[1].get('query', ''), 56)
            return f'Try: "{q1}" or "{q2}"'
        return f'Try: "{q1}"'
    short = (wf_name or "this workflow").split(" - ")[-1][:48]
    return f'Try a What-If on {short} (e.g. force a Switch TRUE/FALSE, or zero records)'


def _workflow_fingerprint(engine, wf_name):
    """Node id set for Diff mode across two loaded workflows."""
    if wf_name not in engine.graphs:
        return []
    g = engine.graphs[wf_name]
    return sorted(
        str(n) for n, d in g.nodes(data=True)
        if not (graph_utils.is_invisible(d) and g.out_degree(n) > 0)
    )


def process_visualization_request(uploads):
    """Core ingestion + trace + render pipeline, fully in-memory.

    ``uploads`` is a list of (filename, bytes). Returns a JSON-serializable dict
    or raises ValueError with a user-facing message.
    """
    om_packages, workflow_xmls, server_logs, rejected = [], [], [], []
    for filename, data in uploads:
        role = _classify_upload(filename)
        if role == 'om_package':
            om_packages.append((filename, data))
        elif role == 'server_log':
            server_logs.append((filename, data))
        elif role == 'workflow_xml':
            workflow_xmls.append((filename, data))
        else:
            rejected.append(filename)

    if rejected:
        raise ValueError(
            f"Unsupported file type(s): {', '.join(rejected)}. "
            "Allowed: .zip (OM Package), .log (server log), .xml/.txt (workflow)."
        )
    if not om_packages and not workflow_xmls:
        raise ValueError("Upload at least one OM Package (.zip) or workflow XML/TXT file.")
    if len(server_logs) > 1:
        raise ValueError("Upload at most one server log (.log) file.")

    engine = TririgaHybridEngine(None, None, None, offline_mode=True)

    load_failures = []
    for filename, data in om_packages:
        if not engine.load_om_package(io.BytesIO(data)):
            load_failures.append(filename)
    for filename, data in workflow_xmls:
        text = data.decode('utf-8', errors='ignore')
        if not engine.load_workflow_xml_string(text, source_label=filename):
            load_failures.append(filename)

    if not engine.loaded_workflow_names:
        detail = f" Failed file(s): {', '.join(load_failures)}." if load_failures else ""
        raise ValueError("No valid TRIRIGA workflows could be parsed from the uploaded files." + detail)

    router = TririgaNLPRouter(engine, offline_mode=True)

    detected = []
    target_wf, target_trace, target_wfiid = None, [], None
    note = None
    log_text = None

    if server_logs:
        log_text = server_logs[0][1].decode('utf-8', errors='ignore')
        log_lines = log_text.splitlines(keepends=True)

        for wf_name in engine.loaded_workflow_names:
            wfiid, trace, _records, _counts = router.extract_execution_trace(log_lines, wf_name)
            detected.append({
                'workflow': wf_name,
                'wfiid': wfiid,
                'steps': len(trace),
            })
            if wfiid is not None:
                if target_wfiid is None or int(wfiid) > int(target_wfiid):
                    target_wf, target_trace, target_wfiid = wf_name, trace, wfiid

        if target_wf is None:
            note = ("No execution of the loaded workflow(s) was found in the uploaded log. "
                    "Rendering a static blueprint instead. Ensure TRIRIGA Workflow Logging "
                    "(Start, End, and Steps) was enabled when the log was captured.")
    else:
        detected = [{'workflow': name, 'wfiid': None, 'steps': 0} for name in engine.loaded_workflow_names]
        note = "No server log (.log) uploaded. Rendering a static blueprint with no live-trace overlay."

    if target_wf is None:
        target_wf = engine.loaded_workflow_names[0]

    live_trace_ids = [step['id'] for step in target_trace]
    visualizer = WorkflowVisualizer(engine)
    map_html = None
    viz_render_errors = []
    try:
        map_html = visualizer.build_html(target_wf, live_trace_ids=live_trace_ids)
    except Exception as exc:
        import traceback
        reasons = [f"{type(exc).__name__}: {exc}"]
        for line in reversed(traceback.format_exc().splitlines()):
            if 'File "' in line and ('cli/' in line or 'core/' in line or 'web/' in line):
                reasons.append(line.strip())
                break
        viz_render_errors = reasons
        map_html = (
            "<!DOCTYPE html><html><body style='font-family:Segoe UI,sans-serif;"
            "background:#2b2b2b;color:#ffb3b3;padding:24px;'>"
            "<h2>Visualization failed to render</h2>"
            f"<pre>{chr(10).join(reasons)}</pre></body></html>"
        )

    session_id = _new_session_id()
    fingerprints = {
        name: _workflow_fingerprint(engine, name)
        for name in engine.loaded_workflow_names
    }
    with _session_lock:
        _sessions[session_id] = {
            'engine': engine,
            'router': router,
            'workflow': target_wf,
            'trace_ids': live_trace_ids,
            'map_html': map_html,
            'log_text': log_text,
            'fingerprints': fingerprints,
        }

    trace_summary = [
        {'id': step['id'], 'name': step['name'], 'type': step['type'], 'context': step['context']}
        for step in target_trace
    ]

    # Diff vs second loaded workflow (if any): ids only for overlay.
    diff = None
    others = [n for n in engine.loaded_workflow_names if n != target_wf]
    if others:
        a = set(fingerprints.get(target_wf, []))
        b = set(fingerprints.get(others[0], []))
        diff = {
            'other_workflow': others[0],
            'added': sorted(a - b),
            'removed': sorted(b - a),
            'shared': sorted(a & b),
        }

    sim_chips = _build_sim_chips(engine, target_wf)
    return {
        'session_id': session_id,
        'map_url': f'/api/map/{session_id}',
        'workflow': target_wf,
        'wfiid': target_wfiid,
        'detected_workflows': detected,
        'trace_summary': trace_summary,
        'note': note,
        'viz_render_errors': viz_render_errors,
        'sim_chips': sim_chips,
        'sim_placeholder': _build_sim_placeholder(sim_chips, target_wf),
        'diff': diff,
        # Backward-compatible: omit huge body by default; clients should use map_url.
        'map_html': None,
    }


class DiagnosticWebHandler(BaseHTTPRequestHandler):
    server_version = "TririgaDiagnosticWeb/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode('utf-8') if isinstance(html, str) else html
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ('/', '/index.html'):
            index_path = os.path.join(STATIC_DIR, 'index.html')
            try:
                with open(index_path, 'rb') as f:
                    body = f.read()
            except FileNotFoundError:
                self._send_json(500, {'error': f'Missing UI file: {index_path}'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith('/api/map/'):
            sid = path[len('/api/map/'):].strip('/')
            with _session_lock:
                sess = _sessions.get(sid)
            if not sess or not sess.get('map_html'):
                self._send_html(404, '<html><body>Map session not found.</body></html>')
                return
            self._send_html(200, sess['map_html'])
            return

        self._send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/api/simulate':
            self._handle_simulate()
            return
        if self.path != '/api/visualize':
            self._send_json(404, {'error': 'Not found'})
            return

        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self._send_json(400, {'error': 'Expected multipart/form-data upload.'})
            return

        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json(400, {'error': 'Empty request body.'})
            return

        body = self.rfile.read(length)

        try:
            uploads = _parse_multipart(content_type, body)
            if not uploads:
                raise ValueError("No files were received. Stage files before clicking Visualize.")
            result = process_visualization_request(uploads)
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected server error: {e}'})
            return

        self._send_json(200, result)

    def _handle_simulate(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json(400, {'error': 'Empty request body.'})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {'error': 'Expected a JSON body: {"query": "..."}.'})
            return

        query = str(payload.get('query', '')).strip()
        if not query:
            self._send_json(400, {'error': 'Provide a simulation question, e.g. "What if the approval is denied?".'})
            return

        session_id = str(payload.get('session_id', '')).strip()
        with _session_lock:
            session = _sessions.get(session_id) if session_id else None
            # Fallback: most recent session (single-tab convenience).
            if session is None and _sessions:
                session = _sessions[list(_sessions.keys())[-1]]

        if session is None:
            self._send_json(400, {'error': 'No workflow is loaded yet. Upload files and click Visualize first.'})
            return

        try:
            result = simulation.run_simulation(
                session['engine'], session['workflow'], query,
                trace_ids=session['trace_ids'])
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected simulation error: {e}'})
            return

        self._send_json(200, result)

    def log_message(self, format, *args):
        print(f"[web] {self.address_string()} - {format % args}")


def run_server(port=8000, open_browser=True):
    address = ('127.0.0.1', port)
    httpd = ThreadingHTTPServer(address, DiagnosticWebHandler)
    url = f"http://{address[0]}:{port}/"
    print("\n" + "=" * 46)
    print("=== TRIRIGA Diagnostic Engine - Web UI    ===")
    print(f"=== Serving locally at {url}  ===")
    print("=" * 46 + "\n(Press Ctrl+C to stop)\n")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb UI shutting down.")
    finally:
        httpd.server_close()
