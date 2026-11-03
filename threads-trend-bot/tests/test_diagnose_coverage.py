"""No-network tests for privacy-preserving Threads search coverage diagnostics."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "diagnose_coverage.py"
sys.path.insert(0, str(PATH.parent))
spec = importlib.util.spec_from_file_location("threads_coverage", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CoverageDiagnosticTests(unittest.TestCase):
    def test_own_thirdparty_and_age_counts(self):
        now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        posts = [
            {"username": "owner", "text": "A"*60, "timestamp": "2026-11-03T10:00:00+00:00"},
            {"username": "other", "text": "B"*90, "timestamp": "2026-11-03T11:00:00+00:00"},
            {"username": "other", "text": "short", "timestamp": "2026-10-20T00:00:00+00:00"},
        ]
        stats = m.classify_search_data({"username": "OWNER"}, posts, now)
        self.assertEqual(stats["results"], 3)
        self.assertEqual(stats["own"], 1)
        self.assertEqual(stats["other"], 2)
        self.assertEqual(stats["recent72h"], 2)
        self.assertEqual(stats["recent_and_long"], 2)

    def test_no_post_details_appear_in_logs(self):
        def fake_get(path, token, params):
            if path == "/me":
                return {"id":"user123", "username":"private-owner"}
            return {"data":[{"id":"123","username":"private-owner",
                             "text":"very-private-"*9,"timestamp":"2026-11-03T12:00:00+00:00"}]}
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"synthetic-token"}), \
             patch.object(m, "get_json", side_effect=fake_get):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(), 0)
        self.assertIn("COVERAGE_OWN: 1", output.getvalue())
        for secret in ("synthetic-token","private-owner","very-private","user123"):
            self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
