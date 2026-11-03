"""Offline tests for a never-publish Threads trend draft bot."""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trend_bot as bot


class ThreadsDraftTests(unittest.TestCase):
    def setUp(self):
        self.now = bot.now_utc()
        self.demo = bot.demo_results(self.now)

    def test_demo_is_explicitly_synthetic(self):
        self.assertEqual(len(self.demo), 16)
        self.assertTrue(all(x["demo"] and x["id"].startswith("DEMO-") for x in self.demo))

    def test_search_selection_is_diverse(self):
        sources = bot.choose_sources(self.demo, self.now)
        self.assertGreaterEqual(len(sources), 4)
        self.assertLessEqual(len(sources), 8)
        self.assertGreaterEqual(len(set(x["topic"] for x in sources)), 3)

    def test_old_posts_are_excluded(self):
        row = dict(self.demo[0])
        row["timestamp"] = (self.now - timedelta(days=20)).isoformat()
        self.assertEqual(bot.choose_sources([row], self.now), [])

    def test_duplicate_posts_are_excluded(self):
        sources = bot.choose_sources([self.demo[0], self.demo[0]], self.now)
        self.assertEqual(len(sources), 1)

    def test_source_reuse_is_rejected(self):
        sources = bot.choose_sources(self.demo, self.now)
        with self.assertRaises(ValueError):
            bot.validate_drafts([{"topic":"Test","text":sources[0]["text"]}], sources)

    def test_urls_in_drafts_are_rejected(self):
        sources = bot.choose_sources(self.demo, self.now)
        with self.assertRaises(ValueError):
            bot.validate_drafts([{"topic":"Test","text":"Đây là bài viết mới khác biệt. "*5+"https://example.com"}], sources)

    def test_demo_writes_drafts_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "SOURCE_MODE": "demo"}):
                with patch.object(sys, "argv", ["trend_bot.py", "--source", "demo", "--output-dir", tmp]):
                    bot.main()
            data = json.loads((Path(tmp)/"drafts.json").read_text(encoding="utf-8"))
            self.assertEqual(data["source_mode"], "demo")
            self.assertFalse(data["published_to_threads"])
            self.assertIn("MẪU TĨNH", data["generator"])
            self.assertTrue((Path(tmp)/"drafts.md").exists())

    def test_real_api_requires_token(self):
        with self.assertRaises(RuntimeError):
            bot.fetch_threads_posts("", self.now)

    def test_gemini_json_parser(self):
        obj = bot.extract_gemini_json('{"drafts":[{"topic":"Ví dụ","text":"Văn bản"}]}')
        self.assertEqual(obj[0]["topic"], "Ví dụ")


if __name__ == "__main__":
    unittest.main()
