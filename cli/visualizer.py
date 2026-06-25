import os
import json
import webbrowser
import networkx as nx
from cli.formatters import wrap_ascii

class WorkflowVisualizer:
    def __init__(self, engine):
        self.engine = engine

    def _get_type_str(self, data):
        t = data.get('type', data.get('Type', 'Generic'))
        if isinstance(t, list): return str(t[0])
        return str(t).strip()

    def _determine_node_shape(self, t_type):
        """Maps TRIRIGA task types to transit map station shapes."""
        if t_type in ['1', 'Trigger', 'Start', '9', '13']:
            return 'ellipse' 
        elif t_type == '14':
            return 'diamond' 
        elif t_type in ['22', '29']:
            return 'database' 
        else:
            return 'box' 

    def _build_side_panel_payload(self, node_data):
        """Extracts the deep metadata to display in the HTML side-panel."""
        payload = []
        
        expressions = node_data.get('Expression', [])
        if expressions: payload.append(f"<b>Expressions Evaluated:</b><br/>" + "<br/>".join([f"- {e}" for e in expressions]))
            
        trgt_flds = node_data.get('TrgtFld', [])
        if trgt_flds: payload.append(f"<b>Database Fields Modified:</b><br/>" + "<br/>".join([f"- {f}" for f in trgt_flds]))
            
        gui_fields = [f for f in node_data.get('Field', []) if f != '^^']
        if gui_fields: payload.append(f"<b>GUI Properties Modified:</b><br/>" + "<br/>".join([f"- {f}" for f in gui_fields]))
            
        gui_mappings = node_data.get('GUIMappings', [])
        if gui_mappings:
            mapping_strs = []
            for gm in gui_mappings:
                sec = gm.get('Section', '')
                fld = gm.get('Field', '')
                if sec and sec != '^^': mapping_strs.append(f"Section: {sec}")
                elif fld and fld != '^^': mapping_strs.append(f"Field: {fld}")
            if mapping_strs:
                payload.append(f"<b>Dynamic UI Targets:</b><br/>" + "<br/>".join(list(set([f"- {m}" for m in mapping_strs]))))

        filters = node_data.get('LFldName', []) + node_data.get('PField', [])
        if filters: payload.append(f"<b>Left Fields Evaluated:</b><br/>" + "<br/>".join([f"- {f}" for f in filters]))
            
        constants = node_data.get('ConstantValue', [])
        if constants: payload.append(f"<b>Constants Checked:</b><br/>" + "<br/>".join([f"- {c}" for c in constants]))

        if not payload: return "<i>No explicit payload mechanics mapped for this task.</i>"
        return "<br/><br/>".join(payload)

    def generate_html_map(self, wf_name, user_query, live_trace_ids=None):
        if wf_name not in self.engine.graphs:
            return wrap_ascii(user_query, f"Cannot visualize: '{wf_name}' is not loaded in the engine.")

        graph = self.engine.graphs[wf_name]
        vis_nodes = []
        vis_edges = []
        
        # Calculate Critical Path (Heaviest Operational Route)
        critical_path_nodes = []
        if nx.is_directed_acyclic_graph(graph):
            try: critical_path_nodes = nx.dag_longest_path(graph)
            except: pass

        if not live_trace_ids: live_trace_ids = []

        # Build Vis.js Nodes
        for node_id, data in graph.nodes(data=True):
            t_type = self._get_type_str(data)
            t_name = data.get('name', f"Task {node_id}")
            t_bo = data.get('BO', data.get('BoName', 'Context BO'))
            if isinstance(t_bo, list): t_bo = t_bo[0]
            
            is_invisible = t_type in ['12', '11'] or (t_name.lower().startswith('unnamed') and t_type != '9') or t_type == 'generic'
            if is_invisible and graph.out_degree(node_id) > 0:
                continue

            shape = self._determine_node_shape(t_type)
            
            # --- Native Vis.js Typographic Hierarchy & Micro-Tags ---
            subtitle = f"Type {t_type}"
            if t_type == '14': subtitle = "Decision Gate"
            elif t_type == '22': subtitle = "Execute Query"
            elif t_type == '29': subtitle = "Retrieve Records"
            elif t_type == '28': subtitle = "Modify Data"
            elif t_type == '23': subtitle = "Modify Form"
            
            tags = []
            if data.get('TrgtFld', []): tags.append("[+Data]")
            if [f for f in data.get('Field', []) if f != '^^'] or data.get('GUIMappings', []): tags.append("[UI]")
            if data.get('LFldName', []) or data.get('PField', []) or data.get('Expression', []): tags.append("[Filter]")
            
            tag_str = (" | " + " ".join(tags)) if tags else ""
            
            # Utilizing vis.js supported native structural pseudo-HTML
            label = f"<b>{t_name}</b>\n<i>{subtitle}</i>\n<code>BO: {t_bo}{tag_str}</code>"
            
            payload_html = self._build_side_panel_payload(data)
            
            # Apply Transit Map Highlights & Dark Mode Colors
            border_color = '#555555' 
            bg_color = '#2b2b2b'
            font_color = '#e0e0e0'
            border_width = 2
            border_width_selected = 2
            shadow_config = False
            
            if str(node_id) in live_trace_ids:
                border_color = '#00ffcc' 
                bg_color = '#1a332e'
                border_width = 3
                border_width_selected = 3
                shadow_config = {'color': '#00ffcc', 'size': 10, 'x': 0, 'y': 0}
            elif str(node_id) in critical_path_nodes:
                border_color = '#0088ff' 
                bg_color = '#1a2633'
                border_width = 2
                border_width_selected = 2
                shadow_config = {'color': '#0088ff', 'size': 8, 'x': 0, 'y': 0}

            vis_nodes.append({
                'id': str(node_id),
                'label': label,
                'shape': shape,
                'color': {
                    'background': bg_color,
                    'border': border_color,
                    'highlight': {'background': '#444444', 'border': '#ffffff'}
                },
                'borderWidth': border_width,
                'borderWidthSelected': border_width_selected,
                'font': {
                    'multi': 'html', 
                    'size': 14, 
                    'face': 'Segoe UI', 
                    'color': font_color, 
                    'align': 'center',
                    'bold': {'color': '#ffffff', 'size': 14},
                    'ital': {'color': '#888888', 'size': 12},
                    'code': {'color': '#4da6ff', 'size': 11, 'face': 'Consolas'}
                },
                'margin': 18,
                'widthConstraint': { 'maximum': 220 }, 
                'shadow': shadow_config,
                'customPayload': f"<h3>Station: {t_name}</h3><b>Type:</b> {t_type}<br/><b>ID:</b> {node_id}<br/><b>Context:</b> {t_bo}<hr/>{payload_html}"
            })

        # Build Vis.js Edges
        def get_visible_targets(start_id, visited=None):
            if visited is None: visited = set()
            targets = []
            for succ in graph.successors(start_id):
                succ_data = graph.nodes[succ]
                s_type = self._get_type_str(succ_data)
                s_name = succ_data.get('name', '').lower()
                
                is_inv = s_type in ['12', '11'] or (s_name.startswith('unnamed') and s_type != '9') or s_type == 'generic'
                if is_inv:
                    if succ not in visited:
                        visited.add(succ)
                        targets.extend(get_visible_targets(succ, visited))
                else:
                    targets.append(succ)
            return list(set(targets))

        edge_tracker = set()
        for node_id in graph.nodes():
            if str(node_id) in [n['id'] for n in vis_nodes]:
                targets = get_visible_targets(node_id)
                for t in targets:
                    edge_key = f"{node_id}->{t}"
                    if edge_key not in edge_tracker:
                        edge_tracker.add(edge_key)
                        
                        label = ""
                        node_data = graph.nodes[node_id]
                        if self._get_type_str(node_data) == '14':
                            true_target = node_data.get('TargetAssociation', '')
                            if isinstance(true_target, list): true_target = true_target[0] if true_target else ''
                            t_list = [x for x in true_target.split(';') if x]
                            if t_list and str(t) == str(t_list[0]): label = "TRUE"
                            else:
                                if t_list and str(t) in get_visible_targets(t_list[0]): label = "TRUE"

                        is_edge_live = str(node_id) in live_trace_ids and str(t) in live_trace_ids
                        is_edge_critical = str(node_id) in critical_path_nodes and str(t) in critical_path_nodes
                        
                        e_color = '#444444' 
                        e_width = 2
                        
                        if is_edge_live:
                            e_color = '#00ffcc'
                            e_width = 4
                        elif is_edge_critical:
                            e_color = '#0088ff'
                            e_width = 3

                        vis_edges.append({
                            'from': str(node_id),
                            'to': str(t),
                            'arrows': 'to',
                            'label': label,
                            'color': {'color': e_color, 'highlight': '#ffffff'},
                            'width': e_width,
                            'font': {'align': 'horizontal', 'color': '#ffaa00', 'background': 'transparent'} if label == 'TRUE' else {}
                        })

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>TRIRIGA Transit Map: {wf_name}</title>
            <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
            <style type="text/css">
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; display: flex; height: 100vh; background-color: #121212; }}
                #mynetwork {{ width: 75%; height: 100%; border-right: 2px solid #333; background-color: #1a1a1a; position: relative; }}
                #sidepanel {{ width: 25%; height: 100%; padding: 20px; overflow-y: auto; background-color: #0d0d0d; color: #f1f1f1; box-sizing: border-box; }}
                h2 {{ color: #00ffcc; font-size: 1.2em; margin-top: 0; border-bottom: 1px solid #333; padding-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }}
                h3 {{ color: #ffffff; margin-bottom: 5px; }}
                hr {{ border-color: #333; }}
                .hint {{ color: #888; font-style: italic; margin-top: 20px; }}
                .legend {{ position: absolute; bottom: 20px; left: 20px; background: rgba(20,20,20,0.85); padding: 15px; border: 1px solid #333; border-radius: 8px; font-size: 13px; color: #ddd; z-index: 1000; box-shadow: 0 4px 15px rgba(0,0,0,0.5); backdrop-filter: blur(4px); }}
                .legend-item {{ display: flex; align-items: center; margin-bottom: 8px; }}
                .legend-item:last-child {{ margin-bottom: 0; }}
                .color-box {{ width: 18px; height: 18px; margin-right: 12px; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div id="mynetwork">
                <div class="legend">
                    <div style="font-weight: 600; margin-bottom: 12px; text-transform: uppercase; font-size: 11px; color: #888; letter-spacing: 1px;">Transit Lines</div>
                    <div class="legend-item"><div class="color-box" style="background: #0088ff; box-shadow: 0 0 8px #0088ff;"></div> Main Line (Critical Path)</div>
                    <div class="legend-item"><div class="color-box" style="background: #00ffcc; box-shadow: 0 0 10px #00ffcc;"></div> Live Execution Track</div>
                    <div class="legend-item"><div class="color-box" style="background: #444444;"></div> Branch / Unused Track</div>
                </div>
            </div>
            <div id="sidepanel">
                <h2>Station Diagnostics</h2>
                <div id="payloadData">
                    <p class="hint">Click on any station node to inspect its internal logic, database modifiers, and GUI mappings.</p>
                </div>
            </div>

            <script type="text/javascript">
                var nodes = new vis.DataSet({json.dumps(vis_nodes)});
                var edges = new vis.DataSet({json.dumps(vis_edges)});
                var container = document.getElementById('mynetwork');
                var data = {{ nodes: nodes, edges: edges }};
                
                var options = {{
                    layout: {{
                        hierarchical: {{
                            direction: 'LR',
                            sortMethod: 'directed',
                            nodeSpacing: 180,
                            levelSeparation: 350,
                            treeSpacing: 200
                        }}
                    }},
                    physics: {{ 
                        hierarchicalRepulsion: {{ 
                            nodeDistance: 250,
                            avoidOverlap: 1
                        }} 
                    }},
                    edges: {{ 
                        smooth: {{ type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.45 }}
                    }}
                }};
                
                var network = new vis.Network(container, data, options);
                
                network.on("click", function (params) {{
                    if (params.nodes.length > 0) {{
                        var nodeId = params.nodes[0];
                        var nodeData = nodes.get(nodeId);
                        document.getElementById('payloadData').innerHTML = nodeData.customPayload;
                    }} else {{
                        document.getElementById('payloadData').innerHTML = '<p class="hint">Click on any station node to inspect its internal logic, database modifiers, and GUI mappings.</p>';
                    }}
                }});
            </script>
        </body>
        </html>
        """

        file_name = f"blueprint_{wf_name.replace(' ', '_')}.html"
        file_path = os.path.join(os.getcwd(), file_name)
        
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(html_content)

        webbrowser.open('file://' + os.path.realpath(file_path))
        
        msg = f"Interactive map successfully generated.\nOpened '{file_name}' in your default web browser."
        if not live_trace_ids:
            msg += "\n[!] Note: No Live Trace detected. Run 'trace live execution' prior to mapping to see the exact track illuminated."
            
        return wrap_ascii(user_query, msg)