"""Windows-specific helpers (ctypes). Every function is safe to call anywhere.

On non-Windows platforms they return neutral values, and on Windows they swallow API
errors, so a quirk in one call can never take the whole companion down.
"""

import logging
import os
import sys

log = logging.getLogger("companion")

IS_WINDOWS = sys.platform == "win32"

# Windows classes that should never be perched on (taskbar, desktop, popup menus, ...).
SHELL_CLASSES = frozenset({
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "#32768",
    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
    "MultitaskingViewFrame", "ForegroundStaging", "Windows.UI.Core.CoreWindow",
})

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "TypingCompanion"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:  # pragma: no cover - dwmapi ships with every supported Windows
        dwmapi = None

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def _declare(lib, name, restype, *argtypes):
        """Give a DLL function proper types (without them 64-bit handles get truncated)."""
        try:
            fn = getattr(lib, name)
        except AttributeError:      # API missing on this Windows version
            return None
        fn.restype = restype
        fn.argtypes = list(argtypes)
        return fn

    _H = wintypes.HWND
    _GetForegroundWindow = _declare(user32, "GetForegroundWindow", _H)
    _GetWindowRect = _declare(user32, "GetWindowRect", wintypes.BOOL, _H, ctypes.POINTER(wintypes.RECT))
    _IsWindowVisible = _declare(user32, "IsWindowVisible", wintypes.BOOL, _H)
    _IsIconic = _declare(user32, "IsIconic", wintypes.BOOL, _H)
    _GetClassNameW = _declare(user32, "GetClassNameW", ctypes.c_int, _H, wintypes.LPWSTR, ctypes.c_int)
    _GetWindowThreadProcessId = _declare(user32, "GetWindowThreadProcessId", wintypes.DWORD, _H,
                                         ctypes.POINTER(wintypes.DWORD))
    _GetAncestor = _declare(user32, "GetAncestor", _H, _H, wintypes.UINT)
    _SetWindowPos = _declare(user32, "SetWindowPos", wintypes.BOOL, _H, _H, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT)
    _SetForegroundWindow = _declare(user32, "SetForegroundWindow", wintypes.BOOL, _H)
    _IsWindow = _declare(user32, "IsWindow", wintypes.BOOL, _H)
    _MonitorFromPoint = _declare(user32, "MonitorFromPoint", wintypes.HANDLE, wintypes.POINT, wintypes.DWORD)
    _GetMonitorInfoW = _declare(user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HANDLE,
                                ctypes.POINTER(MONITORINFO))
    _SystemParametersInfoW = _declare(user32, "SystemParametersInfoW", wintypes.BOOL, wintypes.UINT,
                                      wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
    _GetAsyncKeyState = _declare(user32, "GetAsyncKeyState", ctypes.c_short, ctypes.c_int)
    _OpenInputDesktop = _declare(user32, "OpenInputDesktop", wintypes.HANDLE, wintypes.DWORD,
                                 wintypes.BOOL, wintypes.DWORD)
    _SetThreadDesktop = _declare(user32, "SetThreadDesktop", wintypes.BOOL, wintypes.HANDLE)
    _MessageBoxW = _declare(user32, "MessageBoxW", ctypes.c_int, _H, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.UINT)
    _SetDpiContext = _declare(user32, "SetProcessDpiAwarenessContext", wintypes.BOOL, ctypes.c_void_p)
    _SetDpiAware = _declare(user32, "SetProcessDPIAware", wintypes.BOOL)
    _CreateMutexW = _declare(kernel32, "CreateMutexW", wintypes.HANDLE, ctypes.c_void_p, wintypes.BOOL,
                             wintypes.LPCWSTR)
    _SHQueryUserNotificationState = _declare(shell32, "SHQueryUserNotificationState", ctypes.c_long,
                                             ctypes.POINTER(ctypes.c_int))
    _DwmGetWindowAttribute = (_declare(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, _H, wintypes.DWORD,
                                       ctypes.c_void_p, wintypes.DWORD) if dwmapi else None)
    # Pointer-sized window-long accessors (the *Ptr names don't exist on 32-bit Windows).
    _GetWindowLong = (_declare(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, _H, ctypes.c_int)
                      or _declare(user32, "GetWindowLongW", ctypes.c_ssize_t, _H, ctypes.c_int))
    _SetWindowLong = (_declare(user32, "SetWindowLongPtrW", ctypes.c_ssize_t, _H, ctypes.c_int, ctypes.c_ssize_t)
                      or _declare(user32, "SetWindowLongW", ctypes.c_ssize_t, _H, ctypes.c_int, ctypes.c_ssize_t))

_mutex_handle = None       # kept alive for the life of the process (single-instance lock)
_desktop_handle = None     # must stay open while a thread uses it


# ══════════════════════════════════════════════════════════════
#  Process setup
# ══════════════════════════════════════════════════════════════
def enable_dpi_awareness():
    """Opt in to real pixels (crisp sprite, correct coordinates on 125%/150% displays).

    Must run before the first Tk window is created.
    """
    if not IS_WINDOWS:
        return False
    try:
        if _SetDpiContext and _SetDpiContext(ctypes.c_void_p(-4)):      # per-monitor v2
            return True
        try:
            if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:     # per-monitor
                return True
        except (OSError, AttributeError):
            pass
        return bool(_SetDpiAware and _SetDpiAware())
    except Exception as exc:        # never let DPI setup stop the app
        log.debug("dpi awareness failed: %s", exc)
        return False


def attach_to_default_desktop():
    """Bind the calling thread to the interactive desktop (needed for global key hooks)."""
    global _desktop_handle
    if not IS_WINDOWS or not (_OpenInputDesktop and _SetThreadDesktop):
        return False
    try:
        handle = _OpenInputDesktop(0, False, 0x01FF)
        if handle and _SetThreadDesktop(handle):
            _desktop_handle = handle
            return True
    except Exception as exc:
        log.debug("attach_to_default_desktop failed: %s", exc)
    return False


def acquire_single_instance(name="Local\\TypingCompanion.SingleInstance"):
    """True if this is the only running copy (so double-clicking run.bat twice can't stack two)."""
    global _mutex_handle
    if not IS_WINDOWS or not _CreateMutexW:
        return True
    try:
        ctypes.set_last_error(0)
        handle = _CreateMutexW(None, False, name)
        already = ctypes.get_last_error() == 183        # ERROR_ALREADY_EXISTS
        if handle and not already:
            _mutex_handle = handle
        return not already
    except Exception as exc:
        log.debug("single-instance check failed: %s", exc)
        return True


def show_message(title, text):
    """Native message box (the app usually runs under pythonw, which has no console)."""
    if IS_WINDOWS and _MessageBoxW:
        try:
            _MessageBoxW(None, text, title, 0x40)       # MB_ICONINFORMATION
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


# ══════════════════════════════════════════════════════════════
#  Windows / monitors
# ══════════════════════════════════════════════════════════════
def _rect_tuple(rect):
    return rect.left, rect.top, rect.right, rect.bottom


def primary_work_area():
    """(left, top, right, bottom) of the primary monitor minus the taskbar, or None."""
    if not IS_WINDOWS or not _SystemParametersInfoW:
        return None
    try:
        rect = wintypes.RECT()
        if _SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):    # SPI_GETWORKAREA
            return _rect_tuple(rect)
    except Exception:
        pass
    return None


