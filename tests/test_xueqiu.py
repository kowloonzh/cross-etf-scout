from __future__ import annotations

import json
import subprocess

from cross_etf_scout.xueqiu import fetch_stock, fetch_stocks, normalize_stock_payload


def test_normalize_stock_payload_accepts_top_level_quote_fields():
    payload = {
        "symbol": "SH513310",
        "name": "中韩半导体ETF华泰柏瑞",
        "current": 4.227,
        "percent": 0.02,
        "premium_rate": 10.18,
        "unit_nav": 3.836,
        "iopv": 3.8365,
        "amount": 13272809139,
        "volume": 3063845711,
        "market_capital": 4200000000,
        "timestamp": 1777378800000,
        "nav_date": 1777296000000,
    }

    quote = normalize_stock_payload(payload)

    assert quote == {
        "symbol": "SH513310",
        "name": "中韩半导体ETF华泰柏瑞",
        "current": 4.227,
        "percent": 0.02,
        "premium_rate": 10.18,
        "unit_nav": 3.836,
        "iopv": 3.8365,
        "amount": 13272809139.0,
        "volume": 3063845711.0,
        "market_capital": 4200000000.0,
        "source_timestamp": "1777378800000",
        "trade_date": "2026-04-28",
        "nav_date": "2026-04-27",
    }


def test_fetch_stock_calls_xueqiu_cli_and_normalizes_json(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "data": {
                        "symbol": "SH513310",
                        "name": "中韩半导体ETF华泰柏瑞",
                        "current": 4.227,
                        "premium_rate": 10.18,
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    quote = fetch_stock("SH513310", chrome_remote_url="http://127.0.0.1:9222")

    assert calls == [
        [
            "xueqiu-cli",
            "--chrome-remote-url=http://127.0.0.1:9222",
            "stock",
            "SH513310",
        ]
    ]
    assert quote["symbol"] == "SH513310"
    assert quote["premium_rate"] == 10.18


def test_normalize_stock_payload_accepts_nested_quote_output():
    payload = {
        "data": {
            "quote": {
                "symbol": "SZ159185",
                "name": "港股通信息技术ETF鹏华",
                "current": 1.014,
                "premium_rate": -0.49,
                "timestamp": 1777359894000,
                "nav_date": 1777296000000,
            }
        },
        "error_code": 0,
        "error_description": "",
    }

    quote = normalize_stock_payload(payload)

    assert quote["symbol"] == "SZ159185"
    assert quote["name"] == "港股通信息技术ETF鹏华"
    assert quote["current"] == 1.014
    assert quote["premium_rate"] == -0.49
    assert quote["trade_date"] == "2026-04-28"
    assert quote["nav_date"] == "2026-04-27"


def test_fetch_stocks_calls_batch_command_and_normalizes_list(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, check, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                [
                    {
                        "data": {
                            "quote": {
                                "symbol": "SZ159185",
                                "name": "港股通信息技术ETF鹏华",
                                "current": 1.014,
                            }
                        }
                    },
                    {
                        "data": {
                            "quote": {
                                "symbol": "SZ159186",
                                "name": "港股通汽车ETF鹏华",
                                "current": 0.923,
                            }
                        }
                    },
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    quotes = fetch_stocks(
        ["SZ159185", "SZ159186"],
        chrome_remote_url="http://127.0.0.1:9222",
        timeout_seconds=20,
    )

    assert calls == [
        [
            "xueqiu-cli",
            "--chrome-remote-url=http://127.0.0.1:9222",
            "stocks",
            "SZ159185,SZ159186",
        ]
    ]
    assert [quote["symbol"] for quote in quotes] == ["SZ159185", "SZ159186"]


def test_fetch_stocks_retries_transient_timeout(monkeypatch):
    attempts = []

    def fake_run(cmd, capture_output, text, check, timeout):
        attempts.append(cmd)
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                [
                    {
                        "data": {
                            "quote": {
                                "symbol": "SZ159185",
                                "name": "港股通信息技术ETF鹏华",
                                "current": 1.014,
                            }
                        }
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    quotes = fetch_stocks(
        ["SZ159185"],
        chrome_remote_url="http://127.0.0.1:9222",
        timeout_seconds=20,
        retries=1,
        retry_delay_seconds=0,
    )

    assert len(attempts) == 2
    assert quotes[0]["symbol"] == "SZ159185"


def test_fetch_stocks_raises_after_retries_are_exhausted(monkeypatch):
    attempts = []

    def fake_run(cmd, capture_output, text, check, timeout):
        attempts.append(cmd)
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        fetch_stocks(
            ["SZ159185"],
            chrome_remote_url="http://127.0.0.1:9222",
            timeout_seconds=20,
            retries=2,
            retry_delay_seconds=0,
        )
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("expected TimeoutExpired")

    assert len(attempts) == 3
