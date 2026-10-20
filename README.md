# Design Studio Automation

Automate Adobe Photoshop Web (photoshop.adobe.com) with Playwright, driven from
a custom web UI. Upload an image, pick an operation, watch a live log stream the
steps, and preview the transparent result on any tee-shirt color.

Photoshop-driven operations (Blackout, Remove Background, Resolution, Color
Adjustment) run through a real logged-in browser session. Pixel-level cleanups
(Ghost Pixel Removal, Transparent Pixel Cleanup, Semi-Pixel Cleanup) run locally
with Pillow + NumPy + OpenCV.

## Stack

- **Backend:** Python 3.11+, FastAPI, Playwright, SQLite
- **Frontend:** plain HTML/CSS/JS served by FastAPI (no build step)
- **Image ops:** Pillow, NumPy, OpenCV

## Project structure

```
Photoshop_Automation/
├── app/
│   ├── main.py              # FastAPI app + endpoints (incl. /photoshop/status)
│   ├── config.py            # all runtime flags + connection config (.env aware)
│   ├── db.py                # SQLite job store
│   ├── queue.py             # single-worker job queue + SSE log bus
│   ├── imageops.py          # Pillow/NumPy/OpenCV pixel operations
│   ├── photoshop/
│   │   ├── session.py       # CDP-attach / launch lifecycle, login + download logic
│   │   ├── selectors.py     # ALL Photoshop selectors/labels in one file
│   │   └── recipes/         # one module per Photoshop operation
│   └── static/              # index.html, styles.css, app.js
├── tools/
│   ├── record_selectors.py  # open Playwright Inspector on your Chrome tab
│   └── dump_ui.py           # dump real role/name labels to data/ui_dump/
├── tests/                   # pytest: config, CDP error path, is_logged_in, status
├── start_chrome.bat         # launch your Chrome with remote debugging (Windows)
├── start_chrome.ps1         # same, PowerShell
├── login_once.py            # detect Adobe login in the attached Chrome
├── requirements.txt
└── data/                    # uploads/, results/, debug/, ui_dump/ (runtime)
```

## Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install the Chrome channel Playwright uses in "launch" fallback mode
playwright install chrome
```

## Connection modes

Adobe misbehaves inside the bare browser Playwright launches itself (login
problems, cut-off layout, the "--no-sandbox" warning bar). The robust fix is to
let Playwright **attach to a normal Chrome you started yourself** over the
DevTools protocol (CDP). Two modes, selected by `PS_CONNECT_MODE`:

### `cdp` (default, recommended)

You launch Chrome with remote debugging; the app attaches to it, reuses your
existing window/profile, and **never closes your browser** — on job end it only
closes a tab it opened itself and detaches the connection.

```powershell
# 1. Start YOUR Chrome with debugging + a dedicated profile
.\start_chrome.bat            # or:  ./start_chrome.ps1

# 2. Log in to Adobe in that window, then confirm the session:
python login_once.py

