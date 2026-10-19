#!/usr/bin/env python3
"""
🌸 Taskbar Typing Companion - spring edition
A tiny pixel friend (Cat, Robot, Wizard or Bunny) that stands on your taskbar or perches on
the window you're using. It types along with you, grows a little garden from your keystrokes,
gets visits from butterflies, says kind things now and then, and naps when you stop.

Run it with `pythonw companion.py` (or double-click run.bat).
Click it to pet it, double-click for today's journal, right-click for everything else.
"""

import argparse
import logging
import logging.handlers
import os
import random
import sys
import time

import core
import cozy
import garden
import keyboard_input
import sprites
import theme
import winutil
from effects import Butterfly, Particle

try:                                    # pythonw has no console, so a missing tkinter needs a
    import tkinter as tk                # message box rather than a silent exit (see main()).
    import tkinter.font as tkfont
    from bubble import Bubble, draw_round_rect, draw_shape
except ImportError as _tk_import_error:   # pragma: no cover - depends on the Python install
    tk = tkfont = None
    TK_IMPORT_ERROR = _tk_import_error
else:
    TK_IMPORT_ERROR = None

__version__ = "2.1.0"
SCRIPT_PATH = os.path.abspath(__file__)
log = logging.getLogger("companion")

# ── Layout (in sprite pixels; one sprite pixel = `px` screen pixels) ───────────────────────
HEAD_ROWS = 6              # empty rows above the sprite: room for the badge and effects
PAD_COLS = 7               # columns each side: the garden grows here, effects spread out
GARDEN_COLS = (PAD_COLS + 17, PAD_COLS - 3, PAD_COLS + 20, PAD_COLS - 6)   # growth order
DOCK_MARGIN = 90           # screen px (at 100% DPI) between the docked sprite and the screen edge
PERCH_SINK = 2             # screen px the feet sink into a perched window's top edge
CAPTION_BUTTONS = 145      # screen px of minimise/maximise/close to keep clear when perching
NO_TASKBAR_STRIP = 40      # stand-in taskbar height where there's no Windows API (dev only)

# ── Timing ───────────────────────────────────────────────────────────────────────────────
TICK_BUSY_MS = 33          # ~30 fps while anything is moving
TICK_CALM_MS = 100         # resting loop; also bounds how fast a sleeping sprite wakes up
HOP_SECS = 0.09
IDLE_FLIP_SECS = 0.65      # tail wag / antenna blink / ear twitch period
SLEEP_FLIP_SECS = 1.1
DOUBLE_CLICK_MS = 280      # wait this long before treating a click as a pet
DRAG_THRESHOLD = 4         # screen px of movement before a click becomes a drag
HOUSEKEEPING_SECS = 1.0
STATS_FLUSH_SECS = 30.0
SAVE_RETRY_SECS = 30.0     # after a failed settings write, wait this long before trying again
BACKEND_RETRY_SECS = 10.0
CELEBRATE_COOLDOWN = 60.0
MIN_RECORD_WPM = 20
GREET_DELAY = 1.5
BUTTERFLY_GAP = (40.0, 110.0)    # seconds between butterfly visits while you rest
FIREFLY_GAP = (2.5, 5.0)

MODE_LABELS = {
    "taskbar": "📌 Dock to Taskbar",
    "active_window": "🪟 Perch on Active Window",
    "free": "🪶 Free Floating",
}
SIZE_LABELS = {3: "Small (48px)", 4: "Medium (64px)", 5: "Large (80px)", 6: "Extra Large (96px)"}


def clamp(value, low, high):
    return max(low, min(high, value))


