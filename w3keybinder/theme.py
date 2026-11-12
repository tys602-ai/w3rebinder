"""Colours and ttk styling. Uses the bundled Sun Valley theme (Windows 11 look) when it loads."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

FONT_FAMILY = "Segoe UI"

PALETTES = {
    "dark": {
        "bg": "#1c1c1c", "panel": "#242424", "card": "#2b2b2b", "fg": "#f2f2f2", "muted": "#a3a3a3",
        "head": "#151515", "head_fg": "#ffffff", "head_sub": "#a9a9a9", "gold": "#d8b25a",
        "accent": "#6cb6ff", "ok": "#56d364", "warn": "#e3b341", "bad": "#ff7b72",
        "key_bg": "#3a3a3a", "key_fg": "#ffffff", "key_border": "#5a5a5a",
        "row_pending": "#6cb6ff", "row_conflict": "#4b2626", "row_needs": "#3f3519",
        "box": "#2f2f2f", "box_fg": "#e0e0e0",
    },
    "light": {
        "bg": "#fafafa", "panel": "#f3f3f3", "card": "#ffffff", "fg": "#1c1c1c", "muted": "#5f6368",
        "head": "#1f1f1f", "head_fg": "#ffffff", "head_sub": "#b5b5b5", "gold": "#b8892a",
        "accent": "#0b57d0", "ok": "#1e8e3e", "warn": "#9a6700", "bad": "#c5221f",
        "key_bg": "#ffffff", "key_fg": "#1c1c1c", "key_border": "#c4c4c4",
        "row_pending": "#0b57d0", "row_conflict": "#fde7e7", "row_needs": "#fff4d6",
        "box": "#eef1f6", "box_fg": "#333333",
    },
}

P = dict(PALETTES["dark"])  # current palette; modules read colours from here


def apply(root: tk.Tk, mode: str) -> str:
    """Apply the theme; returns the mode actually used."""
    mode = mode if mode in PALETTES else "dark"
    P.clear()
    P.update(PALETTES[mode])
    st = ttk.Style(root)
    try:
        from . import sv_ttk
        sv_ttk.set_theme(mode, root)
    except Exception:
        for t in ("vista", "clam"):
            if t in st.theme_names():
                st.theme_use(t)
                break
    f = FONT_FAMILY
    # plain tk widgets (labels, dialogs, list boxes) follow the palette too
    for opt, val in (("*Background", P["bg"]), ("*Foreground", P["fg"]), ("*Font", (f, 10)),
                     ("*Listbox.background", P["card"]), ("*Listbox.foreground", P["fg"]),
                     ("*Text.background", P["card"]), ("*Text.foreground", P["fg"]),
                     ("*Text.insertBackground", P["fg"]), ("*selectBackground", P["accent"]),
                     ("*Menu.background", P["panel"]), ("*Menu.foreground", P["fg"]),
                     ("*Menu.activeBackground", P["accent"])):
        root.option_add(opt, val)
    root.configure(bg=P["bg"])
    st.configure(".", font=(f, 10))
    st.configure("Treeview", rowheight=30, font=(f, 10))
    st.configure("Treeview.Heading", font=(f, 10, "bold"))
    st.configure("Side.Treeview", rowheight=32, font=(f, 10))
    st.configure("Big.Accent.TButton", font=(f, 11, "bold"), padding=(20, 8))
    st.configure("Wide.Accent.TButton", font=(f, 11, "bold"), padding=(10, 8))
    st.configure("TButton", padding=(10, 5))
    st.configure("Title.TLabel", font=(f, 14, "bold"))
    st.configure("Muted.TLabel", foreground=P["muted"])
    return mode
