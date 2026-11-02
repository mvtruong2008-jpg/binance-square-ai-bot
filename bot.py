"""Binance Square AI publisher (Python standard library only).

Reads recent crypto headlines from public RSS feeds, drafts one short post
with Gemini, removes URLs, and optionally publishes via Binance's official
Square Post Skill. No API keys are stored in this file.
"""

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
PUBLISH = os.getenv("PUBLISH", "false").lower() == "true"
HISTORY_FILE = Path("data/history.json")
BINANCE_SKILL_DIR = Path("binance-skills-hub/skills/binance/square-post")
TOPICS = (
    ("Bitcoin", "Bitcoin cryptocurrency when:2d"),
    ("Ethereum", "Ethereum cryptocurrency when:2d"),
    ("BNB", "BNB Chain cryptocurrency when:2d"),
)


def fetch_recent_headlines():
    """Get titles published within the last 48 hours (no article contents)."""
    now = datetime.now(timezone.utc)
    result = []
    for topic, query in TOPICS:
        encoded = urllib.parse.quote(query)
        url = (
            f"https://news.google.com/rss/search?q={encoded}"
            "&hl=en-US&gl=US&ceid=US:en"
        )
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                root = ET.fromstring(response.read())
        except (urllib.error.URLError, ET.ParseError) as exc:
            print(f"RSS warning for {topic}: {exc}")
            continue

        for item in root.findall("./channel/item")[:20]:
            title = (item.findtext("title") or "").strip()
            date_text = item.findtext("pubDate") or ""
            try:
                published = parsedate_to_datetime(date_text)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
                published = published.astimezone(timezone.utc)
            except (ValueError, TypeError, IndexError):
                continue
            if not title or not now - timedelta(hours=48) <= published <= now:
                continue

            # Google News RSS titles usually end with ' - Publisher'.
            headline, _, publisher = title.rpartition(" - ")
            if not headline:
                headline, publisher = title, "a news publisher"
            # De-duplicate across feeds by the normalized full title.
            fingerprint = hashlib.sha256(title.casefold().encode()).hexdigest()
            result.append({
                "id": fingerprint,
                "headline": headline.strip(),
                "publisher": publisher.strip(),
                "published": published.isoformat(),
                "topic": topic,
            })

    return list({story["id"]: story for story in result}.values())


def load_history():
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_history(history, story):
    # Keep only recent entries so the cache remains small.
    now = datetime.now(timezone.utc)
    history[story["id"]] = now.isoformat()
    cutoff = now - timedelta(days=7)
    clean = {}
    for key, value in history.items():
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo and stamp >= cutoff:
                clean[key] = value
        except (ValueError, TypeError):
            pass
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def generate_post(story):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in GitHub Secrets")
    prompt = f"""Write ONE original short Binance Square crypto post in English.
News headline: {story['headline']}
News publisher: {story['publisher']}
Headline publication time (UTC): {story['published']}
Topic: {story['topic']}

Requirements:
- Write 2 to 4 concise sentences, approximately 45-85 words.
- Attribute the reported development to the publisher; a headline alone
  is not proof that an allegation is true.
- Do not invent price levels, statistics, incidents, dates, or quotes.
- No price predictions, financial advice, hype, or promises of profit.
- Maximum TWO cashtags, for example $BTC, and optional relevant hashtags.
- Absolutely NO URLs, website domains, Markdown links, citations or source links.
- Return only the post text, not a heading or commentary.
"""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(MODEL, safe='')}:generateContent"
    )
    data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print the key or full request URL.
        raise RuntimeError(f"Gemini API returned HTTP {exc.code}") from exc

    try:
        return "".join(
            part.get("text", "")
            for part in payload["candidates"][0]["content"]["parts"]
        ).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini returned no usable text") from exc


def clean_post(raw):
    # Preserve the visible label of Markdown links, not the URL.
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]*\)", r"\1", raw)
    # Remove URLs even if Gemini ignored the no-links instruction.
    text = re.sub(r"(?i)\b(?:https?://|www\.)[^\s<>]+", "", text)
    # Remove bare web addresses without http(s), e.g. news.google.com/rss/...
    text = re.sub(
        r"(?i)\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>]*)?", "", text
    )
    # Remove a trailing source/citation line if it contains no URL anymore.
    text = re.sub(r"(?im)^\s*(?:source|sources|nguồn|link)\s*:\s*.*$", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = text.strip(" \n\t\"'`-–")
    if not text or len(text) > 1200:
        raise RuntimeError("Generated post is empty or too long")
    if len(re.findall(r"\$[A-Za-z][A-Za-z0-9]*", text)) > 2:
        raise RuntimeError("Generated post has more than two cashtags")
    if re.search(r"(?i)(?:https?://|www\.)", text):
        raise RuntimeError("Generated post still contains a URL")
    return text


def publish_to_binance(post):
    if not os.getenv("BINANCE_SQUARE_OPENAPI_KEY"):
        raise RuntimeError("Missing BINANCE_SQUARE_OPENAPI_KEY")
    script = BINANCE_SKILL_DIR / "scripts/post-text.mjs"
    if not script.is_file():
        raise RuntimeError(f"Official Binance publisher script missing: {script}")
    completed = subprocess.run(
        ["node", "scripts/post-text.mjs", "--text", post],
        cwd=BINANCE_SKILL_DIR,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.stdout:
        print(completed.stdout)
    if completed.returncode != 0:
        raise RuntimeError(
            "Binance publisher failed: " + completed.stderr.strip()[:1200]
        )
    if completed.stderr:
        print("Publisher notes:", completed.stderr.strip()[:500])


def main():
    history = load_history()
    stories = fetch_recent_headlines()
    available = [story for story in stories if story["id"] not in history]
    if not available:
        print("SKIP: No new headline in the last 48 hours. Nothing published.")
        return
    story = random.SystemRandom().choice(available)
    print("Chosen news topic:", story["topic"])
    print("Publisher:", story["publisher"])
    print("Headline:", story["headline"])
    post = clean_post(generate_post(story))
    print("\n=== POST PREVIEW (NO LINKS) ===\n" + post + "\n")

    if not PUBLISH:
        print("TEST MODE: Post generated, not published.")
        return
    publish_to_binance(post)
    save_history(history, story)
    print("DONE: Publisher completed; headline saved to history.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
