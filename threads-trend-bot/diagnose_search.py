#!/usr/bin/env python3
"""Read-only Threads keyword-search diagnostics using Meta's minimal documented params.

Prints counts and error categories, never post bodies, usernames, URLs or tokens.
"""
from __future__ import annotations

import os
import sys

from check_api import ensure_user_access_token, get_json

PROBES = [
    ("AI", "RECENT"),
    ("ThreadsAPI", "TOP"),
    ("bitcoin", "RECENT"),
]


def probe_search(token: str, query: str, mode: str) -> int:
    """Meta Postman reference: q, search_type, fields. No since/other filters."""
    response = get_json("/keyword_search", ensure_user_access_token(token), {
        "q": query,
        "search_type": mode,
        "fields": "id,text,username,permalink,timestamp",
        "limit": 10,
    })
    data = response.get("data")
    if not isinstance(data, list):
        raise RuntimeError("KEYWORD_SEARCH_UNEXPECTED_RESPONSE")
    return len(data)


def main():
    token = ensure_user_access_token(os.getenv("THREADS_ACCESS_TOKEN", ""))
    total = 0
    errors = 0
    for query, mode in PROBES:
        try:
            count = probe_search(token, query, mode)
        except RuntimeError as exc:
            errors += 1
            print(f"SEARCH_PROBE_ERROR: q={query} mode={mode} error={exc}")
            continue
        total += count
        print(f"SEARCH_PROBE_OK: q={query} mode={mode} count={count}")
    if total == 0:
        print("SEARCH_DIAGNOSIS_EMPTY: No public results from 3 basic keyword queries.")
        print("Likely Meta App Review/Advanced Access limitation for threads_keyword_search.")
        print("Verify this permission's approved access level in Meta App Dashboard.")
    else:
        print(f"SEARCH_DIAGNOSIS_RESULTS: {total} posts returned across 3 queries (not unique).")
        print("This confirms response data but not its public coverage or engagement metrics.")
    print("READ_ONLY: No posts published, no token displayed.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"SEARCH_DIAGNOSTIC_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
