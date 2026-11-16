"""Durable write-ahead reservations using GitHub Contents API compare-and-swap.

An ambiguous publish remains reserved forever until a human reconciles it.
This provides at-most-once attempts, not an impossible exactly-once promise.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
from datetime import timedelta
from pathlib import Path

from .core import atomic_json, stamp, utcnow


def empty_state():
    return {"version": 3, "posts": [], "social": {}, "errors": [], "metrics": [], "runs": []}


class State:
    def __init__(self, http, *, live, branch="x-lei-state", local="data/newsroom-state.json"):
        self.http, self.live, self.branch, self.local = http, live, branch, Path(local)
        self.repo = os.getenv("GITHUB_REPOSITORY", "")
        self.token = os.getenv("GH_TOKEN", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo) and live:
            raise ValueError("LIVE requires GITHUB_REPOSITORY")
        if not self.token and live:
            raise ValueError("LIVE requires GitHub state credentials")
        self.base = "https://api.github.com/repos/" + self.repo
        self.sha = None
        self.data = empty_state()

    def api(self, path, method="GET", body=None):
        return self.http.json(self.base + path, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"},
            data=json.dumps(body).encode() if body is not None else None)

    def load(self):
        if self.token and self.repo:
            try:
                row = self.api("/contents/state.json?ref=" + self.branch)
                self.data = json.loads(base64.b64decode(row["content"]))
                self.sha = row["sha"]
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                if self.live:
                    raise RuntimeError("LIVE state missing: initialize via --init-state before publishing") from None
        elif self.local.exists():
            self.data = json.loads(self.local.read_text(encoding="utf-8"))
        if self.data.get("version") != 3 or not isinstance(self.data.get("posts"), list):
            raise ValueError("State schema invalid; refusing to reset publication history")
        return self.data

    def initialize(self):
        if not self.token or not self.repo:
            raise ValueError("Initialization requires GitHub credentials")
        # Idempotent initialization; NEVER replace an existing journal.
        try:
            self.api("/git/ref/heads/" + self.branch)
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            repo = self.api("")
            ref = self.api("/git/ref/heads/" + repo["default_branch"])
            self.api("/git/refs", "POST", {"ref": "refs/heads/" + self.branch, "sha": ref["object"]["sha"]})
        try:
            self.api("/contents/state.json?ref=" + self.branch)
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self.api("/contents/state.json", "PUT", {"message": "Initialize X LEI durable journal [skip ci]", "branch": self.branch,
                      "content": base64.b64encode(json.dumps(empty_state()).encode()).decode()})
        self.load()

    def save(self):
        if self.live:
            if not self.sha:
                raise RuntimeError("Missing state revision; no publication allowed")
            self.archive()
            content = base64.b64encode(json.dumps(self.data, ensure_ascii=False).encode()).decode()
            result = self.api("/contents/state.json", "PUT", {"message": "Update X LEI journal [skip ci]", "branch": self.branch,
                              "sha": self.sha, "content": content})
            self.sha = result["content"]["sha"]
        atomic_json(self.local, self.data)

    def archive(self):
        """Commit old records before removing them from the bounded hot journal."""
        cutoff = utcnow() - timedelta(days=14)
        older = [r for r in self.data["posts"] if stamp(r["reserved_at"]) < cutoff]
        for day in sorted({stamp(r["reserved_at"]).strftime("%Y-%m-%d") for r in older}):
            path = "/contents/archive/" + day + ".json"
            records, sha = {}, None
            try:
                result = self.api(path + "?ref=" + self.branch)
                sha = result["sha"]
                records = {r["event_id"]: r for r in json.loads(base64.b64decode(result["content"]))}
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc):
                    raise
            records.update({r["event_id"]: r for r in older if stamp(r["reserved_at"]).strftime("%Y-%m-%d") == day})
            body = {"message": "Archive X LEI posts " + day + " [skip ci]", "branch": self.branch,
                    "content": base64.b64encode(json.dumps(list(records.values()), ensure_ascii=False).encode()).decode()}
            if sha:
                body["sha"] = sha
            self.api(path, "PUT", body)
        if older:
            self.data["posts"] = [r for r in self.data["posts"] if stamp(r["reserved_at"]) >= cutoff]
        self.data["metrics"] = self.data.get("metrics", [])[-1000:]

    def reserve(self, topic, draft, media, cfg, now):
        if not self.live:
            raise ValueError("PREVIEW cannot reserve publications")
        rows = self.data["posts"]
        authorization = os.getenv("X_LEI_ONE_POST_REQUEST", "")
        if authorization and any(r.get("authorization_id") == authorization for r in rows):
            raise ValueError("One-post authorization already consumed")
        if any(r["event_id"] == topic["id"] for r in rows):
            raise ValueError("Event already reserved")
        recent = [r for r in rows if now-stamp(r["reserved_at"]) < timedelta(hours=24)]
        # Unknown attempts consume budget and spacing just like confirmed publications.
        if len(recent) >= cfg["max_posts_24h"]:
            raise ValueError("24-hour publication cap reached")
        if recent and now-max(stamp(r["reserved_at"]) for r in recent) < timedelta(minutes=cfg["gap_minutes"]):
            raise ValueError("Publication spacing active")
        record = {"event_id": topic["id"], "title": topic["title"], "reserved_at": now.isoformat(),
                  "status": "reserved", "text": draft["text"], "hook": draft["hook"], "kind": topic["kind"],
                  "symbol": topic["market"]["symbol"], "coin_id": topic["market"]["id"], "score": topic["score"],
                  "media": media, "sources": [{k: s[k] for k in ("publisher", "url", "published")} for s in topic["sources"]]}
        before = copy.deepcopy(self.data)
        if authorization:
            record["authorization_id"] = authorization
        rows.append(record)
        try:
            self.save()  # Must be remotely committed BEFORE the external publish call.
        except Exception:
            self.data = before
            raise
        return record


def control(http, local=False):
    if local:
        return json.loads(Path(__file__).with_name("control.json").read_text(encoding="utf-8"))
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    # No ref means the current default branch, independent of the checked-out revision.
    def read(path):
        row = http.json("https://api.github.com/repos/" + repo + "/contents/" + path, headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"})
        return json.loads(base64.b64decode(row["content"]))
    request = os.getenv("X_LEI_ONE_POST_REQUEST", "")
    if not request:
        return read("newsroom/control.json")
    if not re.fullmatch(r"[a-z0-9-]{1,60}", request):
        raise ValueError("Invalid one-post request")
    try:
        main_settings = read("newsroom/control.json")
        if main_settings.get("stop") is not False:
            raise ValueError("Emergency stop is active")
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
        # Before deployment main has no newsroom control; only the scoped trial can run.
    permit = read("authorizations/" + request + ".json?ref=x-lei-state")
    if (permit.get("request_id") != request or permit.get("max_posts") != 1
            or permit.get("ref") != os.getenv("GITHUB_REF")
            or os.getenv("GITHUB_EVENT_NAME") != "push"
            or stamp(permit["expires_at"]) <= utcnow()):
        raise ValueError("One-post authorization expired or scope mismatch")
    return {"enabled": True, "stop": False, "free_ai_confirmed": permit.get("free_ai_confirmed") is True}
