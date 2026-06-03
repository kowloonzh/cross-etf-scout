from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from cross_etf_scout.analysis import Signal, compute_rolling_metrics

WATCH_CATEGORIES = ("强势启动", "趋势确认")
DANGER_CATEGORIES = ("极端过热", "热度退潮", "流动性不足或数据异常")
DEFAULT_CONFIG_PATH = Path("config/config.yaml")


def build_report_sections(quotes: pd.DataFrame, trade_date: str) -> dict[str, pd.DataFrame]:
    metrics = compute_rolling_metrics(quotes)
    if metrics.empty:
        return {}

    today = metrics[metrics["trade_date"] == str(trade_date)].copy()
    if today.empty:
        return {}

    sections = {
        "今日溢价率 Top 20": _top(today, "premium_rate"),
        "今日成交额 Top 20": _top(today, "amount"),
        "今日涨幅 Top 20": _top(today, "percent"),
        "5日价格涨幅 Top 20": _top(today, "price_growth_5d"),
        "5日溢价率上升 Top 20": _top(today, "premium_change_5d"),
    }
    today["resonance_score"] = (
        today["price_growth_5d"].fillna(0)
        + today["premium_change_5d"].fillna(0) * 2
        + today["amount_ratio_5d"].fillna(0) * 5
    ).round(2)
    sections["价格 + 溢价共振榜"] = _top(today, "resonance_score")
    sections["过热风险榜"] = _top(
        today[(today["premium_rate"] >= 12) | (today["price_growth_5d"] >= 15)],
        "premium_rate",
    )
    return sections


def format_report(sections: dict[str, pd.DataFrame]) -> str:
    if not sections:
        return "没有可用行情数据。请先运行 ces collect。"

    lines: list[str] = []
    columns = [
        "symbol",
        "name",
        "current",
        "percent",
        "premium_rate",
        "amount",
        "price_growth_5d",
        "premium_change_5d",
        "amount_ratio_5d",
        "resonance_score",
    ]
    for title, frame in sections.items():
        lines.append(f"## {title}")
        if frame.empty:
            lines.append("无")
        else:
            shown_columns = [column for column in columns if column in frame.columns]
            lines.append(frame[shown_columns].to_string(index=False))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_candidates(signals: list[Signal]) -> str:
    if not signals:
        return "观察池为空。"

    lines: list[str] = []
    for category in ("强势启动", "趋势确认", "极端过热", "热度退潮", "流动性不足或数据异常"):
        grouped = [signal for signal in signals if signal.category == category]
        if not grouped:
            continue
        lines.append(f"## {category}")
        for signal in grouped:
            lines.append(
                f"- {signal.symbol} {signal.name} | score={signal.score:.2f} "
                f"| 风险={signal.risk_level} | {signal.reason}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_telegram_digest(
    signals: list[Signal],
    trade_date: str,
    quote_count: int,
    active_count: int,
    focus_rows: list[dict[str, Any]] | None = None,
) -> str:
    watch_signals = [
        signal for signal in signals if signal.category in WATCH_CATEGORIES
    ]
    danger_signals = [
        signal for signal in signals if signal.category in DANGER_CATEGORIES
    ]
    focus_rows = focus_rows or []

    lines = [
        f"<b>cross-etf-scout {escape(trade_date)}</b>",
        f"行情: {quote_count}/{active_count} | 可选: {len(watch_signals)} | 危险: {len(danger_signals)}",
        "",
        "<b>特别关注</b>",
    ]
    lines.extend(_format_focus_group(focus_rows, signals))
    lines.extend([
        "",
        "<b>可选池</b>",
    ])
    lines.extend(_format_digest_group(watch_signals))
    lines.extend(["", "<b>危险池</b>"])
    lines.extend(_format_digest_group(danger_signals))
    return "\n".join(lines).rstrip()


def format_workwechat_digest(
    signals: list[Signal],
    trade_date: str,
    quote_count: int,
    active_count: int,
    focus_rows: list[dict[str, Any]] | None = None,
) -> str:
    watch_signals = [
        signal for signal in signals if signal.category in WATCH_CATEGORIES
    ]
    danger_signals = [
        signal for signal in signals if signal.category in DANGER_CATEGORIES
    ]
    focus_rows = focus_rows or []

    lines = [
        f"cross-etf-scout {trade_date}",
        f"行情: {quote_count}/{active_count} | 可选: {len(watch_signals)} | 危险: {len(danger_signals)}",
        "",
        "特别关注",
    ]
    lines.extend(_format_workwechat_focus_group(focus_rows, signals))
    lines.extend(["", "可选池"])
    lines.extend(_format_workwechat_digest_group(watch_signals))
    lines.extend(["", "危险池"])
    lines.extend(_format_workwechat_digest_group(danger_signals))
    return "\n".join(lines).rstrip()


