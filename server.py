import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROUTER_IP = os.getenv("ROUTER_IP", "192.168.1.100")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
CACHE_TTL_SECONDS = 30
NEXXROUTE_COMMAND = "/usr/bin/nexxroute show"
TELNET_PORT = int(os.getenv("TELNET_PORT", "9654"))

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
        "cge": int(match.group("port")),
        "ch": int(match.group("id")),
    }


def card_from_cge(cge: int) -> int:
    return ((cge - 1) // 4) + 1


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
            "dst_cge": dst["cge"],
            "dst_ch": dst["ch"],
            "dst_card": card_from_cge(dst["cge"]),
            "src_cge": src["cge"],
            "src_ch": src["ch"],
            "src_card": card_from_cge(src["cge"]),
        }
        routes.append(route)
        source_set.add((src["cge"], src["ch"]))
        destination_set.add((dst["cge"], dst["ch"]))
        card_set.add(route["src_card"])
        card_set.add(route["dst_card"])

    sources = [{"cge": c, "ch": ch, "card": card_from_cge(c)} for c, ch in sorted(source_set)]
    destinations = [{"cge": c, "ch": ch, "card": card_from_cge(c)} for c, ch in sorted(destination_set)]

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


def invalidate_cache():
    """Clear the route cache so the next read fetches fresh data."""
    with _cache_lock:
        _cache["timestamp"] = 0.0


def set_video_route(dest: int, src: int) -> str:
    """SSH to the router, open telnet to the control port, and send an SV command."""
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

        # Use an interactive shell for the telnet session
        shell = ssh.invoke_shell()
        time.sleep(0.5)

        # Drain any login banner
        if shell.recv_ready():
            shell.recv(4096)

        # Open telnet to the router control port
        shell.send(f"telnet localhost {TELNET_PORT}\n".encode())
        time.sleep(1.0)

        # Drain telnet connection banner
        if shell.recv_ready():
            shell.recv(4096)

        # Send the set-video-route command
        sv_command = f".SV{dest},{src}\n"
        shell.send(sv_command.encode())
        time.sleep(1.0)

        # Collect the response
        response = ""
        if shell.recv_ready():
            response = shell.recv(4096).decode("utf-8", errors="replace")

        # Exit telnet
        shell.send(b"quit\n")
        time.sleep(0.3)

        shell.close()
        return response.strip()
    finally:
        ssh.close()


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


@app.route("/api/routes/video/set", methods=["POST"])
def set_route():
    """Set a video route on the router.

    Expects JSON body: {"dest": <int>, "src": <int>}
    where dest and src are the port ID numbers used in the .SV command.
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Request body must be JSON"}), 400

    dest = body.get("dest")
    src = body.get("src")

    if dest is None or src is None:
        return jsonify({"error": "Both 'dest' and 'src' are required"}), 400

    try:
        dest = int(dest)
        src = int(src)
    except (TypeError, ValueError):
        return jsonify({"error": "'dest' and 'src' must be integers"}), 400

    try:
        response = set_video_route(dest, src)
        invalidate_cache()
        return jsonify({
            "ok": True,
            "command": f".SV{dest},{src}",
            "response": response,
            "timestamp": now_utc_iso(),
        })
    except Exception as exc:  # pylint: disable=broad-except
        return jsonify({"error": f"Failed to set route: {str(exc)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT)
