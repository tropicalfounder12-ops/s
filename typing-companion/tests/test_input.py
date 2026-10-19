import ctypes
import importlib
import os
import sys
import threading
import types
import unittest
from ctypes import wintypes
from unittest import mock

from tests.helpers import FakeClock

import core
import keyboard_input
import winutil


class PollingBackendTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.meter = core.TypingMeter(clock=self.clock)
        self.down = set()
        self.backend = keyboard_input.PollingBackend(self.meter, is_down=self.down.__contains__)

    def poll(self, advance=0.016):
        self.clock.advance(advance)
        self.backend.poll_once()
        return self.meter.snapshot()

    def test_press_counts_once_while_held_and_again_after_release(self):
        self.down.add(65)
        self.assertEqual(self.poll().total, 1)
        for _ in range(30):                       # still held: no extra keystrokes
            self.assertEqual(self.poll().total, 1)
        self.down.clear()
        self.poll()
        self.down.add(65)
        self.assertEqual(self.poll().total, 2)

    def test_two_keys_down_together(self):
        self.down.update({65, 66})
        self.assertEqual(self.poll().total, 2)

    def test_polled_set_covers_typing_keys_but_not_mouse_or_modifiers(self):
        keys = set(keyboard_input._polled_keys())
        for vk in (ord("A"), ord("Z"), ord("0"), 0x20, 0x0D, 0x08):
            self.assertIn(vk, keys)
        for vk in list(range(0x01, 0x07)) + [0x10, 0x11, 0x12, 0x5B, 0xA0, 0xA2, 0xA4]:
            self.assertNotIn(vk, keys, hex(vk))

    def test_thread_starts_and_stops(self):
        self.backend.start()
        self.assertTrue(self.backend.alive())
        self.backend.stop()
        self.backend._thread.join(1)
        self.assertFalse(self.backend.alive())

    def test_poll_errors_do_not_kill_the_thread(self):
        calls = []

        def flaky(vk):
            calls.append(vk)
            raise OSError("boom")

        backend = keyboard_input.PollingBackend(self.meter, is_down=flaky)
        backend.POLL_HZ = 500
        backend.start()
        try:
            for _ in range(200):
                if len(calls) > len(backend._keys) * 2:     # polled more than once
                    break
                threading.Event().wait(0.01)
            self.assertTrue(backend.alive())
        finally:
            backend.stop()


class FakeKey:
    def __init__(self, vk=None, name=None):
        if vk is not None:
            self.vk = vk
        if name is not None:
            self.name = name


class PynputHelperTests(unittest.TestCase):
    def test_key_id_prefers_virtual_key_code(self):
        self.assertEqual(keyboard_input.key_id(FakeKey(vk=65)), 65)
        special = types.SimpleNamespace(value=FakeKey(vk=0xA0), name="shift")
        self.assertEqual(keyboard_input.key_id(special), 0xA0)
        self.assertIsInstance(keyboard_input.key_id(object()), str)

    def test_modifier_detection_by_name(self):
        for name in ("shift", "shift_r", "ctrl_l", "alt_gr", "cmd", "caps_lock"):
            self.assertTrue(keyboard_input.is_modifier(FakeKey(name=name)), name)
        for key in (FakeKey(name="space"), FakeKey(name="backspace"), FakeKey(vk=65)):
            self.assertFalse(keyboard_input.is_modifier(key))


def install_fake_pynput(run_exits_immediately=False):
    """Register a stand-in `pynput` whose Listener mimics the real thread + _run structure."""
    class Listener(threading.Thread):
        def __init__(self, on_press=None, on_release=None):
            super().__init__()
            self.on_press, self.on_release = on_press, on_release
            self.ran = threading.Event()
            self.stop_flag = threading.Event()

        def run(self):
            self._run()

        def _run(self):
            self.ran.set()
            if not run_exits_immediately:
                self.stop_flag.wait(5)

        def stop(self):
            self.stop_flag.set()

    module = types.ModuleType("pynput")
    module.keyboard = types.SimpleNamespace(Listener=Listener)
    sys.modules["pynput"] = module
    return Listener


class PynputBackendTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("pynput", None)

    def test_events_reach_the_meter_and_hook_thread_attaches_to_desktop(self):
        install_fake_pynput()
        meter = core.TypingMeter(clock=FakeClock())
        attached = []
        with mock.patch.object(winutil, "attach_to_default_desktop", lambda: attached.append(1)):
            backend = keyboard_input.PynputBackend(meter)
            backend.start()
            try:
                self.assertTrue(backend._listener.ran.wait(2))
                self.assertEqual(attached, [1])                    # the desktop-attach override ran
                self.assertTrue(backend.alive())
                backend._listener.on_press(FakeKey(vk=65))
                backend._listener.on_press(FakeKey(vk=65))         # auto-repeat
                backend._listener.on_press(FakeKey(vk=16, name="shift"))
                backend._listener.on_release(FakeKey(vk=65))
                backend._listener.on_press(FakeKey(vk=65))
                self.assertEqual(meter.snapshot().total, 2)
            finally:
                backend.stop()

    def test_alive_turns_false_when_the_hook_thread_dies(self):
        install_fake_pynput(run_exits_immediately=True)
        backend = keyboard_input.PynputBackend(core.TypingMeter(clock=FakeClock()))
        backend.start()
        backend._listener.join(2)
        self.assertFalse(backend.alive())                          # this is what the watchdog sees

    def test_start_backend_falls_back_when_pynput_is_missing(self):
        sys.modules["pynput"] = None                               # makes `import pynput` fail
        meter = core.TypingMeter(clock=FakeClock())
        with mock.patch.object(winutil, "IS_WINDOWS", False):
            self.assertIsNone(keyboard_input.start_backend(meter))
        with mock.patch.object(winutil, "IS_WINDOWS", True):
            backend = keyboard_input.start_backend(meter)
            try:
                self.assertEqual(backend.name, "polling")
            finally:
                backend.stop()

    def test_start_backend_prefers_pynput(self):
        install_fake_pynput()
        backend = keyboard_input.start_backend(core.TypingMeter(clock=FakeClock()))
        try:
            self.assertEqual(backend.name, "pynput")
        finally:
            backend.stop()


# ══════════════════════════════════════════════════════════════
#  winutil's Windows branch, driven through fake DLLs
# ══════════════════════════════════════════════════════════════
class FakeFn:
    def __init__(self, impl):
        self.impl, self.argtypes, self.restype = impl, None, None

    def __call__(self, *args):
        return self.impl(*args)


class FakeLib:
    def __init__(self, impls):
        self._impls = impls

    def __getattr__(self, name):
        if name in self._impls:
            return FakeFn(self._impls[name])
        raise AttributeError(name)


def ptr(arg):
    return arg._obj            # the object behind ctypes.byref(...)


def set_rect(rect, l, t, r, b):
    rect.left, rect.top, rect.right, rect.bottom = l, t, r, b


