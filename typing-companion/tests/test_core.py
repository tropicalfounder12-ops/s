import datetime
import json
import os
import tempfile
import unittest

from tests.helpers import FakeClock

import core


def type_keys(meter, clock, keys_per_sec, secs):
    """Type distinct keys at a steady rate and return the final snapshot."""
    for i in range(int(keys_per_sec * secs)):
        clock.advance(1.0 / keys_per_sec)
        meter.key_down(65 + i % 26, now=clock())
        meter.key_up(65 + i % 26)
    return meter.snapshot(clock())


class TypingMeterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.meter = core.TypingMeter(clock=self.clock)

    def test_starts_idle_with_zero_wpm(self):
        snap = self.meter.snapshot()
        self.assertEqual(snap.mood, "idle")
        self.assertEqual(snap.wpm, 0)
        self.assertEqual(snap.total, 0)

    def test_steady_typing_reads_true_wpm(self):
        # 5 keys/s = 60 WPM, and it should read ~60 from the first few seconds on
        # (the old fixed 8 s divisor needed a full 8 s to catch up).
        snap = type_keys(self.meter, self.clock, 5, 3.0)
        self.assertAlmostEqual(snap.wpm, 60, delta=6)
        snap = type_keys(self.meter, self.clock, 5, 10.0)
        self.assertAlmostEqual(snap.wpm, 60, delta=3)
        self.assertGreaterEqual(snap.age, core.WPM_SUSTAINED)

    def test_wpm_decays_to_zero_after_typing_stops(self):
        type_keys(self.meter, self.clock, 5, 5.0)
        self.clock.advance(core.WPM_WINDOW + 0.5)
        self.assertEqual(self.meter.snapshot().wpm, 0)

    def test_auto_repeat_is_not_counted(self):
        # Holding a key: one real press, then repeated key-downs 30 ms apart, no key-up.
        self.assertTrue(self.meter.key_down(8, now=self.clock()))
        for _ in range(100):
            self.assertFalse(self.meter.key_down(8, now=self.clock.advance(0.03)))
        self.assertEqual(self.meter.snapshot().total, 1)
        # ...but holding the key still counts as activity, so the sprite stays awake.
        self.assertEqual(self.meter.snapshot().mood, "typing")

    def test_same_key_pressed_again_after_release_counts(self):
        for _ in range(5):
            self.assertTrue(self.meter.key_down(32, now=self.clock.advance(0.1)))
            self.meter.key_up(32)
        self.assertEqual(self.meter.snapshot().total, 5)

    def test_stale_key_down_from_missed_release_counts_again(self):
        self.assertTrue(self.meter.key_down(70, now=self.clock()))
        # key-up was lost; much later the same key is pressed again
        self.assertTrue(self.meter.key_down(70, now=self.clock.advance(core.REPEAT_WINDOW + 1)))

    def test_modifiers_wake_but_do_not_count(self):
        self.assertFalse(self.meter.key_down(16, is_modifier=True, now=self.clock()))
        snap = self.meter.snapshot()
        self.assertEqual((snap.total, snap.mood), (0, "typing"))

    def test_mood_transitions(self):
        self.meter.key_down(65, now=self.clock())
        self.assertEqual(self.meter.snapshot().mood, "typing")
        self.clock.advance(core.IDLE_AFTER + 0.1)
        self.assertEqual(self.meter.snapshot().mood, "idle")
        self.clock.advance(core.SLEEP_AFTER)
        self.assertEqual(self.meter.snapshot().mood, "sleeping")
        self.meter.key_down(66, now=self.clock())
        self.assertEqual(self.meter.snapshot().mood, "typing")

    def test_wake_does_not_fake_a_keystroke(self):
        self.meter.nap(self.clock())
        self.assertEqual(self.meter.snapshot().mood, "sleeping")
        self.meter.wake(self.clock())
        snap = self.meter.snapshot()
        self.assertEqual((snap.mood, snap.total, snap.wpm), ("idle", 0, 0))

    def test_nap_sleeps_until_next_key(self):
        self.meter.nap(self.clock())
        self.assertEqual(self.meter.snapshot().mood, "sleeping")
        self.meter.key_down(65, now=self.clock.advance(1))
        self.assertEqual(self.meter.snapshot().mood, "typing")

    def test_press_seq_only_counts_real_keystrokes(self):
        self.meter.key_down(65, now=self.clock())
        self.meter.key_down(65, now=self.clock.advance(0.03))        # repeat
        self.meter.key_down(16, True, now=self.clock.advance(0.03))  # modifier
        self.assertEqual(self.meter.snapshot().press_seq, 1)

    def test_down_table_does_not_grow_without_bound(self):
        for vk in range(500):
            self.meter.key_down(vk, now=self.clock.advance(0.01))
        self.assertLess(len(self.meter._down), 200)


