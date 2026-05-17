from __future__ import annotations

import argparse
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

from cross_etf_scout.analysis import generate_candidate_signals
from cross_etf_scout.reporting import (
    build_focus_rows,
    build_report_sections,
    format_candidates,
    format_report,
    format_telegram_digest,
    load_focus_etf_codes,
)
from cross_etf_scout.storage import (
    DEFAULT_DB_PATH,
    import_etfs,
    init_db,
    list_active_etfs,
    load_quotes,
    load_signals,
    replace_daily_signals,
    upsert_daily_quote,
)
from cross_etf_scout.xueqiu import DEFAULT_CHROME_REMOTE_URL, fetch_stock, fetch_stocks


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    if args.command != "init-db" and not db_path.exists():
        print(f"Database not found: {db_path}. Run ces init-db first.")
        return 1

    if args.command == "init-db":
        init_db(db_path)
        print(f"Initialized database: {db_path}")
        return 0

    if args.command == "import-etfs":
        count = import_etfs(args.csv, db_path)
        print(f"Imported {count} ETFs from {args.csv}")
        return 0

    if args.command == "collect":
        return _collect(args, db_path)

    if args.command == "report":
        quotes = pd.DataFrame(load_quotes(db_path))
        sections = build_report_sections(quotes, args.date)
        print(format_report(sections))
        return 0

    if args.command == "candidates":
        quotes = pd.DataFrame(load_quotes(db_path))
        signals = generate_candidate_signals(quotes, args.date)
        replace_daily_signals(db_path, args.date, signals)
        print(format_candidates(signals))
        return 0

    if args.command == "telegram-digest":
        quotes = pd.DataFrame(load_quotes(db_path))
        signals = generate_candidate_signals(quotes, args.date)
        replace_daily_signals(db_path, args.date, signals)
        quote_count = len(load_quotes(db_path, trade_date=args.date))
        active_count = len(list_active_etfs(db_path))
        focus_codes = load_focus_etf_codes(args.config)
        focus_rows = build_focus_rows(quotes, args.date, focus_codes)
        print(
            format_telegram_digest(
                signals,
                args.date,
                quote_count,
                active_count,
                focus_rows=focus_rows,
            )
        )
        return 0

    if args.command == "show":
        _show(args, db_path)
        return 0

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ces")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init-db")

    import_parser = subparsers.add_parser("import-etfs")
    import_parser.add_argument("--csv", default="cross_etf.csv")

    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--date", default=date.today().isoformat())
    collect_parser.add_argument("--chrome-remote-url", default=DEFAULT_CHROME_REMOTE_URL)
    collect_parser.add_argument("--batch-size", type=int, default=10)
    collect_parser.add_argument("--request-timeout", type=int, default=30)
    collect_parser.add_argument("--retries", type=int, default=2)
    collect_parser.add_argument("--retry-delay", type=float, default=1.0)
    collect_parser.add_argument("--restart-container-on-timeout", default="headless-shell")
    collect_parser.add_argument("--no-restart-on-timeout", action="store_true")
    collect_parser.add_argument("--ensure-browser", action="store_true")
    collect_parser.add_argument("--headless-image", default="chromedp/headless-shell")
    collect_parser.add_argument("--headless-host-port", default="9222")
    collect_parser.add_argument("--force", action="store_true")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--date", default=date.today().isoformat())

    candidates_parser = subparsers.add_parser("candidates")
    candidates_parser.add_argument("--date", default=date.today().isoformat())

    telegram_digest_parser = subparsers.add_parser("telegram-digest")
    telegram_digest_parser.add_argument("--date", default=date.today().isoformat())
    telegram_digest_parser.add_argument("--config", default="config/config.yaml")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("symbol")
    show_parser.add_argument("--date", default=None)

    return parser


