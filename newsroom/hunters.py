"""Publisher-owned RSS, official macro releases and authorized social APIs."""
from __future__ import annotations

import html
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .core import fingerprint, similarity, stamp, words

EVENTS = {
    "listing": r"\b(list(?:ing|s|ed)?|launchpool)\b",
    "delisting": r"\b(delist\w*|remov\w* trading)\b",
    "unlock": r"\b(unlock\w*|vesting)\b",
    "airdrop": r"\bairdrop\w*\b",
    "upgrade": r"\b(upgrade\w*|hard fork|mainnet)\b",
    "whale": r"\b(whale\w*|large transfer)\b",
    "macro": r"\b(federal reserve|interest rate|inflation|fomc|tariff|sanction|ecb|war|oil)\b",
    "regulation": r"\b(sec|etf|regulat\w*|lawsuit|court)\b",
}


def clean(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()[:400]


def category(title):
    return next((name for name, pattern in EVENTS.items() if re.search(pattern, title, re.I)), "crypto")


def relevant(title, universe):
    lower = title.casefold()
    symbols = []
    for symbol, coin in universe.items():
        name = coin["name"].casefold()
        # Short/common words (NEAR, OP, GAS, etc.) are never treated as token names.
        name_match = len(name) >= 5 and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", lower)
        ticker_match = re.search(r"(?<!\w)\$" + re.escape(symbol) + r"(?!\w)", title)
        if name_match or ticker_match or (symbol == "BTC" and "bitcoin" in lower):
            symbols.append(symbol)
    return symbols


def parse_feed(body, feed, universe, now, hours=6):
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Unsafe XML")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ValueError("Invalid RSS XML") from None
    records = []
    atom = "{http://www.w3.org/2005/Atom}"
    items = root.findall("./channel/item") + root.findall(atom + "entry")
    for item in items[:80]:
        title = clean(item.findtext("title") or item.findtext(atom + "title"))
        date = item.findtext("pubDate") or item.findtext(atom + "published") or item.findtext(atom + "updated")
        try:
            try:
                published = parsedate_to_datetime(date)
                if published.tzinfo is None:
                    continue
            except (TypeError, ValueError):
                published = stamp(date)
            if not timedelta(0) <= now - published <= timedelta(hours=hours):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        link = item.findtext("link")
        if not link:
            elem = item.find(atom + "link")
            link = elem.get("href", "") if elem is not None else ""
        # Store publisher links only. Aggregator/search URLs do not count as evidence.
        host = urllib.parse.urlsplit(link or "").hostname or ""
        feed_host = urllib.parse.urlsplit(feed["url"]).hostname or ""
        if not link or not link.startswith("https://") or host.removeprefix("www.") != feed_host.removeprefix("www."):
            continue
        symbols = list(dict.fromkeys(relevant(title, universe) + [s for s in feed.get("symbols", []) if s in universe]))
        kind = category(title)
        if not symbols and kind not in {"macro", "regulation"}:
            continue
        records.append({"id": fingerprint(title), "title": title, "url": link, "published": published.isoformat(),
                        "publisher": feed["name"], "group": feed["group"], "primary": feed["primary"],
                        "symbols": symbols, "category": kind})
    return records


def news(http, cfg, universe, now):
    records = []
    for feed in cfg["feeds"]:
        records.extend(http.optional(feed["name"], lambda f=feed: parse_feed(
            http.request(f["url"], limit=2_000_000, retries=1), f, universe, now, cfg["news_hours"]), []))
    return records


def cluster(records):
    """Conservative lexical grouping; AI verification later checks event agreement."""
    groups = []
    for record in sorted(records, key=lambda r: r["published"], reverse=True):
        match = next((g for g in groups if g[0]["category"] == record["category"]
                      and set(g[0]["symbols"]) == set(record["symbols"])
                      and similarity(g[0]["title"], record["title"]) >= .42), None)
        if match is None:
            groups.append([record])
        elif record["url"] not in {r["url"] for r in match}:
            match.append(record)
    return groups


def social(http, cfg, state, universe, now):
    """Read-only OAuth Reddit when access exists; no paid X calls or scraping."""
    status = {"X": "disabled: paid API; no requests", "Binance Square": "publishing API only; no authorized discovery API",
              "Reddit": "disabled: approved OAuth access required"}
    token = os.getenv("REDDIT_ACCESS_TOKEN", "")
    rows = []
    if token:
        status["Reddit"] = "authorized API requested"
        for subreddit in cfg["reddit_subreddits"][:3]:
            if not re.fullmatch(r"[A-Za-z0-9_]+", subreddit):
                raise ValueError("Invalid subreddit")
            response = http.optional("Reddit " + subreddit, lambda s=subreddit: http.json(
                f"https://oauth.reddit.com/r/{s}/hot?limit=25", headers={"Authorization": "Bearer " + token}), {})
            for child in response.get("data", {}).get("children", []):
                row = child.get("data", {})
                date = datetime.fromtimestamp(row.get("created_utc", 0), timezone.utc)
                symbols = relevant(row.get("title", ""), universe)
                if not symbols or not timedelta(0) <= now - date <= timedelta(hours=6):
                    continue
                # score is Reddit's net score, never label it as a count of likes.
                current = {"id": row["id"], "title": clean(row["title"]), "symbols": symbols,
                           "net_score": max(0, int(row.get("score", 0))), "comments": max(0, int(row.get("num_comments", 0))),
                           "published": date.isoformat(), "observed": now.isoformat(),
                           "url": "https://www.reddit.com" + row.get("permalink", ""), "kind": "opinion"}
                previous = state.get("social", {}).get(current["id"])
                current["score_per_hour"] = None
                if previous:
                    hours = (now - stamp(previous["observed"])).total_seconds() / 3600
                    if 0 < hours <= 6:
                        current["score_per_hour"] = (current["net_score"] - previous["net_score"]) / hours
                rows.append(current)
        status["Reddit"] = "available" if rows else "no eligible results; see source errors"
    state["social"] = {r["id"]: r for r in rows}
    for row in rows:
        row["cashtags"] = re.findall(r"\$[A-Za-z][A-Za-z0-9]*", row["title"])
        row["keywords"] = sorted(words(row["title"]))[:12]
    return rows, status
