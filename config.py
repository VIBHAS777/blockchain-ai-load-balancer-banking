"""Runtime configuration for the real backend server pool."""

SERVER_URLS = {
    "Server-A": "http://localhost:8001",
    "Server-B": "http://localhost:8002",
    "Server-C": "http://localhost:8003",
}

PRIMARY_SERVERS = ("Server-A", "Server-B")
FALLBACK_SERVER = "Server-C"

REQUEST_TIMEOUT_SECONDS = 2.0
CLUSTER_FAIL_CPU_THRESHOLD = 100.0

LATENCY_THRESHOLDS = {
    "degraded": 200.0,
    "critical": 350.0,
    "unreachable": 500.0,
}

OVERLOAD_LIMITS = {
    "cpu": 90.0,
    "memory": 90.0,
    "connections": 9999,   # Per-server limits own connection saturation.
    "latency": 250.0,
    "response_time": 300.0,
}

# Per-server max connection limits (hardware/config based)
SERVER_CONNECTION_LIMITS = {
    "Server-A": 2000,
    "Server-B": 1500,
    "Server-C": 1000,
}

# Cascade risk threshold: if remaining servers are above this percentage
# of their own limit, warn that the cluster is at risk.
CASCADE_RISK_THRESHOLD = 0.80

RESPONSE_TIME_THRESHOLDS = {
    "slow": 5000.0,
    "timeout": 10000.0,
    "dead": 30000.0,
}

# Consistent hashing ring config
VIRTUAL_NODES_PER_SERVER = 300
