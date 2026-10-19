"""Global keyboard watching. Two interchangeable backends feed a TypingMeter:

* PynputBackend  - low-level keyboard hook via the optional `pynput` package (preferred).
* PollingBackend - polls GetAsyncKeyState; needs nothing installed, so the companion still
                   works on a fresh Python install where `pip install pynput` was never run.

Only the timing of key presses is forwarded. The key itself is reduced to an opaque id
that lives in memory while the key is held and is then forgotten.
"""

import logging
import threading
import time

import core
import winutil

log = logging.getLogger("companion")


# ══════════════════════════════════════════════════════════════
#  pynput
# ══════════════════════════════════════════════════════════════
def key_id(key):
    """Opaque, hashable id for a pynput key (virtual-key code when available)."""
    vk = getattr(key, "vk", None)
    if vk is None:
        vk = getattr(getattr(key, "value", None), "vk", None)
    return vk if vk is not None else repr(key)


def is_modifier(key):
    return getattr(key, "name", None) in core.MODIFIER_NAMES


class PynputBackend:
    name = "pynput"

    def __init__(self, meter):
        from pynput import keyboard     # ImportError here makes the caller fall back

        class DesktopListener(keyboard.Listener):
            """Attaches the hook thread to the interactive desktop before it starts."""

            def _run(self_):
                winutil.attach_to_default_desktop()
                super()._run()

        self._meter = meter
        self._factory = DesktopListener
        self._listener = None

    def start(self):
        self._listener = self._factory(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass

    def alive(self):
        return bool(self._listener and self._listener.is_alive())

    def _on_press(self, key):
        self._meter.key_down(key_id(key), is_modifier(key))

    def _on_release(self, key):
        self._meter.key_up(key_id(key))


# ══════════════════════════════════════════════════════════════
#  Polling fallback
# ══════════════════════════════════════════════════════════════
def _polled_keys():
    """Virtual-key codes worth polling: typing keys only (modifiers never count anyway)."""
    vks = {0x08, 0x09, 0x0D, 0x20, 0x2E}                       # Back, Tab, Enter, Space, Delete
    vks.update(range(0x30, 0x3A))                              # 0-9
    vks.update(range(0x41, 0x5B))                              # A-Z
    vks.update(range(0x60, 0x70))                              # numpad
    vks.update(range(0xBA, 0xC1))                              # ; = , - . / `
    vks.update(range(0xDB, 0xE0))                              # [ \ ] ' ...
    return tuple(sorted(vks))


class PollingBackend:
    name = "polling"
    POLL_HZ = 60

    def __init__(self, meter, is_down=winutil.async_key_is_down, keys=None):
        self._meter = meter
        self._is_down = is_down
        self._keys = tuple(keys) if keys is not None else _polled_keys()
        self._held = set()
        self._stop = threading.Event()
        self._thread = None

    def poll_once(self):
        """Compare key states with the previous poll and report presses/releases."""
        down = {vk for vk in self._keys if self._is_down(vk)}
        for vk in down - self._held:
            self._meter.key_down(vk, False)
        for vk in self._held - down:
            self._meter.key_up(vk)
        self._held = down

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="key-poll", daemon=True)
        self._thread.start()

    def _loop(self):
        next_report = 0.0
        while not self._stop.wait(1.0 / self.POLL_HZ):
            try:
                self.poll_once()
            except Exception:
                now = time.monotonic()
                if now >= next_report:          # at most one traceback a minute, not 60 a second
                    next_report = now + 60.0
                    log.exception("key polling failed")

    def stop(self):
        self._stop.set()

    def alive(self):
        return bool(self._thread and self._thread.is_alive())


def start_backend(meter, prefer_pynput=True):
    """Start the best available backend. Returns it, or None if nothing could be started."""
    if prefer_pynput:
        try:
            backend = PynputBackend(meter)
            backend.start()
            log.info("keyboard backend: pynput")
            return backend
        except Exception as exc:
            log.warning("pynput unavailable (%s: %s); using key polling instead", type(exc).__name__, exc)
    if winutil.IS_WINDOWS:
        backend = PollingBackend(meter)
        backend.start()
        log.info("keyboard backend: polling")
        return backend
    log.warning("no keyboard backend available on this platform")
    return None