# 3. Run the app
uvicorn app.main:app --reload
```

> **Chrome 136+ requires a dedicated profile.** Modern Chrome ignores
> `--remote-debugging-port` on the *default* profile for security, so the
> launcher scripts always pass `--user-data-dir=<project>\chrome_profile`. This
> is mandatory — debugging will silently not work on the default profile.
>
> Debugging binds to **127.0.0.1 only**, never `0.0.0.0`, so nothing off your
> machine can drive the browser.

### `launch` (fallback)

Playwright launches its own persistent Chrome, maximized, with the sandbox
warning suppressed and **no fixed viewport** (a real resizable window, so the
Adobe layout is not cut off).

```powershell
$env:PS_CONNECT_MODE = "launch"; uvicorn app.main:app --reload
```

## Log in to Adobe (one time per profile)

Adobe uses captcha / 2FA, so login is **never automated** and **no credentials
are ever stored**. With Chrome started via `start_chrome.bat`:

```bash
python login_once.py
```

It connects over CDP, opens photoshop.adobe.com if needed, and polls every 2s
(up to 10 minutes) until it detects the signed-in state, then prints:

> Logged in as detected, session saved in …\chrome_profile

No Enter press needed. The session lives inside Chrome's own profile
(`./chrome_profile`), which is gitignored. If the session later expires, a job
fails with:

> Adobe session expired. Log in again in the Chrome window opened by start_chrome.bat

## Connection status in the UI

The header shows a status pill next to the DEMO MODE badge, polling
`GET /photoshop/status` every 10s:

- 🟢 **green** — Chrome reachable and logged in (shows the window size)
- 🟠 **amber** — Chrome not reachable (run `start_chrome.bat`) or DEMO MODE
- 🔴 **red** — connected but logged out (log in again)

Before every Photoshop job the app also checks the window is at least
**1280×720** and logs a warning telling you to maximize or zoom out (Ctrl + -)
if it is smaller, since a small window cuts off Adobe's layout.

## Run

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## DEMO_MODE (no Adobe / no Chrome needed)

To exercise the UI, queue, and log streaming with **zero Chrome dependency**,
start with `DEMO_MODE=1`. Every operation runs through the local Pillow engine
and still produces a downloadable PNG. The status pill shows "Demo".

```powershell
$env:DEMO_MODE = "1"; uvicorn app.main:app --reload      # Windows PowerShell
```
```bash
DEMO_MODE=1 uvicorn app.main:app --reload                 # macOS / Linux
```

## Configuration flags

Set as environment variables, or put them in a `.env` file at the project root
(loaded automatically). Example `.env`:

```ini
PS_CONNECT_MODE=cdp
PS_CDP_URL=http://127.0.0.1:9222
PS_DOWNLOAD_DIR=C:\Users\you\Downloads
```

| Variable              | Default                 | Meaning |
|-----------------------|-------------------------|---------|
| `PS_CONNECT_MODE`     | `cdp`                   | `cdp` (attach to your Chrome) or `launch` (Playwright launches Chrome). |
| `PS_CDP_URL`          | `http://127.0.0.1:9222` | DevTools endpoint the launcher exposes. |
| `PS_PROFILE_DIR`      | `./chrome_profile`      | Dedicated Chrome profile (absolute path). |
| `PS_DOWNLOAD_DIR`     | user's Downloads        | Folder watched for exported PNGs (download fallback). |
| `DEMO_MODE`           | `0`                     | Skip Photoshop; local Pillow engine for everything (no Chrome). |
| `BLACKOUT_ENGINE`     | `photoshop`             | `photoshop` or `pillow` — which engine runs Blackout. |
| `JOB_TIMEOUT_SECONDS` | `180`                   | Hard timeout per job. |
| `PW_CHANNEL`          | `chrome`                | Playwright browser channel (launch mode). |
| `MAX_UPLOAD_BYTES`    | `10485760`              | Upload size limit (10 MB). |
| `CHROME_PATH`         | auto-detect             | Override Chrome location for the launcher scripts. |

## Downloads

Exporting a PNG is captured two ways, whichever fires first (the log says which
one worked):