class WinutilWindowsBranchTests(unittest.TestCase):
    def setUp(self):
        self.s = {                        # tweakable "world" the fake DLLs report on
            "pid": 4242, "cls": "Chrome_WidgetWin_1", "cloaked": 0, "dwm_ok": True,
            "frame": (100, 50, 900, 650), "visible": 1, "iconic": 0, "notify": 3,
            "last_error": 0, "keys_down": {65}, "exstyle": 0x00040000,
        }
        self.calls = []
        s, calls = self.s, self.calls

        def get_class(h, buf, n):
            buf.value = s["cls"]
            return len(s["cls"])

        def get_pid(h, p):
            ptr(p).value = s["pid"]
            return 1

        def window_rect(h, p):
            set_rect(ptr(p), 90, 40, 910, 660)      # includes the invisible resize border
            return 1

        def dwm(h, attr, p, size):
            if attr == 14:
                ptr(p).value = s["cloaked"]
                return 0
            if not s["dwm_ok"]:
                return 1
            set_rect(ptr(p), *s["frame"])
            return 0

        def monitor_info(h, p):
            info = ptr(p)
            set_rect(info.rcMonitor, 0, 0, 1920, 1080)
            set_rect(info.rcWork, 0, 0, 1920, 1040)
            return 1

        def spi(action, a, p, b):
            set_rect(ptr(p), 0, 0, 1920, 1040)
            return 1

        def notify(p):
            ptr(p).value = s["notify"]
            return 0

        def set_style(h, idx, val):
            calls.append(("SetWindowLong", idx, val))
            return 0

        def set_pos(*a):
            calls.append(("SetWindowPos",) + a)
            return 1

        user32 = FakeLib({
            "GetForegroundWindow": lambda: 0x1234, "IsWindowVisible": lambda h: s["visible"],
            "IsIconic": lambda h: s["iconic"], "GetClassNameW": get_class,
            "GetWindowThreadProcessId": get_pid, "GetWindowRect": window_rect,
            "GetAncestor": lambda h, f: 0x99, "GetWindowLongPtrW": lambda h, i: s["exstyle"],
            "SetWindowLongPtrW": set_style, "SetWindowPos": set_pos,
            "SetForegroundWindow": lambda h: 1, "IsWindow": lambda h: 1,
            "MonitorFromPoint": lambda pt, flags: 0x77, "GetMonitorInfoW": monitor_info,
            "SystemParametersInfoW": spi, "GetAsyncKeyState": lambda vk: -32768 if vk in s["keys_down"] else 0,
            "OpenInputDesktop": lambda *a: 5, "SetThreadDesktop": lambda h: 1,
            "MessageBoxW": lambda *a: calls.append(("MessageBox",) + a) or 1,
            "SetProcessDpiAwarenessContext": lambda c: calls.append(("dpi", c)) or 1,
            "SetProcessDPIAware": lambda: 1,
        })
        libs = {
            "user32": user32,
            "kernel32": FakeLib({"CreateMutexW": lambda *a: 9}),
            "shell32": FakeLib({"SHQueryUserNotificationState": notify}),
            "dwmapi": FakeLib({"DwmGetWindowAttribute": dwm}),
        }
        self.patches = [
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(ctypes, "WinDLL", lambda name, **kw: libs[name], create=True),
            mock.patch.object(ctypes, "get_last_error", lambda: s["last_error"], create=True),
            mock.patch.object(ctypes, "set_last_error", lambda v: None, create=True),
        ]
        for p in self.patches:
            p.start()
        importlib.reload(winutil)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        importlib.reload(winutil)

    def test_perch_rect_uses_visible_frame_not_the_padded_window_rect(self):
        self.assertEqual(winutil.perch_rect(), (100, 50, 900, 650))

    def test_perch_rect_falls_back_to_window_rect_without_dwm(self):
        self.s["dwm_ok"] = False
        self.assertEqual(winutil.perch_rect(), (90, 40, 910, 660))

    def test_perch_rect_skips_unsuitable_windows(self):
        for key, value in (("pid", os.getpid()), ("cls", "Shell_TrayWnd"), ("cls", "Progman"),
                           ("cls", "#32768"), ("cloaked", 1), ("visible", 0), ("iconic", 1),
                           ("frame", (0, 0, 60, 20))):
            with self.subTest(**{key: value}):
                setup = dict(self.s)
                self.s[key] = value
                self.assertIsNone(winutil.perch_rect())
                self.s.update(setup)
        self.assertIsNotNone(winutil.perch_rect())

    def test_monitor_and_work_area(self):
        self.assertEqual(winutil.monitor_areas_at(10, 10), ((0, 0, 1920, 1080), (0, 0, 1920, 1040)))
        self.assertEqual(winutil.primary_work_area(), (0, 0, 1920, 1040))

    def test_fullscreen_detection(self):
        for state, expected in ((1, False), (2, True), (3, True), (4, True), (5, False), (6, False)):
            self.s["notify"] = state
            self.assertEqual(winutil.fullscreen_app_running(), expected, state)

    def test_overlay_style_is_noactivate_toolwindow_without_appwindow(self):
        self.assertEqual(winutil.toplevel_hwnd(7), 0x99)
        self.assertTrue(winutil.make_overlay(0x99))
        style = next(c[2] for c in self.calls if c[0] == "SetWindowLong")
        self.assertTrue(style & winutil.WS_EX_NOACTIVATE)
        self.assertTrue(style & winutil.WS_EX_TOOLWINDOW)
        self.assertFalse(style & winutil.WS_EX_APPWINDOW)
        self.assertTrue(winutil.keep_on_top(0x99))
        pos = [c for c in self.calls if c[0] == "SetWindowPos"][-1]
        self.assertEqual(pos[2], winutil.HWND_TOPMOST)

    def test_single_instance(self):
        self.s["last_error"] = 0
        self.assertTrue(winutil.acquire_single_instance("test-mutex"))
        self.s["last_error"] = 183
        self.assertFalse(winutil.acquire_single_instance("test-mutex"))

    def test_keys_dpi_desktop_and_messagebox(self):
        self.assertTrue(winutil.async_key_is_down(65))
        self.assertFalse(winutil.async_key_is_down(66))
        self.assertTrue(winutil.enable_dpi_awareness())
        self.assertTrue(winutil.attach_to_default_desktop())
        winutil.show_message("t", "m")
        self.assertTrue(any(c[0] == "MessageBox" for c in self.calls))
        self.assertTrue(winutil.restore_foreground(0x55))

    def test_api_errors_never_escape(self):
        def boom(*a):
            raise OSError("api exploded")
        with mock.patch.object(winutil, "_GetForegroundWindow", boom), \
                mock.patch.object(winutil, "_SHQueryUserNotificationState", boom), \
                mock.patch.object(winutil, "_MonitorFromPoint", boom), \
                mock.patch.object(winutil, "_SetWindowPos", boom):
            self.assertIsNone(winutil.perch_rect())
            self.assertFalse(winutil.fullscreen_app_running())
            self.assertIsNone(winutil.monitor_areas_at(0, 0))
            self.assertFalse(winutil.keep_on_top(1))

    def test_autostart_command_quotes_paths(self):
        cmd = winutil.autostart_command("C:\\Program Files\\Companion\\companion.py")
        self.assertTrue(cmd.startswith('"'))
        self.assertIn('companion.py"', cmd)


class WinutilNonWindowsTests(unittest.TestCase):
    def test_everything_is_a_safe_no_op(self):
        if sys.platform == "win32":
            self.skipTest("only meaningful off Windows")
        self.assertFalse(winutil.IS_WINDOWS)
        self.assertIsNone(winutil.perch_rect())
        self.assertIsNone(winutil.monitor_areas_at(1, 1))
        self.assertIsNone(winutil.primary_work_area())
        self.assertFalse(winutil.fullscreen_app_running())
        self.assertTrue(winutil.acquire_single_instance())
        self.assertFalse(winutil.make_overlay(1))
        self.assertFalse(winutil.autostart_enabled())
        self.assertEqual(winutil.foreground_window(), 0)


if __name__ == "__main__":
    unittest.main()
