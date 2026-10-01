# Gym Tracker

A small local app to log gym sessions (chest, legs, arms, abs, ...) on a calendar, with how long each one took.

No dependencies: just Node.js 18+.

## Run

```bash
npm start
```

Then open http://localhost:3000 (set `PORT=4000 npm start` to use another port).

## Usage

- Click any day on the calendar to log a session: pick a type, the duration in minutes, and optional notes.
- Type anything for the type: presets (Chest, Back, Legs, Arms, Shoulders, Abs, Cardio, Full body) get fixed colors, custom ones get their own.
- Edit or delete sessions from the same day dialog.
- The side panel shows the month's sessions, total time, active days and a per-muscle-group breakdown.

Data is stored in `data/sessions.json` on your machine (git-ignored).
