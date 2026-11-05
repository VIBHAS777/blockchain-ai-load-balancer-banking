"""
AI decision engine for the blockchain load balancer demo.

Exposes:
  - select_best_server(servers) -> dict
  - evaluate_all_algorithms(servers, client_ip=None) -> dict
  - detect_anomaly(requests_per_min, failed_logins, ip_change,
                   device_change, transaction_amount) -> dict
"""

import os
import random
import string

import joblib
import pandas as pd

from router import get_server_state

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(BASE, "models")

SERVER_PROFILES = {
    "Server-A": {"region": "ap-south-1", "role": "primary"},
    "Server-B": {"region": "ap-south-2", "role": "primary"},
    "Server-C": {"region": "us-east-1", "role": "fallback"},
}


def _load(name: str):
    path = os.path.join(MODELS, name)
    return joblib.load(path)


_anomaly_model = None
_server_model = None
_label_encoder = None
_server_features = None
_scaler = None
_round_robin_index = 0


def _get_anomaly_model():
    global _anomaly_model
    if _anomaly_model is None:
        _anomaly_model = _load("anomaly_detector.pkl")
    return _anomaly_model


def _get_server_model_bundle():
    global _server_model, _label_encoder, _server_features, _scaler
    if _server_model is None:
        _server_model = _load("model.pkl")
    if _label_encoder is None:
        _label_encoder = _load("label_encoder.pkl")
    if _scaler is None:
        _scaler = _load("scaler.pkl")
    if _server_features is None:
        path = os.path.join(MODELS, "feature_cols.csv")
        if os.path.exists(path):
            _server_features = pd.read_csv(path, header=None)[0].astype(str).tolist()
        elif hasattr(_scaler, "feature_names_in_"):
            _server_features = list(_scaler.feature_names_in_)
        else:
            raise FileNotFoundError("models/feature_cols.csv is required for server inference")
    return _server_model, _label_encoder, _server_features, _scaler


def _label_to_server_name(label) -> str:
    label_text = str(label)
    if label_text.startswith("Server-"):
        return label_text
    return f"Server-{label_text.upper()}"


def _feature_value(feature: str, servers: dict[str, dict]) -> float:
    metric_name, separator, suffix = feature.rpartition("_")
    if not separator:
        return 0.0

    server_name = f"Server-{suffix.upper()}"
    metrics = servers.get(server_name, {})
    aliases = {
        "conn": "connections",
        "latency_ms": "latency",
        "response_time_ms": "response_time",
    }
    metric_key = aliases.get(metric_name, metric_name)
    return float(metrics.get(metric_key, 0))


def _server_names(servers: dict[str, dict]) -> list[str]:
    if not servers:
        raise ValueError("At least one server is required for selection")
    return list(servers.keys())


def round_robin(servers: dict[str, dict]) -> dict:
    global _round_robin_index
    names = _server_names(servers)
    selected = names[_round_robin_index % len(names)]
    _round_robin_index += 1

    return {
        "selected_server": selected,
        "reason": "Next server in rotation",
        "decision_mode": "round-robin",
    }


def least_connections(servers: dict[str, dict]) -> dict:
    _server_names(servers)
    selected = min(servers, key=lambda name: servers[name].get("connections", 0))
    return {
        "selected_server": selected,
        "reason": f"Lowest active connections ({servers[selected].get('connections', 0)})",
        "decision_mode": "least-connections",
    }


def ip_hash(servers: dict[str, dict], client_ip: str | None = None) -> dict:
    from router import hash_ip_to_server, validate_ip

    _server_names(servers)
    ip = validate_ip(client_ip or "")

    live_servers = [
        name for name, metrics in servers.items()
        if get_server_state(name, metrics)["state"] not in ("DOWN", "SATURATED", "TIMEOUT")
    ]
    if not live_servers:
        raise RuntimeError("No live servers available for IP hash routing.")

    selected = hash_ip_to_server(ip, live_servers)

    return {
        "selected_server": selected,
        "reason": f"SHA-256 hash of IP {ip} mapped to {selected} ({len(live_servers)} live servers).",
        "decision_mode": "ip-hash",
    }


def cpu_based(servers: dict[str, dict]) -> dict:
    _server_names(servers)
    selected = min(servers, key=lambda name: servers[name].get("cpu", 0))
    return {
        "selected_server": selected,
        "reason": f"Lowest CPU usage ({servers[selected].get('cpu', 0)}%)",
        "decision_mode": "cpu-based",
    }


