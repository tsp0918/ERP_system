#!/usr/bin/env bash
# test.sh — テスト実行
#   オプション:
#     --cov         カバレッジ付きで実行
#     --integration 統合テスト (ERP + AI_TM Stub の両方が起動済みである必要あり)
#     -k <expr>     pytest の -k オプションをそのまま渡す
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "ERROR: .venv が見つかりません。先に ./setup.sh を実行してください。"
    exit 1
fi

source .venv/bin/activate

# 開発用パッケージが未インストールなら追加
python -c "import pytest" 2>/dev/null || pip install --quiet -r requirements-dev.txt

COV=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cov)
            COV="--cov=app --cov-report=term-missing"
            shift
            ;;
        --integration)
            echo "  統合テスト: scripts/integration_test.py を実行"
            python scripts/integration_test.py
            exit $?
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo ""
echo "=== pytest 実行 ==="
# shellcheck disable=SC2086
pytest $COV "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
