"""Export all SQLite tables to CSV files."""
import csv
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "erp.db"
OUTPUT_DIR = Path(__file__).parent.parent / "exports"


def export_all(db_path: Path, output_dir: Path) -> None:
    if not db_path.exists():
        print(f"ERROR: {db_path} が見つかりません。シードを実行してください。")
        sys.exit(1)

    output_dir.mkdir(exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]

    print(f"出力先: {output_dir}\n")
    print(f"{'テーブル':<40} {'件数':>6}  ファイル")
    print("-" * 70)

    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        out_file = output_dir / f"{table}.csv"
        if rows:
            with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows([dict(r) for r in rows])
        else:
            out_file.touch()
        print(f"  {table:<38} {len(rows):>6}件  {out_file.name}")

    conn.close()
    print(f"\n✓ {len(tables)} テーブルを CSV に出力しました。")


if __name__ == "__main__":
    export_all(DB_PATH, OUTPUT_DIR)