class SettingsTests(unittest.TestCase):
    def test_defaults_when_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            self.assertEqual(core.load_settings(path), core.DEFAULT_SETTINGS)
            with open(path, "w") as fh:
                fh.write("{not json")
            self.assertEqual(core.load_settings(path), core.DEFAULT_SETTINGS)
            with open(path, "w") as fh:
                fh.write("[1, 2, 3]")
            self.assertEqual(core.load_settings(path), core.DEFAULT_SETTINGS)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "settings.json")      # directory is created on demand
            cfg = dict(core.DEFAULT_SETTINGS, character="wizard", scale=6, dock_mode="free",
                       free_x=-1900, free_y=40, show_wpm=False)
            self.assertTrue(core.save_settings(path, cfg))
            self.assertEqual(core.load_settings(path), cfg)

    def test_bad_values_fall_back_individually(self):
        raw = {"character": "dragon", "dock_mode": "free", "scale": 99, "show_wpm": "yes",
               "free_x": 12.5, "free_y": True, "dock_x": 300, "unknown": 1}
        cfg = core.sanitize_settings(raw)
        self.assertEqual(cfg["character"], "cat")
        self.assertEqual(cfg["dock_mode"], "free")          # the valid ones survive
        self.assertEqual(cfg["scale"], 4)
        self.assertIs(cfg["show_wpm"], True)
        self.assertIsNone(cfg["free_x"])
        self.assertIsNone(cfg["free_y"])                    # bool is not an int here
        self.assertEqual(cfg["dock_x"], 300)
        self.assertNotIn("unknown", cfg)

    def test_save_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            core.save_settings(path, core.DEFAULT_SETTINGS)
            self.assertEqual(os.listdir(d), ["settings.json"])

    def test_data_dir_override(self):
        old = os.environ.get("TYPING_COMPANION_HOME")
        os.environ["TYPING_COMPANION_HOME"] = "/somewhere/else"
        try:
            self.assertEqual(core.data_dir(), "/somewhere/else")
        finally:
            if old is None:
                del os.environ["TYPING_COMPANION_HOME"]
            else:
                os.environ["TYPING_COMPANION_HOME"] = old


class StatsTests(unittest.TestCase):
    def test_counts_persist_and_roll_over_at_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stats.json")
            stats = core.Stats(path, today="2026-01-01")
            stats.add_keys(120, today="2026-01-01")
            self.assertTrue(stats.record_wpm(55.4))
            self.assertFalse(stats.record_wpm(40))
            stats.save()
            self.assertFalse(stats.dirty)

            same_day = core.Stats(path, today="2026-01-01")
            self.assertEqual((same_day.keys_today, same_day.total_keys), (120, 120))
            self.assertAlmostEqual(same_day.best_wpm, 55.4, places=1)

            next_day = core.Stats(path, today="2026-01-02")
            self.assertEqual(next_day.keys_today, 0)                # today resets...
            self.assertEqual(next_day.total_keys, 120)              # ...lifetime doesn't
            self.assertAlmostEqual(next_day.best_wpm, 55.4, places=1)

    def test_rolls_over_while_running(self):
        with tempfile.TemporaryDirectory() as d:
            stats = core.Stats(os.path.join(d, "s.json"), today="2026-01-01")
            stats.add_keys(10, today="2026-01-01")
            stats.add_keys(5, today="2026-01-02")
            self.assertEqual((stats.keys_today, stats.total_keys), (5, 15))

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stats.json")
            with open(path, "w") as fh:
                json.dump({"keys_today": "lots", "best_wpm": -3, "total_keys": None}, fh)
            stats = core.Stats(path)
            self.assertEqual((stats.keys_today, stats.total_keys, stats.best_wpm), (0, 0, 0.0))

    def test_summary_text(self):
        with tempfile.TemporaryDirectory() as d:
            stats = core.Stats(os.path.join(d, "s.json"))
            self.assertIn("Best: -", stats.summary())
            stats.add_keys(1234)
            stats.record_wpm(71.6)
            self.assertEqual(stats.summary(), "Today: 1,234 keys  ·  Best: 72 WPM")

    def test_stats_file_holds_only_counts(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            stats = core.Stats(path)
            stats.add_keys(3)
            stats.save()
            with open(path) as fh:
                self.assertEqual(set(json.load(fh)), {"day", "keys_today", "total_keys", "best_wpm"})


if __name__ == "__main__":
    unittest.main()
