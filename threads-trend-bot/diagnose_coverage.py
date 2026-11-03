#!/usr/bin/env python3
"""Diagnose whether Threads keyword search returns own or third-party posts.

Read-only. Never logs usernames, post content, links, IDs, token or entire API
response. Metrics help distinguish app review limitation from content filtering.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from check_api import get_json, ensure_user_access_token


def classify_search_data(profile: dict, posts: list, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    own_name = str(profile.get("username", "")).strip().lower()
    stats = {"results": 0, "own": 0, "other": 0, "unknown_owner": 0,
             "recent72h": 0, "long_enough": 0, "recent_and_long": 0}
    for row in posts:
        if not isinstance(row, dict):
            continue
        stats["results"] += 1
        username = str(row.get("username", "")).strip().lower()
        if not username or not own_name:
            stats["unknown_owner"] += 1
        elif username == own_name:
            stats["own"] += 1
        else:
            stats["other"] += 1
        text = str(row.get("text", "")).strip()
        long_enough = len(text) >= 45
        stats["long_enough"] += int(long_enough)
        recent = False
        stamp = row.get("timestamp")
        if isinstance(stamp, str):
            try:
                date = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                age = (now - date.astimezone(timezone.utc)).total_seconds() / 3600
                recent = -0.25 <= age <= 72
            except ValueError:
                pass
        stats["recent72h"] += int(recent)
        stats["recent_and_long"] += int(recent and long_enough)
    return stats


def main():
    token = ensure_user_access_token(os.environ.get("THREADS_ACCESS_TOKEN", ""))
    me = get_json("/me", token, {"fields": "id,username"})
    if not me.get("id"):
        raise RuntimeError("PROFILE_MISSING")
    if not me.get("username"):
        print("OWNER_CHECK_INCOMPLETE: Profile did not return a username.")
    response = get_json("/keyword_search", token, {
        "q": "AI",
        "search_type": "RECENT",
        "fields": "id,text,username,permalink,timestamp",
        "limit": 25,
    })
    posts = response.get("data")
    if not isinstance(posts, list):
        raise RuntimeError("BAD_KEYWORD_SEARCH_RESPONSE")
    stats = classify_search_data(me, posts)
    for k, v in stats.items():
        print(f"COVERAGE_{k.upper()}: {v}")
    if stats["results"] > 0 and stats["other"] == 0:
        print("COVERAGE_HINT: Results show no confirmed third-party author. Check Meta App Review for threads_keyword_search Advanced Access.")
    elif stats["other"] > 0:
        print("COVERAGE_HINT: Some posts are from other accounts. Inspect age, length and selection filters.")
    elif stats["results"] == 0:
        print("COVERAGE_HINT: No posts for this query; approval remains unproven.")
    print("READ_ONLY: Neither token nor post details were logged or published.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"OWNERSHIP_DIAG_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
