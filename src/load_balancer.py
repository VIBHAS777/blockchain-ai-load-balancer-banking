import numpy as np

class AILoadBalancer:
    """
    Predictive AI load balancing engine utilizing health telemetry (CPU, Memory, Active Connections,
    Transaction Queue Depth) to compute optimum server assignments across core banking nodes.
    """
    def __init__(self, nodes: list):
        self.nodes = nodes

    def predict_node_score(self, node_metrics: dict) -> float:
        # Weighted cost function: lower is better
        # Score = 0.35*CPU + 0.25*Mem + 0.30*(ActiveConns/MaxConns) + 0.10*AvgLatency
        cpu_load = node_metrics.get("cpu_percent", 50.0) / 100.0
        mem_load = node_metrics.get("mem_percent", 50.0) / 100.0
        conn_ratio = node_metrics.get("active_conns", 10) / node_metrics.get("max_conns", 100)
        norm_lat = min(node_metrics.get("avg_latency_ms", 10.0) / 100.0, 1.0)
        
        score = (0.35 * cpu_load) + (0.25 * mem_load) + (0.30 * conn_ratio) + (0.10 * norm_lat)
        return score

    def route_transaction(self, cluster_state: dict) -> tuple:
        best_node = None
        min_score = float("inf")
        
        for node_id, metrics in cluster_state.items():
            if not metrics.get("healthy", True):
                continue
            score = self.predict_node_score(metrics)
            if score < min_score:
                min_score = score
                best_node = node_id
                
        predicted_latency = min_score * 35.0 # Estimated ms
        return best_node, round(predicted_latency, 2)
