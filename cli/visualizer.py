import os
import json
import base64
import webbrowser
import networkx as nx
import textwrap
import urllib.parse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from cli.formatters import wrap_ascii
from cli.models import TaskInsight, MechanicSection
from cli.knowledge import type_display_name
from cli import graph_utils

# Exact fills from the precision SVG registry (hex for compact SVG attrs).
_SWITCH_BLUE = '#00b0f0'
_FILL = {
    '28': '#E9C2E9',   # Modify rgb(233,194,233)
    '23': '#6F5DA4',   # Modify Metadata rgb(111,93,164)
    '32': '#BAE7BA',   # Delete Reference rgb(186,231,186)
    '25': '#86A690',   # Get Temp rgb(134,166,144)
    '38': '#87A690',   # Call Workflow rgb(135,166,144)
    '33': '#CC9CFD',   # Add Child rgb(204,156,253)
    '21': '#BAE7BA',   # Break
    '34': '#FDFDD3',   # Set Project rgb(253,253,211)
    '24': _SWITCH_BLUE,
    '30': '#9191D8',   # Associate rgb(145,145,216)
    '36': '#7B92A8',   # Populate File rgb(123,146,168)
    '20': _SWITCH_BLUE,
    '17': '#C4A484',   # Schedule light brown
    '37': '#9E6C85',   # Distill File rgb(158,108,133)
    '43': '#FFE600',   # Fact Condition
    '26': '#7B5F96',   # Save Permanent rgb(123,95,150)
    '40': '#9093B8',   # Variable Definition rgb(144,147,184)
    '41': '#9093B8',   # Variable Assignment
}
_DARK_FILLS = {'23', '26', '37'}


def _svg_text(value):
    """Escape user/task strings embedded as SVG text nodes."""
    return xml_escape(str(value), {'"': '&quot;', "'": '&apos;'})


def _stroke_for(fill, darken=0.35):
    """Derive a slightly darker border from a #RRGGBB fill."""
    fill = fill.lstrip('#')
    r, g, b = int(fill[0:2], 16), int(fill[2:4], 16), int(fill[4:6], 16)
    r = max(0, int(r * (1 - darken)))
    g = max(0, int(g * (1 - darken)))
    b = max(0, int(b * (1 - darken)))
    return f'#{r:02x}{g:02x}{b:02x}'


def _poly(points, fill, border, stroke_width):
    pts = ' '.join(f'{x},{y}' for x, y in points)
    return (
        f'<polygon points="{pts}" fill="{fill}" stroke="{border}" '
        f'stroke-width="{stroke_width}"/>'
    )


def _rect_default(w, h, fill, border, stroke_width, rx=4):
    return (
        f'<rect x="2" y="2" width="{w - 2}" height="{h - 2}" rx="{rx}" '
        f'fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'
    )


def _bite_all_corners(w, h, fill, border, stroke_width, bite=14):
    """12-gon: rectangular with all four corners bitten (cut) off."""
    b = bite
    pts = [
        (2 + b, 2), (w - b, 2), (w, 2 + b),
        (w, h * 0.35), (w, h * 0.65),
        (w, h - b), (w - b, h), (2 + b, h), (2, h - b),
        (2, h * 0.65), (2, h * 0.35), (2, 2 + b),
    ]
    return _poly(pts, fill, border, stroke_width)


def _chevron_right(w, h, fill, border, stroke_width, tip=22):
    pts = [(2, 2), (w - tip, 2), (w, h / 2), (w - tip, h), (2, h), (2 + tip * 0.45, h / 2)]
    return _poly(pts, fill, border, stroke_width)


def _chevron_inward(w, h, fill, border, stroke_width, notch=18):
    """Associate: both left and right sides point inward."""
    mid = h / 2
    pts = [
        (2, 2), (w, 2), (w - notch, mid), (w, h),
        (2, h), (2 + notch, mid),
    ]
    return _poly(pts, fill, border, stroke_width)


def _add_child_hex(w, h, fill, border, stroke_width, cut=18):
    """Thin rect with top-left and bottom-right corners diagonally cut."""
    pts = [(2 + cut, 2), (w, 2), (w, h - cut), (w - cut, h), (2, h), (2, 2 + cut)]
    return _poly(pts, fill, border, stroke_width)


