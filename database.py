"""
SQLite-backed transaction store.

This keeps transactions on disk so verification and tamper demos
survive Flask restarts.
"""

import random
import sqlite3
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional


DATA_DIR = Path(__file__).resolve().parent / "data"
DB_FILE = DATA_DIR / "nexusbank.db"


def _new_id() -> str:
    return "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


class TransactionDB:
    def __init__(self, db_file: Path = DB_FILE):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    amount REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    server TEXT NOT NULL,
                    anomaly INTEGER NOT NULL,
                    risk_score REAL NOT NULL,
                    block_index INTEGER,
                    tx_hash TEXT,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transactions_tx_hash ON transactions(tx_hash)"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row | None) -> Optional[dict]:
        if row is None:
            return None
        record = dict(row)
        record["anomaly"] = bool(record["anomaly"])
        return record

    # ------------------------------------------------------------------
    def insert(self, *, sender: str, receiver: str, amount: float,
               server: str, anomaly: bool, risk_score: float,
               block_index: Optional[int] = None,
               tx_hash: Optional[str] = None,
               status: str = "SUCCESS",
               timestamp: Optional[str] = None,
               tx_id: Optional[str] = None) -> dict:

        tx_id = tx_id or _new_id()
        timestamp = timestamp or datetime.now(UTC).isoformat()
        record = {
            "tx_id": tx_id,
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "timestamp": timestamp,
            "server": server,
            "anomaly": bool(anomaly),
            "risk_score": risk_score,
            "block_index": block_index,
            "tx_hash": tx_hash,
            "status": status,
        }

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO transactions (
                    tx_id, sender, receiver, amount, timestamp, server,
                    anomaly, risk_score, block_index, tx_hash, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["tx_id"],
                    record["sender"],
                    record["receiver"],
                    record["amount"],
                    record["timestamp"],
                    record["server"],
                    int(record["anomaly"]),
                    record["risk_score"],
                    record["block_index"],
                    record["tx_hash"],
                    record["status"],
                ),
            )

        return record

    # ------------------------------------------------------------------
    def update_hash(self, tx_id: str, block_index: int, tx_hash: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE transactions
                SET block_index = ?, tx_hash = ?
                WHERE tx_id = ?
                """,
                (block_index, tx_hash, tx_id),
            )

    def get(self, tx_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE tx_id = ?",
                (tx_id,),
            ).fetchone()
        return self._row_to_record(row)

    def get_by_hash(self, tx_hash: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE tx_hash = ?",
                (tx_hash,),
            ).fetchone()
        return self._row_to_record(row)

    def all(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY timestamp DESC"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_transactions,
                    COALESCE(SUM(CASE WHEN anomaly = 1 THEN 1 ELSE 0 END), 0) AS flagged,
                    COALESCE(SUM(amount), 0) AS total_volume_inr
                FROM transactions
                """
            ).fetchone()

        total = int(row["total_transactions"])
        flagged = int(row["flagged"])
        return {
            "total_transactions": total,
            "flagged": flagged,
            "clean": total - flagged,
            "total_volume_inr": round(float(row["total_volume_inr"]), 2),
        }


# Singleton
db = TransactionDB()
