"""The cozy speech bubble (its own little window) plus pixel-art canvas drawing helpers."""

import tkinter as tk

import sprites
import theme
import winutil


def draw_round_rect(canvas, x0, y0, x1, y1, step, fill, edge, tags=()):
    """A pixel-art rounded box: a one-step outline with chamfered corners."""
    for (ax, ay, bx, by), colour in (
            ((x0 + step, y0, x1 - step, y1), edge),
            ((x0, y0 + step, x1, y1 - step), edge),
            ((x0 + 2 * step, y0 + step, x1 - 2 * step, y1 - step), fill),
            ((x0 + step, y0 + 2 * step, x1 - step, y1 - 2 * step), fill)):
        canvas.create_rectangle(ax, ay, bx, by, fill=colour, outline="", tags=tags)


def draw_shape(canvas, shape, x, y, size, colors=None, tags=()):
    """Draw one of sprites.SHAPES with its top-left corner at (x, y), `size` px per cell."""
    rows, default_colors = sprites.SHAPES[shape]
    colors = colors or default_colors
    x, y = int(x), int(y)
    for ry, row in enumerate(rows):
        for rx, cell in enumerate(row):
            if cell != "0":
                colour = colors[int(cell) - 1]
                cx, cy = x + rx * size, y + ry * size
                canvas.create_rectangle(cx, cy, cx + size, cy + size, fill=colour, outline="", tags=tags)


def shape_size(shape):
    rows = sprites.SHAPES[shape][0]
    return len(rows[0]), len(rows)


class Bubble:
    """A speech bubble that floats above (or, without room, below) the companion."""

    MAX_TEXT_W = 210            # px at 100% display scale

    def __init__(self, root, font, ui):
        self.font = font
        self.ui = ui
        self.step = max(2, round(2 * ui))       # one "pixel" of the bubble's pixel art
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        for attr, value in (("-topmost", True), ("-transparentcolor", sprites.TRANSP)):
            try:
                self.win.attributes(attr, value)
            except tk.TclError:
                pass
        self.win.configure(bg=sprites.TRANSP)
        self.canvas = tk.Canvas(self.win, bg=sprites.TRANSP, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", lambda _e: self.hide())
        self.text = ""
        self.icon = None
        self.until = 0.0
        self.priority = -1
        self.visible = False
        self.hwnd = 0
        self.size = (0, 0)
        self._drawn = None
        self._geo = None
        self._metrics = None

    # ── public ───────────────────────────────────────────────
    def say(self, text, now, icon=None, secs=5.0, priority=1):
        """Show `text` for `secs`. A lower-priority message never interrupts a higher one."""
        if self.text and now < self.until and priority < self.priority:
            return False
        self.text, self.icon, self.until, self.priority = text, icon, now + secs, priority
        self._drawn = None
        return True

    def hide(self):
        self.text = ""
        self.priority = -1
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def update(self, now, anchor_x, top_y, bottom_y, area, allowed=True):
        """Follow the companion. `area` is the (l, t, r, b) work area of its monitor."""
        if not self.text or now >= self.until or not allowed:
            self.hide()
            return
        w, h, body_h = self._measure()
        left, top, right, bottom = area
        x = int(min(max(anchor_x - w / 2, left), max(left, right - w)))
        tail_up = top_y - h < top                       # no room above: hang below instead
        y = int(bottom_y if tail_up else top_y - h)
        tail_x = int(min(max(anchor_x - x, 5 * self.step), w - 5 * self.step))
        key = (self.text, self.icon, tail_x, tail_up)
        if key != self._drawn:
            self._draw(w, h, body_h, tail_x, tail_up)
            self._drawn = key
        if self._geo != (w, h, x, y):
            self.win.geometry(f"{w}x{h}+{x}+{y}")
            self._geo = (w, h, x, y)
        if not self.visible:
            self.win.deiconify()
            self.win.update_idletasks()
            self.hwnd = winutil.toplevel_hwnd(self.win.winfo_id())
            if not winutil.make_overlay(self.hwnd):     # on Windows this also raises it to the top
                self.win.lift()
            self.visible = True

    # ── drawing ──────────────────────────────────────────────
    def _icon_box(self):
        if not self.icon:
            return 0, 0
        cols, rows = shape_size(self.icon)
        return cols * self.step, rows * self.step

    def _measure(self):
        key = (self.text, self.icon)
        if self._metrics is None or self._metrics[0] != key:     # measure once per message
            self._metrics = (key, self._measure_now())
        return self._metrics[1]

    def _measure_now(self):
        s = self.step
        probe = self.canvas.create_text(0, 0, text=self.text, font=self.font, anchor="nw",
                                        width=int(self.MAX_TEXT_W * self.ui))
        x0, y0, x1, y1 = self.canvas.bbox(probe)
        self.canvas.delete(probe)
        icon_w, icon_h = self._icon_box()
        gap = 3 * s if icon_w else 0
        w = 5 * s + icon_w + gap + (x1 - x0) + 5 * s
        body_h = max(y1 - y0, icon_h) + 7 * s
        return int(w), int(body_h + 2 * s), int(body_h)

    def _draw(self, w, h, body_h, tail_x, tail_up):
        c, s = self.canvas, self.step
        c.delete("all")
        c.config(width=w, height=h)
        self.size = (w, h)
        y0 = 2 * s if tail_up else 0
        y1 = y0 + body_h
        draw_round_rect(c, 0, y0, w, y1, s, theme.CREAM, theme.CREAM_EDGE)
        # Little tail pointing at the companion.
        if tail_up:
            parts = (((tail_x - s, y0, tail_x + s, y0 + s), theme.CREAM),
                     ((tail_x - 2 * s, y0 - s, tail_x + 2 * s, y0), theme.CREAM_EDGE),
                     ((tail_x - s, y0 - s, tail_x + s, y0), theme.CREAM),
                     ((tail_x - s, y0 - 2 * s, tail_x + s, y0 - s), theme.CREAM_EDGE))
        else:
            parts = (((tail_x - s, y1 - s, tail_x + s, y1), theme.CREAM),
                     ((tail_x - 2 * s, y1, tail_x + 2 * s, y1 + s), theme.CREAM_EDGE),
                     ((tail_x - s, y1, tail_x + s, y1 + s), theme.CREAM),
                     ((tail_x - s, y1 + s, tail_x + s, y1 + 2 * s), theme.CREAM_EDGE))
        for (ax, ay, bx, by), colour in parts:
            c.create_rectangle(ax, ay, bx, by, fill=colour, outline="")
        icon_w, icon_h = self._icon_box()
        text_x = 5 * s
        if icon_w:
            draw_shape(c, self.icon, 5 * s, y0 + (body_h - icon_h) / 2, s)
            text_x += icon_w + 3 * s
        c.create_text(text_x, y0 + body_h / 2, text=self.text, font=self.font, fill=theme.COCOA,
                      anchor="w", width=int(self.MAX_TEXT_W * self.ui))