def _set_project_path(w, h, fill, border, stroke_width, r=10):
    """Thin rect with TR and BL corners rounded slightly inward."""
    d = (
        f'M 2 2 '
        f'L {w - r} 2 '
        f'Q {w - r * 0.3} {2 + r * 0.7} {w} {2 + r} '
        f'L {w} {h} '
        f'L {2 + r} {h} '
        f'Q {2 + r * 0.3} {h - r * 0.7} 2 {h - r} Z'
    )
    return f'<path d="{d}" fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'


def _populate_path(w, h, fill, border, stroke_width):
    """Concave left, convex right."""
    mid = h / 2
    d = (
        f'M 18 2 '
        f'Q 2 {mid} 18 {h} '
        f'L {w - 8} {h} '
        f'Q {w + 6} {mid} {w - 8} 2 Z'
    )
    return f'<path d="{d}" fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'


def _distill_path(w, h, fill, border, stroke_width):
    """Convex left, concave right."""
    mid = h / 2
    d = (
        f'M 8 2 '
        f'Q -6 {mid} 8 {h} '
        f'L {w - 18} {h} '
        f'Q {w} {mid} {w - 18} 2 Z'
    )
    return f'<path d="{d}" fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'


def _parallelogram(w, h, fill, border, stroke_width, skew=22):
    pts = [(2 + skew, 2), (w, 2), (w - skew, h), (2, h)]
    return _poly(pts, fill, border, stroke_width)


def _fact_octagon(w, h, fill, border, stroke_width):
    """Asymmetric elongated octagon: shorter top half than bottom."""
    top_cut_x, top_cut_y = 28, h * 0.18
    bot_cut_x, bot_cut_y = 36, h * 0.78
    pts = [
        (2 + top_cut_x, 2), (w - top_cut_x, 2),
        (w, 2 + top_cut_y), (w, bot_cut_y),
        (w - bot_cut_x, h), (2 + bot_cut_x, h),
        (2, bot_cut_y), (2, 2 + top_cut_y),
    ]
    return _poly(pts, fill, border, stroke_width)


def _save_permanent_path(w, h, fill, border, stroke_width, bite=12):
    """Left-side bites only; right side fully rounded."""
    mid = h / 2
    r = min(28, h / 2 - 2)
    d = (
        f'M {2 + bite} 2 '
        f'L {w - r} 2 '
        f'A {r} {r} 0 0 1 {w - r} {h} '
        f'L {2 + bite} {h} '
        f'L 2 {h - bite} '
        f'L {2 + bite * 0.6} {mid + bite} '
        f'L 2 {mid} '
        f'L {2 + bite * 0.6} {mid - bite} '
        f'L 2 {2 + bite} Z'
    )
    return f'<path d="{d}" fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'


def _var_hex(w, h, fill, border, stroke_width, tip=16, body_fill=None, tip_fill=None):
    """Thin hex with outward side triangles. Optional split tip coloring for Assignment."""
    mid = h / 2
    body_fill = body_fill or fill
    if tip_fill is None:
        pts = [
            (2 + tip, 2), (w - tip, 2), (w, mid), (w - tip, h),
            (2 + tip, h), (2, mid),
        ]
        return _poly(pts, body_fill, border, stroke_width)
    # Composite: body rectangle-ish + black tips
    body = _poly(
        [(2 + tip, 2), (w - tip, 2), (w - tip, h), (2 + tip, h)],
        body_fill, border, stroke_width,
    )
    left = _poly([(2 + tip, 2), (2 + tip, h), (2, mid)], tip_fill, tip_fill, stroke_width)
    right = _poly([(w - tip, 2), (w, mid), (w - tip, h)], tip_fill, tip_fill, stroke_width)
    return body + left + right