1. **Playwright download event** (`page.expect_download`).
2. **Download-folder watch** — in CDP mode the real browser may drive the
   download and never surface the event, so the app also watches
   `PS_DOWNLOAD_DIR` for the newest `*.png` appearing after the export click
   (skipping Chrome's `.crdownload` temp files and waiting for a stable size).

If your Chrome saves downloads somewhere other than the default Downloads
folder, set `PS_DOWNLOAD_DIR` to match.

## Operations

| Operation                 | Engine     | Notes |
|---------------------------|------------|-------|
| Blackout                  | Photoshop¹ | Select > Color Range (black, fuzziness = Softness) > Delete > export PNG. Softness 0–60 also eats near-black JPG artifacts. |
| Remove Background         | Photoshop  | Quick action, then export transparent PNG. |
| Resolution                | Photoshop  | Image > Image size (width/height or scale %, DPI). |
| Color Adjustment          | Photoshop  | Brightness / Contrast / Saturation. |
| Ghost Pixel Removal       | Local      | Drops tiny isolated alpha blobs (connected components, `min_area`). |
| Transparent Pixel Cleanup | Local      | Zeros RGB where alpha == 0, optional 1px edge defringe. |
| Semi-Pixel Cleanup        | Local      | alpha < low → 0, alpha > high → 255. |
| Custom Edit               | —          | Disabled placeholder. |

¹ Respects `BLACKOUT_ENGINE`; set to `pillow` to use the local reference
`blackout_color_to_alpha()` instead.

## How to record the Blackout recipe

The recipes ship with the step flow written out but the actual selectors left as
clearly marked `TODO` blocks — Adobe's DOM changes and must be captured on your
machine, in the exact Chrome/profile the app drives.

1. **Start Chrome:** `.\start_chrome.bat`
2. **Log in:** sign in to Adobe in that window, then `python login_once.py`.
3. **See the real labels:** `python tools/dump_ui.py`
   - Writes `data/ui_dump/<timestamp>.json` (role + accessible name of every
     visible button / menu item / dialog) plus a screenshot.
   - To capture an opened menu, click it first:
     `python tools/dump_ui.py --after-click "Select"`
4. **Record locators:** `python tools/record_selectors.py`
   - Opens Playwright's Inspector on your Photoshop tab so you can explore /
     record codegen-style locators against the real, logged-in session.
5. **Paste into `app/photoshop/selectors.py`** (every selector lives there) and
   uncomment the reference flow in the matching `recipes/*.py`.

Prefer **role + accessible-name** locators over CSS classes (Adobe's classes are
generated and change constantly). The login markers in `selectors.py`
(`LOGGED_IN_MARKERS` / `LOGGED_OUT_MARKERS`) are plain editable lists — add as
many candidates as you like.

Each step logs a timestamped line, waits for an explicit condition (never a bare
sleep), and saves a debug screenshot to `./data/debug/{job_id}/step_N.png`. On
failure the session saves a screenshot and the log reports the failing step.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Photoshop layout is cut off / menus overflow | Window smaller than 1280×720 | Maximize the Chrome window or zoom out (Ctrl + -). The job log warns when this happens. |
| "Sign in" button missing / login markers never match | Adobe changed the UI labels | Run `python tools/dump_ui.py`, then update `LOGGED_IN_MARKERS` / `LOGGED_OUT_MARKERS` in `selectors.py`. |
| Port 9222 busy | Another process (or a stale Chrome) holds the port | `start_chrome` checks `/json/version`: if it's a Chrome debug endpoint you're already good; otherwise close that process or set `PS_CDP_URL` to a free port. |
| Export "did not produce a PNG" | Chrome saves downloads elsewhere | Set `PS_DOWNLOAD_DIR` to Chrome's real download folder. The log says which capture method it tried. |
| Status pill amber "Chrome not reachable" | Chrome not started with debugging | Run `start_chrome.bat` (needs the dedicated `--user-data-dir`). |
| Status pill red / "Adobe session expired" | Logged out of Adobe | Log in again in the `start_chrome.bat` window; `login_once.py` confirms it. |
| `connect_over_cdp` fails on the default profile | Chrome 136+ ignores debugging on the default profile | Always use the launcher scripts — they pass a dedicated `--user-data-dir`. |

## Tests

```bash
pytest -q
```

Covers config parsing (defaults, env overrides, `.env`), the CDP-unreachable
error path (mocked — no real Chrome), `is_logged_in` with a mocked page, and the
`/photoshop/status` endpoint in DEMO_MODE. The whole suite runs with **zero
Chrome dependency**.

## API

| Method | Path                   | Purpose |
|--------|------------------------|---------|
| POST   | `/upload`              | Save upload → `file_id` + metadata. |
| POST   | `/jobs`                | `{file_id, op, params}` → `job_id` (enqueued). |
| GET    | `/jobs/{id}/events`    | SSE stream of log lines + status. |
| GET    | `/results/{id}.png`    | Processed PNG. |
| GET    | `/history`             | Past jobs from SQLite. |
| GET    | `/photoshop/status`    | `{connected, logged_in, window_size, url, demo_mode}`. |

Jobs run **strictly one at a time** — there is only one logged-in Photoshop
session to share.
