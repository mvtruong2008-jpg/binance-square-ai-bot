#!/usr/bin/env python3
"""Read-only verification of an officially authorized Threads API token.

Never publishes, refreshes, modifies, or prints the token. Intentionally
does not log the original API response or arbitrary user content.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAPH_ROOT = "https://graph.threads.net/v1.0"


def ensure_user_access_token(token: str) -> str:
    """Fail closed for a common App Secret format. Never log token content."""
    value = token.strip()
    if not value:
        raise RuntimeError("MISSING_TOKEN: Set THREADS_ACCESS_TOKEN as a GitHub Actions secret.")
    if re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise RuntimeError(
            "LIKELY_APP_SECRET: 32 hexadecimal characters resemble a Meta App Secret, "
            "not a Threads User Access Token. Complete Threads Login authorization "
            "and save the USER token in THREADS_ACCESS_TOKEN. Do not paste secrets in chat."
        )
    return value


def get_json(path: str, token: str, params=None) -> dict:
    token = ensure_user_access_token(token)
    if path not in ("/me", "/keyword_search"):
        raise ValueError("Only read-only Threads API endpoints are allowed.")
    url = GRAPH_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "User-Agent": "ThreadsTrendBotCredentialCheck/1.0",
        "Accept": "application/json",
    }, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401):
            raise RuntimeError(f"THREADS_AUTH_FAILED: HTTP {exc.code}. Check Threads token and authorization.") from None
        if exc.code == 403:
            raise RuntimeError("THREADS_PERMISSION_DENIED: HTTP 403. App review or search scope may be required.") from None
        if exc.code == 429:
            raise RuntimeError("THREADS_RATE_LIMITED: API query limit reached.") from None
        raise RuntimeError(f"THREADS_API_ERROR: HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("THREADS_NETWORK_ERROR: Could not reach graph.threads.net.") from None
    if not isinstance(data, dict):
        raise RuntimeError("THREADS_RESPONSE_ERROR: Unexpected JSON response.")
    if "error" in data:
        raise RuntimeError("THREADS_RESPONSE_ERROR: Threads returned an error.")
    return data


def main():
    token = os.getenv("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        print("NOT_CONFIGURED: THREADS_ACCESS_TOKEN is not set in GitHub Actions secrets.")
        print("Meta app creation and OAuth authorization must be done by the account owner.")
        return 2
    ensure_user_access_token(token)
    profile = get_json("/me", token, {"fields": "id,username"})
    if not profile.get("id"):
        raise RuntimeError("THREADS_PROFILE_CHECK_FAILED: No Threads user ID returned.")
    print("PROFILE_OK: Token authenticated; Threads profile is accessible.")
    # Uses one benign read-only query and shows no third-party post contents.
    results = get_json("/keyword_search", token, {
        "q": "công nghệ", "search_type": "RECENT", "search_mode": "KEYWORD",
        "fields": "id,text,username,permalink,timestamp", "limit": 3,
    })
    items = results.get("data")
    if not isinstance(items, list):
        raise RuntimeError("THREADS_SEARCH_UNEXPECTED: Expected data array.")
    if items:
        print(f"SEARCH_API_OK: Returned {len(items)} item(s) for the sample keyword.")
        print("PUBLIC_DISCOVERY_NOT_PROVEN: A result may belong only to the authorized user.")
    else:
        print("SEARCH_API_EMPTY: Endpoint responded but returned no posts.")
        print("This alone does NOT prove public keyword-search permission.")
    print("READ_ONLY_OK: No posts were created or published.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
