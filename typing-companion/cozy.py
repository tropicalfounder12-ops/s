"""Gentle words: greetings, little reactions, the daily journal and a kind break coach.

Pure logic, no GUI. Every message is short, warm and never pushy.
"""

BREAK_RESET = 5 * 60            # a pause this long already counts as a proper break
WELCOME_BACK_AFTER = 10 * 60    # say hello again after a nap at least this long


def greeting(hour):
    """(text, icon) for the time of day."""
    if 5 <= hour < 12:
        return "Good morning! Let's grow something lovely today.", "sun"
    if 12 <= hour < 17:
        return "Good afternoon! Your garden is waiting.", "flower"
    if 17 <= hour < 22:
        return "Good evening! Take it easy.", "leaf"
    return "Up late? I'll keep you company.", "moon"


PET_LINES = {
    "cat": ("Purr...", "Mrrp! ♥", "*slow blink*"),
    "robot": ("Beep boop ♥", "Affection received!", "Happiness +1"),
    "wizard": ("A charm for your keys ✦", "Thank you, friend!", "Hmm-hm-hm ♪"),
    "bunny": ("*happy hop*", "Nose boops! ♥", "Squeak!"),
}


def pet_line(character, rng):
    return rng.choice(PET_LINES.get(character, ("♥",)))


BREAK_LINES = (
    "You've been typing for {m} minutes. Stretch and sip some water?",
    "{m} minutes of focus - lovely! Roll your shoulders and rest your eyes.",
    "Time for a tiny break? Look out of a window for a moment.",
    "Breathe in... and out. You're doing great.",
)


def break_message(minutes, rng):
    return rng.choice(BREAK_LINES).format(m=minutes)


def best_message(wpm):
    return f"New personal best: {int(round(wpm))} WPM!"


def bloom_message(bloomed, slots):
    """Message for a flower opening (None when it's better to bloom quietly)."""
    if bloomed == slots:
        return "Your garden is in full bloom. What a lovely day's work!"
    if bloomed == 1:
        return "Your first flower of the day just bloomed!"
    return None


def journal(stats, garden):
    best = f"{int(round(stats.best_wpm))} WPM" if stats.best_wpm else "not yet"
    flowers = f"{garden.bloomed} of {len(garden.stages)} flowers in bloom"
    return f"Today: {stats.keys_today:,} keys\nBest ever: {best}\n{flowers}"


class BreakCoach:
    """Notices a long stretch of typing and suggests a gentle break - once per stretch.

    A stretch starts with the first keystroke after a real pause (BREAK_RESET) and the next
    suggestion only comes after another full interval, so it never nags.
    """

    def __init__(self, minutes):
        self.minutes = minutes
        self.started = None

    def update(self, now, typing, idle_for):
        """Returns True when it is time to suggest a break."""
        if idle_for >= BREAK_RESET:
            self.started = None
            return False
        if self.started is None:
            if typing:
                self.started = now
            return False
        if self.minutes and now - self.started >= self.minutes * 60:
            self.started = now
            return True
        return False
