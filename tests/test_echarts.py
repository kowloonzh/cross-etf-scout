from __future__ import annotations

import sqlite3

import pytest

from cross_etf_scout.echarts import generate_premium_echarts
from cross_etf_scout.storage import init_db


def test_generate_premium_echarts_uses_latest_database_month(tmp_path):
    db_path = tmp_path / "scout.sqlite"
    output_dir = tmp_path / "charts"
    init_db(db_path)
    _insert_quotes(
        db_path,
        [
            ("2026-08-08", 20.0),
            ("2026-08-10", 16.29),
            ("2026-08-11", 15.71),
            ("2026-09-09", 9.12),
        ],
    )

    output_path = generate_premium_echarts(db_path, "SH513310", output_dir)

    assert output_path == (
        output_dir / "zhonghan_semiconductor_premium_20260809_20260909.js"
    )
    content = output_path.read_text(encoding="utf-8")
    assert "option = {" in content
    assert "'2026-08-10',\n      '2026-08-11',\n      '2026-09-09'" in content
    assert "16.29,\n        15.71,\n        9.12" in content
    assert "2026-08-08" not in content
    assert "20.0" not in content
    assert "type: 'line'" in content
    assert "smooth: true" in content


def test_generate_premium_echarts_rejects_null_premium_in_range(tmp_path):
    db_path = tmp_path / "scout.sqlite"
    init_db(db_path)
    _insert_quotes(
        db_path,
        [
            ("2026-08-10", 16.29),
            ("2026-09-08", None),
            ("2026-09-09", 9.12),
        ],
    )

    with pytest.raises(ValueError, match="空溢价率"):
        generate_premium_echarts(db_path, "SH513310", tmp_path)


def _insert_quotes(db_path, dated_values):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            insert into etfs (
                symbol, code, exchange, name, active, created_at, updated_at
            ) values (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                "SH513310",
                "513310",
                "SH",
                "中韩半导体ETF华泰柏瑞",
                "2026-09-09T00:00:00+00:00",
                "2026-09-09T00:00:00+00:00",
            ),
        )
        conn.executemany(
            """
            insert into daily_quotes (
                trade_date, symbol, name, premium_rate, collected_at
            ) values (?, 'SH513310', '中韩半导体ETF华泰柏瑞', ?, ?)
            """,
            [
                (trade_date, premium_rate, "2026-09-09T00:00:00+00:00")
                for trade_date, premium_rate in dated_values
            ],
        )
