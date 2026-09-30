from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any


QUOTE_URL = "https://qt.gtimg.cn/q="
_QUOTE_ROW = re.compile(r'v_(?P<symbol>[a-z0-9.]+)="(?P<fields>[^"]*)";', re.I)


def fetch_stock(
    symbol: str,
    chrome_remote_url: str | None = None,
    timeout_seconds: int = 30,
    retries: int = 2,
    retry_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    del chrome_remote_url
    quotes = fetch_stocks(
        [symbol],
        timeout_seconds=timeout_seconds,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    return quotes[0]


def fetch_stocks(
    symbols: list[str],
    chrome_remote_url: str | None = None,
    timeout_seconds: int = 30,
    retries: int = 2,
    retry_delay_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    del chrome_remote_url
    if not symbols:
        return []
    normalized = ",".join(symbol.strip().lower() for symbol in symbols)
    request = urllib.request.Request(
        QUOTE_URL + normalized,
        headers={"Referer": "https://gu.qq.com/", "User-Agent": "Mozilla/5.0"},
    )
    attempts = max(0, retries) + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise ValueError(f"Tencent quote status: {response.status}")
                return parse_quotes(response.read().decode("gbk"))
        except (OSError, UnicodeError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < attempts - 1 and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
    raise ValueError(f"Tencent quote request failed: {last_error}") from last_error


def parse_quotes(text: str) -> list[dict[str, Any]]:
    quotes: list[dict[str, Any]] = []
    for match in _QUOTE_ROW.finditer(text):
        symbol = match.group("symbol").upper()
        fields = match.group("fields").split("~")
        current = _required_float(fields, 3, symbol, "current")
        iopv = _required_float(fields, 81, symbol, "IOPV")
        timestamp = _field(fields, 30)
        quotes.append(
            {
                "symbol": symbol,
                "name": _field(fields, 1),
                "current": current,
                "percent": _float(fields, 32),
                "premium_rate": (current / iopv - 1) * 100,
                "unit_nav": _float(fields, 78),
                "iopv": iopv,
                # Tencent field 57 is turnover in ten-thousand yuan.
                "amount": (_float(fields, 57) or 0.0) * 10000,
                "volume": (_float(fields, 36) or 0.0) * 100,
                "market_capital": _float(fields, 72),
                "source_timestamp": timestamp or None,
                "trade_date": _trade_date(timestamp),
                "nav_date": None,
            }
        )
    if not quotes:
        raise ValueError("Tencent response does not contain valid ETF quotes")
    return quotes


def _field(fields: list[str], index: int) -> str:
    return fields[index] if index < len(fields) else ""


def _float(fields: list[str], index: int) -> float | None:
    value = _field(fields, index)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _required_float(
    fields: list[str], index: int, symbol: str, label: str
) -> float:
    value = _float(fields, index)
    if value is None or value <= 0:
        raise ValueError(f"{symbol} has invalid {label}")
    return value


def _trade_date(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None
