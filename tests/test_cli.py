from __future__ import annotations

import csv
import subprocess

from cross_etf_scout.cli import main
from cross_etf_scout.storage import import_etfs, init_db, load_quotes, upsert_daily_quote


def test_cli_init_db_and_import_etfs(tmp_path, capsys):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path)

    assert main(["--db", str(db_path), "init-db"]) == 0
    assert main(["--db", str(db_path), "import-etfs", "--csv", str(csv_path)]) == 0

    output = capsys.readouterr().out
    assert "Initialized database" in output
    assert "Imported 1 ETFs" in output


def test_cli_report_handles_empty_history(tmp_path, capsys):
    db_path = tmp_path / "scout.sqlite"
    init_db(db_path)

    assert main(["--db", str(db_path), "report", "--date", "2026-04-28"]) == 0

    assert "没有可用行情数据" in capsys.readouterr().out


def test_cli_reports_missing_database_before_running_command(tmp_path, capsys):
    db_path = tmp_path / "missing" / "scout.sqlite"

    assert main(["--db", str(db_path), "report", "--date", "2026-04-28"]) == 1

    assert "Database not found" in capsys.readouterr().out


def test_cli_candidates_generates_and_stores_signals(tmp_path, capsys):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path)
    init_db(db_path)
    import_etfs(csv_path, db_path)
    for quote in [
        _quote("2026-04-24", 1.00, 1.0, 100),
        _quote("2026-04-25", 1.03, 2.0, 100),
        _quote("2026-04-26", 1.06, 3.0, 120),
        _quote("2026-04-27", 1.09, 4.0, 160),
        _quote("2026-04-28", 1.12, 6.0, 220),
    ]:
        upsert_daily_quote(db_path, quote)

    assert main(["--db", str(db_path), "candidates", "--date", "2026-04-28"]) == 0

    assert "强势启动" in capsys.readouterr().out


def test_cli_collect_uses_batch_fetch(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])
        writer.writerow(["513310", "SH", "SH513310", "中韩半导体ETF华泰柏瑞"])
    init_db(db_path)
    import_etfs(csv_path, db_path)
    calls = []

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        calls.append(
            (symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds)
        )
        return [
            {
                "symbol": symbol,
                "name": symbol,
                "current": 1.0,
                "percent": 0.0,
                "premium_rate": 1.0,
                "unit_nav": 1.0,
                "iopv": 1.0,
                "amount": 100.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "2026-04-28T15:00:00+08:00",
            }
            for symbol in symbols
        ]

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--batch-size",
                "2",
                "--request-timeout",
                "20",
                "--retries",
                "3",
                "--retry-delay",
                "0",
            ]
        )
        == 0
    )

    assert calls == [(["SH513310", "SZ159100"], "http://127.0.0.1:9222", 20, 3, 0.0)]
    assert "Collected 2 quotes, 0 failures." in capsys.readouterr().out


def test_cli_collect_uses_source_trade_date_from_quote(tmp_path, monkeypatch):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["513310", "SH", "SH513310", "中韩半导体ETF华泰柏瑞"])
    init_db(db_path)
    import_etfs(csv_path, db_path)

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        return [
            {
                "symbol": symbols[0],
                "name": symbols[0],
                "trade_date": "2026-05-15",
                "nav_date": "2026-05-14",
                "current": 6.005,
                "percent": -3.72,
                "premium_rate": 35.94,
                "unit_nav": 4.436,
                "iopv": 4.4173,
                "amount": 100.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "1778828400000",
            }
        ]

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-05-17",
                "--batch-size",
                "1",
            ]
        )
        == 0
    )

    assert load_quotes(db_path, trade_date="2026-05-17") == []
    rows = load_quotes(db_path, trade_date="2026-05-15")
    assert len(rows) == 1
    assert rows[0]["nav_date"] == "2026-05-14"


def test_cli_collect_skips_symbols_already_collected_for_date(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])
        writer.writerow(["513310", "SH", "SH513310", "中韩半导体ETF华泰柏瑞"])
    init_db(db_path)
    import_etfs(csv_path, db_path)
    upsert_daily_quote(db_path, _quote("2026-04-28", 1.0, 1.0, 100.0))
    calls = []

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        calls.append(symbols)
        return [
            {
                "symbol": symbol,
                "name": symbol,
                "current": 1.0,
                "percent": 0.0,
                "premium_rate": 1.0,
                "unit_nav": 1.0,
                "iopv": 1.0,
                "amount": 100.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "2026-04-28T15:00:00+08:00",
            }
            for symbol in symbols
        ]

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--batch-size",
                "10",
            ]
        )
        == 0
    )

    assert calls == [["SH513310"]]
    assert "Skipped 1 already collected quotes." in capsys.readouterr().out


def test_cli_collect_force_refetches_symbols_already_collected_for_date(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])
    init_db(db_path)
    import_etfs(csv_path, db_path)
    upsert_daily_quote(db_path, _quote("2026-04-28", 1.0, 1.0, 100.0))
    calls = []

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        calls.append(symbols)
        return [
            {
                "symbol": symbol,
                "name": symbol,
                "current": 2.0,
                "percent": 0.0,
                "premium_rate": 2.0,
                "unit_nav": 1.0,
                "iopv": 1.0,
                "amount": 200.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "2026-04-28T15:00:00+08:00",
            }
            for symbol in symbols
        ]

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--force",
            ]
        )
        == 0
    )

    assert calls == [["SZ159100"]]
    assert "Skipped 0 already collected quotes." in capsys.readouterr().out


