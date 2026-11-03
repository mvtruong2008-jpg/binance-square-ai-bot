"""Offline tests for exchanging, refreshing, and encrypted storage of Threads tokens."""
import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "token_manager.py"
sys.path.insert(0, str(FILE.parent))
spec = importlib.util.spec_from_file_location("threads_token_manager", FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TokenManagerTests(unittest.TestCase):
    def test_official_exchange_endpoint_and_parameters(self):
        with patch.object(m, "graph_get", return_value={"access_token": "NEW-LONG-TOKEN", "expires_in": 5184000}) as call:
            value, seconds = m.exchange_short_token("SHORT-TOKEN", "APP-SECRET")
        self.assertEqual(value, "NEW-LONG-TOKEN")
        self.assertEqual(seconds, 5184000)
        self.assertEqual(call.call_args.args[0], "/access_token")
        self.assertEqual(call.call_args.args[1]["grant_type"], "th_exchange_token")
        self.assertEqual(call.call_args.args[1]["client_secret"], "APP-SECRET")
        self.assertEqual(call.call_args.args[1]["access_token"], "SHORT-TOKEN")

    def test_official_refresh_endpoint_and_parameters(self):
        with patch.object(m, "graph_get", return_value={"access_token": "REFRESHED-LONG-TOKEN", "expires_in": 5184000}) as call:
            value, seconds = m.refresh_long_token("OLD-LONG-TOKEN")
        self.assertEqual(value, "REFRESHED-LONG-TOKEN")
        self.assertEqual(seconds, 5184000)
        self.assertEqual(call.call_args.args[0], "/refresh_access_token")
        self.assertEqual(call.call_args.args[1]["grant_type"], "th_refresh_token")

    def test_expiry_must_indicate_long_lived_token(self):
        with self.assertRaises(m.TokenManagerError):
            m.parse_token_response({"access_token": "TOKEN", "expires_in": 3600})

    def test_likely_app_secret_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "LIKELY_APP_SECRET"):
            m.refresh_long_token("a" * 32)

    def test_disallowed_graph_endpoint_never_makes_request(self):
        with patch("urllib.request.urlopen") as call:
            with self.assertRaises(m.TokenManagerError):
                m.graph_get("/me/threads_publish", {"grant_type": "irrelevant"})
            call.assert_not_called()

    def test_disallowed_github_endpoint_never_makes_request(self):
        with patch("urllib.request.urlopen") as call:
            with self.assertRaises(m.TokenManagerError):
                m.github_request("PUT", "/repos/other/repo/actions/secrets/KEY", "TOKEN")
            call.assert_not_called()

    def test_github_repo_is_restricted(self):
        with self.assertRaises(m.TokenManagerError):
            m.fetch_secret_public_key("PAT", "wrong/repo")

    def test_secret_encrypted_and_only_encrypted_payload_sent(self):
        with patch.object(m, "encrypt_for_github", return_value="ENCRYPTED_PLACEHOLDER"):
            with patch.object(m, "github_request", return_value={}) as send:
                m.save_long_token("UNPRINTABLE-USER-TOKEN", "PAT", m.ALLOWED_REPOSITORY, public_key=("KEY", "KEY_ID"))
        self.assertEqual(send.call_args.args[0], "PUT")
        self.assertTrue(send.call_args.args[1].endswith("/actions/secrets/THREADS_ACCESS_TOKEN"))
        self.assertEqual(send.call_args.kwargs["body"], {"encrypted_value": "ENCRYPTED_PLACEHOLDER", "key_id": "KEY_ID"})
        self.assertNotIn("UNPRINTABLE", str(send.call_args))

    def test_refresh_requires_pat_before_meta_call(self):
        with patch.dict(os.environ, {
            "THREADS_ACCESS_TOKEN": "SYNTHETIC-USER-TOKEN",
            "GH_SECRETS_PAT": "",
            "GITHUB_REPOSITORY": m.ALLOWED_REPOSITORY,
        }):
            with patch.object(m, "graph_get") as graph:
                with self.assertRaisesRegex(m.TokenManagerError, "MISSING_GH_SECRETS_PAT"):
                    m.manage_token("refresh")
                graph.assert_not_called()

    def test_preflight_gets_github_public_key_before_refresh(self):
        order = []
        with patch.dict(os.environ, {
            "THREADS_ACCESS_TOKEN": "SYNTHETIC-USER-TOKEN",
            "GH_SECRETS_PAT": "SYNTHETIC-GH-PAT",
            "GITHUB_REPOSITORY": m.ALLOWED_REPOSITORY,
        }):
            with patch.object(m, "fetch_secret_public_key", side_effect=lambda *args: (order.append("preflight") or ("KEY", "KEY_ID"))):
                with patch.object(m, "refresh_long_token", side_effect=lambda *args: (order.append("refresh") or ("LONG-NEW", 5184000))):
                    with patch.object(m, "save_long_token", side_effect=lambda *args, **kwargs: order.append("save")):
                        with redirect_stdout(io.StringIO()) as output:
                            m.manage_token("refresh")
        self.assertEqual(order, ["preflight", "refresh", "save"])
        self.assertIn("TOKEN_REFRESH_OK", output.getvalue())
        self.assertNotIn("LONG-NEW", output.getvalue())
        self.assertNotIn("SYNTHETIC", output.getvalue())

    def test_inspect_never_changes_secrets(self):
        with patch.dict(os.environ, {"THREADS_ACCESS_TOKEN": "SYNTHETIC-USER-TOKEN"}):
            with patch.object(m, "threads_get_json", return_value={"id": "a"}):
                with patch.object(m, "save_long_token") as saver:
                    with redirect_stdout(io.StringIO()) as out:
                        m.manage_token("inspect")
                    saver.assert_not_called()
        self.assertIn("TOKEN_PROFILE_OK", out.getvalue())


if __name__ == "__main__":
    unittest.main()