def _break_composite(w, h, fill, border, stroke_width):
    """Small circular ring with rectangular arrow right then 90° down."""
    cx, cy = 36, h / 2
    r_outer, r_inner = min(22, h / 2 - 4), min(14, h / 2 - 10)
    ring = (
        f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="{fill}" '
        f'stroke="{border}" stroke-width="{stroke_width}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="#f8f9fa" '
        f'stroke="{border}" stroke-width="1"/>'
    )
    ax = cx + r_outer - 2
    arrow = _poly(
        [
            (ax, cy - 5), (w - 28, cy - 5), (w - 28, cy + 18),
            (w - 18, cy + 18), (w - 18, cy + 5), (ax + 8, cy + 5),
        ],
        fill, border, stroke_width,
    )
    return ring + arrow


def _end_octagon(w, h, fill, border, stroke_width):
    """Symmetrical stop-sign octagon."""
    cut = min(28, w * 0.12, h * 0.22)
    pts = [
        (2 + cut, 2), (w - cut, 2), (w, 2 + cut), (w, h - cut),
        (w - cut, h), (2 + cut, h), (2, h - cut), (2, 2 + cut),
    ]
    return _poly(pts, fill, border, stroke_width)


def _switch_scalene(w, h, fill, border, stroke_width):
    return _poly(
        [(2, 2), (w, 2), (w, h - 20), (w / 2, h), (2, h - 20)],
        fill, border, stroke_width,
    )


def _metadata_notch(w, h, fill, border, stroke_width):
    r = 14
    y1 = h * 0.35
    y2 = h * 0.65
    d = (
        f'M 2 2 L {w} 2 L {w} {y1 - r} A {r} {r} 0 0 0 {w} {y1 + r} '
        f'L {w} {y2 - r} A {r} {r} 0 0 0 {w} {y2 + r} L {w} {h} '
        f'L 2 {h} L 2 {y2 + r} A {r} {r} 0 0 0 2 {y2 - r} '
        f'L 2 {y1 + r} A {r} {r} 0 0 0 2 {y1 - r} Z'
    )
    return f'<path d="{d}" fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'


