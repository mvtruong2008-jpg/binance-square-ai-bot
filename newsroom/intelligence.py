from __future__ import annotations

import math
from datetime import timedelta

from .core import fingerprint, similarity, stamp
from .hunters import cluster


def score_topic(topic, social, history, now):
    age = max(0, (now - stamp(topic["published"])).total_seconds() / 3600)
    coin = topic["market"]
    sources = topic["sources"]
    independent = len({s["group"] for s in sources})
    points = sum(r["net_score"] + r["comments"] * 2 for r in social if coin["symbol"] in r["symbols"])
    # Search rank is a measured interest signal; market turnover is not social engagement.
    community = min(25, (max(0, 22 - coin["rank"]) if coin.get("rank") else 0) + math.log10(1 + points) * 4)
    activity = min(20, abs(coin["change"]) * 2 + max(0, coin["volume_ratio"] - 1) * 5)
    repeated = any(similarity(topic["title"], r.get("title", "")) >= .55 for r in history
                   if topic["sources"] or now - stamp(r["reserved_at"]) < timedelta(hours=24))
    breakdown = {"freshness": max(0, 25 * (1 - age / 6)), "community": community, "market": activity,
                 "trust": 20 if not sources or any(s["primary"] for s in sources) else min(20, 8 * independent),
                 "novelty": 0 if repeated else 10}
    topic["breakdown"] = {k: round(v, 2) for k, v in breakdown.items()}
    topic["score"] = round(sum(breakdown.values()), 2)
    topic["independent_sources"] = independent
    topic["duplicate"] = repeated
    return topic


def plan(markets, stories, social, state, cfg, now):
    mapped = {r["symbol"]: r for r in markets}
    history = [r for r in state.get("posts", []) if now - stamp(r["reserved_at"]) < timedelta(days=7)]
    topics = []
    for group in cluster(stories):
        lead = group[0]
        # Macro news can use a BTC quote explicitly labelled as separate market context.
        coin = next((mapped[s] for s in lead["symbols"] if s in mapped), None)
        if coin is None and lead["category"] in {"macro", "regulation"}:
            coin = mapped.get("BTC")
        if coin is None:
            continue
        if not any(s["primary"] for s in group) and len({s["group"] for s in group}) < 2:
            continue
        kind = "WHALE WATCH" if lead["category"] == "whale" else "BREAKING NEWS" if (now-stamp(lead["published"])).total_seconds() < 3600 else "CRYPTO INSIGHT"
        topics.append({"id": lead["id"], "title": lead["title"], "published": lead["published"], "sources": group,
                       "market": coin, "kind": kind, "category": lead["category"]})
    for coin in markets:
        if abs(coin["change"]) < cfg["movement_percent"] and coin["volume_ratio"] < cfg["volume_ratio"] and not coin["rank"]:
            continue
        signal = "volume" if coin["volume_ratio"] >= cfg["volume_ratio"] else "movement" if abs(coin["change"]) >= cfg["movement_percent"] else "search"
        # Bucket changes by direction and signal, not every price tick or workflow ID.
        key = f"market {coin['id']} {signal} {'up' if coin['change'] >= 0 else 'down'} {now.strftime('%Y-%m-%d')}"
        kind = "MARKET ALERT" if signal in {"volume", "movement"} else "TREND WATCH"
        if signal == "movement" and abs(coin["change"]) < 5:
            kind = "MARKET ANALYSIS"
        topics.append({"id": fingerprint(key), "title": coin["name"] + " " + signal + " market observation",
                       "published": coin["asof"], "sources": [], "market": coin, "kind": kind, "category": signal})
    for topic in topics:
        score_topic(topic, social, history, now)
        if any(topic["id"] == r["event_id"] for r in history):
            topic["duplicate"] = True
    return sorted(topics, key=lambda t: t["score"], reverse=True)
