#!/usr/bin/env python3
"""Public, multi-source trend signals for original Vietnamese Threads drafts.

No Meta token, login, unofficial social scraping, or posting. Sources:
- Google Trends Vietnam's exported public RSS feed (search trend signals)
- Google News Vietnam public RSS (headlines only)
- VnExpress published public RSS (headlines only)
- Hacker News Algolia public search API (tech community signals)

This module treats all retrieved text as untrusted data, not instructions.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

RSS_SOURCES = (
    ("Google Trends VN", "Xu hướng tìm kiếm", "TRENDS", "https://trends.google.com/trending/rss?geo=VN"),
    ("Google News VN", "Công nghệ", "NEWS", "https://news.google.com/rss/search?q=AI%20cong%20nghe%20when%3A2d&hl=vi&gl=VN&ceid=VN%3Avi"),
    ("Google News VN", "Mạng xã hội", "NEWS", "https://news.google.com/rss/search?q=mang%20xa%20hoi%20when%3A2d&hl=vi&gl=VN&ceid=VN%3Avi"),
    ("VnExpress", "Công nghệ", "NEWS", "https://vnexpress.net/rss/so-hoa.rss"),
    ("VnExpress", "Đời sống", "NEWS", "https://vnexpress.net/rss/doi-song.rss"),
    ("VnExpress", "Giáo dục", "NEWS", "https://vnexpress.net/rss/giao-duc.rss"),
    ("VnExpress", "Kinh doanh", "NEWS", "https://vnexpress.net/rss/kinh-doanh.rss"),
)
HN_ENDPOINT = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=25"
MAX_SOURCE_AGE_HOURS = 72
MAX_BYTES = 2_000_000


def get_bytes(url: str) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in (
        "trends.google.com", "news.google.com", "vnexpress.net", "hn.algolia.com"
    ):
        raise ValueError("Unsupported data source host")
    request = urllib.request.Request(url, headers={
        "User-Agent": "automation-thread-trend-research/1.0 (public RSS; read-only)",
        "Accept": "application/rss+xml, application/xml, application/json, */*",
    }, method="GET")
    with urllib.request.urlopen(request, timeout=16) as response:
        return response.read(MAX_BYTES + 1)[:MAX_BYTES]


def clean_title(value: str) -> str:
    text = re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:230]


def parse_date(text: str, reference_time: datetime):
    """Missing feed time is an observation timestamp, not a claimed post time."""
    if not text:
        return reference_time
    try:
        dt = parsedate_to_datetime(text)
    except (ValueError, TypeError, IndexError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return reference_time
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def make_row(title, publisher, topic, source_type, url, dt, rank, *, observed=False):
    title = clean_title(title)
    if len(title) < 3:
        return None
    # Each snippet only contains short titles + provenance, never article text.
    text = (
        f"Cụm từ tìm kiếm đang được Google Trends Việt Nam ghi nhận: {title}."
        if source_type == "TRENDS"
        else f"Tiêu đề do {publisher} công bố: {title}. Nội dung chỉ là tiêu đề nguồn, chưa được xác minh độc lập."
    )
    link = url if str(url).startswith("https://") else ""
    key = f"{publisher}:{title.casefold()}:{link}"
    return {
        "id": "PUBLIC-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20],
        "topic": topic, "text": text, "username": publisher,
        "permalink": link, "timestamp": dt.isoformat(),
        "search_type": f"{source_type}_OBSERVED" if observed else source_type,
        "rank": rank, "demo": False, "is_reply": False,
    }


def parse_rss(raw: bytes, publisher: str, topic: str, source_type: str, reference_time: datetime):
    root = ET.fromstring(raw)
    items = root.findall(".//channel/item")
    if not items:
        items = root.findall("{http://www.w3.org/2005/Atom}entry")
    rows = []
    for index, item in enumerate(items[:32]):
        title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
        link = item.findtext("link") or ""
        if not link:
            link_elt = item.find("{http://www.w3.org/2005/Atom}link")
            if link_elt is not None:
                link = link_elt.get("href", "")
        when = (item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}updated")
                or item.findtext("{http://www.w3.org/2005/Atom}published") or "")
        stamp = parse_date(when, reference_time)
        hours = (reference_time - stamp).total_seconds()/3600
        if not -.25 <= hours <= MAX_SOURCE_AGE_HOURS:
            continue
        row = make_row(title, publisher, topic, source_type, link, stamp, index,
                       observed=not bool(when))
        if row:
            rows.append(row)
    return rows


def parse_hackernews(raw: bytes, reference_time: datetime):
    data = json.loads(raw)
    hits = data.get("hits", [])
    if not isinstance(hits, list):
        raise ValueError("Invalid Hacker News response")
    rows = []
    for index, hit in enumerate(hits[:30]):
        if not isinstance(hit, dict):
            continue
        when = hit.get("created_at", "")
        stamp = parse_date(when, reference_time)
        if not -.25 <= (reference_time - stamp).total_seconds()/3600 <= MAX_SOURCE_AGE_HOURS:
            continue
        title = hit.get("title", "")
        # Use canonical HN discussion URL rather than untrusted arbitrary external URLs.
        oid = str(hit.get("objectID", ""))
        if not oid.isdecimal():
            continue
        link = f"https://news.ycombinator.com/item?id={oid}"
        row = make_row(title, "Hacker News", "Công nghệ quốc tế",
                       "COMMUNITY_HN", link, stamp, index)
        if row:
            rows.append(row)
    return rows


def fetch_public_trends(reference_time: datetime):
    """Best-effort independent sources; fail clearly if all are unreachable/stale."""
    found, errors, succeeded = [], [], 0
    for publisher, topic, mode, url in RSS_SOURCES:
        try:
            rows = parse_rss(get_bytes(url), publisher, topic, mode, reference_time)
            found.extend(rows)
            succeeded += 1
            print(f"PUBLIC_FEED_OK: {publisher}/{topic} recent={len(rows)}")
        except (OSError, ValueError, ET.ParseError, urllib.error.URLError) as exc:
            errors.append(f"{publisher}/{topic}: {type(exc).__name__}")
            print(f"PUBLIC_FEED_UNAVAILABLE: {publisher}/{topic} ({type(exc).__name__})")
    try:
        rows = parse_hackernews(get_bytes(HN_ENDPOINT), reference_time)
        found.extend(rows)
        succeeded += 1
        print(f"PUBLIC_FEED_OK: Hacker News recent={len(rows)}")
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        errors.append(f"Hacker News: {type(exc).__name__}")
        print(f"PUBLIC_FEED_UNAVAILABLE: Hacker News ({type(exc).__name__})")
    if len(found) < 2:
        raise RuntimeError(
            f"PUBLIC_SOURCES_UNAVAILABLE: received {len(found)} recent signals from {succeeded} feeds. "
            "This is not real Threads popularity data."
        )
    # Deduplicate same headline linked via different feeds.
    unique, seen = [], set()
    for row in sorted(found, key=lambda r: r["timestamp"], reverse=True):
        headline = row["text"].split(": ", 1)[-1].casefold()
        normalized = re.sub(r"\W+", "", headline)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(row)
    print(f"PUBLIC_SOURCES_TOTAL: feeds={succeeded}/{len(RSS_SOURCES)+1} dedup_signals={len(unique)} "
          f"failed_feeds={len(errors)}")
    return unique
