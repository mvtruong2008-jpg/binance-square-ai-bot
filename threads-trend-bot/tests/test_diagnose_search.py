"""Tests: keyword diagnostics never print private user content, URLs or tokens."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "diagnose_search.py"
sys.path.insert(0, str(PATH.parent))
spec = importlib.util.spec_from_file_location("threads_diagnose_search", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class KeywordDiagnosticTests(unittest.TestCase):
    def test_official_minimal_search_parameters(self):
        with patch.object(m, "get_json", return_value={"data":[{"id":"fake","text":"do-not-display"}]}) as api:
            count = m.probe_search("synthetic", "AI", "RECENT")
        self.assertEqual(count, 1)
        self.assertEqual(api.call_args.args[0], "/keyword_search")
        self.assertEqual(api.call_args.args[2], {"q":"AI","search_type":"RECENT",
                         "fields":"id,text,username,permalink,timestamp","limit":10})
        self.assertNotIn("since", api.call_args.args[2])

    def test_output_contains_only_counts_not_posts_or_tokens(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"synthetic-token"}), \
             patch.object(m, "get_json", return_value={"data":[{"id":"123","text":"private-post-body"}]}):
            with redirect_stdout(io.StringIO()) as output:
                code = m.main()
        self.assertEqual(code, 0)
        self.assertIn("SEARCH_DIAGNOSIS_RESULTS", output.getvalue())
        self.assertNotIn("private-post-body", output.getvalue())
        self.assertNotIn("synthetic-token", output.getvalue())

    def test_empty_results_are_not_misreported_as_auth_failure(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN":"synthetic-token"}), \
             patch.object(m, "get_json", return_value={"data":[]}):
            with redirect_stdout(io.StringIO()) as output:
                code = m.main()
        self.assertEqual(code, 0)
        self.assertIn("SEARCH_DIAGNOSIS_EMPTY", output.getvalue())


if __name__ == "__main__":
    unittest.main()
