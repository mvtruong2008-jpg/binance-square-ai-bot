#!/usr/bin/env python3
"""Safe official Threads text publishing for owner-authorized accounts.

Only runs official Meta API endpoints and public RSS/Google Trends/Hacker News
research. Creates exactly one original Gemini text post per live run; it does
not copy source posts. No token is printed or stored in artifacts.

Modes:
  preview (default): public research + Gemini, writes a preview but never POSTs.
  publish: requires Threads user token with threads_basic and
           threads_content_publish; preflights own recent posts to avoid duplicates.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from check_api import ensure_user_access_token, get_json as threads_get_json, meta_numeric_error
from public_sources import fetch_public_trends
from trend_bot import choose_sources, generate_with_gemini, now_utc, validate_drafts

BASE = "https://graph.threads.net/v1.0"
MIN_HOURS_BETWEEN_POSTS = 4
MAX_POSTS_24H = 6
MAX_POST_LENGTH = 500


class PublisherError(RuntimeError):
    pass


def graph_call(method: str, path: str, token: str, params: dict | None = None):
    allowed = {
        ("GET", "/me/threads"),
        ("POST", "/me/threads"),
        ("POST", "/me/threads_publish"),
    }
    if (method, path) not in allowed:
        raise PublisherError("THREADS_ENDPOINT_NOT_ALLOWED")
    token = ensure_user_access_token(token)
    params = dict(params or {})
    data = urllib.parse.urlencode(params).encode("utf-8") if method == "POST" else None
    url = BASE + path
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "automation-thread-official-publisher/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as exc:
        # IMPORTANT: Never include URL, headers, raw error bodies, token or draft text.
        suffix = meta_numeric_error(exc)
        if exc.code in (400, 401, 403):
            raise PublisherError(
                f"THREADS_PUBLISH_PERMISSION_OR_TOKEN_ERROR: HTTP {exc.code}{suffix}. "
                "Check threads_content_publish permission, current token and app mode."
            ) from None
        if exc.code == 429:
            raise PublisherError(f"THREADS_RATE_LIMIT: HTTP 429{suffix}") from None
        raise PublisherError(
            f"THREADS_API_UNCERTAIN: HTTP {exc.code}{suffix}; "
            "check your Threads profile before retrying to avoid duplicate posts."
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise PublisherError(
            "THREADS_NETWORK_UNCERTAIN: Network failure. Check account for a new "
            "post before retrying; an API write may already have succeeded."
        ) from None
    if not isinstance(answer, dict) or answer.get("error"):
        raise PublisherError("THREADS_API_RESPONSE_ERROR: Unexpected response.")
    return answer


def published_recently(posts: list, current_time: datetime):
    count_24h = 0
    latest_age = None
    for item in posts:
        if not isinstance(item, dict):
            continue
        stamp = item.get("timestamp")
        if not isinstance(stamp, str):
            continue
        try:
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            hours = (current_time - at.astimezone(timezone.utc)).total_seconds() / 3600
        except ValueError:
            continue
        if 0 <= hours <= 24:
            count_24h += 1
            latest_age = hours if latest_age is None else min(latest_age, hours)
    return count_24h, latest_age


def get_recent_own_posts(token):
    # Read own posts first to avoid retrying or repeating successful content.
    data = graph_call("GET", "/me/threads", token, {
        "fields": "id,text,timestamp",
        "limit": 50,
    })
    if not isinstance(data.get("data"), list):
        raise PublisherError("THREADS_HISTORY_UNAVAILABLE: Cannot check already published posts.")
    return data["data"]


def choose_unpublished(drafts, existing):
    old = [str(p.get("text", "")).strip() for p in existing if isinstance(p, dict)]
    for draft in drafts:
        fresh = draft["text"].strip()
        match = False
        for text in old:
            if not text:
                continue
            ratio = difflib.SequenceMatcher(None, fresh.casefold(), text.casefold()).ratio()
            if ratio >= 0.72 or fresh.casefold() == text.casefold():
                match = True
                break
        if not match:
            return draft
    return None


def create_container(token: str, text: str):
    clean = re.sub(r"\s+", " ", text).strip()
    if not 65 <= len(clean) <= MAX_POST_LENGTH:
        raise PublisherError("TEXT_LENGTH_INVALID: Threads text must be 65-500 characters.")
    if re.search(r"(?i)https?://|www\.|@\w+", clean):
        raise PublisherError("TEXT_UNSAFE: Draft contains a URL or account mention.")
    result = graph_call("POST", "/me/threads", token, {
        "media_type": "TEXT",
        "text": clean,
    })
    cid = str(result.get("id", ""))
    if not re.fullmatch(r"[0-9]+", cid):
        raise PublisherError("THREADS_CONTAINER_ID_MISSING: Verify Meta response.")
    return cid


def publish_container(token: str, creation_id: str):
    if not re.fullmatch(r"[0-9]+", str(creation_id)):
        raise PublisherError("INVALID_CREATION_ID")
    result = graph_call("POST", "/me/threads_publish", token, {
        "creation_id": creation_id,
    })
    pid = str(result.get("id", ""))
    if not re.fullmatch(r"[0-9]+", pid):
        raise PublisherError(
            "THREADS_PUBLISH_UNCERTAIN: Publish returned no numeric post ID; "
            "check the account before retrying."
        )
    return pid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "publish"), default="preview")
    parser.add_argument("--output-dir", default="threads-trend-bot/output")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    token = ""
    previous = []
    if args.mode == "publish":
        token = ensure_user_access_token(os.getenv("THREADS_ACCESS_TOKEN", ""))
        me = threads_get_json("/me", token, {"fields": "id,username"})
        if not me.get("id"):
            raise PublisherError("THREADS_PROFILE_AUTH_FAILED")
        previous = get_recent_own_posts(token)
        count, age = published_recently(previous, now_utc())
        if count >= MAX_POSTS_24H:
            print(f"SKIP_DAILY_LIMIT: {count} own posts already published within 24h.")
            return
        if age is not None and age < MIN_HOURS_BETWEEN_POSTS:
            print(f"SKIP_COOLDOWN: Latest own Threads post is {age:.1f}h old (<{MIN_HOURS_BETWEEN_POSTS}h).")
            return
        print(f"THREADS_AUTH_OK: Existing recent posts checked; last24h={count}.")

    now = now_utc()
    rows = fetch_public_trends(now)
    sources = choose_sources(rows, now)
    if len(sources) < 2:
        raise PublisherError("NOT_ENOUGH_PUBLIC_SIGNALS: Did not publish.")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise PublisherError("MISSING_GEMINI_API_KEY")
    drafts = validate_drafts(
        generate_with_gemini(sources, api_key, source_mode="public"), sources
    )
    if not drafts:
        raise PublisherError("NO_SAFE_GEMINI_DRAFTS")
    chosen = choose_unpublished(drafts, previous)
    if chosen is None:
        print("SKIP_DUPLICATE: Gemini drafts overlap with already posted Threads.")
        return
    # A preview contains only selected text and source public links; no credentials.
    (output/"publish_preview.json").write_text(
        json.dumps({
            "mode": args.mode,
            "selected_text": chosen["text"],
            "topic": chosen["topic"],
            "source_count": len(sources),
            "source_categories": sorted(set(p["topic"] for p in sources)),
            "published_to_threads": False,
            "created_at_utc": now.isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    if args.mode == "preview":
        print(f"PREVIEW_OK: 1 original Gemini post ready, source_signals={len(sources)}.")
        print("PUBLISH_DISABLED: Preview only.")
        return

    # Two-stage official API. Do not retry automatic writes after ambiguous failures.
    container_id = create_container(token, chosen["text"])
    post_id = publish_container(token, container_id)
    # Write *only after* a confirmed official publish response.
    (output/"publish_result.json").write_text(
        json.dumps({
            "published_to_threads": True,
            "post_id": post_id,
            "topic": chosen["topic"],
            "published_at_utc": now_utc().isoformat(),
            "source_mode": "public",
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"THREADS_PUBLISH_SUCCESS: post_id={post_id}; source=public; author=authorized-user.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(f"PUBLISHER_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
