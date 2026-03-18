"""Fit analyzer — symbol structural fit and repeated failure detection."""

from collections import Counter, defaultdict
from trading_watchdog.models.verdict import Verdict


def analyze_fit(bots, symbol_pnl=None, trade_logs=None):
    """Identify symbols with structural fit problems.

    Returns dict with fit section data and list of verdicts.
    """
    verdicts = []
    symbol_issues = defaultdict(list)
    size_suppressed = []
    repeated_blocked = Counter()

    for bot in bots:
        bot_id = bot.get("id", "?")
        symbol = bot.get("symbol", "?")
        reason = bot.get("execution_viability_reason", "")
        bucket = bot.get("execution_viability_bucket", "")
        status = bot.get("status", "")
        margin_limited = bot.get("execution_margin_limited", False)

        if status not in ("running", "paused", "recovering", "flash_crash_paused"):
            continue

        if bucket == "size_limited":
            size_suppressed.append({"bot_id": bot_id, "symbol": symbol, "reason": reason})
            symbol_issues[symbol].append("size_limited")

        if bucket in ("margin_limited", "position_capped"):
            symbol_issues[symbol].append(bucket)

        if bot.get("execution_blocked"):
            repeated_blocked[symbol] += 1

    # Symbol PnL analysis for poor performers
    poor_fit_symbols = []
    if symbol_pnl and isinstance(symbol_pnl, dict):
        for sym, data in symbol_pnl.items():
            if not isinstance(data, dict):
                continue
            net = data.get("net_pnl", 0)
            trades = data.get("trade_count", 0)
            win_count = data.get("win_count", 0)
            loss_count = data.get("loss_count", 0)
            win_rate = win_count / trades if trades > 0 else 0

            issues = symbol_issues.get(sym, [])
            is_poor = (
                (trades >= 5 and win_rate < 0.35 and net < 0) or
                (len(issues) >= 2) or
                (repeated_blocked.get(sym, 0) >= 2)
            )
            if is_poor:
                poor_fit_symbols.append({
                    "symbol": sym,
                    "net_pnl": round(net, 4),
                    "trade_count": trades,
                    "win_rate": round(win_rate * 100, 1),
                    "blocker_issues": issues,
                    "blocked_count": repeated_blocked.get(sym, 0),
                })

    # Repeated blocked symbols
    repeat_blocked_list = [
        {"symbol": sym, "count": count}
        for sym, count in repeated_blocked.most_common()
        if count >= 2
    ]

    # Verdicts
    if size_suppressed:
        verdicts.append(Verdict(
            key="fit:size_suppression",
            category="fit",
            severity="medium",
            summary=f"{len(size_suppressed)} bot(s) size-suppressed (min qty/notional)",
            evidence=[f"{s['symbol']}: {s['reason']}" for s in size_suppressed],
        ))

    if poor_fit_symbols:
        verdicts.append(Verdict(
            key="fit:poor_fit_symbols",
            category="fit",
            severity="medium" if len(poor_fit_symbols) <= 2 else "high",
            summary=f"{len(poor_fit_symbols)} symbol(s) structurally poor fit",
            evidence=[f"{s['symbol']}: PnL={s['net_pnl']}, WR={s['win_rate']}%, blocks={s['blocked_count']}" for s in poor_fit_symbols],
        ))

    if repeat_blocked_list:
        verdicts.append(Verdict(
            key="fit:repeat_blocked",
            category="fit",
            severity="medium",
            summary=f"{len(repeat_blocked_list)} symbol(s) repeatedly execution-blocked",
            evidence=[f"{r['symbol']}: {r['count']}x blocked" for r in repeat_blocked_list],
        ))

    section_data = {
        "size_suppressed": size_suppressed,
        "size_suppressed_count": len(size_suppressed),
        "poor_fit_symbols": poor_fit_symbols,
        "poor_fit_count": len(poor_fit_symbols),
        "repeat_blocked": repeat_blocked_list,
        "repeat_blocked_count": len(repeat_blocked_list),
        "symbol_issue_map": {k: list(v) for k, v in symbol_issues.items()},
    }

    return section_data, verdicts
