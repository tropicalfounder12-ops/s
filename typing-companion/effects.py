"""Little moving things: petals, hearts, sparkles, fireflies and visiting butterflies.

Pure logic (positions in window pixels); the app draws them with sprites.SHAPES.
"""

import math

import sprites

TAU = 2 * math.pi


class Particle:
    """A pixel-art shape that drifts, sways and fades."""

    __slots__ = ("x", "y", "vx", "vy", "ay", "age", "life", "shape", "colors", "blinks",
                 "sway", "sway_hz", "phase", "pulse_hz", "tag", "drawn")

    def __init__(self, x, y, vx, vy, life, shape, colors=None, ay=0.0, blinks=False,
                 sway=0.0, sway_hz=1.0, phase=0.0, pulse_hz=0.0):
        self.x, self.y, self.vx, self.vy, self.ay = x, y, vx, vy, ay
        self.age, self.life = 0.0, life
        self.shape = shape
        self.colors = colors or sprites.SHAPES[shape][1]
        self.blinks, self.sway, self.sway_hz, self.phase, self.pulse_hz = blinks, sway, sway_hz, phase, pulse_hz
        self.tag = None          # canvas bookkeeping (owned by the app)
        self.drawn = None

    @property
    def lively(self):
        """Needs smooth (30 fps) animation? Slow-drifting fireflies are fine at 10 fps."""
        return self.shape != "firefly"

    def step(self, dt):
        """Advance by dt seconds; returns False once the particle has faded out."""
        self.age += dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += self.ay * dt
        return self.age < self.life

    def position(self):
        return self.x + self.sway * math.sin(TAU * self.sway_hz * self.age + self.phase), self.y

    def visible(self):
        if self.pulse_hz and math.sin(TAU * self.pulse_hz * self.age + self.phase) < -0.25:
            return False                         # fireflies glow on and off
        if self.blinks and self.age > self.life * 0.65 and int(self.age * 30) % 2:
            return False                         # twinkle out at the end
        return True


class Butterfly:
    """Flutters in from the edge, rests by a flower or the companion's head, then drifts away."""

    def __init__(self, start, rest, leave_to, wing_color, unit, rest_secs):
        self.x, self.y = start
        self.rest_at = rest
        self.leave_to = leave_to
        self.colors = (wing_color,) + sprites.SHAPES["fly_a"][1][1:]
        self.unit = unit                         # screen px per sprite pixel
        self.speed = 10.0 * unit                 # px per second
        self.rest_left = rest_secs
        self.state = "arrive"
        self.age = 0.0
        self.tag = None
        self.drawn = None

    @property
    def done(self):
        return self.state == "gone"

    def _toward(self, target, dt):
        dx, dy = target[0] - self.x, target[1] - self.y
        dist = math.hypot(dx, dy)
        reach = self.speed * dt
        if dist <= max(reach, self.unit * 0.5):
            self.x, self.y = target
            return True
        self.x += dx / dist * reach
        self.y += dy / dist * reach
        return False

    def step(self, dt):
        self.age += dt
        if self.state == "arrive":
            if self._toward(self.rest_at, dt):
                self.state = "rest"
        elif self.state == "rest":
            self.rest_left -= dt
            if self.rest_left <= 0:
                self.state = "leave"
        elif self.state == "leave":
            if self._toward(self.leave_to, dt):
                self.state = "gone"
        return not self.done

    def position(self):
        if self.state == "rest":                 # a slow, sleepy bob
            return self.x, self.y + math.sin(TAU * 0.5 * self.age) * self.unit * 0.3
        return self.x, self.y + math.sin(TAU * 2.2 * self.age) * self.unit * 1.2

    @property
    def shape(self):
        flaps_per_sec = 1.5 if self.state == "rest" else 7.0
        return "fly_a" if int(self.age * flaps_per_sec) % 2 == 0 else "fly_b"

    def visible(self):
        return True

    @property
    def lively(self):
        return self.state != "rest"
