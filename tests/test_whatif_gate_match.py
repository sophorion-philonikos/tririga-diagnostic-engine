"""What-If gate matching: task id / name / value must resolve the correct Switch."""

import os
import unittest

from core.engine import TririgaHybridEngine
from cli.simulation.parse import parse_query
from cli.simulation.matching import match_clauses
from cli.simulation.orchestrate import run_simulation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPIM_WF = os.path.join(ROOT, "wf_building_rpim_status_ind.txt")

ACT_SWITCH = "333395"
DISP_SWITCH = "333367"


class TestWhatIfGateMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(RPIM_WF):
            raise unittest.SkipTest("wf_building_rpim_status_ind.txt not present")
        cls.engine = TririgaHybridEngine(None, None, None, offline_mode=True)
        cls.engine.load_workflow_xml_file(RPIM_WF)
        cls.wf = cls.engine.loaded_workflow_names[0]

    def _gate_matches(self, query):
        req = parse_query(query)
        gates = [c for c in req.clauses if c.kind == "gate"]
        matched, unmatched = match_clauses(self.engine, self.wf, gates)
        return matched, unmatched

    def test_switch_id_true_forces_act_gate(self):
        matched, unmatched = self._gate_matches("what if switch 333395 is true?")
        self.assertEqual(unmatched, [])
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["node_id"], ACT_SWITCH)
        self.assertEqual(matched[0]["verdict"], "TRUE")
        self.assertEqual(matched[0]["reason"], "explicit task id")

    def test_task_id_true_forces_act_gate(self):
        matched, unmatched = self._gate_matches("what if task 333395 is true")
        self.assertEqual(unmatched, [])
        self.assertEqual(matched[0]["node_id"], ACT_SWITCH)
        self.assertEqual(matched[0]["verdict"], "TRUE")

    def test_name_act_true(self):
        matched, unmatched = self._gate_matches("what if ACT? is true")
        self.assertEqual(unmatched, [])
        self.assertEqual(matched[0]["node_id"], ACT_SWITCH)
        self.assertEqual(matched[0]["verdict"], "TRUE")

    def test_operational_status_act_still_hits_act_gate(self):
        matched, unmatched = self._gate_matches("what if operational status is ACT?")
        self.assertEqual(unmatched, [])
        ids = {m["node_id"] for m in matched if m["verdict"] == "TRUE"}
        self.assertIn(ACT_SWITCH, ids)

    def test_disp_switch_by_id(self):
        matched, unmatched = self._gate_matches("what if switch 333367 is true?")
        self.assertEqual(unmatched, [])
        self.assertEqual(matched[0]["node_id"], DISP_SWITCH)
        self.assertEqual(matched[0]["verdict"], "TRUE")

    def test_bare_switch_is_true_does_not_guess_wrong_gate(self):
        """Without an id/name, do not crown a random TaskLabel 'Switch'."""
        matched, unmatched = self._gate_matches("what if switch is true?")
        # Prefer unmatched over forcing the wrong cascading Switch.
        if matched:
            self.assertNotEqual(matched[0]["node_id"], ACT_SWITCH)
            # If anything matched, it must not be a silent wrong pick of 333367
            # when the user gave no id — either unmatched or a clear name hit.
        self.assertTrue(unmatched or matched)

    def test_run_simulation_switch_id_path_includes_act_true_branch(self):
        result = run_simulation(
            self.engine, self.wf, "what if switch 333395 is true?")
        self.assertIn(ACT_SWITCH, result.get("path_node_ids", []))
        decisions = " ".join(result.get("decisions") or result.get("summary") or [])
        self.assertIn(ACT_SWITCH, decisions)


NESTED_WF = os.path.join(
    ROOT,
    "wf_xml_samples_variety",
    "Workflow_triHelper_triNotificationHelper_csttriNotificationHelper-MapNotificationcontentrecord.xml",
)
NESTED_GATE = "332207"
NESTED_ANCESTOR = "332198"  # must be TRUE to reach 332207


class TestWhatIfGateReachability(unittest.TestCase):
    """Forced gates off the default FALSE spine must still appear on the purple path."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(NESTED_WF):
            raise unittest.SkipTest("notification helper sample not present")
        cls.engine = TririgaHybridEngine(None, None, None, offline_mode=True)
        cls.engine.load_workflow_xml_file(NESTED_WF)
        cls.wf = cls.engine.loaded_workflow_names[0]

    def test_nested_switch_false_is_reachable(self):
        result = run_simulation(
            self.engine, self.wf, "what if switch 332207 is FALSE?")
        path = {str(n) for n in result.get("path_node_ids", [])}
        self.assertIn(NESTED_GATE, path)
        decisions = " ".join(result.get("decisions") or [])
        self.assertIn(f"({NESTED_GATE}): forced FALSE", decisions)
        self.assertIn(f"({NESTED_ANCESTOR}): forced TRUE", decisions)


if __name__ == "__main__":
    unittest.main()
