"""Forward load-balanced requests to the selected backend server."""
# Fault-tolerance: if the primary selected server is unhealthy, the router
# automatically tries remaining servers in order of composite health score.

from __future__ import annotations

import hashlib
import ipaddress

import requests

from config import (
    FALLBACK_SERVER,
    OVERLOAD_LIMITS,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSE_TIME_THRESHOLDS,
    SERVER_CONNECTION_LIMITS,
    SERVER_URLS,
    LATENCY_THRESHOLDS,
)


def validate_ip(client_ip: str) -> str:
    if not client_ip or not client_ip.strip():
        raise ValueError("IP address is required.")
    try:
        return str(ipaddress.ip_address(client_ip.strip()))
    except ValueError as exc:
        raise ValueError(
            f"Invalid input '{client_ip}' — only IPv4 (e.g. 192.168.1.1) "
            f"or IPv6 (e.g. 2001:db8::1) addresses are accepted."
        ) from exc


def hash_ip_to_server(client_ip: str, live_servers: list[str]) -> str:
    digest = hashlib.sha256(client_ip.encode()).hexdigest()
    index = int(digest, 16) % len(live_servers)
    return live_servers[index]


def is_overloaded(metric: dict, server_name: str = None) -> bool:
    if not metric.get("available", True):
        return True

    # CPU / memory / latency / response_time use global limits
    global_keys = ["cpu", "memory", "latency", "response_time"]
    for key in global_keys:
        if key in OVERLOAD_LIMITS and metric.get(key, 0) >= OVERLOAD_LIMITS[key]:
            return True

    # Connections use per-server limit if server_name provided
    if server_name and server_name in SERVER_CONNECTION_LIMITS:
        if metric.get("connections", 0) >= SERVER_CONNECTION_LIMITS[server_name]:
            return True
    else:
        # Fallback to global limit
        if metric.get("connections", 0) >= OVERLOAD_LIMITS.get("connections", 500):
            return True

    return False


def is_latency_unreachable(metric: dict) -> bool:
    latency = metric.get("latency", 0)
    response_time = metric.get("response_time", 0)
    return (
        latency >= LATENCY_THRESHOLDS["unreachable"]
        or response_time >= LATENCY_THRESHOLDS["unreachable"]
    )


def is_connection_saturated(server_name: str, metric: dict) -> bool:
    """True if connections >= that server's hard limit."""
    limit = SERVER_CONNECTION_LIMITS.get(server_name, 1000)
    return metric.get("connections", 0) >= limit


def get_connection_usage(server_name: str, metric: dict) -> dict:
    """Returns connection usage stats for a server."""
    limit = SERVER_CONNECTION_LIMITS.get(server_name, 1000)
    current = metric.get("connections", 0)
    pct = round((current / limit) * 100, 1)
    return {
        "current": current,
        "limit": limit,
        "usage_pct": pct,
        "status": (
            "SATURATED" if current >= limit else
            "CRITICAL" if pct >= 90 else
            "WARNING" if pct >= 75 else
            "OK"
        ),
    }


def is_response_timeout(metric: dict) -> bool:
    """True if response_time >= 30000ms."""
    return metric.get("response_time", 0) >= RESPONSE_TIME_THRESHOLDS["dead"]


def get_response_time_state(metric: dict) -> str:
    """Returns: OK / SLOW / TIMEOUT / DEAD"""
    rt = metric.get("response_time", 0)
    if rt >= RESPONSE_TIME_THRESHOLDS["dead"]:
        return "DEAD"
    if rt >= RESPONSE_TIME_THRESHOLDS["timeout"]:
        return "TIMEOUT"
    if rt >= RESPONSE_TIME_THRESHOLDS["slow"]:
        return "SLOW"
    return "OK"


