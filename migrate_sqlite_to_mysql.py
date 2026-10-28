"""Migrasikan data DUDA dari SQLite (duda.db) ke MySQL/MariaDB XAMPP.

Letakkan file ini di folder yang sama dengan duda.db, lalu jalankan:
    python migrate_sqlite_to_mysql.py

Migrasi mempertahankan ID, melewati baris yang sudah ada (aman dijalankan ulang),
dan tidak menghapus/mengubah data yang sudah ada di MySQL.
"""
import os
import sqlite3
import sys
from pathlib import Path

import mysql.connector
from mysql.connector import Error

ROOT = Path(__file__).resolve().parent
SQLITE_PATH = ROOT / "duda.db"
DB_CONFIG = {
    "host": os.getenv("DUDA_DB_HOST", "localhost"),
    "port": int(os.getenv("DUDA_DB_PORT", "3306")),
    "user": os.getenv("DUDA_DB_USER", "root"),
    "password": os.getenv("DUDA_DB_PASSWORD", ""),
    "database": os.getenv("DUDA_DB_NAME", "duda_db"),
    "charset": "utf8mb4",
    "use_unicode": True,
}

SCHEMA = {
    "transactions": """CREATE TABLE IF NOT EXISTS transactions (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        type VARCHAR(30) NOT NULL,
        amount BIGINT NOT NULL,
        category VARCHAR(100) NOT NULL,
        date DATE NOT NULL,
        description TEXT DEFAULT NULL,
        INDEX idx_transactions_date (date),
        INDEX idx_transactions_type (type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    "budgets": """CREATE TABLE IF NOT EXISTS budgets (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        month CHAR(7) NOT NULL,
        category VARCHAR(100) NOT NULL,
        amount BIGINT NOT NULL,
        UNIQUE KEY uq_budgets_month_category (month, category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    "settings": """CREATE TABLE IF NOT EXISTS settings (
        `key` VARCHAR(100) NOT NULL PRIMARY KEY,
        `value` TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
}


def table_exists(conn, table):
    cur = conn.cursor()
    try:
        cur.execute("SHOW TABLES LIKE %s", (table,))
        return cur.fetchone() is not None
    finally:
        cur.close()


def main():
    if not SQLITE_PATH.exists():
        print(f"ERROR: File SQLite tidak ditemukan: {SQLITE_PATH}")
        print("Salin duda.db lama ke folder yang sama dengan script ini. Jangan hapus file aslinya.")
        return 2

    try:
        source = sqlite3.connect(f"file:{SQLITE_PATH.as_posix()}?mode=ro", uri=True)
        source.row_factory = sqlite3.Row
        source_tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"transactions", "budgets", "settings"}
        missing = required - source_tables
        if missing:
            print("ERROR: Tabel berikut tidak ditemukan di duda.db:", ", ".join(sorted(missing)))
            source.close()
            return 2

        mysql_conn = mysql.connector.connect(**DB_CONFIG)
        mysql_cur = mysql_conn.cursor()
        try:
            for ddl in SCHEMA.values():
                mysql_cur.execute(ddl)
            mysql_conn.commit()

            # Import dengan ID asli. INSERT IGNORE tidak menimpa data target yang sudah ada.
            stats = {}
            for table, columns in [
                ("transactions", ["id", "type", "amount", "category", "date", "description"]),
                ("budgets", ["id", "month", "category", "amount"]),
                ("settings", ["key", "value"]),
            ]:
                source_rows = source.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in columns)} FROM "{table}"').fetchall()
                before = mysql_cur.rowcount
                inserted = 0
                placeholders = ", ".join(["%s"] * len(columns))
                if table == "settings":
                    sql = f"INSERT IGNORE INTO settings (`key`, `value`) VALUES ({placeholders})"
                else:
                    quoted = ", ".join(f"`{c}`" for c in columns)
                    sql = f"INSERT IGNORE INTO `{table}` ({quoted}) VALUES ({placeholders})"
                for row in source_rows:
                    values = tuple(row[c] for c in columns)
                    # Normalize date values for MySQL DATE columns.
                    if table == "transactions" and values[4]:
                        values = values[:4] + (str(values[4])[:10],) + values[5:]
                    mysql_cur.execute(sql, values)
                    inserted += max(mysql_cur.rowcount, 0)
                mysql_conn.commit()
                stats[table] = (len(source_rows), inserted, len(source_rows) - inserted)

            print("\nMIGRASI SELESAI")
            print(f"Sumber SQLite : {SQLITE_PATH}")
            print(f"Target MySQL  : {DB_CONFIG['host']}:{DB_CONFIG['port']} / {DB_CONFIG['database']}\n")
            for table, (total, inserted, skipped) in stats.items():
                print(f"{table:14} sumber={total:5} | ditambahkan={inserted:5} | dilewati={skipped:5}")
            print("\nBaris yang dilewati biasanya sudah memiliki ID/kunci yang sama di MySQL.")
            print("File duda.db SQLite tidak dihapus atau diubah; simpan sebagai cadangan.")
            return 0
        except Exception:
            mysql_conn.rollback()
            raise
        finally:
            mysql_cur.close()
            mysql_conn.close()
            source.close()
    except (Error, sqlite3.Error) as exc:
        print(f"ERROR saat migrasi: {exc}")
        print("Pastikan MySQL XAMPP Running, database duda_db tersedia, dan kredensial benar.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
