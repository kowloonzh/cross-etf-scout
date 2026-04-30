from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class Signal:
    symbol: str
    name: str
    category: str
    score: float
    risk_level: str
    reason: str
    price_growth_3d: float | None = None
    price_growth_5d: float | None = None
    price_growth_10d: float | None = None
    price_growth_20d: float | None = None
    premium_change_3d: float | None = None
    premium_change_5d: float | None = None
    avg_premium_5d: float | None = None
    amount_ratio_5d: float | None = None


def compute_etf_metrics(
    symbol: str,
    name: str,
    prices: pd.DataFrame,
    navs: pd.DataFrame,
    lookback: int = 5,
) -> dict:
    merged = pd.merge(prices.copy(), navs.copy(), on="date", how="inner").sort_values("date")
    if merged.empty:
        raise ValueError(f"No overlapping price/nav rows for {symbol}")

    window = merged.tail(lookback)
    first = window.iloc[0]
    latest = window.iloc[-1]

    first_close = float(first["close"])
    first_nav = float(first["nav"])
    latest_close = float(latest["close"])
    latest_nav = float(latest["nav"])

    first_premium = _percent_change(first_close, first_nav)
    latest_premium = _percent_change(latest_close, latest_nav)
    price_growth = _percent_change(latest_close, first_close)
    premium_change = latest_premium - first_premium
    score = round(price_growth + (latest_premium * 0.8), 2)

    return {
        "symbol": symbol,
        "name": name,
        "price_growth_pct": round(price_growth, 2),
        "premium_pct": round(latest_premium, 2),
        "premium_change_pct": round(premium_change, 2),
        "score": score,
        "signal": _classify_metric_signal(score, latest_premium, price_growth),
    }


def classify_signal(score: float, premium_pct: float, price_growth_pct: float) -> str:
    if score >= 15 and premium_pct >= 7 and price_growth_pct >= 7:
        return "强异动"
    if score >= 8 and premium_pct >= 3 and price_growth_pct >= 3:
        return "异动"
    if score >= 4 and premium_pct >= 2:
        return "关注"
    return "正常"


def rank_anomalies(rows: Iterable[dict], top: int = 20) -> list[dict]:
    positive = [
        row
        for row in rows
        if row.get("signal") != "正常" and float(row.get("score", 0)) > 0
    ]
    return sorted(positive, key=lambda row: float(row.get("score", 0)), reverse=True)[:top]


