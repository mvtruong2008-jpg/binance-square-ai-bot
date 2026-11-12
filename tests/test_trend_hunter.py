"""Offline tests for Trend Hunter v2. Never call external APIs or post content."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bot
import binance_batch
import trend_hunter as th


class TrendHunterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)

    def test_market_activity_reads_exact_usdt_pairs_only(self):
        fake = [
            {"symbol": "SOLUSDT", "quoteVolume": "1000000000",
             "priceChangePercent": "5.5", "lastPrice": "100"},
            {"symbol": "SOLBTC", "quoteVolume": "999999999999",
             "priceChangePercent": "100", "lastPrice": "1"},
        ]
        with patch.object(th, "get_json", return_value=fake) as fetch:
            values = th.market_activity(["SOL"])
        self.assertEqual(values["SOL"]["change_24h"], 5.5)
        self.assertEqual(len(values), 1)
        self.assertIn("symbols=", fetch.call_args.args[0])

    def test_trending_uses_exact_gecko_id_not_symbol_collision(self):
        response = {"coins": [
            {"item": {"id": "fake-coin", "symbol": "BTC"}},
            {"item": {"id": "bitcoin", "symbol": "BTC"}},
        ]}
        with patch.object(th, "get_json", return_value=response):
            ranks = th.trending_coins()
        self.assertEqual(ranks["bitcoin"], 2)
        self.assertEqual(ranks["fake-coin"], 1)

    def test_activity_score_rewards_newsworthy_activity(self):
        boring = th.market_score({"quote_volume_24h": 1000, "change_24h": 0}, None)
        active = th.market_score({"quote_volume_24h": 1_000_000_000,
                                  "change_24h": -8}, 1)
        self.assertGreater(active, boring)
        self.assertLessEqual(active, 69.0)
        self.assertEqual(th.market_score({"change_24h": "bad"}, None), 0.0)

    def test_news_is_recent_unique_and_attributed(self):
        old_story = {"id": "old", "symbol": "SOL", "date": (self.now - timedelta(days=3)).isoformat()}
        new_story = {"id": "new", "symbol": "SOL", "date": (self.now - timedelta(hours=2)).isoformat(),
                     "headline": "Solana update", "publisher": "Example"}
        chosen, bonus = th._choose_story("SOL", [old_story, new_story], {}, self.now)
        self.assertEqual(chosen["id"], "new")
        self.assertEqual(bonus, 24)
        chosen, bonus = th._choose_story("SOL", [new_story], {"new": self.now.isoformat()}, self.now)
        self.assertIsNone(chosen)
        self.assertEqual(bonus, 0)

    def test_rank_can_beat_old_coin_rotation(self):
        market = {"BTC": {"quote_volume_24h": 100_000, "change_24h": 0},
                  "SOL": {"quote_volume_24h": 1_000_000_000, "change_24h": 8}}
        with patch.object(th, "market_activity", return_value=market), \
             patch.object(th, "trending_coins", return_value={"solana": 1}):
            result = th.plan_batch(["BTC", "SOL"], {}, self.now, with_news=False)
        self.assertEqual([r["symbol"] for r in result], ["SOL", "BTC"])
        self.assertEqual(len(result), 2)
        self.assertEqual(len({r["symbol"] for r in result}), 2)

    def test_offline_sources_failure_returns_legacy_order(self):
        with patch.object(th, "market_activity", side_effect=RuntimeError("offline")), \
             patch.object(th, "trending_coins", side_effect=RuntimeError("offline")):
            result = th.plan_batch(["BTC", "ETH", "SOL"], {}, self.now, with_news=False)
        self.assertEqual([r["symbol"] for r in result], ["BTC", "ETH", "SOL"])

    def test_fresh_news_boosts_candidate(self):
        fresh = {"id": "story1", "symbol": "SOL", "date": (self.now - timedelta(hours=2)).isoformat(),
                 "headline": "Network upgrade", "publisher": "Example"}
        with patch.object(th, "market_activity", return_value={}), \
             patch.object(th, "trending_coins", return_value={}), \
             patch.object(th, "_fetch_symbol_news", side_effect=lambda sym: [fresh] if sym == "SOL" else []):
            result = th.plan_batch(["BTC", "SOL"], {}, self.now, with_news=True)
        self.assertEqual(result[0]["symbol"], "SOL")
        self.assertEqual(result[0]["news"]["id"], "story1")

    def test_plan_roundtrip_and_story_selection(self):
        story = {"id": "unique", "symbol": "SOL", "date": self.now.isoformat(),
                 "headline": "Some attributed news", "publisher": "Example"}
        records = [{"symbol": "SOL", "score": 60, "trend_rank": 2, "news": story}]
        with tempfile.TemporaryDirectory() as tmp:
            file = th.write_plan(records, Path(tmp) / "plan.json")
            with patch.dict(os.environ, {"TREND_PLAN_PATH": str(file)}), \
                 patch.object(bot, "PILOT_SYMBOL", "SOL"):
                picked = bot.planned_story({})
        self.assertEqual(picked["id"], "unique")
        self.assertEqual(picked["trend"]["rank"], 2)

    def test_old_plan_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "plan.json"
            file.write_text(json.dumps({
                "generated_at": (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
                "items": {"BTC": {"trend_rank": 1, "news": None}},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"TREND_PLAN_PATH": str(file)}), \
                 patch.object(bot, "PILOT_SYMBOL", "BTC"):
                self.assertIsNone(bot.planned_story({}))

    def test_batch_feature_flag_uses_ranked_order(self):
        ranked = [{"symbol": "SOL", "score": 70.0, "trend_rank": 1, "news": None},
                  {"symbol": "BTC", "score": 40.0, "trend_rank": None, "news": None}]
        with patch.dict(os.environ, {"TREND_HUNTER_ENABLED": "true"}), \
             patch.object(binance_batch, "PUBLISH", False), \
             patch.object(binance_batch, "load_history", return_value={}), \
             patch.object(th, "plan_batch", return_value=ranked), \
             patch.object(th, "write_plan"), \
             patch.object(binance_batch, "run_coin", return_value=True) as run, \
             patch.object(binance_batch.time, "sleep"):
            binance_batch.main()
        self.assertEqual([x.args[0] for x in run.call_args_list], ["SOL", "BTC"])


if __name__ == "__main__":
    unittest.main()