def get_server_state(server_name: str, metric: dict) -> dict:
    """
    Returns {
        state: UP/SLOW/DEGRADED/CRITICAL/TIMEOUT/SATURATED/DOWN,
        reasons: [list of specific metric problems]
    }
    """
    reasons = []
    state = "UP"

    # 1. Availability
    if not metric.get("available", True):
        return {
            "state": "DOWN",
            "reasons": ["Server unreachable - not responding to health checks"],
        }

    # 2. Connection saturation (per-server limit)
    limit = SERVER_CONNECTION_LIMITS.get(server_name, 1000)
    current_conn = metric.get("connections", 0)
    if current_conn >= limit:
        reasons.append(
            f"Connections {current_conn}/{limit} (100%) - "
            f"Too many open files. New connections refused. Removed from pool."
        )
        state = "SATURATED"

    # 3. Response time
    rt = metric.get("response_time", 0)
    if rt >= RESPONSE_TIME_THRESHOLDS["dead"]:
        reasons.append(
            f"Response time {rt}ms >= 30,000ms - "
            f"Server deadlocked or crashed. 504 Gateway Timeout."
        )
        state = "DOWN"
    elif rt >= RESPONSE_TIME_THRESHOLDS["timeout"]:
        reasons.append(
            f"Response time {rt}ms >= 10,000ms - "
            f"Severe degradation. Routing as last resort only."
        )
        if state == "UP":
            state = "TIMEOUT"
    elif rt >= RESPONSE_TIME_THRESHOLDS["slow"]:
        reasons.append(
            f"Response time {rt}ms >= 5,000ms - Slow server. Routing with warning."
        )
        if state == "UP":
            state = "SLOW"

    # 4. CPU
    cpu = metric.get("cpu", 0)
    if cpu >= 100.0:
        reasons.append(
            f"CPU {cpu}% - Fully saturated. No new connections accepted."
        )
        state = "DOWN"
    elif cpu >= OVERLOAD_LIMITS.get("cpu", 90):
        reasons.append(
            f"CPU {cpu}% >= {OVERLOAD_LIMITS['cpu']}% - Overloaded."
        )
        if state == "UP":
            state = "DOWN"

    # 5. Memory
    memory = metric.get("memory", 0)
    if memory >= OVERLOAD_LIMITS.get("memory", 90):
        reasons.append(
            f"Memory {memory}% >= {OVERLOAD_LIMITS['memory']}% - Overloaded."
        )
        if state == "UP":
            state = "DOWN"

    # 6. Latency
    latency = metric.get("latency", 0)
    if latency >= LATENCY_THRESHOLDS["unreachable"]:
        reasons.append(
            f"Latency {latency}ms >= 500ms - "
            f"TCP handshake timeout. Server marked offline."
        )
        state = "DOWN"
    elif latency >= LATENCY_THRESHOLDS["critical"]:
        reasons.append(
            f"Latency {latency}ms >= {LATENCY_THRESHOLDS['critical']}ms - Critical degradation."
        )
        if state == "UP":
            state = "CRITICAL"
    elif latency >= LATENCY_THRESHOLDS["degraded"]:
        reasons.append(
            f"Latency {latency}ms >= {LATENCY_THRESHOLDS['degraded']}ms - Degraded performance."
        )
        if state == "UP":
            state = "DEGRADED"

    # 7. Connection warning levels (not yet saturated)
    if current_conn < limit:
        usage_pct = (current_conn / limit) * 100
        if usage_pct >= 90:
            reasons.append(
                f"Connections {current_conn}/{limit} ({usage_pct:.0f}%) - "
                f"Critical. Risk of saturation."
            )
            if state == "UP":
                state = "CRITICAL"
        elif usage_pct >= 75:
            reasons.append(
                f"Connections {current_conn}/{limit} ({usage_pct:.0f}%) - "
                f"Warning. Approaching limit."
            )
            if state == "UP":
                state = "DEGRADED"

    return {
        "state": state,
        "reasons": reasons if reasons else ["All metrics nominal"],
    }


def check_cascade_risk(server_name: str, metric: dict) -> bool:
    """True if this server is above 80% of its own connection limit."""
    from config import CASCADE_RISK_THRESHOLD

    limit = SERVER_CONNECTION_LIMITS.get(server_name, 1000)
    current = metric.get("connections", 0)
    return (current / limit) >= CASCADE_RISK_THRESHOLD


def all_servers_overloaded(metrics: dict) -> bool:
    return all(is_overloaded(m, name) for name, m in metrics.items())


# ── Fault-Tolerance / Failover Logic ──────────────────────────────────────────

# States that mean a server cannot accept traffic.
_DEAD_STATES = frozenset({"DOWN", "SATURATED"})

# States where the server can still serve but we prefer alternatives.
_DEGRADED_STATES = frozenset({"SLOW", "DEGRADED", "CRITICAL", "TIMEOUT"})