def monitor_areas_at(x, y):
    """((monitor rect), (work-area rect)) of the monitor nearest to (x, y), or None."""
    if not IS_WINDOWS or not (_MonitorFromPoint and _GetMonitorInfoW):
        return None
    try:
        hmon = _MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)     # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if hmon and _GetMonitorInfoW(hmon, ctypes.byref(info)):
            return _rect_tuple(info.rcMonitor), _rect_tuple(info.rcWork)
    except Exception:
        pass
    return None


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    return buf.value if _GetClassNameW(hwnd, buf, 256) else ""


def perch_rect():
    """Visible frame of the foreground window if it's something worth perching on, else None.

    Skips our own windows, the taskbar/desktop/start menu, minimised and cloaked windows,
    and uses the DWM frame bounds so the invisible resize border doesn't offset the sprite.
    """
    if not IS_WINDOWS or not (_GetForegroundWindow and _GetWindowRect):
        return None
    try:
        hwnd = _GetForegroundWindow()
        if not hwnd or not _IsWindowVisible(hwnd) or _IsIconic(hwnd):
            return None
        pid = wintypes.DWORD(0)
        _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid() or _class_name(hwnd) in SHELL_CLASSES:
            return None
        rect = wintypes.RECT()
        if _DwmGetWindowAttribute:
            cloaked = wintypes.DWORD(0)
            if _DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                return None
            if _DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                rect = wintypes.RECT()
                if not _GetWindowRect(hwnd, ctypes.byref(rect)):
                    return None
        elif not _GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        left, top, right, bottom = _rect_tuple(rect)
        if right - left < 100 or bottom - top < 40:
            return None
        return left, top, right, bottom
    except Exception as exc:
        log.debug("perch_rect failed: %s", exc)
        return None


