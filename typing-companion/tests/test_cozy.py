import random
import unittest
from types import SimpleNamespace

from tests.helpers import FakeClock  # noqa: F401  (sets up sys.path)

import cozy
import sprites


class MessageTests(unittest.TestCase):
    def test_greeting_follows_the_clock_and_uses_real_icons(self):
        seen = set()
        for hour in range(24):
            text, icon = cozy.greeting(hour)
            self.assertTrue(text)
            self.assertIn(icon, sprites.SHAPES)
            seen.add(text)
        self.assertEqual(len(seen), 4)
        self.assertIn("morning", cozy.greeting(8)[0])
        self.assertIn("late", cozy.greeting(2)[0])

    def test_every_character_has_pet_lines(self):
        rng = random.Random(1)
        for key in sprites.CHARACTERS:
            self.assertIn(key, cozy.PET_LINES)
            self.assertTrue(cozy.pet_line(key, rng))

    def test_break_message_mentions_minutes_where_it_can(self):
        rng = random.Random(0)
        texts = {cozy.break_message(45, rng) for _ in range(50)}
        self.assertEqual(len(texts), len(cozy.BREAK_LINES))
        self.assertTrue(any("45" in t for t in texts))
        self.assertFalse(any("{m}" in t for t in texts))

    def test_blooms_only_speak_for_the_first_and_the_last_flower(self):
        self.assertIn("first", cozy.bloom_message(1, 4))
        self.assertIsNone(cozy.bloom_message(2, 4))
        self.assertIsNone(cozy.bloom_message(3, 4))
        self.assertIn("full bloom", cozy.bloom_message(4, 4))

    def test_journal(self):
        stats = SimpleNamespace(keys_today=1234, best_wpm=71.6)
        g = SimpleNamespace(bloomed=1, stages=[4, 1, 0, 0])
        self.assertEqual(cozy.journal(stats, g),
                         "Today: 1,234 keys\nBest ever: 72 WPM\n1 of 4 flowers in bloom")
        stats.best_wpm = 0
        self.assertIn("not yet", cozy.journal(stats, g))


class BreakCoachTests(unittest.TestCase):
    def run_coach(self, coach, minutes, typing=True, idle_for=1.0, start=0.0, step=10.0):
        hits, t = [], start
        while t < start + minutes * 60:
            if coach.update(t, typing, idle_for):
                hits.append(t)
            t += step
        return hits, t

    def test_suggests_a_break_after_the_interval_and_not_before(self):
        coach = cozy.BreakCoach(45)
        hits, _ = self.run_coach(coach, 44)
        self.assertEqual(hits, [])
        hits, _ = self.run_coach(coach, 2, start=44 * 60)
        self.assertEqual(len(hits), 1)

    def test_never_nags_more_than_once_per_interval(self):
        hits, _ = self.run_coach(cozy.BreakCoach(30), 125)
        self.assertEqual(len(hits), 4)
        self.assertTrue(all(b - a >= 30 * 60 for a, b in zip(hits, hits[1:])))

    def test_a_real_pause_resets_the_clock(self):
        coach = cozy.BreakCoach(45)
        self.run_coach(coach, 40)
        coach.update(2400, False, cozy.BREAK_RESET + 1)        # a 5+ minute break
        hits, _ = self.run_coach(coach, 40, start=2800)
        self.assertEqual(hits, [])

    def test_short_pauses_do_not_reset_it(self):
        coach = cozy.BreakCoach(30)
        t, hits = 0.0, []
        while t < 31 * 60:
            typing = int(t / 120) % 2 == 0                      # 2 min on, 2 min off
            if coach.update(t, typing, 1.0 if typing else 60.0):
                hits.append(t)
            t += 10
        self.assertEqual(len(hits), 1)

    def test_off_means_off(self):
        hits, _ = self.run_coach(cozy.BreakCoach(0), 300)
        self.assertEqual(hits, [])

    def test_idle_time_before_typing_does_not_count(self):
        coach = cozy.BreakCoach(30)
        hits, _ = self.run_coach(coach, 60, typing=False, idle_for=60.0)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
