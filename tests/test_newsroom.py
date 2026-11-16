"""Safety and integration tests: no live credentials or publishing required."""
import argparse
import base64
import copy
import io
import json
import os
import socket
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from newsroom import core, hunters, intelligence, market, media, performance, publisher
from newsroom.__main__ import run
from newsroom.editor import Editor, validate
from newsroom.state import State, empty_state

NOW = datetime.now(timezone.utc)


def coin(symbol="BTC", name="Bitcoin"):
    return {"symbol": symbol, "name": name, "id": "bitcoin" if symbol == "BTC" else "solana", "pair": symbol+"USDT",
            "price": 100.5, "change": -8.2, "volume": 100_000_000, "volume_ratio": 3.1, "rank": 1,
            "prices": [90+i/2 for i in range(25)], "asof": NOW.isoformat(), "quote": "USDT"}


def topic():
    return intelligence.plan([coin()], [], [], empty_state(), core.load_config(), NOW)[0]


def source(**extra):
    return {"id": "s1", "title": "Bitcoin ETF approvals bring new fund rules", "publisher": "Official", "group": "one",
            "primary": True, "symbols": ["BTC"], "category": "regulation", "url": "https://example.org/release", "published": NOW.isoformat(), **extra}


class IdentityNewsTests(unittest.TestCase):
    def test_dynamic_identity_exact_exchange_instrument(self):
        exchange = {"symbols": [{"symbol": "NEWUSDT", "baseAsset": "NEW", "quoteAsset": "USDT", "status": "TRADING", "isSpotTradingAllowed": True}]}
        coins = [{"id": "new-token", "symbol": "new", "name": "New Token"}]
        listing = [{"base": "NEW", "target": "USDT", "coin_id": "new-token", "market": {"identifier": "binance"}}]
        self.assertEqual(market.resolve_universe(exchange, coins, listing)["NEW"]["id"], "new-token")
        self.assertEqual(market.resolve_universe(exchange, coins, []), {})
        coins.append({"id": "collision", "symbol": "new", "name": "Collision"})
        listing.append({**listing[0], "coin_id": "collision"})
        self.assertEqual(market.resolve_universe(exchange, coins, listing), {})
        exchange["symbols"][0]["status"] = "BREAK"
        self.assertEqual(market.resolve_universe(exchange, coins, listing), {})

    def test_near_does_not_match_unrelated_bitcoin_story(self):
        universe = {"NEAR": {"name": "NEAR Protocol"}, "BTC": {"name": "Bitcoin"}}
        self.assertEqual(hunters.relevant("Bitcoin trades near a moving average", universe), ["BTC"])
        self.assertEqual(hunters.relevant("NEAR Protocol launches an upgrade", universe), ["NEAR"])

    def test_rss_requires_timestamp_original_url_and_freshness(self):
        feed = {"name": "Example", "group": "example", "primary": True, "url": "https://example.org/feed"}
        from email.utils import format_datetime
        items = ''.join(f'<item><title>Bitcoin ETF rules {i}</title><link>{url}</link><pubDate>{date}</pubDate></item>' for i, url, date in [
            (1, "https://example.org/1", format_datetime(NOW)),
            (2, "https://example.org/2", format_datetime(NOW-timedelta(hours=7))),
            (3, "https://news.google.com/3", format_datetime(NOW)),
            (4, "https://example.org/4", ""),
            (5, "https://example.org/5", format_datetime(NOW+timedelta(hours=1)))])
        rows = hunters.parse_feed(f'<rss><channel>{items}</channel></rss>'.encode(), feed, {"BTC": {"name": "Bitcoin"}}, NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://example.org/1")
        with self.assertRaises(ValueError):
            hunters.parse_feed(b'<!DOCTYPE x><rss/>', feed, {}, NOW)

    def test_independent_groups_and_primary_evidence_gate(self):
        cfg = core.load_config()
        s = source(primary=False)
        self.assertFalse(any(t["sources"] for t in intelligence.plan([coin()], [s], [], empty_state(), cfg, NOW)))
        second = source(id="s2", url="https://example.net/release", group="two", primary=False)
        self.assertTrue(any(t["sources"] for t in intelligence.plan([coin()], [s, second], [], empty_state(), cfg, NOW)))
        second["group"] = s["group"]
        self.assertFalse(any(t["sources"] for t in intelligence.plan([coin()], [s, second], [], empty_state(), cfg, NOW)))

    def test_exact_score_weights_and_no_fake_social(self):
        t = topic()
        for key, limit in {"freshness": 25, "community": 25, "market": 20, "trust": 20, "novelty": 10}.items():
            self.assertGreaterEqual(t["breakdown"][key], 0)
            self.assertLessEqual(t["breakdown"][key], limit)
        self.assertLessEqual(t["score"], 100)
        t["market"]["rank"] = None
        intelligence.score_topic(t, [], [], NOW)
        self.assertEqual(t["breakdown"]["community"], 0)

    def test_reddit_disabled_makes_no_network_call(self):
        http = Mock()
        with patch.dict(os.environ, {"REDDIT_ACCESS_TOKEN": ""}):
            rows, status = hunters.social(http, core.load_config(), {}, {}, NOW)
        self.assertEqual(rows, [])
        http.json.assert_not_called()
        self.assertIn("paid", status["X"])

    def test_nonfinite_and_naive_times_rejected(self):
        for value in ("nan", "inf", "-inf"):
            with self.assertRaises(ValueError):
                core.number(value)
        with self.assertRaises(ValueError):
            core.stamp("2026-11-01T10:00:00")

    def test_ticker_during_request_is_fresh_but_clock_skew_is_bounded(self):
        c = coin()
        row = {"symbol": "BTCUSDT", "closeTime": (NOW+timedelta(seconds=2)).timestamp()*1000,
               "lastPrice": "101", "priceChangePercent": "2"}
        http = Mock()
        http.json.return_value = row
        self.assertEqual(market.refresh(http, c, NOW)["price"], 101)
        row["closeTime"] = (NOW+timedelta(minutes=2)).timestamp()*1000
        with self.assertRaises(ValueError):
            market.refresh(http, c, NOW)

    def test_config_hard_cap(self):
        cfg = core.load_config()
        cfg["max_posts_24h"] = 21
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"config.json"
            path.write_text(json.dumps(cfg))
            with self.assertRaises(ValueError):
                core.load_config(path)


class EditorMediaTests(unittest.TestCase):
    def test_deterministic_facts_with_no_ai_for_market(self):
        http = Mock()
        t = topic()
        draft = Editor(http, 6).draft(t, [])
        self.assertTrue(validate(t, draft, [], NOW))
        http.json.assert_not_called()
        self.assertIn("100.5 USDT", draft["text"])
        self.assertIn("-8.20%", draft["text"])

    def test_stale_or_hallucinated_or_hype_or_duplicate_rejected(self):
        t = topic()
        draft = Editor(Mock(), 6).draft(t, [])
        for suffix in (" Buy now for guaranteed profit!", " See https://example.org", " $SOL $ETH"):
            with self.assertRaises(ValueError):
                validate(t, {**draft, "text": draft["text"]+suffix}, [], NOW)
        with self.assertRaises(ValueError):
            validate(t, draft, [], NOW+timedelta(minutes=6))
        with self.assertRaises(ValueError):
            validate(t, {**draft, "text": draft["text"].replace("100.5", "999")}, [], NOW)
        with self.assertRaises(ValueError):
            validate(t, draft, [{"event_id": t["id"], "text": draft["text"]}], NOW)

    def test_news_requires_independent_ai_grounding_and_originality(self):
        t = topic()
        t["sources"] = [source()]
        editor = Editor(Mock(), 6)
        with patch.object(editor, "ask", side_effect=[{"accepted": True, "summary": "Authorities have introduced rules governing Bitcoin funds"},
                                                      {"supported": True, "same_event": True, "independent": True}]):
            draft = editor.draft(t, [])
        self.assertTrue(validate(t, draft, [], NOW))
        draft["summary"] += " worth 999 billion"
        with self.assertRaises(ValueError):
            validate(t, draft, [], NOW)
        with patch.object(editor, "ask", side_effect=[{"accepted": True, "summary": "A new rule is in place"}, {"supported": False}]):
            with self.assertRaises(ValueError):
                editor.draft(t, [])

    def test_ai_missing_free_confirmation_never_calls_provider(self):
        http = Mock()
        editor = Editor(http, 0)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only", "X_LEI_FREE_AI_CONFIRMED": "false"}):
            with self.assertRaises(RuntimeError):
                editor.ask("test")
        http.json.assert_not_called()

    def test_original_media_three_layouts_valid_and_distinct(self):
        http = Mock()
        hashes = set()
        with tempfile.TemporaryDirectory() as tmp:
            for layout in range(3):
                result = media.produce(http, topic(), core.load_config(), tmp, layout)
                self.assertTrue(result["original"])
                self.assertEqual(media.image_check(Path(tmp)/result["path"]), result["sha256"])
                hashes.add(result["sha256"])
        self.assertEqual(len(hashes), 3)
        http.request.assert_not_called()

    def test_dashboard_escapes_untrusted_content(self):
        from newsroom.dashboard import render
        with tempfile.TemporaryDirectory() as tmp:
            render({"mode": "PREVIEW", "status": "ok", "time": "now", "threshold": 65,
                    "errors": [{"source": "RSS", "error": "<script>alert(1)</script>"}]}, tmp)
            text = Path(tmp, "index.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", text)
            self.assertIn("&lt;script&gt;", text)


class JournalPublisherTests(unittest.TestCase):
    def store(self, tmp):
        with patch.dict(os.environ, {"GH_TOKEN": "unit-test", "GITHUB_REPOSITORY": "owner/repo"}):
            store = State(Mock(), live=True, local=Path(tmp)/"state.json")
        store.sha = "revision1"
        store.api = Mock(return_value={"content": {"sha": "revision2"}})
        return store

    def test_write_ahead_reservation_durable_then_duplicate_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.store(tmp)
            draft = Editor(Mock(), 6).draft(topic(), [])
            row = store.reserve(topic(), draft, {}, core.load_config(), NOW)
            self.assertEqual(row["status"], "reserved")
            self.assertEqual(store.sha, "revision2")
            sent = json.loads(base64.b64decode(store.api.call_args.args[2]["content"]))
            self.assertEqual(sent["posts"][0]["status"], "reserved")
            with self.assertRaises(ValueError):
                store.reserve(topic(), draft, {}, core.load_config(), NOW)

    def test_conflict_rolls_back_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.store(tmp)
            store.api.side_effect = RuntimeError("HTTP 409")
            with self.assertRaises(RuntimeError):
                store.reserve(topic(), {"text": "safe", "hook": 0}, {}, core.load_config(), NOW)
            self.assertEqual(store.data["posts"], [])

    def test_daily_cap_and_spacing_include_unknown_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.store(tmp)
            store.data["posts"] = [{"event_id": str(i), "status": "unknown", "reserved_at": (NOW-timedelta(hours=2)).isoformat()} for i in range(20)]
            with self.assertRaisesRegex(ValueError, "cap"):
                store.reserve(topic(), {}, {}, core.load_config(), NOW)
            store.data["posts"] = [{"event_id": "old", "status": "reserved", "reserved_at": NOW.isoformat()}]
            with self.assertRaisesRegex(ValueError, "spacing"):
                store.reserve(topic(), {}, {}, core.load_config(), NOW)

    def test_preview_cannot_reserve(self):
        store = State(Mock(), live=False)
        with self.assertRaises(ValueError):
            store.reserve(topic(), {}, {}, core.load_config(), NOW)

    def test_archive_committed_before_old_records_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.store(tmp)
            old = {"event_id": "old", "reserved_at": (NOW-timedelta(days=16)).isoformat(), "status": "published"}
            store.data["posts"] = [old]
            store.api.side_effect = [RuntimeError("HTTP 404"), {"content": {"sha": "archived"}}]
            store.archive()
            self.assertEqual(store.data["posts"], [])
            body = store.api.call_args.args[2]
            self.assertEqual(json.loads(base64.b64decode(body["content"]))[0]["event_id"], "old")
            store.data["posts"] = [old]
            store.api.side_effect = RuntimeError("HTTP 403")
            with self.assertRaises(RuntimeError):
                store.archive()
            self.assertEqual(store.data["posts"], [old])

    def test_live_missing_journal_never_resets_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.store(tmp)
            store.api.side_effect = RuntimeError("HTTP 404")
            with self.assertRaisesRegex(RuntimeError, "state missing"):
                store.load()

    def test_stop_switch_before_subprocess(self):
        store = Mock()
        with patch.object(publisher, "control", return_value={"enabled": True, "stop": True}), patch.object(publisher.subprocess, "run") as send:
            with self.assertRaises(ValueError):
                publisher.publish(store, topic(), {}, {}, ".", core.load_config())
        store.reserve.assert_not_called()
        send.assert_not_called()

    def test_ambiguous_publish_never_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)/"skill"/"scripts"
            skill.mkdir(parents=True)
            (skill/"post-image.mjs").write_text("// test placeholder")
            store = self.store(tmp)
            t = topic()
            draft = Editor(Mock(), 6).draft(t, [])
            result = media.produce(Mock(), t, core.load_config(), tmp, 0)
            with patch.dict(os.environ, {"BINANCE_SQUARE_OPENAPI_KEY": "unit-test", "BINANCE_PUBLISHER_DIR": str(skill.parent)}), \
                    patch.object(publisher, "control", return_value={"enabled": True, "stop": False}), \
                    patch.object(publisher.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 240)) as send:
                with self.assertRaises(RuntimeError):
                    publisher.publish(store, t, draft, result, tmp, core.load_config())
                with self.assertRaises(ValueError):
                    publisher.publish(store, t, draft, result, tmp, core.load_config())
            self.assertEqual(send.call_count, 1)
            self.assertEqual(store.data["posts"][0]["status"], "unknown")

    def test_publisher_success_captures_id_and_preserves_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)/"skill"/"scripts"
            skill.mkdir(parents=True)
            (skill/"post-image.mjs").write_text("// test placeholder")
            store = self.store(tmp)
            t = topic()
            draft = Editor(Mock(), 6).draft(t, [])
            result = media.produce(Mock(), t, core.load_config(), tmp, 0)
            with patch.dict(os.environ, {"BINANCE_SQUARE_OPENAPI_KEY": "unit-test-secret", "BINANCE_PUBLISHER_DIR": str(skill.parent)}), \
                    patch.object(publisher, "control", return_value={"enabled": True, "stop": False}), \
                    patch.object(publisher.subprocess, "run", return_value=Mock(returncode=0, stdout="Success!\nID: 123456\n")) as send:
                row = publisher.publish(store, t, draft, result, tmp, core.load_config())
            self.assertEqual(row["status"], "published")
            self.assertEqual(row["post_id"], "123456")
            self.assertNotIn("unit-test-secret", str(send.call_args))


