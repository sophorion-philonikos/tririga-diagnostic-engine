"""Contract: RUNBOOK.md documents the primary execution commands."""

import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNBOOK = os.path.join(ROOT, "RUNBOOK.md")
VIEWER = os.path.join(ROOT, "cli", "templates", "viewer.html")
INDEX = os.path.join(ROOT, "web", "static", "index.html")


class TestRunbookExists(unittest.TestCase):
    def test_runbook_file_exists(self):
        self.assertTrue(os.path.isfile(RUNBOOK), "RUNBOOK.md missing at repo root")

    def test_runbook_lists_core_commands(self):
        with open(RUNBOOK, encoding="utf-8") as fh:
            text = fh.read()
        for needle in (
            "python3 main.py --web",
            "python3 main.py --offline",
            "python3 -m unittest discover -s tests -v",
            "pip install -r requirements.txt",
        ):
            self.assertIn(needle, text, "RUNBOOK.md missing: " + needle)


class TestUxMessageContracts(unittest.TestCase):
    def test_viewer_selection_and_isolate_messages(self):
        with open(VIEWER, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("tririga-selection", html)
        self.assertIn("tririga-isolate", html)
        self.assertIn("is-zooming", html)
        self.assertIn("data-lod", html)
        self.assertIn("iso-dim", html)
        self.assertIn(".node.search-hit", html)
        self.assertIn(".node.sim-failed", html)
        self.assertIn(".node.sim-altered", html)
        self.assertIn("drop-shadow", html)

    def test_web_analysis_dock(self):
        with open(INDEX, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("analysisDock", html)
        self.assertIn("focusContext", html)
        self.assertIn("tririga-selection", html)
        self.assertIn("tririga-isolate", html)
        self.assertIn("dock-collapsed", html)


if __name__ == "__main__":
    unittest.main()
