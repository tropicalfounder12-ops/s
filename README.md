# Gym Tracker

A small local app to log gym sessions (chest, legs, arms, abs, ...) on a calendar, with how long each one took.

No dependencies: just Node.js 18+.

## Run

```bash
npm start
```

Then open http://localhost:3000 (set `PORT=4000 npm start` to use another port).

## Use it on your phone

### Same Wi-Fi

```bash
npm run start:lan
```

The terminal prints an address like `http://192.168.1.20:3000`. Open it on your phone. Your computer has to stay on. Anyone on the same network can open it unless you set a password (below). If the phone can't connect, allow Node.js through your computer's firewall.

### From anywhere (mobile data, the gym, other Wi-Fi)

Always set a `PASSWORD` for this. With it, every page and API call needs a login (30-day cookie, wrong guesses are throttled).

**Option A: your own computer + Tailscale (free, recommended).** Nothing is exposed to the public internet.

1. Install [Tailscale](https://tailscale.com) on your computer and your phone, signed in to the same account.
2. On the computer: `PASSWORD='something-long' npm run start:lan` (Windows PowerShell: `$env:PASSWORD='something-long'; npm run start:lan`).
3. On the phone, open `http://<computer's Tailscale name or 100.x.x.x address>:3000`.

It works from anywhere as long as the computer is on and running the app.

**Option B: a real server that is always on.** Deploy the included `Dockerfile` to any host that runs containers (Fly.io, Railway, a VPS...). You need:

- the env var `PASSWORD` (and optionally `SESSION_SECRET`, a random string),
- a **persistent volume mounted at `/data`**, otherwise your sessions are wiped on every redeploy,
- HTTPS, which these hosts provide.

The container sets `HOST=0.0.0.0`, `DATA_DIR=/data` and `TRUST_PROXY=1`, and refuses to start without a `PASSWORD`.

| Variable | Meaning | Default |
| --- | --- | --- |
| `PORT` | port to listen on | `3000` |
| `HOST` | `127.0.0.1` = this computer only, `0.0.0.0` = reachable by others | `127.0.0.1` |
| `PASSWORD` | turns on the login | none |
| `DATA_DIR` | where `sessions.json` is stored | `./data` |
| `SESSION_SECRET` | signs login cookies (defaults to a key derived from `PASSWORD`) | |
| `ANTHROPIC_API_KEY` | turns on the Claude features; keep it in the environment or your host's secrets, never in git | none |
| `TRUST_PROXY` | `1` when behind a proxy, so login throttling sees the real client IP | off |

To make it feel like an app, use "Add to Home Screen" in your phone's browser menu.

## Usage

- Click any day on the calendar to log a session: pick a type, the duration in minutes, and optional notes.
- Type anything for the type: presets (Chest, Back, Legs, Arms, Shoulders, Abs, Cardio, Full body) get fixed colors, custom ones get their own.
- Edit or delete sessions from the same day dialog.
- The side panel shows the month's sessions, total time, active days and a per-muscle-group breakdown.

Data is stored in `data/sessions.json` on your machine (git-ignored).
