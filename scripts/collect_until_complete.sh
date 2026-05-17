#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="/root/python/cross-etf-scout"
DB_PATH="$ROOT_DIR/data/cross_etf_scout.sqlite"
LOCK_PATH="/tmp/cross-etf-scout-collect.lock"
TRADE_DATE="${1:-$(TZ=Asia/Shanghai date +%F)}"
LOG_DIR="$ROOT_DIR/logs"
LOG_PATH="$LOG_DIR/collect-$TRADE_DATE.log"
REPORT_PATH="$LOG_DIR/report-$TRADE_DATE.md"
TELEGRAM_PATH="$LOG_DIR/telegram-$TRADE_DATE.md"
MAX_ATTEMPTS="${CES_COLLECT_MAX_ATTEMPTS:-24}"
SLEEP_SECONDS="${CES_COLLECT_SLEEP_SECONDS:-300}"

mkdir -p "$LOG_DIR"

exec >>"$LOG_PATH" 2>&1

send_success_notifications() {
  local active_count="$1"
  local quote_count="$2"

  PYTHONPATH=src python3 -m cross_etf_scout.cli report --date "$TRADE_DATE" > "$REPORT_PATH" || true
  PYTHONPATH=src python3 -m cross_etf_scout.cli candidates --date "$TRADE_DATE" >> "$REPORT_PATH" || true
  PYTHONPATH=src python3 -m cross_etf_scout.cli telegram-digest --date "$TRADE_DATE" > "$TELEGRAM_PATH" || true

  local signal_count
  signal_count="$(sqlite3 "$DB_PATH" "select count(*) from daily_signals where trade_date='$TRADE_DATE';")"
  local watch_count
  watch_count="$(sqlite3 "$DB_PATH" "select count(*) from daily_signals where trade_date='$TRADE_DATE' and category in ('强势启动','趋势确认');")"
  local danger_count
  danger_count="$(sqlite3 "$DB_PATH" "select count(*) from daily_signals where trade_date='$TRADE_DATE' and category in ('极端过热','热度退潮','流动性不足或数据异常');")"
  local summary
  summary="cross-etf-scout 采集完成
日期: $TRADE_DATE
行情: $quote_count/$active_count
可选池: $watch_count
危险池: $danger_count
信号总数: $signal_count
日志: $LOG_PATH"

  PYTHONPATH=src python3 -m cross_etf_scout.notifications \
    --channel workwechat \
    --message "$summary" || true

  PYTHONPATH=src python3 -m cross_etf_scout.notifications \
    --channel telegram \
    --file "$TELEGRAM_PATH" || true
}

send_failure_notification() {
  local active_count="$1"
  local quote_count="$2"
  local summary
  summary="cross-etf-scout 采集未完成
日期: $TRADE_DATE
行情: $quote_count/$active_count
日志: $LOG_PATH"

  PYTHONPATH=src python3 -m cross_etf_scout.notifications \
    --channel workwechat \
    --message "$summary" || true
}

is_weekend() {
  local day_of_week
  day_of_week="$(TZ=Asia/Shanghai date -d "$TRADE_DATE" +%u)"
  [ "$day_of_week" = "6" ] || [ "$day_of_week" = "7" ]
}

latest_complete_trade_date() {
  sqlite3 "$DB_PATH" "
    with active as (
      select count(*) as active_count from etfs where active = 1
    ),
    complete_dates as (
      select trade_date
      from daily_quotes, active
      where trade_date <= '$TRADE_DATE'
      group by trade_date
      having count(*) = active.active_count
    )
    select coalesce(max(trade_date), '') from complete_dates;
  "
}

exit_if_weekend_data_is_stale() {
  local active_count="$1"
  local quote_count="$2"
  local latest_date

  if [ "$active_count" = "0" ] || [ "$quote_count" != "0" ] || ! is_weekend; then
    return 1
  fi

  latest_date="$(latest_complete_trade_date)"
  if [ -n "$latest_date" ] && [ "$latest_date" != "$TRADE_DATE" ]; then
    echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] market data not updated for $TRADE_DATE; latest_complete_trade_date=$latest_date"
    return 0
  fi
  return 1
}

echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] collect_until_complete start trade_date=$TRADE_DATE"

cd "$ROOT_DIR" || exit 1

exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] another collect job is already running"
  exit 0
fi

if [ ! -f "$DB_PATH" ]; then
  echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] database missing, running init-db and import-etfs"
  PYTHONPATH=src python3 -m cross_etf_scout.cli init-db || exit 1
  PYTHONPATH=src python3 -m cross_etf_scout.cli import-etfs || exit 1
fi

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  active_count="$(sqlite3 "$DB_PATH" "select count(*) from etfs where active=1;")"
  quote_count="$(sqlite3 "$DB_PATH" "select count(*) from daily_quotes where trade_date='$TRADE_DATE';")"

  echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] attempt=$attempt active=$active_count quotes=$quote_count"

  if [ "$active_count" != "0" ] && [ "$quote_count" = "$active_count" ]; then
    echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] collection complete"
    send_success_notifications "$active_count" "$quote_count"
    exit 0
  fi

  if exit_if_weekend_data_is_stale "$active_count" "$quote_count"; then
    exit 0
  fi

  PYTHONPATH=src python3 -m cross_etf_scout.cli collect \
    --date "$TRADE_DATE" \
    --batch-size "${CES_COLLECT_BATCH_SIZE:-5}" \
    --request-timeout "${CES_COLLECT_REQUEST_TIMEOUT:-30}" \
    --retries "${CES_COLLECT_RETRIES:-2}" \
    --retry-delay "${CES_COLLECT_RETRY_DELAY:-1}" \
    --ensure-browser \
    --restart-container-on-timeout "${CES_HEADLESS_CONTAINER_NAME:-headless-shell}" \
    --headless-image "${CES_HEADLESS_IMAGE:-chromedp/headless-shell}" \
    --headless-host-port "${CES_HEADLESS_HOST_PORT:-9222}"

  active_count="$(sqlite3 "$DB_PATH" "select count(*) from etfs where active=1;")"
  quote_count="$(sqlite3 "$DB_PATH" "select count(*) from daily_quotes where trade_date='$TRADE_DATE';")"

  echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] after collect active=$active_count quotes=$quote_count"

  if exit_if_weekend_data_is_stale "$active_count" "$quote_count"; then
    exit 0
  fi

  if [ "$active_count" != "0" ] && [ "$quote_count" = "$active_count" ]; then
    echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] collection complete"
    send_success_notifications "$active_count" "$quote_count"
    exit 0
  fi

  attempt=$((attempt + 1))
  if [ "$attempt" -le "$MAX_ATTEMPTS" ]; then
    echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] sleeping ${SLEEP_SECONDS}s before retry"
    sleep "$SLEEP_SECONDS"
  fi
done

echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] collection incomplete after $MAX_ATTEMPTS attempts"
send_failure_notification "$active_count" "$quote_count"
exit 1