def _build_shape_markup(t_type, width, total_h, fill, border, stroke_width):
    """Return SVG shape element(s) for a task type inside the node bbox."""
    w = width - 2
    h = total_h - 2
    mid = total_h / 2
    t = str(t_type)

    if t in ('1', 'Trigger', 'Start'):
        return (
            f'<ellipse cx="{width / 2}" cy="{mid}" rx="{width / 2 - 2}" ry="{mid - 2}" '
            f'fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'
        )
    if t == '13':
        return (
            f'<ellipse cx="{width / 2}" cy="{mid}" rx="{width / 2 - 2}" ry="{mid - 2}" '
            f'fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'
        )
    if t == '9':
        return _end_octagon(w, h, fill, border, stroke_width)
    if t == '10':
        return (
            f'<rect x="2" y="{mid - 10}" width="{width - 4}" height="20" rx="4" '
            f'fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'
        )
    if t in ('14', '24'):
        return _switch_scalene(w, h, fill, border, stroke_width)
    if t == '22':
        return _poly(
            [(2, 2), (w - 15, 2), (w, mid), (w - 15, h), (2, h)],
            fill, border, stroke_width,
        )
    if t == '29':
        return (
            f'<rect x="2" y="2" width="{width - 4}" height="{total_h - 4}" rx="20" ry="20" '
            f'fill="{fill}" stroke="{border}" stroke-width="{stroke_width}"/>'
        )
    if t == '23':
        return _metadata_notch(w, h, fill, border, stroke_width)
    if t == '32':
        return _bite_all_corners(w, h, fill, border, stroke_width)
    if t == '38':
        return _chevron_right(w, h, fill, border, stroke_width)
    if t == '33':
        return _add_child_hex(w, h, fill, border, stroke_width)
    if t == '21':
        return _break_composite(w, h, fill, border, stroke_width)
    if t == '34':
        return _set_project_path(w, h, fill, border, stroke_width)
    if t == '30':
        return _chevron_inward(w, h, fill, border, stroke_width)
    if t == '36':
        return _populate_path(w, h, fill, border, stroke_width)
    if t == '37':
        return _distill_path(w, h, fill, border, stroke_width)
    if t == '17':
        return _parallelogram(w, h, fill, border, stroke_width)
    if t == '43':
        return _fact_octagon(w, h, fill, border, stroke_width)
    if t == '26':
        return _save_permanent_path(w, h, fill, border, stroke_width)
    if t == '40':
        return _var_hex(w, h, fill, border, stroke_width)
    if t == '41':
        return _var_hex(w, h, fill, border, stroke_width, tip_fill='#000000')
    if t == '28':
        return _rect_default(w, h, fill, border, stroke_width)
    if t == '25':
        return _rect_default(w, h, fill, border, stroke_width)
    if t == '20':
        return _rect_default(w, h, fill, border, stroke_width, rx=6)
    return _rect_default(w, h, fill, border, stroke_width)


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

        subtitle = _svg_text(type_display_name(t_type))
        t_type = str(t_type)
        safe_bo = _svg_text(t_bo)

        width = 240
        wrap_limit = 28
        text_x_offset = 20
        
        if t_type in ('14', '24'): 
            wrap_limit = 24
            text_x_offset = 15
            extra_bottom = 20
        elif t_type == '22': 
            wrap_limit = 24
            text_x_offset = 15
            extra_bottom = 0
        elif t_type in ('1', '9', '13'): 
            wrap_limit = 22
            text_x_offset = 35
            extra_bottom = 0
        elif t_type == '29': 
            wrap_limit = 26
            text_x_offset = 20
            extra_bottom = 0
        elif t_type in ('38', '30', '33', '40', '41', '17', '36', '37'):
            wrap_limit = 22
            text_x_offset = 28
            extra_bottom = 0
        else:
            extra_bottom = 0

        wrapped_name = [_svg_text(line) for line in textwrap.wrap(t_name, width=wrap_limit)]
        
        header_h = 28
        line_height = 16
        name_start_y = header_h + 20
        subtitle_y = name_start_y + (len(wrapped_name) * line_height) + 6
        
        pill_area_h = 35 if tags else 15
        total_h = subtitle_y + pill_area_h + extra_bottom

        # --- fills / fonts ---
        bg_color = '#ffffff'
        border_color = '#7f8c8d'
        font_color = '#111111'
        subtitle_color = '#444444'
        header_font_color = '#222222'
        header_label_color = '#555555'
        line_color = '#7f8c8d'

        if t_type in _FILL:
            bg_color = _FILL[t_type]
            border_color = _stroke_for(bg_color)
            if t_type in _DARK_FILLS:
                font_color = subtitle_color = header_font_color = '#f5f5f5'
                header_label_color = '#e0e0e0'
                line_color = '#cccccc'
        elif t_type in ('1', 'Trigger', 'Start'):
            bg_color, border_color = '#00b050', '#007a37'
        elif t_type == '9':
            bg_color, border_color = '#ff0000', '#b30000'
            font_color = subtitle_color = header_font_color = '#f5f5f5'
            header_label_color = '#ffe0e0'
        elif t_type == '13':
            bg_color, border_color = '#ff0000', '#b30000'
            font_color = subtitle_color = header_font_color = '#f5f5f5'
            header_label_color = '#ffe0e0'
        elif t_type == '29':
            bg_color, border_color = '#bbf3ff', '#33ccff'
        elif t_type == '22':
            bg_color, border_color = '#ccffcc', '#66cc66'
        elif t_type == '14':
            bg_color, border_color = _SWITCH_BLUE, '#007ab3'
        elif t_type == '19':
            bg_color, border_color = '#f2f2f2', '#999999'
        elif t_type == '10':
            bg_color, border_color = '#eceff4', '#5c6b7a'
        elif t_type == '31':
            bg_color, border_color = '#ffd6e7', '#eb2f96'
        elif t_type == '27':
            bg_color, border_color = '#c4a574', '#8b6914'
            font_color = '#1a1208'
            subtitle_color = '#3d2e14'
            header_font_color = '#2a1f0e'
            header_label_color = '#5c4a2a'

        stroke_width = 2
        if is_live:
            border_color = '#00c3a5'
            stroke_width = 6
        elif is_critical:
            border_color = '#e67e22'
            stroke_width = 3

        svg_shape = _build_shape_markup(t_type, width, total_h, bg_color, border_color, stroke_width)

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}">
            {svg_shape}
            <text x="{text_x_offset}" y="20" font-family="Segoe UI, Tahoma, sans-serif" font-size="11" font-weight="bold" fill="{header_label_color}">Context: <tspan fill="{header_font_color}">{safe_bo}</tspan></text>
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
                svg += f'<text x="{pill_x + 5}" y="{pill_y + 11}" font-family="Consolas, monospace" font-size="9" font-weight="bold" fill="{tag["text"]}">{_svg_text(tag["label"])}</text>'
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

    def build_html(self, wf_name, live_trace_ids=None):
        """Render the interactive blueprint for a loaded workflow and return the HTML string.

        Renderer-only: no file writes, no browser launch. Raises ValueError when the
        workflow is not loaded or the viewer template is missing.
        """
        if wf_name not in self.engine.graphs:
            raise ValueError(f"Cannot visualize: '{wf_name}' is not loaded in the engine.")

        graph = self.engine.graphs[wf_name]
        
        critical_path_nodes = []
        if nx.is_directed_acyclic_graph(graph):
            try: critical_path_nodes = nx.dag_longest_path(graph)
            except: pass

        if not live_trace_ids: live_trace_ids = []

        dagre_nodes = []
        dagre_edges = []

        parents, container_ids, members_by_container = graph_utils.compute_container_parents(
            graph, branch_map_fn=self.engine.get_branch_map,
        )
        container_successors = {
            cid: {str(s) for s in graph.successors(cid)}
            for cid in container_ids if graph.has_node(cid)
        }

        visible_child_counts = {}
        for child, parent in parents.items():
            if not graph.has_node(child):
                continue
            if graph_utils.is_invisible(graph.nodes[child]) and graph.out_degree(child) > 0:
                continue
            visible_child_counts[parent] = visible_child_counts.get(parent, 0) + 1

        # Containers with ≥1 visible child get a synthetic cluster wrapper. The
        # real task id remains a leaf (edges may touch it). Dagre forbids edges
        # on compound parents — that caused the blank-canvas rank crash.
        wrapping = {
            cid for cid in container_ids
            if visible_child_counts.get(cid, 0) >= 1
        }

        def viz_parent(nid):
            p = parents.get(nid)
            if not p:
                return None
            if p in wrapping:
                return graph_utils.cluster_wrapper_id(p)
            return p

        in_degrees = dict(graph.in_degree())
        start_nodes = [n for n, d in in_degrees.items() if d == 0]

        for node_id, data in graph.nodes(data=True):
            t_type = self._get_type_str(data)
            t_name = data.get('name', f"Task {node_id}")
            t_bo = data.get('BO', data.get('BoName', 'Context BO'))
            if isinstance(t_bo, list): t_bo = t_bo[0]
            
            if graph_utils.is_invisible(data) and graph.out_degree(node_id) > 0:
                continue

            is_live = str(node_id) in live_trace_ids
            is_critical = str(node_id) in critical_path_nodes
            is_start = node_id in start_nodes
            nid = str(node_id)
            insight = self._build_task_insight(node_id, data, t_type, t_name, t_bo)

            if nid in wrapping:
                condition = data.get('Condition', '')
                if isinstance(condition, list):
                    condition = condition[0] if condition else ''
                condition = str(condition or '').strip()
                trgt = data.get('TRGTTaskId', data.get('trgtTaskId', ''))
                if isinstance(trgt, list):
                    trgt = trgt[0] if trgt else ''
                exit_cue = condition
                if not exit_cue and str(trgt) not in ('', '-1', 'None'):
                    exit_cue = f"TRGT={trgt}"

                cluster_id = graph_utils.cluster_wrapper_id(nid)
                cluster_rec = {
                    'id': cluster_id,
                    'name': str(t_name),
                    'type': str(t_type),
                    'isCluster': True,
                    'taskId': nid,
                    'isStart': False,
                    'exitCue': exit_cue,
                    'customPayload': insight.render_html(),
                }
                outer = viz_parent(nid)
                if outer:
                    cluster_rec['parent'] = outer
                dagre_nodes.append(cluster_rec)

                svg_data_uri, node_width, node_height = self._build_svg_node(
                    t_name, t_type, t_bo, data, is_live, is_critical,
                )
                leaf_rec = {
                    'id': nid,
                    'name': str(t_name),
                    'type': str(t_type),
                    'image': svg_data_uri,
                    'width': node_width,
                    'height': node_height,
                    'isStart': is_start,
                    'isCluster': False,
                    'parent': cluster_id,
                    'customPayload': insight.render_html(),
                }
                dagre_nodes.append(leaf_rec)
                continue

            svg_data_uri, node_width, node_height = self._build_svg_node(
                t_name, t_type, t_bo, data, is_live, is_critical,
            )
            node_rec = {
                'id': nid,
                'name': str(t_name),
                'type': str(t_type),
                'image': svg_data_uri,
                'width': node_width,
                'height': node_height,
                'isStart': is_start,
                'isCluster': False,
                'customPayload': insight.render_html(),
            }
            parent = viz_parent(nid)
            if parent:
                node_rec['parent'] = parent
            dagre_nodes.append(node_rec)

        def get_visible_targets(start_id, visited=None):
            return graph_utils.visible_successors(graph, start_id, visited)

        visible_ids = {n['id'] for n in dagre_nodes}
        edge_tracker = set()
        for node_id in graph.nodes():
            if str(node_id) not in visible_ids: continue

            targets = get_visible_targets(node_id)
            source_data = graph.nodes[node_id]
            s_type = self._get_type_str(source_data)

            local_edges = []
            for t in targets:
                edge_key = f"{node_id}->{t}"
                if edge_key not in edge_tracker:
                    edge_tracker.add(edge_key)
                    
                    label = ""
                    
                    if s_type in ('14', '24'):
                        # Branch labels are read from the workflow's own EventName/
                        # TargetAssociation declaration via the shared engine helper
                        # (Switch -> TRUE/FALSE, Iter -> LOOP BODY/EXIT), then resolved
                        # forward through invisible junctions to the visible successor.
                        truth_map = self.engine.get_branch_map(source_data)
                        label = "FALSE" if s_type == '14' else "EXIT"
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
                        e_width = 6
                    elif is_edge_critical:
                        e_color = '#e67e22'
                        e_width = 3

                    is_back = graph_utils.is_loop_back_edge(
                        node_id, t, parents, container_ids, members_by_container,
                        container_successors=container_successors,
                    )
                    edge_rec = {
                        'from': str(node_id),
                        'to': str(t),
                        'label': label,
                        'color': e_color,
                        'width': e_width,
                        'live': bool(is_edge_live),
                        'constraint': not is_back,
                    }
                    if is_back:
                        edge_rec['kind'] = 'loop-back'
                    local_edges.append(edge_rec)

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
            # Iter tasks follow the same convention: the EXIT continuation stays on the
            # spine (like FALSE) while the LOOP BODY peels off (like TRUE).
            local_edges.sort(key=lambda x: 0 if x['label'] in ('FALSE', 'EXIT')
                             else (1 if x['label'] in ('TRUE', 'LOOP BODY') else 2))
            dagre_edges.extend(local_edges)

        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'viewer.html')
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
        except FileNotFoundError:
            raise ValueError(f"ERROR: Could not find template file at {template_path}. Ensure you created the cli/templates/ directory.")

        html_content = html_content.replace('GRAPH_NODES_DATA_PLACEHOLDER', json.dumps(dagre_nodes))
        html_content = html_content.replace('GRAPH_EDGES_DATA_PLACEHOLDER', json.dumps(dagre_edges))
        return html_content

    def generate_html_map(self, wf_name, user_query, live_trace_ids=None):
        try:
            html_content = self.build_html(wf_name, live_trace_ids)
        except ValueError as e:
            return wrap_ascii(user_query, str(e))

        file_name = f"blueprint_{wf_name.replace(' ', '_')}.html"
        file_path = os.path.join(os.getcwd(), file_name)
        
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(html_content)

        webbrowser.open('file://' + os.path.realpath(file_path))
        
        msg = f"Orthogonal map successfully generated using native vanilla pathing.\nOpened '{file_name}' in your default web browser."
        if not live_trace_ids:
            msg += "\n[!] Note: No Live Trace detected. Run 'trace live execution' prior to mapping to see the exact track illuminated."
            
        return wrap_ascii(user_query, msg)