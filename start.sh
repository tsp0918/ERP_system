#!/usr/bin/env bash
# =============================================================================
# start.sh — Mini Global ERP 起動スクリプト
#
# 使い方:
#   ./start.sh                # 開発インスタンス起動 (port 9000, erp.db)
#   ./start.sh --dev          # ホットリロード付き開発モード
#   ./start.sh --test         # テストインスタンス起動 (port 9001, erp_test.db)
#   ./start.sh --reset-test   # テスト DB を初期化してから --test 起動
#   ./start.sh --stop         # 起動中のプロセスをすべて停止
#   ./start.sh --status       # 起動状態の確認
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv/bin"
export PYTHONPATH="$SCRIPT_DIR"
PIDFILE_DEV="$SCRIPT_DIR/.erp_dev.pid"
PIDFILE_TEST="$SCRIPT_DIR/.erp_test.pid"
DEV_PORT=9000
TEST_PORT=9001
DEV_URL="https://erp.tsp-aitrademanagement.com"
TEST_URL="https://erp-test.tsp-aitrademanagement.com"

# ── カラー出力 ──────────────────────────────────────────────────────────────
RESET='\033[0m'; BOLD='\033[1m'
GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'

info()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }

# ── 共通チェック ────────────────────────────────────────────────────────────
check_venv() {
  if [[ ! -f "$VENV/python3" ]]; then
    error "仮想環境が見つかりません: $VENV"
    echo "  先に ./setup.sh を実行してください。"
    exit 1
  fi
}

# ── --stop ──────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--stop" ]]; then
  info "ERP プロセスを停止しています…"
  for PIDFILE in "$PIDFILE_DEV" "$PIDFILE_TEST"; do
    if [[ -f "$PIDFILE" ]]; then
      PID=$(cat "$PIDFILE")
      LABEL=$(basename "$PIDFILE" .pid)
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" && ok "$LABEL (PID $PID) を停止しました"
      else
        warn "$LABEL の PID $PID はすでに停止済みです"
      fi
      rm -f "$PIDFILE"
    fi
  done
  # ポートが残っていれば強制解放
  for PORT in $DEV_PORT $TEST_PORT; do
    PID_PORT=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    if [[ -n "$PID_PORT" ]]; then
      kill "$PID_PORT" 2>/dev/null && info "ポート $PORT (PID $PID_PORT) を解放しました"
    fi
  done
  exit 0
fi

# ── --status ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--status" ]]; then
  echo ""
  echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
  echo -e "${BOLD}  Mini Global ERP — 起動状態${RESET}"
  echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
  for ENTRY in "dev:$PIDFILE_DEV:$DEV_PORT:$DEV_URL" "test:$PIDFILE_TEST:$TEST_PORT:$TEST_URL"; do
    LABEL="${ENTRY%%:*}"; REST="${ENTRY#*:}"
    PIDFILE="${REST%%:*}"; REST="${REST#*:}"
    PORT="${REST%%:*}";    URL="${REST#*:}"
    if [[ -f "$PIDFILE" ]]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        ok "$LABEL (PID $PID) — port $PORT — $URL"
      else
        warn "$LABEL — PID ファイルあり (PID $PID) だが停止済み"
      fi
    else
      echo -e "  ${LABEL}: ${RED}停止中${RESET}"
    fi
  done
  echo ""
  exit 0
fi

# ── --reset-test ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--reset-test" ]]; then
  check_venv
  info "テスト DB を初期化しています…"
  set -a; source "$SCRIPT_DIR/.env.test"; set +a
  "$VENV/python3" scripts/reset_test_db.py
  ok "テスト DB の初期化完了"
  # 初期化後そのままテストインスタンスを起動
  set -- "--test"
fi

# ── venv チェック ────────────────────────────────────────────────────────────
check_venv

# ── モード判定 ───────────────────────────────────────────────────────────────
MODE="dev"
DEV_MODE=0
if [[ "${1:-}" == "--dev" ]];  then DEV_MODE=1; fi
if [[ "${1:-}" == "--test" ]]; then MODE="test"; fi

if [[ "$MODE" == "test" ]]; then
  ENV_FILE=".env.test"
  PORT=$TEST_PORT
  PIDFILE="$PIDFILE_TEST"
  DB_LABEL="erp_test.db"
  EXT_URL="$TEST_URL"
else
  ENV_FILE=".env"
  PORT=$DEV_PORT
  PIDFILE="$PIDFILE_DEV"
  DB_LABEL="erp.db"
  EXT_URL="$DEV_URL"
fi

# ── .env 読み込み ────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SCRIPT_DIR/$ENV_FILE"
  set +a
  ok ".env 読み込み: $ENV_FILE"
else
  warn "$ENV_FILE が見つかりません。デフォルト設定で起動します。"
fi

# ── ポート競合チェック ──────────────────────────────────────────────────────
OLD_PID=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [[ -n "$OLD_PID" ]]; then
  warn "ポート $PORT が使用中 (PID $OLD_PID)。停止してから再起動します…"
  kill "$OLD_PID" 2>/dev/null || true
  sleep 1
fi

# ── ヘッダー表示 ────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  Mini Global ERP${RESET} — ${MODE} インスタンス起動"
echo -e "${BOLD}═══════════════════════════════════════════════${RESET}"
echo ""
info "DB     : $DB_LABEL"
info "ローカル: http://localhost:$PORT"
info "外部   : $EXT_URL"
info "API仕様 : http://localhost:$PORT/docs"
info "停止   : ./start.sh --stop"
echo ""

# ── 起動 ────────────────────────────────────────────────────────────────────
UVICORN_ARGS="app.main:app --host 0.0.0.0 --port $PORT"
if [[ $DEV_MODE -eq 1 ]]; then
  info "ホットリロードモードで起動します…"
  "$VENV/uvicorn" $UVICORN_ARGS --reload
else
  "$VENV/uvicorn" $UVICORN_ARGS &
  APP_PID=$!
  echo "$APP_PID" > "$PIDFILE"
  ok "ERP 起動済み (PID $APP_PID)"
  echo ""
  info "ログ: tail -f /tmp/erp_${MODE}.log"
  info "停止: ./start.sh --stop"
  # フォアグラウンドで待機（Ctrl+C で停止）
  wait "$APP_PID" || true
  rm -f "$PIDFILE"
fi
