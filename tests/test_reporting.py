from __future__ import annotations

import pandas as pd

from cross_etf_scout.analysis import compute_rolling_metrics, generate_candidate_signals
from cross_etf_scout.reporting import (
    build_focus_rows,
    build_report_sections,
    format_candidates,
    format_report,
    format_telegram_digest,
    format_focus_live_digest,
    format_workwechat_digest,
)


def test_compute_rolling_metrics_calculates_recent_growth_and_premium_change():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-24", "SZ159100", "巴西ETF华夏", 1.00, 1.0, 100),
            _quote("2026-04-25", "SZ159100", "巴西ETF华夏", 1.03, 2.0, 100),
            _quote("2026-04-26", "SZ159100", "巴西ETF华夏", 1.06, 3.0, 120),
            _quote("2026-04-27", "SZ159100", "巴西ETF华夏", 1.09, 4.0, 160),
            _quote("2026-04-28", "SZ159100", "巴西ETF华夏", 1.12, 6.0, 220),
        ]
    )

    metrics = compute_rolling_metrics(quotes)
    latest = metrics.iloc[-1]

    assert latest["price_growth_5d"] == 12.0
    assert latest["premium_change_5d"] == 5.0
    assert latest["avg_premium_5d"] == 3.2
    assert latest["amount_ratio_5d"] == 1.57


def test_generate_candidate_signals_groups_strong_start_and_overheat():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-24", "SZ159100", "巴西ETF华夏", 1.00, 1.0, 100),
            _quote("2026-04-25", "SZ159100", "巴西ETF华夏", 1.03, 2.0, 100),
            _quote("2026-04-26", "SZ159100", "巴西ETF华夏", 1.06, 3.0, 120),
            _quote("2026-04-27", "SZ159100", "巴西ETF华夏", 1.09, 4.0, 160),
            _quote("2026-04-28", "SZ159100", "巴西ETF华夏", 1.12, 6.0, 220),
            _quote("2026-04-24", "SH513310", "中韩半导体ETF华泰柏瑞", 3.60, 11.0, 500),
            _quote("2026-04-25", "SH513310", "中韩半导体ETF华泰柏瑞", 3.75, 12.0, 650),
            _quote("2026-04-26", "SH513310", "中韩半导体ETF华泰柏瑞", 3.90, 14.0, 800),
            _quote("2026-04-27", "SH513310", "中韩半导体ETF华泰柏瑞", 4.05, 15.0, 900),
            _quote("2026-04-28", "SH513310", "中韩半导体ETF华泰柏瑞", 4.20, 16.0, 1200),
        ]
    )

    signals = generate_candidate_signals(quotes, "2026-04-28")

    categories = {(signal.symbol, signal.category) for signal in signals}
    assert ("SZ159100", "强势启动") in categories
    assert ("SH513310", "极端过热") in categories
    assert any("5日涨幅 12.0%" in signal.reason for signal in signals)


def test_build_and_format_report_sections():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-27", "SZ159100", "巴西ETF华夏", 1.00, 2.0, 100),
            _quote("2026-04-28", "SZ159100", "巴西ETF华夏", 1.10, 7.0, 200),
            _quote("2026-04-28", "SH513310", "中韩半导体ETF华泰柏瑞", 4.20, 16.0, 1200),
        ]
    )

    sections = build_report_sections(quotes, "2026-04-28")
    report = format_report(sections)
    candidates = format_candidates(
        generate_candidate_signals(quotes, "2026-04-28")
    )

    assert sections["今日溢价率 Top 20"].iloc[0]["symbol"] == "SH513310"
    assert "今日溢价率 Top 20" in report
    assert "观察池为空" in candidates or "极端过热" in candidates


def test_format_telegram_digest_only_shows_watch_and_danger_pools():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-24", "SZ159100", "巴西ETF华夏", 1.00, 1.0, 100),
            _quote("2026-04-25", "SZ159100", "巴西ETF华夏", 1.03, 2.0, 100),
            _quote("2026-04-26", "SZ159100", "巴西ETF华夏", 1.06, 3.0, 120),
            _quote("2026-04-27", "SZ159100", "巴西ETF华夏", 1.09, 4.0, 160),
            _quote("2026-04-28", "SZ159100", "巴西ETF华夏", 1.12, 6.0, 220),
            _quote("2026-04-24", "SH513310", "中韩半导体ETF华泰柏瑞", 3.60, 11.0, 500),
            _quote("2026-04-25", "SH513310", "中韩半导体ETF华泰柏瑞", 3.75, 12.0, 650),
            _quote("2026-04-26", "SH513310", "中韩半导体ETF华泰柏瑞", 3.90, 14.0, 800),
            _quote("2026-04-27", "SH513310", "中韩半导体ETF华泰柏瑞", 4.05, 15.0, 900),
            _quote("2026-04-28", "SH513310", "中韩半导体ETF华泰柏瑞", 4.20, 16.0, 1200),
        ]
    )
    signals = generate_candidate_signals(quotes, "2026-04-28")

    digest = format_telegram_digest(
        signals,
        trade_date="2026-04-28",
        quote_count=2,
        active_count=2,
    )

    assert "<b>cross-etf-scout 2026-04-28</b>" in digest
    assert "<b>可选池</b>" in digest
    assert "<b>危险池</b>" in digest
    assert "<code>SZ159100</code> 巴西ETF华夏" in digest
    assert "<code>SH513310</code> 中韩半导体ETF华泰柏瑞" in digest
    assert "今日溢价率 Top 20" not in digest


