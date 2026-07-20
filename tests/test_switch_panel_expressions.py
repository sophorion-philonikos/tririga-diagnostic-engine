"""Switch Diagnostics Panel: resolve p0/pN via Condition Params."""
import os
import unittest

from core.engine import TririgaHybridEngine
from cli.visualizer import (
    WorkflowVisualizer,
    _resolve_switch_expressions,
    _switch_left_field_bullets,
)

SAMPLE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "wf_xml_samples_variety",
    "Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml",
)


class TestSwitchParamHelpers(unittest.TestCase):
    def test_resolve_field_expression(self):
        params = [{
            "PId": "0",
            "PField": "triLinkedBusinessObjectLI",
            "PModule": "triRouting",
            "PBO": "triApproval",
            "PSection": "General",
        }]
        out = _resolve_switch_expressions(
            ['p0 == "Standard Contract Change Order"  '], params
        )
        self.assertEqual(out, ['triLinkedBusinessObjectLI == "Standard Contract Change Order"'])

    def test_resolve_item_expression(self):
        params = [{"PId": "0", "PItem": "Result Count", "PType": "item"}]
        out = _resolve_switch_expressions(["p0 > 1  "], params)
        self.assertEqual(out, ["Result Count > 1"])

    def test_left_fields_indented_for_field_param(self):
        params = [{
            "PId": "0",
            "PField": "triLinkedBusinessObjectLI",
            "PModule": "triRouting",
            "PBO": "triApproval",
            "PSection": "General",
        }]
        bullets = _switch_left_field_bullets(params)
        self.assertEqual(bullets, [
            "Module: triRouting",
            "  BO: triApproval",
            "  Section: General",
            "  Field: triLinkedBusinessObjectLI",
        ])

    def test_left_fields_item_fallback(self):
        params = [{"PId": "0", "PItem": "Result Count"}]
        self.assertEqual(_switch_left_field_bullets(params), ["Result Count"])


class TestSwitchPanelFromSampleXml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = TririgaHybridEngine(None, None, None, offline_mode=True)
        cls.engine.load_workflow_xml_file(SAMPLE)
        cls.viz = WorkflowVisualizer(cls.engine)
        cls.wf = next(iter(cls.engine.graphs))

    def _insight(self, task_id):
        g = self.engine.graphs[self.wf]
        data = g.nodes[str(task_id)]
        return self.viz._build_task_insight(
            str(task_id), data, data.get("type") or data.get("Type"),
            data.get("name", ""), data.get("BO", ""), g,
        )

    def test_switch_347117_field_expression_and_left_fields(self):
        # Screenshot task: Expression is p0 == "Standard Contract" (not Change Order).
        insight = self._insight("347117")
        by_h = {s.heading: s.bullets for s in insight.mechanics}
        self.assertEqual(
            by_h["Expressions Evaluated"],
            ['triLinkedBusinessObjectLI == "Standard Contract"'],
        )
        self.assertEqual(by_h["Left Fields Evaluated"], [
            "Module: triRouting",
            "  BO: triApproval",
            "  Section: General",
            "  Field: triLinkedBusinessObjectLI",
        ])
        html = insight.render_html()
        self.assertIn("triLinkedBusinessObjectLI ==", html)
        self.assertNotIn("p0 ==", html)
        self.assertIn("Module: triRouting", html)

    def test_switch_347814_change_order_expression(self):
        # XML ~4082: Change Order variant of the same field param shape.
        insight = self._insight("347814")
        by_h = {s.heading: s.bullets for s in insight.mechanics}
        self.assertEqual(
            by_h["Expressions Evaluated"],
            ['triLinkedBusinessObjectLI == "Standard Contract Change Order"'],
        )

    def test_switch_334000_item_expression(self):
        insight = self._insight("334000")
        by_h = {s.heading: s.bullets for s in insight.mechanics}
        self.assertEqual(by_h["Expressions Evaluated"], ["Result Count > 1"])
        self.assertEqual(by_h["Left Fields Evaluated"], ["Result Count"])


if __name__ == "__main__":
    unittest.main()
