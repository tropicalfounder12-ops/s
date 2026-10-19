#!/usr/bin/env python3
"""Render docs/preview.png: every character in every pose, standing on a taskbar strip.

Developer tool (needs Pillow: `pip install pillow`); the companion itself doesn't use it.
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sprites  # noqa: E402

SCALE = 6
POSES = [("sit_a", "idle"), ("blink_a", "blink"), ("type_l", "typing L"), ("type_r", "typing R"),
         ("sleep_a", "sleep"), ("sleep_b", "sleep Zzz")]
CELL_W, CELL_H, TASKBAR, LABEL = 118, 126, 22, 16
BG, BAR, LINE, TEXT = (43, 43, 51), (24, 24, 30), (70, 70, 84), (170, 170, 190)


def hex_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def main(out=os.path.join(ROOT, "docs", "preview.png")):
    width = CELL_W * len(POSES)
    height = (CELL_H + TASKBAR) * len(sprites.CHARACTERS) + LABEL
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    for col, (_key, label) in enumerate(POSES):
        draw.text((col * CELL_W + CELL_W // 2, 3), label, fill=TEXT, anchor="mt")
    for row, char in enumerate(sprites.CHARACTERS.values()):
        top = LABEL + row * (CELL_H + TASKBAR)
        ground = top + CELL_H                       # the taskbar's top edge
        draw.rectangle([0, ground, width, ground + TASKBAR], fill=BAR)
        draw.line([0, ground, width, ground], fill=LINE)
        for col, (pose, _label) in enumerate(POSES):
            frame = char["frames"][pose]
            x0 = col * CELL_W + (CELL_W - sprites.SPRITE_SIZE * SCALE) // 2
            y0 = ground - sprites.SPRITE_SIZE * SCALE       # feet land exactly on the line
            for y, cells in enumerate(frame):
                for x, idx in enumerate(cells):
                    if idx:
                        px, py = x0 + x * SCALE, y0 + y * SCALE
                        draw.rectangle([px, py, px + SCALE - 1, py + SCALE - 1],
                                       fill=hex_rgb(char["palette"][idx]))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, optimize=True)
    print(f"wrote {out} ({width}x{height})")


if __name__ == "__main__":
    main()
