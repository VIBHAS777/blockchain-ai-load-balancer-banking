"""
Flask REST API for the AI decision simulator + blockchain backend.

Endpoints:
  POST /api/send          -> simulated transaction flow
  GET  /api/transactions  -> list all transactions
  GET  /api/transaction/<id> -> single record
  POST /api/verify        -> dispute / verify a tx
  GET  /api/algorithms    -> compare server selection algorithms
  POST /api/anomaly-check -> anomaly check only
  GET  /api/blockchain    -> view chain
  GET  /api/stats         -> dashboard KPIs
"""

import os
import sys
import time
from datetime import UTC, datetime

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

from ai_engine import _tx_id, detect_anomaly, evaluate_all_algorithms, select_best_server
from blockchain.ledger import Blockchain
from config import OVERLOAD_LIMITS, SERVER_CONNECTION_LIMITS, RESPONSE_TIME_THRESHOLDS, LATENCY_THRESHOLDS
from database import db
from router import failover_route, get_server_state

app = Flask(__name__)
CORS(app)

chain = Blockchain()
LOG: list = []

SERVER_FIELD_MAP = {
    "Server-A": {
        "cpu": "cpu_A",
        "memory": "memory_A",
        "latency": "latency_A",
        "connections": "conn_A",
        "response_time": "response_time_A",
    },
    "Server-B": {
        "cpu": "cpu_B",
        "memory": "memory_B",
        "latency": "latency_B",
        "connections": "conn_B",
        "response_time": "response_time_B",
    },
    "Server-C": {
        "cpu": "cpu_C",
        "memory": "memory_C",
        "latency": "latency_C",
        "connections": "conn_C",
        "response_time": "response_time_C",
    },
}

DEFAULT_METRICS = {
    "cpu_A": 65,
    "memory_A": 50,
    "latency_A": 80,
    "conn_A": 60,
    "response_time_A": 110,
    "cpu_B": 40,
    "memory_B": 70,
    "latency_B": 60,
    "conn_B": 55,
    "response_time_B": 90,
    "cpu_C": 30,
    "memory_C": 40,
    "latency_C": 50,
    "conn_C": 45,
    "response_time_C": 75,
}


def _log(event: str, detail: dict):
    LOG.append({"ts": datetime.now(UTC).isoformat(), "event": event, **detail})
    if len(LOG) > 500:
        LOG.pop(0)


def _require_float(body: dict, key: str, defaults: dict | None = None) -> float:
    if key not in body and (not defaults or key not in defaults):
        raise KeyError(key)
    raw = body.get(key, defaults[key] if defaults else None)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if value < 0:
        raise ValueError(f"{key} must be zero or greater")
    return value


