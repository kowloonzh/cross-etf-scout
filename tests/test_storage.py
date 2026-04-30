from __future__ import annotations

import csv
import sqlite3

from cross_etf_scout.analysis import Signal
from cross_etf_scout.storage import (
    import_etfs,
    init_db,
    list_active_etfs,
    load_quotes,
    load_signals,
    replace_daily_signals,
    upsert_daily_quote,
)


def test_init_db_creates_expected_tables(tmp_path):
    db_path = tmp_path / "scout.sqlite"

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        }

    assert {"etfs", "daily_quotes", "daily_signals"} <= table_names


def test_import_etfs_upserts_universe_rows(tmp_path):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path, [["159100", "SZ", "SZ159100", "巴西ETF华夏"]])
    init_db(db_path)

    imported = import_etfs(csv_path, db_path)
    imported_again = import_etfs(csv_path, db_path)

    rows = list_active_etfs(db_path)
    assert imported == 1
    assert imported_again == 1
    assert rows == [
        {
            "symbol": "SZ159100",
            "code": "159100",
            "exchange": "SZ",
            "name": "巴西ETF华夏",
            "active": 1,
        }
    ]


def test_upsert_daily_quote_replaces_same_symbol_and_date(tmp_path):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path, [["159100", "SZ", "SZ159100", "巴西ETF华夏"]])
    init_db(db_path)
    import_etfs(csv_path, db_path)

    quote = {
        "trade_date": "2026-04-28",
        "symbol": "SZ159100",
        "name": "巴西ETF华夏",
        "current": 1.2,
        "percent": 3.4,
        "premium_rate": 5.6,
        "unit_nav": 1.1,
        "iopv": 1.09,
        "amount": 100000000.0,
        "volume": 5000000.0,
        "market_capital": 2000000000.0,
        "source_timestamp": "2026-04-28T15:00:00+08:00",
    }
    upsert_daily_quote(db_path, quote)
    upsert_daily_quote(db_path, {**quote, "current": 1.25, "premium_rate": 6.0})

    rows = load_quotes(db_path, trade_date="2026-04-28")
    assert len(rows) == 1
    assert rows[0]["current"] == 1.25
    assert rows[0]["premium_rate"] == 6.0


def test_replace_daily_signals_replaces_existing_date(tmp_path):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path, [["159100", "SZ", "SZ159100", "巴西ETF华夏"]])
    init_db(db_path)
    import_etfs(csv_path, db_path)

    replace_daily_signals(
        db_path,
        "2026-04-28",
        [
            Signal(
                symbol="SZ159100",
                name="巴西ETF华夏",
                category="强势启动",
                score=12.5,
                risk_level="中",
                reason="5日涨幅 8.0%，溢价率上升",
            )
        ],
    )
    replace_daily_signals(
        db_path,
        "2026-04-28",
        [
            Signal(
                symbol="SZ159100",
                name="巴西ETF华夏",
                category="趋势确认",
                score=9.0,
                risk_level="中",
                reason="10日趋势保持",
            )
        ],
    )

    rows = load_signals(db_path, trade_date="2026-04-28")
    assert len(rows) == 1
    assert rows[0]["category"] == "趋势确认"
    assert rows[0]["reason"] == "10日趋势保持"


def _write_etf_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerows(rows)
