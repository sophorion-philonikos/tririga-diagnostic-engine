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
from cli import analysis_api
from cli import graph_utils
from om_gen.build import build_from_ir
from om_gen.emit_workflow import ir_to_preview_graph, workflow_filename
from om_gen.nl_recipe import SUPPORTED_NL_HELP, nl_to_recipe
from om_gen.parse_recipe import ir_to_recipe_dict, recipe_to_ir
from om_gen.validate import ValidationError, validate_ir

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

ALLOWED_EXTENSIONS = {'.zip', '.log', '.xml', '.txt'}

# Per-browser session store (token -> session dict). Multi-tab safe.
_session_lock = threading.Lock()
_sessions = {}


def generator_parse(payload):
    """Parse NL (+ optional name/module/bo) → IR recipe dict + preview graph."""
    prompt = str(payload.get('prompt') or payload.get('description') or '').strip()
    if not prompt:
        raise ValueError('Provide a workflow description (prompt).')
    name = str(payload.get('name') or '').strip()
    module = str(payload.get('module') or '').strip()
    bo = str(payload.get('bo') or '').strip()
    event_name = str(payload.get('event_name') or payload.get('event') or '').strip()
    recipe = nl_to_recipe(
        prompt, name=name, module=module, bo=bo, event_name=event_name,
    )
    if name:
        recipe['header']['name'] = name
    if module:
        recipe['header']['module'] = module
    if bo:
        recipe['header']['bo'] = bo
    ir = recipe_to_ir(recipe)
    validate_ir(ir)
    nodes, edges = ir_to_preview_graph(ir)
    return {
        'ir': ir_to_recipe_dict(ir),
        'nodes': nodes,
        'edges': edges,
    }


