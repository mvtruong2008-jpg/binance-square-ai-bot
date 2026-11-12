#!/usr/bin/env python3
"""Binance Square: up to five DIFFERENT coins per batch; publish only if PUBLISH=true.

Requires existing bot.py, secrets, official Binance publisher checkout, and
restored data/history.json. No synthetic market data can ever be published.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from bot import COINS, HISTORY, load_history

BATCH_SIZE = 5
MAX_ATTEMPTS = 10
POST_GAP_SECONDS = 60
SYMBOL_COOLDOWN_HOURS = 12
BATCH_COOLDOWN_HOURS = 5
MAX_POSTS_24H = 30
PRIORITY = ("BTC ETH BNB SOL XRP DOGE ADA AVAX LINK SUI "
            "DOT LTC UNI AAVE NEAR TRX ATOM ARB OP FIL XLM HBAR APT ETC").split()
PUBLISH = os.environ.get("PUBLISH", "false").strip().lower() in {"true", "1", "yes"}


def as_utc(stamp):
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def recent_posts_count(history, now):
    """Each posted story/market snapshot is stored with its unique ID."""
    return sum(
        1 for key, stamp in history.items()
        if not key.startswith(("symbol:", "batch:"))
        and (dt := as_utc(stamp)) is not None
        and timedelta(0) <= now - dt < timedelta(hours=24)
    )


def batch_is_too_recent(history, now):
    stamp = as_utc(history.get("batch:last"))
    return stamp is not None and timedelta(0) <= now-stamp < timedelta(hours=BATCH_COOLDOWN_HOURS)


def available_coins(history, now):
    """Pick least recently published coin first; never repeat within a batch."""
    order = {coin: index for index, coin in enumerate(PRIORITY)}
    candidates = []
    for coin in COINS:
        last = as_utc(history.get("symbol:" + coin))
        if last is not None and timedelta(0) <= now-last < timedelta(hours=SYMBOL_COOLDOWN_HOURS):
            continue
        candidates.append((last or datetime.min.replace(tzinfo=timezone.utc),
                           order.get(coin, 1000), coin))
    return [coin for _, _, coin in sorted(candidates)]


def stamp_batch_start():
    """Persist a guard as soon as the first real post succeeded."""
    history = load_history()
    history["batch:last"] = datetime.now(timezone.utc).isoformat()
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    import json
    HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")


def run_coin(symbol):
    env = os.environ.copy()
    env["PILOT_SYMBOL"] = symbol
    env["ALLOW_MARKET_ONLY"] = "true"
    if os.environ.get("TREND_HUNTER_ENABLED", "false").lower() in {"1", "true", "yes"}:
        if os.path.isfile("data/trend_plan.json"):
            env["TREND_PLAN_PATH"] = "data/trend_plan.json"
    # Never pass secrets on the command line.
    print(f"COIN_START: {symbol}, mode={'PUBLISH' if PUBLISH else 'PREVIEW'}", flush=True)
    try:
        result = subprocess.run(
            [sys.executable, "-u", "bot.py"], env=env, timeout=280, check=False
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"COIN_TIMEOUT: {symbol}; do not retry this coin in this batch.", flush=True)
        return False


def main():
    history = load_history()
    now = datetime.now(timezone.utc)
    if PUBLISH:
        if batch_is_too_recent(history, now):
            print("BATCH_SKIPPED: A successful batch began less than 5 hours ago.")
            return 0
        daily_count = recent_posts_count(history, now)
        if daily_count >= MAX_POSTS_24H:
            print(f"BATCH_SKIPPED: local history shows {daily_count} posts in last 24 hours.")
            return 0
    else:
        daily_count = 0

    eligible = available_coins(history, now)
    selected = eligible[:MAX_ATTEMPTS]
    # Plan the batch once rather than choose coins by rotation alone.
    # A network failure must never disable the existing publishing pipeline.
    if os.environ.get("TREND_HUNTER_ENABLED", "false").lower() in {"1", "true", "yes"} and eligible:
        try:
            from trend_hunter import plan_batch, write_plan
            ranked = plan_batch(eligible, history, now)
            if ranked:
                write_plan(ranked, "data/trend_plan.json")
                selected = [item["symbol"] for item in ranked[:MAX_ATTEMPTS]]
                for item in ranked[:MAX_ATTEMPTS]:
                    print(
                        f"TREND_CHOICE: {item['symbol']} score={item['score']:.1f} "
                        f"trending_rank={item['trend_rank']} has_news={bool(item['news'])}",
                        flush=True,
                    )
        except Exception as exc:
            print(f"TREND_FALLBACK: {type(exc).__name__}: {exc}", flush=True)
    if not selected:
        print("BATCH_SKIPPED: All coins are inside the 12-hour cooldown window.")
        return 0

    posted = 0
    failures = 0
    for coin in selected:
        if posted >= BATCH_SIZE:
            break
        if PUBLISH and daily_count + posted >= MAX_POSTS_24H:
            print("BATCH_BUDGET_REACHED: stopping at 30 locally tracked posts / 24h.")
            break
        if posted:
            print(f"COIN_GAP: waiting {POST_GAP_SECONDS}s before the next success attempt.", flush=True)
            time.sleep(POST_GAP_SECONDS)
        ok = run_coin(coin)
        if ok:
            posted += 1
            print(f"COIN_OK: {coin} ({posted}/{BATCH_SIZE})", flush=True)
            if PUBLISH and posted == 1:
                stamp_batch_start()
        else:
            failures += 1
            print(f"COIN_FAILED: {coin}; trying another coin if available.", flush=True)

    print(
        f"BATCH_SUMMARY: success={posted} failures={failures} "
        f"target={BATCH_SIZE} publish={str(PUBLISH).lower()}",
        flush=True,
    )
    if posted == BATCH_SIZE:
        return 0
    if posted == 0 and PUBLISH:
        print("BATCH_FAILURE: No posts were successfully published.", flush=True)
    else:
        print("BATCH_PARTIAL: Fewer than five coins completed; check upstream API and rate limits.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
