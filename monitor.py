"""Fetch live metrics from all backend servers."""

from __future__ import annotations

import requests

from config import REQUEST_TIMEOUT_SECONDS, SERVER_URLS


def fetch_server_metrics() -> dict:
    metrics = {}
    for name, url in SERVER_URLS.items():
        try:
            response = requests.get(f"{url}/metrics", timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            data["available"] = True
            data["url"] = url
            metrics[name] = data
        except requests.RequestException as exc:
            metrics[name] = {
                "server": name,
                "available": False,
                "url": url,
                "error": str(exc),
                "cpu": 100.0,
                "memory": 100.0,
                "connections": 9999,
                "latency": 9999.0,
                "response_time": 9999.0,
            }
    return metrics


def routing_features(metrics: dict) -> dict:
    """Build one feature vector for the existing A/B ML selector."""
    available = [
        m for name, m in metrics.items()
        if m.get("available") and m.get("cpu", 100) < 100.0
    ]
    if not available:
        return {
            "cpu": 100.0,
            "memory": 100.0,
            "connections": 9999,
            "latency": 9999.0,
            "response_time": 9999.0,
        }

    return {
        "cpu": sum(m["cpu"] for m in available) / len(available),
        "memory": sum(m["memory"] for m in available) / len(available),
        "connections": int(sum(m["connections"] for m in available) / len(available)),
        "latency": sum(m["latency"] for m in available) / len(available),
        "response_time": sum(m["response_time"] for m in available) / len(available),
    }
