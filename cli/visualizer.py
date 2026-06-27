import os
import json
import webbrowser
import networkx as nx
import textwrap
import urllib.parse
from cli.formatters import wrap_ascii

class WorkflowVisualizer:
    def __init__(self, engine):
        self.engine = engine

    def _get_type_str(self, data):
        t = data.get('type', data.get('Type', 'Generic'))
        if isinstance(t, list): return str(t[0])
        return str(t).strip()

    def _build_svg_node(self, t_name, t_type, t_bo, payload_data, is_live, is_critical):
        """Mathematically generates a pixel-perfect TRIRIGA OOB-shaped SVG UI Card."""
        
        tags = []
        if payload_data.get('TrgtFld', []): 
            tags.append({'label': '[+ Data]', 'bg': '#003366', 'border': '#4da6ff', 'text': '#ffffff'})
        if [f for f in payload_data.get('Field', []) if f != '^^'] or payload_data.get('GUIMappings', []): 
            tags.append({'label': '[ UI ]', 'bg': '#4d0033', 'border': '#ff66cc', 'text': '#ffffff'})
        if payload_data.get('LFldName', []) or payload_data.get('PField', []) or payload_data.get('Expression', []): 
            tags.append({'label': '[Filter]', 'bg': '#4d3300', 'border': '#f1c232', 'text': '#ffffff'})

        subtitle = f"Type {t_type}"
        if t_type == '14': subtitle = "Decision Gate"
        elif t_type == '22': subtitle = "Execute Query"
        elif t_type == '29': subtitle = "Retrieve Records"
        elif t_type == '28': subtitle = "Modify Data"
        elif t_type == '23': subtitle = "Modify Form"

        width = 240
        wrap_limit = 28
        text_x_offset = 20
        
        if t_type == '14': 
            wrap_limit = 24
            text_x_offset = 15
        elif t_type == '22': 
            wrap_limit = 24
            text_x_offset = 15
        elif t_type in ['1', '9', '13']: 
            wrap_limit = 22
            text_x_offset = 35
        elif t_type == '29': 
            wrap_limit = 26
            text_x_offset = 20

        wrapped_name = textwrap.wrap(t_name, width=wrap_limit)
        
        header_h = 28
        line_height = 16
        name_start_y = header_h + 20
        subtitle_y = name_start_y + (len(wrapped_name) * line_height) + 6
        
        pill_area_h = 35 if tags else 15
        total_h = subtitle_y + pill_area_h

        if t_type == '14': total_h += 20 

        # Exact TRIRIGA OOB Hex Colors
        bg_color = '#ffffff'
        border_color = '#7f8c8d'
        
        font_color = '#111111'
        subtitle_color = '#444444'
        header_font_color = '#222222'
        header_label_color = '#555555'
        line_color = '#7f8c8d'
        
        if t_type in ['1', 'Trigger', 'Start']:
            bg_color = '#00b050' 
            border_color = '#007a37'
        elif t_type in ['9', '13']:
            bg_color = '#ff0000' 
            border_color = '#b30000'
        elif t_type == '28':
            bg_color = '#ffcccc' 
            border_color = '#ff6666'
        elif t_type == '29':
            bg_color = '#bbf3ff' 
            border_color = '#33ccff'
        elif t_type == '22':
            bg_color = '#ccffcc' 
            border_color = '#66cc66'
        elif t_type == '23':
            bg_color = '#e6ccff' 
            border_color = '#b366ff'
        elif t_type == '14':
            bg_color = '#00b0f0' 
            border_color = '#007ab3'

        stroke_width = 2
        if is_live:
            border_color = '#00c3a5'
            stroke_width = 4
        elif is_critical:
            border_color = '#e67e22'
            stroke_width = 3

        svg_shape = ""
        mid = total_h / 2
        w = width - 2
        h = total_h - 2
        
        if t_type in ['1', 'Trigger', 'Start', '9', '13']:
            svg_shape = f'<ellipse cx="{width/2}" cy="{mid}" rx="{width/2 - 2}" ry="{mid - 2}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '14':
            # V-Bottom Shield: Guarantees connection to the bounding box at the Left, Right, and Bottom edges. Fixes floating lines.
            svg_shape = f'<polygon points="2,2 {w},2 {w},{h-20} {w/2},{h} 2,{h-20}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '22':
            svg_shape = f'<polygon points="2,2 {w-15},2 {w},{mid} {w-15},{h} 2,{h}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '29':
            svg_shape = f'<rect x="2" y="2" width="{width-4}" height="{total_h-4}" rx="20" ry="20" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '23':
            # Violet Rectangle with Taller Double Bite Marks (radius increased to 14)
            r = 14
            y1 = total_h * 0.35
            y2 = total_h * 0.65
            svg_shape = f'<path d="M 2 2 L {w} 2 L {w} {y1-r} A {r} {r} 0 0 0 {w} {y1+r} L {w} {y2-r} A {r} {r} 0 0 0 {w} {y2+r} L {w} {h} L 2 {h} L 2 {y2+r} A {r} {r} 0 0 0 2 {y2-r} L 2 {y1+r} A {r} {r} 0 0 0 2 {y1-r} Z" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        else:
            svg_shape = f'<rect x="2" y="2" width="{width-4}" height="{total_h-4}" rx="4" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}">
            {svg_shape}
            <text x="{text_x_offset}" y="20" font-family="Segoe UI, Tahoma, sans-serif" font-size="11" font-weight="bold" fill="{header_label_color}">Context: <tspan fill="{header_font_color}">{t_bo}</tspan></text>
            <line x1="{text_x_offset}" y1="{header_h}" x2="{width - 30}" y2="{header_h}" stroke="{line_color}" stroke-width="1" opacity="0.4"/>
        """

        current_y = name_start_y
        for line in wrapped_name:
            svg += f'<text x="{text_x_offset}" y="{current_y}" font-family="Segoe UI, Tahoma, sans-serif" font-size="13" font-weight="bold" fill="{font_color}">{line}</text>'
            current_y += line_height

        svg += f'<text x="{text_x_offset}" y="{subtitle_y}" font-family="Segoe UI, Tahoma, sans-serif" font-size="11" font-style="italic" fill="{subtitle_color}">{subtitle}</text>'

        if tags:
            pill_x = text_x_offset
            pill_y = subtitle_y + 8
            for tag in tags:
                text_w = len(tag['label']) * 6
                rect_w = text_w + 10
                svg += f'<rect x="{pill_x}" y="{pill_y}" width="{rect_w}" height="16" rx="3" fill="{tag["bg"]}" stroke="{tag["border"]}" stroke-width="1"/>'
                svg += f'<text x="{pill_x + 5}" y="{pill_y + 11}" font-family="Consolas, monospace" font-size="9" font-weight="bold" fill="{tag["text"]}">{tag["label"]}</text>'
                pill_x += rect_w + 5

        svg += "</svg>"
        
        encoded_svg = "data:image/svg+xml;charset=utf-8," + urllib.parse.quote(svg, safe='')
        return encoded_svg, width, total_h

    def _build_side_panel_payload(self, node_data, t_type):
        payload = []
        
        expressions = node_data.get('Expression', [])
        if expressions: 
            if isinstance(expressions, str): expressions = [expressions]
            payload.append(f"<b>Expressions Evaluated:</b><br/>" + "<br/>".join([f"&bull; {e}" for e in expressions]))
        
        if t_type == '28':
            trgt_flds = node_data.get('TrgtFld', [])
            src_flds = node_data.get('SrcFld', [])
            trgt_bos = node_data.get('TrgtBo', node_data.get('TrgtBO', []))
            src_bos = node_data.get('SrcBo', node_data.get('SrcBO', []))
            fld_vals = node_data.get('FldVal', node_data.get('ConstantValue', []))
            
            if isinstance(trgt_flds, str): trgt_flds = [trgt_flds]
            if isinstance(src_flds, str): src_flds = [src_flds]
            if isinstance(trgt_bos, str): trgt_bos = [trgt_bos]
            if isinstance(src_bos, str): src_bos = [src_bos]
            if isinstance(fld_vals, str): fld_vals = [fld_vals]
            
            if trgt_flds:
                mapping_sentences = []
                for i in range(len(trgt_flds)):
                    t_fld = trgt_flds[i]
                    
                    t_bo_raw = node_data.get('BO', ['Target Context'])
                    if isinstance(t_bo_raw, list): t_bo_raw = t_bo_raw[0] if t_bo_raw else 'Target Context'
                    
                    t_bo = trgt_bos[i] if i < len(trgt_bos) else (trgt_bos[0] if trgt_bos else t_bo_raw)
                    s_bo = src_bos[i] if i < len(src_bos) else (src_bos[0] if src_bos else 'Source Context')
                    
                    val = fld_vals[i] if i < len(fld_vals) else None
                    s_fld = src_flds[i] if i < len(src_flds) else None
                    
                    source_val_text = val if val else (s_fld if s_fld else 'mapped data')
                    if val and val.lower() == 'source' and s_fld:
                        source_val_text = f"'{s_fld}'"
                    elif val and val.lower() == 'source':
                        source_val_text = "the source record"
                    elif val:
                        source_val_text = f"'{val}'"
                        
                    sentence = f"The field <b>{t_fld}</b> on the BO <b>{t_bo}</b> is being updated to the value <b>{source_val_text}</b>, which comes from BO <b>{s_bo}</b>."
                    mapping_sentences.append(sentence)
                
                payload.append(f"<b>Data Mapping Mechanics:</b><br/>" + "<br/>".join([f"&bull; {s}" for s in mapping_sentences]))
        else:
            trgt_flds = node_data.get('TrgtFld', [])
            if trgt_flds: 
                if isinstance(trgt_flds, str): trgt_flds = [trgt_flds]
                payload.append(f"<b>Database Fields Modified:</b><br/>" + "<br/>".join([f"&bull; {f}" for f in trgt_flds]))
                
        gui_fields = [f for f in node_data.get('Field', []) if f != '^^']
        if gui_fields: 
            if isinstance(gui_fields, str): gui_fields = [gui_fields]
            payload.append(f"<b>GUI Properties Modified:</b><br/>" + "<br/>".join([f"&bull; {f}" for f in gui_fields]))
            
        gui_mappings = node_data.get('GUIMappings', [])
        if gui_mappings:
            mapping_strs = []
            for gm in gui_mappings:
                sec = gm.get('Section', '')
                fld = gm.get('Field', '')
                if sec and sec != '^^': mapping_strs.append(f"Section: {sec}")
                elif fld and fld != '^^': mapping_strs.append(f"Field: {fld}")
            if mapping_strs:
                payload.append(f"<b>Dynamic UI Targets:</b><br/>" + "<br/>".join(list(set([f"&bull; {m}" for m in mapping_strs]))))
                
        filters = node_data.get('LFldName', []) + node_data.get('PField', [])
        if filters: 
            if isinstance(filters, str): filters = [filters]
            payload.append(f"<b>Left Fields Evaluated:</b><br/>" + "<br/>".join([f"&bull; {f}" for f in filters]))
            
        constants = node_data.get('ConstantValue', [])
        if constants: 
            if isinstance(constants, str): constants = [constants]
            payload.append(f"<b>Constants Checked:</b><br/>" + "<br/>".join([f"&bull; {c}" for c in constants]))

        if not payload: return "<i>No explicit payload mechanics mapped for this task.</i>"
        return "<br/><br/>".join(payload)

    def generate_html_map(self, wf_name, user_query, live_trace_ids=None):
        if wf_name not in self.engine.graphs:
            return wrap_ascii(user_query, f"Cannot visualize: '{wf_name}' is not loaded in the engine.")

        graph = self.engine.graphs[wf_name]
        
        critical_path_nodes = []
        if nx.is_directed_acyclic_graph(graph):
            try: critical_path_nodes = nx.dag_longest_path(graph)
            except: pass

        if not live_trace_ids: live_trace_ids = []

        dagre_nodes = []
        dagre_edges = []

        for node_id, data in graph.nodes(data=True):
            t_type = self._get_type_str(data)
            t_name = data.get('name', f"Task {node_id}")
            t_bo = data.get('BO', data.get('BoName', 'Context BO'))
            if isinstance(t_bo, list): t_bo = t_bo[0]
            
            is_invisible = t_type in ['12', '11'] or (t_name.lower().startswith('unnamed') and t_type != '9') or t_type == 'generic'
            if is_invisible and graph.out_degree(node_id) > 0:
                continue

            is_live = str(node_id) in live_trace_ids
            is_critical = str(node_id) in critical_path_nodes

            svg_data_uri, node_width, node_height = self._build_svg_node(t_name, t_type, t_bo, data, is_live, is_critical)
            payload_html = self._build_side_panel_payload(data, t_type)

            dagre_nodes.append({
                'id': str(node_id),
                'image': svg_data_uri,
                'width': node_width,
                'height': node_height,
                'customPayload': f"<h3>Task: {t_name}</h3><b>Type:</b> {t_type}<br/><b>ID:</b> {node_id}<br/><b>Context:</b> {t_bo}<hr/>{payload_html}"
            })

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
            if str(node_id) in [n['id'] for n in dagre_nodes]:
                targets = get_visible_targets(node_id)
                
                source_data = graph.nodes[node_id]
                s_type = self._get_type_str(source_data)

                for t in targets:
                    edge_key = f"{node_id}->{t}"
                    if edge_key not in edge_tracker:
                        edge_tracker.add(edge_key)
                        
                        label = ""
                        if s_type == '14':
                            true_target = source_data.get('TargetAssociation', '')
                            if isinstance(true_target, list): true_target = true_target[0] if true_target else ''
                            t_list = [x for x in true_target.split(';') if x]
                            if t_list and str(t) == str(t_list[0]): label = "TRUE"
                            else:
                                if t_list and str(t) in get_visible_targets(t_list[0]): label = "TRUE"

                        is_edge_live = str(node_id) in live_trace_ids and str(t) in live_trace_ids
                        is_edge_critical = str(node_id) in critical_path_nodes and str(t) in critical_path_nodes
                        
                        e_color = '#7f8c8d' 
                        e_width = 2
                        
                        if is_edge_live:
                            e_color = '#00c3a5'
                            e_width = 4
                        elif is_edge_critical:
                            e_color = '#e67e22'
                            e_width = 3

                        dagre_edges.append({
                            'from': str(node_id),
                            'to': str(t),
                            'label': label,
                            'color': e_color,
                            'width': e_width,
                            'source_type': s_type
                        })

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>TRIRIGA Diagnostic Blueprint: {wf_name}</title>
            <script src="https://d3js.org/d3.v5.min.js"></script>
            <script src="https://dagrejs.github.io/project/dagre-d3/latest/dagre-d3.min.js"></script>
            <style type="text/css">
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; display: flex; height: 100vh; background-color: #f4f6f9; }}
                
                #canvas-container {{ 
                    width: 75%; 
                    height: 100%; 
                    border-right: 2px solid #ccc; 
                    background-color: #f8f9fa;
                    background-image: radial-gradient(#d5d5d5 1px, transparent 1px);
                    background-size: 20px 20px;
                    position: relative; 
                    overflow: hidden; 
                }}
                
                #sidepanel {{ width: 25%; height: 100%; padding: 20px; overflow-y: auto; background-color: #2b2b2b; color: #f1f1f1; box-sizing: border-box; }}
                h2 {{ color: #4da6ff; font-size: 1.2em; margin-top: 0; border-bottom: 1px solid #555; padding-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }}
                h3 {{ color: #ffffff; margin-bottom: 5px; }}
                hr {{ border-color: #555; }}
                .hint {{ color: #888; font-style: italic; margin-top: 20px; }}
                
                svg {{ width: 100%; height: 100%; }}
                .node {{ cursor: pointer; }}
                .node img {{ display: block; }}
                
                .node rect {{ fill: transparent !important; stroke: none !important; }}
                
                .edgePath path {{ fill: none; }}
                
                .edgeLabel rect {{ fill: #ffffff; stroke: #ccc; stroke-width: 1; rx: 3; ry: 3; }}
                .edgeLabel text {{ font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold; fill: #d35400; }}

                .legend {{ position: absolute; bottom: 20px; left: 20px; background: rgba(255,255,255,0.95); padding: 15px; border: 1px solid #ccc; border-radius: 8px; font-size: 12px; color: #333; z-index: 1000; box-shadow: 0 4px 10px rgba(0,0,0,0.1); pointer-events: none; }}
                .legend-item {{ display: flex; align-items: center; margin-bottom: 6px; }}
                .legend-item:last-child {{ margin-bottom: 0; }}
                .color-box {{ width: 16px; height: 16px; margin-right: 10px; border-radius: 3px; }}
                
                .shape-icon {{ display: inline-block; width: 20px; height: 15px; margin-right: 10px; border: 1px solid #777; }}
                .s-scalene {{ background: #00b0f0; clip-path: polygon(0 0, 100% 0, 100% 70%, 50% 100%, 0 70%); }}
                .s-oval {{ background: #00b050; border-radius: 50%; }}
                .s-pill {{ background: #bbf3ff; border-radius: 8px; }}
                .s-query-chevron {{ background: #ccffcc; clip-path: polygon(0 0, 80% 0, 100% 50%, 80% 100%, 0 100%); }}
                .s-rect-p {{ background: #ffcccc; border-radius: 2px; }}
                .s-notch {{ background: #e6ccff; clip-path: polygon(0 0, 100% 0, 100% 20%, 80% 30%, 100% 40%, 100% 60%, 80% 70%, 100% 80%, 100% 100%, 0 100%, 0 80%, 20% 70%, 0 60%, 0 40%, 20% 30%, 0 20%); }}
            </style>
        </head>
        <body>
            <div id="canvas-container">
                <svg id="svg-canvas"><g/></svg>
                <div class="legend">
                    <div style="font-weight: bold; margin-bottom: 10px; text-transform: uppercase; font-size: 10px; color: #666;">Routing Tracks</div>
                    <div class="legend-item"><div class="color-box" style="background: #e67e22;"></div> Critical Path</div>
                    <div class="legend-item"><div class="color-box" style="background: #00c3a5;"></div> Live Trace Log</div>

                    <div style="font-weight: bold; margin-top: 15px; margin-bottom: 10px; text-transform: uppercase; font-size: 10px; color: #666;">TRIRIGA Task Legend</div>
                    <div class="legend-item"><div class="shape-icon s-oval"></div> Start / End Task</div>
                    <div class="legend-item"><div class="shape-icon s-scalene"></div> Switch (Decision Gate)</div>
                    <div class="legend-item"><div class="shape-icon s-query-chevron"></div> Query Task</div>
                    <div class="legend-item"><div class="shape-icon s-pill"></div> Retrieve Task</div>
                    <div class="legend-item"><div class="shape-icon s-rect-p"></div> Modify Records</div>
                    <div class="legend-item"><div class="shape-icon s-notch"></div> Modify Metadata</div>
                </div>
            </div>
            <div id="sidepanel">
                <h2>Diagnostics Panel</h2>
                <div id="payloadData">
                    <p class="hint">Click on any Task to inspect its internal logic, database modifiers, and GUI mappings.</p>
                </div>
            </div>

            <script type="text/javascript">
                var nodesData = {json.dumps(dagre_nodes)};
                var edgesData = {json.dumps(dagre_edges)};

                edgesData.sort(function(a, b) {{
                    if (a.label === "TRUE" && b.label !== "TRUE") return -1;
                    if (a.label !== "TRUE" && b.label === "TRUE") return 1;
                    return 0;
                }});

                var g = new dagreD3.graphlib.Graph().setGraph({{
                    rankdir: 'TB',
                    nodesep: 50,   
                    edgesep: 15,
                    ranksep: 25 /* Ultra-tight vertical compression */   
                }});

                nodesData.forEach(function(n) {{
                    g.setNode(n.id, {{
                        labelType: "html",
                        label: "<div style='width:" + n.width + "px; height:" + n.height + "px;'><img src='" + n.image + "' width='" + n.width + "' height='" + n.height + "' style='display:block;'/></div>",
                        padding: 0,
                        width: n.width,
                        height: n.height,
                        customPayload: n.customPayload
                    }});
                }});

                edgesData.forEach(function(e) {{
                    var edgeConfig = {{
                        label: e.label || "",
                        style: "stroke: " + e.color + "; stroke-width: " + e.width + "px; fill: none;",
                        arrowhead: "undirected", /* Strips the arrowheads completely */
                        curve: d3.curveStepBefore 
                    }};
                    
                    if (e.source_type === '14') {{
                        if (e.label === "TRUE") {{
                            edgeConfig.tailport = 'w'; /* True path visually exits the West (Left) wall */
                        }} else {{
                            edgeConfig.tailport = 'e'; /* False path visually exits the East (Right) wall */
                        }}
                    }}
                    
                    g.setEdge(e.from, e.to, edgeConfig);
                }});

                var svg = d3.select("#svg-canvas"),
                    inner = svg.select("g");

                var zoom = d3.zoom().on("zoom", function() {{
                    inner.attr("transform", d3.event.transform);
                }});
                svg.call(zoom);

                var render = new dagreD3.render();
                render(inner, g);

                var initialScale = 0.85;
                svg.call(zoom.transform, d3.zoomIdentity.translate((document.getElementById('canvas-container').clientWidth - g.graph().width * initialScale) / 2, 40).scale(initialScale));

                inner.selectAll("g.node").on("click", function(id) {{
                    var node = g.node(id);
                    document.getElementById('payloadData').innerHTML = node.customPayload;
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
        
        msg = f"Orthogonal map successfully generated.\nOpened '{file_name}' in your default web browser."
        if not live_trace_ids:
            msg += "\n[!] Note: No Live Trace detected. Run 'trace live execution' prior to mapping to see the exact track illuminated."
            
        return wrap_ascii(user_query, msg)