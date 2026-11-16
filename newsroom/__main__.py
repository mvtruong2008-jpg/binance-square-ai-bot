from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import dashboard, hunters, market, performance
from .core import HTTP, atomic_json, load_config, utcnow
from .editor import Editor, validate
from .intelligence import plan
from .media import produce
from .publisher import publish
from .state import State, control


def run(args):
    cfg, http, now = load_config(args.config), HTTP(), utcnow()
    store = State(http, live=args.mode == "LIVE", branch=cfg["state_branch"], local=args.state)
    if args.init_state:
        store.initialize()
        print("Durable journal initialized without publication")
        return 0
    report = {"mode": args.mode, "status": "starting", "time": now.isoformat(), "threshold": cfg["threshold"], "drafts": [], "errors": []}
    code = 0
    editor = Editor(http, cfg["max_ai_calls"])
    try:
        settings = control(http, local=args.mode == "PREVIEW")
        os.environ["X_LEI_FREE_AI_CONFIRMED"] = str(settings.get("free_ai_confirmed") is True).lower()
        if args.mode == "LIVE" and (settings.get("enabled") is not True or settings.get("stop") is not False):
            raise ValueError("LIVE disabled or stopped")
        state = store.load()
        if args.import_metrics:
            state["metrics"] = performance.ingest(json.loads(Path(args.import_metrics).read_text(encoding="utf-8")), state["posts"])
        universe, markets = market.discover(http, state, cfg, now)
        stories = hunters.news(http, cfg, universe, now)
        signals, social_status = hunters.social(http, cfg, state, universe, now)
        topics = plan(markets, stories, signals, state, cfg, now)
        learned = performance.strategy(state.get("metrics", []), state["posts"])
        # Quality score remains the gate; measured performance only breaks ties.
        topics.sort(key=lambda t: (t["score"], learned.get(t["kind"], 0)), reverse=True)
        report.update(markets=markets, news=stories, topics=topics, social_status=social_status, social=signals,
                      universe_size=len(universe), strategy=learned)
        for topic in topics:
            if topic["duplicate"] or topic["score"] < cfg["threshold"]:
                continue
            try:
                topic["market"] = market.refresh(http, topic["market"], utcnow())
                draft = editor.draft(topic, state["posts"])
                validate(topic, draft, state["posts"], utcnow())
                media = produce(http, topic, cfg, args.output, len(state["posts"]) + len(report["drafts"]))
                report["drafts"].append({**draft, "media": media, "kind": topic["kind"], "event_id": topic["id"]})
                if args.mode == "LIVE":
                    publish(store, topic, draft, media, args.output, cfg)
                # One highest-quality post per scan; never fill a quota.
                break
            except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
                report["errors"].append({"source": topic["id"], "error": str(exc), "time": utcnow().isoformat()})
                # A reserved attempt must not be followed by a different publication in this run.
                if any(p["event_id"] == topic["id"] for p in store.data["posts"]):
                    code = 1
                    break
        report["status"] = "published" if args.mode == "LIVE" and report["drafts"] and code == 0 else "preview ready" if report["drafts"] else "no eligible content"
        if not markets:
            raise RuntimeError("No fresh verified market data; no publication")
    except (ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        code = 1
        report["status"] = "failed safely"
        report["errors"].append({"source": "pipeline", "error": str(exc), "time": utcnow().isoformat()})
    finally:
        report.update(posts=store.data["posts"], requests=http.usage, ai_calls=editor.calls, ai_tokens=editor.tokens, ai_limit=cfg["max_ai_calls"])
        report["errors"].extend(http.errors)
        if args.mode == "LIVE" and store.sha:
            store.data["errors"] = (store.data.get("errors", []) + report["errors"])[-100:]
            store.data["runs"] = (store.data.get("runs", []) + [{"time": report["time"], "status": report["status"], "requests": http.usage,
                                  "ai_calls": editor.calls, "ai_tokens": editor.tokens}])[-100:]
            try:
                store.save()
            except (ValueError, RuntimeError) as exc:
                code = 1
                report["status"] = "state persistence failed; inspect journal before rerun"
        elif args.mode == "PREVIEW":
            # Local-only discovery cache. A preview never consumes LIVE journal budget.
            atomic_json(args.state, store.data)
        atomic_json(Path(args.output) / "report.json", report)
        dashboard.render(report, args.output)
        print(json.dumps({k: report[k] for k in ("mode", "status", "time", "ai_calls")}, ensure_ascii=True))
        if code:
            print(json.dumps({"errors": report["errors"]}, ensure_ascii=True))
    return code


def main():
    parser = argparse.ArgumentParser(description="X LEI 3.0 evidence-first crypto newsroom")
    parser.add_argument("--mode", choices=("PREVIEW", "LIVE"), default="PREVIEW")
    parser.add_argument("--config")
    parser.add_argument("--state", default="data/newsroom-state.json")
    parser.add_argument("--output", default="newsroom-output")
    parser.add_argument("--init-state", action="store_true")
    parser.add_argument("--import-metrics")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
