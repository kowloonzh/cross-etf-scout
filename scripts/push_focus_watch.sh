#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="/root/python/cross-etf-scout"
LOCK_PATH="/tmp/cross-etf-scout-focus-watch.lock"
TRADE_DATE="${1:-$(TZ=Asia/Shanghai date +%F)}"
LOG_DIR="$ROOT_DIR/logs"
LOG_PATH="$LOG_DIR/focus-watch-$TRADE_DATE.log"
DIGEST_PATH="$LOG_DIR/focus-watch-$TRADE_DATE.txt"

mkdir -p "$LOG_DIR"

exec >>"$LOG_PATH" 2>&1

echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] focus watch start trade_date=$TRADE_DATE"

cd "$ROOT_DIR" || exit 1

exec 9>"$LOCK_PATH"
if ! flock -n 9; then
  echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] another focus watch job is already running"
  exit 0
fi

PYTHONPATH=src python3 -m cross_etf_scout.cli focus-live-digest \
  --date "$TRADE_DATE" \
  --batch-size "${CES_FOCUS_BATCH_SIZE:-10}" \
  --request-timeout "${CES_FOCUS_REQUEST_TIMEOUT:-30}" \
  --retries "${CES_FOCUS_RETRIES:-2}" \
  --retry-delay "${CES_FOCUS_RETRY_DELAY:-1}" \
  --ensure-browser \
  --restart-container-on-timeout "${CES_HEADLESS_CONTAINER_NAME:-headless-shell}" \
  --headless-image "${CES_HEADLESS_IMAGE:-chromedp/headless-shell}" \
  --headless-host-port "${CES_HEADLESS_HOST_PORT:-9222}" \
  > "$DIGEST_PATH"

PYTHONPATH=src python3 -m cross_etf_scout.notifications \
  --channel workwechat \
  --file "$DIGEST_PATH"

echo "[$(TZ=Asia/Shanghai date '+%F %T %Z')] focus watch complete"
