"""Local Web UI server for the TRIRIGA Diagnostic Engine.

Zero-dependency backend built on the Python standard library only
(http.server + email for multipart parsing). Uploaded files never touch
disk: they are streamed into the existing engine as in-memory objects.
"""

import io
import json
import os
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.engine import TririgaHybridEngine
from cli.router import TririgaNLPRouter
from cli.visualizer import WorkflowVisualizer
from cli import simulation

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

ALLOWED_EXTENSIONS = {'.zip', '.log', '.xml', '.txt'}

# Last successful visualization, kept in memory so follow-up What-If queries
# can run against the already-parsed graphs (single-user local tool).
_session_lock = threading.Lock()
_session = None  # dict(engine, router, workflow, trace_ids)


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
    """Parse a multipart/form-data body into [(filename, bytes)] using stdlib email.

    The deprecated ``cgi`` module is intentionally avoided so this runs on
    Python 3.13+ unchanged.
    """
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

    # Live-trace correlation: match each loaded <Header><Name> against the log and
    # keep the workflow whose execution instance (WFIID) is the most recent.
    detected = []
    target_wf, target_trace, target_wfiid = None, [], None
    note = None

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

    global _session
    with _session_lock:
        _session = {
            'engine': engine,
            'router': router,
            'workflow': target_wf,
            'trace_ids': live_trace_ids,
        }

    trace_summary = [
        {'id': step['id'], 'name': step['name'], 'type': step['type'], 'context': step['context']}
        for step in target_trace
    ]

    return {
        'workflow': target_wf,
        'wfiid': target_wfiid,
        'detected_workflows': detected,
        'trace_summary': trace_summary,
        'note': note,
        'map_html': map_html,
        'viz_render_errors': viz_render_errors,
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

    def do_GET(self):
        if self.path in ('/', '/index.html'):
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

        with _session_lock:
            session = _session

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
