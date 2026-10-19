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
        a, c = self.app, self.app.canvas
        self.assertEqual(c.itemcget(a.badge, "state"), "hidden")
        self.type_for(5, 4)
        self.assertEqual(c.itemcget(a.badge, "state"), "normal")
        text = c.itemcget(a.badge, "text")
        self.assertRegex(text, r"^\d+ WPM$")
        self.assertAlmostEqual(int(text.split()[0]), 60, delta=12)
        a.var_wpm.set(False)
        a._on_wpm_toggle()
        self.type_for(5, 0.4)
        self.assertEqual(c.itemcget(a.badge, "state"), "hidden")
        a.var_wpm.set(True)
        a._on_wpm_toggle()
        self.type_for(5, 0.4)
        self.assertEqual(c.itemcget(a.badge, "state"), "normal")
        self.settle(core.IDLE_AFTER + 1)
        self.assertEqual(c.itemcget(a.badge, "state"), "hidden")

    def test_sparkles_only_in_turbo_and_never_over_the_badge(self):
        import random
        random.seed(1)
        self.type_for(2, 6)                                     # ~24 WPM
        self.assertNotIn("spark", self.shapes())
        sparks = []
        for _ in range(8):                                      # ~96 WPM
            self.type_for(8, 1.0)
            sparks += [p for p in self.app.particles if p.shape == "spark"]
        self.assertGreater(len(sparks), 3)
        a = self.app
        centre = a.pad_x + a.spr / 2
        for p in sparks:       # the badge is centred above the head; sparkles spawn beside it
            self.assertGreater(abs(p.x - centre), 4 * a.px)

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
        self.assertIsNone(a.banner)
        self.type_for(8, 1.5)
        self.assertIsNotNone(a.banner)
        self.assertIn("NEW BEST", a.banner[0])
        self.assertEqual(a.canvas.itemcget(a.badge, "text"), a.banner[0])      # banner replaces the badge
        self.assertGreater(len([p for p in a.particles if p.shape == "dot"]), 10)
        self.assertGreater(a.stats.best_wpm, 80)
        first_until = a.banner[2]
        self.type_for(10, 1.0)                                  # the run keeps climbing...
        self.assertEqual(a.banner[2], first_until)              # ...but doesn't re-trigger
        self.settle(3.0)                                        # banner times out on its own
        self.assertIsNone(a.banner)
        self.assertFalse([p for p in a.particles if p.shape == "dot"])          # confetti has landed

    def test_a_second_run_inside_the_cooldown_does_not_celebrate_again(self):
        a = self.app
        a.stats.best_wpm = 30.0
        a._run_start_best = 30.0
        self.type_for(8, 6.5)
        self.assertIsNotNone(a.banner)
        self.settle(core.IDLE_AFTER + core.WPM_WINDOW + 1)      # stop typing; banner goes away
        self.assertIsNone(a.banner)
        self.type_for(12, 7)                                    # an even faster run, 15 s later
        self.assertGreater(a.stats.best_wpm, 100)
        self.assertIsNone(a.banner)                             # cooldown (60 s) still running

    def test_no_celebration_for_a_slow_or_short_run(self):
        self.type_for(8, 3)                                     # fast but not sustained
        self.assertIsNone(self.app.banner)
        a = self.app
        self.settle(core.WPM_WINDOW + core.IDLE_AFTER)
        self.type_for(1, 8)                                     # sustained but below the minimum
        self.assertIsNone(a.banner)

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

    def test_double_click_toggles_badge_and_does_not_pet(self):
        a = self.app
        self.assertTrue(a.cfg["show_wpm"])
        for seq in ("<ButtonPress-1>", "<ButtonRelease-1>", "<ButtonPress-1>", "<ButtonRelease-1>"):
            self.mouse(seq)                                     # Tk turns the 2nd press into a Double
        self.assertFalse(a.cfg["show_wpm"])
        self.assertFalse(a.var_wpm.get())
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
        right_edge = a.win_x + a.pad_x + a.spr
        self.assertLessEqual(right_edge, 900 - companion.CAPTION_CLEARANCE * a.ui + 1)
        self.assertGreater(right_edge, 900 - companion.CAPTION_CLEARANCE * a.ui - a.spr - 80)

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

        def fake_start(meter):
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


if __name__ == "__main__":
    unittest.main()
