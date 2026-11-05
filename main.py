import random
from src.blockchain import BankingBlockchain
from src.load_balancer import AILoadBalancer

def main():
    print("=" * 70)
    print("  AI-Driven Load Balancer with Blockchain Decision-Making")
    print("  Publication: 10th IEEE ICECA 2026, Coimbatore")
    print("=" * 70)

    nodes = ["Bank-Node-Alpha", "Bank-Node-Beta", "Bank-Node-Gamma", "Bank-Node-Delta"]
    balancer = AILoadBalancer(nodes)
    ledger = BankingBlockchain(difficulty=2)

    print(f"[*] Initialized banking cluster with 4 distributed core transaction nodes.")
    print(f"[*] Genesis block created: {ledger.chain[0].hash[:16]}...\n")

    print("[*] Simulating high-concurrency burst of 10 incoming customer transactions:")
    for i in range(1, 11):
        # Simulate dynamic node load
        cluster_state = {
            node: {
                "cpu_percent": random.uniform(15, 90),
                "mem_percent": random.uniform(20, 85),
                "active_conns": random.randint(10, 80),
                "max_conns": 100,
                "avg_latency_ms": random.uniform(5, 50),
                "healthy": True
            }
            for node in nodes
        }
        
        tx_id = f"TX-2026-BNK-{1000 + i}"
        client_ip = f"192.168.1.{random.randint(10, 200)}"
        
        chosen_node, pred_lat = balancer.route_transaction(cluster_state)
        ledger.record_routing_decision(tx_id, client_ip, chosen_node, pred_lat)
        
        print(f"  [Tx {i:02d}] {tx_id} -> Assigned to [{chosen_node}] | Est. Latency: {pred_lat} ms")

    print("\n[*] Mining consensus block to commit tamper-proof routing audit trail...")
    mined_block = ledger.mine_pending_block()
    print(f"[✓] Block #{mined_block.index} successfully mined!")
    print(f"    - Block Hash : {mined_block.hash}")
    print(f"    - Transactions Committed : {len(mined_block.transactions)}")
    print(f"    - Nonce Found : {mined_block.nonce}")
    print("=" * 70)

if __name__ == "__main__":
    main()
