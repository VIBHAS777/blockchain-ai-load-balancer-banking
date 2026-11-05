import os
import sys
import time
from threading import Lock

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from common.metrics import collect_metrics

SERVER_NAME = "Server-B"
PORT = 8002

app = Flask(__name__)
_active_connections = 0
_lock = Lock()


@app.get("/metrics")
def metrics():
    return jsonify(collect_metrics(SERVER_NAME, _active_connections))


@app.post("/process")
def process():
    global _active_connections
    payload = request.get_json(force=True, silent=True) or {}
    with _lock:
        _active_connections += 1
    try:
        time.sleep(0.12)
        return jsonify({
            "processed": True,
            "server": SERVER_NAME,
            "message": "Transaction processed by Server-B",
            "payload": payload,
        })
    finally:
        with _lock:
            _active_connections -= 1


if __name__ == "__main__":
    print(f"{SERVER_NAME} running on http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