def score_server_health(server_name: str, metric: dict) -> float:
    """
    Returns a composite health score (lower = healthier) used to rank
    candidate failover targets.  Healthy server ≈ 0, fully dead ≈ 1000.
    """
    state_info = get_server_state(server_name, metric)
    state = state_info["state"]

    if state in _DEAD_STATES:
        return 1000.0          # Do not route to this server.

    # Base penalty from state
    state_penalty = {
        "UP":       0.0,
        "SLOW":    25.0,
        "DEGRADED":35.0,
        "CRITICAL":50.0,
        "TIMEOUT": 75.0,
    }.get(state, 0.0)

    cpu    = metric.get("cpu", 0)
    memory = metric.get("memory", 0)
    lat    = metric.get("latency", 0)
    rt     = metric.get("response_time", 0)
    limit  = SERVER_CONNECTION_LIMITS.get(server_name, 1000)
    conn_pct = (metric.get("connections", 0) / limit) * 100

    # Weighted composite: CPU and RT dominate.
    score = (
        state_penalty
        + cpu * 0.4
        + memory * 0.2
        + conn_pct * 0.2
        + min(lat, 500) * 0.1
        + min(rt, 5000) * 0.01
    )
    return round(score, 2)


def failover_route(
    selected_server: str,
    servers: dict[str, dict],
) -> dict:
    """
    Fault-tolerant routing decision (simulation – no real network calls).

    Tries ``selected_server`` first.  If it is DOWN/SATURATED it
    falls back to the remaining servers ranked by ``score_server_health``.

    Returns a dict with:
      - routed_server       : the server that will actually handle the request
      - fallback_used       : True if the primary was bypassed
      - failover_chain      : ordered list of attempts with state + reason
      - fault_tolerance_log : human-readable summary
    """
    # Build health scores for ALL servers
    scored = {
        name: score_server_health(name, metric)
        for name, metric in servers.items()
    }

    # Ordered attempt list: primary first, then remaining sorted by score
    others = sorted(
        [n for n in servers if n != selected_server],
        key=lambda n: scored[n],
    )
    attempt_order = [selected_server] + others

    failover_chain = []
    routed_server  = None
    fallback_used  = False

    for idx, server in enumerate(attempt_order):
        state_info = get_server_state(server, servers[server])
        state      = state_info["state"]
        score      = scored[server]
        is_primary = idx == 0

        if state in _DEAD_STATES:
            failover_chain.append({
                "attempt"  : idx + 1,
                "server"   : server,
                "state"    : state,
                "score"    : score,
                "outcome"  : "FAILED",
                "reasons"  : state_info["reasons"],
                "action"   : "Server removed from pool – rerouting" if is_primary else "Server also unavailable – skipped",
            })
            continue

        # Server is routable (UP / SLOW / DEGRADED / CRITICAL / TIMEOUT)
        outcome = "PRIMARY" if is_primary else "FAILOVER"
        fallback_used = not is_primary
        routed_server = server
        failover_chain.append({
            "attempt": idx + 1,
            "server" : server,
            "state"  : state,
            "score"  : score,
            "outcome": outcome,
            "reasons": state_info["reasons"],
            "action" : "Request routed here" if is_primary else f"Failover to {server} (attempt {idx + 1})",
        })
        break

    # All servers are dead
    if routed_server is None:
        routed_server = selected_server   # keep original for record-keeping
        fault_log = (
            "CLUSTER DOWN – All servers failed health checks. "
            "No viable failover target found."
        )
    elif fallback_used:
        failed_primary = failover_chain[0]["server"]
        fault_log = (
            f"FAULT DETECTED on {failed_primary} ({failover_chain[0]['state']}). "
            f"Traffic automatically rerouted to {routed_server} after "
            f"{sum(1 for e in failover_chain if e['outcome'] == 'FAILED')} failed attempt(s)."
        )
    else:
        fault_log = (
            f"Primary server {routed_server} is healthy. "
            f"No failover required."
        )

    return {
        "routed_server"       : routed_server,
        "original_selection"  : selected_server,
        "fallback_used"       : fallback_used,
        "failover_chain"      : failover_chain,
        "fault_tolerance_log" : fault_log,
        "server_scores"       : scored,
    }


# ── Legacy helpers kept for backward-compatibility ────────────────────────────

def forward_request(selected_server: str, payload: dict, metrics: dict) -> dict:
    route = _choose_route(selected_server, metrics)
    attempts = [route]

    if route != FALLBACK_SERVER:
        attempts.append(FALLBACK_SERVER)

    errors = []
    for server in attempts:
        try:
            response = requests.post(
                f"{SERVER_URLS[server]}/process",
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return {
                "requested_server": selected_server,
                "routed_server": server,
                "fallback_used": server != selected_server,
                "backend_response": response.json(),
            }
        except requests.RequestException as exc:
            errors.append({"server": server, "error": str(exc)})

    raise RuntimeError(f"All backend routes failed: {errors}")


def _choose_route(selected_server: str, metrics: dict) -> str:
    selected_metric = metrics.get(selected_server, {})
    result = get_server_state(selected_server, selected_metric)
    if result["state"] in ("DOWN", "SATURATED"):
        return FALLBACK_SERVER
    return selected_server
