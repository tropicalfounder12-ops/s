"""Your daily taskbar garden: every 1,000 keystrokes grows a flower beside the companion.

A fresh garden is planted every morning and it never wilts - nothing to lose, no streaks,
no guilt. Pure logic, no GUI.
"""

import random

import sprites

FLOWER_KEYS = 1000          # keystrokes per flower
SLOTS = 4                   # flowers per day


def stage_for(keys, index, per_flower=FLOWER_KEYS):
    """Growth stage (0 = bare soil ... 4 = in bloom) of flower number `index` after `keys` keystrokes."""
    progress = (keys - index * per_flower) / float(per_flower)
    if progress <= 0:
        return 0
    if progress < 1 / 3:
        return 1
    if progress < 2 / 3:
        return 2
    if progress < 1:
        return 3
    return sprites.FLOWER_STAGES


def kinds_for_day(day):
    """Which flowers grow today - a different mix each day, the same all day long."""
    return random.Random(day).sample(sorted(sprites.FLOWER_KINDS), SLOTS)


class Garden:
    def __init__(self, day, keys, per_flower=FLOWER_KEYS):
        self.per_flower = per_flower
        self.day = day
        self.kinds = kinds_for_day(day)
        self.stages = self._stages(keys)

    def _stages(self, keys):
        return [stage_for(keys, i, self.per_flower) for i in range(SLOTS)]

    def update(self, day, keys):
        """Move to the current day/keystroke count. Returns [(event, slot)] for anything that grew:
        "grow", "bloom", or ("new_day", -1) when a fresh garden was planted."""
        if day != self.day:
            self.day = day
            self.kinds = kinds_for_day(day)
            self.stages = self._stages(keys)
            return [("new_day", -1)]
        fresh = self._stages(keys)
        events = [("bloom" if new == sprites.FLOWER_STAGES else "grow", i)
                  for i, (old, new) in enumerate(zip(self.stages, fresh)) if new > old]
        self.stages = fresh
        return events

    @property
    def bloomed(self):
        return sum(1 for stage in self.stages if stage >= sprites.FLOWER_STAGES)

    @property
    def full(self):
        return self.bloomed == SLOTS
