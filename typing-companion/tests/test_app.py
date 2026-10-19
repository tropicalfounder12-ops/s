"""End-to-end tests of the window: real Tk widgets, fake clock, synthetic mouse events.

Needs tkinter and a display; on a headless box run them with `xvfb-run -a python -m unittest`.
"""
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from tests.helpers import FakeClock

import core
import sprites
import theme
import winutil


def tk_available():
    try:
        import tkinter
        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


HAVE_TK = tk_available()
if HAVE_TK:
    import companion


@unittest.skipUnless(HAVE_TK, "needs tkinter and a display (try: xvfb-run -a python -m unittest)")
class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self._old_home = os.environ.get("TYPING_COMPANION_HOME")
        os.environ["TYPING_COMPANION_HOME"] = self.home
        self.clock = FakeClock()
        self.app = self.make_app()

    def make_app(self):
        app = companion.TypingCompanionApp(start_input=False, clock=self.clock)
        app.root.update()
        return app

    def tearDown(self):
        self.app.quit()
        if self._old_home is None:
            os.environ.pop("TYPING_COMPANION_HOME", None)
        else:
            os.environ["TYPING_COMPANION_HOME"] = self._old_home
        shutil.rmtree(self.home, ignore_errors=True)

    # ── helpers ──────────────────────────────────────────────
    def key(self, vk=65):
        self.app.meter.key_down(vk, now=self.clock())
        self.app.meter.key_up(vk)

    def type_for(self, keys_per_sec, secs):
        for i in range(int(keys_per_sec * secs)):
            self.clock.advance(1.0 / keys_per_sec)
            self.key(65 + i % 20)
            self.app.step()

    def settle(self, secs=0.5, dt=0.05):
        for _ in range(int(secs / dt)):
            self.clock.advance(dt)
            self.app.step()

    def work_bottom(self):
        return self.app.root.winfo_screenheight() - companion.NO_TASKBAR_STRIP

    def sprite_bottom(self):
        return self.app.win_y + self.app.head + self.app.spr

    def mouse(self, seq, dx=0, dy=0, state=0):
        a = self.app
        cx, cy = int(a.pad_x + a.spr / 2), int(a.head + a.spr / 2)
        if seq.startswith("<ButtonPress") or seq.startswith("<Double"):
            self._origin = (int(a.win_x) + cx, int(a.win_y) + cy)
        a.canvas.event_generate(seq, x=cx, y=cy, rootx=self._origin[0] + dx,
                                rooty=self._origin[1] + dy, state=state)
        a.root.update()

    def drag(self, dx, dy, steps=6):
        self.mouse("<ButtonPress-1>")
        for i in range(1, steps + 1):
            self.mouse("<B1-Motion>", dx * i // steps, dy * i // steps, state=0x100)
        self.mouse("<ButtonRelease-1>", dx, dy)

    def wait_for(self, predicate, secs=1.5):
        end = time.time() + secs
        while time.time() < end:
            self.app.root.update()
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def shapes(self):
        return [p.shape for p in self.app.particles]

    def badge_text(self):
        c = self.app.canvas
        texts = [i for i in c.find_withtag("badge") if c.type(i) == "text"]
        return c.itemcget(texts[0], "text") if texts else None


class PlacementTests(AppTestCase):
    def test_stands_exactly_on_the_taskbar_line(self):
        a = self.app
        self.assertEqual(a.win_y + a.win_h, self.work_bottom())
        self.assertEqual(a.root.winfo_y() + a.root.winfo_height(), self.work_bottom())
        self.assertEqual(a.cfg["dock_mode"], "taskbar")

    def test_feet_stay_on_the_line_in_every_pose_and_character(self):
        for key in sprites.CHARACTERS:
            self.app.set_character(key)
            for mood in ("idle", "typing", "sleeping"):
                if mood == "sleeping":
                    self.app.meter.nap(self.clock())
                elif mood == "typing":
                    self.key()
                else:
                    self.app.meter.wake(self.clock())
                self.settle(0.2)
                self.assertEqual(self.app.mood, mood)
                frame = sprites.CHARACTERS[key]["frames"][self.app._frame_name]
                feet = self.app.win_y + self.app.head + (sprites.last_row(frame) + 1) * self.app.px
                self.assertEqual(feet, self.work_bottom(), f"{key}/{mood}")

    def test_changing_size_keeps_the_feet_on_the_line(self):
        for scale in (6, 3, 5, 4):
            self.app.set_scale(scale)
            self.app.root.update()
            self.assertEqual(self.app.px, round(scale * self.app.ui))
            self.assertEqual(self.sprite_bottom(), self.work_bottom(), scale)
            self.assertEqual(self.app.canvas.winfo_reqwidth(), self.app.win_w)
            self.assertEqual(self.app.root.winfo_width(), self.app.win_w)

    def test_changing_size_while_free_floating_keeps_the_feet_in_place(self):
        a = self.app
        a.set_dock_mode("free")
        a.cfg["free_x"], a.cfg["free_y"] = 200, 80
        a._update_position(self.clock(), 0, force=True)
        feet = self.sprite_bottom()
        a.set_scale(6)
        self.assertEqual(self.sprite_bottom(), feet)


class AnimationTests(AppTestCase):
    def test_mood_follows_typing_and_wakes_immediately(self):
        a = self.app
        self.assertEqual(a.step().mood, "idle")
        self.key()
        self.assertEqual(a.step().mood, "typing")
        self.clock.advance(core.IDLE_AFTER + 0.2)
        self.assertEqual(a.step().mood, "idle")
        self.clock.advance(core.SLEEP_AFTER)
        self.assertEqual(a.step().mood, "sleeping")
        self.assertIn(a._frame_name, ("sleep_a", "sleep_b"))
        # The very next step after a key press is awake and startled - no waiting for a slow
        # sleeping-animation tick (the original needed up to ~1.1 s).
        self.key()
        self.clock.advance(0.01)
        self.assertEqual(a.step().mood, "typing")
        self.assertIn(a._frame_name, ("type_l", "type_r"))
        self.assertIn("bang", self.shapes())

    def test_each_keystroke_swaps_paws_straight_away(self):
        names = []
        for _ in range(6):
            self.clock.advance(0.15)
            self.key()
            self.app.step()
            names.append(self.app._frame_name)
        self.assertEqual(set(names), {"type_l", "type_r"})
        self.assertTrue(all(a != b for a, b in zip(names, names[1:])), names)

    def test_held_key_does_not_swap_paws_or_count(self):
        self.app.meter.key_down(65, now=self.clock())           # pressed and still held
        self.app.step()
        before = (self.app._frame_name, self.app.meter.snapshot().total)
        for _ in range(20):
            self.clock.advance(0.03)
            self.app.meter.key_down(65, now=self.clock())      # auto-repeat, no key-up
            self.app.step()
        self.assertEqual((self.app._frame_name, self.app.meter.snapshot().total), before)
        self.assertEqual(self.app.mood, "typing")

    def test_badge_shows_wpm_only_while_typing_and_when_enabled(self):
        a = self.app
        self.assertIsNone(self.badge_text())
        self.type_for(5, 4)
        text = self.badge_text()
        self.assertRegex(text, r"^\d+ WPM$")
        self.assertAlmostEqual(int(text.split()[0]), 60, delta=12)
        self.assertEqual(a._badge_state[1], theme.BADGE_TURBO if a.wpm_shown >= core.WPM_FAST else theme.BADGE_CALM)
        a.var_wpm.set(False)
        a._on_wpm_toggle()
        self.type_for(5, 0.4)
        self.assertIsNone(self.badge_text())
        a.var_wpm.set(True)
        a._on_wpm_toggle()
        self.type_for(5, 0.4)
        self.assertIsNotNone(self.badge_text())
        self.settle(core.IDLE_AFTER + 1)
        self.assertIsNone(self.badge_text())

    def test_badge_turns_into_a_blossom_pill_in_turbo(self):
        self.type_for(2, 6)
        self.assertEqual(self.app._badge_state[1], theme.BADGE_CALM)
        self.type_for(9, 6)
        self.assertEqual(self.app._badge_state[1], theme.BADGE_TURBO)
        pill = [i for i in self.app.canvas.find_withtag("badge") if self.app.canvas.type(i) == "rectangle"]
        self.assertTrue(pill)
        x0, y0, x1, y1 = self.app.canvas.bbox("badge")
        self.assertGreaterEqual(y0, 0)                          # fits inside the window
        self.assertLessEqual(y1, self.app._head_y() + 2)        # sits on top of the head

    def test_petals_only_in_turbo_and_never_over_the_badge(self):
        self.app.rng.seed(1)
        self.app.stats.best_wpm = 500                           # no personal-best confetti here
        self.type_for(2, 6)                                     # ~24 WPM
        self.assertFalse({"petal", "spark"} & set(self.shapes()))
        fresh = []
        for _ in range(8):                                      # ~96 WPM
            before = set(map(id, self.app.particles))
            self.type_for(8, 1.0)
            fresh += [p for p in self.app.particles if id(p) not in before]
        kinds = {p.shape for p in fresh}
        self.assertIn("petal", kinds)
        a = self.app
        centre = a.pad_x + a.spr / 2
        for p in fresh:        # the badge is centred above the head; petals puff out beside it
            if p.shape in ("petal", "spark"):
                self.assertGreater(abs(p.x - centre), 2 * a.px)

    def test_idle_sprite_blinks_now_and_then(self):
        self.app.meter.wake(self.clock())
        seen = set()
        for _ in range(400):
            self.clock.advance(0.05)
            self.app.step()
            seen.add(self.app._frame_name)
        self.assertTrue({"sit_a", "sit_b", "blink_a"} <= seen or {"sit_a", "sit_b", "blink_b"} <= seen, seen)

    def test_new_personal_best_celebrates_once_per_typing_run(self):
        a = self.app
        a.stats.best_wpm = 30.0
        a._run_start_best = 30.0
        self.type_for(8, 4.5)                                   # ~96 WPM but not yet "sustained"
        self.assertNotIn("best", a.bubble.text)
        self.type_for(8, 1.5)
        self.assertIn("personal best", a.bubble.text)
        self.assertEqual(a.bubble.icon, "star")
        self.assertGreater(len([p for p in a.particles if p.shape in ("petal", "spark")]), 15)
        self.assertGreater(a.stats.best_wpm, 80)
        first_until = a.bubble.until
        self.type_for(10, 1.0)                                  # the run keeps climbing...
        self.assertEqual(a.bubble.until, first_until)           # ...but doesn't re-trigger
        self.settle(5.0)
        self.assertFalse(a.bubble.visible)

    def test_a_second_run_inside_the_cooldown_does_not_celebrate_again(self):
        a = self.app
        a.stats.best_wpm = 30.0
        a._run_start_best = 30.0
        self.type_for(8, 6.5)
        self.assertIn("best", a.bubble.text)
        self.settle(core.IDLE_AFTER + core.WPM_WINDOW + 1)
        self.assertFalse(a.bubble.visible)
        self.type_for(12, 7)                                    # an even faster run, 15 s later
        self.assertGreater(a.stats.best_wpm, 100)
        self.assertNotIn("best", a.bubble.text)                 # cooldown (60 s) still running

    def test_no_celebration_for_a_slow_or_short_run(self):
        a = self.app
        self.type_for(8, 3)                                     # fast but not sustained
        self.assertNotIn("best", a.bubble.text)
        self.settle(core.WPM_WINDOW + core.IDLE_AFTER)
        self.type_for(1, 8)                                     # sustained but below the minimum
        self.assertNotIn("best", a.bubble.text)

    def test_keystrokes_are_counted_in_stats(self):
        self.type_for(5, 3)
        total = self.app.meter.snapshot().total
        self.assertEqual(self.app.stats.keys_today, total)
        self.assertGreater(total, 10)


class MouseTests(AppTestCase):
    def test_click_pets_after_the_double_click_window(self):
        self.mouse("<ButtonPress-1>")
        self.mouse("<ButtonRelease-1>")
        self.assertNotIn("heart", self.shapes())                # waiting to see if it's a double-click
        self.assertTrue(self.wait_for(lambda: "heart" in self.shapes()))
        self.assertEqual(self.shapes().count("heart"), 5)

    def test_double_click_opens_the_journal_and_does_not_pet(self):
        a = self.app
        a.stats.add_keys(1234)
        for seq in ("<ButtonPress-1>", "<ButtonRelease-1>", "<ButtonPress-1>", "<ButtonRelease-1>"):
            self.mouse(seq)                                     # Tk turns the 2nd press into a Double
        self.assertTrue(a.bubble.text.startswith("Today: 1,234 keys"))
        self.assertTrue(a.cfg["show_wpm"])                      # the badge setting is untouched
        self.wait_for(lambda: False, 0.5)
        self.assertNotIn("heart", self.shapes())
        self.assertIsNone(a._pet_job)

    def test_drag_slides_along_the_taskbar_with_height_locked(self):
        a = self.app
        y0, x0 = a.win_y, a.win_x
        self.drag(-120, 6)                                      # a little vertical wobble is ignored
        a.root.update()
        self.assertEqual(a.cfg["dock_mode"], "taskbar")
        self.assertEqual(a.win_y, y0)
        self.assertAlmostEqual(a.win_x, x0 - 120, delta=2)
        self.assertIsNotNone(a.cfg["dock_x"])
        self.assertEqual(self.sprite_bottom(), self.work_bottom())

    def test_dock_position_survives_a_size_change(self):
        a = self.app
        self.drag(-150, 0)
        left = a.win_x + a.pad_x
        a.set_scale(6)
        self.assertAlmostEqual(a.win_x + a.pad_x, left, delta=1)

    def test_pulling_off_the_taskbar_frees_it_and_dropping_back_redocks(self):
        a = self.app
        self.drag(-60, -160)
        self.assertEqual(a.cfg["dock_mode"], "free")
        self.assertEqual(a.var_mode.get(), "free")
        self.assertLess(self.sprite_bottom(), self.work_bottom() - a.spr)
        self.assertIsNotNone(a.cfg["free_x"])
        y_free = a.win_y
        self.drag(0, 10)                                        # dropped in mid-air: stays put
        self.assertEqual(a.cfg["dock_mode"], "free")
        self.assertAlmostEqual(a.win_y, y_free + 10, delta=2)
        gap = self.work_bottom() - self.sprite_bottom()
        self.drag(0, int(gap) - 4)                              # ...and dropped on the taskbar: docks
        self.assertEqual(a.cfg["dock_mode"], "taskbar")
        self.assertEqual(self.sprite_bottom(), self.work_bottom())

    def test_a_drag_is_not_a_click(self):
        self.drag(-80, 0)
        self.wait_for(lambda: False, 0.5)
        self.assertNotIn("heart", self.shapes())

    def test_free_mode_drag_moves_anywhere_and_is_remembered(self):
        a = self.app
        a.set_dock_mode("free")
        a.cfg["free_x"], a.cfg["free_y"] = 300, 100
        a._update_position(self.clock(), 0, force=True)
        self.drag(40, 30)
        self.assertEqual((a.cfg["free_x"], a.cfg["free_y"]), (340, 130))
        self.assertEqual(a.cfg["dock_mode"], "free")

    def test_free_position_is_kept_on_screen(self):
        a = self.app
        a.set_dock_mode("free")
        a.cfg["free_x"], a.cfg["free_y"] = -5000, 99999
        a._update_position(self.clock(), 0, force=True)
        sw, sh = a.root.winfo_screenwidth(), a.root.winfo_screenheight()
        self.assertGreaterEqual(a.win_x + a.pad_x, 0)
        self.assertLessEqual(a.win_y + a.head + a.spr, sh)
        self.assertLessEqual(a.win_x + a.pad_x + a.spr, sw)


class PerchTests(AppTestCase):
    def perch_on(self, rect):
        self.app.set_dock_mode("active_window")
        with mock.patch.object(winutil, "perch_rect", lambda: rect):
            self.settle(1.0, dt=0.05)

    def test_perches_with_feet_on_the_title_bar_near_the_caption_buttons(self):
        a = self.app
        self.perch_on((200, 300, 900, 700))
        self.assertAlmostEqual(self.sprite_bottom(), 300 + round(companion.PERCH_SINK * a.ui), delta=1)
        window_right = a.win_x + a.win_w                         # garden and effects included
        self.assertLessEqual(window_right, 900 - companion.CAPTION_BUTTONS * a.ui + 1)
        self.assertGreater(window_right, 900 - companion.CAPTION_BUTTONS * a.ui - 60)

    def test_glides_rather_than_teleporting(self):
        a = self.app
        a.set_dock_mode("active_window")
        with mock.patch.object(winutil, "perch_rect", lambda: (200, 300, 900, 700)):
            self.settle(1.0)
        x_before = a.win_x
        with mock.patch.object(winutil, "perch_rect", lambda: (600, 300, 1400, 700)):
            self.settle(0.12, dt=0.04)
            mid = a.win_x
            self.settle(1.5)
        self.assertGreater(mid, x_before)
        self.assertLess(mid, a.win_x - 5)

    def test_stays_put_when_nothing_is_worth_perching_on(self):
        a = self.app
        self.perch_on((200, 300, 900, 700))
        pos = (a.win_x, a.win_y)
        with mock.patch.object(winutil, "perch_rect", lambda: None):    # e.g. taskbar focused
            self.settle(1.0)
        self.assertEqual((a.win_x, a.win_y), pos)

    def test_maximised_window_keeps_the_sprite_on_screen(self):
        a = self.app
        sw = a.root.winfo_screenwidth()
        self.perch_on((0, 0, sw, 260))
        self.assertGreaterEqual(a.win_y + a.head, 0)
        self.assertLessEqual(a.win_x + a.pad_x + a.spr, sw)

    def test_starting_in_perch_mode_with_no_window_still_shows_up(self):
        a = self.app
        a.cfg["dock_mode"] = "active_window"
        a._placed_once = False
        a._target = None
        with mock.patch.object(winutil, "perch_rect", lambda: None):
            a._update_position(self.clock(), 0, force=True)
        self.assertTrue(a._placed_once)

    def test_picking_it_up_cancels_the_perch(self):
        a = self.app
        self.perch_on((200, 300, 900, 700))
        with mock.patch.object(winutil, "perch_rect", lambda: (200, 300, 900, 700)):
            self.drag(-50, -50)
            self.assertEqual(a.cfg["dock_mode"], "free")
            self.settle(0.5)
            self.assertEqual(a.cfg["dock_mode"], "free")


class SettingsAndMenuTests(AppTestCase):
    def test_settings_survive_a_restart(self):
        a = self.app
        a.set_character("wizard")
        a.set_scale(6)
        a.var_fullscreen.set(False)
        a._on_fullscreen_toggle()
        self.drag(-200, 0)
        dock_x = a.cfg["dock_x"]
        a.quit()
        self.app = self.make_app()
        self.assertEqual(self.app.cfg["character"], "wizard")
        self.assertEqual(self.app.cfg["scale"], 6)
        self.assertFalse(self.app.cfg["hide_fullscreen"])
        self.assertEqual(self.app.cfg["dock_x"], dock_x)
        self.assertEqual(self.app.var_char.get(), "wizard")           # menu reflects it too
        self.assertEqual(self.app.sprite_bottom if False else self.app.win_y + self.app.win_h,
                         self.work_bottom())

    def test_stats_are_saved_on_quit_and_reloaded(self):
        self.type_for(5, 4)
        total = self.app.stats.keys_today
        self.assertGreater(total, 0)
        self.app.quit()
        self.app = self.make_app()
        self.assertEqual(self.app.stats.keys_today, total)
        self.assertIn(f"{total:,} keys", self.app.stats.summary())

    def test_settings_file_is_written_soon_after_a_change(self):
        self.app.set_character("robot")
        self.clock.advance(2)
        self.app.step()
        self.assertEqual(core.load_settings(self.app.settings_path)["character"], "robot")

    def test_corrupt_settings_do_not_stop_startup(self):
        self.app.quit()
        with open(os.path.join(self.home, "settings.json"), "w") as fh:
            fh.write("\x00\x01 not json")
        self.app = self.make_app()
        self.assertEqual(self.app.cfg, core.DEFAULT_SETTINGS)

    def test_menu_controls_are_wired_to_actions(self):
        a = self.app
        a._refresh_menu()
        self.assertIn("keys", a.menu.entrycget(0, "label"))
        a.set_character("robot")
        self.assertEqual(a.var_char.get(), "robot")
        a.set_dock_mode("free")
        self.assertEqual(a.var_mode.get(), "free")
        a.set_scale(5)
        self.assertEqual(a.var_scale.get(), 5)
        a.snap_to_taskbar()
        self.assertEqual((a.cfg["dock_mode"], a.cfg["dock_x"]), ("taskbar", None))
        self.assertEqual(self.sprite_bottom(), self.work_bottom())
        for bad in ("dragon",):
            a.set_character(bad)
        a.set_scale(99)
        a.set_dock_mode("nowhere")
        self.assertEqual((a.cfg["character"], a.cfg["scale"], a.cfg["dock_mode"]), ("robot", 5, "taskbar"))

    def test_nap_and_wake_up(self):
        a = self.app
        a.nap()
        self.assertEqual(a.step().mood, "sleeping")
        a.wake_up()
        snap = a.step()
        self.assertEqual((snap.mood, snap.total), ("idle", 0))

    def test_right_click_opens_the_menu_without_error(self):
        with mock.patch.object(self.app.menu, "tk_popup") as popup:
            self.mouse("<ButtonPress-3>")
            popup.assert_called_once()
        self.assertEqual(self.app.root.winfo_exists(), 1)


class RobustnessTests(AppTestCase):
    def test_a_failing_frame_does_not_stop_the_animation_loop(self):
        a = self.app
        scheduled = []
        real_after = a.root.after
        a.root.after = lambda ms, fn=None, *args: scheduled.append(ms) or real_after(ms, fn, *args)
        with mock.patch.object(a, "_render", side_effect=RuntimeError("bad frame")):
            a._tick()                                           # must not raise
        self.assertEqual(len(scheduled), 1)                     # ...and must reschedule itself
        a.root.after = real_after

    def test_loop_is_fast_when_busy_and_relaxed_when_resting(self):
        a = self.app
        delays = []
        real_after = a.root.after
        a.root.after = lambda ms, fn=None, *args: delays.append(ms) or real_after(ms, fn, *args)
        a.meter.wake(self.clock())
        a._tick()
        self.key()
        a._tick()
        a.root.after = real_after
        self.assertEqual(delays, [companion.TICK_CALM_MS, companion.TICK_BUSY_MS])

    def test_hides_for_fullscreen_apps_and_returns(self):
        a = self.app
        self.assertEqual(a.root.state(), "normal")
        with mock.patch.object(winutil, "fullscreen_app_running", lambda: True):
            self.settle(1.2)
            self.assertEqual(a.root.state(), "withdrawn")
        self.settle(1.2)
        self.assertEqual(a.root.state(), "normal")

    def test_fullscreen_hiding_can_be_switched_off(self):
        a = self.app
        a.var_fullscreen.set(False)
        a._on_fullscreen_toggle()
        with mock.patch.object(winutil, "fullscreen_app_running", lambda: True):
            self.settle(1.2)
        self.assertEqual(a.root.state(), "normal")

    def test_dead_keyboard_backend_is_restarted_but_not_hammered(self):
        a = self.app

        class Backend:
            def __init__(self, alive):
                self._alive, self.stopped = alive, False

            def alive(self):
                return self._alive

            def stop(self):
                self.stopped = True

        dead = Backend(False)
        a.backend = dead
        starts = []

        def fake_start(meter, prefer_pynput=False):
            starts.append(1)
            return Backend(False)                               # the replacement dies as well

        with mock.patch("keyboard_input.start_backend", fake_start):
            self.settle(3.0)
            self.assertEqual(len(starts), 1)                    # throttled to one try per 10 s
            self.assertTrue(dead.stopped)
            self.settle(10.0)
            self.assertEqual(len(starts), 2)

    def test_shutdown_stops_the_backend_and_is_safe_to_repeat(self):
        a = self.app

        class Backend:
            stopped = 0

            def alive(self):
                return True

            def stop(self):
                Backend.stopped += 1

        a.backend = Backend()
        a.quit()
        a.quit()
        a._shutdown()
        self.assertEqual(Backend.stopped, 1)

    def test_demo_mode_cycles_through_every_mood(self):
        a = self.app
        a.demo = True
        a._demo_t0 = self.clock()
        moods = set()
        for _ in range(1400):                                   # 70 s of demo time
            self.clock.advance(0.05)
            moods.add(a.step().mood)
        self.assertEqual(moods, {"idle", "typing", "sleeping"})

    def test_images_are_cached_per_pose_not_rebuilt_every_frame(self):
        self.type_for(8, 2)
        cached = len(self.app._images)
        self.type_for(8, 2)
        self.assertEqual(len(self.app._images), cached)
        self.assertLessEqual(cached, 8)


class SpringTests(AppTestCase):
    def garden_boxes(self):
        c = self.app.canvas
        return [c.coords(i) for i in c.find_withtag("garden")]

    def grow_to(self, keys):
        self.app.stats.keys_today = keys
        self.settle(0.2)

    def test_greets_once_shortly_after_starting(self):
        a = self.app
        self.settle(companion.GREET_DELAY + 0.3)
        self.assertTrue(a.bubble.visible)
        self.assertIn(a.bubble.icon, ("sun", "flower", "leaf", "moon"))
        self.settle(6)
        self.assertFalse(a.bubble.visible)
        self.settle(30)
        self.assertFalse(a.bubble.visible)

    def test_garden_grows_beside_the_companion_never_over_it(self):
        a = self.app
        self.assertEqual(self.garden_boxes(), [])
        self.grow_to(4000)
        boxes = self.garden_boxes()
        self.assertGreater(len(boxes), 30)
        for x0, y0, x1, y1 in boxes:
            self.assertTrue(x1 <= a.pad_x or x0 >= a.pad_x + a.spr, (x0, x1))
            self.assertLessEqual(y1, a.win_h)
            self.assertGreaterEqual(x0, 0)
            self.assertLessEqual(x1, a.win_w)
        self.assertEqual(max(b[3] for b in boxes), a.win_h)        # stems stand on the ground line
        self.assertTrue(a.garden.full)

    def test_first_bloom_and_full_garden_say_something_kind(self):
        a = self.app
        self.settle(8)                                          # let the greeting pass
        self.grow_to(999)
        self.assertFalse(a.bubble.visible)
        self.grow_to(1001)
        self.assertIn("first flower", a.bubble.text)
        self.assertIn("spark", self.shapes())                   # a little puff at the flower
        self.settle(6)
        self.grow_to(2100)                                      # the 2nd bloom is quiet
        self.assertFalse(a.bubble.visible)
        self.grow_to(4000)
        self.assertIn("full bloom", a.bubble.text)

    def test_garden_switch_hides_flowers_and_visitors(self):
        a = self.app
        self.grow_to(4000)
        a.next_butterfly = self.clock()
        self.settle(0.5)
        self.assertTrue(a.butterflies)
        a.var_garden.set(False)
        a._on_garden_toggle()
        self.settle(0.2)
        self.assertEqual(self.garden_boxes(), [])
        self.assertFalse(a.butterflies)
        a.next_butterfly = self.clock()
        self.settle(5)
        self.assertFalse(a.butterflies)
        a.var_garden.set(True)
        a._on_garden_toggle()
        self.settle(0.2)
        self.assertTrue(self.garden_boxes())

    def test_butterflies_visit_while_you_rest_and_then_leave(self):
        a = self.app
        a.rng.seed(4)
        self.grow_to(4000)
        a.meter.wake(self.clock())
        a.next_butterfly = self.clock()
        self.settle(0.2)
        self.assertEqual(len(a.butterflies), 1)
        states = set()
        for _ in range(600):
            self.clock.advance(0.05)
            a.step()
            states.update(b.state for b in a.butterflies)
            if not a.butterflies:
                break
        self.assertEqual(a.butterflies, [])
        self.assertTrue({"arrive", "rest", "leave"} <= states)
        self.assertGreaterEqual(a.next_butterfly - self.clock(), 0)   # next visit is a while off

    def test_no_new_butterflies_while_typing(self):
        a = self.app
        a.next_butterfly = self.clock()
        self.type_for(4, 3)
        self.assertEqual(a.butterflies, [])

    def test_fireflies_glow_only_while_sleeping(self):
        a = self.app
        a.rng.seed(5)
        a.meter.wake(self.clock())
        self.settle(10)
        self.assertNotIn("firefly", self.shapes())
        a.nap()
        most = 0
        for _ in range(200):                                    # watch the whole 10 s nap
            self.clock.advance(0.05)
            a.step()
            most = max(most, self.shapes().count("firefly"))
        self.assertGreater(most, 0)
        self.assertLessEqual(most, 3)
        self.key()                                              # waking up: no new fireflies
        self.settle(6)
        self.assertNotIn("firefly", self.shapes())

    def test_friendly_messages_switch(self):
        a = self.app
        a.var_messages.set(False)
        a._on_messages_toggle()
        self.settle(3)
        self.assertFalse(a.bubble.visible)                      # no greeting
        self.grow_to(1500)
        self.assertFalse(a.bubble.visible)                      # no bloom chatter
        a.show_journal()                                        # ...but things you ask for still show
        self.settle(0.1)
        self.assertTrue(a.bubble.visible)

    def test_stretch_reminder_after_a_long_stretch_of_typing(self):
        a = self.app
        a.set_break_minutes(30)
        self.settle(8)
        shown_at = None
        start = self.clock()
        for i in range(31 * 30):                                # a key every 2 s for 31 minutes
            self.clock.advance(2.0)
            self.key(65 + i % 20)
            a.step()
            if a.bubble.visible and a.bubble.icon == "cup":
                shown_at = self.clock() - start
                break
        self.assertIsNotNone(shown_at)
        self.assertAlmostEqual(shown_at, 30 * 60, delta=10)

    def test_stretch_reminders_can_be_switched_off(self):
        a = self.app
        a.set_break_minutes(0)
        for i in range(50 * 30):
            self.clock.advance(2.0)
            self.key(65 + i % 20)
            a.step()
            self.assertNotEqual(a.bubble.icon if a.bubble.visible else None, "cup")

    def test_welcome_back_after_a_long_nap_but_not_a_short_one(self):
        a = self.app
        self.settle(8)
        a.nap()
        self.settle(60)
        self.key()
        self.settle(0.2)
        self.assertNotIn("Welcome back", a.bubble.text)
        a.nap()
        self.settle(11 * 60, dt=1.0)
        self.key()
        self.settle(0.2)
        self.assertIn("Welcome back", a.bubble.text)

    def test_petting_sometimes_gets_a_reply(self):
        a = self.app
        a.rng.seed(2)
        self.settle(8)
        replies = 0
        for _ in range(12):
            a._pet()
            if a.bubble.visible or a.bubble.text:
                replies += 1
                a.bubble.hide()
        self.assertGreater(replies, 0)
        self.assertLess(replies, 12)

    def test_bunny_is_selectable(self):
        a = self.app
        a.set_character("bunny")
        self.type_for(5, 1)
        self.assertIn(("bunny", a._frame_name, a.px), a._images)


class BubbleTests(AppTestCase):
    def test_floats_above_the_companion_and_stays_on_screen(self):
        a = self.app
        self.settle(companion.GREET_DELAY + 0.3)
        w, h, x, y = a.bubble._geo
        self.assertLessEqual(y + h, a.win_y + a._content_top)   # above the head (and badge)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + w, a.root.winfo_screenwidth())
        tail_x = x + a.bubble._drawn[2]
        self.assertAlmostEqual(tail_x, a.win_x + a.pad_x + a.spr / 2, delta=a.bubble.step * 6)

    def test_hangs_below_when_there_is_no_room_above(self):
        a = self.app
        a.set_dock_mode("active_window")
        with mock.patch.object(winutil, "perch_rect", lambda: (100, 0, 900, 400)):
            self.settle(1.0)
            a.show_journal()
            self.settle(0.2)
        w, h, x, y = a.bubble._geo
        self.assertGreaterEqual(y, a.win_y + a.win_h - 1)
        self.assertTrue(a.bubble._drawn[3])                     # tail points up

    def test_follows_the_companion_when_it_moves(self):
        a = self.app
        a.show_journal()
        self.settle(0.2)
        x_before = a.bubble._geo[2]
        self.drag(-200, 0)
        self.settle(0.1)
        self.assertAlmostEqual(a.bubble._geo[2], x_before - 200, delta=3)

    def test_click_dismisses_it(self):
        a = self.app
        a.show_journal()
        self.settle(0.2)
        self.assertTrue(a.bubble.visible)
        a.bubble.canvas.event_generate("<ButtonPress-1>", x=5, y=5)
        a.root.update()
        self.assertFalse(a.bubble.visible)
        self.settle(1)
        self.assertFalse(a.bubble.visible)                      # and it doesn't come back

    def test_low_priority_chatter_never_interrupts_something_important(self):
        a = self.app
        a.say("important", priority=3)
        self.assertFalse(a.say("chatter", priority=0))
        self.assertEqual(a.bubble.text, "important")
        self.assertTrue(a.say("more important", priority=3))

    def test_hidden_with_the_companion_during_fullscreen(self):
        a = self.app
        a.show_journal()
        self.settle(0.2)
        with mock.patch.object(winutil, "fullscreen_app_running", lambda: True):
            self.settle(1.2)
            self.assertFalse(a.bubble.visible)
            self.assertFalse(a.say("hello?"))

    def test_always_stacked_above_the_companion(self):
        a = self.app
        a.show_journal()
        self.settle(1.5)                                        # housekeeping re-raises windows
        order = a.root.tk.call("wm", "stackorder", ".")
        names = [str(w) for w in a.root.tk.splitlist(order)]
        self.assertIn(str(a.bubble.win), names)
        self.assertGreater(names.index(str(a.bubble.win)), names.index("."))

    def test_a_new_bubble_appears_above_the_companion_straight_away(self):
        a = self.app
        self.settle(1.2)                                        # just after a stay-on-top pass
        a.root.lift()
        a.show_journal()
        a.step()                                                # no housekeeping in between
        a.root.update()
        names = [str(w) for w in a.root.tk.splitlist(a.root.tk.call("wm", "stackorder", "."))]
        self.assertGreater(names.index(str(a.bubble.win)), names.index("."))

    def test_long_text_wraps_instead_of_running_off_screen(self):
        a = self.app
        a.say("word " * 60, priority=3, friendly=False)
        self.settle(0.2)
        w, h, _x, _y = a.bubble._geo
        self.assertLess(w, (a.bubble.MAX_TEXT_W + 80) * a.ui)
        self.assertGreater(h, 3 * a.bubble.font.metrics("linespace"))

    def test_menu_is_dressed_for_spring(self):
        a = self.app
        self.assertEqual(str(a.menu.cget("bg")), theme.CREAM)
        self.assertEqual(str(a.menu.cget("activebackground")), theme.BLOSSOM_HOVER)
        labels = [a.menu.entrycget(i, "label") for i in range(a.menu.index("end") + 1)
                  if a.menu.type(i) not in ("separator",)]
        for wanted in ("Spring Garden & Visitors", "Friendly Messages", "Stretch Reminders"):
            self.assertIn(wanted, labels)
        self.assertTrue(any("Journal" in label for label in labels))
        self.assertTrue(labels[0].startswith("✿"))

    def test_effects_are_moved_not_redrawn_every_frame(self):
        a = self.app
        a._spawn_hearts()
        self.settle(0.1)
        ids_before = set(a.canvas.find_withtag("fx"))
        coords_before = {i: a.canvas.coords(i) for i in ids_before}
        self.settle(0.3)
        ids_after = set(a.canvas.find_withtag("fx"))
        self.assertEqual(ids_after, ids_before)                 # same items...
        moved = sum(1 for i in ids_after if a.canvas.coords(i) != coords_before[i])
        self.assertGreater(moved, len(ids_after) // 2)          # ...just moved along
        self.settle(2.0)
        self.assertEqual(a.canvas.find_withtag("fx"), ())       # and cleaned up when they fade

    def test_sleeping_with_only_fireflies_keeps_the_loop_relaxed(self):
        a = self.app
        a.cfg["messages"] = False
        a.nap()
        a.rng.seed(5)
        self.settle(8)
        self.assertIn("firefly", self.shapes())
        delays = []
        real_after = a.root.after
        a.root.after = lambda ms, fn=None, *args: delays.append(ms) or real_after(ms, fn, *args)
        a._tick()
        a.root.after = real_after
        self.assertEqual(delays, [companion.TICK_CALM_MS])


class StabilityTests(AppTestCase):
    def test_demo_mode_never_touches_your_real_stats(self):
        self.app.quit()
        stats_file = os.path.join(self.home, "stats.json")
        os.remove(stats_file)                                   # written by the normal app we just closed
        self.app = companion.TypingCompanionApp(start_input=False, clock=self.clock, demo=True)
        for _ in range(1200):                                   # a minute of demo typing
            self.clock.advance(0.05)
            self.app.step()
        self.assertGreater(self.app.stats.keys_today, 50)
        self.app.quit()
        self.assertFalse(os.path.exists(stats_file))

    def test_failed_settings_save_backs_off_instead_of_hammering_the_disk(self):
        a = self.app
        calls = []
        with mock.patch.object(core, "save_settings", lambda path, cfg: calls.append(1) or False):
            a.set_character("robot")
            self.settle(65, dt=0.5)
        self.assertLessEqual(len(calls), 4)                     # ~every 30 s, not every second
        self.assertTrue(a._settings_dirty)
        self.settle(31, dt=0.5)                                 # disk is fine again: it catches up
        self.assertFalse(a._settings_dirty)
        self.assertEqual(core.load_settings(a.settings_path)["character"], "robot")

    def test_a_hook_that_keeps_dying_is_replaced_by_polling(self):
        a = self.app
        a.prefer_hook = True

        class DeadHook:
            name = "pynput"

            def alive(self):
                return False

            def stop(self):
                pass

        asked = []

        def fake_start(meter, prefer_pynput=False):
            asked.append(prefer_pynput)
            return DeadHook()

        a.backend = DeadHook()
        with mock.patch("keyboard_input.start_backend", fake_start):
            self.settle(35, dt=0.5)
        self.assertEqual(asked[:2], [True, False])              # 2nd death: give up on the hook
        self.assertTrue(all(flag is False for flag in asked[1:]))

    def test_no_flash_when_starting_under_a_fullscreen_app(self):
        self.app.quit()
        with mock.patch.object(winutil, "fullscreen_app_running", lambda: True):
            self.app = self.make_app()
            self.assertEqual(self.app.root.state(), "withdrawn")
            self.assertTrue(self.app._hidden)
        self.settle(1.2)
        self.assertEqual(self.app.root.state(), "normal")

    def test_stay_on_top_pauses_while_the_menu_is_open(self):
        a = self.app
        raised = []
        with mock.patch.object(winutil, "keep_on_top", lambda hwnd: raised.append(hwnd) or True):
            a._menu_open = True
            self.settle(3)
            self.assertEqual(raised, [])
            a._menu_open = False
            self.settle(1.2)
            self.assertTrue(raised)

    def test_missing_tkinter_explains_itself_instead_of_vanishing(self):
        shown = []
        with mock.patch.object(companion, "tk", None), \
                mock.patch.object(winutil, "show_message", lambda title, text: shown.append(text)), \
                mock.patch.object(companion, "setup_logging", lambda: None):
            self.assertEqual(companion.main([]), 1)
        self.assertIn("tkinter", shown[0])

    def test_startup_crash_explains_itself_instead_of_vanishing(self):
        shown = []

        def boom(**kwargs):
            raise RuntimeError("display exploded")

        with mock.patch.object(companion, "TypingCompanionApp", boom), \
                mock.patch.object(winutil, "show_message", lambda title, text: shown.append(text)), \
                mock.patch.object(companion, "setup_logging", lambda: None), \
                self.assertLogs("companion", "ERROR"):
            self.assertEqual(companion.main([]), 1)
        self.assertIn("display exploded", shown[0])


    def test_two_companions_at_once_keep_their_own_fonts_and_settings(self):
        # Regression: fonts/variables created without an explicit root land in tkinter's *first*
        # interpreter, so a second window silently fell back to some default font.
        other = companion.TypingCompanionApp(settings_path=os.path.join(self.home, "other.json"),
                                             stats_path=os.path.join(self.home, "other-stats.json"),
                                             start_input=False, clock=self.clock)
        try:
            for app in (self.app, other):
                for thing in (app.font, app.bubble.font, app.var_char, app.var_break, app.var_garden):
                    self.assertIs(thing._tk, app.root.tk)
            other.set_character("wizard")
            self.assertEqual(self.app.var_char.get(), "cat")
        finally:
            other.quit()

if __name__ == "__main__":
    unittest.main()
