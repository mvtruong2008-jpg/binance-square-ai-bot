"""Offline tests for Binance's five-coin batch planner and publish safeguards."""
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from unittest.mock import patch

import binance_batch as b


class BinanceBatchTests(unittest.TestCase):
    def setUp(self):
        # Legacy rotation tests must not inherit the live trend feature flag.
        # New ranking behaviour has its own independently isolated tests.
        env_patch = patch.dict(os.environ, {"TREND_HUNTER_ENABLED": "false"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.now = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)

    def test_five_unique_coin_plan(self):
        selected = b.available_coins({}, self.now)
        self.assertEqual(selected[:5], ["BTC", "ETH", "BNB", "SOL", "XRP"])
        self.assertEqual(len(selected), len(set(selected)))
        self.assertEqual(len(selected), 24)

    def test_recent_coin_not_used(self):
        history = {"symbol:BTC": (self.now - timedelta(hours=1)).isoformat()}
        self.assertNotIn("BTC", b.available_coins(history, self.now)[:10])

    def test_old_coin_becomes_eligible(self):
        history = {"symbol:BTC": (self.now - timedelta(hours=14)).isoformat()}
        self.assertIn("BTC", b.available_coins(history, self.now))

    def test_count_ignores_batch_and_symbol_markers(self):
        recent = (self.now - timedelta(hours=1)).isoformat()
        history = {"story_123": recent, "market:foo": recent,
                   "symbol:BTC": recent, "batch:last": recent,
                   "old": (self.now - timedelta(days=7)).isoformat()}
        self.assertEqual(b.recent_posts_count(history, self.now), 2)

    def test_recent_batch_stops_redundant_trigger(self):
        history = {"batch:last": (self.now - timedelta(hours=1)).isoformat()}
        self.assertTrue(b.batch_is_too_recent(history, self.now))
        history["batch:last"] = (self.now - timedelta(hours=6)).isoformat()
        self.assertFalse(b.batch_is_too_recent(history, self.now))

    def test_old_batch_does_not_stop_next_scheduled_run(self):
        history = {"batch:last": (self.now - timedelta(hours=6, minutes=10)).isoformat()}
        self.assertFalse(b.batch_is_too_recent(history, self.now))

    def test_five_attempts_with_preview_flag_and_no_secret_output(self):
        with patch.object(b, "PUBLISH", False), \
             patch.object(b, "load_history", return_value={}), \
             patch.object(b, "run_coin", return_value=True) as runner, \
             patch.object(b.time, "sleep") as sleep:
            with redirect_stdout(io.StringIO()) as output:
                code = b.main()
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertIn("publish=false", output.getvalue())

    def test_backup_coins_used_after_failure(self):
        def report(coin):
            return coin != "ETH"
        with patch.object(b, "PUBLISH", False), \
             patch.object(b, "load_history", return_value={}), \
             patch.object(b, "run_coin", side_effect=report) as runner, \
             patch.object(b.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                code = b.main()
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_count, 6)
        self.assertNotEqual(runner.call_args_list[0].args[0], runner.call_args_list[1].args[0])

    def test_publish_recent_batch_skips_before_subprocess(self):
        history = {"batch:last": datetime.now(timezone.utc).isoformat()}
        with patch.object(b, "PUBLISH", True), \
             patch.object(b, "load_history", return_value=history), \
             patch.object(b, "run_coin") as runner:
            with redirect_stdout(io.StringIO()) as output:
                code = b.main()
        self.assertEqual(code, 0)
        runner.assert_not_called()
        self.assertIn("BATCH_SKIPPED", output.getvalue())

    def test_published_batch_marks_guard_after_first_success(self):
        with patch.object(b, "PUBLISH", True), \
             patch.object(b, "load_history", return_value={}), \
             patch.object(b, "run_coin", return_value=True), \
             patch.object(b, "stamp_batch_start") as mark, \
             patch.object(b.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                code = b.main()
        self.assertEqual(code, 0)
        mark.assert_called_once()


if __name__ == "__main__":
    unittest.main()
