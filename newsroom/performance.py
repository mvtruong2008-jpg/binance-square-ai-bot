"""Import real, attributable exported metrics; never fabricate API availability."""
from __future__ import annotations

from .core import stamp

METRICS = ("views", "likes", "comments", "shares", "coin_clicks")


def ingest(records, posts):
    known = {p.get("post_id"): p for p in posts if p.get("post_id")}
    accepted = []
    for row in records:
        if row.get("post_id") not in known or row.get("source") not in {"binance_export", "authorized_api"}:
            raise ValueError("Unknown post or unauthenticated metric provenance")
        stamp(row["observed_at"])
        for key in METRICS:
            if row.get(key) is not None and (type(row[key]) is not int or row[key] < 0):
                raise ValueError("Metrics must be real nonnegative integer counts or null")
        accepted.append({"post_id": row["post_id"], "observed_at": row["observed_at"], "source": row["source"],
                         **{k: row.get(k) for k in METRICS}})
    return accepted


def strategy(metrics, posts):
    # Compare rates only when each kind has >=5 actual observed posts with views.
    latest = {}
    for row in sorted(metrics, key=lambda r: stamp(r["observed_at"])):
        latest[row["post_id"]] = row
    groups = {}
    for post in posts:
        row = latest.get(post.get("post_id"))
        if not row or not row.get("views") or row.get("likes") is None:
            continue
        groups.setdefault(post["kind"], []).append(row["likes"] / row["views"])
    return {kind: sum(rates)/len(rates) for kind, rates in groups.items() if len(rates) >= 5}
