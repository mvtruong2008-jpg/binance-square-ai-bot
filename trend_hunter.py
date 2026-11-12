"""Trend Hunter v2: market activity + CoinGecko trends + fresh RSS.
No trading signals or speculative claims; graceful fallback if a source fails.
Only use data from public endpoints. Existing Binance Square publishing stays unchanged.
"""
from __future__ import annotations

import concurrent.futures
import json
import math
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from bot import COINS, fetch_stories, get_json

BINANCE_TICKERS = "https://data-api.binance.vision/api/v3/ticker/24hr"
COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
MAX_NEWS_LOOKUPS = 10
MIN_NEWS_AGE = timedelta(minutes=2)
MAX_NEWS_AGE = timedelta(hours=36)


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def market_activity(symbols):
    """Fetch all supported USDT 24h tickers in a single public request."""
    pairs = [symbol + "USDT" for symbol in symbols]
    query = urllib.parse.urlencode({"symbols": json.dumps(pairs, separators=(",", ":"))})
    result = get_json(BINANCE_TICKERS + "?" + query, timeout=14)
    if not isinstance(result, list):
        raise ValueError("Binance ticker result was not a list")
    mapped = {}
    for row in result:
        if not isinstance(row, dict):
            continue
        pair = row.get("symbol", "")
        if pair not in pairs:
            continue
        symbol = pair[:-4]
        volume = max(0.0, _number(row.get("quoteVolume")))
        change = _number(row.get("priceChangePercent"))
        if volume <= 0 or _number(row.get("lastPrice")) <= 0:
            continue
        mapped[symbol] = {"quote_volume_24h": volume, "change_24h": change}
    return mapped


def trending_coins():
    """Resolve CoinGecko trending by exact coin ID, never ticker alone."""
    key = os.environ.get("COINGECKO_DEMO_KEY", "").strip()
    headers = {"x-cg-demo-api-key": key} if key else {}
    response = get_json(COINGECKO_TRENDING, headers=headers, timeout=12)
    if not isinstance(response, dict):
        return {}
    ranks = {}
    for position, entry in enumerate(response.get("coins", [])[:20], 1):
        if not isinstance(entry, dict):
            continue
        item = entry.get("item") or {}
        coin_id = item.get("id")
        if isinstance(coin_id, str) and coin_id:
            ranks[coin_id] = position
    return ranks


def market_score(metrics, rank):
    """Heuristic engagement interest, not a probability or investment rating."""
    # Moderate movement and high turnover indicate activity, not positive returns.
    volume = max(0, _number(metrics.get("quote_volume_24h")))
    change = abs(_number(metrics.get("change_24h")))
    liquidity = min(22.0, max(0.0, math.log10(volume + 1) - 5) * 5.5)
    movement = min(15.0, change * 1.8)
    trending = max(0.0, 32 - (rank - 1) * 2.5) if rank else 0.0
    return round(liquidity + movement + trending, 2)


def _fetch_symbol_news(symbol):
    try:
        return fetch_stories([symbol])
    except Exception as exc:
        print(f"TREND_NEWS_WARNING: {symbol}: {type(exc).__name__}", flush=True)
        return []


def _choose_story(symbol, stories, history, now):
    for story in stories:
        if story.get("symbol") != symbol or story.get("id") in history:
            continue
        try:
            date = datetime.fromisoformat(story["date"].replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            age = now - date.astimezone(timezone.utc)
        except (KeyError, ValueError, TypeError):
            continue
        if MIN_NEWS_AGE <= age <= MAX_NEWS_AGE:
            fresh = 24 if age <= timedelta(hours=6) else 17 if age <= timedelta(hours=18) else 8
            return story, fresh
    return None, 0


def plan_batch(candidates, history, now=None, with_news=True):
    """Return ranked, distinct, eligible symbols and their evidence records.

    Never fabricates a news event. If RSS is absent, the bot can use a labeled
    market-only snapshot; volume and change are never carried into future hours.
    """
    now = now or datetime.now(timezone.utc)
    candidates = list(dict.fromkeys(s for s in candidates if s in COINS))
    if not candidates:
        return []
    metrics, trending = {}, {}
    try:
        metrics = market_activity(candidates)
    except Exception as exc:
        print(f"TREND_MARKET_WARNING: {type(exc).__name__}: {exc}", flush=True)
    try:
        trending = trending_coins()
    except Exception as exc:
        print(f"TREND_COINGECKO_WARNING: {type(exc).__name__}: {exc}", flush=True)
    ranks = []
    for position, symbol in enumerate(candidates):
        ticker = metrics.get(symbol, {})
        trend_rank = trending.get(COINS[symbol]["gecko"])
        score = market_score(ticker, trend_rank)
        ranks.append({
            "symbol": symbol,
            "base_score": score,
            "score": score,
            "trend_rank": trend_rank,
            "quote_volume_24h": ticker.get("quote_volume_24h"),
            "change_24h": ticker.get("change_24h"),
            "original_order": position,
            "news": None,
            "news_bonus": 0,
        })
    ranks.sort(key=lambda row: (-row["base_score"], row["original_order"]))
    if with_news:
        # Bounded discovery avoids slow serial RSS requests for all 24 coins.
        lookup = ranks[:MAX_NEWS_LOOKUPS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_fetch_symbol_news, row["symbol"]): row for row in lookup}
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                story, bonus = _choose_story(row["symbol"], future.result(), history, now)
                if story:
                    row["news"] = story
                    row["news_bonus"] = bonus
                    row["score"] = round(row["base_score"] + bonus, 2)
    ranks.sort(key=lambda row: (-row["score"], row["original_order"]))
    for row in ranks:
        row.pop("original_order")
    return ranks


def write_plan(items, path):
    """The plan file is a local ephemeral artifact, not an authorization token."""
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "trend-hunter-v2",
        "items": {item["symbol"]: item for item in items},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
