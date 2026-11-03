"""Offline safety checks: no Threads write operations, no secret logging."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

MOD = Path(__file__).resolve().parents[1] / "check_api.py"
spec = importlib.util.spec_from_file_location("threads_api_check", MOD)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ReadOnlyApiTests(unittest.TestCase):
    def test_only_allowed_paths(self):
        with self.assertRaises(ValueError):
            checker.get_json("/me/threads_publish", "fake-token")

    def test_missing_token_does_not_make_http_request(self):
        with patch("urllib.request.urlopen") as get:
            with self.assertRaises(RuntimeError):
                checker.get_json("/me", "")
            get.assert_not_called()

    def test_app_secret_shape_is_rejected_before_network(self):
        fake_32_hex = "a" * 32
        with patch("urllib.request.urlopen") as request:
            with self.assertRaisesRegex(RuntimeError, "LIKELY_APP_SECRET"):
                checker.get_json("/me", fake_32_hex)
            request.assert_not_called()

    def test_nonsecret_synthetic_token_is_not_rejected(self):
        self.assertEqual(checker.ensure_user_access_token(" synthetic-USER-TOKEN "), "synthetic-USER-TOKEN")

    def test_http_401_retries_graph_query_auth_without_logging_token(self):
        import urllib.error
        import urllib.parse
        synthetic = "SYNTHETIC-USER-TOKEN"
        unauthorized = urllib.error.HTTPError("https://graph.threads.net/v1.0/me", 401, "Unauthorized", None, None)
        with patch("urllib.request.urlopen", side_effect=[unauthorized, io.BytesIO(b'{"id":"123"}')]) as transport:
            with redirect_stdout(io.StringIO()) as output:
                data = checker.get_json("/me", synthetic, {"fields": "id"})
        self.assertEqual(data["id"], "123")
        self.assertEqual(transport.call_count, 2)
        first = transport.call_args_list[0].args[0]
        second = transport.call_args_list[1].args[0]
        self.assertNotIn(synthetic, first.full_url)
        self.assertIn("access_token=" + urllib.parse.quote(synthetic), second.full_url)
        self.assertNotIn(synthetic, output.getvalue())

    def test_http_401_both_auth_methods_fail_without_secret_in_error(self):
        import urllib.error
        synthetic = "SYNTHETIC-USER-TOKEN"
        err = urllib.error.HTTPError("https://graph.threads.net/v1.0/me", 401, "Unauthorized", None, None)
        with patch("urllib.request.urlopen", side_effect=[err, err]) as transport:
            with self.assertRaisesRegex(RuntimeError, "THREADS_AUTH_FAILED") as raised:
                checker.get_json("/me", synthetic, {"fields": "id"})
        self.assertNotIn(synthetic, str(raised.exception))
        self.assertEqual(transport.call_count, 2)

    def test_missing_secret_has_clear_status(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": ""}):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(checker.main(), 2)
            self.assertIn("NOT_CONFIGURED", output.getvalue())

    def test_check_profile_and_search_without_real_api(self):
        def fake_api(path, token, params=None):
            self.assertEqual(token, "fake-secret")
            if path == "/me":
                return {"id": "123", "username": "example"}
            self.assertEqual(path, "/keyword_search")
            return {"data": [{"id": "abc"}]}
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "fake-secret"}):
            with patch.object(checker, "get_json", side_effect=fake_api):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(checker.main(), 0)
            self.assertIn("PROFILE_OK", output.getvalue())
            self.assertIn("READ_ONLY_OK", output.getvalue())
            self.assertNotIn("fake-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
