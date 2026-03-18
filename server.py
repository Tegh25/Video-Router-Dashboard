import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

ROUTER_IP = os.getenv("ROUTER_IP", "192.168.1.100")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
CACHE_TTL_SECONDS = 5
NEXXROUTE_COMMAND = "/usr/bin/nexxroute show"

TOKEN_PATTERN = re.compile(r"^(?P<type>[a-z_]+),port(?P<port>\d+),id(?P<id>\d+)$")

app = Flask(__name__)
CORS(app)

# Cache only successful fetches so transient SSH errors do not overwrite usable data.
_cache = {"timestamp": 0.0, "payload": None}
_cache_lock = threading.Lock()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_signal(token: str):
    match = TOKEN_PATTERN.match(token)
    if not match:
        return None

    return {
        "type": match.group("type"),
        "port": int(match.group("port")),
        "id": int(match.group("id")),
    }


def card_from_port(port_id: int) -> int:
    return ((port_id - 1) // 32) + 1


def parse_video_routes(raw_output: str):
    routes = []
    source_set = set()
    destination_set = set()
    card_set = set()

    for raw_line in raw_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 2:
            continue

        dst = parse_signal(parts[0])
        src = parse_signal(parts[1])
        if not dst or not src:
            continue

        if dst["type"] != "vid" or src["type"] != "vid":
            continue

        route = {
            "dst_port": dst["port"],
            "dst_id": dst["id"],
            "dst_card": card_from_port(dst["port"]),
            "src_port": src["port"],
            "src_id": src["id"],
            "src_card": card_from_port(src["port"]),
        }
        routes.append(route)
        source_set.add((src["port"], src["id"]))
        destination_set.add((dst["port"], dst["id"]))
        card_set.add(route["src_card"])
        card_set.add(route["dst_card"])

    sources = [{"port": p, "id": i, "card": card_from_port(p)} for p, i in sorted(source_set)]
    destinations = [{"port": p, "id": i, "card": card_from_port(p)} for p, i in sorted(destination_set)]

    return {
        "routes": routes,
        "sources": sources,
        "destinations": destinations,
        "cards": sorted(card_set),
        "fetched_at": now_utc_iso(),
    }


def run_nexxroute() -> str:
    if not SSH_PASSWORD:
        raise RuntimeError("SSH_PASSWORD is required")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            hostname=ROUTER_IP,
            username=SSH_USER,
            password=SSH_PASSWORD,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )

        _, stdout, stderr = ssh.exec_command(NEXXROUTE_COMMAND, timeout=10)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="replace")
        error_output = stderr.read().decode("utf-8", errors="replace").strip()

        if exit_status != 0:
            message = error_output or f"Command exited with status {exit_status}"
            raise RuntimeError(message)

        return output
    finally:
        ssh.close()


def get_routes_with_cache(force_refresh: bool = False):
    now = time.time()

    with _cache_lock:
        if not force_refresh and _cache["payload"] and (now - _cache["timestamp"] < CACHE_TTL_SECONDS):
            return _cache["payload"]

    fresh_output = run_nexxroute()
    payload = parse_video_routes(fresh_output)

    with _cache_lock:
        _cache["payload"] = payload
        _cache["timestamp"] = time.time()

    return payload


@app.route("/")
def index():
    return send_from_directory(Path(__file__).resolve().parent, "index.html")


@app.route("/styles.css")
def styles():
    return send_from_directory(Path(__file__).resolve().parent, "styles.css")


@app.route("/api/routes/video", methods=["GET"])
def video_routes():
    force_refresh = os.getenv("DISABLE_CACHE", "0") == "1"

    try:
        payload = get_routes_with_cache(force_refresh=force_refresh)
        return jsonify(payload)
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": f"SSH connection failed: {str(exc)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT)
