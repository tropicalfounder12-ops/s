"""Pure logic for the Typing Companion: typing meter, settings and stats.

No tkinter and no Windows APIs in here, so everything is unit-testable anywhere.

Privacy: only the *timing* of key presses is used. Which key was pressed is never
stored, logged or sent anywhere (a key id is held in memory only while the key is
down, to tell auto-repeat from a real press).
"""

import datetime
import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections import deque, namedtuple

import sprites

log = logging.getLogger("companion")

# ── Timing / thresholds ──────────────────────────────────────
IDLE_AFTER = 3.5        # seconds without typing -> idle
SLEEP_AFTER = 35.0      # seconds without typing -> sleeping
WPM_WINDOW = 8.0        # rolling window used for WPM
WPM_MIN_SPAN = 3.0      # shortest divisor, so the first keys of a burst don't read as ~0 WPM
WPM_SUSTAINED = 5.0     # a reading only counts as a "record" after this many seconds of typing
WPM_SLOW = 25           # below this: gentle typing
WPM_FAST = 60           # at/above this: turbo mode (sparkles)
REPEAT_WINDOW = 1.5     # a second key-down for a key still held within this long is auto-repeat

MODIFIER_NAMES = frozenset({
    "shift", "shift_l", "shift_r", "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r",
    "alt_gr", "cmd", "cmd_l", "cmd_r", "caps_lock", "num_lock", "scroll_lock",
})

Snapshot = namedtuple("Snapshot", "wpm age mood idle_for press_seq total")


def mood_for(idle_for):
    """Map seconds-since-last-activity to 'typing' / 'idle' / 'sleeping'."""
    if idle_for > SLEEP_AFTER:
        return "sleeping"
    if idle_for > IDLE_AFTER:
        return "idle"
    return "typing"


class TypingMeter:
    """Thread-safe record of key-press timing (written by the keyboard thread, read by the UI)."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._stamps = deque()          # times of counted keystrokes inside the WPM window
        self._down = {}                 # key id -> time of its latest key-down while held
        # Start out idle rather than "typing" so the sprite doesn't greet you with a fake burst.
        self._last_activity = clock() - IDLE_AFTER - 1.0
        self._press_seq = 0             # increments on every counted keystroke
        self._total = 0

    # ── written from the keyboard thread ─────────────────────
    def key_down(self, key_id, is_modifier=False, now=None):
        """Register a key-down. Returns True if it counted as a new keystroke.

        Auto-repeat (key still held) and modifier keys keep the sprite awake but are not
        counted towards WPM, so holding Backspace or tapping Shift can't inflate it.
        """
        now = self._clock() if now is None else now
        with self._lock:
            last = self._down.get(key_id)
            self._down[key_id] = now
            if len(self._down) > 64:    # missed key-ups: forget stale entries
                self._down = {k: t for k, t in self._down.items() if now - t < REPEAT_WINDOW}
            self._last_activity = now
            if is_modifier or (last is not None and now - last < REPEAT_WINDOW):
                return False
            self._stamps.append(now)
            self._press_seq += 1
            self._total += 1
            return True

    def key_up(self, key_id):
        with self._lock:
            self._down.pop(key_id, None)

    # ── user actions ─────────────────────────────────────────
    def wake(self, now=None):
        """Wake from sleep into the idle pose, without counting a keystroke."""
        now = self._clock() if now is None else now
        with self._lock:
            self._last_activity = now - IDLE_AFTER - 0.01

    def nap(self, now=None):
        """Fall asleep immediately (the next key press wakes the sprite)."""
        now = self._clock() if now is None else now
        with self._lock:
            self._last_activity = now - SLEEP_AFTER - 1.0

    # ── read from the UI thread ──────────────────────────────
    def snapshot(self, now=None):
        now = self._clock() if now is None else now
        with self._lock:
            cutoff = now - WPM_WINDOW
            while self._stamps and self._stamps[0] < cutoff:
                self._stamps.popleft()
            count = len(self._stamps)
            if count:
                age = now - self._stamps[0]
                wpm = (count / 5.0) * (60.0 / max(age, WPM_MIN_SPAN))   # 5 keystrokes = 1 word
            else:
                age = wpm = 0.0
            idle_for = max(0.0, now - self._last_activity)
            return Snapshot(wpm, age, mood_for(idle_for), idle_for, self._press_seq, self._total)


# ══════════════════════════════════════════════════════════════
#  Persistence
# ══════════════════════════════════════════════════════════════
def data_dir():
    """Folder for settings, stats and the log (override with TYPING_COMPANION_HOME)."""
    override = os.environ.get("TYPING_COMPANION_HOME")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "TypingCompanion")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "typing-companion")


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    """Atomic write (temp file + rename) so a crash can't leave a half-written file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError as exc:
        log.warning("could not write %s: %s", path, exc)
        return False


