"""Assert precision SVG fills and geometry markers per type registry."""
import base64
import re
import unittest

from cli.visualizer import WorkflowVisualizer, _FILL


def _decode_svg(uri: str) -> str:
    return base64.b64decode(uri.split(',', 1)[1]).decode('utf-8')


def _build(t_type: str, name: str = 'Task') -> str:
    viz = WorkflowVisualizer(None)
    uri, _, _ = viz._build_svg_node(name, t_type, 'BO', {}, False, False)
    return _decode_svg(uri)


def _point_count(svg: str) -> int:
    m = re.search(r'points="([^"]+)"', svg)
    if not m:
        return 0
    return len(m.group(1).split())


class TestVizShapeRegistry(unittest.TestCase):
    def test_mapped_fills(self):
        for code, fill in _FILL.items():
            with self.subTest(type=code):
                raw = _build(code)
                self.assertIn(f'fill="{fill}"', raw)

    def test_modify_is_rounded_rect(self):
        raw = _build('28')
        self.assertIn('<rect ', raw)
        self.assertIn('rx="4"', raw)
        self.assertIn('fill="#E9C2E9"', raw)

    def test_metadata_notched_path_light_text(self):
        raw = _build('23')
        self.assertIn('<path d=', raw)
        self.assertIn(' A ', raw)
        self.assertIn('fill="#6F5DA4"', raw)
        self.assertIn('fill="#f5f5f5"', raw)

    def test_delete_ref_12gon(self):
        raw = _build('32')
        self.assertEqual(_point_count(raw), 12)
        self.assertIn('fill="#BAE7BA"', raw)

    def test_get_temp_rect(self):
        raw = _build('25')
        self.assertIn('<rect ', raw)
        self.assertIn('fill="#86A690"', raw)

    def test_call_wf_chevron(self):
        raw = _build('38')
        self.assertIn('<polygon points=', raw)
        self.assertEqual(_point_count(raw), 6)
        self.assertIn('fill="#87A690"', raw)

    def test_add_child_hex(self):
        raw = _build('33')
        self.assertEqual(_point_count(raw), 6)
        self.assertIn('fill="#CC9CFD"', raw)

    def test_break_composite(self):
        raw = _build('21')
        self.assertGreaterEqual(raw.count('<circle '), 2)
        self.assertIn('<polygon points=', raw)
        self.assertIn('fill="#BAE7BA"', raw)

    def test_set_project_path(self):
        raw = _build('34')
        self.assertIn('<path d=', raw)
        self.assertIn('fill="#FDFDD3"', raw)

    def test_iter_matches_switch_scalene(self):
        raw = _build('24')
        self.assertIn('fill="#00b0f0"', raw)
        self.assertIn('<polygon points=', raw)
        self.assertEqual(_point_count(raw), 5)
        switch = _build('14')
        self.assertIn('fill="#00b0f0"', switch)

    def test_associate_inward_chevron(self):
        raw = _build('30')
        self.assertEqual(_point_count(raw), 6)
        self.assertIn('fill="#9191D8"', raw)

    def test_populate_concave_left(self):
        raw = _build('36')
        self.assertIn('<path d=', raw)
        self.assertIn('fill="#7B92A8"', raw)

    def test_loop_switch_fill(self):
        raw = _build('20')
        self.assertIn('fill="#00b0f0"', raw)
        self.assertIn('<rect ', raw)

    def test_schedule_parallelogram(self):
        raw = _build('17')
        self.assertEqual(_point_count(raw), 4)
        self.assertIn('fill="#C4A484"', raw)

    def test_distill_concave_right(self):
        raw = _build('37')
        self.assertIn('<path d=', raw)
        self.assertIn('fill="#9E6C85"', raw)
        self.assertIn('fill="#f5f5f5"', raw)

    def test_fact_asymmetric_octagon(self):
        raw = _build('43')
        self.assertEqual(_point_count(raw), 8)
        self.assertIn('fill="#FFE600"', raw)

    def test_save_permanent_left_bites(self):
        raw = _build('26')
        self.assertIn('<path d=', raw)
        self.assertIn(' A ', raw)
        self.assertIn('fill="#7B5F96"', raw)
        self.assertIn('fill="#f5f5f5"', raw)

    def test_var_definition_hex(self):
        raw = _build('40')
        self.assertEqual(_point_count(raw), 6)
        self.assertIn('fill="#9093B8"', raw)
        self.assertNotIn('fill="#000000"', raw)

    def test_var_assignment_black_tips(self):
        raw = _build('41')
        self.assertIn('fill="#9093B8"', raw)
        self.assertIn('fill="#000000"', raw)
        self.assertGreaterEqual(raw.count('<polygon '), 3)

    def test_end_is_octagon_not_ellipse(self):
        raw = _build('9', 'End')
        self.assertNotIn('<ellipse ', raw)
        self.assertEqual(_point_count(raw), 8)
        self.assertIn('fill="#ff0000"', raw)

    def test_create_keeps_tan(self):
        raw = _build('27', 'Create X')
        self.assertIn('#c4a574', raw)


if __name__ == '__main__':
    unittest.main()
