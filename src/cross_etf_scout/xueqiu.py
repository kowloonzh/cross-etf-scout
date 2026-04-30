from __future__ import annotations

import json
import subprocess
import time
from typing import Any


DEFAULT_CHROME_REMOTE_URL = "http://127.0.0.1:9222"


def fetch_stock(
    symbol: str,
    chrome_remote_url: str = DEFAULT_CHROME_REMOTE_URL,
    timeout_seconds: int = 30,
    retries: int = 2,
    retry_delay_seconds: float = 1.0,
) -> dict[str, Any]:
    cmd = [
        "xueqiu-cli",
        f"--chrome-remote-url={chrome_remote_url}",
        "stock",
        symbol,
    ]
    result = _run_with_retries(cmd, timeout_seconds, retries, retry_delay_seconds)
    payload = json.loads(result.stdout)
    return normalize_stock_payload(payload)


def fetch_stocks(
    symbols: list[str],
    chrome_remote_url: str = DEFAULT_CHROME_REMOTE_URL,
    timeout_seconds: int = 30,
    retries: int = 2,
    retry_delay_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    if not symbols:
        return []
    cmd = [
        "xueqiu-cli",
        f"--chrome-remote-url={chrome_remote_url}",
        "stocks",
        ",".join(symbols),
    ]
    result = _run_with_retries(cmd, timeout_seconds, retries, retry_delay_seconds)
    payload = json.loads(result.stdout)
    if isinstance(payload, list):
        return [normalize_stock_payload(item) for item in payload]
    return [normalize_stock_payload(payload)]


def _run_with_retries(
    cmd: list[str],
    timeout_seconds: int,
    retries: int,
    retry_delay_seconds: float,
) -> subprocess.CompletedProcess:
    attempts = max(0, retries) + 1
    last_error: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    for attempt in range(attempts):
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt < attempts - 1 and retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
    if last_error is not None:
        raise last_error
    raise RuntimeError("xueqiu-cli did not run")


def normalize_stock_payload(payload: dict[str, Any]) -> dict[str, Any]:
    quote = _extract_quote(payload)
    return {
        "symbol": str(quote["symbol"]),
        "name": str(quote.get("name") or ""),
        "current": _to_float(quote.get("current")),
        "percent": _to_float(quote.get("percent")),
        "premium_rate": _to_float(quote.get("premium_rate")),
        "unit_nav": _to_float(quote.get("unit_nav")),
        "iopv": _to_float(quote.get("iopv")),
        "amount": _to_float(quote.get("amount")),
        "volume": _to_float(quote.get("volume")),
        "market_capital": _to_float(quote.get("market_capital")),
        "source_timestamp": _to_timestamp(quote),
    }


def _extract_quote(payload: dict[str, Any]) -> dict[str, Any]:
    if "symbol" in payload:
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("quote"), dict):
        return data["quote"]
    if isinstance(data, dict) and "symbol" in data:
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    raise ValueError("xueqiu payload does not contain stock quote fields")


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_timestamp(quote: dict[str, Any]) -> str | None:
    value = quote.get("timestamp") or quote.get("time") or quote.get("updated_at")
    if value is None:
        return None
    return str(value)
