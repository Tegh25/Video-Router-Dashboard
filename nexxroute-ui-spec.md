# Nexxroute Video Router UI — Project Specification

## Project Overview

Build a web-based UI tool that SSHes into a broadcast router (NEXX-XC1), runs the `nexxroute show` CLI command, parses the **video (`vid`) routes** from the output, and displays them in an interactive routing matrix. The tool is hosted on a Linux server in the same local network as the router.

---

## Architecture

```
[ NEXX-XC1 Router ]  ←  SSH  ←  [ Linux App Server ]  ←  HTTP  ←  [ Browser (any LAN machine) ]
       /usr/bin/nexxroute show          Flask API + static HTML
```

- **Backend:** Python (Flask) — SSHes into router, parses output, serves JSON API
- **Frontend:** Single HTML file — polls the API, renders a 32×32 routing matrix
- **Hosting:** Linux server on the same LAN, served on port `5000` (or via Nginx reverse proxy)

---

## Router Details

| Property | Value |
|---|---|
| Hostname/IP | Configured via environment variable `ROUTER_IP` (e.g. `192.168.1.100`) |
| SSH user | `root` |
| SSH auth | Username + password via `sshpass` |
| CLI command | `/usr/bin/nexxroute show` |
| Output format | Space-separated pairs, one route per line (see below) |

---

## `nexxroute show` Output Format

Each line is a single route:

```
<type>,<port>,<id> <type>,<port>,<id>
```

The **left side** is the **destination**, the **right side** is the **source**.

### Example output (excerpt):

```
vid,port41,id5   vid,port41,id0
vid,port41,id6   vid,port47,id6
vid,port44,id5   vid,port44,id0
vid,port44,id6   vid,port44,id4
vid,port45,id1   vid,port48,id1
vid,port46,id0   vid,port47,id0
vid,port46,id1   vid,port47,id0
vid,port46,id2   vid,port47,id0
vid,port46,id3   vid,port47,id0
vid,port46,id4   vid,port1,id2
vid,port46,id5   vid,port47,id0
vid,port46,id6   vid,port47,id0
vid,port46,id7   vid,port47,id0
vid,port47,id0   vid,port47,id0
vid,port47,id1   vid,port47,id0
vid,port47,id2   vid,port47,id0
vid,port47,id3   vid,port47,id0
vid,port47,id4   vid,port47,id0
vid,port47,id5   vid,port47,id0
vid,port48,id0   vid,port47,id0
```

The full output also contains lines prefixed with `aud,`, `mio_aud,`, `tdm_aud,`, `vanc,`, etc. **These must be ignored.** Only lines where **both sides begin with `vid,`** are relevant.

### Parsing rules

1. Split each line on whitespace into exactly two tokens: `destination` and `source`
2. Keep only lines where both tokens start with `vid,`
3. Parse each token as: `type,portNN,idNN` — extract `port` and `id` as integers
4. Return a list of objects: `{ dst_port, dst_id, src_port, src_id }`

---

## Router Scale

- **32 sources** and **32 destinations** (video signals only)
- The UI must handle displaying a full 32×32 matrix

---

## Backend — `server.py`

### Dependencies

```
flask
flask-cors
paramiko
```

Install: `pip install flask flask-cors paramiko`

### Endpoints

#### `GET /api/routes/video`

Runs `nexxroute show` on the router via SSH, filters video routes, and returns them as JSON.

**Response:**
```json
{
  "routes": [
    { "dst_port": 46, "dst_id": 0, "src_port": 47, "src_id": 0 },
    { "dst_port": 46, "dst_id": 1, "src_port": 47, "src_id": 0 }
  ],
  "sources": [
    { "port": 47, "id": 0 },
    { "port": 47, "id": 6 }
  ],
  "destinations": [
    { "port": 46, "id": 0 },
    { "port": 46, "id": 1 }
  ],
  "fetched_at": "2026-03-15T12:00:00Z"
}
```

- `routes` — all current video routes (left = destination, right = source)
- `sources` — deduplicated, sorted list of all unique sources seen
- `destinations` — deduplicated, sorted list of all unique destinations seen
- `fetched_at` — UTC ISO timestamp of when the data was fetched

**Error response (HTTP 500):**
```json
{ "error": "SSH connection failed: ..." }
```

### SSH implementation

Use `paramiko` with password authentication. Set `AutoAddPolicy` so the first connection doesn't hang waiting for a host key confirmation prompt.

