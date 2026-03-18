# Nexxroute Video Router UI — Project Specification

## Project Overview

Build a web-based UI tool that SSHes into a broadcast router frame, runs the `nexxroute show` CLI command, parses the **video (`vid`) routes** from the output, and displays them in an interactive routing matrix. The tool is hosted on a Linux server in the same local network as the router.

The router is a **frame** containing up to **12 cards**. Each card has **32 inputs and 32 outputs**, giving the frame a maximum capacity of **384 inputs and 384 outputs**. The UI must handle this scale gracefully with filtering and navigation controls.

---

## Architecture

```
[ NEXX-XC1 Router ]  ←  SSH  ←  [ Linux App Server ]  ←  HTTP  ←  [ Browser (any LAN machine) ]
       /usr/bin/nexxroute show          Flask API + static HTML
```

- **Backend:** Python (Flask) — SSHes into router, parses output, serves JSON API
- **Frontend:** Single HTML file — polls the API, renders a filterable routing matrix (up to 384×384)
- **Hosting:** Linux server on the same LAN, served on port `5000` (or via Nginx reverse proxy)

---

## Router Details

| Property | Value |
|---|---|
| Hostname/IP | Configured via environment variable `ROUTER_IP` (e.g. `192.168.1.100`) |
| SSH user | `root` |
| SSH auth | Username + password via paramiko |
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

## Router Scale & Card Architecture

The router is a **frame** of up to **12 cards**. Each card has **32 ports**, and port IDs are assigned sequentially across cards:

| Card | Port ID range |
|---|---|
| Card 1 | 1 – 32 |
| Card 2 | 33 – 64 |
| Card 3 | 65 – 96 |
| Card 4 | 97 – 128 |
| Card 5 | 129 – 160 |
| Card 6 | 161 – 192 |
| Card 7 | 193 – 224 |
| Card 8 | 225 – 256 |
| Card 9 | 257 – 288 |
| Card 10 | 289 – 320 |
| Card 11 | 321 – 352 |
| Card 12 | 353 – 384 |

The same port ID applies to both the input and output of that port (IDs are shared across directions).

### Card number derivation

Given a port ID, its card number can be derived as:

```python
card = ((port_id - 1) // 32) + 1  # result is 1–12
```

The backend must include `card` in every source and destination object in the API response so the frontend can group and filter by card without recalculating.

### Full matrix size

A fully populated frame = **384 sources × 384 destinations**. A flat 384×384 matrix is not usable — the frontend must implement the filtering and view controls described below.

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
    { "dst_port": 46, "dst_id": 0, "dst_card": 2, "src_port": 47, "src_id": 0, "src_card": 2 },
    { "dst_port": 46, "dst_id": 1, "dst_card": 2, "src_port": 47, "src_id": 0, "src_card": 2 }
  ],
  "sources": [
    { "port": 47, "id": 0, "card": 2 },
    { "port": 47, "id": 6, "card": 2 }
  ],
  "destinations": [
    { "port": 46, "id": 0, "card": 2 },
    { "port": 46, "id": 1, "card": 2 }
  ],
  "cards": [1, 2, 5],
  "fetched_at": "2026-03-15T12:00:00Z"
}
```

- `routes` — all current video routes (left = destination, right = source)
- `sources` — deduplicated, sorted list of all unique sources seen, each with their derived card number
- `destinations` — deduplicated, sorted list of all unique destinations seen, each with their derived card number
- `cards` — sorted list of card numbers that have at least one active port in this snapshot
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

Cache the last successful result for **30 seconds** to avoid hammering the router on rapid page refreshes. Use a simple in-memory dict with a timestamp check.

---

## Frontend — `index.html`

A single self-contained HTML file (inline CSS and JS, no build step required).

### Layout

```
+------------------------------------------------------------------+
|  [Video Router]  [● Live]  [↻ Refresh]   Last updated: 12:00:05 |
+------------------------------------------------------------------+
|  CARDS: [✓ Card 1] [✓ Card 2] [ Card 3] ...  [All] [None]       |
|  PORT RANGE: From [___] To [___] [Apply]                         |
|  VIEW: [Card-pair] [Active routes]                               |
+------------------------------------------------------------------+
|                                                                  |
|  [Matrix or active routes list — see views below]                |
|                                                                  |
+------------------------------------------------------------------+
|  Selected: port46 id0 (Card 2)  ←  port47 id0 (Card 2)          |
+------------------------------------------------------------------+
```

### Card filter bar

- Displays a toggle button for each card number present in the `cards` array returned by the API
- Cards not present in the API response are not shown (i.e. unpopulated card slots are hidden)
- "All" selects all available cards; "None" deselects all
- The matrix updates instantly when card selection changes (no server round-trip needed — filter client-side)

### Port range filter

- Two number inputs: "From" and "To" accepting port ID values (1–384)
- An "Apply" button updates the matrix view to show only ports within the specified range
- Validates that From ≤ To and that values are within 1–384

### Views

#### 1. Matrix view (default)

- **Rows** = sources, **Columns** = destinations
- Filtered by the active card selection and port range
- Each cell shows a filled circle if that source is routed to that destination column
- The active cell per column is highlighted in blue
- Column headers (destinations) are labelled vertically: `pNN id N (C N)` e.g. `p46 id0 (C2)`
- Row headers (sources) are labelled: `pNN idN (CN)` e.g. `p47 id0 (C2)`
- Rows and columns are grouped visually by card — insert a subtle divider line between each card's ports
- The matrix must be horizontally and vertically scrollable
- Clicking any cell shows the route detail in the status bar

#### 2. Card-pair view

- Two dropdowns: "Source card" and "Destination card" — each populated from the `cards` array
- Renders a focused 32×32 matrix showing only the ports of the selected source card (rows) vs destination card (columns)
- Same cell styling as the main matrix view
- Useful for inspecting routing between two specific cards

#### 3. Active routes view

- A flat list of all routes where source ≠ destination (non-trivial routes only)
- Each row shows: `Card N | pNN idN  ←  Card N | pNN idN`
- Sortable by source card, destination card, or port ID
- Searchable by port ID or card number via a text input

### Polling

- Auto-refresh every **5 seconds** via `setInterval` calling `GET /api/routes/video`
- Show a "stale" warning badge if the last fetch failed
- "Refresh" button triggers an immediate fetch
- Filters and view selection are preserved across refreshes

### Status bar

Clicking a matrix cell shows:
- If active: `port XX id Y (Card N)  ←  port AA id B (Card N)  [active]`
- If inactive: `port XX id Y is not currently routed to this destination`

### Display labels

Format each signal as `pNN idN (CN)` for brevity, e.g. `p46 id0 (C2)` instead of `vid,port46,id0`.

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
- Card number must be derived in the backend using `card = ((port_id - 1) // 32) + 1` and included in every port object in the API response
- The `cards` array in the API response must only include cards that have at least one port appearing in the current route data — do not hardcode all 12 cards
- All matrix filtering (by card, by port range) is done client-side in JavaScript — no additional API endpoints are needed for filtering
- The three views (matrix, card-pair, active routes) should be tabs or toggle buttons — only one view is visible at a time
- Port range filter inputs should default to empty (no filter applied) on page load