def _collect(args: argparse.Namespace, db_path: Path) -> int:
    etfs = list_active_etfs(db_path)
    if not etfs:
        print("ETF universe is empty. Run ces import-etfs first.")
        return 1

    if args.ensure_browser and not _ensure_browser(args):
        print("Browser dependency is unavailable; continuing collection attempt.")

    successes = 0
    failures: list[tuple[str, str]] = []
    names_by_symbol = {etf["symbol"]: etf["name"] for etf in etfs}
    collected_symbols = set()
    if not args.force:
        collected_symbols = {
            quote["symbol"] for quote in load_quotes(db_path, trade_date=args.date)
        }
    symbols = [symbol for symbol in names_by_symbol if symbol not in collected_symbols]
    skipped = len(names_by_symbol) - len(symbols)
    if not symbols:
        print(f"Skipped {skipped} already collected quotes.")
        print("Collected 0 quotes, 0 failures.")
        return 0

    for batch in _chunks(symbols, args.batch_size):
        try:
            quotes = _fetch_batch(args, batch)
        except subprocess.TimeoutExpired:
            if args.no_restart_on_timeout:
                quotes = _collect_one_by_one(args, batch, failures)
            else:
                if _restart_container(args.restart_container_on_timeout):
                    print(
                        "Restarted container after timeout: "
                        f"{args.restart_container_on_timeout}"
                    )
                    try:
                        quotes = _fetch_batch(args, batch)
                    except (
                        subprocess.CalledProcessError,
                        subprocess.TimeoutExpired,
                        ValueError,
                        KeyError,
                    ):
                        quotes = _collect_one_by_one(args, batch, failures)
                else:
                    quotes = _collect_one_by_one(args, batch, failures)
        except (
            subprocess.CalledProcessError,
            ValueError,
            KeyError,
        ):
            quotes = _collect_one_by_one(args, batch, failures)

        returned_symbols = set()
        for quote in quotes:
            symbol = quote["symbol"]
            returned_symbols.add(symbol)
            quote["trade_date"] = quote.get("trade_date") or args.date
            if not quote.get("name"):
                quote["name"] = names_by_symbol.get(symbol, symbol)
            upsert_daily_quote(db_path, quote)
            successes += 1
        for symbol in set(batch) - returned_symbols:
            failures.append((symbol, "symbol missing from batch response"))

    print(f"Skipped {skipped} already collected quotes.")
    print(f"Collected {successes} quotes, {len(failures)} failures.")
    for symbol, message in failures:
        print(f"- {symbol}: {message}")
    return 0 if successes else 1


def _fetch_batch(args: argparse.Namespace, batch: list[str]) -> list[dict]:
    return fetch_stocks(
        batch,
        chrome_remote_url=args.chrome_remote_url,
        timeout_seconds=args.request_timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay,
    )


def _restart_container(container_name: str) -> bool:
    try:
        subprocess.run(["docker", "restart", container_name], check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Failed to restart container {container_name}: {exc}")
        return False
    return True


def _ensure_browser(args: argparse.Namespace) -> bool:
    if _is_chrome_remote_ready(args.chrome_remote_url):
        return True

    if not _restart_or_start_container(
        args.restart_container_on_timeout,
        args.headless_image,
        args.headless_host_port,
    ):
        return False

    for _ in range(10):
        time.sleep(1)
        if _is_chrome_remote_ready(args.chrome_remote_url):
            print(
                "Started container for browser dependency: "
                f"{args.restart_container_on_timeout}"
            )
            return True
    return False


def _is_chrome_remote_ready(chrome_remote_url: str) -> bool:
    url = f"{chrome_remote_url.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _restart_or_start_container(
    container_name: str,
    image: str,
    host_port: str,
) -> bool:
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name=^/{container_name}$",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if container_name in result.stdout.splitlines():
            return _restart_container(container_name)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "-p",
                f"{host_port}:9222",
                "--rm",
                "--name",
                container_name,
                image,
            ],
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Failed to start container {container_name}: {exc}")
        return False
    return True


def _collect_one_by_one(
    args: argparse.Namespace,
    batch: list[str],
    failures: list[tuple[str, str]],
) -> list[dict]:
    quotes: list[dict] = []
    for symbol in batch:
        try:
            quotes.append(_fetch_single(args, symbol))
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ValueError,
            KeyError,
        ) as exc:
            failures.append((symbol, str(exc)))
    return quotes


def _fetch_single(args: argparse.Namespace, symbol: str) -> dict:
    return fetch_stock(
        symbol,
        chrome_remote_url=args.chrome_remote_url,
        timeout_seconds=args.request_timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay,
    )


def _chunks(values: list[str], size: int) -> list[list[str]]:
    if size < 1:
        raise ValueError("--batch-size must be at least 1")
    return [values[index : index + size] for index in range(0, len(values), size)]


def _show(args: argparse.Namespace, db_path: Path) -> None:
    quotes = load_quotes(db_path, trade_date=args.date, symbol=args.symbol)
    signals = load_signals(db_path, trade_date=args.date, symbol=args.symbol)
    if not quotes and not signals:
        print(f"No data for {args.symbol}.")
        return
    if quotes:
        print("## Quotes")
        print(pd.DataFrame(quotes).tail(20).to_string(index=False))
    if signals:
        print("## Signals")
        print(pd.DataFrame(signals).tail(20).to_string(index=False))


if __name__ == "__main__":
    raise SystemExit(main())