def compute_rolling_metrics(quotes: pd.DataFrame) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()

    metrics = quotes.copy()
    metrics["trade_date"] = metrics["trade_date"].astype(str)
    metrics = metrics.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    metrics["current"] = pd.to_numeric(metrics["current"], errors="coerce")
    metrics["premium_rate"] = pd.to_numeric(metrics["premium_rate"], errors="coerce")
    metrics["amount"] = pd.to_numeric(metrics["amount"], errors="coerce")

    grouped = metrics.groupby("symbol", group_keys=False)
    for window in (3, 5, 10, 20):
        periods = window - 1
        baseline_price = grouped["current"].shift(periods)
        baseline_premium = grouped["premium_rate"].shift(periods)
        metrics[f"price_growth_{window}d"] = (
            ((metrics["current"] - baseline_price) / baseline_price) * 100
        ).round(2)
        metrics[f"premium_change_{window}d"] = (
            metrics["premium_rate"] - baseline_premium
        ).round(2)

    metrics["avg_premium_5d"] = (
        grouped["premium_rate"]
        .rolling(5, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .round(2)
    )
    avg_amount_5d = (
        grouped["amount"]
        .rolling(5, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )
    metrics["amount_ratio_5d"] = (metrics["amount"] / avg_amount_5d).round(2)
    return metrics


def generate_candidate_signals(quotes: pd.DataFrame, trade_date: str) -> list[Signal]:
    metrics = compute_rolling_metrics(quotes)
    if metrics.empty:
        return []

    latest_rows = metrics[metrics["trade_date"] == str(trade_date)]
    signals: list[Signal] = []
    for row in latest_rows.to_dict("records"):
        signal = _signal_from_row(row)
        if signal is not None:
            signals.append(signal)
    return sorted(signals, key=lambda signal: signal.score, reverse=True)


def _classify_metric_signal(score: float, premium_pct: float, price_growth_pct: float) -> str:
    if score >= 30 and premium_pct >= 10 and price_growth_pct >= 10:
        return "强异动"
    if score >= 8 and premium_pct >= 3 and price_growth_pct >= 3:
        return "异动"
    if score >= 4 and premium_pct >= 2:
        return "关注"
    return "正常"


def _signal_from_row(row: dict) -> Signal | None:
    symbol = str(row["symbol"])
    name = str(row.get("name") or "")
    premium = _safe_float(row.get("premium_rate"))
    price_growth_5d = _safe_float(row.get("price_growth_5d"))
    price_growth_10d = _safe_float(row.get("price_growth_10d"))
    premium_change_5d = _safe_float(row.get("premium_change_5d"))
    avg_premium_5d = _safe_float(row.get("avg_premium_5d"))
    amount_ratio_5d = _safe_float(row.get("amount_ratio_5d"))

    if premium is None:
        return None

    if premium >= 12 or (
        price_growth_5d is not None
        and price_growth_5d >= 15
        and amount_ratio_5d is not None
        and amount_ratio_5d >= 1.5
    ):
        return _build_signal(row, symbol, name, "极端过热", "高")

    if (
        price_growth_5d is not None
        and premium_change_5d is not None
        and amount_ratio_5d is not None
        and 3 <= premium < 12
        and price_growth_5d >= 5
        and premium_change_5d >= 2
        and amount_ratio_5d >= 1.2
    ):
        return _build_signal(row, symbol, name, "强势启动", "中")

    if (
        price_growth_10d is not None
        and avg_premium_5d is not None
        and amount_ratio_5d is not None
        and price_growth_10d >= 8
        and avg_premium_5d >= 4
        and amount_ratio_5d >= 0.8
    ):
        return _build_signal(row, symbol, name, "趋势确认", "中")

    if (
        price_growth_10d is not None
        and premium_change_5d is not None
        and amount_ratio_5d is not None
        and price_growth_10d >= 5
        and premium_change_5d <= -2
        and amount_ratio_5d < 1
    ):
        return _build_signal(row, symbol, name, "热度退潮", "中")

    return None


def _build_signal(row: dict, symbol: str, name: str, category: str, risk_level: str) -> Signal:
    price_growth_3d = _safe_float(row.get("price_growth_3d"))
    price_growth_5d = _safe_float(row.get("price_growth_5d"))
    price_growth_10d = _safe_float(row.get("price_growth_10d"))
    price_growth_20d = _safe_float(row.get("price_growth_20d"))
    premium_change_3d = _safe_float(row.get("premium_change_3d"))
    premium_change_5d = _safe_float(row.get("premium_change_5d"))
    avg_premium_5d = _safe_float(row.get("avg_premium_5d"))
    amount_ratio_5d = _safe_float(row.get("amount_ratio_5d"))
    premium = _safe_float(row.get("premium_rate")) or 0.0
    score = _score_candidate(
        price_growth_5d=price_growth_5d,
        premium=premium,
        premium_change_5d=premium_change_5d,
        amount_ratio_5d=amount_ratio_5d,
        risk_level=risk_level,
    )
    reason = (
        f"5日涨幅 {_fmt_pct(price_growth_5d)}，"
        f"当前溢价率 {_fmt_pct(premium)}，"
        f"5日溢价变化 {_fmt_pct(premium_change_5d)}，"
        f"成交额为5日均值的 {_fmt_ratio(amount_ratio_5d)}"
    )
    return Signal(
        symbol=symbol,
        name=name,
        category=category,
        score=score,
        risk_level=risk_level,
        reason=reason,
        price_growth_3d=price_growth_3d,
        price_growth_5d=price_growth_5d,
        price_growth_10d=price_growth_10d,
        price_growth_20d=price_growth_20d,
        premium_change_3d=premium_change_3d,
        premium_change_5d=premium_change_5d,
        avg_premium_5d=avg_premium_5d,
        amount_ratio_5d=amount_ratio_5d,
    )


def _score_candidate(
    price_growth_5d: float | None,
    premium: float,
    premium_change_5d: float | None,
    amount_ratio_5d: float | None,
    risk_level: str,
) -> float:
    score = min(price_growth_5d or 0.0, 20) * 1.0
    score += min(premium, 12) * 1.5
    score += min(premium_change_5d or 0.0, 8) * 2.0
    score += min(amount_ratio_5d or 0.0, 3) * 5.0
    if risk_level == "高":
        score -= 5
    return round(score, 2)


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "无数据"
    return f"{value:.1f}%"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "无数据"
    return f"{value:.2f}倍"


def _percent_change(current: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("baseline cannot be zero")
    return ((current - baseline) / baseline) * 100
