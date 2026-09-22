import unittest
from valheim_codex.progress import Progress


class ProgressTests(unittest.TestCase):
    def test_feedback_detects_supply_progress_and_bounds_history(self):
        tracker = Progress()
        def context(n):
            return tracker.context({"status": {"supplies": [{"name": "Wood", "count": n}]}})
        self.assertEqual(context(1)["progress"]["observations_without_supply_change"], 0)
        self.assertEqual(context(1)["progress"]["observations_without_supply_change"], 1)
        self.assertEqual(context(2)["progress"]["observations_without_supply_change"], 0)
        for _ in range(20):
            tracker.record({"note": "a", "action": None}, {"ok": False})
        self.assertEqual(len(context(2)["progress"]["recent_actions"]), 6)

