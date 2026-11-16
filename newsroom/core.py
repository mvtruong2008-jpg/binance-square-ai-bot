from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return dt.astimezone(timezone.utc)


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite number")
    return result


def fingerprint(text):
    return hashlib.sha256(re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:24]


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - {
        "the", "a", "an", "and", "or", "to", "in", "on", "of", "for", "with", "as", "is", "at", "by", "from", "s"
    }


def similarity(a, b):
    a, b = words(a), words(b)
    return len(a & b) / max(1, len(a | b))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config(path=None):
    cfg = json.loads(Path(path or Path(__file__).with_name("config.json")).read_text(encoding="utf-8"))
    for key, lo, hi in (("threshold", 0, 100), ("max_posts_24h", 1, 20), ("gap_minutes", 1, 1440),
                        ("news_hours", 1, 6), ("max_market_candidates", 1, 12), ("max_ai_calls", 0, 10)):
        if type(cfg[key]) is not int or not lo <= cfg[key] <= hi:
            raise ValueError("Invalid config: " + key)
    return cfg


def public_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Only public HTTPS URLs allowed")
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise RuntimeError("Source DNS unavailable") from None
    for addr in addresses:
        if not ipaddress.ip_address(addr[4][0]).is_global:
            raise ValueError("Private network URL rejected")
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        if urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            # Authenticated APIs must never forward credentials to another host.
            if any(k.lower() in {"authorization", "x-goog-api-key", "x-cg-demo-api-key"} for k in req.headers):
                raise ValueError("Credential redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HTTP:
    """Bounded requests; retry reads only. Never log API response bodies or keys."""
    def __init__(self):
        self.usage = {}
        self.errors = []
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, url, *, headers=None, data=None, method=None, limit=5_000_000, retries=2):
        public_url(url)
        host = urllib.parse.urlsplit(url).hostname
        method = method or ("POST" if data is not None else "GET")
        if method != "GET":
            retries = 0
        for attempt in range(retries + 1):
            self.usage[host] = self.usage.get(host, 0) + 1
            req = urllib.request.Request(url, data=data, method=method, headers={
                "User-Agent": "XLEI-Newsroom/3.0 (public research)", **(headers or {})})
            try:
                with self.opener.open(req, timeout=20) as response:
                    body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError("Response too large")
                return body
            except urllib.error.HTTPError as exc:
                retry = exc.code == 429 or 500 <= exc.code < 600
                if attempt >= retries or not retry:
                    raise RuntimeError(f"{host}: HTTP {exc.code}") from None
                delay = exc.headers.get("Retry-After", "2")
                time.sleep(min(10, int(delay) if delay.isdigit() else 2) + attempt)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt >= retries:
                    raise RuntimeError(f"{host}: network unavailable") from None
                time.sleep(1 + attempt)

    def json(self, url, **kwargs):
        return json.loads(self.request(url, **kwargs))

    def optional(self, name, fn, default):
        try:
            return fn()
        except (RuntimeError, ValueError, KeyError, TypeError, IndexError) as exc:
            self.errors.append({"source": name, "error": type(exc).__name__, "time": utcnow().isoformat()})
            return default


def gecko_headers():
    key = os.getenv("COINGECKO_DEMO_KEY", "")
    return {"x-cg-demo-api-key": key} if key else {}
