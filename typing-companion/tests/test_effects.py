import unittest

from tests.helpers import FakeClock  # noqa: F401  (sets up sys.path)

from effects import Butterfly, Particle


class ParticleTests(unittest.TestCase):
    def test_moves_falls_and_expires(self):
        p = Particle(0, 0, 10, -20, 1.0, "petal", ay=40)
        self.assertTrue(p.step(0.5))
        self.assertEqual((p.x, p.y), (5.0, -10.0))
        self.assertEqual(p.vy, 0.0)                     # gravity slowed it
        self.assertFalse(p.step(0.6))

    def test_default_colours_come_from_the_shape(self):
        self.assertEqual(Particle(0, 0, 0, 0, 1, "heart").colors, ("#ff8fab", "#ffe0e8"))
        self.assertEqual(Particle(0, 0, 0, 0, 1, "petal", ("#123456",)).colors, ("#123456",))

    def test_sway_moves_sideways_only(self):
        p = Particle(10, 10, 0, 0, 5, "petal", sway=3, sway_hz=1, phase=1.0)
        xs = set()
        for _ in range(20):
            p.step(0.05)
            x, y = p.position()
            xs.add(round(x, 3))
            self.assertEqual(y, 10)
        self.assertGreater(len(xs), 5)
        self.assertTrue(all(7 <= x <= 13 for x in xs))

    def test_fireflies_glow_on_and_off(self):
        p = Particle(0, 0, 0, 0, 10, "firefly", pulse_hz=1.0)
        states = []
        for _ in range(40):
            p.step(0.05)
            states.append(p.visible())
        self.assertIn(True, states)
        self.assertIn(False, states)

    def test_blinking_particles_twinkle_out_at_the_end(self):
        p = Particle(0, 0, 0, 0, 1.0, "spark", blinks=True)
        early = []
        for _ in range(10):
            p.step(0.05)
            early.append(p.visible())
        self.assertTrue(all(early))
        late = []
        for _ in range(9):
            p.step(0.05)
            late.append(p.visible())
        self.assertIn(False, late)


class ButterflyTests(unittest.TestCase):
    def test_arrives_rests_and_leaves(self):
        b = Butterfly((-20, 10), (50, 5), (200, -10), "#cdb4f0", unit=3, rest_secs=2.0)
        states = []
        for _ in range(400):
            b.step(0.05)
            states.append(b.state)
            if b.done:
                break
        order = [s for i, s in enumerate(states) if i == 0 or states[i - 1] != s]
        self.assertEqual(order, ["arrive", "rest", "leave", "gone"])
        self.assertTrue(b.done)
        self.assertEqual((b.x, b.y), (200, -10))
        rest_steps = states.count("rest")
        self.assertAlmostEqual(rest_steps * 0.05, 2.0, delta=0.15)

    def test_flaps_fast_in_flight_and_slowly_at_rest(self):
        b = Butterfly((0, 0), (100, 0), (0, 0), "#ffffff", unit=2, rest_secs=10)
        flying = []
        for _ in range(10):
            b.step(0.03)
            flying.append(b.shape)
        self.assertEqual(set(flying), {"fly_a", "fly_b"})
        b.x, b.y, b.state = 100, 0, "rest"
        resting = []
        for _ in range(10):
            b.step(0.03)
            resting.append(b.shape)
        changes = sum(1 for a, c in zip(resting, resting[1:]) if a != c)
        self.assertLessEqual(changes, 1)
        self.assertEqual(b.colors[0], "#ffffff")


if __name__ == "__main__":
    unittest.main()
