#!/usr/bin/env python3
"""Manage Threads long-lived tokens without printing or committing credentials.

Actions:
  inspect: verify a user token can read an authorized Threads profile.
  exchange: exchange a short-lived user token for a long-lived one, then store
            its encrypted replacement as GitHub Actions THREADS_ACCESS_TOKEN.
  refresh: refresh a valid long-lived token, then store its replacement.

For exchange/refresh the runner MUST have a separate GH_SECRETS_PAT secret
with fine-grained repository "Secrets: Read and write" permission.
The ordinary Actions GITHUB_TOKEN CANNOT manage Actions Secrets.
No Threads publishing endpoint is ever called.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from check_api import ensure_user_access_token, get_json as threads_get_json

GRAPH_ROOT = "https://graph.threads.net"
GITHUB_API_ROOT = "https://api.github.com"
SECRET_NAME = "THREADS_ACCESS_TOKEN"
ALLOWED_REPOSITORY = "mvtruong2008-jpg/binance-square-ai-bot"


class TokenManagerError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise TokenManagerError(f"MISSING_{name}: Add {name} to GitHub Actions Secrets.")
    return value


def graph_get(path: str, params: dict) -> dict:
    """Use only official read-only token endpoints; no publishing."""
    if path not in ("/access_token", "/refresh_access_token"):
        raise TokenManagerError("GRAPH_PATH_NOT_ALLOWED.")
    url = GRAPH_ROOT + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "ThreadsLongLivedTokenManager/1.0"
    }, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        # NEVER print URL, headers, raw error body or Meta's free-text error message:
        # GET query contains an access token and potentially the Threads App Secret.
        try:
            payload = json.loads(exc.read(8192).decode("utf-8"))
            detail = payload.get("error", {}) if isinstance(payload, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            code = detail.get("code")
            subcode = detail.get("error_subcode")
            numeric_code = int(code) if isinstance(code, int) else None
            numeric_subcode = int(subcode) if isinstance(subcode, int) else None
        except (ValueError, TypeError, OSError, UnicodeDecodeError):
            numeric_code, numeric_subcode = None, None
        # Numeric Meta codes are safe diagnostics; arbitrary response strings are not.
        detail_code = f" meta_code={numeric_code}" if numeric_code is not None else ""
        detail_subcode = f" meta_subcode={numeric_subcode}" if numeric_subcode is not None else ""
        cause = (
            "THREADS_USER_TOKEN_INVALID_OR_EXPIRED" if numeric_code == 190 else
            "META_BAD_PARAMETER: Check Threads App Secret vs Facebook App Secret, "
            "and that token belongs to the same Threads app" if numeric_code == 100 else
            "META_REJECTED_EXCHANGE: Check token age, app-specific Threads secret, and permissions"
        )
        raise TokenManagerError(
            f"META_HTTP_{exc.code}{detail_code}{detail_subcode}: {cause}."
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise TokenManagerError("META_CONNECTION_ERROR: Threads API could not be reached.") from None
    if not isinstance(value, dict) or value.get("error"):
        raise TokenManagerError("META_TOKEN_RESPONSE_ERROR: Could not obtain a new token.")
    return value


def parse_token_response(data: dict) -> tuple[str, int]:
    value = ensure_user_access_token(str(data.get("access_token", "")))
    try:
        lifetime = int(data.get("expires_in", 0))
    except (ValueError, TypeError):
        lifetime = 0
    if lifetime < 24 * 3600:
        raise TokenManagerError("UNEXPECTED_TOKEN_EXPIRY: Meta did not return a long-lived token.")
    return value, lifetime


def exchange_short_token(short_token: str, app_secret: str) -> tuple[str, int]:
    if not app_secret:
        raise TokenManagerError("MISSING_THREADS_APP_SECRET.")
    response = graph_get("/access_token", {
        "grant_type": "th_exchange_token", "client_secret": app_secret,
        "access_token": ensure_user_access_token(short_token),
    })
    return parse_token_response(response)


def refresh_long_token(long_token: str) -> tuple[str, int]:
    response = graph_get("/refresh_access_token", {
        "grant_type": "th_refresh_token",
        "access_token": ensure_user_access_token(long_token),
    })
    return parse_token_response(response)


def github_request(method: str, path: str, token: str, *, body=None) -> dict:
    if not re.fullmatch(r"/repos/mvtruong2008-jpg/binance-square-ai-bot/actions/secrets(/public-key|/THREADS_ACCESS_TOKEN)", path):
        raise TokenManagerError("GITHUB_PATH_NOT_ALLOWED.")
    request = urllib.request.Request(
        GITHUB_API_ROOT + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ThreadsLongLivedTokenManager/1.0",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise TokenManagerError(
            f"GITHUB_SECRET_HTTP_{exc.code}: GitHub PAT lacks Secrets write permission or has expired."
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise TokenManagerError("GITHUB_CONNECTION_ERROR: GitHub API unavailable.") from None


def fetch_secret_public_key(gh_pat: str, repo: str) -> tuple[str, str]:
    if repo != ALLOWED_REPOSITORY:
        raise TokenManagerError("REPOSITORY_MISMATCH: Refusing to write a different repository.")
    prefix = f"/repos/{repo}/actions/secrets"
    info = github_request("GET", prefix + "/public-key", gh_pat)
    if not isinstance(info.get("key"), str) or not isinstance(info.get("key_id"), str):
        raise TokenManagerError("GITHUB_PUBLIC_KEY_MISSING.")
    return info["key"], info["key_id"]


def encrypt_for_github(value: str, public_key_b64: str) -> str:
    try:
        from nacl import encoding, public
    except ImportError as exc:
        raise TokenManagerError("MISSING_PYNACL: pip install pynacl.") from None
    try:
        key = public.PublicKey(public_key_b64.encode("ascii"), encoding.Base64Encoder())
        encrypted = public.SealedBox(key).encrypt(value.encode("utf-8"))
    except Exception:
        raise TokenManagerError("GITHUB_SECRET_ENCRYPTION_FAILED.") from None
    return base64.b64encode(encrypted).decode("ascii")


def save_long_token(value: str, gh_pat: str, repo: str, *, public_key=None):
    """Encrypt in-memory using repo public key. Never expose plaintext to logs."""
    if public_key is None:
        public_key = fetch_secret_public_key(gh_pat, repo)
    key, key_id = public_key
    ciphertext = encrypt_for_github(value, key)
    github_request("PUT", f"/repos/{repo}/actions/secrets/{SECRET_NAME}", gh_pat, body={
        "encrypted_value": ciphertext,
        "key_id": key_id,
    })


def manage_token(mode: str):
    if mode == "inspect":
        current = require_env(SECRET_NAME)
        ensure_user_access_token(current)
        info = threads_get_json("/me", current, {"fields": "id,username"})
        if not info.get("id"):
            raise TokenManagerError("PROFILE_UNAVAILABLE: Verify OAuth authorization.")
        print("TOKEN_PROFILE_OK: Authorized Threads profile is accessible.")
        print("TOKEN_EXPIRY_UNKNOWN: Read-only profile request does not reveal expiry.")
        print("TOKEN_NOT_CHANGED: No token was exchanged, refreshed or posted.")
        return

    if mode not in ("exchange", "refresh"):
        raise TokenManagerError("INVALID_MODE: Use inspect, exchange or refresh.")

    current = require_env(SECRET_NAME)
    ensure_user_access_token(current)
    gh_pat = require_env("GH_SECRETS_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    # Preflight the GitHub public key BEFORE refreshing / exchanging.
    # Failure here means no new Meta token is issued and potentially lost.
    public_key = fetch_secret_public_key(gh_pat, repo)
    if mode == "exchange":
        # A valid user token can access /me. Run this before the exchange to
        # distinguish token validity from a mismatched Threads App Secret.
        profile = threads_get_json("/me", current, {"fields": "id,username"})
        if not isinstance(profile, dict) or not profile.get("id"):
            raise TokenManagerError("SHORT_TOKEN_PROFILE_UNAVAILABLE.")
        print("TOKEN_PROFILE_OK: Current short-lived token can access Threads /me.")
        app_secret = require_env("THREADS_APP_SECRET")
        new_token, lifetime = exchange_short_token(current, app_secret)
    else:
        new_token, lifetime = refresh_long_token(current)
    save_long_token(new_token, gh_pat, repo, public_key=public_key)
    # Do not print, save to artifacts, or persist the raw token elsewhere.
    est = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
    print(f"TOKEN_{mode.upper()}_OK: Refreshed credential saved to encrypted GitHub Actions Secret.")
    print(f"EXPIRES_APPROX_UTC: {est.strftime('%Y-%m-%d')} (according to Meta's expires_in).")
    print("PUBLISH_DISABLED: No Threads post was created.")


def main():
    parser = argparse.ArgumentParser(description="Manage Threads tokens using GitHub Actions Secrets.")
    parser.add_argument("--mode", choices=("inspect", "exchange", "refresh"), default="inspect")
    args = parser.parse_args()
    try:
        manage_token(args.mode)
    except (TokenManagerError, RuntimeError) as err:
        # Only fixed, sanitized errors from helpers reach this handler.
        print(f"TOKEN_MANAGER_ERROR: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
