"""Shared test helpers: put the project on sys.path and provide a controllable clock."""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Keep expected error-path logging out of the test output.
logging.getLogger("companion").addHandler(logging.NullHandler())


class FakeClock:
    """A clock tests can move by hand."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs
        return self.t