def load_focus_etf_codes(path: str | Path = DEFAULT_CONFIG_PATH) -> list[str]:
    config_path = Path(path)
    if not config_path.exists():
        return []
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return []
    raw_codes = data.get("focus_etfs", [])
    if not isinstance(raw_codes, list):
        return []
    return [str(code).strip() for code in raw_codes if str(code).strip()]


def build_focus_rows(
    quotes: pd.DataFrame,
    trade_date: str,
    focus_codes: list[str],
) -> list[dict[str, Any]]:
    if quotes.empty or not focus_codes:
        return []
    metrics = compute_rolling_metrics(quotes)
    if metrics.empty:
        return []
    today = metrics[metrics["trade_date"] == str(trade_date)].copy()
    if today.empty:
        return []

    normalized_focus_codes = [_normalize_symbol(code) for code in focus_codes]
    today["normalized_symbol"] = today["symbol"].map(_normalize_symbol)
    matched = today[today["normalized_symbol"].isin(normalized_focus_codes)]
    order = {code: index for index, code in enumerate(normalized_focus_codes)}
    rows = matched.to_dict("records")
    return sorted(
        rows,
        key=lambda row: order.get(_normalize_symbol(row.get("symbol")), len(order)),
    )


def _format_digest_group(signals: list[Signal]) -> list[str]:
    if not signals:
        return ["无"]
    return [_format_digest_signal(signal) for signal in signals]


def _format_digest_signal(signal: Signal) -> str:
    return (
        f"<code>{escape(signal.symbol)}</code> {escape(signal.name)}\n"
        f"{escape(signal.category)} | score={signal.score:.2f} | 风险={escape(signal.risk_level)}\n"
        f"{escape(signal.reason)}"
    )


def _format_workwechat_digest_group(signals: list[Signal]) -> list[str]:
    if not signals:
        return ["无"]
    return [_format_workwechat_digest_signal(signal) for signal in signals]


def _format_workwechat_digest_signal(signal: Signal) -> str:
    return (
        f"{signal.symbol} {signal.name}\n"
        f"{signal.category} | score={signal.score:.2f} | 风险={signal.risk_level}\n"
        f"{signal.reason}"
    )


def _format_focus_group(
    rows: list[dict[str, Any]],
    signals: list[Signal],
) -> list[str]:
    if not rows:
        return ["无"]
    signals_by_symbol = {signal.symbol: signal for signal in signals}
    return [_format_focus_row(row, signals_by_symbol.get(str(row.get("symbol")))) for row in rows]


def _format_workwechat_focus_group(
    rows: list[dict[str, Any]],
    signals: list[Signal],
) -> list[str]:
    if not rows:
        return ["无"]
    signals_by_symbol = {signal.symbol: signal for signal in signals}
    return [
        _format_workwechat_focus_row(row, signals_by_symbol.get(str(row.get("symbol"))))
        for row in rows
    ]


def _format_focus_row(row: dict[str, Any], signal: Signal | None) -> str:
    symbol = str(row.get("symbol") or "")
    name = str(row.get("name") or "")
    status = signal.category if signal is not None else "未入池"
    return (
        f"<code>{escape(symbol)}</code> {escape(name)}\n"
        f"现价 {_fmt_price(row.get('current'))} | 今日 {_fmt_signed_pct(row.get('percent'))} | 溢价 {_fmt_pct(row.get('premium_rate'))}\n"
        f"5日涨幅 {_fmt_pct(row.get('price_growth_5d'))} | 5日溢价变化 {_fmt_signed_pct(row.get('premium_change_5d'))} | 成交额 {_fmt_ratio(row.get('amount_ratio_5d'))}\n"
        f"状态: {escape(status)}"
    )


def _format_workwechat_focus_row(row: dict[str, Any], signal: Signal | None) -> str:
    symbol = str(row.get("symbol") or "")
    name = str(row.get("name") or "")
    status = signal.category if signal is not None else "未入池"
    return (
        f"{symbol} {name}\n"
        f"现价 {_fmt_price(row.get('current'))} | 今日 {_fmt_signed_pct(row.get('percent'))} | 溢价 {_fmt_pct(row.get('premium_rate'))}\n"
        f"5日涨幅 {_fmt_pct(row.get('price_growth_5d'))} | 5日溢价变化 {_fmt_signed_pct(row.get('premium_change_5d'))} | 成交额 {_fmt_ratio(row.get('amount_ratio_5d'))}\n"
        f"状态: {status}"
    )


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith(("SH", "SZ")):
        return raw[2:]
    return raw


def _fmt_price(value: Any) -> str:
    if value is None or pd.isna(value):
        return "无数据"
    return f"{float(value):.2f}"


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "无数据"
    return f"{float(value):.1f}%"


def _fmt_signed_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "无数据"
    return f"{float(value):+.1f}%"


def _fmt_ratio(value: Any) -> str:
    if value is None or pd.isna(value):
        return "无数据"
    return f"{float(value):.2f}倍"


def _top(frame: pd.DataFrame, column: str, limit: int = 20) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame.head(0)
    return frame.sort_values(column, ascending=False).head(limit).reset_index(drop=True)
