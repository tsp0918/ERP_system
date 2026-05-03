#!/usr/bin/env bash
# setup.sh — 初回セットアップ (仮想環境作成・依存インストール・.env生成・シードデータ投入)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== [1/5] 仮想環境の作成 ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  .venv を作成しました"
else
    echo "  .venv は既に存在します (スキップ)"
fi

echo "=== [2/5] 依存パッケージのインストール ==="
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "=== [3/5] .env の生成 ==="
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  .env.example をコピーしました"
else
    echo "  .env は既に存在します (スキップ)"
fi

echo "=== [4/5] データベース初期化 ==="
# SQLite の場合はサーバ起動時に create_all_tables() が走るため、
# ここでは一度だけ起動して即停止することでテーブルを作成する
python - <<'EOF'
from app.core.database import create_all_tables
create_all_tables()
print("  テーブルを作成しました")
EOF

echo "=== [5/5] シードデータの投入 ==="
python scripts/seed.py
python scripts/seed_pp.py
python scripts/seed_mm.py
python scripts/seed_pp_execution.py
python scripts/seed_fi_hr.py

echo ""
echo "======================================"
echo "  セットアップ完了!"
echo "  起動: ./start.sh"
echo "  URL : http://localhost:8888/docs"
echo "======================================"
