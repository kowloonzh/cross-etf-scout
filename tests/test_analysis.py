import pandas as pd

from cross_etf_scout.analysis import (
    compute_etf_metrics,
    rank_anomalies,
    classify_signal,
)


def test_compute_etf_metrics_uses_latest_premium_and_price_growth():
    prices = pd.DataFrame(
        [
            {"date": "2026-04-01", "close": 1.00},
            {"date": "2026-04-02", "close": 1.05},
            {"date": "2026-04-03", "close": 1.20},
        ]
    )
    navs = pd.DataFrame(
        [
            {"date": "2026-04-01", "nav": 1.00},
            {"date": "2026-04-02", "nav": 1.02},
            {"date": "2026-04-03", "nav": 1.10},
        ]
    )

    metrics = compute_etf_metrics("159100", "巴西ETF华夏", prices, navs, lookback=3)

    assert metrics["price_growth_pct"] == 20.0
    assert metrics["premium_pct"] == 9.09
    assert metrics["premium_change_pct"] == 9.09
    assert metrics["score"] == 27.27
    assert metrics["signal"] == "异动"


def test_rank_anomalies_sorts_by_score_descending_and_keeps_positive_signals():
    rows = [
        {"symbol": "SZ159001", "score": 2.0, "signal": "观察"},
        {"symbol": "SZ159002", "score": 15.0, "signal": "异动"},
        {"symbol": "SZ159003", "score": -1.0, "signal": "正常"},
        {"symbol": "SZ159004", "score": 8.0, "signal": "关注"},
    ]

    ranked = rank_anomalies(rows, top=3)

    assert [row["symbol"] for row in ranked] == ["SZ159002", "SZ159004", "SZ159001"]


def test_classify_signal_thresholds():
    assert classify_signal(score=16, premium_pct=8, price_growth_pct=8) == "强异动"
    assert classify_signal(score=9, premium_pct=5, price_growth_pct=5) == "异动"
    assert classify_signal(score=5, premium_pct=3, price_growth_pct=4) == "关注"
    assert classify_signal(score=1, premium_pct=0.5, price_growth_pct=1) == "正常"
