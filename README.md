# Gym Tracker

A small local app to log gym sessions (chest, legs, arms, abs, ...) on a calendar, with how long each one took.

No dependencies: just Node.js 18+.

## Run

```bash
npm start
```

Then open http://localhost:3000 (set `PORT=4000 npm start` to use another port).

## Use it on your phone

Your computer runs the app and your phone opens it over the same Wi-Fi:

```bash
npm run start:lan
```

The terminal prints an address like `http://192.168.1.20:3000`. Open that on your phone. The computer has to stay on and running the app, and your data stays on the computer (`data/sessions.json`), so phone and computer always show the same sessions.

To make it feel like an app, use "Add to Home Screen" in your phone's browser menu.

There is no password: while `start:lan` is running, anyone on the same network can open and edit your log. Use it on your home Wi-Fi, not on public Wi-Fi. If the phone can't connect, allow Node.js through your computer's firewall.

## Usage

- Click any day on the calendar to log a session: pick a type, the duration in minutes, and optional notes.
- Type anything for the type: presets (Chest, Back, Legs, Arms, Shoulders, Abs, Cardio, Full body) get fixed colors, custom ones get their own.
- Edit or delete sessions from the same day dialog.
- The side panel shows the month's sessions, total time, active days and a per-muscle-group breakdown.

Data is stored in `data/sessions.json` on your machine (git-ignored).
