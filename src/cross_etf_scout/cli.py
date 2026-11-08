from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

from cross_etf_scout.analysis import generate_candidate_signals
from cross_etf_scout.reporting import (
    build_focus_rows,
    format_focus_live_digest,
    build_report_sections,
    format_candidates,
    format_report,
    format_telegram_digest,
    format_workwechat_digest,
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
from cross_etf_scout.tencent import fetch_stock, fetch_stocks


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

    if args.command == "workwechat-digest":
        quotes = pd.DataFrame(load_quotes(db_path))
        focus_codes = load_focus_etf_codes(args.config)
        focus_etfs = _select_focus_etfs(list_active_etfs(db_path), focus_codes)
        if args.focus_only:
            if not focus_etfs:
                print("No active ETFs match focus_etfs in the config.")
                return 1
            focus_symbols = {_normalize_symbol(etf["symbol"]) for etf in focus_etfs}
            if not quotes.empty:
                quotes = quotes[
                    quotes["symbol"].map(_normalize_symbol).isin(focus_symbols)
                ]
        signals = generate_candidate_signals(quotes, args.date)
        replace_daily_signals(db_path, args.date, signals)
        daily_quotes = [
            quote
            for quote in load_quotes(db_path, trade_date=args.date)
            if not args.focus_only
            or _normalize_symbol(quote["symbol"])
            in focus_symbols
        ]
        quote_count = len(daily_quotes)
        active_count = (
            len(focus_etfs) if args.focus_only else len(list_active_etfs(db_path))
        )
        focus_rows = build_focus_rows(quotes, args.date, focus_codes)
        print(
            format_workwechat_digest(
                signals,
                args.date,
                quote_count,
                active_count,
                focus_rows=focus_rows,
                focus_only=args.focus_only,
            )
        )
        return 0

    if args.command == "focus-live-digest":
        return _focus_live_digest(args, db_path)

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
    collect_parser.add_argument("--batch-size", type=int, default=10)
    collect_parser.add_argument("--request-timeout", type=int, default=30)
    collect_parser.add_argument("--retries", type=int, default=2)
    collect_parser.add_argument("--retry-delay", type=float, default=1.0)
    collect_parser.add_argument("--force", action="store_true")
    collect_parser.add_argument(
        "--focus-only",
        action="store_true",
        help="collect only active ETFs listed in focus_etfs config",
    )
    collect_parser.add_argument("--config", default="config/config.yaml")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--date", default=date.today().isoformat())

    candidates_parser = subparsers.add_parser("candidates")
    candidates_parser.add_argument("--date", default=date.today().isoformat())

    telegram_digest_parser = subparsers.add_parser("telegram-digest")
    telegram_digest_parser.add_argument("--date", default=date.today().isoformat())
    telegram_digest_parser.add_argument("--config", default="config/config.yaml")

    workwechat_digest_parser = subparsers.add_parser("workwechat-digest")
    workwechat_digest_parser.add_argument("--date", default=date.today().isoformat())
    workwechat_digest_parser.add_argument("--config", default="config/config.yaml")
    workwechat_digest_parser.add_argument("--focus-only", action="store_true")

    focus_live_parser = subparsers.add_parser("focus-live-digest")
    focus_live_parser.add_argument("--date", default=date.today().isoformat())
    focus_live_parser.add_argument("--config", default="config/config.yaml")
    focus_live_parser.add_argument("--batch-size", type=int, default=10)
    focus_live_parser.add_argument("--request-timeout", type=int, default=30)
    focus_live_parser.add_argument("--retries", type=int, default=2)
    focus_live_parser.add_argument("--retry-delay", type=float, default=1.0)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("symbol")
    show_parser.add_argument("--date", default=None)

    return parser


def _collect(args: argparse.Namespace, db_path: Path) -> int:
    etfs = list_active_etfs(db_path)
    if not etfs:
        print("ETF universe is empty. Run ces import-etfs first.")
        return 1

    if args.focus_only:
        focus_codes = load_focus_etf_codes(args.config)
        if not focus_codes:
            print(f"No focus_etfs configured in {args.config}.")
            return 1
        etfs = _select_focus_etfs(etfs, focus_codes)
        if not etfs:
            print(f"No active ETFs match focus_etfs in {args.config}.")
            return 1

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
        if args.focus_only:
            return _focus_collection_status(args, db_path, names_by_symbol)
        return 0

    for batch in _chunks(symbols, args.batch_size):
        try:
            quotes = _fetch_batch(args, batch)
        except subprocess.TimeoutExpired:
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
    if args.focus_only:
        return _focus_collection_status(args, db_path, names_by_symbol)
    return 0 if successes else 1


def _focus_collection_status(
    args: argparse.Namespace, db_path: Path, names_by_symbol: dict[str, str]
) -> int:
    expected_symbols = set(names_by_symbol)
    collected_symbols = {
        quote["symbol"] for quote in load_quotes(db_path, trade_date=args.date)
    }
    missing_symbols = expected_symbols - collected_symbols
    print(
        f"Scope: focus-only; quotes available {len(expected_symbols) - len(missing_symbols)}"
        f"/{len(expected_symbols)} for {args.date}."
    )
    for symbol in sorted(missing_symbols):
        print(f"- {symbol}: no quote saved for {args.date}")
    return 1 if missing_symbols else 0


def _select_focus_etfs(etfs: list[dict], focus_codes: list[str]) -> list[dict]:
    focus_symbols = {_normalize_symbol(code) for code in focus_codes}
    return [etf for etf in etfs if _normalize_symbol(etf["symbol"]) in focus_symbols]


def _focus_live_digest(args: argparse.Namespace, db_path: Path) -> int:
    focus_codes = load_focus_etf_codes(args.config)
    if not focus_codes:
        print(format_focus_live_digest([], args.date))
        return 0

    active_etfs = list_active_etfs(db_path)
    etfs_by_code = {
        _normalize_symbol(etf["symbol"]): etf
        for etf in active_etfs
        if int(etf.get("active", 0)) == 1
    }
    selected_etfs = []
    for code in focus_codes:
        normalized = _normalize_symbol(code)
        etf = etfs_by_code.get(normalized)
        if etf is not None:
            selected_etfs.append(etf)

    symbols = [etf["symbol"] for etf in selected_etfs]
    names_by_symbol = {etf["symbol"]: etf["name"] for etf in selected_etfs}
    quotes: list[dict] = []
    for batch in _chunks(symbols, args.batch_size):
        quotes.extend(_fetch_batch(args, batch))

    returned_symbols = set()
    stale_quotes: list[tuple[str, str]] = []
    for quote in quotes:
        symbol = quote["symbol"]
        returned_symbols.add(symbol)
        source_date = quote.get("trade_date")
        if source_date != args.date:
            stale_quotes.append((symbol, str(source_date or "unknown")))
        if not quote.get("name") or quote["name"] == symbol:
            quote["name"] = names_by_symbol.get(symbol, symbol)

    missing_symbols = [symbol for symbol in symbols if symbol not in returned_symbols]
    if stale_quotes or missing_symbols:
        print(
            f"Live quote data is stale or incomplete; notification skipped for {args.date}."
        )
        for symbol, source_date in stale_quotes:
            print(f"- {symbol}: stale quote date {source_date} (expected {args.date})")
        for symbol in missing_symbols:
            print(f"- {symbol}: symbol missing from focus response")
        return 1

    ordered_quotes = sorted(
        quotes,
        key=lambda quote: symbols.index(quote["symbol"])
        if quote.get("symbol") in symbols
        else len(symbols),
    )
    print(format_focus_live_digest(ordered_quotes, args.date))
    return 0


def _fetch_batch(args: argparse.Namespace, batch: list[str]) -> list[dict]:
    return fetch_stocks(
        batch,
        chrome_remote_url=None,
        timeout_seconds=args.request_timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay,
    )


def _normalize_symbol(value: str) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith(("SH", "SZ")):
        return raw[2:]
    return raw


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
        chrome_remote_url=None,
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
