import hashlib
import time
import json
from typing import List, Dict

class Block:
    def __init__(self, index: int, timestamp: float, transactions: List[Dict], previous_hash: str):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

class BankingBlockchain:
    """
    Decentralized immutable ledger recording banking load balancing decisions
    to prevent rogue node manipulation and single-point-of-failure routing attacks.
    """
    def __init__(self, difficulty: int = 2):
        self.chain: List[Block] = []
        self.difficulty = difficulty
        self.pending_decisions: List[Dict] = []
        self._create_genesis_block()

    def _create_genesis_block(self):
        genesis = Block(0, time.time(), [{"info": "Genesis Routing Ledger"}], "0")
        self.chain.append(genesis)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def record_routing_decision(self, tx_id: str, client_ip: str, assigned_node: str, predicted_latency_ms: float):
        self.pending_decisions.append({
            "tx_id": tx_id,
            "client_ip": client_ip,
            "assigned_node": assigned_node,
            "predicted_latency_ms": predicted_latency_ms,
            "timestamp": time.time()
        })

    def mine_pending_block(self) -> Block:
        if not self.pending_decisions:
            return None
        new_block = Block(
            index=len(self.chain),
            timestamp=time.time(),
            transactions=list(self.pending_decisions),
            previous_hash=self.last_block.hash
        )
        # Proof-of-Work consensus
        while not new_block.hash.startswith("0" * self.difficulty):
            new_block.nonce += 1
            new_block.hash = new_block.compute_hash()
            
        self.chain.append(new_block)
        self.pending_decisions = []
        return new_block
