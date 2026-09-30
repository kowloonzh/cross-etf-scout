from __future__ import annotations

import math

import pytest

from cross_etf_scout.tencent import fetch_stocks, parse_quotes


def _quote_row(symbol: str, fields: list[str]) -> str:
    return f'v_{symbol}="{"~".join(fields)}";'


def test_parse_quotes_calculates_premium_from_current_and_iopv():
    fields = [""] * 88
    fields[1] = "标普500ETF博时"
    fields[2] = "513500"
    fields[3] = "2.688"
    fields[4] = "2.690"
    fields[30] = "20260930153805"
    fields[32] = "-0.07"
    fields[36] = "994951"
    fields[57] = "26824.9988"
    fields[72] = "10319638600"
    fields[78] = "2.4470"
    fields[81] = "2.4506"

    quotes = parse_quotes(_quote_row("sh513500", fields))

    assert len(quotes) == 1
    quote = quotes[0]
    assert quote["symbol"] == "SH513500"
    assert quote["name"] == "标普500ETF博时"
    assert quote["current"] == 2.688
    assert quote["iopv"] == 2.4506
    assert quote["unit_nav"] == 2.447
    assert quote["amount"] == 268249988.0
    assert quote["volume"] == 99495100.0
    assert quote["market_capital"] == 10319638600.0
    assert quote["trade_date"] == "2026-09-30"
    assert math.isclose(
        quote["premium_rate"],
        (2.688 / 2.4506 - 1) * 100,
    )


def test_parse_quotes_rejects_etf_without_iopv():
    fields = [""] * 88
    fields[1] = "测试ETF"
    fields[2] = "513500"
    fields[3] = "2.688"

    with pytest.raises(ValueError, match="IOPV"):
        parse_quotes(_quote_row("sh513500", fields))


def test_fetch_stocks_requests_batch_and_decodes_gbk(monkeypatch):
    fields = [""] * 88
    fields[1] = "标普500ETF博时"
    fields[2] = "513500"
    fields[3] = "2.688"
    fields[30] = "20260930153805"
    fields[81] = "2.4506"
    body = _quote_row("sh513500", fields).encode("gbk")
    calls = []

    class FakeResponse:
        status = 200

        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout, request.headers))
        return FakeResponse()

    monkeypatch.setattr("cross_etf_scout.tencent.urllib.request.urlopen", fake_urlopen)

    quotes = fetch_stocks(["SH513500"], timeout_seconds=12, retries=0)

    assert len(quotes) == 1
    assert calls[0][0].endswith("q=sh513500")
    assert calls[0][1] == 12
    assert quotes[0]["name"] == "标普500ETF博时"
