"""Exact instrument identities, dynamic universe, closed-candle volume signals."""
from __future__ import annotations

import statistics
import urllib.parse
from datetime import timedelta

from bot import COINS
from .core import gecko_headers, number, stamp

BASE = "https://data-api.binance.vision/api/v3"
CG = "https://api.coingecko.com/api/v3"


def resolve_universe(exchange, coins, listings):
    names = {row["id"]: row for row in coins}
    mappings = {}
    for row in listings:
        if row.get("target") == "USDT" and row.get("market", {}).get("identifier") == "binance":
            symbol = row.get("base", "")
            coin = names.get(row.get("coin_id"))
            if coin and coin.get("symbol", "").upper() == symbol:
                mappings.setdefault(symbol, set()).add(coin["id"])
    result = {}
    for row in exchange.get("symbols", []):
        symbol = row.get("baseAsset", "")
        if (row.get("status") != "TRADING" or row.get("quoteAsset") != "USDT"
                or row.get("symbol") != symbol + "USDT" or not row.get("isSpotTradingAllowed", False)):
            continue
        ids = mappings.get(symbol, set())
        # Existing reviewed identities remain usable when optional CoinGecko is down.
        pinned = COINS.get(symbol)
        if pinned:
            coin_id, name = pinned["gecko"], pinned["name"]
            if ids and ids != {coin_id}:
                continue
        elif len(ids) == 1:
            coin_id = next(iter(ids))
            name = names[coin_id]["name"]
        else:
            continue  # Ambiguous or unverified symbols never enter the newsroom.
        result[symbol] = {"symbol": symbol, "pair": row["symbol"], "id": coin_id, "name": name,
                          "identity_source": "reviewed mapping" if pinned else "CoinGecko Binance instrument"}
    return result


def discover(http, state, cfg, now):
    exchange = http.json(BASE + "/exchangeInfo?permissions=SPOT&symbolStatus=TRADING&showPermissionSets=false", limit=20_000_000)
    cache = state.get("identity_cache", {})
    if not cache or now - stamp(cache["asof"]) > timedelta(days=1):
        coins = http.optional("CoinGecko identities", lambda: http.json(CG + "/coins/list", headers=gecko_headers()), [])
        listings = []
        for page in range(1, 4):
            page_data = http.optional("CoinGecko instruments", lambda p=page: http.json(
                CG + f"/exchanges/binance/tickers?page={p}&order=volume_desc&depth=false", headers=gecko_headers()), {})
            listings.extend(page_data.get("tickers", []))
        universe = resolve_universe(exchange, coins, listings)
        if coins and listings:
            state["identity_cache"] = {"asof": now.isoformat(), "universe": universe}
    else:
        # A cached identity is insufficient if the instrument is no longer trading.
        active = {r["symbol"] for r in exchange["symbols"] if r["status"] == "TRADING"}
        universe = {s: c for s, c in cache["universe"].items() if c["pair"] in active}
    tickers = http.json(BASE + "/ticker/24hr")
    ranks = http.optional("CoinGecko search", lambda: http.json(CG + "/search/trending", headers=gecko_headers()), {})
    trending = {r["item"]["id"]: i for i, r in enumerate(ranks.get("coins", []), 1)}
    candidates = []
    for row in tickers:
        symbol = row.get("symbol", "")[:-4]
        if symbol not in universe or row["symbol"] != universe[symbol]["pair"]:
            continue
        try:
            price, volume, change = number(row["lastPrice"]), number(row["quoteVolume"]), number(row["priceChangePercent"])
            asof = stamp_ms(row["closeTime"])
            if price <= 0 or volume < cfg["min_quote_volume"] or not timedelta(0) <= now - asof <= timedelta(minutes=5):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        rank = trending.get(universe[symbol]["id"])
        candidates.append({**universe[symbol], "price": price, "change": change, "volume": volume,
                           "asof": asof.isoformat(), "rank": rank, "quote": "USDT"})
    candidates.sort(key=lambda c: (abs(c["change"]) + (15 / c["rank"] if c["rank"] else 0)), reverse=True)
    result = []
    for coin in candidates[:cfg["max_market_candidates"]]:
        candles = http.optional("Binance candles " + coin["symbol"], lambda c=coin: http.json(
            BASE + "/klines?" + urllib.parse.urlencode({"symbol": c["pair"], "interval": "1h", "limit": 26})), [])
        closed = [r for r in candles if stamp_ms(r[6]) < now]
        if len(closed) < 25:
            continue
        prices = [number(r[4]) for r in closed]
        volumes = [number(r[7]) for r in closed]
        if any(p <= 0 for p in prices) or any(v < 0 for v in volumes):
            continue
        baseline = statistics.mean(volumes[-25:-1])
        coin.update(prices=prices, volume_ratio=volumes[-1] / baseline if baseline > 0 else 0,
                    candle_asof=stamp_ms(closed[-1][6]).isoformat())
        result.append(coin)
    return universe, result


def stamp_ms(value):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(number(value) / 1000, timezone.utc)


def refresh(http, coin, now):
    row = http.json(BASE + "/ticker/24hr?" + urllib.parse.urlencode({"symbol": coin["pair"]}))
    if row.get("symbol") != coin["pair"]:
        raise ValueError("Instrument mismatch")
    date = stamp_ms(row["closeTime"])
    if not timedelta(0) <= now - date <= timedelta(minutes=5):
        raise ValueError("Stale ticker")
    result = {**coin, "price": number(row["lastPrice"]), "change": number(row["priceChangePercent"]), "asof": date.isoformat()}
    if result["price"] <= 0:
        raise ValueError("Invalid price")
    return result
