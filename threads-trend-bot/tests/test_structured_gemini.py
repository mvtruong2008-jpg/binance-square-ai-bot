"""Offline check that Gemini structured JSON is requested and malformed output retries."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trend_bot


class StructuredGeminiTests(unittest.TestCase):
    def setUp(self):
        self.sources = trend_bot.choose_sources(
            trend_bot.demo_results(trend_bot.now_utc()), trend_bot.now_utc()
        )

    def test_json_schema_and_two_drafts(self):
        fake = json.dumps({"drafts": [
            {"topic": "Thói quen", "angle": "Quan sát", "text": "Mình từng nghĩ dùng ít ứng dụng thì công việc sẽ chậm hơn, nhưng đôi khi ít công cụ lại giúp tập trung tốt hơn. Bạn nghĩ sao?"},
            {"topic": "Công nghệ", "angle": "Thảo luận", "text": "Một điều thú vị là chúng ta luôn tìm công cụ mới, nhưng hiếm khi hỏi điều mình thực sự muốn tiết kiệm là gì. Theo bạn đó là thời gian hay sức lực?"},
        ]}, ensure_ascii=False)
        with patch.object(trend_bot, "request_json", return_value={
            "candidates":[{"content":{"parts":[{"text":fake}]}}]
        }) as request:
            posts = trend_bot.generate_with_gemini(self.sources, "FAKE-KEY", source_mode="public")
        self.assertEqual(len(posts), 2)
        config = request.call_args.kwargs["payload"]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseSchema"]["properties"]["drafts"]["minItems"], 2)

    def test_malformed_json_is_retried_once(self):
        bad={"candidates":[{"content":{"parts":[{"text":'{"drafts":[{"oops":]}'}]}}]}
        good={"candidates":[{"content":{"parts":[{"text":'{"drafts":[{"topic":"A","angle":"B","text":"A new test post text."}]}'}]}}]}
        with patch.object(trend_bot,"request_json",side_effect=[bad,good]) as req:
            drafts=trend_bot.generate_with_gemini(self.sources,"FAKE-KEY","public")
        self.assertEqual(req.call_count,2)
        self.assertEqual(len(drafts),1)

    def test_permanent_malformed_json_fails_without_fake_output(self):
        bad={"candidates":[{"content":{"parts":[{"text":'{"drafts":['}]}}]}
        with patch.object(trend_bot,"request_json",return_value=bad):
            with self.assertRaises(RuntimeError):
                trend_bot.generate_with_gemini(self.sources,"FAKE-KEY","public")


if __name__=="__main__":
    unittest.main()
