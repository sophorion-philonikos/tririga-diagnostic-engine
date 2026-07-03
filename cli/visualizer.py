import os
import json
import base64
import webbrowser
import networkx as nx
import textwrap
import urllib.parse
from cli.formatters import wrap_ascii
from cli.models import TaskInsight, MechanicSection

class WorkflowVisualizer:
    def __init__(self, engine):
        self.engine = engine

    def _get_type_str(self, data):
        t = data.get('type', data.get('Type', 'Generic'))
        if isinstance(t, list): return str(t[0])
        return str(t).strip()

    def _build_svg_node(self, t_name, t_type, t_bo, payload_data, is_live, is_critical):
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
            svg_shape = f'<polygon points="2,2 {w},2 {w},{h-20} {w/2},{h} 2,{h-20}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '22':
            svg_shape = f'<polygon points="2,2 {w-15},2 {w},{mid} {w-15},{h} 2,{h}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '29':
            svg_shape = f'<rect x="2" y="2" width="{width-4}" height="{total_h-4}" rx="20" ry="20" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_width}"/>'
        elif t_type == '23':
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
        
        encoded_svg = "data:image/svg+xml;base64," + base64.b64encode(svg.encode('utf-8')).decode('utf-8')
        return encoded_svg, width, total_h

    def _build_task_insight(self, node_id, node_data, t_type, t_name, t_bo):
        """Assemble a renderer-neutral TaskInsight for the diagnostics side panel."""
        sections = self._build_mechanic_sections(node_data, t_type)
        return TaskInsight(
            task_id=str(node_id),
            name=t_name,
            type_code=str(t_type),
            bo=str(t_bo),
            mechanics=sections,
        )

    def _build_mechanic_sections(self, node_data, t_type):
        """Return structured, plain-text mechanic sections (no inline markup)."""
        sections = []

        expressions = node_data.get('Expression', [])
        if isinstance(expressions, str): expressions = [expressions]
        if expressions:
            sections.append(MechanicSection('Expressions Evaluated', list(expressions)))

        if t_type == '28':
            t_bo_raw = node_data.get('BO', 'Target Context')
            if isinstance(t_bo_raw, list): t_bo_raw = t_bo_raw[0] if t_bo_raw else 'Target Context'

            obj_records = node_data.get('ObjMappingRecords', [])
            mapping_sentences = []
            for rec in obj_records:
                t_fld = rec.get('TrgtFld')
                if not t_fld: continue
                t_bo = rec.get('TrgtBo', t_bo_raw)
                s_bo = rec.get('SrcBo', 'Source Context')
                s_fld = rec.get('SrcFld')
                val = rec.get('FldVal') or rec.get('SrcFldVal')

                source_val_text = val if val else (s_fld if s_fld else 'mapped data')
                if val and val.lower() == 'source' and s_fld:
                    source_val_text = f"'{s_fld}'"
                elif val and val.lower() == 'source':
                    source_val_text = "the source record"
                elif val:
                    source_val_text = f"'{val}'"

                mapping_sentences.append(
                    f"Field '{t_fld}' on BO '{t_bo}' is updated to {source_val_text}, sourced from BO '{s_bo}'."
                )

            if mapping_sentences:
                sections.append(MechanicSection('Data Mapping Mechanics', mapping_sentences))
            else:
                trgt_flds = node_data.get('TrgtFld', [])
                if isinstance(trgt_flds, str): trgt_flds = [trgt_flds]
                if trgt_flds:
                    sections.append(MechanicSection('Database Fields Modified', list(trgt_flds)))
        else:
            trgt_flds = node_data.get('TrgtFld', [])
            if isinstance(trgt_flds, str): trgt_flds = [trgt_flds]
            if trgt_flds:
                sections.append(MechanicSection('Database Fields Modified', list(trgt_flds)))

        gui_fields = [f for f in node_data.get('Field', []) if f != '^^']
        if isinstance(gui_fields, str): gui_fields = [gui_fields]
        if gui_fields:
            sections.append(MechanicSection('GUI Properties Modified', list(gui_fields)))

        gui_mappings = node_data.get('GUIMappings', [])
        if gui_mappings:
            mapping_strs = []
            seen = set()
            for gm in gui_mappings:
                sec = gm.get('Section', '')
                fld = gm.get('Field', '')
                entry = None
                if sec and sec != '^^': entry = f"Section: {sec}"
                elif fld and fld != '^^': entry = f"Field: {fld}"
                if entry and entry not in seen:
                    seen.add(entry)
                    mapping_strs.append(entry)
            if mapping_strs:
                sections.append(MechanicSection('Dynamic UI Targets', mapping_strs))

        filters = node_data.get('LFldName', []) + node_data.get('PField', [])
        if isinstance(filters, str): filters = [filters]
        if filters:
            sections.append(MechanicSection('Left Fields Evaluated', list(filters)))

        constants = node_data.get('ConstantValue', [])
        if isinstance(constants, str): constants = [constants]
        if constants:
            sections.append(MechanicSection('Constants Checked', list(constants)))

        return sections

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

        in_degrees = dict(graph.in_degree())
        start_nodes = [n for n, d in in_degrees.items() if d == 0]

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
            is_start = node_id in start_nodes

            svg_data_uri, node_width, node_height = self._build_svg_node(t_name, t_type, t_bo, data, is_live, is_critical)
            insight = self._build_task_insight(node_id, data, t_type, t_name, t_bo)

            dagre_nodes.append({
                'id': str(node_id),
                'image': svg_data_uri,
                'width': node_width,
                'height': node_height,
                'isStart': is_start,
                'customPayload': insight.render_html()
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
            if str(node_id) not in [n['id'] for n in dagre_nodes]: continue

            targets = get_visible_targets(node_id)
            source_data = graph.nodes[node_id]
            s_type = self._get_type_str(source_data)

            local_edges = []
            for t in targets:
                edge_key = f"{node_id}->{t}"
                if edge_key not in edge_tracker:
                    edge_tracker.add(edge_key)
                    
                    label = ""
                    
                    if s_type == '14':
                        # Truth is read from the workflow's own EventName/TargetAssociation
                        # declaration via the shared engine helper, then resolved forward
                        # through invisible junctions to the concrete visible successor.
                        truth_map = self.engine.get_switch_truth_map(source_data)
                        label = "FALSE"
                        for raw_target, verdict in truth_map.items():
                            if str(t) == str(raw_target):
                                label = verdict
                                break
                            if graph.has_node(str(raw_target)) and str(t) in [str(x) for x in get_visible_targets(str(raw_target))]:
                                label = verdict
                                break

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

                    local_edges.append({
                        'from': str(node_id),
                        'to': str(t),
                        'label': label,
                        'color': e_color,
                        'width': e_width
                    })

            # Declare each switch's edges in a CONSISTENT order (FALSE/default first, then
            # TRUE, then unlabeled). Edge declaration order is a supported Dagre input that
            # seeds the ordering phase, so applying the same order at every switch makes the
            # TRUE and FALSE branches resolve to the same side workflow-wide. That consistency
            # is what produces the clean cascading "switch ladder" layout (the FALSE/default
            # chain stays on the spine while TRUE branches peel off predictably), instead of
            # each switch being placed by whatever locally minimizes crossings.
            #
            # This is deterministic ordering (not a CSS/coordinate hack): worst case on an
            # arbitrary graph is a crossing, never a broken or mis-rendered topology.
            local_edges.sort(key=lambda x: 0 if x['label'] == 'FALSE' else (1 if x['label'] == 'TRUE' else 2))
            dagre_edges.extend(local_edges)

        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'viewer.html')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except FileNotFoundError:
            return wrap_ascii(user_query, f"ERROR: Could not find template file at {template_path}. Ensure you created the cli/templates/ directory.")

        html_content = html_content.replace('GRAPH_NODES_DATA_PLACEHOLDER', json.dumps(dagre_nodes))
        html_content = html_content.replace('GRAPH_EDGES_DATA_PLACEHOLDER', json.dumps(dagre_edges))

        file_name = f"blueprint_{wf_name.replace(' ', '_')}.html"
        file_path = os.path.join(os.getcwd(), file_name)
        
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(html_content)

        webbrowser.open('file://' + os.path.realpath(file_path))
        
        msg = f"Orthogonal map successfully generated using native vanilla pathing.\nOpened '{file_name}' in your default web browser."
        if not live_trace_ids:
            msg += "\n[!] Note: No Live Trace detected. Run 'trace live execution' prior to mapping to see the exact track illuminated."
            
        return wrap_ascii(user_query, msg)