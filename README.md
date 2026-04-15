# Nexxroute Video Router UI — Project Specification

## Project Overview

Build a web-based UI tool that SSHes into a broadcast router frame, runs the `nexxroute show` CLI command, parses the **video (`vid`) routes** from the output, and displays them in an interactive routing matrix. The tool is hosted on a Linux server in the same local network as the router.

The router is a **frame** containing up to **12 cards**. Each card has **4 CGE groups** (Coaxial Group Elements), and each CGE group has **8 channels** (0–7), giving each card **32 channels** and the frame a maximum capacity of **384 channels per direction**. The UI must handle this scale gracefully with filtering and navigation controls.

---

## Architecture

```
[ NEXX-XC1 Router ]  ←  SSH  ←  [ Linux App Server ]  ←  HTTP  ←  [ Browser (any LAN machine) ]
       /usr/bin/nexxroute show          Flask API + static HTML
```

- **Backend:** Python (Flask) — SSHes into router, parses output, serves JSON API
- **Frontend:** Single HTML file — polls the API, renders a filterable routing matrix (up to 48 CGE groups × 8 channels per direction)
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
3. Parse each token as: `type,portNN,idNN` — `portNN` is the **CGE group number** (1–48, 1-indexed), `idNN` is the **channel** within the group (0–7, 0-indexed)
4. Return a list of objects: `{ dst_cge, dst_ch, src_cge, src_ch }`

---

## Router Scale & Card Architecture

The router is a **frame** of up to **12 cards**. Each card has **4 CGE groups** (Coaxial Group Elements), and each CGE group has **8 channels** (indexed 0–7). The `port` number in the `nexxroute show` output represents the **CGE group number** (1–48), and the `id` represents the **channel** within that group (0–7).

| Card | CGE Group Range | Channels per Card |
|---|---|---|
| Card 1 | 1 – 4 | 32 (4 × 8) |
| Card 2 | 5 – 8 | 32 |
| Card 3 | 9 – 12 | 32 |
| Card 4 | 13 – 16 | 32 |
| Card 5 | 17 – 20 | 32 |
| Card 6 | 21 – 24 | 32 |
| Card 7 | 25 – 28 | 32 |
| Card 8 | 29 – 32 | 32 |
| Card 9 | 33 – 36 | 32 |
| Card 10 | 37 – 40 | 32 |
| Card 11 | 41 – 44 | 32 |
| Card 12 | 45 – 48 | 32 |

The most commonly used cards on this frame are **8, 9, 11, 12** (CGEs 29–32, 33–36, 41–44, 45–48).

The same CGE group number applies to both the input and output side (IDs are shared across directions).

### Card number derivation

Given a CGE group number, its card number can be derived as:

```python
card = ((cge - 1) // 4) + 1  # result is 1–12
```

The backend must include `card` in every source and destination object in the API response so the frontend can group and filter by card without recalculating.

### Full matrix size

A fully populated frame = **48 CGE groups × 8 channels = 384 channels** per direction. A flat 384×384 matrix is not usable — the frontend must implement the filtering and view controls described below.

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
    { "dst_cge": 46, "dst_ch": 0, "dst_card": 12, "src_cge": 47, "src_ch": 0, "src_card": 12 },
    { "dst_cge": 46, "dst_ch": 1, "dst_card": 12, "src_cge": 47, "src_ch": 0, "src_card": 12 }
  ],
  "sources": [
    { "cge": 47, "ch": 0, "card": 12 },
    { "cge": 47, "ch": 6, "card": 12 }
  ],
  "destinations": [
    { "cge": 46, "ch": 0, "card": 12 },
    { "cge": 46, "ch": 1, "card": 12 }
  ],
  "cards": [8, 9, 12],
  "fetched_at": "2026-03-15T12:00:00Z"
}
```

- `routes` — all current video routes (left = destination, right = source); fields use `cge` (CGE group) and `ch` (channel)
- `sources` — deduplicated, sorted list of all unique sources seen, each with their derived card number
- `destinations` — deduplicated, sorted list of all unique destinations seen, each with their derived card number
- `cards` — sorted list of card numbers that have at least one active CGE group in this snapshot
- `fetched_at` — UTC ISO timestamp of when the data was fetched

**Error response (HTTP 500):**
```json
{ "error": "SSH connection failed: ..." }
```

#### `POST /api/routes/video/set`

Sets a video route on the router by SSHing into the device, opening a telnet session to the router control port (`localhost:9654`), and sending the `.SV` command.

**Request body (JSON):**
```json
{ "dest": 350, "src": 350 }
```

| Field | Type | Description |
|---|---|---|
| `dest` | integer | Destination port ID number |
| `src` | integer | Source port ID number (use `0` to remove/disconnect the route to `dest`) |

**Success response (HTTP 200):**
```json
{
  "ok": true,
  "command": ".SV350,350",
  "response": "...",
  "timestamp": "2026-04-11T12:00:00Z"
}
```

- `ok` — always `true` on success
- `command` — the `.SV` command that was sent
- `response` — raw text response from the router control port
- `timestamp` — UTC ISO timestamp of when the command was executed

**Validation errors (HTTP 400):**
```json
{ "error": "Both 'dest' and 'src' are required" }
```
```json
{ "error": "'dest' and 'src' must be integers" }
```

**Error response (HTTP 500):**
```json
{ "error": "Failed to set route: ..." }
```

**Notes:**
- The route cache is automatically invalidated after a successful set-route so subsequent `GET /api/routes/video` calls return fresh data.
- The underlying procedure is: SSH → `telnet localhost 9654` → `.SV<dest>,<src>`
- **Route removal:** To disconnect/remove a route, send `src` as `0`. This translates to `.SV<dest>,0` on the router. Example: `{"dest": 350, "src": 0}` removes whatever is routed to port 350.

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
| `TELNET_PORT` | `9654` | Router control telnet port (used by set-route) |

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
|  CARDS: [✓ Card 8] [✓ Card 9] [ Card 11] ...  [All] [None]      |
|  CGE RANGE: From [___] To [___] [Apply]                          |
|  VIEW: [Card-pair] [Active routes]                               |
+------------------------------------------------------------------+
|                                                                  |
|  [Matrix or active routes list — see views below]                |
|                                                                  |
+------------------------------------------------------------------+
|  Selected: CGE46 ch0 (Card 12)  ←  CGE47 ch0 (Card 12)          |
+------------------------------------------------------------------+
```

