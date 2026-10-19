"""The spring look: soft pastel colours and friendly fonts for everything that isn't sprite art.

None of these colours may equal sprites.TRANSP (the window's see-through colour key).
"""

CREAM = "#fffaf2"          # bubble / badge / menu background
CREAM_EDGE = "#f2cdd8"     # blossom-tinted outline
COCOA = "#6b4f4f"          # warm text colour
COCOA_SOFT = "#a08880"     # secondary text
BLOSSOM = "#ffd1dc"        # turbo badge
BLOSSOM_EDGE = "#ff9fb6"
BLOSSOM_HOVER = "#ffe4ec"  # menu highlight
BUTTER = "#fff0b8"
BUTTER_EDGE = "#f5cf6a"
LEAF = "#6fbf7c"

# Badge styles: (fill, outline, text)
BADGE_CALM = (CREAM, "#ecd9cc", COCOA)
BADGE_TURBO = (BLOSSOM, BLOSSOM_EDGE, "#5a3d3d")

MENU_STYLE = {
    "bg": CREAM,
    "fg": COCOA,
    "activebackground": BLOSSOM_HOVER,
    "activeforeground": "#5a3d3d",
    "selectcolor": "#e0708f",
    "disabledforeground": COCOA_SOFT,
    "relief": "flat",
    "bd": 1,
}

_UI_FAMILIES = ("Segoe UI", "Segoe UI Variable Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans", "Arial")


def pick_family(available, preferred=_UI_FAMILIES):
    """First preferred font family that is installed, else Tk's default."""
    installed = {name.lower() for name in available}
    for family in preferred:
        if family.lower() in installed:
            return family
    return "TkDefaultFont"