class PipelineNetworkTests(unittest.TestCase):
    def test_preview_end_to_end_without_any_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(mode="PREVIEW", config=None, state=str(Path(tmp)/"state.json"), output=str(Path(tmp)/"out"), init_state=False, import_metrics=None)
            with patch.dict(os.environ, {"GH_TOKEN": "", "GITHUB_REPOSITORY": ""}), \
                 patch("newsroom.__main__.market.discover", return_value=({"BTC": coin()}, [coin()])), \
                 patch("newsroom.__main__.market.refresh", side_effect=lambda h, c, n: c), \
                 patch("newsroom.__main__.hunters.news", return_value=[]), \
                 patch("newsroom.__main__.hunters.social", return_value=([], {})), \
                 patch("newsroom.__main__.publish") as send:
                self.assertEqual(run(args), 0)
            report = json.loads(Path(args.output, "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "preview ready")
            self.assertEqual(len(report["drafts"]), 1)
            self.assertEqual(report["posts"], [])
            send.assert_not_called()

    def test_private_url_rejected_before_network(self):
        addr = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(socket, "getaddrinfo", return_value=addr):
            with self.assertRaises(ValueError):
                core.public_url("https://example.org/x")
        for url in ("http://example.org", "https://user:pass@example.org", "file:///tmp/test"):
            with self.assertRaises(ValueError):
                core.public_url(url)

    def test_read_retries_but_write_does_not(self):
        import urllib.error
        http = core.HTTP()
        http.opener = Mock()
        http.opener.open.side_effect = urllib.error.URLError("test")
        with patch.object(core, "public_url"), patch.object(core.time, "sleep"):
            with self.assertRaises(RuntimeError):
                http.json("https://example.org")
            self.assertEqual(http.opener.open.call_count, 3)
            http.opener.open.reset_mock()
            with self.assertRaises(RuntimeError):
                http.json("https://example.org", data=b"{}")
            self.assertEqual(http.opener.open.call_count, 1)

    def test_no_fake_metrics(self):
        with self.assertRaises(ValueError):
            performance.ingest([{"post_id": "123", "source": "random"}], [])
        self.assertEqual(performance.strategy([], []), {})
        posts = [{"post_id": "123", "kind": "MARKET ALERT"}]
        rows = performance.ingest([{"post_id": "123", "source": "binance_export", "observed_at": NOW.isoformat(), "views": 10, "likes": None}], posts)
        self.assertIsNone(rows[0]["likes"])
        self.assertEqual(performance.strategy(rows, posts), {})


if __name__ == "__main__":
    unittest.main()
