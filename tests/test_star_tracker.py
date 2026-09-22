import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


spec = importlib.util.spec_from_file_location(
    "star_tracker", Path(__file__).resolve().parents[1] / "scripts/update-stars.py")
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)


class StarTrackerTests(unittest.TestCase):
    def test_same_day_refresh_replaces_count_and_allows_unstars(self):
        samples = [{"date": "2026-01-01", "stars": 5}]
        samples = tracker.record_sample(samples, "2026-01-02", 4)
        self.assertEqual(tracker.record_sample(samples, "2026-01-02", 3), [
            {"date": "2026-01-01", "stars": 5},
            {"date": "2026-01-02", "stars": 3},
        ])

    def test_invalid_counts_do_not_become_zero(self):
        for count in (None, -1, True, "0", 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                tracker.record_sample([], "2026-01-01", count)

    def test_zero_and_large_count_charts_are_valid_svg(self):
        for count in (0, 1, 1000000):
            samples = tracker.record_sample([], "2026-01-01", count)
            for content in (tracker.badge_svg(count), tracker.chart_svg(samples)):
                root = ET.fromstring(content)
                self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
                self.assertIn(f"{count:,}", content)
                self.assertNotIn("nan", content.lower())

    def test_api_failure_preserves_saved_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder)
            for name in ("star-history.json", "star-history.svg", "stars.svg"):
                (media / name).write_text("existing data")
            with patch.object(tracker, "MEDIA", media), \
                    patch.dict(tracker.os.environ, {"GITHUB_REPOSITORY": "example/project"}), \
                    patch.object(tracker.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gh")):
                with self.assertRaises(subprocess.CalledProcessError):
                    tracker.main()
            self.assertTrue(all(p.read_text() == "existing data" for p in media.iterdir()))

    def test_stores_only_dates_and_aggregate_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder)
            with patch.object(tracker, "MEDIA", media), \
                    patch.dict(tracker.os.environ, {"GITHUB_REPOSITORY": "example/project"}), \
                    patch.object(tracker.subprocess, "run", return_value=subprocess.CompletedProcess("gh", 0, "7\n")):
                tracker.main()
            sample = json.loads((media / "star-history.json").read_text())[0]
            self.assertEqual(set(sample), {"date", "stars"})
            self.assertEqual(sample["stars"], 7)


if __name__ == "__main__":
    unittest.main()
