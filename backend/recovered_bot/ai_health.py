"""ai_health.py - live, read-only health report for the AI assistant.

Goal: the assistant (and the owner) can ask "where is data slow / leaking / freezing?"
and get a short, actionable answer with benefits, without hunting logs or asking 4 people.

Sources (all cached / O(1) or cheap tail):
  * loop_watch.snapshot()  – freezes + OUR CODE BUSY / PHONE PAUSED?
  * telemetry.snapshot()   – CPU, REST top, data_hint, broadcast lag
  * ops_status.snapshot()  – current-run problems, restarts, zip
  * optional /api/ai/health screen timings if present in process

Never raises. Never changes trading. Safe to call from AI context builders.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def build_report(data_dir: str = "") -> Dict[str, Any]:
    """Structured report + plain-English suggestions for the AI assistant."""
    now = time.time()
    report: Dict[str, Any] = {
        "ok": True,
        "ts": int(now),
        "summary": "",
        "freezes": {},
        "speed": {},
        "data": {},
        "backend": {},
        "suggestions": [],
        "benefits": [],
    }

    # --- freezes (loop_watch)
    lw = _safe(lambda: __import__("recovered_bot.loop_watch", fromlist=["snapshot"]).snapshot(), {}) or {}
    last = lw.get("last_stall")
    report["freezes"] = {
        "loop_lag_ms": lw.get("loop_lag_ms", 0),
        "loop_lag_max_60s": lw.get("loop_lag_max_60s", 0),
        "stalls_10min": lw.get("stalls_10min", 0),
        "last_stall": last,
    }
    if last:
        cause = last.get("cause") or "unknown"
        where = last.get("where") or "?"
        ago = last.get("ago_s", 0)
        ms = last.get("ms", 0)
        if cause == "OUR CODE BUSY":
            report["suggestions"].append(
                f"Last freeze {ago}s ago was OUR CODE BUSY ({ms}ms) at {where}. "
                "Find that file:line and move blocking work off the event loop (thread / to_thread)."
            )
            report["benefits"].append(
                "Fixing OUR CODE BUSY freezes stops false WS disconnects and loading spinners."
            )
        else:
            report["suggestions"].append(
                f"Last freeze {ago}s ago looks like PHONE PAUSED? ({ms}ms, stack not captured). "
                "Set Termux battery to Unrestricted and lock the app in Recents."
            )
            report["benefits"].append(
                "Unrestricted Termux stops Android from freezing the backend; labels will confirm."
            )
    elif lw.get("stalls_10min", 0) == 0 and (lw.get("loop_lag_max_60s") or 0) < 500:
        report["suggestions"].append("No freezes in the last 10 minutes; loop lag is healthy.")

    # --- speed + data (telemetry)
    tel = _safe(lambda: __import__("recovered_bot.telemetry", fromlist=["snapshot"]).snapshot(), {}) or {}
    report["speed"] = {
        "cpu_backend_pct": (tel.get("cpu") or {}).get("backend_pct"),
        "cpu_system_pct": (tel.get("cpu") or {}).get("system_pct"),
        "broadcast_avg_ms": (tel.get("broadcast") or {}).get("avg_ms"),
        "broadcast_max_ms": (tel.get("broadcast") or {}).get("max_ms"),
        "poll_cycle_ms": (tel.get("poll") or {}).get("cycle_ms"),
        "alerts": tel.get("alerts") or [],
    }
    dh = tel.get("data_hint") or {}
    rest = tel.get("rest") or {}
    report["data"] = {
        "rest_per_min": rest.get("per_min"),
        "rest_total": rest.get("total"),
        "top_endpoints": rest.get("top") or [],
        "likely_heavy": dh.get("likely_heavy"),
        "tip": dh.get("tip"),
        "rest_candle_calls": (tel.get("poll") or {}).get("rest_candle_calls"),
        "ws_candles": (tel.get("poll") or {}).get("ws_candles"),
    }
    if (rest.get("per_min") or 0) >= 80:
        report["suggestions"].append(
            f"REST is busy ({rest.get('per_min')}/min). Top: "
            + ", ".join(f"{t.get('ep')}×{t.get('n')}" for t in (rest.get("top") or [])[:3])
            + ". Prefer WebSocket candles over REST to cut mobile data."
        )
        report["benefits"].append(
            "Cutting REST candle calls reduces Termux mobile data (you saw ~18 GB) and lowers lag."
        )
    if (report["speed"].get("broadcast_avg_ms") or 0) > 150:
        report["suggestions"].append(
            f"Broadcast tick avg {report['speed']['broadcast_avg_ms']}ms – UI may feel sticky. "
            "Check build_ms vs send cost; drop heavy fields from the WS payload if needed."
        )
        report["benefits"].append("Faster broadcast keeps charts and PnL updating without freezes.")

    # --- backend card (ops_status) – current run only
    ops = _safe(
        lambda: __import__("recovered_bot.ops_status", fromlist=["snapshot"]).snapshot(data_dir),
        {},
    ) or {}
    report["backend"] = {
        "build": ops.get("build"),
        "uptime_s": ops.get("uptime_s"),
        "restarts_today": ops.get("restarts_today"),
        "run_started": ops.get("run_started"),
        "problems": ops.get("problems") or [],
        "problems_scope": ops.get("problems_scope"),
        "zip": (ops.get("zip") or {}).get("name"),
        "restart_reasons": ops.get("restart_reasons") or [],
    }
    if ops.get("restarts_today", 0) >= 3:
        report["suggestions"].append(
            f"Restarts today: {ops.get('restarts_today')}. Check restart_reasons / last_exits on the Backend panel."
        )
        report["benefits"].append("Knowing why it restarts stops mystery downtime and red lines on old logs.")
    if ops.get("problems"):
        report["suggestions"].append(
            "Current-run problems (newest first): " + " | ".join(ops["problems"][:3])
        )

    # --- short summary for the AI
    parts: List[str] = []
    if last:
        parts.append(f"last freeze={last.get('cause')} {last.get('ms')}ms")
    else:
        parts.append("no recent freeze")
    parts.append(f"REST={rest.get('per_min', 0)}/min")
    parts.append(f"restarts_today={ops.get('restarts_today', 0)}")
    if dh.get("likely_heavy"):
        parts.append(f"data≈{dh['likely_heavy']}")
    report["summary"] = "; ".join(parts)

    if not report["suggestions"]:
        report["suggestions"].append("All clear: no freezes, REST moderate, current-run log clean.")
        report["benefits"].append("Keep running 2–4 h and re-check Load Report to confirm stability.")

    return report


def plain_text(data_dir: str = "") -> str:
    """One block of text the AI can paste into its context."""
    r = build_report(data_dir)
    lines = [
        "=== APP HEALTH (read-only) ===",
        f"Summary: {r.get('summary')}",
        "",
        "Freezes:",
        f"  lag_now={r['freezes'].get('loop_lag_ms')}ms  max60s={r['freezes'].get('loop_lag_max_60s')}ms  "
        f"stalls_10min={r['freezes'].get('stalls_10min')}",
    ]
    last = r["freezes"].get("last_stall")
    if last:
        lines.append(
            f"  last: cause={last.get('cause')} ms={last.get('ms')} ago_s={last.get('ago_s')} where={last.get('where')}"
        )
    lines += [
        "",
        "Speed:",
        f"  cpu_backend={r['speed'].get('cpu_backend_pct')}%  broadcast_avg={r['speed'].get('broadcast_avg_ms')}ms  "
        f"poll={r['speed'].get('poll_cycle_ms')}ms",
        f"  alerts: {r['speed'].get('alerts')}",
        "",
        "Data:",
        f"  REST/min={r['data'].get('rest_per_min')}  top={r['data'].get('top_endpoints')}",
        f"  likely_heavy={r['data'].get('likely_heavy')}",
        f"  tip={r['data'].get('tip')}",
        "",
        "Backend:",
        f"  zip={r['backend'].get('zip')}  uptime_s={r['backend'].get('uptime_s')}  "
        f"restarts_today={r['backend'].get('restarts_today')}  scope={r['backend'].get('problems_scope')}",
        f"  problems: {r['backend'].get('problems')}",
        "",
        "Suggestions (do these):",
    ]
    for s in r.get("suggestions") or []:
        lines.append(f"  - {s}")
    lines.append("")
    lines.append("Benefits:")
    for b in r.get("benefits") or []:
        lines.append(f"  - {b}")
    return "\n".join(lines)