def test_format_telegram_digest_includes_configured_focus_etfs():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-24", "SH513310", "中韩半导体ETF华泰柏瑞", 3.60, 11.0, 500),
            _quote("2026-04-25", "SH513310", "中韩半导体ETF华泰柏瑞", 3.75, 12.0, 650),
            _quote("2026-04-26", "SH513310", "中韩半导体ETF华泰柏瑞", 3.90, 14.0, 800),
            _quote("2026-04-27", "SH513310", "中韩半导体ETF华泰柏瑞", 4.05, 15.0, 900),
            _quote("2026-04-28", "SH513310", "中韩半导体ETF华泰柏瑞", 4.20, 16.0, 1200),
        ]
    )
    signals = generate_candidate_signals(quotes, "2026-04-28")
    focus_rows = build_focus_rows(quotes, "2026-04-28", ["513310"])

    digest = format_telegram_digest(
        signals,
        trade_date="2026-04-28",
        quote_count=1,
        active_count=1,
        focus_rows=focus_rows,
    )

    assert "<b>特别关注</b>" in digest
    assert "<code>SH513310</code> 中韩半导体ETF华泰柏瑞" in digest
    assert "现价 4.20 | 今日 +0.0% | 溢价 16.0%" in digest
    assert "状态: 极端过热" in digest


def test_format_workwechat_digest_uses_plain_text_for_enterprise_wechat():
    quotes = pd.DataFrame(
        [
            _quote("2026-04-24", "SH513310", "中韩半导体ETF华泰柏瑞", 3.60, 11.0, 500),
            _quote("2026-04-25", "SH513310", "中韩半导体ETF华泰柏瑞", 3.75, 12.0, 650),
            _quote("2026-04-26", "SH513310", "中韩半导体ETF华泰柏瑞", 3.90, 14.0, 800),
            _quote("2026-04-27", "SH513310", "中韩半导体ETF华泰柏瑞", 4.05, 15.0, 900),
            _quote("2026-04-28", "SH513310", "中韩半导体ETF华泰柏瑞", 4.20, 16.0, 1200),
        ]
    )
    signals = generate_candidate_signals(quotes, "2026-04-28")
    focus_rows = build_focus_rows(quotes, "2026-04-28", ["513310"])

    digest = format_workwechat_digest(
        signals,
        trade_date="2026-04-28",
        quote_count=1,
        active_count=1,
        focus_rows=focus_rows,
    )

    assert "cross-etf-scout 2026-04-28" in digest
    assert "特别关注" in digest
    assert "危险池" in digest
    assert "SH513310 中韩半导体ETF华泰柏瑞" in digest
    assert "现价 4.20 | 今日 +0.0% | 溢价 16.0%" in digest
    assert "<b>" not in digest
    assert "<code>" not in digest


def test_format_focus_live_digest_shows_intraday_focus_quotes():
    digest = format_focus_live_digest(
        [
            {
                "symbol": "SH513310",
                "name": "中韩半导体ETF华泰柏瑞",
                "current": 4.743,
                "percent": 4.59,
                "premium_rate": 7.29,
                "iopv": 4.4207,
                "unit_nav": 4.312,
                "amount": 2135690949,
                "source_timestamp": "1784598029780",
            }
        ],
        trade_date="2026-07-21",
    )

    assert "cross-etf-scout 特别关注 2026-07-21" in digest
    assert "SH513310 中韩半导体ETF华泰柏瑞" in digest
    assert "现价 4.74 | 今日 +4.6% | 溢价 7.3%" in digest
    assert "IOPV 4.42 | 单位净值 4.31 | 成交额 21.36亿" in digest


def _quote(trade_date, symbol, name, current, premium_rate, amount):
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "name": name,
        "current": current,
        "percent": 0.0,
        "premium_rate": premium_rate,
        "amount": amount,
    }
