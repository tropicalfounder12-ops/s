import unittest

from tests.helpers import FakeClock  # noqa: F401  (sets up sys.path)

import sprites

REQUIRED = {"sit_a", "sit_b", "blink_a", "blink_b", "type_l", "type_r", "sleep_a", "sleep_b"}


class SpriteDataTests(unittest.TestCase):
    def test_every_character_has_every_pose(self):
        self.assertEqual(set(sprites.CHARACTERS), {"cat", "robot", "wizard", "bunny"})
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

    def test_effect_shapes_are_rectangular_and_have_their_colours(self):
        for name, (rows, colors) in sprites.SHAPES.items():
            self.assertEqual(len({len(r) for r in rows}), 1, name)
            self.assertTrue(set("".join(rows)) <= set("0123456789"), name)
            self.assertLessEqual(max(int(c) for c in "".join(rows)), len(colors), name)
            for colour in colors:
                self.assertRegex(colour, r"^#[0-9a-f]{6}$", name)
                self.assertNotEqual(colour, sprites.TRANSP, name)

    def test_bunny_sleep_frames_have_no_stray_colours(self):
        # Regression: `[[_] * 16 for _ in range(8)]` rebinds `_` and paints rows 0-7 in colours.
        for name in ("sleep_a",):
            frame = sprites.CHARACTERS["bunny"]["frames"][name]
            self.assertFalse(any(any(row) for row in frame[:8]), name)
        zzz = sprites.CHARACTERS["bunny"]["frames"]["sleep_b"][:7]
        self.assertTrue({c for row in zzz for c in row} <= {0, 7})

    def test_flowers_grow_taller_stage_by_stage(self):
        for kind in sprites.FLOWER_KINDS:
            heights = [len(sprites.flower_rows(kind, stage)) for stage in range(sprites.FLOWER_STAGES + 1)]
            self.assertEqual(heights[0], 0, kind)
            self.assertEqual(heights, sorted(heights), kind)
            colors = sprites.flower_colors(kind)
            for stage in range(1, sprites.FLOWER_STAGES + 1):
                rows = sprites.flower_rows(kind, stage)
                self.assertEqual({len(r) for r in rows}, {3}, (kind, stage))
                self.assertTrue(set("".join(rows)) <= set(colors) | {"."}, (kind, stage))

    def test_ui_colours_never_collide_with_the_transparency_key(self):
        import theme
        values = [v for k, v in vars(theme).items() if k.isupper() and isinstance(v, str)]
        values += [c for k, v in vars(theme).items() if k.startswith("BADGE_") for c in v]
        values += [v for v in theme.MENU_STYLE.values() if isinstance(v, str) and v.startswith("#")]
        self.assertTrue(values)
        self.assertNotIn(sprites.TRANSP, values)

if __name__ == "__main__":
    unittest.main()
