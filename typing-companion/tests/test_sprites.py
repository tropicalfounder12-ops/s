import unittest

from tests.helpers import FakeClock  # noqa: F401  (sets up sys.path)

import sprites

REQUIRED = {"sit_a", "sit_b", "blink_a", "blink_b", "type_l", "type_r", "sleep_a", "sleep_b"}


class SpriteDataTests(unittest.TestCase):
    def test_every_character_has_every_pose(self):
        self.assertEqual(set(sprites.CHARACTERS), {"cat", "robot", "wizard"})
        for key, char in sprites.CHARACTERS.items():
            self.assertEqual(set(char["frames"]), REQUIRED, key)

    def test_frames_are_square_and_use_palette_colours(self):
        n = sprites.SPRITE_SIZE
        for key, char in sprites.CHARACTERS.items():
            for name, frame in char["frames"].items():
                self.assertEqual(len(frame), n, f"{key}/{name} rows")
                for row in frame:
                    self.assertEqual(len(row), n, f"{key}/{name} row width")
                    for cell in row:
                        self.assertIn(cell, char["palette"], f"{key}/{name} palette index")

    def test_feet_always_touch_the_ground_row(self):
        # The original frames left 0-3 empty rows below the feet, so the sprite hovered
        # above the taskbar at a different height in each pose.
        for key, char in sprites.CHARACTERS.items():
            for name, frame in char["frames"].items():
                self.assertEqual(sprites.last_row(frame), sprites.SPRITE_SIZE - 1, f"{key}/{name}")

    def test_ground_align_only_moves_content_down_without_losing_pixels(self):
        n = sprites.SPRITE_SIZE
        for key, char in sprites.CHARACTERS.items():
            for name, frame in char["frames"].items():
                pixels = sum(1 for row in frame for c in row if c)
                self.assertGreater(pixels, 20, f"{key}/{name} looks empty")
        raw = [[0] * n for _ in range(n)]
        raw[3][4] = 7
        raw[5][6] = 9
        aligned = sprites.ground_align(raw)
        self.assertEqual((aligned[n - 3][4], aligned[n - 1][6]), (7, 9))
        self.assertEqual(sum(1 for row in aligned for c in row if c), 2)
        self.assertEqual(sprites.ground_align(aligned), aligned)       # idempotent

    def test_blink_poses_differ_from_open_eyes_and_keep_the_tail_pose(self):
        for key, char in sprites.CHARACTERS.items():
            f = char["frames"]
            self.assertNotEqual(f["blink_a"], f["sit_a"], key)
            self.assertNotEqual(f["blink_b"], f["sit_b"], key)
            # blink_b is sit_b with only the eye rows swapped in, so nothing else jumps
            diff_a = {i for i, (x, y) in enumerate(zip(f["sit_a"], f["blink_a"])) if x != y}
            diff_b = {i for i, (x, y) in enumerate(zip(f["sit_b"], f["blink_b"])) if x != y}
            self.assertEqual(diff_a, diff_b, key)

    def test_put_data_format(self):
        frame = [[0, 1], [1, 0]]
        data = sprites.to_put_data(frame, {0: "#010101", 1: "#ffffff"})
        self.assertEqual(data, "{#010101 #ffffff} {#ffffff #010101}")

    def test_effect_shapes_are_rectangular(self):
        for name, rows in sprites.SHAPES.items():
            self.assertEqual(len({len(r) for r in rows}), 1, name)
            self.assertTrue(set("".join(rows)) <= {"0", "1"}, name)


if __name__ == "__main__":
    unittest.main()