### Card filter bar

- Displays a toggle button for each card number present in the `cards` array returned by the API
- Cards not present in the API response are not shown (i.e. unpopulated card slots are hidden)
- "All" selects all available cards; "None" deselects all
- The matrix updates instantly when card selection changes (no server round-trip needed — filter client-side)

### CGE range filter

- Two number inputs: "From" and "To" accepting CGE group numbers (1–48)
- An "Apply" button updates the matrix view to show only CGE groups within the specified range
- Validates that From ≤ To and that values are within 1–48

### Views

#### 1. Matrix view (default)

- **Rows** = sources, **Columns** = destinations
- Filtered by the active card selection and CGE range
- Each cell shows a filled circle if that source is routed to that destination column
- The active cell per column is highlighted in blue
- Column headers (destinations) are labelled vertically: `CGEnn chN (CN)` e.g. `CGE46 ch0 (C12)`
- Row headers (sources) are labelled: `CGEnn chN (CN)` e.g. `CGE47 ch0 (C12)`
- Rows and columns are grouped visually by card — insert a subtle divider line between each card's CGE groups
- The matrix must be horizontally and vertically scrollable
- Clicking any cell shows the route detail in the status bar

#### 2. Card-pair view

- Two dropdowns: "Source card" and "Destination card" — each populated from the `cards` array
- Renders a focused 32×32 matrix showing only the CGE groups/channels of the selected source card (rows) vs destination card (columns)
- Same cell styling as the main matrix view
- Useful for inspecting routing between two specific cards

#### 3. Active routes view

- A flat list of all routes where source ≠ destination (non-trivial routes only)
- Each row shows: `Card N | CGEnn chN  ←  Card N | CGEnn chN`
- Sortable by source card, destination card, or CGE group
- Searchable by CGE group or card number via a text input

### Polling

- Auto-refresh every **5 seconds** via `setInterval` calling `GET /api/routes/video`
- Show a "stale" warning badge if the last fetch failed
- "Refresh" button triggers an immediate fetch
- Filters and view selection are preserved across refreshes

### Status bar

Clicking a matrix cell shows:
- If active: `CGE XX ch Y (Card N)  ←  CGE AA ch B (Card N)  [active]`
- If inactive: `CGE XX ch Y is not currently routed to this destination`

### Display labels

Format each signal as `CGEnn chN (CN)` for brevity, e.g. `CGE46 ch0 (C12)` instead of `vid,port46,id0`.

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

- Do **not** implement any write/reroute functionality from the frontend UI — route changes should only be made through the `POST /api/routes/video/set` API endpoint
- The `nexxroute show` command outputs **all** route types in one command; there is no flag to filter by type. Filtering to `vid,` lines must be done in the parser
- The destination is the **left** token and the source is the **right** token on each line
- Both tokens are always in the format `type,portNN,idNN` — `portNN` is the CGE group number (1–48) and `idNN` is the channel (0–7)
- Lines where destination == source (e.g. `vid,port47,id0 vid,port47,id0`) are valid self-routes and should be included, not filtered out
- The SSH connection must not block indefinitely — always use a connection timeout
- The frontend has no build step — plain HTML/CSS/JS only, no npm, no webpack
- Card number must be derived in the backend using `card = ((cge - 1) // 4) + 1` and included in every source/destination object in the API response
- The `cards` array in the API response must only include cards that have at least one CGE group appearing in the current route data — do not hardcode all 12 cards
- All matrix filtering (by card, by CGE range) is done client-side in JavaScript — no additional API endpoints are needed for filtering
- The three views (matrix, card-pair, active routes) should be tabs or toggle buttons — only one view is visible at a time
- CGE range filter inputs should default to empty (no filter applied) on page load
- The most commonly used cards are **8, 9, 11, 12** (CGEs 29–32, 33–36, 41–44, 45–48)