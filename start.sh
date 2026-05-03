#!/usr/bin/env bash
# start.sh — ERPサーバ起動
#   オプション:
#     --with-stub   AI_TM Stub (port 5001) も同時に起動する
#     --mock        AI_TM_MOCK_MODE=true で起動 (デフォルト)
#     --live        AI_TM_MOCK_MODE=false で起動 (AI_TM Stub/本実装が必要)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "ERROR: .venv が見つかりません。先に ./setup.sh を実行してください。"
    exit 1
fi

source .venv/bin/activate

WITH_STUB=false
MOCK_MODE=""

for arg in "$@"; do
    case "$arg" in
        --with-stub) WITH_STUB=true ;;
        --mock)      MOCK_MODE=true  ;;
        --live)      MOCK_MODE=false ;;
    esac
done

# .env の AI_TM_MOCK_MODE を上書き (オプション指定時のみ)
if [ -n "$MOCK_MODE" ]; then
    if [ "$MOCK_MODE" = "true" ]; then
        sed -i.bak 's/^AI_TM_MOCK_MODE=.*/AI_TM_MOCK_MODE=true/' .env
        echo "  AI_TM_MOCK_MODE=true に設定"
    else
        sed -i.bak 's/^AI_TM_MOCK_MODE=.*/AI_TM_MOCK_MODE=false/' .env
        echo "  AI_TM_MOCK_MODE=false に設定"
    fi
    rm -f .env.bak
fi

# AI_TM Stub を別プロセスで起動
STUB_PID=""
if [ "$WITH_STUB" = "true" ]; then
    echo "  AI_TM Stub を port 5001 で起動..."
    uvicorn ai_tm_stub.main:app --port 5001 &
    STUB_PID=$!
    echo "  Stub PID: $STUB_PID"
fi

# 終了時に Stub も停止
cleanup() {
    if [ -n "$STUB_PID" ]; then
        echo ""
        echo "  AI_TM Stub (PID $STUB_PID) を停止..."
        kill "$STUB_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

echo ""
echo "======================================"
echo "  ERP 起動中 → http://localhost:8888"
echo "  Swagger UI  → http://localhost:8888/docs"
echo "  終了: Ctrl+C"
echo "======================================"
echo ""

uvicorn app.main:app --reload --port 8888