DOCK_MODES = ("taskbar", "active_window", "free")
SCALES = (3, 4, 5, 6)

DEFAULT_SETTINGS = {
    "character": "cat",
    "dock_mode": "taskbar",
    "scale": 4,
    "show_wpm": True,
    "hide_fullscreen": True,
    "dock_x": None,      # sprite's left edge while docked to the taskbar
    "free_x": None,      # sprite's top-left corner while free floating
    "free_y": None,
}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


_VALIDATORS = {
    "character": lambda v: v in sprites.CHARACTERS,
    "dock_mode": lambda v: v in DOCK_MODES,
    "scale": lambda v: v in SCALES,
    "show_wpm": lambda v: isinstance(v, bool),
    "hide_fullscreen": lambda v: isinstance(v, bool),
    "dock_x": lambda v: v is None or _is_int(v),
    "free_x": lambda v: v is None or _is_int(v),
    "free_y": lambda v: v is None or _is_int(v),
}


def sanitize_settings(raw):
    """Merge raw (possibly hand-edited or corrupt) data over the defaults, dropping bad values."""
    out = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key, ok in _VALIDATORS.items():
            if key in raw and ok(raw[key]):
                out[key] = raw[key]
    return out


def load_settings(path):
    return sanitize_settings(read_json(path))


def save_settings(path, settings):
    return write_json(path, sanitize_settings(settings))


class Stats:
    """Lifetime counters: keys today, best WPM and total keys. Counts only - never key contents."""

    def __init__(self, path, today=None):
        self.path = path
        self.dirty = False
        raw = read_json(path)
        self.day = raw.get("day") if isinstance(raw.get("day"), str) else ""
        self.keys_today = self._count(raw.get("keys_today"))
        self.total_keys = self._count(raw.get("total_keys"))
        best = raw.get("best_wpm")
        self.best_wpm = float(best) if isinstance(best, (int, float)) and best >= 0 else 0.0
        self._roll(today)

    @staticmethod
    def _count(value):
        return value if _is_int(value) and value >= 0 else 0

    def _roll(self, today=None):
        today = today or datetime.date.today().isoformat()
        if self.day != today:
            self.day = today
            self.keys_today = 0
            self.dirty = True

    def add_keys(self, n, today=None):
        if n > 0:
            self._roll(today)
            self.keys_today += n
            self.total_keys += n
            self.dirty = True

    def record_wpm(self, wpm):
        """Store a new personal best. Returns True if `wpm` beat the previous best."""
        if wpm > self.best_wpm:
            self.best_wpm = float(wpm)
            self.dirty = True
            return True
        return False

    def summary(self):
        self._roll()
        best = f"{int(round(self.best_wpm))} WPM" if self.best_wpm else "-"
        return f"Today: {self.keys_today:,} keys  ·  Best: {best}"

    def save(self):
        if write_json(self.path, {
            "day": self.day,
            "keys_today": self.keys_today,
            "total_keys": self.total_keys,
            "best_wpm": round(self.best_wpm, 1),
        }):
            self.dirty = False