def generator_compile(payload):
    """Compile IR or NL into flat OM zip bytes + suggested filename."""
    ir = None
    if payload.get('ir'):
        ir = recipe_to_ir(payload['ir'])
        validate_ir(ir)
        data = build_from_ir(ir)
    elif payload.get('prompt') or payload.get('description'):
        prompt = str(payload.get('prompt') or payload.get('description'))
        name = str(payload.get('name') or '')
        module = str(payload.get('module') or '')
        bo = str(payload.get('bo') or '')
        event_name = str(payload.get('event_name') or '')
        recipe = nl_to_recipe(
            prompt, name=name, module=module, bo=bo, event_name=event_name,
        )
        if name:
            recipe['header']['name'] = name
        if module:
            recipe['header']['module'] = module
        if bo:
            recipe['header']['bo'] = bo
        ir = recipe_to_ir(recipe)
        data = build_from_ir(ir)
    else:
        raise ValueError('Provide ir or prompt to compile.')
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError('Compiler did not return zip bytes.')
    base = workflow_filename(ir).replace('.xml', '')
    return bytes(data), f'{base}.zip'



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
            switch_label = f"{name[:32]} ({nid})"
            chips.append({
                'label': f"Force FALSE · {switch_label}",
                'query': f"what if switch {nid} is FALSE",
            })
            if len(chips) >= limit:
                break
            chips.append({
                'label': f"Force TRUE · {switch_label}",
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


def _trace_summary_from_steps(trace):
    return [
        {'id': step['id'], 'name': step['name'], 'type': step['type'], 'context': step['context']}
        for step in (trace or [])
    ]


def _render_map_html(engine, wf_name, trace_ids):
    """Build map HTML for one workflow; returns (html, viz_errors)."""
    visualizer = WorkflowVisualizer(engine)
    try:
        return visualizer.build_html(wf_name, live_trace_ids=trace_ids or []), []
    except Exception as exc:
        import traceback
        reasons = [f"{type(exc).__name__}: {exc}"]
        for line in reversed(traceback.format_exc().splitlines()):
            if 'File "' in line and ('cli/' in line or 'core/' in line or 'web/' in line):
                reasons.append(line.strip())
                break
        html = (
            "<!DOCTYPE html><html><body style='font-family:Segoe UI,sans-serif;"
            "background:#2b2b2b;color:#ffb3b3;padding:24px;'>"
            "<h2>Visualization failed to render</h2>"
            f"<pre>{chr(10).join(reasons)}</pre></body></html>"
        )
        return html, reasons


def _diff_for(session, wf_name):
    fingerprints = session.get('fingerprints') or {}
    others = [n for n in session['engine'].loaded_workflow_names if n != wf_name]
    if not others:
        return None
    a = set(fingerprints.get(wf_name, []))
    b = set(fingerprints.get(others[0], []))
    return {
        'other_workflow': others[0],
        'added': sorted(a - b),
        'removed': sorted(b - a),
        'shared': sorted(a & b),
    }


def _sync_active_mirrors(session):
    """Keep legacy top-level keys pointing at the active workflow bundle."""
    active = session['active_workflow']
    bundle = session['workflows'][active]
    session['workflow'] = active
    session['trace_ids'] = list(bundle.get('trace_ids') or [])
    session['map_html'] = bundle.get('map_html')


def _ensure_map_html(session, wf_name):
    """Lazy-build map HTML for a workflow bundle. Mutates session."""
    bundle = session['workflows'][wf_name]
    if bundle.get('map_html') is not None:
        return bundle
    html, errs = _render_map_html(
        session['engine'], wf_name, bundle.get('trace_ids') or []
    )
    bundle['map_html'] = html
    bundle['viz_error'] = errs or None
    return bundle


def _active_response(session_id, session):
    """JSON slice the UI needs after visualize or switch."""
    wf = session['active_workflow']
    bundle = session['workflows'][wf]
    detected = [
        {
            'workflow': name,
            'wfiid': session['workflows'][name].get('wfiid'),
            'steps': len(session['workflows'][name].get('trace_summary') or []),
        }
        for name in session['engine'].loaded_workflow_names
    ]
    return {
        'session_id': session_id,
        'map_url': f'/api/map/{session_id}',
        'workflow': wf,
        'wfiid': bundle.get('wfiid'),
        'detected_workflows': detected,
        'trace_summary': list(bundle.get('trace_summary') or []),
        'sim_chips': list(bundle.get('sim_chips') or []),
        'sim_placeholder': bundle.get('sim_placeholder') or '',
        'diff': _diff_for(session, wf),
        'last_sim': bundle.get('last_sim'),
        'viz_render_errors': list(bundle.get('viz_error') or []),
        'map_html': None,
    }


def _get_session(session_id):
    """Resolve session by id, else most recent (single-tab convenience)."""
    session = _sessions.get(session_id) if session_id else None
    if session is None and _sessions:
        session = _sessions[list(_sessions.keys())[-1]]
    return session


def switch_workflow(session_id, workflow):
    """Activate another loaded workflow; lazy-build its map. Returns UI slice."""
    workflow = str(workflow or '').strip()
    if not workflow:
        raise ValueError('Provide a workflow name to switch to.')
    with _session_lock:
        session = _get_session(session_id)
        if session is None:
            raise ValueError('No workflow is loaded yet. Upload files and click Visualize first.')
        if workflow not in session['workflows']:
            names = ', '.join(session['workflows'].keys())
            raise ValueError(f"Unknown workflow '{workflow}'. Loaded: {names}")
        session['active_workflow'] = workflow
        _ensure_map_html(session, workflow)
        _sync_active_mirrors(session)
        # Resolve actual session id for map_url (fallback path may lack client id).
        sid = session_id
        if not sid or sid not in _sessions:
            for k, v in _sessions.items():
                if v is session:
                    sid = k
                    break
        return _active_response(sid, session)


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
    target_wf, target_wfiid = None, None
    note = None
    log_text = None
    # name -> (wfiid, raw_trace_steps)
    traces_by_wf = {}

    if server_logs:
        log_text = server_logs[0][1].decode('utf-8', errors='ignore')
        log_lines = log_text.splitlines(keepends=True)

        for wf_name in engine.loaded_workflow_names:
            wfiid, trace, _records, _counts = router.extract_execution_trace(log_lines, wf_name)
            traces_by_wf[wf_name] = (wfiid, trace)
            detected.append({
                'workflow': wf_name,
                'wfiid': wfiid,
                'steps': len(trace),
            })
            if wfiid is not None:
                if target_wfiid is None or int(wfiid) > int(target_wfiid):
                    target_wf, target_wfiid = wf_name, wfiid

        if target_wf is None:
            note = ("No execution of the loaded workflow(s) was found in the uploaded log. "
                    "Rendering a static blueprint instead. Ensure TRIRIGA Workflow Logging "
                    "(Start, End, and Steps) was enabled when the log was captured.")
    else:
        for name in engine.loaded_workflow_names:
            traces_by_wf[name] = (None, [])
            detected.append({'workflow': name, 'wfiid': None, 'steps': 0})
        note = "No server log (.log) uploaded. Rendering a static blueprint with no live-trace overlay."

    if target_wf is None:
        target_wf = engine.loaded_workflow_names[0]

    fingerprints = {
        name: _workflow_fingerprint(engine, name)
        for name in engine.loaded_workflow_names
    }

    workflows = {}
    for name in engine.loaded_workflow_names:
        wfiid, trace = traces_by_wf.get(name, (None, []))
        chips = _build_sim_chips(engine, name)
        workflows[name] = {
            'wfiid': wfiid,
            'trace_ids': [step['id'] for step in trace],
            'trace_summary': _trace_summary_from_steps(trace),
            'map_html': None,
            'sim_chips': chips,
            'sim_placeholder': _build_sim_placeholder(chips, name),
            'last_sim': None,
            'viz_error': None,
        }

    primary = workflows[target_wf]
    map_html, viz_render_errors = _render_map_html(
        engine, target_wf, primary['trace_ids']
    )
    primary['map_html'] = map_html
    primary['viz_error'] = viz_render_errors or None

    session_id = _new_session_id()
    session = {
        'engine': engine,
        'router': router,
        'log_text': log_text,
        'fingerprints': fingerprints,
        'active_workflow': target_wf,
        'workflows': workflows,
        # Compat mirrors for /api/map and /api/simulate
        'workflow': target_wf,
        'trace_ids': list(primary['trace_ids']),
        'map_html': map_html,
    }
    with _session_lock:
        _sessions[session_id] = session

    result = _active_response(session_id, session)
    result['note'] = note
    result['detected_workflows'] = detected
    result['viz_render_errors'] = viz_render_errors
    return result


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

    def _send_bytes(self, status, data, content_type, headers=None):
        body = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length <= 0:
            return None, 'Empty request body.'
        try:
            return json.loads(self.rfile.read(length).decode('utf-8')), None
        except (ValueError, UnicodeDecodeError):
            return None, 'Expected a JSON body.'

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

        if path in ('/generator', '/generator.html'):
            gen_path = os.path.join(STATIC_DIR, 'generator.html')
            try:
                with open(gen_path, 'rb') as f:
                    body = f.read()
            except FileNotFoundError:
                self._send_json(500, {'error': f'Missing UI file: {gen_path}'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/api/generator/nl-help':
            self._send_json(200, {'help': SUPPORTED_NL_HELP})
            return

        if path.startswith('/api/map/'):
            sid = path[len('/api/map/'):].strip('/')
            html = None
            with _session_lock:
                sess = _sessions.get(sid)
                if sess:
                    active = sess.get('active_workflow')
                    if active and active in sess.get('workflows', {}):
                        _ensure_map_html(sess, active)
                        _sync_active_mirrors(sess)
                    html = sess.get('map_html')
            if not html:
                self._send_html(404, '<html><body>Map session not found.</body></html>')
                return
            self._send_html(200, html)
            return

        self._send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/api/simulate':
            self._handle_simulate()
            return
        if self.path == '/api/switch-workflow':
            self._handle_switch_workflow()
            return
        if self.path == '/api/analyze':
            self._handle_analyze()
            return
        if self.path == '/api/generator/parse':
            self._handle_generator_parse()
            return
        if self.path == '/api/generator/compile':
            self._handle_generator_compile()
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

    def _handle_generator_parse(self):
        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {'error': err})
            return
        try:
            result = generator_parse(payload or {})
        except (ValueError, ValidationError) as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected generator parse error: {e}'})
            return
        self._send_json(200, result)

    def _handle_generator_compile(self):
        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {'error': err})
            return
        try:
            data, filename = generator_compile(payload or {})
        except (ValueError, ValidationError) as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected generator compile error: {e}'})
            return
        self._send_bytes(
            200,
            data,
            'application/zip',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
            },
        )

    def _handle_switch_workflow(self):
        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {'error': err})
            return
        session_id = str(payload.get('session_id', '')).strip()
        workflow = payload.get('workflow', '')
        try:
            result = switch_workflow(session_id, workflow)
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected switch error: {e}'})
            return
        self._send_json(200, result)

    def _handle_analyze(self):
        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {'error': err})
            return
        session_id = str(payload.get('session_id', '')).strip()
        op = payload.get('op', '')
        with _session_lock:
            session = _get_session(session_id)
        if session is None:
            self._send_json(400, {
                'error': 'No workflow is loaded yet. Upload files and click Visualize first.'
            })
            return
        wf_name = str(payload.get('workflow') or session.get('active_workflow') or '').strip()
        try:
            result = analysis_api.run_analyze(session['router'], wf_name, op, payload)
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected analyze error: {e}'})
            return
        self._send_json(200, result)

    def _handle_simulate(self):
        payload, err = self._read_json_body()
        if err:
            self._send_json(400, {'error': err})
            return
        if payload is None:
            self._send_json(400, {'error': 'Empty request body.'})
            return

        session_id = str(payload.get('session_id', '')).strip()

        if payload.get('clear'):
            with _session_lock:
                session = _get_session(session_id)
                if session is None:
                    self._send_json(400, {
                        'error': 'No workflow is loaded yet. Upload files and click Visualize first.'
                    })
                    return
                active = session.get('active_workflow') or session.get('workflow')
                if active and active in session.get('workflows', {}):
                    session['workflows'][active]['last_sim'] = None
            self._send_json(200, {'ok': True, 'cleared': True})
            return

        query = str(payload.get('query', '')).strip()
        if not query:
            self._send_json(400, {'error': 'Provide a simulation question, e.g. "What if the approval is denied?".'})
            return

        with _session_lock:
            session = _get_session(session_id)
            if session is None:
                self._send_json(400, {'error': 'No workflow is loaded yet. Upload files and click Visualize first.'})
                return
            engine = session['engine']
            workflow = session['workflow']
            trace_ids = list(session.get('trace_ids') or [])
            active = session.get('active_workflow') or workflow

        try:
            result = simulation.run_simulation(
                engine, workflow, query, trace_ids=trace_ids)
        except ValueError as e:
            self._send_json(400, {'error': str(e)})
            return
        except Exception as e:
            self._send_json(500, {'error': f'Unexpected simulation error: {e}'})
            return

        with _session_lock:
            sess = _get_session(session_id)
            if sess is not None:
                wf_key = sess.get('active_workflow') or active
                if wf_key in sess.get('workflows', {}):
                    sess['workflows'][wf_key]['last_sim'] = result

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