def fullscreen_app_running():
    """True while a fullscreen game/video/presentation is up (so the sprite can step aside)."""
    if not IS_WINDOWS or not _SHQueryUserNotificationState:
        return False
    try:
        state = ctypes.c_int(0)
        if _SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value in (2, 3, 4)     # BUSY, D3D fullscreen, presentation mode
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════════
#  Our own overlay window
# ══════════════════════════════════════════════════════════════
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_FLAGS = 0x0001 | 0x0002 | 0x0010            # NOSIZE | NOMOVE | NOACTIVATE
SWP_FRAMECHANGED = 0x0020


def toplevel_hwnd(winfo_id):
    """The real top-level window behind a Tk widget id (Tk nests the widget in a wrapper)."""
    if not IS_WINDOWS or not _GetAncestor:
        return 0
    try:
        return _GetAncestor(winfo_id, 2) or winfo_id        # GA_ROOT
    except Exception:
        return winfo_id


def make_overlay(hwnd):
    """Tool-window + no-activate: clicking or dragging the sprite no longer steals keyboard
    focus from the app you're typing in, and it stays out of Alt-Tab."""
    if not IS_WINDOWS or not hwnd or not (_GetWindowLong and _SetWindowLong and _SetWindowPos):
        return False
    try:
        style = _GetWindowLong(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
        _SetWindowLong(hwnd, GWL_EXSTYLE, style)
        _SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS | SWP_FRAMECHANGED)
        return True
    except Exception as exc:
        log.debug("make_overlay failed: %s", exc)
        return False


def keep_on_top(hwnd):
    """Re-assert topmost without activating (clicking the taskbar pushes us underneath it)."""
    if not IS_WINDOWS or not hwnd or not _SetWindowPos:
        return False
    try:
        return bool(_SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS))
    except Exception:
        return False


def foreground_window():
    if not IS_WINDOWS or not _GetForegroundWindow:
        return 0
    try:
        return _GetForegroundWindow() or 0
    except Exception:
        return 0


def restore_foreground(hwnd):
    """Hand focus back to `hwnd` (used after our context menu closes)."""
    if not IS_WINDOWS or not hwnd or not (_SetForegroundWindow and _IsWindow):
        return False
    try:
        return bool(_IsWindow(hwnd) and _SetForegroundWindow(hwnd))
    except Exception:
        return False


def focus_window(hwnd):
    """Make `hwnd` the foreground window. A popup menu needs its owner to be foreground to
    dismiss correctly when you click elsewhere."""
    return restore_foreground(hwnd)


# ══════════════════════════════════════════════════════════════
#  Keyboard polling (dependency-free fallback when pynput is missing)
# ══════════════════════════════════════════════════════════════
def async_key_is_down(vk):
    if not IS_WINDOWS or not _GetAsyncKeyState:
        return False
    try:
        return bool(_GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
#  Start with Windows
# ══════════════════════════════════════════════════════════════
def autostart_command(script_path):
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(script_path)}"'


def autostart_enabled():
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False


def set_autostart(enabled, script_path):
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command(script_path))
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        log.warning("could not update autostart: %s", exc)
        return False
