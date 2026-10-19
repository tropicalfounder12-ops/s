import unittest

from tests.helpers import FakeClock  # noqa: F401  (sets up sys.path)

import garden
import sprites


class GardenTests(unittest.TestCase):
    def test_each_thousand_keys_grows_one_flower(self):
        self.assertEqual([garden.stage_for(0, i) for i in range(4)], [0, 0, 0, 0])
        self.assertEqual([garden.stage_for(100, i) for i in range(4)], [1, 0, 0, 0])
        self.assertEqual([garden.stage_for(500, i) for i in range(4)], [2, 0, 0, 0])
        self.assertEqual([garden.stage_for(900, i) for i in range(4)], [3, 0, 0, 0])
        self.assertEqual([garden.stage_for(1000, i) for i in range(4)], [4, 0, 0, 0])
        self.assertEqual([garden.stage_for(2500, i) for i in range(4)], [4, 4, 2, 0])
        self.assertEqual([garden.stage_for(99999, i) for i in range(4)], [4, 4, 4, 4])

    def test_events_fire_as_flowers_grow_and_bloom(self):
        g = garden.Garden("2026-04-01", 0)
        self.assertEqual(g.update("2026-04-01", 0), [])
        self.assertEqual(g.update("2026-04-01", 400), [("grow", 0)])
        self.assertEqual(g.update("2026-04-01", 400), [])               # nothing new
        self.assertEqual(g.update("2026-04-01", 1000), [("bloom", 0)])
        self.assertEqual(g.update("2026-04-01", 4200), [("bloom", 1), ("bloom", 2), ("bloom", 3)])
        self.assertTrue(g.full)

    def test_starting_mid_day_does_not_replay_old_blooms(self):
        g = garden.Garden("2026-04-01", 2100)
        self.assertEqual(g.bloomed, 2)
        self.assertEqual(g.update("2026-04-01", 2150), [])

    def test_a_new_day_plants_a_fresh_garden(self):
        g = garden.Garden("2026-04-01", 4000)
        self.assertEqual(g.update("2026-04-02", 0), [("new_day", -1)])
        self.assertEqual(g.stages, [0, 0, 0, 0])
        self.assertEqual(g.bloomed, 0)

    def test_flower_mix_changes_by_day_but_is_stable_within_a_day(self):
        days = ["2026-04-%02d" % d for d in range(1, 15)]
        mixes = {tuple(garden.kinds_for_day(day)) for day in days}
        self.assertGreater(len(mixes), 3)
        self.assertEqual(garden.kinds_for_day("2026-04-03"), garden.kinds_for_day("2026-04-03"))
        for day in days:
            kinds = garden.kinds_for_day(day)
            self.assertEqual(len(set(kinds)), garden.SLOTS)
            self.assertTrue(set(kinds) <= set(sprites.FLOWER_KINDS))


if __name__ == "__main__":
    unittest.main()