```python
import paramiko

def run_nexxroute():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=ROUTER_IP,
        username=SSH_USER,
        password=SSH_PASSWORD,
        timeout=10
    )
    _, stdout, _ = ssh.exec_command("/usr/bin/nexxroute show")
    output = stdout.read().decode()
    ssh.close()
    return output
```

### Configuration

Read from environment variables with sensible defaults:

| Variable | Default | Description |
|---|---|---|
| `ROUTER_IP` | `192.168.1.100` | LAN IP of the router |
| `SSH_USER` | `root` | SSH username |
| `SSH_PASSWORD` | *(required)* | SSH password |
| `FLASK_PORT` | `5000` | Port to run Flask on |

### Caching

Cache the last successful result for **5 seconds** to avoid hammering the router on rapid page refreshes. Use a simple in-memory dict with a timestamp check.

---

## Frontend — `index.html`

A single self-contained HTML file (inline CSS and JS, no build step required).

### Layout

```
+--------------------------------------------------+
|  [NEXX-XC1 Video Router]  [● Live]  [↻ Refresh] |
|  Last updated: 12:00:05                          |
+--------------------------------------------------+
|                                                  |
|  [Video routing matrix — 32 destinations ×       |
|   32 sources, scrollable]                        |
|                                                  |
+--------------------------------------------------+
|  Selected: vid,port46,id0 ← vid,port47,id0       |
+--------------------------------------------------+
```

### Matrix

- **Rows** = sources (labelled `portNN idNN`, e.g. `p47 id0`)
- **Columns** = destinations (labelled rotated 45° or vertically, e.g. `p46 id0`)
- Each **cell** shows a filled circle if that source is currently routed to that destination
- The active cell per column is highlighted in blue
- Clicking any cell shows the route detail in the status bar below
- The matrix must be horizontally and vertically scrollable for 32×32

### Polling

- Auto-refresh every **5 seconds** via `setInterval` calling `GET /api/routes/video`
- Show a "stale" warning badge if the last fetch failed
- "Refresh" button triggers an immediate fetch

### Status bar

Clicking a cell shows:
- If active: `vid,portXX,idYY  ←  vid,portAA,idBB  (active)`
- If inactive: `vid,portXX,idYY is not routed to this destination`

### Display labels

Format each signal as `pNN idNN` for brevity (e.g. `p47 id0` instead of `vid,port47,id0`).

---

## File Structure

```
/opt/nexxroute-ui/
├── server.py          # Flask backend
├── index.html         # Frontend (static, served by Flask)
├── requirements.txt   # pip dependencies
└── nexxroute-ui.service  # systemd unit file
```

Flask should serve `index.html` at `/` (root) in addition to the API routes.

---

## `requirements.txt`

```
flask
flask-cors
paramiko
```

---

## systemd Unit File — `nexxroute-ui.service`

```ini
[Unit]
Description=Nexxroute Video Router UI
After=network.target

[Service]
WorkingDirectory=/opt/nexxroute-ui
ExecStart=/usr/bin/python3 /opt/nexxroute-ui/server.py
Restart=always
RestartSec=5
Environment=ROUTER_IP=192.168.1.100
Environment=SSH_USER=root
Environment=SSH_PASSWORD=yourpassword

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable --now nexxroute-ui
```

---

## Deployment Steps

```bash
# 1. Copy files to server
sudo mkdir -p /opt/nexxroute-ui
sudo cp server.py index.html requirements.txt /opt/nexxroute-ui/

# 2. Install Python dependencies
pip install -r /opt/nexxroute-ui/requirements.txt --break-system-packages

# 3. Install and start the service
sudo cp nexxroute-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nexxroute-ui

# 4. Open in browser
# http://<SERVER_IP>:5000
```

---

## Notes for Copilot

- Do **not** implement any write/reroute functionality — this is a **read-only** monitoring tool
- The `nexxroute show` command outputs **all** route types in one command; there is no flag to filter by type. Filtering to `vid,` lines must be done in the parser
- The destination is the **left** token and the source is the **right** token on each line
- Both tokens are always in the format `type,portNN,idNN` — port and id are always integers
- Lines where destination == source (e.g. `vid,port47,id0 vid,port47,id0`) are valid self-routes and should be included, not filtered out
- The SSH connection must not block indefinitely — always use a connection timeout
- The frontend has no build step — plain HTML/CSS/JS only, no npm, no webpack