def ai_model_predict(servers: dict[str, dict]) -> dict:
    _server_names(servers)
    from config import LATENCY_THRESHOLDS, SERVER_CONNECTION_LIMITS, RESPONSE_TIME_THRESHOLDS

    live_servers = {}
    for name, metrics in servers.items():
        limit = SERVER_CONNECTION_LIMITS.get(name, 1000)
        latency_ok = metrics.get("latency", 0) < LATENCY_THRESHOLDS["unreachable"]
        cpu_ok = metrics.get("cpu", 100) < 100.0
        conn_ok = metrics.get("connections", 0) < limit
        rt_ok = metrics.get("response_time", 0) < RESPONSE_TIME_THRESHOLDS["dead"]

        if latency_ok and cpu_ok and conn_ok and rt_ok:
            live_servers[name] = metrics

    if not live_servers:
        raise RuntimeError(
            "No routable servers — all are saturated, overloaded, "
            "unreachable, or timed out (≥30s response time)"
        )
    servers = live_servers

    model, encoder, features, scaler = _get_server_model_bundle()

    row = {feature: _feature_value(feature, servers) for feature in features}
    frame = pd.DataFrame([row], columns=features)
    frame_scaled = scaler.transform(frame)

    prediction = model.predict(frame_scaled)[0]
    selected = _label_to_server_name(encoder.inverse_transform([prediction])[0])
    probabilities = model.predict_proba(frame_scaled)[0] if hasattr(model, "predict_proba") else None

    candidates = []
    probability_by_server = {}
    if probabilities is not None:
        for class_index, encoded_label in enumerate(model.classes_):
            server_name = _label_to_server_name(encoder.inverse_transform([encoded_label])[0])
            probability_by_server[server_name] = round(float(probabilities[class_index]) * 100, 1)

    for server_name, metrics in servers.items():
        confidence = 0.0
        if probability_by_server:
            confidence = probability_by_server.get(server_name, 0.0)
        candidates.append({
            "server": server_name,
            "predicted_server": selected,
            "confidence": confidence,
            "metrics": metrics,
        })

    if selected not in servers:
        selected = min(
            servers,
            key=lambda name: (
                servers[name].get("cpu", 0),
                servers[name].get("memory", 0),
                servers[name].get("connections", 0),
                servers[name].get("latency", 0),
                servers[name].get("response_time", 0),
            ),
        )

    confidence = probability_by_server.get(selected, 0.0) if probability_by_server else 0.0

    return {
        "selected_server": selected,
        "confidence": confidence,
        "reason": f"ML classifier prediction using {', '.join(features)}",
        "decision_mode": "ai-model",
        "features": list(features),
        "model_file": "model.pkl",
        "scaler_file": "scaler.pkl",
        "encoder_file": "label_encoder.pkl",
        "feature_file": "feature_cols.csv",
        "candidates": candidates,
    }


def evaluate_all_algorithms(servers: dict[str, dict], client_ip: str | None = None) -> dict:
    return {
        "round_robin": round_robin(servers),
        "least_connections": least_connections(servers),
        "ip_hash": ip_hash(servers, client_ip),
        "cpu_based": cpu_based(servers),
        "ai_model": ai_model_predict(servers),
    }


def select_best_server(servers: dict[str, dict]) -> dict:
    selection = ai_model_predict(servers)
    return {
        **selection,
        "ranking": [
            {
                "server": server_name,
                "profile": SERVER_PROFILES.get(server_name, {}),
                "metrics": metrics,
            }
            for server_name, metrics in servers.items()
        ],
        "explanation": "The selected server comes from model.pkl, scaled with scaler.pkl, decoded with label_encoder.pkl, and ordered by feature_cols.csv.",
    }


def detect_anomaly(
    requests_per_min: int,
    failed_logins: int,
    ip_change: int,
    device_change: int,
    transaction_amount: float,
) -> dict:
    model = _get_anomaly_model()
    frame = pd.DataFrame([{
        "requests_per_min": requests_per_min,
        "failed_logins": failed_logins,
        "ip_change": ip_change,
        "device_change": device_change,
        "transaction_amount": transaction_amount,
    }])
    label = int(model.predict(frame)[0])
    probability = model.predict_proba(frame)[0]
    risk_score = round(float(probability[1]) * 100, 1)
    return {
        "is_anomaly": bool(label),
        "risk_score": risk_score,
        "severity": "HIGH" if risk_score > 75 else "MEDIUM" if risk_score > 40 else "LOW",
        "action": "BLOCK" if label else "ALLOW",
    }


def _tx_id() -> str:
    return "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
