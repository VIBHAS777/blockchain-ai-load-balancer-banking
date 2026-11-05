"""
Lightweight file-backed blockchain for transaction proof-of-existence.

Blocks are stored in `data/blockchain.json` so the ledger survives restarts
and can be inspected during tamper-detection demos.
"""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHAIN_FILE = DATA_DIR / "blockchain.json"


class Block:
    def __init__(self, index: int, tx_hash: str, previous_hash: str, metadata: dict | None = None):
        self.index = index
        self.timestamp = time.time()
        self.tx_hash = tx_hash
        self.previous_hash = previous_hash
        self.metadata = metadata or {}
        self.nonce = 0
        self.block_hash = self._mine_block()

    # ------------------------------------------------------------------
    # Simple proof-of-work: find a hash starting with '00'
    # ------------------------------------------------------------------
    def _mine_block(self, difficulty: int = 2) -> str:
        prefix = "0" * difficulty
        while True:
            raw = json.dumps({
                "index": self.index,
                "timestamp": self.timestamp,
                "tx_hash": self.tx_hash,
                "previous_hash": self.previous_hash,
                "nonce": self.nonce,
            }, sort_keys=True)
            candidate = hashlib.sha256(raw.encode()).hexdigest()
            if candidate.startswith(prefix):
                return candidate
            self.nonce += 1

    @classmethod
    def from_storage(cls, payload: dict):
        block = cls.__new__(cls)
        block.index = payload["index"]
        block.timestamp = payload["timestamp"]
        block.tx_hash = payload["tx_hash"]
        block.previous_hash = payload["previous_hash"]
        block.metadata = payload.get("metadata", {})
        block.nonce = payload["nonce"]
        block.block_hash = payload["block_hash"]
        return block

    def to_storage_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "tx_hash": self.tx_hash,
            "previous_hash": self.previous_hash,
            "block_hash": self.block_hash,
            "nonce": self.nonce,
            "metadata": self.metadata,
        }

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "tx_hash": self.tx_hash,
            "previous_hash": self.previous_hash,
            "block_hash": self.block_hash,
            "nonce": self.nonce,
            "metadata": self.metadata,
        }


class Blockchain:
    def __init__(self, chain_file: Path = CHAIN_FILE):
        self.chain_file = Path(chain_file)
        self.chain_file.parent.mkdir(parents=True, exist_ok=True)
        self.chain: list[Block] = []
        self._load_chain()

    def _load_chain(self):
        if self.chain_file.exists():
            payload = json.loads(self.chain_file.read_text(encoding="utf-8"))
            self.chain = [Block.from_storage(item) for item in payload]
            if self.chain:
                return
        self.chain = []
        self._add_genesis()
        self._save_chain()

    def _save_chain(self):
        payload = [block.to_storage_dict() for block in self.chain]
        self.chain_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    def _add_genesis(self):
        genesis = Block(
            index=0,
            tx_hash="0" * 64,
            previous_hash="0" * 64,
            metadata={"note": "Genesis block"},
        )
        self.chain.append(genesis)

    # ------------------------------------------------------------------
    @staticmethod
    def compute_tx_hash(tx_id: str, sender: str, receiver: str,
                        amount: float, timestamp: str,
                        status: str = "", server: str = "") -> str:
        """Deterministic SHA-256 of anchored transaction fields."""
        raw = f"{tx_id}|{sender}|{receiver}|{amount}|{timestamp}|{status}|{server}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    def add_transaction(self, tx_id: str, sender: str, receiver: str,
                        amount: float, timestamp: str, extra: dict | None = None) -> dict:
        extra = extra or {}
        tx_hash = self.compute_tx_hash(
            tx_id,
            sender,
            receiver,
            amount,
            timestamp,
            extra.get("status", ""),
            extra.get("server", ""),
        )
        previous = self.chain[-1].block_hash
        block = Block(
            index=len(self.chain),
            tx_hash=tx_hash,
            previous_hash=previous,
            metadata={"tx_id": tx_id, **extra},
        )
        self.chain.append(block)
        self._save_chain()
        return {"block_index": block.index, "tx_hash": tx_hash, "block_hash": block.block_hash}

    # ------------------------------------------------------------------
    def verify_transaction(self, tx_id: str, sender: str, receiver: str,
                           amount: float, timestamp: str,
                           status: str = "", server: str = "") -> dict:
        """Re-compute the hash and search the chain."""
        expected = self.compute_tx_hash(tx_id, sender, receiver, amount, timestamp, status, server)
        for block in self.chain[1:]:
            if block.tx_hash == expected:
                return {
                    "valid": True,
                    "block_index": block.index,
                    "block_hash": block.block_hash,
                    "tx_hash": expected,
                }
        return {"valid": False, "reason": "Hash not found on chain", "tx_hash": expected}

    # ------------------------------------------------------------------
    def verify_by_hash(self, tx_hash: str) -> dict:
        """Verify directly by tx_hash - no DB lookup needed."""
        if not tx_hash or len(tx_hash) != 64:
            return {
                "valid": False,
                "reason": "Invalid hash - must be a 64-character SHA-256 hex string.",
            }
        for block in self.chain[1:]:
            if block.tx_hash == tx_hash:
                return {
                    "valid": True,
                    "block_index": block.index,
                    "block_hash": block.block_hash,
                    "tx_hash": tx_hash,
                    "timestamp": datetime.fromtimestamp(block.timestamp).isoformat(),
                    "metadata": block.metadata,
                }
        return {
            "valid": False,
            "reason": "Hash not found on chain - transaction may be tampered or never recorded.",
            "tx_hash": tx_hash,
        }

    # ------------------------------------------------------------------
    def is_chain_intact(self) -> bool:
        for i in range(1, len(self.chain)):
            cur = self.chain[i]
            prev = self.chain[i - 1]
            if cur.previous_hash != prev.block_hash:
                return False
            raw = json.dumps({
                "index": cur.index,
                "timestamp": cur.timestamp,
                "tx_hash": cur.tx_hash,
                "previous_hash": cur.previous_hash,
                "nonce": cur.nonce,
            }, sort_keys=True)
            if hashlib.sha256(raw.encode()).hexdigest() != cur.block_hash:
                return False
        return True

    # ------------------------------------------------------------------
    def get_chain(self) -> list[dict]:
        return [block.to_dict() for block in self.chain]

    def stats(self) -> dict:
        total_blocks = len(self.chain)
        transaction_blocks = max(total_blocks - 1, 0)
        return {
            "blocks": total_blocks,
            "transaction_blocks": transaction_blocks,
            "genesis_blocks": 1 if total_blocks else 0,
            "intact": self.is_chain_intact(),
            "latest_hash": self.chain[-1].block_hash,
        }
