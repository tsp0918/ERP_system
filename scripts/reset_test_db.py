"""テストインスタンス用 DB を削除→再作成→最小シードを投入するスクリプト。

./start.sh --reset-test から呼び出される。
DATABASE_URL 環境変数が erp_test.db を指していることを前提とする。
"""
import os
import sys

# テスト DB 以外への実行を拒否
db_url = os.environ.get("DATABASE_URL", "")
if "erp_test" not in db_url:
    print(f"ERROR: DATABASE_URL={db_url!r} はテスト DB ではありません。")
    print("  .env.test を読み込んでから実行してください。")
    sys.exit(1)

# SQLite ファイルパスを抽出して削除
db_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"  削除: {db_path}")

# テーブル作成
from app.core.database import create_all_tables
create_all_tables()
print("  テーブルを作成しました")

# 最小シード（認証ユーザー + 基本マスタのみ）
import scripts.seed as seed_mod
seed_mod.main()
print("  基本シード完了")
print("  テスト DB の初期化が完了しました")