def _optional_int(body: dict, key: str, default: int = 50, defaults: dict | None = None) -> int:
    value = body.get(key, defaults.get(key, default) if defaults else default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{key} must be zero or greater")
    return parsed


def _optional_float(body: dict, key: str, default: float, defaults: dict | None = None) -> float:
    value = body.get(key, defaults.get(key, default) if defaults else default)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if parsed < 0:
        raise ValueError(f"{key} must be zero or greater")
    return parsed


def _build_servers(body: dict, *, use_defaults: bool = False) -> dict[str, dict]:
    servers: dict[str, dict] = {}
    defaults = DEFAULT_METRICS if use_defaults else None

    for server_name, keys in SERVER_FIELD_MAP.items():
        cpu = _require_float(body, keys["cpu"], defaults)
        memory = _require_float(body, keys["memory"], defaults)
        latency = _require_float(body, keys["latency"], defaults)
        connections = _optional_int(body, keys["connections"], defaults=defaults)
        response_time = _optional_float(body, keys["response_time"], latency, defaults=defaults)
        servers[server_name] = {
            "cpu": cpu,
            "memory": memory,
            "latency": latency,
            "connections": connections,
            "response_time": response_time,
        }

    return servers


def _observed_load_signal(servers: dict[str, dict]) -> int:
    return int(sum(server["connections"] for server in servers.values()) / len(servers))


def _server_down_reason(metrics: dict) -> str:
    if max(metrics["latency"], metrics["response_time"]) >= 500:
        return "Latency >= 500ms - LB marks DOWN"
    if metrics["cpu"] >= 100:
        return "CPU 100% - no new connections accepted"
    if (
        metrics["cpu"] >= OVERLOAD_LIMITS["cpu"]
        or metrics["memory"] >= OVERLOAD_LIMITS["memory"]
        or metrics["connections"] >= OVERLOAD_LIMITS["connections"]
    ):
        return "Resource overload - LB marks DOWN"
    return "Server unavailable - LB marks DOWN"


def _recompute_record_hash(record: dict) -> str:
    return chain.compute_tx_hash(
        record["tx_id"],
        record["sender"],
        record["receiver"],
        record["amount"],
        record["timestamp"],
        record.get("status", ""),
        record.get("server", ""),
    )


def _metadata_mismatches(record: dict, metadata: dict | None) -> list[str]:
    if not metadata:
        return []

    mismatches: list[str] = []
    for field in ("tx_id", "status", "server"):
        expected = metadata.get(field)
        if expected is not None and record.get(field) != expected:
            mismatches.append(field)
    return mismatches


@app.route("/")
def home():
    return render_template("dashboard.html")


@app.route("/algorithms")
def algorithms_page():
    return render_template("algorithms.html")


@app.route("/api/send", methods=["POST"])
def send_transaction():
    body = request.get_json(force=True) or {}
    sender = body.get("sender", "").strip()
    receiver = body.get("receiver", "").strip()

    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be numeric"}), 400

    if not sender or not receiver:
        return jsonify({"error": "sender and receiver are required"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be positive"}), 400

    try:
        t0 = time.perf_counter()
        servers = _build_servers(body)
        metrics_ms = round((time.perf_counter() - t0) * 1000, 2)
    except KeyError as exc:
        return jsonify({"error": f"missing required metric: {exc.args[0]}"}), 400
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    step_timings = {"metrics_ms": metrics_ms}

    # ── Per-server connection limit + latency check ───────────────────
    from router import check_cascade_risk, failover_route, get_server_state

    server_states = {}
    connection_stats = {}
    server_detail = {}
    cascade_risks = []

    for name, s in servers.items():
        result = get_server_state(name, s)
        state = result["state"]
        reasons = result["reasons"]

        limit = SERVER_CONNECTION_LIMITS.get(name, 1000)
        current_conn = s.get("connections", 0)
        usage_pct = round((current_conn / limit) * 100, 1)

        conn_status = (
            "SATURATED" if current_conn >= limit else
            "CRITICAL" if usage_pct >= 90 else
            "WARNING" if usage_pct >= 75 else
            "OK"
        )

        server_states[name] = state
        connection_stats[name] = {
            "current": current_conn,
            "limit": limit,
            "usage_pct": usage_pct,
            "status": conn_status,
        }
        server_detail[name] = {
            "state": state,
            "cpu": s["cpu"],
            "memory": s["memory"],
            "latency": s["latency"],
            "response_time": s["response_time"],
            "connections": connection_stats[name],
            "reasons": reasons,
        }

        if state not in ("DOWN", "SATURATED") and check_cascade_risk(name, s):
            cascade_risks.append(name)

    live_servers = [
        name for name, state in server_states.items()
        if state not in ("DOWN", "SATURATED")
    ]

    # Build per-server detail for error responses
    server_detail = server_detail
    for name in ():
        s = servers[name]
        limit = SERVER_CONNECTION_LIMITS.get(name, 1000)
        latency_val = max(s["latency"], s["response_time"])
        rt = s["response_time"]
        reasons = []

        if server_states[name] == "SATURATED":
            reasons.append(
                f"Connections {s['connections']}/{limit} — "
                f"Too many open files. Connection refused. Removed from pool."
            )
        if s["cpu"] >= 100.0:
            reasons.append("CPU 100% — no new connections accepted")
        if rt >= RESPONSE_TIME_THRESHOLDS["dead"]:
            reasons.append(
                f"Response time {rt}ms ≥ 30000ms — "
                f"Server deadlocked or crashed. 504 Gateway Timeout. "
                f"Marked DOWN immediately."
            )
        elif rt >= RESPONSE_TIME_THRESHOLDS["timeout"]:
            reasons.append(
                f"Response time {rt}ms ≥ 10000ms — "
                f"Severe degradation. Last resort routing only."
            )
        elif rt >= RESPONSE_TIME_THRESHOLDS["slow"]:
            reasons.append(
                f"Response time {rt}ms ≥ 5000ms — "
                f"Slow server. Routing with warning."
            )
        if latency_val >= LATENCY_THRESHOLDS["unreachable"]:
            reasons.append(
                f"Latency {latency_val}ms ≥ 500ms — TCP timeout. Marked offline."
            )

        server_detail[name] = {
            "state":       server_states[name],
            "cpu":         s["cpu"],
            "latency":     latency_val,
            "response_time": rt,
            "connections": connection_stats[name],
            "reason":      "; ".join(reasons) if reasons else "OK"
        }

    if len(live_servers) == 0:
        # Check if any server specifically died due to response timeout → 504
        timeout_servers = [
            name for name in servers
            if servers[name]["response_time"] >= RESPONSE_TIME_THRESHOLDS["dead"]
        ]
        error_code = 504 if timeout_servers else 503
        error_msg  = (
            "504 Gateway Timeout — All servers timed out (response ≥ 30s). "
            "Servers may be deadlocked or crashed."
            if timeout_servers else
            "503 Service Unavailable — All servers removed from pool."
        )

        _log(
            "TRANSACTION_DROPPED",
            {
                "reason": "all servers down",
                "status": str(error_code),
            },
        )
        return jsonify({
            "success": False,
            "error": "504 Gateway Timeout" if timeout_servers else "503 Service Unavailable",
            "http_code": error_code,
            "cluster_status": "DOWN",
            "reason": "All servers removed from pool. See per-server reasons below.",
            "servers": server_detail,
            "performance": step_timings,
        }), error_code

    # Cascade risk warning (attached to successful responses too)
    cascade_warning = None
    if cascade_risks:
        cascade_warning = (
            f"⚠️ Cascade risk: {', '.join(cascade_risks)} are above 80% of their "
            f"connection limits. If remaining servers fail, cluster goes down."
        )
    # ─────────────────────────────────────────────────────────────────

    t0 = time.perf_counter()
    observed_requests = _observed_load_signal(servers)
    anomaly = detect_anomaly(
        requests_per_min=observed_requests,
        failed_logins=body.get("failed_logins", 0),
        ip_change=body.get("ip_change", 0),
        device_change=body.get("device_change", 0),
        transaction_amount=amount,
    )
    step_timings["anomaly_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    t0 = time.perf_counter()
    selection = select_best_server(servers)
    step_timings["routing_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    status = "BLOCKED" if anomaly["action"] == "BLOCK" else "SUCCESS"

    # ── Fault-Tolerance: reroute if the AI-selected server is unhealthy ───────
    t0 = time.perf_counter()
    ai_selected = selection["selected_server"]
    fault_result = failover_route(ai_selected, servers)
    final_server = fault_result["routed_server"]
    step_timings["failover_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    # ─────────────────────────────────────────────────────────────────────────

    t0 = time.perf_counter()
    routing = {
        "mode": "simulation",
        "decision_only": True,
        "executed": False,
        "selected_server": final_server,
        "original_ai_selection": ai_selected,
        "fallback_used": fault_result["fallback_used"],
        "message": (
            "No live backend server call was made. This project now simulates the routing decision in code."
        ),
    }
    step_timings["simulation_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    timestamp = datetime.now(UTC).isoformat()
    # Use the fault-tolerance resolved server (may differ from AI selection)
    selected_server = final_server

    t0 = time.perf_counter()
    tx_id = _tx_id()
    chain_result = chain.add_transaction(
        tx_id=tx_id,
        sender=sender,
        receiver=receiver,
        amount=amount,
        timestamp=timestamp,
        extra={
            "server": selected_server,
            "status": status,
            "ai_selected": ai_selected,
            "failover": fault_result["fallback_used"],
        },
    )
    step_timings["blockchain_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    record = db.insert(
        sender=sender,
        receiver=receiver,
        amount=amount,
        server=selected_server,
        anomaly=anomaly["is_anomaly"],
        risk_score=anomaly["risk_score"],
        block_index=chain_result["block_index"],
        tx_hash=chain_result["tx_hash"],
        status=status,
        timestamp=timestamp,
        tx_id=tx_id,
    )

    _log(
        "TRANSACTION",
        {
            "tx_id": tx_id,
            "status": status,
            "server": selected_server,
            "ai_selected": ai_selected,
            "failover": fault_result["fallback_used"],
            "decision_mode": selection["decision_mode"],
        },
    )

    total_ms = round(sum(step_timings.values()), 2)

    return jsonify({
        "success": True,
        "transaction": record,
        "ai_decisions": {
            "observed_metrics_signal": {
                "requests_per_min": observed_requests,
                "source": "average active connections from submitted server metrics",
            },
            "server_selection": selection,
            "server_metrics": servers[selected_server],
            "all_server_metrics": servers,
            "server_health": {
                name: {
                    "state": server_states[name],
                    "cpu": servers[name]["cpu"],
                    "memory": servers[name]["memory"],
                    "latency": servers[name]["latency"],
                    "response_time": servers[name]["response_time"],
                    "connections": connection_stats[name],
                    "reasons": server_detail[name]["reasons"],
                }
                for name in servers
            },
            "cascade_warning": cascade_warning,
            "anomaly_detection": anomaly,
        },
        "fault_tolerance": {
            "ai_selected": ai_selected,
            "routed_server": final_server,
            "fallback_used": fault_result["fallback_used"],
            "failover_chain": fault_result["failover_chain"],
            "fault_tolerance_log": fault_result["fault_tolerance_log"],
            "server_scores": fault_result["server_scores"],
        },
        "routing": routing,
        "blockchain": chain_result,
        "performance": {**step_timings, "total_ms": total_ms},
    })


@app.route("/api/transactions", methods=["GET"])
def list_transactions():
    return jsonify({"transactions": db.all(), "stats": db.stats()})


@app.route("/api/transaction/<tx_id>", methods=["GET"])
def get_transaction(tx_id):
    record = db.get(tx_id)
    if not record:
        return jsonify({"error": "not found"}), 404
    return jsonify(record)


@app.route("/api/verify", methods=["POST"])
def verify_transaction():
    body = request.get_json(force=True) or {}
    tx_hash = body.get("tx_hash", "").strip()
    tx_id = body.get("tx_id", "").strip()

    db_record = None
    if tx_id:
        db_record = db.get(tx_id)
        if not db_record:
            return jsonify({"error": "tx_id not found"}), 404
        tx_hash = db_record.get("tx_hash", "").strip()

    if not tx_hash:
        return jsonify({"error": "tx_hash or tx_id is required"}), 400
    if len(tx_hash) != 64:
        return jsonify({"error": "Invalid tx_hash - must be 64 hex characters"}), 400

    chain_record = chain.verify_by_hash(tx_hash)
    db_record = db_record or db.get_by_hash(tx_hash)
    recomputed_hash = _recompute_record_hash(db_record) if db_record else None
    integrity_ok = bool(chain_record["valid"] and db_record and recomputed_hash == tx_hash)
    mismatched_fields = (
        _metadata_mismatches(db_record, chain_record.get("metadata"))
        if db_record and chain_record["valid"]
        else []
    )

    if not chain_record["valid"]:
        verdict = "INVALID - Hash not found on blockchain"
    elif not db_record:
        verdict = "INVALID - Blockchain record exists, but the database record is missing"
    elif integrity_ok:
        verdict = "VALID - Current database values still match the blockchain"
    else:
        verdict = "TAMPERED - Current database values do not match the blockchain"

    return jsonify({
        "tx_hash": tx_hash,
        "tx_id": db_record.get("tx_id") if db_record else tx_id or None,
        "chain": chain_record,
        "db_record": db_record,
        "recomputed_hash": recomputed_hash,
        "integrity_ok": integrity_ok,
        "mismatched_fields": mismatched_fields,
        "verdict": verdict,
    })


@app.route("/api/algorithms", methods=["GET"])
def algorithms():
    try:
        servers = _build_servers(request.args.to_dict(), use_defaults=True)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    from router import get_server_state

    server_health = {}
    live_servers = []

    for name, s in servers.items():
        result = get_server_state(name, s)
        server_health[name] = {
            "state": result["state"],
            "reasons": result["reasons"],
        }
        if result["state"] not in ("DOWN", "SATURATED"):
            live_servers.append(name)

    client_ip = request.args.get("client_ip")

    if not live_servers:
        return jsonify({
            "cluster_status": "DOWN",
            "client_ip": client_ip,
            "server_metrics": servers,
            "server_health": server_health,
            "algorithms": None,
            "error": "No live servers - see server_health for per-server breakdown",
        }), 503

    try:
        results = evaluate_all_algorithms(servers, client_ip=client_ip)
    except ValueError as exc:
        return jsonify({
            "error": str(exc),
            "cluster_status": "DEGRADED",
            "server_health": server_health,
        }), 400
    except RuntimeError as exc:
        return jsonify({
            "error": str(exc),
            "cluster_status": "DEGRADED",
            "server_health": server_health,
        }), 503

    return jsonify({
        "client_ip": client_ip,
        "server_metrics": servers,
        "cluster_status": "OK" if len(live_servers) == 3 else "DEGRADED",
        "server_health": server_health,
        "algorithms": results,
    })


@app.route("/api/anomaly-check", methods=["POST"])
def anomaly_check():
    body = request.get_json(force=True)
    result = detect_anomaly(
        requests_per_min=body.get("requests_per_min", 10),
        failed_logins=body.get("failed_logins", 0),
        ip_change=body.get("ip_change", 0),
        device_change=body.get("device_change", 0),
        transaction_amount=body.get("transaction_amount", 1000),
    )
    return jsonify(result)


@app.route("/api/blockchain", methods=["GET"])
def get_chain():
    limit = int(request.args.get("limit", 20))
    full_chain = chain.get_chain()
    return jsonify({
        "stats": chain.stats(),
        "chain": full_chain[-limit:][::-1],
    })


@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify({
        "transactions": db.stats(),
        "blockchain": chain.stats(),
        "audit_log": LOG[-10:],
    })


@app.route("/api/log", methods=["GET"])
def audit_log():
    return jsonify({"log": LOG[-50:][::-1]})


if __name__ == "__main__":
    print("\nAI Decision Simulator + Blockchain API")
    print("Running on http://localhost:5050\n")
    app.run(port=5050, debug=False)
