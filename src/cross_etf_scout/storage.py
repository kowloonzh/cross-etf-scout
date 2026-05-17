from __future__ import annotations

import csv
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path("data/cross_etf_scout.sqlite")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(
            """
            create table if not exists etfs (
                symbol text primary key,
                code text not null,
                exchange text not null,
                name text not null,
                active integer not null default 1,
                created_at text not null,
                updated_at text not null
            );

            create table if not exists daily_quotes (
                trade_date text not null,
                symbol text not null,
                name text not null,
                current real,
                percent real,
                premium_rate real,
                unit_nav real,
                iopv real,
                amount real,
                volume real,
                market_capital real,
                source_timestamp text,
                nav_date text,
                collected_at text not null,
                primary key (trade_date, symbol),
                foreign key (symbol) references etfs(symbol)
            );

            create table if not exists daily_signals (
                trade_date text not null,
                symbol text not null,
                name text not null,
                category text not null,
                score real not null,
                price_growth_3d real,
                price_growth_5d real,
                price_growth_10d real,
                price_growth_20d real,
                premium_change_3d real,
                premium_change_5d real,
                avg_premium_5d real,
                amount_ratio_5d real,
                risk_level text not null,
                reason text not null,
                created_at text not null,
                primary key (trade_date, symbol, category),
                foreign key (symbol) references etfs(symbol)
            );
            """
        )
        _ensure_column(conn, "daily_quotes", "nav_date", "text")


def import_etfs(
    csv_path: str | Path = "cross_etf.csv",
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    now = _now_iso()
    count = 0
    with connect(db_path) as conn, Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["证券代码"]
            exchange = row["交易所"]
            symbol = row["symbol"]
            name = row["证券名称"]
            conn.execute(
                """
                insert into etfs (symbol, code, exchange, name, active, created_at, updated_at)
                values (?, ?, ?, ?, 1, ?, ?)
                on conflict(symbol) do update set
                    code = excluded.code,
                    exchange = excluded.exchange,
                    name = excluded.name,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (symbol, code, exchange, name, now, now),
            )
            count += 1
    return count


def list_active_etfs(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            select symbol, code, exchange, name, active
            from etfs
            where active = 1
            order by symbol
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def upsert_daily_quote(
    db_path: str | Path,
    quote: dict[str, Any],
) -> None:
    data = {
        "trade_date": quote["trade_date"],
        "symbol": quote["symbol"],
        "name": quote["name"],
        "current": quote.get("current"),
        "percent": quote.get("percent"),
        "premium_rate": quote.get("premium_rate"),
        "unit_nav": quote.get("unit_nav"),
        "iopv": quote.get("iopv"),
        "amount": quote.get("amount"),
        "volume": quote.get("volume"),
        "market_capital": quote.get("market_capital"),
        "source_timestamp": quote.get("source_timestamp"),
        "nav_date": quote.get("nav_date"),
        "collected_at": quote.get("collected_at") or _now_iso(),
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            insert into daily_quotes (
                trade_date, symbol, name, current, percent, premium_rate, unit_nav,
                iopv, amount, volume, market_capital, source_timestamp, nav_date,
                collected_at
            )
            values (
                :trade_date, :symbol, :name, :current, :percent, :premium_rate,
                :unit_nav, :iopv, :amount, :volume, :market_capital,
                :source_timestamp, :nav_date, :collected_at
            )
            on conflict(trade_date, symbol) do update set
                name = excluded.name,
                current = excluded.current,
                percent = excluded.percent,
                premium_rate = excluded.premium_rate,
                unit_nav = excluded.unit_nav,
                iopv = excluded.iopv,
                amount = excluded.amount,
                volume = excluded.volume,
                market_capital = excluded.market_capital,
                source_timestamp = excluded.source_timestamp,
                nav_date = excluded.nav_date,
                collected_at = excluded.collected_at
            """,
            data,
        )


def load_quotes(
    db_path: str | Path = DEFAULT_DB_PATH,
    trade_date: str | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    sql = "select * from daily_quotes"
    conditions: list[str] = []
    params: list[Any] = []
    if trade_date is not None:
        conditions.append("trade_date = ?")
        params.append(trade_date)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    if conditions:
        sql += " where " + " and ".join(conditions)
    sql += " order by trade_date, symbol"
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def replace_daily_signals(
    db_path: str | Path,
    trade_date: str,
    signals: Iterable[Any],
) -> None:
    now = _now_iso()
    with connect(db_path) as conn:
        conn.execute("delete from daily_signals where trade_date = ?", (trade_date,))
        for signal in signals:
            data = _signal_to_dict(signal)
            data["trade_date"] = trade_date
            data["created_at"] = now
            conn.execute(
                """
                insert into daily_signals (
                    trade_date, symbol, name, category, score, price_growth_3d,
                    price_growth_5d, price_growth_10d, price_growth_20d,
                    premium_change_3d, premium_change_5d, avg_premium_5d,
                    amount_ratio_5d, risk_level, reason, created_at
                )
                values (
                    :trade_date, :symbol, :name, :category, :score,
                    :price_growth_3d, :price_growth_5d, :price_growth_10d,
                    :price_growth_20d, :premium_change_3d, :premium_change_5d,
                    :avg_premium_5d, :amount_ratio_5d, :risk_level, :reason,
                    :created_at
                )
                """,
                data,
            )


def load_signals(
    db_path: str | Path = DEFAULT_DB_PATH,
    trade_date: str | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    sql = "select * from daily_signals"
    conditions: list[str] = []
    params: list[Any] = []
    if trade_date is not None:
        conditions.append("trade_date = ?")
        params.append(trade_date)
    if symbol is not None:
        conditions.append("symbol = ?")
        params.append(symbol)
    if conditions:
        sql += " where " + " and ".join(conditions)
    sql += " order by trade_date, score desc, symbol"
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _ensure_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"pragma table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"alter table {table_name} add column {column_name} {column_type}")


def _signal_to_dict(signal: Any) -> dict[str, Any]:
    if is_dataclass(signal):
        return asdict(signal)
    return dict(signal)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
