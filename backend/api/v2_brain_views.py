"""api/v2_brain_views.py - Part M4c (the split of api/v2_data.py, which had grown to 431 lines): the Brain Trader / Brain pages of the V2 data API, MOVED here with the same code.
Every function is a read-only view(con, params, now, data_dir) -> dict, exactly as before; api/v2_data.py imports VIEWS and NAMES from here and merges them into its own VIEWS, so the
route names, the answers, the v2_api_enabled switch and the token check do not change. NAMES = the routes whose answer does NOT need the market store (own files only).
No network, no write, no trading import (guard test scans this file too). Added with the split: brain_timeline (Part M4a)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_bt_chart as CH
import v2_bt_compare as CP
import v2_bt_dash as DH
import v2_bt_exitlab as XL
import v2_bt_progress as PG
import v2_bt_detail as DT
import v2_bt_filter as FL
import v2_bt_health as HE
import v2_bt_ready as RD
import v2_bt_playbook as PB
import v2_bt_report as BR
import v2_bt_review as RV
import v2_bt_verdict as VD
import v2_sys_health as SH
import v2_bt_zonestudy as ZS
import v2_bt_limits as LM
import v2_brain_chat as BC
import v2_candles as K
import v2_bt_timeline as TL
import v2_bt_why as WY


def v_brain_chat(con, p, now, d):
    """Part 76: Conversational Brain. ?q=bhai BTC me kya hua. Claude answers ONLY from backend facts (see v2_brain_chat.py); one question out to api.anthropic.com, nothing written, never an order."""
    return BC.ask(p.get("q") or "", d, con, now)


def v_brain_dash(con, p, now, d):
    """Part M3: Brain Dashboard = today net (Brain and Current Bot apart), signals, open trades, 30-day pace, daily loss cap, last 8 days, why. ?source=PAPER. Read-only."""
    return DH.build(d, p.get("source") or "PAPER", now)


def v_brain_month(con, p, now, d):
    """Part M2: one UTC month as a calendar: Brain and Current Bot net per day, best / worst day, profit / loss days, worst dip, running line. ?source=PAPER&month=2026-11 (both optional). Read-only."""
    return CP.month_view(d, p.get("source") or "PAPER", p.get("month") or None, now)


def v_sys_health(con, p, now, d):
    """Part M1a: System Health = real measured facts only (backend, candle feed, collector, Brain tick, safety, CPU, RAM, disk); what cannot be measured says NOT AVAILABLE. Read-only."""
    return SH.build(d, now)


def v_brain_exits(con, p, now, d):
    """Part E1: Exit Study = the same closed trades replayed with other exits (current, TSI turns, half of the gain given back, break-even stop). ?source=REPLAY. Read-only, nothing is applied."""
    return XL.build(d, p.get("source") or "REPLAY", now)


def v_brain_progress(con, p, now, d):
    """Part L1: Learning Progress = today (trades, profit / loss counts, net), 30 days, 5 weeks, trend (older vs newer half), mistakes / fixed / learned groups in plain words. ?source=PAPER. Read-only."""
    return PG.build(d, p.get("source") or "PAPER", now)


def v_brain_compare(con, p, now, d):
    """Part X1: Owl Brain vs Current Bot vs Take-All baseline for one UTC day + a 30-day calendar. ?source=PAPER&day=2026-11-01 (both optional). Read-only; Take-All is a simulation on saved candles."""
    return CP.build(d, p.get("source") or "PAPER", p.get("day") or None, now)


def v_brain_verdict(con, p, now, d):
    """Part 91a: Simple Results = ONE verdict word (PROFIT / LOSS / MIXED / NOT ENOUGH DATA), net, drawdown, losing streak, equity line, USE / STOP sentences. ?source=PAPER. Read-only."""
    return VD.build(d, p.get("source") or "PAPER", now)


def v_brain_ready(con, p, now, d):
    """Part N2: Brain Ready? What the Brain does by itself + 8 plain checks. ?source=PAPER (or SHADOW). Read-only; live is always LOCKED."""
    return RD.build(d, p.get("source") or "PAPER", now)


def v_brain_health(con, p, now, d):
    """Part 90a: Brain Health (pipeline, sample coverage per market state, safety chips, graduation checklist, what is missing). ?source=PAPER&interval=5m. Read-only; live is always LOCKED."""
    return HE.build(d, p.get("source") or "PAPER", now, p.get("interval") or "5m")


def v_brain_limits(con, p, now, d):
    """Part 89b: squeeze study (what the break did after a squeeze) + starting-limits study (BT-01 limits replayed with other values). ?interval=5m. Reads only the saved study file (made by v2_bt_limits.py, also every 6 h by the auto-runner)."""
    iv = p.get("interval") or "5m"
    if iv not in K.INTERVALS:
        raise ValueError("interval must be 3m or 5m")
    return LM.build(d, iv, now)


def v_brain_zones(con, p, now, d):
    """Part 89a: the SD-zone study (what price did after arriving in a zone, hypothetical BT-01 trade, TRAIN / HOLDOUT, baseline). ?interval=5m. Reads only the saved study file (made by v2_bt_zonestudy.py run)."""
    iv = p.get("interval") or "5m"
    if iv not in K.INTERVALS:
        raise ValueError("interval must be 3m or 5m")
    return ZS.build(d, iv, now)


def v_brain_playbook(con, p, now, d):
    """Part 88c: Indicator Playbook = what the Brain is learning, per indicator (USE / AVOID / MIXED / thin states). ?source=PAPER&interval=5m|15m&state=TREND|SIDEWAYS|CONSOLIDATION|BREAKOUT (Part 88e, both optional). Read-only."""
    return PB.build_playbook(d, p.get("source") or "PAPER", now, p.get("interval") or None, p.get("state") or None)


def v_brain_whatif(con, p, now, d):
    """Part 88c: What-if explorer on the same closed paper trades (counterfactual, nothing runs). ?source=PAPER&skip=zone:LABEL|tsi:LABEL&only=... Read-only."""
    return PB.build_whatif(d, p.get("source") or "PAPER", p.get("skip"), p.get("only"), now)


def v_brain_filter(con, p, now, d):
    """Part 88b: TAKE / SKIP filter candidates + A/B on the same closed paper trades (counterfactual, nothing runs). ?source=PAPER. Read-only."""
    return FL.build(d, p.get("source") or "PAPER", now)


def v_brain_review(con, p, now, d):
    """Part 88a: the night review of the closed paper trades. ?source=PAPER. Read-only."""
    return RV.build(d, p.get("source") or "PAPER", now)


def v_brain_signal(con, p, now, d):
    """Part 87: Signal Detail of one coin now. ?symbol=BTCUSDT&interval=5m&source=PAPER. Read-only."""
    sym, iv = p.get("symbol") or "", p.get("interval") or "5m"
    if not K._symbol_ok(sym) or iv not in K.INTERVALS:
        raise ValueError("symbol must be like BTCUSDT and interval 3m or 5m")
    return DT.signal(d, sym, iv, p.get("source") or "PAPER", now)


def v_brain_trade(con, p, now, d):
    """Part 87: the open PAPER trade of one coin (or a note that there is none). ?symbol=&interval=. Read-only."""
    sym, iv = p.get("symbol") or "", p.get("interval") or "5m"
    if not K._symbol_ok(sym) or iv not in K.INTERVALS:
        raise ValueError("symbol must be like BTCUSDT and interval 3m or 5m")
    return DT.trade(d, sym, iv, p.get("source") or "PAPER", now)


def v_brain_today(con, p, now, d):
    """Part 86a: the Today page (report lines + newest answer per coin). ?source=PAPER. Own file, read-only."""
    return CH.today(d, p.get("source") or "PAPER", now)


def v_brain_chart(con, p, now, d):
    """Part 86a: the CURRENT chart of one coin in plain sentences. ?symbol=BTCUSDT&interval=5m. Read-only, nothing is saved."""
    sym, iv = p.get("symbol") or "", p.get("interval") or "5m"
    if not K._symbol_ok(sym) or iv not in K.INTERVALS:
        raise ValueError("symbol must be like BTCUSDT and interval 3m or 5m")
    return CH.view(d, sym, iv, now)


def v_brain_report(con, p, now, d):
    """Part 85b: the Brain Trader daily report in plain words. ?source=PAPER&day=YYYY-MM-DD (UTC day, both optional). Own file, read-only (see v2_bt_report.py)."""
    return BR.build(d, p.get("source") or "PAPER", p.get("day") or None, now)


def v_brain_timeline(con, p, now, d):
    """Part M4a: Brain and Activity timeline of one UTC day (Brain decisions / trades next to the Current Bot's trades, per-coin table). ?source=PAPER&day=2026-11-01 (both optional). Read-only."""
    return TL.build(d, p.get("source") or "PAPER", p.get("day") or None, now)


def v_brain_why(con, p, now, d):
    """E6: why is the Brain not trading today? Today's decisions grouped by decision and reason, read only. ?source=PAPER."""
    return WY.build(d, p.get("source") or "PAPER", now)


VIEWS = {"brain_why": v_brain_why, "brain_ready": v_brain_ready, "brain_chat": v_brain_chat, "brain_dash": v_brain_dash, "brain_month": v_brain_month, "sys_health": v_sys_health, "brain_exits": v_brain_exits, "brain_progress": v_brain_progress, "brain_compare": v_brain_compare, "brain_verdict": v_brain_verdict, "brain_health": v_brain_health, "brain_limits": v_brain_limits, "brain_zones": v_brain_zones, "brain_playbook": v_brain_playbook, "brain_whatif": v_brain_whatif, "brain_filter": v_brain_filter, "brain_review": v_brain_review, "brain_signal": v_brain_signal, "brain_trade": v_brain_trade, "brain_today": v_brain_today, "brain_chart": v_brain_chart, "brain_report": v_brain_report, "brain_timeline": v_brain_timeline}
NAMES = tuple(n for n in VIEWS if n not in ("brain_chat", "brain_report"))      # these two are answered another way inside dispatch
