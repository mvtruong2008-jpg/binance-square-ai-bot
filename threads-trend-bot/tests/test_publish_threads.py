"""Offline regression tests for the official, opt-in Threads publisher."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_threads as p


class ThreadsPublisherTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)
        self.text = ("Nếu được chọn lại một thói quen công nghệ, mình sẽ ưu tiên "
                     "công cụ giúp tiết kiệm thời gian thay vì thêm một ứng dụng mới. "
                     "Bạn sẽ thay đổi điều gì đầu tiên?")
        self.drafts = [{"topic": "Công nghệ", "angle": "Cách nhìn mới", "text": self.text}]

    def test_recent_posts_cooldown_and_daily_count(self):
        posts = [
            {"text":"test","timestamp":(self.now-timedelta(hours=2)).isoformat()},
            {"text":"test2","timestamp":(self.now-timedelta(hours=9)).isoformat()},
            {"text":"ancient","timestamp":(self.now-timedelta(days=4)).isoformat()},
        ]
        count, newest = p.published_recently(posts, self.now)
        self.assertEqual(count, 2)
        self.assertAlmostEqual(newest, 2)

    def test_duplicate_draft_rejected(self):
        self.assertIsNone(p.choose_unpublished(self.drafts, [{"text":self.text}]))
        self.assertIsNotNone(p.choose_unpublished(self.drafts, [{"text":"Totally unrelated and short."}]))

    def test_unapproved_endpoint_rejected_before_http(self):
        with patch("urllib.request.urlopen") as net:
            with self.assertRaisesRegex(p.PublisherError,"THREADS_ENDPOINT_NOT_ALLOWED"):
                p.graph_call("POST","/me/likes","synthetic-token",{})
            net.assert_not_called()

    def test_two_step_post_uses_official_meta_paths(self):
        with patch.object(p, "graph_call", side_effect=[{"id":"987654321"},{"id":"123456789"}]) as api:
            container=p.create_container("synthetic",self.text)
            thread=p.publish_container("synthetic",container)
        self.assertEqual(container,"987654321")
        self.assertEqual(thread,"123456789")
        self.assertEqual(api.call_args_list[0].args[1],"/me/threads")
        self.assertEqual(api.call_args_list[0].args[0],"POST")
        self.assertEqual(api.call_args_list[0].args[3]["media_type"],"TEXT")
        self.assertNotIn("auto_publish_text",api.call_args_list[0].args[3])
        self.assertEqual(api.call_args_list[1].args[1],"/me/threads_publish")
        self.assertEqual(api.call_args_list[1].args[3]["creation_id"],"987654321")

    def test_bad_draft_does_not_create_container(self):
        with patch.object(p,"graph_call") as call:
            with self.assertRaisesRegex(p.PublisherError,"TEXT_UNSAFE"):
                p.create_container("synthetic",self.text + " https://example.com")
            call.assert_not_called()

    def test_publish_preview_never_checks_tokens_or_posts(self):
        sources = [{"topic":"Tech","text":"some source content","id":"1"} for _ in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{"GEMINI_API_KEY":"synthetic-gemini","THREADS_ACCESS_TOKEN":""}):
                with patch.object(sys,"argv",["publish_threads.py","--mode","preview","--output-dir",tmp]):
                    with patch.object(p,"fetch_public_trends",return_value=sources):
                        with patch.object(p,"choose_sources",return_value=sources):
                            with patch.object(p,"generate_with_gemini",return_value=self.drafts):
                                with patch.object(p,"validate_drafts",return_value=self.drafts):
                                    with patch.object(p,"graph_call") as graph:
                                        with redirect_stdout(io.StringIO()) as out:
                                            p.main()
                                        graph.assert_not_called()
            result=json.loads((Path(tmp)/"publish_preview.json").read_text())
            self.assertFalse(result["published_to_threads"])
            self.assertIn("PUBLISH_DISABLED",out.getvalue())
            self.assertFalse((Path(tmp)/"publish_result.json").exists())

    def test_publish_skips_when_last_post_recent(self):
        recent = [{"timestamp":datetime.now(timezone.utc).isoformat(),"text":"hello"}]
        with patch.dict(os.environ,{"THREADS_ACCESS_TOKEN":"synthetic-token"}):
            with patch.object(sys,"argv",["publish_threads.py","--mode","publish"]):
                with patch.object(p,"threads_get_json",return_value={"id":"123"}), \
                     patch.object(p,"get_recent_own_posts",return_value=recent), \
                     patch.object(p,"fetch_public_trends") as sources:
                    with redirect_stdout(io.StringIO()) as out:
                        p.main()
                    sources.assert_not_called()
                    self.assertIn("SKIP_COOLDOWN",out.getvalue())

    def test_successful_publish_creates_public_post_id_artifact_not_token(self):
        sources=[{"topic":"Tech","text":"public signal","id":"1"} for _ in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,{"THREADS_ACCESS_TOKEN":"synthetic-user-token","GEMINI_API_KEY":"synthetic-gemini"}):
                with patch.object(sys,"argv",["publish_threads.py","--mode","publish","--output-dir",tmp]):
                    with patch.object(p,"threads_get_json",return_value={"id":"123"}), \
                         patch.object(p,"get_recent_own_posts",return_value=[]), \
                         patch.object(p,"fetch_public_trends",return_value=sources), \
                         patch.object(p,"choose_sources",return_value=sources), \
                         patch.object(p,"generate_with_gemini",return_value=self.drafts), \
                         patch.object(p,"validate_drafts",return_value=self.drafts), \
                         patch.object(p,"create_container",return_value="123"), \
                         patch.object(p,"publish_container",return_value="789") as published:
                        with redirect_stdout(io.StringIO()) as out:
                            p.main()
            result=json.loads((Path(tmp)/"publish_result.json").read_text())
            self.assertTrue(result["published_to_threads"])
            self.assertEqual(result["post_id"],"789")
            self.assertNotIn("synthetic-user-token",str(result)+out.getvalue())
            published.assert_called_once()

    def test_container_requires_numeric_id(self):
        with patch.object(p,"graph_call",return_value={"id":"unexpected"}):
            with self.assertRaisesRegex(p.PublisherError,"THREADS_CONTAINER_ID_MISSING"):
                p.create_container("synthetic",self.text)


if __name__ == "__main__":
    unittest.main()