def test_cli_collect_falls_back_to_single_symbol_after_batch_timeout(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])
        writer.writerow(["513310", "SH", "SH513310", "中韩半导体ETF华泰柏瑞"])
    init_db(db_path)
    import_etfs(csv_path, db_path)
    batch_calls = []
    single_calls = []

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        batch_calls.append(symbols)
        if len(symbols) > 1:
            raise subprocess.TimeoutExpired("xueqiu-cli", timeout_seconds)
        raise AssertionError("fallback should use fetch_stock for single symbols")

    def fake_fetch_stock(
        symbol, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        single_calls.append(symbol)
        return {
            "symbol": symbol,
            "name": symbol,
            "current": 1.0,
            "percent": 0.0,
            "premium_rate": 1.0,
            "unit_nav": 1.0,
            "iopv": 1.0,
            "amount": 100.0,
            "volume": 100.0,
            "market_capital": 1000.0,
            "source_timestamp": "2026-04-28T15:00:00+08:00",
        }

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)
    monkeypatch.setattr("cross_etf_scout.cli.fetch_stock", fake_fetch_stock)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--batch-size",
                "2",
                "--request-timeout",
                "1",
                "--no-restart-on-timeout",
            ]
        )
        == 0
    )

    assert batch_calls == [["SH513310", "SZ159100"]]
    assert single_calls == ["SH513310", "SZ159100"]
    assert "Collected 2 quotes, 0 failures." in capsys.readouterr().out


def test_cli_collect_restarts_container_after_timeout_before_retrying_batch(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])
    init_db(db_path)
    import_etfs(csv_path, db_path)
    fetch_attempts = []
    restart_calls = []

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        fetch_attempts.append(symbols)
        if len(fetch_attempts) == 1:
            raise subprocess.TimeoutExpired("xueqiu-cli", timeout_seconds)
        return [
            {
                "symbol": symbols[0],
                "name": symbols[0],
                "current": 1.0,
                "percent": 0.0,
                "premium_rate": 1.0,
                "unit_nav": 1.0,
                "iopv": 1.0,
                "amount": 100.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "2026-04-28T15:00:00+08:00",
            }
        ]

    def fake_run(cmd, check):
        restart_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--batch-size",
                "1",
                "--request-timeout",
                "1",
                "--retries",
                "0",
                "--retry-delay",
                "0",
            ]
        )
        == 0
    )

    assert fetch_attempts == [["SZ159100"], ["SZ159100"]]
    assert restart_calls == [["docker", "restart", "headless-shell"]]
    assert "Restarted container after timeout: headless-shell" in capsys.readouterr().out


def test_cli_collect_starts_persistent_headless_container_when_browser_is_unavailable(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "scout.sqlite"
    csv_path = tmp_path / "cross_etf.csv"
    _write_etf_csv(csv_path)
    init_db(db_path)
    import_etfs(csv_path, db_path)
    ready_checks = [False, False, True]
    docker_calls = []

    def fake_is_chrome_remote_ready(chrome_remote_url):
        assert chrome_remote_url == "http://127.0.0.1:9222"
        return ready_checks.pop(0)

    def fake_run(cmd, capture_output=False, text=False, check=False):
        docker_calls.append(cmd)
        if cmd[:3] == ["docker", "ps", "-a"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        return subprocess.CompletedProcess(cmd, 0, stdout="container-id\n")

    def fake_fetch_stocks(
        symbols, chrome_remote_url, timeout_seconds, retries, retry_delay_seconds
    ):
        return [
            {
                "symbol": symbols[0],
                "name": symbols[0],
                "current": 1.0,
                "percent": 0.0,
                "premium_rate": 1.0,
                "unit_nav": 1.0,
                "iopv": 1.0,
                "amount": 100.0,
                "volume": 100.0,
                "market_capital": 1000.0,
                "source_timestamp": "2026-04-28T15:00:00+08:00",
            }
        ]

    monkeypatch.setattr(
        "cross_etf_scout.cli._is_chrome_remote_ready", fake_is_chrome_remote_ready
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("cross_etf_scout.cli.fetch_stocks", fake_fetch_stocks)

    assert (
        main(
            [
                "--db",
                str(db_path),
                "collect",
                "--date",
                "2026-04-28",
                "--batch-size",
                "1",
                "--ensure-browser",
            ]
        )
        == 0
    )

    assert docker_calls == [
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^/headless-shell$",
            "--format",
            "{{.Names}}",
        ],
        [
            "docker",
            "run",
            "-d",
            "-p",
            "9222:9222",
            "--restart",
            "unless-stopped",
            "--name",
            "headless-shell",
            "chromedp/headless-shell",
        ],
    ]
    assert "Started container for browser dependency: headless-shell" in capsys.readouterr().out


def _write_etf_csv(path):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["证券代码", "交易所", "symbol", "证券名称"])
        writer.writerow(["159100", "SZ", "SZ159100", "巴西ETF华夏"])


def _quote(trade_date, current, premium_rate, amount):
    return {
        "trade_date": trade_date,
        "symbol": "SZ159100",
        "name": "巴西ETF华夏",
        "current": current,
        "percent": 0.0,
        "premium_rate": premium_rate,
        "unit_nav": None,
        "iopv": None,
        "amount": amount,
        "volume": None,
        "market_capital": None,
        "source_timestamp": None,
    }
