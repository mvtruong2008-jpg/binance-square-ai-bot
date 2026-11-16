from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .core import utcnow
from .editor import validate
from .media import image_check
from .state import control


def publish(store, topic, draft, media, output, cfg):
    settings = control(store.http)
    if settings.get("enabled") is not True or settings.get("stop") is not False or os.getenv("X_LEI_STOP", "false").lower() == "true":
        raise ValueError("Emergency stop or LIVE disabled")
    if not os.getenv("BINANCE_SQUARE_OPENAPI_KEY"):
        raise ValueError("Existing Binance Square secret unavailable")
    skill = Path(os.getenv("BINANCE_PUBLISHER_DIR", "binance-skills-hub/skills/binance/square-post"))
    if not (skill / "scripts/post-image.mjs").is_file():
        raise ValueError("Official publisher missing")
    validate(topic, draft, store.data["posts"], utcnow())
    path = Path(output) / media["path"]
    if image_check(path) != media["sha256"]:
        raise ValueError("Media changed after QC")
    record = store.reserve(topic, draft, media, cfg, utcnow())
    # Check again after reserving, directly before the non-idempotent operation.
    settings = control(store.http)
    if settings.get("stop") is not False or settings.get("enabled") is not True:
        record["status"] = "cancelled"
        store.save()
        raise ValueError("Stopped before publication")
    try:
        result = subprocess.run(["node", "scripts/post-image.mjs", "--text", draft["text"], "--images", str(path.resolve())],
                                cwd=skill, capture_output=True, text=True, timeout=240, check=False)
        # Do not echo raw subprocess output: upstream errors can contain request details.
        match = re.search(r"(?m)^ID:\s*(\d+)\s*$", result.stdout or "")
        if result.returncode != 0 or not match:
            record["status"] = "unknown"
            record["error"] = "Publisher response ambiguous; reconcile manually, never auto-retry"
        else:
            record.update(status="published", post_id=match[1], url="https://www.binance.com/square/post/" + match[1],
                          published_at=utcnow().isoformat())
    except (subprocess.TimeoutExpired, OSError):
        record.update(status="unknown", error="Publisher timeout/start failure; reconcile before any retry")
    store.save()
    if record["status"] != "published":
        raise RuntimeError("Unknown publication outcome: event remains reserved")
    return record