class TypingCompanionApp:
    def __init__(self, settings_path=None, stats_path=None, start_input=True, demo=False,
                 clock=time.monotonic, prefer_hook=False, rng=None):
        home = core.data_dir()
        self.settings_path = settings_path or os.path.join(home, "settings.json")
        self.cfg = core.load_settings(self.settings_path)
        # --demo keeps its fake typing in memory, away from your real records.
        self.stats = core.Stats(None if demo else (stats_path or os.path.join(home, "stats.json")))
        self.clock = clock
        self.rng = rng or random.Random()
        self.meter = core.TypingMeter(clock=clock)
        self.backend = None
        self.prefer_hook = prefer_hook
        self._hook_failures = 0
        self.demo = demo
        self.garden_boost = 25 if demo else 1          # the demo grows flowers 25x faster
        self.garden = garden.Garden(self.stats.day, self.stats.keys_today * self.garden_boost)
        self.coach = cozy.BreakCoach(self.cfg["break_minutes"])
        now = clock()

        # Animation state
        self.mood = "idle"
        self.paw = False
        self.hop_until = 0.0
        self.hop_rows = 1
        self.blink_until = 0.0
        self.next_blink = now + self.rng.uniform(3.0, 8.0)
        self.wpm_shown = 0.0
        self.particles = []
        self.butterflies = []
        self.next_butterfly = now + self.rng.uniform(15.0, 40.0)
        self.next_firefly = now
        self._greet_at = now + GREET_DELAY
        self._slept_since = None
        self._seen_seq = 0
        self._seen_total = 0
        self._run_start_best = self.stats.best_wpm
        self._celebrated = False
        self._next_celebrate = 0.0
        self._last_step = now
        self._frame_name = "sit_a"
        self._shown_item = None             # (image, y) last pushed to the canvas
        self._badge_state = None
        self._garden_key = None
        self._fx_live = set()               # canvas tags of the effects currently drawn
        self._fx_serial = 0
        self._content_top = 0               # window y of the topmost visible thing (badge or head)
        self._images = {}

        # Position / interaction state
        self.win_x = self.win_y = 0.0
        self._applied_geo = None
        self._target = None
        self._target_at = 0.0
        self._placed_once = False
        self._press = None
        self._dragging = False
        self._suppress_release = False
        self._pet_job = None
        self._tick_job = None
        self._menu_open = False
        self._hidden = False
        self._closing = False
        self._shut = False
        self._hwnd = 0
        self._next_housekeeping = 0.0
        self._next_stats_flush = now + STATS_FLUSH_SECS
        self._backend_retry_at = 0.0
        self._settings_dirty = False
        self._settings_retry_at = 0.0
        self._demo_acc = 0.0
        self._demo_t0 = now
        self._demo_napped = -1

        self.root = tk.Tk()
        self.root.withdraw()                # stay hidden until we've positioned it
        self.root.report_callback_exception = self._on_tk_error
        self.family = theme.pick_family(tkfont.families(self.root))
        self._init_metrics()
        self._init_window()
        self._init_canvas()
        self._init_menu()
        self.bubble = Bubble(self.root, tkfont.Font(root=self.root, family=self.family, size=10), self.ui)

        if start_input:
            self.backend = keyboard_input.start_backend(self.meter, prefer_pynput=prefer_hook)

        self.step()
        if not self._hidden:                # a fullscreen app may already be running
            self._show()
        self._tick()

    # ═════════════════════════════════════════════════════════
    #  Setup
    # ═════════════════════════════════════════════════════════
    def _init_metrics(self):
        self.ui = max(1.0, self.root.winfo_fpixels("1i") / 96.0)      # display scale (1.0 = 100%)
        self.px = max(1, round(self.cfg["scale"] * self.ui))           # screen px per sprite pixel
        self.spr = sprites.SPRITE_SIZE * self.px
        self.pad_x = PAD_COLS * self.px
        self.head = HEAD_ROWS * self.px
        self.win_w = self.spr + 2 * self.pad_x
        self.win_h = self.head + self.spr
        self.fx_px = max(2, self.px // 2)
        self.fly_px = max(2, round(self.px * 0.75))
        self.font = tkfont.Font(root=self.root, family=self.family, size=max(7, self.cfg["scale"] * 2),
                                weight="bold")
        self.font_h = self.font.metrics("linespace")

    def _init_window(self):
        root = self.root
        root.title("TypingCompanion")
        root.overrideredirect(True)
        for attr, value in (("-topmost", True), ("-transparentcolor", sprites.TRANSP)):
            try:
                root.attributes(attr, value)
            except tk.TclError:             # e.g. colour keys aren't supported off Windows
                log.debug("window attribute %s unsupported", attr)
        root.configure(bg=sprites.TRANSP)
        root.protocol("WM_DELETE_WINDOW", self.quit)

    def _init_canvas(self):
        self.canvas = tk.Canvas(self.root, width=self.win_w, height=self.win_h, bg=sprites.TRANSP,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._create_items()
        canvas = self.canvas
        canvas.bind("<Button-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_motion)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Double-Button-1>", self._on_double)
        canvas.bind("<Button-3>", self._show_menu)

    def _create_items(self):
        self.sprite_item = self.canvas.create_image(self.pad_x, self.head, anchor="nw")
        self._shown_item = None
        self._badge_state = None
        self._garden_key = None
        self._fx_live = set()

    def _styled_menu(self, parent):
        menu = tk.Menu(parent, tearoff=0, font=(self.family, 10))
        for option, value in theme.MENU_STYLE.items():
            try:
                menu.configure(**{option: value})
            except tk.TclError:             # a platform may not support every option
                pass
        return menu

    def _init_menu(self):
        self.menu = self._styled_menu(self.root)
        self.var_char = tk.StringVar(self.root, value=self.cfg["character"])
        self.var_mode = tk.StringVar(self.root, value=self.cfg["dock_mode"])
        self.var_scale = tk.IntVar(self.root, value=self.cfg["scale"])
        self.var_wpm = tk.BooleanVar(self.root, value=self.cfg["show_wpm"])
        self.var_fullscreen = tk.BooleanVar(self.root, value=self.cfg["hide_fullscreen"])
        self.var_garden = tk.BooleanVar(self.root, value=self.cfg["garden"])
        self.var_messages = tk.BooleanVar(self.root, value=self.cfg["messages"])
        self.var_break = tk.IntVar(self.root, value=self.cfg["break_minutes"])
        self.var_autostart = tk.BooleanVar(self.root, value=False)

        self.menu.add_command(label=self._menu_header(), state="disabled")
        self.menu.add_separator()

        char_menu = self._styled_menu(self.menu)
        for key, char in sprites.CHARACTERS.items():
            char_menu.add_radiobutton(label=char["name"], variable=self.var_char, value=key,
                                      command=lambda k=key: self.set_character(k))
        self.menu.add_cascade(label="Character", menu=char_menu)

        mode_menu = self._styled_menu(self.menu)
        for key in core.DOCK_MODES:
            mode_menu.add_radiobutton(label=MODE_LABELS[key], variable=self.var_mode, value=key,
                                      command=lambda k=key: self.set_dock_mode(k))
        self.menu.add_cascade(label="Positioning Mode", menu=mode_menu)

        size_menu = self._styled_menu(self.menu)
        for scale in core.SCALES:
            size_menu.add_radiobutton(label=SIZE_LABELS[scale], variable=self.var_scale, value=scale,
                                      command=lambda s=scale: self.set_scale(s))
        self.menu.add_cascade(label="Size", menu=size_menu)

        self.menu.add_separator()
        self.menu.add_command(label="🌷 Today's Journal", command=self.show_journal)
        self.menu.add_checkbutton(label="Spring Garden & Visitors", variable=self.var_garden,
                                  command=self._on_garden_toggle)
        self.menu.add_checkbutton(label="Friendly Messages", variable=self.var_messages,
                                  command=self._on_messages_toggle)
        break_menu = self._styled_menu(self.menu)
        for minutes in core.BREAK_CHOICES:
            label = f"Every {minutes} minutes" if minutes else "Off"
            break_menu.add_radiobutton(label=label, variable=self.var_break, value=minutes,
                                       command=lambda m=minutes: self.set_break_minutes(m))
        self.menu.add_cascade(label="Stretch Reminders", menu=break_menu)

        self.menu.add_separator()
        self.menu.add_checkbutton(label="Show WPM Badge", variable=self.var_wpm, command=self._on_wpm_toggle)
        self.menu.add_checkbutton(label="Hide During Fullscreen Apps", variable=self.var_fullscreen,
                                  command=self._on_fullscreen_toggle)
        if winutil.IS_WINDOWS:
            self.menu.add_checkbutton(label="Start with Windows", variable=self.var_autostart,
                                      command=self._on_autostart_toggle)
        self.menu.add_separator()
        self.menu.add_command(label="Snap to Taskbar", command=self.snap_to_taskbar)
        self.menu.add_command(label="Take a Nap", command=self.nap)
        self.menu.add_command(label="Wake Up", command=self.wake_up)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

    def _menu_header(self):
        return f"✿  {self.stats.summary()}"

    def _show(self):
        """Reveal the window (also used when a fullscreen app ends)."""
        self.root.deiconify()
        self.root.update_idletasks()
        self._hwnd = winutil.toplevel_hwnd(self.root.winfo_id())
        winutil.make_overlay(self._hwnd)
        self._hidden = False

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self._shutdown()

    # ═════════════════════════════════════════════════════════
    #  Main loop
    # ═════════════════════════════════════════════════════════
    def _tick(self):
        if self._closing:
            return
        busy = False
        try:
            self.step()
            busy = (self.mood == "typing" or self._dragging or self._moving()
                    or any(fx.lively for fx in self.particles) or any(b.lively for b in self.butterflies))
        except Exception:
            log.exception("update failed")      # keep animating even if one frame goes wrong
        try:
            if self._tick_job is not None:              # never run two loops side by side
                self.root.after_cancel(self._tick_job)
            self._tick_job = self.root.after(TICK_BUSY_MS if busy else TICK_CALM_MS, self._tick)
        except tk.TclError:
            pass

    def step(self, now=None):
        """One update + render pass. Public so tests can drive time deterministically."""
        now = self.clock() if now is None else now
        dt = clamp(now - self._last_step, 0.0, 0.1)
        self._last_step = now
        if self.demo:
            self._demo_feed(now, dt)
        snap = self.meter.snapshot(now)
        self._account(snap, now)
        self._animate(snap, now, dt)
        self._ambient(now)
        self._update_position(now, dt)
        self._update_effects(dt)
        self._render(now)
        self._update_bubble(now)
        self._housekeeping(now)
        return snap

    def _moving(self):
        return self.cfg["dock_mode"] == "active_window" and self._target is not None and (
            abs(self._target[0] - self.win_x) > 1 or abs(self._target[1] - self.win_y) > 1)

    # ── words ────────────────────────────────────────────────
    def say(self, text, icon=None, secs=5.0, priority=1, friendly=True):
        """Show a speech bubble. `friendly` ones respect the Friendly Messages switch."""
        if (friendly and not self.cfg["messages"]) or self._hidden or not text:
            return False
        return self.bubble.say(text, self.clock(), icon=icon, secs=secs, priority=priority)

    def show_journal(self):
        self.say(cozy.journal(self.stats, self.garden), "flower", secs=6.0, priority=3, friendly=False)

    def _update_bubble(self, now):
        if not self.bubble.text and not self.bubble.visible:
            return
        anchor_x = self.win_x + self.pad_x + self.spr / 2
        top_y = self.win_y + self._content_top - int(2 * self.ui)
        bottom_y = self.win_y + self.win_h
        _mon, work = self._work_area_near(anchor_x, bottom_y - 1)
        self.bubble.update(now, anchor_x, top_y, bottom_y, work, allowed=not self._hidden)

    # ── stats, records, garden, breaks ───────────────────────
    def _account(self, snap, now):
        if snap.total != self._seen_total:
            self.stats.add_keys(snap.total - self._seen_total)
            self._seen_total = snap.total
        if snap.mood == "typing" and snap.age >= core.WPM_SUSTAINED and snap.wpm > self.stats.best_wpm:
            self.stats.record_wpm(snap.wpm)
            if (not self._celebrated and now >= self._next_celebrate
                    and snap.wpm >= max(MIN_RECORD_WPM, self._run_start_best + 2)):
                self._celebrate(now, snap.wpm)
        for event, slot in self.garden.update(self.stats.day, self.stats.keys_today * self.garden_boost):
            if event == "bloom" and self.cfg["garden"]:
                self._bloom_puff(slot)
                self.say(cozy.bloom_message(self.garden.bloomed, garden.SLOTS), "flower", priority=2)
        self.coach.minutes = self.cfg["break_minutes"]
        if self.coach.update(now, snap.mood == "typing", snap.idle_for):
            self.say(cozy.break_message(self.cfg["break_minutes"], self.rng), "cup", secs=14.0,
                     priority=2, friendly=False)
        if self._greet_at is not None and now >= self._greet_at:
            self._greet_at = None
            text, icon = cozy.greeting(time.localtime().tm_hour)
            self.say(text, icon, secs=5.0, priority=1)

    def _celebrate(self, now, wpm):
        self._celebrated = True
        self._next_celebrate = now + CELEBRATE_COOLDOWN
        self.say(cozy.best_message(wpm), "star", secs=4.0, priority=3)
        cx, top = self.pad_x + self.spr / 2, self.head + 2 * self.px
        for i in range(28):
            shape = "spark" if i % 3 == 0 else "petal"
            colors = None if shape == "spark" else (self.rng.choice(sprites.CELEBRATION_COLORS),)
            self.particles.append(Particle(
                cx + self.rng.uniform(-3, 3) * self.px, top,
                self.rng.uniform(-9, 9) * self.px, self.rng.uniform(-15, -6) * self.px,
                self.rng.uniform(0.9, 1.5), shape, colors, ay=16 * self.px,
                sway=self.px, sway_hz=self.rng.uniform(0.8, 1.6), phase=self.rng.uniform(0, 6.3)))

    # ── animation state ──────────────────────────────────────
    def _animate(self, snap, now, dt):
        mood = snap.mood
        if mood != self.mood:
            previous, self.mood = self.mood, mood
            if mood == "sleeping":
                self._slept_since = now
            if mood == "typing":
                self._run_start_best = self.stats.best_wpm
                self._celebrated = False
            if previous == "sleeping":
                if mood == "typing":
                    self._startle(now)
                if self._slept_since is not None and now - self._slept_since >= cozy.WELCOME_BACK_AFTER:
                    self.say("Welcome back! I kept your garden company.", "sun", secs=4.0)
                self._slept_since = None
        if snap.press_seq != self._seen_seq:        # a real keystroke: swap paws right now
            self._seen_seq = snap.press_seq
            self.paw = not self.paw
            self.hop_until = now + HOP_SECS
            self.hop_rows = 1

        target = snap.wpm if mood == "typing" else 0.0
        self.wpm_shown += (target - self.wpm_shown) * min(1.0, dt * 6.0)
        if mood != "typing" and self.wpm_shown < 0.5:
            self.wpm_shown = 0.0

        if mood == "idle" and now >= self.next_blink:
            self.blink_until = now + 0.16
            self.next_blink = now + self.rng.uniform(3.5, 8.0)
        if mood == "typing" and self.wpm_shown >= core.WPM_FAST and self.rng.random() < dt * 9.0:
            self._spawn_turbo()

    def _startle(self, now):
        self.hop_until = now + 0.28
        self.hop_rows = 2
        self.particles.append(Particle(
            self.pad_x + self.spr * 0.72, self.head - self.px, 0, -2 * self.px, 0.7, "bang"))

    def _head_y(self):
        frame = sprites.CHARACTERS[self.cfg["character"]]["frames"][self._frame_name]
        return self.head + sprites.first_row(frame) * self.px

    def _spawn_turbo(self):
        """Turbo typing: blossom petals puff up from the keyboard, with the odd sparkle."""
        side = self.rng.choice((-1, 1))
        x = self.pad_x + self.spr / 2 + side * self.rng.uniform(3.5, 7.5) * self.px
        if self.rng.random() < 0.25:
            char = sprites.CHARACTERS[self.cfg["character"]]
            self.particles.append(Particle(
                x, self.head + self.rng.randint(1, 8) * self.px, side * self.rng.uniform(0.5, 2) * self.px,
                -self.rng.uniform(3, 7) * self.px, self.rng.uniform(0.45, 0.8), "spark",
                (char["sparkle"], "#fffbe6"), blinks=True))
            return
        self.particles.append(Particle(
            x, self.head + self.rng.uniform(8, 13) * self.px, side * self.rng.uniform(1, 4) * self.px,
            -self.rng.uniform(5, 9) * self.px, self.rng.uniform(0.8, 1.3), "petal",
            (self.rng.choice(sprites.PETAL_COLORS),), ay=7 * self.px, sway=self.px,
            sway_hz=self.rng.uniform(0.8, 1.5), phase=self.rng.uniform(0, 6.3)))

    def _spawn_hearts(self):
        for _unused in range(5):
            self.particles.append(Particle(
                self.pad_x + self.rng.randint(3, 11) * self.px, self.head + self.rng.randint(0, 3) * self.px,
                self.rng.uniform(-1.5, 1.5) * self.px, -self.rng.uniform(4, 7) * self.px,
                self.rng.uniform(0.8, 1.2), "heart", sway=self.px * 0.6, sway_hz=1.2,
                phase=self.rng.uniform(0, 6.3)))

    def _flower_top(self, slot):
        rows = sprites.flower_rows(self.garden.kinds[slot], self.garden.stages[slot])
        return GARDEN_COLS[slot] * self.px + 1.5 * self.px, self.win_h - max(1, len(rows)) * self.px

    def _bloom_puff(self, slot):
        x, y = self._flower_top(slot)
        for _unused in range(6):
            self.particles.append(Particle(
                x + self.rng.uniform(-1, 1) * self.px, y, self.rng.uniform(-3, 3) * self.px,
                -self.rng.uniform(3, 6) * self.px, self.rng.uniform(0.6, 1.0), "spark", blinks=True))

    def _ambient(self, now):
        """Butterflies visit while you rest; fireflies glow while the companion sleeps."""
        if not self.cfg["garden"] or self.mood == "typing":
            return
        if not self.butterflies and now >= self.next_butterfly:
            self.next_butterfly = now + self.rng.uniform(*BUTTERFLY_GAP)
            self._spawn_butterfly()
        if self.mood == "sleeping" and now >= self.next_firefly:
            self.next_firefly = now + self.rng.uniform(*FIREFLY_GAP)
            if sum(1 for p in self.particles if p.shape == "firefly") < 3:
                self.particles.append(Particle(
                    self.rng.uniform(self.pad_x - 2 * self.px, self.pad_x + self.spr + 2 * self.px),
                    self.head + self.rng.uniform(2, 10) * self.px, self.rng.uniform(-1, 1) * self.px,
                    -self.rng.uniform(0.3, 1.5) * self.px, self.rng.uniform(3.0, 5.0), "firefly",
                    sway=self.px * 1.5, sway_hz=0.4, phase=self.rng.uniform(0, 6.3), pulse_hz=0.8))

    def _spawn_butterfly(self):
        u = self.fly_px
        side = self.rng.choice((-1, 1))
        start = (-6 * u if side < 0 else self.win_w + u, self.head + self.rng.uniform(0, 3) * self.px)
        bloomed = [slot for slot, stage in enumerate(self.garden.stages) if stage >= sprites.FLOWER_STAGES]
        if bloomed and self.rng.random() < 0.6:
            fx, fy = self._flower_top(self.rng.choice(bloomed))
            rest = (fx - 2.5 * u, fy - 4 * u)
        else:                                   # perch on the companion's head
            rest = (self.pad_x + self.spr / 2 - 2.5 * u, max(0.0, self._head_y() - 4 * u))
        leave = (self.win_w + 8 * u if side < 0 else -8 * u, self.rng.uniform(-2, 1) * self.px)
        self.butterflies.append(Butterfly(start, rest, leave, self.rng.choice(sprites.BUTTERFLY_WINGS),
                                          u, rest_secs=self.rng.uniform(3.0, 6.0)))

    def _update_effects(self, dt):
        self.particles = [p for p in self.particles if p.step(dt)][-90:]
        self.butterflies = [b for b in self.butterflies if b.step(dt)]

    # ── rendering ────────────────────────────────────────────
    def _current_frame_name(self, now):
        if self.mood == "sleeping":
            return "sleep_a" if int(now / SLEEP_FLIP_SECS) % 2 == 0 else "sleep_b"
        if self.mood == "typing":
            return "type_l" if self.paw else "type_r"
        base = "a" if int(now / IDLE_FLIP_SECS) % 2 == 0 else "b"
        return f"{'blink' if now < self.blink_until else 'sit'}_{base}"

    def _image_for(self, name):
        key = (self.cfg["character"], name, self.px)
        img = self._images.get(key)
        if img is None:
            char = sprites.CHARACTERS[self.cfg["character"]]
            small = tk.PhotoImage(master=self.root, width=sprites.SPRITE_SIZE, height=sprites.SPRITE_SIZE)
            small.put(sprites.to_put_data(char["frames"][name], char["palette"]))
            img = small.zoom(self.px) if self.px > 1 else small
            self._images[key] = img
        return img

    def _render(self, now):
        c = self.canvas
        self._draw_garden()
        name = self._current_frame_name(now)
        self._frame_name = name
        hop = self.hop_rows if now < self.hop_until else 0
        y = self.head - hop * self.px
        item = (self._image_for(name), y)
        if item != self._shown_item:                # only touch the canvas when something changed
            c.itemconfigure(self.sprite_item, image=item[0])
            c.coords(self.sprite_item, self.pad_x, y)
            self._shown_item = item

        # The WPM badge: a soft pastel pill hugging the top of whatever pose is showing.
        text, style = "", theme.BADGE_CALM
        if self.cfg["show_wpm"] and self.mood == "typing":
            text = f"{int(round(self.wpm_shown))} WPM"
            if self.wpm_shown >= core.WPM_FAST:
                style = theme.BADGE_TURBO
        pill_h = self.font_h + 2 * self.fx_px
        head_y = self._head_y() - hop * self.px
        by = max(pill_h, head_y - int(2 * self.ui))
        badge = (text, style, by)
        if badge != self._badge_state:
            self._badge_state = badge
            c.delete("badge")
            if text:
                fill, edge, ink = style
                s = self.fx_px
                w = self.font.measure(text) + 6 * s
                cx = self.pad_x + self.spr / 2
                draw_round_rect(c, int(cx - w / 2), by - pill_h, int(cx + w / 2), by, s, fill, edge, tags="badge")
                c.create_text(cx, by - pill_h / 2, text=text, font=self.font, fill=ink, tags="badge")
        self._content_top = (by - pill_h) if text else head_y

        if self.particles or self.butterflies or self._fx_live:
            live = set()
            for fx in self.particles:
                live.add(self._draw_effect(fx, self.fx_px))
            for fx in self.butterflies:
                live.add(self._draw_effect(fx, self.fly_px))
            for tag in self._fx_live - live:          # effects that finished this frame
                c.delete(tag)
            self._fx_live = live

    def _draw_effect(self, fx, size):
        """Effects keep their canvas items and are moved, not redrawn, every frame."""
        c = self.canvas
        x, y = (int(v) for v in fx.position())
        shown = fx.visible()
        drawn = fx.drawn
        if drawn is None or drawn[0] != fx.shape:     # new, or a butterfly flapped its wings
            if fx.tag is None:
                self._fx_serial += 1
                fx.tag = f"fx{self._fx_serial}"
            else:
                c.delete(fx.tag)
            draw_shape(c, fx.shape, x, y, size, fx.colors, tags=("fx", fx.tag))
            if not shown:
                c.itemconfigure(fx.tag, state="hidden")
        else:
            if (x, y) != drawn[1:3]:
                c.move(fx.tag, x - drawn[1], y - drawn[2])
            if shown != drawn[3]:
                c.itemconfigure(fx.tag, state="normal" if shown else "hidden")
        fx.drawn = (fx.shape, x, y, shown)
        return fx.tag

    def _draw_garden(self):
        key = (self.cfg["garden"], tuple(self.garden.stages), tuple(self.garden.kinds), self.px)
        if key == self._garden_key:
            return
        self._garden_key = key
        c, px = self.canvas, self.px
        c.delete("garden")
        if not self.cfg["garden"]:
            return
        for slot, col in enumerate(GARDEN_COLS):
            kind = self.garden.kinds[slot]
            rows = sprites.flower_rows(kind, self.garden.stages[slot])
            colors = sprites.flower_colors(kind)
            top = self.win_h - len(rows) * px
            for ry, row in enumerate(rows):
                for rx, cell in enumerate(row):
                    if cell in colors:
                        x0, y0 = (col + rx) * px, top + ry * px
                        c.create_rectangle(x0, y0, x0 + px, y0 + px, fill=colors[cell], outline="",
                                           tags="garden")
        c.tag_lower("garden")

    # ═════════════════════════════════════════════════════════
    #  Positioning
    # ═════════════════════════════════════════════════════════
    def _screen_area(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return 0, 0, sw, sh

    def _work_area_near(self, x, y):
        """(monitor rect, work-area rect) of the monitor nearest to a screen point."""
        areas = winutil.monitor_areas_at(x, y)
        if areas:
            return areas
        work = winutil.primary_work_area()
        if work:
            return self._screen_area(), work
        ml, mt, mr, mb = self._screen_area()
        return (ml, mt, mr, mb), (ml, mt, mr, mb - NO_TASKBAR_STRIP)

    def _default_dock_x(self):
        _mon, (wl, _wt, wr, _wb) = self._work_area_near(*self._primary_probe())
        return wr - self.spr - int(DOCK_MARGIN * self.ui)

    def _primary_probe(self):
        work = winutil.primary_work_area()
        if work:
            return work[2] - 1, work[3] - 1
        _l, _t, r, b = self._screen_area()
        return r - 1, b - 1

    def _dock_target(self):
        """Window position that stands the sprite on the taskbar line of its monitor."""
        dock_x = self.cfg["dock_x"]
        if dock_x is None:
            dock_x = self._default_dock_x()
        probe_y = self.win_y + self.win_h / 2 if self._placed_once else self._primary_probe()[1]
        _mon, (wl, _wt, wr, wb) = self._work_area_near(dock_x + self.spr / 2, probe_y)
        sx = clamp(dock_x, wl, max(wl, wr - self.spr))
        return sx - self.pad_x, wb - self.win_h

    def _perch_target(self):
        rect = winutil.perch_rect()
        if rect is None:
            return None                              # nothing worth perching on: stay put
        wl, wt, wr, _wb = rect
        _mon, (al, at, ar, _ab) = self._work_area_near((wl + wr) // 2, wt)
        # Keep the whole window (garden included) clear of the caption buttons.
        sx = max(wl + int(20 * self.ui), wr - self.spr - self.pad_x - int(CAPTION_BUTTONS * self.ui))
        sx = clamp(sx, al, max(al, ar - self.spr))
        sy = max(at, wt - self.spr + int(PERCH_SINK * self.ui))   # maximised: no room above, stay on-screen
        return sx - self.pad_x, sy - self.head

    def _free_target(self):
        fx, fy = self.cfg["free_x"], self.cfg["free_y"]
        if fx is None or fy is None:
            return self._dock_target()
        (ml, mt, mr, mb), _work = self._work_area_near(fx + self.spr / 2, fy + self.spr / 2)
        sx = clamp(fx, ml, max(ml, mr - self.spr))
        sy = clamp(fy, mt, max(mt, mb - self.spr))
        return sx - self.pad_x, sy - self.head

    def _compute_target(self):
        mode = self.cfg["dock_mode"]
        if mode == "taskbar":
            return self._dock_target()
        if mode == "active_window":
            return self._perch_target()
        return self._free_target()

    def _update_position(self, now, dt, force=False):
        mode = self.cfg["dock_mode"]
        if force or now >= self._target_at:
            fresh = self._compute_target()
            if fresh is not None or mode != "active_window":
                self._target = fresh
            self._target_at = now + (0.08 if mode == "active_window" else 0.5)
        if self._target is None:
            if not self._placed_once:               # perching with nothing to perch on yet
                self._place(*self._dock_target())
            return
        tx, ty = self._target
        if mode == "active_window" and self._placed_once:
            k = min(1.0, dt * 14.0)                  # glide to the new perch
            nx = tx if abs(tx - self.win_x) < 1 else self.win_x + (tx - self.win_x) * k
            ny = ty if abs(ty - self.win_y) < 1 else self.win_y + (ty - self.win_y) * k
        else:
            nx, ny = tx, ty
        self._place(nx, ny)

    def _place(self, x, y):
        self.win_x, self.win_y = x, y
        ix, iy = int(round(x)), int(round(y))
        if self._applied_geo != (ix, iy, self.win_w, self.win_h):
            self.root.geometry(f"{self.win_w}x{self.win_h}+{ix}+{iy}")
            self._applied_geo = (ix, iy, self.win_w, self.win_h)
        self._placed_once = True

    def _sprite_xy(self):
        """Screen position of the sprite's top-left corner."""
        return self.win_x + self.pad_x, self.win_y + self.head

    # ═════════════════════════════════════════════════════════
    #  Mouse: drag, pet, journal, menu
    # ═════════════════════════════════════════════════════════
    def _on_press(self, event):
        self._press = (event.x_root, event.y_root, self.win_x, self.win_y)
        self._dragging = False

    def _on_motion(self, event):
        if self._press is None:
            return
        px0, py0, wx0, wy0 = self._press
        dx, dy = event.x_root - px0, event.y_root - py0
        if not self._dragging:
            if max(abs(dx), abs(dy)) < DRAG_THRESHOLD * self.ui:
                return
            self._dragging = True
            if self.cfg["dock_mode"] == "active_window":        # picking it up cancels the perch
                self._enter_free(wx0 + self.pad_x, wy0 + self.head)
        sx, sy = wx0 + dx + self.pad_x, wy0 + dy + self.head
        if self.cfg["dock_mode"] == "taskbar":
            _mon, (wl, _wt, wr, wb) = self._work_area_near(sx + self.spr / 2, wy0 + self.win_h / 2)
            if abs((sy + self.spr) - wb) > self._snap_distance():
                self._enter_free(sx, sy)                          # pulled well off the taskbar
            else:
                self.cfg["dock_x"] = int(clamp(sx, wl, max(wl, wr - self.spr)))
        elif self.cfg["dock_mode"] == "free":
            self.cfg["free_x"], self.cfg["free_y"] = int(sx), int(sy)
        self._settings_dirty = True
        self._update_position(self.clock(), 0.0, force=True)

    def _snap_distance(self):
        return 0.75 * self.spr

    def _on_release(self, _event):
        if self._suppress_release:
            self._suppress_release = False
            self._press = None
            return
        if self._dragging:
            self._dragging = False
            if self.cfg["dock_mode"] == "free":                   # dropped back near the taskbar: dock
                sx, sy = self._sprite_xy()
                _mon, (wl, _wt, wr, wb) = self._work_area_near(sx + self.spr / 2, sy + self.spr / 2)
                if abs((sy + self.spr) - wb) <= self._snap_distance():
                    self.cfg["dock_x"] = int(clamp(sx, wl, max(wl, wr - self.spr)))
                    self._set_mode("taskbar")
        elif self._press is not None:
            self._pet_job = self.root.after(DOUBLE_CLICK_MS, self._pet)
        self._press = None

    def _on_double(self, _event):
        if self._pet_job is not None:
            self.root.after_cancel(self._pet_job)
            self._pet_job = None
        self._suppress_release = True
        self.show_journal()

    def _pet(self):
        self._pet_job = None
        self._spawn_hearts()
        if self.mood != "sleeping":
            self.hop_until = self.clock() + 0.2
            self.hop_rows = 1
        if self.rng.random() < 0.4:
            self.say(cozy.pet_line(self.cfg["character"], self.rng), "heart", secs=2.6, priority=0)

    def _enter_free(self, sx, sy):
        self.cfg["free_x"], self.cfg["free_y"] = int(sx), int(sy)
        self._set_mode("free", reposition=False)

    def _show_menu(self, event):
        self._refresh_menu()
        previous = winutil.foreground_window()
        own = self._hwnd
        # A popup menu only dismisses properly when its owner is foreground; we hand focus
        # straight back to the window you were typing in afterwards.
        winutil.focus_window(own)
        self._menu_open = True
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu_open = False
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass
            if previous and previous != own and not self._closing:
                winutil.restore_foreground(previous)

    def _refresh_menu(self):
        self.menu.entryconfigure(0, label=self._menu_header())
        self.var_autostart.set(winutil.autostart_enabled())

    # ═════════════════════════════════════════════════════════
    #  Menu actions
    # ═════════════════════════════════════════════════════════
    def set_character(self, key):
        if key in sprites.CHARACTERS:
            self.cfg["character"] = key
            self.var_char.set(key)
            self._shown_item = None
            self._badge_state = None
            self._settings_dirty = True

    def _set_mode(self, mode, reposition=True):
        self.cfg["dock_mode"] = mode
        self.var_mode.set(mode)
        self._settings_dirty = True
        if reposition:
            self._update_position(self.clock(), 0.0, force=True)

    def set_dock_mode(self, mode):
        if mode not in core.DOCK_MODES:
            return
        if mode == "free" and self.cfg["free_x"] is None:
            sx, sy = self._sprite_xy()
            self.cfg["free_x"], self.cfg["free_y"] = int(sx), int(sy)
        if mode == "taskbar":
            self.cfg["dock_x"] = int(self._sprite_xy()[0]) if self._placed_once else self.cfg["dock_x"]
        self._set_mode(mode)

    def snap_to_taskbar(self):
        self.cfg["dock_x"] = None
        self._set_mode("taskbar")

    def set_scale(self, scale):
        if scale not in core.SCALES:
            return
        sx, sy = self._sprite_xy()
        feet = sy + self.spr                         # the line the sprite stands on
        self.cfg["scale"] = scale
        self.var_scale.set(scale)
        self.particles = []
        self.butterflies = []
        self._images.clear()
        self._init_metrics()
        self.canvas.config(width=self.win_w, height=self.win_h)
        self.canvas.delete("all")
        self._create_items()
        self._applied_geo = None
        self.win_x, self.win_y = sx - self.pad_x, feet - self.spr - self.head
        if self.cfg["dock_mode"] == "free":          # saved as the sprite's top-left: re-save for the new size
            self.cfg["free_x"], self.cfg["free_y"] = int(sx), int(feet - self.spr)
        self._settings_dirty = True
        self._update_position(self.clock(), 0.0, force=True)

    def set_break_minutes(self, minutes):
        if minutes in core.BREAK_CHOICES:
            self.cfg["break_minutes"] = minutes
            self.var_break.set(minutes)
            self.coach.minutes = minutes
            self._settings_dirty = True

    def _on_wpm_toggle(self):
        self.cfg["show_wpm"] = bool(self.var_wpm.get())
        self._badge_state = None
        self._settings_dirty = True

    def _on_fullscreen_toggle(self):
        self.cfg["hide_fullscreen"] = bool(self.var_fullscreen.get())
        self._settings_dirty = True

    def _on_garden_toggle(self):
        self.cfg["garden"] = bool(self.var_garden.get())
        if not self.cfg["garden"]:
            self.butterflies = []
            self.particles = [p for p in self.particles if p.shape != "firefly"]
        self._settings_dirty = True

    def _on_messages_toggle(self):
        self.cfg["messages"] = bool(self.var_messages.get())
        self._settings_dirty = True

    def _on_autostart_toggle(self):
        wanted = bool(self.var_autostart.get())
        if not winutil.set_autostart(wanted, SCRIPT_PATH):
            self.var_autostart.set(not wanted)

    def nap(self):
        self.meter.nap(self.clock())

    def wake_up(self):
        self.meter.wake(self.clock())

    # ═════════════════════════════════════════════════════════
    #  Housekeeping
    # ═════════════════════════════════════════════════════════
    def _housekeeping(self, now):
        if now < self._next_housekeeping:
            return
        self._next_housekeeping = now + HOUSEKEEPING_SECS

        hide = self.cfg["hide_fullscreen"] and winutil.fullscreen_app_running()
        if hide and not self._hidden:
            self.root.withdraw()
            self.bubble.hide()
            self._hidden = True
        elif not hide and self._hidden:
            self._show()
        # Re-assert "on top" (clicking the taskbar pushes us under it) - but never while our
        # menu is open, or the sprite would cover the menu.
        if not self._hidden and not self._menu_open:
            # The bubble goes second so it always sits above the companion.
            for hwnd, window, shown in ((self._hwnd, self.root, True),
                                        (self.bubble.hwnd, self.bubble.win, self.bubble.visible)):
                if shown and not winutil.keep_on_top(hwnd):
                    try:
                        window.lift()               # off Windows (or if SetWindowPos failed)
                    except tk.TclError:
                        pass

        if self.backend is not None and not self.backend.alive() and now >= self._backend_retry_at:
            if getattr(self.backend, "name", "") == "pynput":
                self._hook_failures += 1
            log.warning("keyboard backend stopped; restarting")
            self._backend_retry_at = now + BACKEND_RETRY_SECS
            self.backend.stop()
            # A hook that keeps dying is given up for polling, which always works.
            self.backend = keyboard_input.start_backend(
                self.meter, prefer_pynput=self.prefer_hook and self._hook_failures < 2)

        if self._settings_dirty and now >= self._settings_retry_at:
            if core.save_settings(self.settings_path, self.cfg):
                self._settings_dirty = False
            else:
                self._settings_retry_at = now + SAVE_RETRY_SECS
        if self.stats.dirty and now >= self._next_stats_flush:
            self.stats.save()
            self._next_stats_flush = now + STATS_FLUSH_SECS

    def _demo_feed(self, now, dt):
        """--demo: cycle through idle / slow / brisk / turbo / nap with synthetic keystrokes."""
        phases = ((4, 0.0), (6, 1.7), (6, 3.4), (8, 7.5), (4, 0.0), (7, -1.0))   # (secs, keys/s; -1 = nap)
        t = (now - self._demo_t0) % sum(p[0] for p in phases)
        cycle = int((now - self._demo_t0) // sum(p[0] for p in phases))
        for secs, rate in phases:
            if t < secs:
                break
            t -= secs
        if rate < 0:
            if self._demo_napped != cycle:
                self._demo_napped = cycle
                self.meter.nap(now)
                self.next_butterfly = min(self.next_butterfly, now + 1.0)   # show off a visitor
            return
        self._demo_acc += rate * dt
        while self._demo_acc >= 1.0:
            self._demo_acc -= 1.0
            vk = self.rng.randint(0x41, 0x5A)
            self.meter.key_down(vk, False, now)
            self.meter.key_up(vk)

    def _on_tk_error(self, exc, val, tb):
        log.error("Tk callback failed", exc_info=(exc, val, tb))

    # ═════════════════════════════════════════════════════════
    #  Shutdown
    # ═════════════════════════════════════════════════════════
    def quit(self):
        if self._closing:
            return
        self._closing = True
        self._shutdown()
        try:
            for job in (self._tick_job, self._pet_job):
                if job is not None:
                    self.root.after_cancel(job)
            self.root.destroy()
        except tk.TclError:
            pass

    def _shutdown(self):
        if self._shut:
            return
        self._shut = True
        if self.backend is not None:
            self.backend.stop()
        core.save_settings(self.settings_path, self.cfg)
        self.stats.save()


# ══════════════════════════════════════════════════════════════
#  Launcher
# ══════════════════════════════════════════════════════════════
def setup_logging():
    log.setLevel(logging.INFO)
    handlers = []
    try:
        os.makedirs(core.data_dir(), exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            os.path.join(core.data_dir(), "companion.log"), maxBytes=200_000, backupCount=1,
            encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:                      # pythonw has no console
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Taskbar Typing Companion")
    parser.add_argument("--demo", action="store_true",
                        help="animate with synthetic typing (idle / slow / brisk / turbo / nap); "
                             "nothing is saved to your stats")
    parser.add_argument("--no-input", action="store_true", help="don't watch the keyboard")
    parser.add_argument("--hook", action="store_true",
                        help="use a pynput keyboard hook instead of polling (needs `pip install pynput`)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    setup_logging()
    if tk is None:
        winutil.show_message("Typing Companion", "This Python has no tkinter, which the companion needs "
                             f"to draw itself.\n\nReinstall Python from python.org with the "
                             f"\"tcl/tk\" option ticked.\n\n({TK_IMPORT_ERROR})")
        return 1
    if not winutil.acquire_single_instance():
        winutil.show_message("Typing Companion", "Typing Companion is already running - "
                             "look for it near your taskbar.")
        return 1
    winutil.enable_dpi_awareness()
    winutil.attach_to_default_desktop()
    log.info("starting Typing Companion %s", __version__)
    try:
        app = TypingCompanionApp(start_input=not args.no_input, demo=args.demo, prefer_hook=args.hook)
    except Exception as exc:                        # under pythonw this would otherwise vanish silently
        log.exception("could not start")
        winutil.show_message("Typing Companion", f"Sorry - the companion couldn't start:\n{exc}\n\n"
                             f"Details: {os.path.join(core.data_dir(), 'companion.log')}")
        return 1
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
