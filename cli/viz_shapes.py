"""SVG shape builders for workflow map nodes.

Extracted from ``cli.visualizer`` so ``build_html`` stays the sole graph→HTML entry.
"""

from xml.sax.saxutils import escape as xml_escape

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


