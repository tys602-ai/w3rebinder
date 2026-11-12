"""W3 KeyBinder window."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from . import __version__
from . import paths
from . import settings_file as sf
from .ahk import generate_ahk
from .combohelper import IS_WINDOWS, ComboHelper, XInput, get_autostart, set_autostart
from .keys import (ALL_LABELS, DEFAULT_PROXY_POOL, IK_BY_VK, MODIFIER_KEYS, PAD_BY_BIT, PAD_BY_LONG,
                   PAD_LONG_LABELS, Combo, is_pad_button, label, mod_name, pad_label, to_ik)
from .model import solo_buttons  # noqa: E402
from .model import (ActionInfo, all_snippets, build_catalog, compile_settings, merged_doc, only_narrowed,
                    pad_users, target_contexts, who_uses)
from .names import category_order, friendly_mod
from .profile import Profile
from .scanner import ScanResult, scan
from . import theme
from .theme import P

BACKUP_DIRNAME = "W3KeyBinder backups"
KEEP_BACKUPS = 20

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")

_KEYSYM = {
    "space": "IK_Space", "Return": "IK_Enter", "KP_Enter": "IK_Enter", "Escape": "IK_Escape", "Tab": "IK_Tab",
    "ISO_Left_Tab": "IK_Tab", "BackSpace": "IK_Backspace", "Insert": "IK_Insert", "Delete": "IK_Delete",
    "Home": "IK_Home", "End": "IK_End", "Prior": "IK_PageUp", "Next": "IK_PageDown", "Left": "IK_Left",
    "Up": "IK_Up", "Right": "IK_Right", "Down": "IK_Down", "Caps_Lock": "IK_CapsLock", "Num_Lock": "IK_NumLock",
    "Scroll_Lock": "IK_ScrollLock", "Pause": "IK_Pause", "Print": "IK_PrintScrn",
    "grave": "IK_Tilde", "asciitilde": "IK_Tilde", "minus": "IK_Minus", "underscore": "IK_Minus",
    "equal": "IK_Equals", "plus": "IK_Equals", "bracketleft": "IK_LeftBracket", "braceleft": "IK_LeftBracket",
    "bracketright": "IK_RightBracket", "braceright": "IK_RightBracket", "backslash": "IK_Backslash",
    "bar": "IK_Backslash", "semicolon": "IK_Semicolon", "colon": "IK_Semicolon", "apostrophe": "IK_SingleQuote",
    "quotedbl": "IK_SingleQuote", "comma": "IK_Comma", "less": "IK_Comma", "period": "IK_Period",
    "greater": "IK_Period", "slash": "IK_Slash", "question": "IK_Slash",
    "exclam": "IK_1", "at": "IK_2", "numbersign": "IK_3", "dollar": "IK_4", "percent": "IK_5",
    "asciicircum": "IK_6", "ampersand": "IK_7", "asterisk": "IK_8", "parenleft": "IK_9", "parenright": "IK_0",
    "KP_Add": "IK_NumPlus", "KP_Subtract": "IK_NumMinus", "KP_Multiply": "IK_NumStar",
    "KP_Divide": "IK_NumSlash", "KP_Decimal": "IK_NumPeriod", "KP_Delete": "IK_NumPeriod",
    "KP_Insert": "IK_NumPad0", "KP_End": "IK_NumPad1", "KP_Down": "IK_NumPad2", "KP_Next": "IK_NumPad3",
    "KP_Left": "IK_NumPad4", "KP_Begin": "IK_NumPad5", "KP_Right": "IK_NumPad6", "KP_Home": "IK_NumPad7",
    "KP_Up": "IK_NumPad8", "KP_Prior": "IK_NumPad9",
    "Shift_L": "IK_LShift", "Shift_R": "IK_RShift", "Control_L": "IK_LControl", "Control_R": "IK_RControl",
    "Alt_L": "IK_Alt", "Alt_R": "IK_Alt", "Meta_L": "IK_Alt", "Meta_R": "IK_Alt",
}
_MOD_OF = {"IK_LShift": "Shift", "IK_RShift": "Shift", "IK_Shift": "Shift", "IK_LControl": "Ctrl",
           "IK_RControl": "Ctrl", "IK_Ctrl": "Ctrl", "IK_Alt": "Alt"}


def event_to_ik(event) -> Optional[str]:
    if sys.platform == "win32":  # virtual-key code: independent of keyboard layout and modifiers
        if event.keycode in (16, 17):  # the game uses left/right Shift and Ctrl (IK_LShift ...)
            return _KEYSYM.get(event.keysym, "IK_LShift" if event.keycode == 16 else "IK_LControl")
        return IK_BY_VK.get(event.keycode)
    ks = event.keysym
    if len(ks) == 1 and ks.isalnum():
        return f"IK_{ks.upper()}"
    if ks.startswith("KP_") and ks[3:].isdigit():
        return f"IK_NumPad{ks[3:]}"
    if ks.startswith("F") and ks[1:].isdigit():
        return f"IK_{ks}"
    return _KEYSYM.get(ks)


_CTX_NAMES = {"exploration": "on foot", "combat": "in combat", "horse": "on horseback", "swimming": "swimming",
              "boat": "sailing", "diving": "underwater", "scene": "in cutscenes"}


def friendly_context(ctx: str) -> str:
    low = ctx.lower()
    ciri = "replacer_ciri" in low
    base = low.replace("_replacer_ciri", "")
    name = _CTX_NAMES.get(base, ctx.replace("_", " "))
    return name + (" (as Ciri)" if ciri else "")


def _center(win, master):
    win.update_idletasks()
    x = master.winfo_rootx() + max(0, (master.winfo_width() - win.winfo_width()) // 2)
    y = master.winfo_rooty() + max(0, (master.winfo_height() - win.winfo_height()) // 3)
    win.geometry(f"+{x}+{y}")


# =============================================================================================
class PressTypeRow(tk.Frame):
    """Normal press / hold for N seconds / double-tap within N ms."""

    def __init__(self, master, on_change):
        super().__init__(master)
        self.kind = tk.StringVar(value="press")
        self.hold_s = tk.StringVar(value="1.0")
        self.dbl_ms = tk.StringVar(value="300")
        tk.Label(self, text="Press type:", font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(side="left")
        ttk.Radiobutton(self, text="Normal", value="press", variable=self.kind, takefocus=False,
                        command=on_change).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(self, text="Hold for", value="hold", variable=self.kind, takefocus=False,
                        command=on_change).pack(side="left", padx=(8, 0))
        e1 = ttk.Spinbox(self, textvariable=self.hold_s, from_=0.2, to=10, increment=0.1, width=4,
                         takefocus=False, command=on_change)
        e1.pack(side="left")
        tk.Label(self, text="s", fg=P["muted"]).pack(side="left")
        ttk.Radiobutton(self, text="Double-tap within", value="double", variable=self.kind, takefocus=False,
                        command=on_change).pack(side="left", padx=(8, 0))
        e2 = ttk.Spinbox(self, textvariable=self.dbl_ms, from_=100, to=1000, increment=25, width=5,
                         takefocus=False, command=on_change)
        e2.pack(side="left")
        tk.Label(self, text="ms", fg=P["muted"]).pack(side="left")
        for e in (e1, e2):  # typing a number must not be captured as a key to bind
            e.bind("<KeyPress>", lambda ev: "break" if not (ev.char.isdigit() or ev.char == "." or ev.keysym in
                                                           ("BackSpace", "Delete", "Left", "Right")) else None)
            e.bind("<KeyRelease>", lambda ev: (on_change(), "break")[1])

    def get(self) -> tuple:
        """(kind, ms); raises ValueError with a message if the number is unusable."""
        k = self.kind.get()
        if k == "press":
            return "press", 0
        try:
            ms = int(round(float(self.hold_s.get()) * 1000)) if k == "hold" else int(float(self.dbl_ms.get()))
        except ValueError:
            raise ValueError("Enter a number for the time.")
        if not 50 <= ms <= 10000:
            raise ValueError("The time must be between 0.05 and 10 seconds.")
        return k, ms


class KeyCaptureDialog(tk.Toplevel):
    """'Press the key you want' dialog.

    Press a key on its own, or hold one or more keys / mouse buttons and then press another to make a
    combo (Ctrl+Q, Alt+1, Mouse 4+2, Caps Lock+Mouse 5). For combos, a tick box decides whether the
    held key is hidden from the game while the combo is pressed.
    """

    def __init__(self, app: "App", info: ActionInfo, add: bool):
        super().__init__(app)
        self.app, self.info = app, info
        self.title(("Add a key - " if add else "Change key - ") + info.name)
        self.transient(app)
        self.resizable(False, False)
        self.configure(padx=18, pady=14)
        self.result: Optional[str] = None
        self.hide = app.profile.block_modifiers
        self._down: list[str] = []      # keys / buttons held right now, in the order pressed
        self._made = False              # a combo was completed while keys were held
        self._combo: Optional[Combo] = None

        tk.Label(self, text=info.name, font=(theme.FONT_FAMILY, 14, "bold")).pack(anchor="w")
        cur = ", ".join(app.keys_of(info)) or "nothing"
        tk.Label(self, text=f"Currently: {cur}", fg=P["muted"]).pack(anchor="w")
        tk.Label(self, text="Press a key. For a combo, hold a key or mouse button, then press another.",
                 ).pack(anchor="w", pady=(12, 0))
        tk.Label(self, text="Examples:  R     Ctrl+Q     Alt+1     Mouse 4 + 2     or choose Hold / Double-tap below",
                 font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(anchor="w")

        self.shown = tk.StringVar(value="...")
        tk.Label(self, textvariable=self.shown, font=(theme.FONT_FAMILY, 26, "bold"), fg=P["accent"],
                 width=18).pack(pady=(10, 2))
        self.warn = tk.StringVar()
        tk.Label(self, textvariable=self.warn, fg=P["warn"], wraplength=480, justify="center").pack()

        self.v_hide = tk.BooleanVar(value=self.hide)
        self.hide_row = tk.Frame(self)
        self.hide_box = tk.Checkbutton(self.hide_row, variable=self.v_hide, anchor="w", justify="left",
                                       selectcolor=P["card"], activebackground=P["bg"], wraplength=470,
                                       command=lambda: setattr(self, "hide", bool(self.v_hide.get())))
        self.hide_box.pack(anchor="w")
        self.hide_note = tk.Label(self.hide_row, text="", font=(theme.FONT_FAMILY, 9), fg=P["muted"],
                                  wraplength=470, justify="left")
        self.hide_note.pack(anchor="w", padx=(24, 0))

        self.box = tk.Label(self, text="Mouse buttons: click, hold or scroll inside this box", relief="groove",
                            bg=P["box"], fg=P["box_fg"], height=3, cursor="hand2")
        self.box.pack(fill="x", pady=10)

        man = tk.Frame(self)
        man.pack(fill="x")
        tk.Label(man, text="Or choose:", font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(side="left")
        self.m_vars = {m: tk.BooleanVar() for m in ("Ctrl", "Shift", "Alt")}
        for m, v in self.m_vars.items():
            ttk.Checkbutton(man, text=m, variable=v, takefocus=False, command=self._use_manual).pack(side="left")
        tk.Label(man, text=" hold", font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(side="left")
        holdable = ["-"] + [l for l in ALL_LABELS if l not in ("Wheel Up", "Wheel Down", "Shift", "Ctrl", "Alt",
                                                                "Left Shift", "Right Shift", "Left Ctrl", "Right Ctrl")]
        self.m_hold = ttk.Combobox(man, values=holdable, width=11, state="readonly", takefocus=False)
        self.m_hold.set("-")
        self.m_hold.pack(side="left", padx=4)
        self.m_hold.bind("<<ComboboxSelected>>", lambda _e: self._use_manual())
        tk.Label(man, text="then", font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(side="left")
        self.m_key = ttk.Combobox(man, values=ALL_LABELS, width=11, state="readonly", takefocus=False)
        self.m_key.pack(side="left", padx=4)
        self.m_key.bind("<<ComboboxSelected>>", lambda _e: self._use_manual())

        self.ptype = PressTypeRow(self, self._retype)
        self.ptype.pack(fill="x", pady=(10, 0))
        self._base: Optional[Combo] = None

        btns = tk.Frame(self)
        btns.pack(fill="x", pady=(14, 0))
        self.ok = ttk.Button(btns, text="OK", command=self._ok, state="disabled", takefocus=False)
        self.ok.pack(side="right")
        ttk.Button(btns, text="Cancel", command=self.destroy, takefocus=False).pack(side="right", padx=6)

        self.bind("<KeyPress>", self._press)
        self.bind("<KeyRelease>", self._release)
        for b in (1, 2, 3, 4, 5):
            self.box.bind(f"<ButtonPress-{b}>", self._mouse_down)
            self.box.bind(f"<ButtonRelease-{b}>", self._mouse_up)
        self.box.bind("<MouseWheel>", self._wheel)
        _center(self, app)
        self.grab_set()
        self.focus_force()

    # ---- result ----
    def _retype(self):
        if self._base is not None:
            self._set(self._base)

    def _set(self, combo: Combo):
        self._base = Combo(combo.key, combo.mods)
        try:
            kind, ms = self.ptype.get()
            combo = Combo.parse(str(Combo(combo.key, combo.mods, kind, ms)))
        except ValueError as e:
            self._combo = None
            self.shown.set(self._base.base_text())
            self.warn.set(str(e))
            self.ok.configure(state="disabled")
            self.hide_row.pack_forget()
            return
        self._combo = combo
        self.shown.set(str(combo))
        self.ok.configure(state="normal")
        if combo.hideable:
            self.v_hide.set(self.app.profile.combo_hide.get(str(combo), self.app.profile.block_modifiers))
            self.hide = bool(self.v_hide.get())
            if combo.kind == "press":
                self.hide_box.configure(text=f"Hide {combo.mods_text()} from the game while pressing {combo}")
                self.hide_note.configure(text="So the held key's own action (e.g. Alt = dodge) doesn't also "
                                              "happen. Pressed on its own it still works: the game gets it "
                                              "when you let go.")
            else:
                k = label(combo.key)
                self.hide_box.configure(text=f"Keep the normal {k} press from the game when this triggers")
                self.hide_note.configure(text=f"A plain tap of {k} still works, but a little later: the app has "
                                              "to wait to see whether you're holding or double-tapping.")
            self.hide_row.pack(fill="x", pady=(8, 0), before=self.box)
        else:
            self.hide_row.pack_forget()
        others = who_uses(self.app.catalog, self.app.profile, str(combo), self.info, self.app.pending,
                          self.app.pending_ctx)
        msgs = []
        if others:
            names = ", ".join(o.name for o in others[:4]) + (" ..." if len(others) > 4 else "")
            msgs.append(f"Already used by: {names}. Both would happen when you press it.")
        if self.info.shared_mods:
            msgs.append("This key is also used by " + ", ".join(friendly_mod(m) for m in self.info.shared_mods)
                        + ", so it changes there too.")
        if combo.is_chord and not IS_WINDOWS:
            msgs.append("Combos, hold and double-tap need the Windows combo helper.")
        self.warn.set("\n".join(msgs))

    # ---- capture: hold any keys/buttons, then press one more ----
    def _begin(self, ik: str):
        if ik in self._down:
            return                                     # key repeat
        if self._down and ik not in MODIFIER_KEYS:
            held = frozenset(mod_name(x) for x in self._down)
            self._down.append(ik)
            self._made = True
            self._set(Combo(ik, held))
            return
        if not self._down:
            self._made = False
        self._down.append(ik)
        if not self._made:
            self.shown.set(" + ".join(label(x) for x in self._down) + " + ...")

    def _end(self, ik: str):
        if ik not in self._down:
            return
        self._down.remove(ik)
        if not self._down and not self._made:
            self._set(Combo(ik))                       # pressed and let go on its own
        elif not self._down and self._combo:
            self.shown.set(str(self._combo))

    def _press(self, ev):
        if isinstance(ev.widget, ttk.Spinbox):
            return None                                # typing a time, not choosing a key
        ik = event_to_ik(ev)
        if ik is None:
            self.shown.set("?")
            self.warn.set("That key isn't supported. Choose it from the list instead.")
            return "break"
        self._begin(ik)
        return "break"

    def _release(self, ev):
        if isinstance(ev.widget, ttk.Spinbox):
            return None
        ik = event_to_ik(ev)
        if ik:
            self._end(ik)
        return "break"

    @staticmethod
    def _button_ik(num: int) -> Optional[str]:
        if sys.platform == "win32":
            m = {1: "IK_LeftMouse", 2: "IK_MiddleMouse", 3: "IK_RightMouse", 4: "IK_Mouse4", 5: "IK_Mouse5"}
        elif sys.platform == "darwin":
            m = {1: "IK_LeftMouse", 2: "IK_RightMouse", 3: "IK_MiddleMouse"}
        else:
            m = {1: "IK_LeftMouse", 2: "IK_MiddleMouse", 3: "IK_RightMouse",
                 4: "IK_MouseWheelUp", 5: "IK_MouseWheelDown"}
        return m.get(num)

    def _mouse_down(self, ev):
        ik = self._button_ik(ev.num)
        if ik in ("IK_MouseWheelUp", "IK_MouseWheelDown"):
            self._wheel_to(ik)
        elif ik:
            self._begin(ik)
        return "break"

    def _mouse_up(self, ev):
        ik = self._button_ik(ev.num)
        if ik and ik not in ("IK_MouseWheelUp", "IK_MouseWheelDown"):
            self._end(ik)
        return "break"

    def _wheel(self, ev):
        self._wheel_to("IK_MouseWheelUp" if ev.delta > 0 else "IK_MouseWheelDown")
        return "break"

    def _wheel_to(self, ik: str):
        if self._down:
            self._made = True
            self._set(Combo(ik, frozenset(mod_name(x) for x in self._down)))
        else:
            self._set(Combo(ik))

    def _use_manual(self):
        self.focus_set()
        if not self.m_key.get():
            return
        ik = to_ik(self.m_key.get())
        mods = {m for m, v in self.m_vars.items() if v.get()}
        hold = self.m_hold.get()
        if hold and hold != "-":
            mods.add(mod_name(to_ik(hold)))
        try:
            combo = Combo.parse(str(Combo(ik, frozenset(mods))))
        except ValueError as e:
            self.warn.set(str(e))
            return
        self._set(combo)

    def _ok(self):
        if self._combo:
            self.result = str(self._combo)
            self.hide = bool(self.v_hide.get())
        self.destroy()


class PadCaptureDialog(tk.Toplevel):
    """Controller: one button, or up to three together, with normal / hold / double-tap.

    result is ("button", "IK_Pad_...") for a plain single button (written straight into input.settings)
    or ("combo", "Pad LB+Pad RB+Pad A") for everything the combo helper handles.
    """

    def __init__(self, app: "App", info: ActionInfo, combo_only: bool = False):
        super().__init__(app)
        self.app, self.info, self.combo_only = app, info, combo_only
        self.title("Controller - " + info.name)
        self.transient(app)
        self.resizable(False, False)
        self.configure(padx=18, pady=14)
        self.result: Optional[tuple] = None
        self.buttons: list = []
        self.xi = XInput()
        tk.Label(self, text=info.name, font=(theme.FONT_FAMILY, 14, "bold")).pack(anchor="w")
        cur = " / ".join(pad_label(b, long=True) for b in app.pad_of(info)) or "nothing"
        tk.Label(self, text=f"Controller button now: {cur}", fg=P["muted"]).pack(anchor="w")
        if self.xi.ok and self.xi.connected():
            hint = "Press a button, or press up to three buttons together, then let go."
        elif self.xi.ok:
            hint = ("No controller found. Connect one and press the button(s), or pick from the lists. "
                    "PlayStation pads are read through Steam Input or DS4Windows.")
        else:
            hint = "Pick the button(s) from the lists."
        self.hint = tk.Label(self, text=hint, wraplength=480, justify="left")
        self.hint.pack(anchor="w", pady=(12, 0))
        self.shown = tk.StringVar(value="...")
        tk.Label(self, textvariable=self.shown, font=(theme.FONT_FAMILY, 22, "bold"), fg=P["accent"],
                 width=24).pack(pady=(10, 2))
        self.warn = tk.StringVar()
        tk.Label(self, textvariable=self.warn, fg=P["warn"], wraplength=480, justify="center").pack()
        row = tk.Frame(self)
        row.pack(fill="x", pady=(10, 0))
        tk.Label(row, text="Or choose:", font=(theme.FONT_FAMILY, 9), fg=P["muted"]).pack(side="left")
        self.picks = []
        for i in range(3):
            if i:
                tk.Label(row, text="+", fg=P["muted"]).pack(side="left")
            cb = ttk.Combobox(row, values=["-"] + PAD_LONG_LABELS, width=15, state="readonly", takefocus=False)
            cb.set("-")
            cb.pack(side="left", padx=3)
            cb.bind("<<ComboboxSelected>>", lambda _e: self._from_lists())
            self.picks.append(cb)
        self.ptype = PressTypeRow(self, self._refresh)
        self.ptype.pack(fill="x", pady=(12, 0))
        self.v_hide = tk.BooleanVar(value=app.profile.block_modifiers)
        self.hide = bool(self.v_hide.get())
        self.hide_box = tk.Checkbutton(self, variable=self.v_hide, anchor="w", justify="left", wraplength=470,
                                       selectcolor=P["card"], activebackground=P["bg"],
                                       command=self._refresh)
        self.note = tk.Label(self, text="", font=(theme.FONT_FAMILY, 9), fg=P["muted"], wraplength=480,
                             justify="left")
        self.note.pack(anchor="w", pady=(8, 0))
        btns = tk.Frame(self)
        btns.pack(fill="x", pady=(14, 0))
        self.ok = ttk.Button(btns, text="OK", command=self.destroy, state="disabled")
        self.ok.pack(side="right")
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._ignore = self.xi.pressed()   # whatever was already held when the window opened
        self._peak: list = []
        _center(self, app)
        self.grab_set()
        self.after(40, self._poll)

    def _poll(self):
        try:
            now = self.xi.pressed()
            self._ignore &= now
            now = [b for b in sorted(now) if b not in self._ignore]
            if now:
                for b in now:
                    if b not in self._peak and len(self._peak) < 3:
                        self._peak.append(b)
                self.shown.set(" + ".join(pad_label(b) for b in self._peak) + " ...")
            elif self._peak:                      # all let go: that's the choice
                self.set_buttons(self._peak)
                self._peak = []
            self.after(25, self._poll)
        except tk.TclError:
            pass

    def _from_lists(self):
        btns = []
        for cb in self.picks:
            v = cb.get()
            if v and v != "-" and PAD_BY_LONG[v.lower()] not in btns:
                btns.append(PAD_BY_LONG[v.lower()])
        if btns:
            self.set_buttons(btns)

    def set_buttons(self, buttons: list):
        self.buttons = list(buttons)
        self._refresh()

    def _refresh(self):
        if not self.buttons:
            return
        self.result = None
        self.ok.configure(state="disabled")
        text = " + ".join(pad_label(b) for b in self.buttons)
        try:
            kind, ms = self.ptype.get()
            if len(self.buttons) == 1 and kind == "press":
                if self.combo_only:
                    raise ValueError("Press two or three buttons together, or choose Hold or Double-tap.")
                result = ("button", self.buttons[0])
                self.shown.set(pad_label(self.buttons[0], long=True))
            else:
                combo = Combo.parse(str(Combo(self.buttons[-1], frozenset(self.buttons[:-1]), kind, ms)))
                result = ("combo", str(combo))
                self.shown.set(str(combo).replace("Pad ", ""))
        except ValueError as e:
            self.shown.set(text)
            self.warn.set(str(e))
            self.note.configure(text="")
            return
        self.result = result
        self.ok.configure(state="normal")
        if result[0] == "button":
            others = pad_users(self.app.catalog, result[1], self.info, self.app.pending_pad, self.app.profile)
            names = ", ".join(o.name for o in others[:4]) + (" ..." if len(others) > 4 else "")
            self.warn.set(f"Already used by: {names}. Both would happen when you press it." if others else "")
            self.note.configure(text="")
        else:
            others = who_uses(self.app.catalog, self.app.profile, result[1], self.info, self.app.pending,
                              self.app.pending_ctx)
            self.warn.set("Already used by: " + ", ".join(o.name for o in others[:4]) if others else "")
            names = Combo.parse(result[1]).buttons_text()
            self.hide = bool(self.v_hide.get())
            self.hide_box.configure(text=f"Hide {names}'s own actions when used for this")
            self.hide_box.pack(anchor="w", pady=(8, 0), before=self.note)
            if self.hide:
                self.note.configure(text=f"The game won't react to {names} directly any more: W3 KeyBinder sends "
                                         "their normal actions itself when you press one on its own (a tap acts "
                                         "when you let go, a hold after a quarter of a second). So keep W3 "
                                         "KeyBinder open while you play, or those buttons do nothing.")
            else:
                self.note.configure(text="The game still gets each button's own action as well as the combo. "
                                         "Keep W3 KeyBinder open while you play for the combo to work.")
            return
        self.hide_box.pack_forget()

    def _cancel(self):
        self.result = None
        self.destroy()


class TestCombosDialog(tk.Toplevel):
    """A window the combo helper treats as the game, showing exactly which keys the game would get."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Test my combos")
        self.transient(app)
        self.configure(padx=16, pady=12)
        self.geometry("540x460")
        tk.Label(self, text="Test my combos", font=(theme.FONT_FAMILY, 14, "bold")).pack(anchor="w")
        combos = app._combos_in_file()
        if not IS_WINDOWS:
            info = "The combo helper only runs on Windows."
        elif not app.helper.running:
            info = f"The combo helper isn't running: {app.helper.error or 'no saved combos yet.'}"
        else:
            names = ", ".join(sorted(combos)) or "none saved yet"
            info = (f"Click in the box and press your combos: this window acts like the game. Saved combos: "
                    f"{names}.\nBelow is exactly what the game would receive.")
        tk.Label(self, text=info, wraplength=500, justify="left", fg=P["muted"]).pack(anchor="w", pady=(4, 8))
        self.text = tk.Text(self, height=16, font=("Consolas", 10))
        self.text.pack(fill="both", expand=True)
        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e", pady=(8, 0))
        rev = {v: k for k, v in app.profile.proxies.items()}
        self.names = {label(ik): f"{label(ik)}  = your combo {c}" for ik, c in rev.items()}
        self.text.bind("<KeyPress>", lambda e: self._log(e))
        self.text.bind("<ButtonPress>", lambda e: self._log_mouse(e))
        self.text.focus_set()
        self.update_idletasks()
        self._hwnd = None
        try:
            self._hwnd = int(self.wm_frame(), 16)
            app.helper.test_hwnds.add(self._hwnd)
        except (ValueError, tk.TclError):
            pass
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        _center(self, app)

    def _log(self, ev):
        ik = event_to_ik(ev)
        name = label(ik) if ik else ev.keysym
        self.text.insert("end", "game gets: " + self.names.get(name, name) + "\n")
        self.text.see("end")
        return "break"

    def _log_mouse(self, ev):
        self.text.insert("end", f"game gets: mouse button {ev.num}\n")
        self.text.see("end")

    def destroy(self):
        if self._hwnd is not None:
            self.app.helper.test_hwnds.discard(self._hwnd)
            self.app.helper._fg_cache = (0, False)
        super().destroy()


class ContextDialog(tk.Toplevel):
    def __init__(self, app: "App", info: ActionInfo, all_contexts: list[str], selected: list[str]):
        super().__init__(app)
        self.title("Where this key works")
        self.transient(app)
        self.configure(padx=14, pady=12)
        self.result: Optional[list[str]] = None
        self.reset = False
        tk.Label(self, text=info.name, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(self, text="The key only works in the game situations selected below.\n"
                            "Mods usually say which ones in their description (e.g. [Exploration]).\n"
                            "Ctrl-click to select several.", font=FONT, justify="left").pack(anchor="w", pady=(4, 6))
        lf = tk.Frame(self)
        lf.pack(fill="both", expand=True)
        self.lb = tk.Listbox(lf, selectmode="extended", height=16, width=48, exportselection=False, font=FONT)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.names = sorted(set(all_contexts) | set(selected), key=str.lower)
        for i, n in enumerate(self.names):
            self.lb.insert("end", f"[{n}]   {friendly_context(n)}")
            if n in selected:
                self.lb.selection_set(i)
                self.lb.see(i)
        b = tk.Frame(self)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Reset", command=self._reset).pack(side="left")
        ttk.Button(b, text="OK", command=self._ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        _center(self, app)
        self.grab_set()

    def _ok(self):
        self.result = [self.names[i] for i in self.lb.curselection()]
        if not self.result:
            messagebox.showwarning("Nothing selected", "Select at least one.", parent=self)
            return
        self.destroy()

    def _reset(self):
        self.reset = True
        self.destroy()


class ModFilesDialog(tk.Toplevel):
    """List of mod keybind files found, with on/off, plus 'add lines manually'."""

    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Mod keybind files")
        self.transient(app)
        self.configure(padx=14, pady=12)
        self.geometry("860x560")
        tk.Label(self, text="Keybind lines found in your mods", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(self, text="These are the input.settings lines mods ask you to add. Missing ones are added "
                            "for you when you save.\nDouble-click to switch one off/on.", font=FONT,
                 justify="left").pack(anchor="w", pady=(2, 6))
        self.tree = ttk.Treeview(self, columns=("on", "mod", "n", "file"), show="headings", height=9)
        for c, t, w in (("on", "Used", 60), ("mod", "Mod", 200), ("n", "Lines", 60), ("file", "File", 500)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=c == "file")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self._toggle())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show())
        self.text = tk.Text(self, height=9, font=("Consolas", 10), state="disabled")
        self.text.pack(fill="x", pady=6)
        b = tk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="Switch off / on", command=self._toggle).pack(side="left")
        ttk.Button(b, text="Add a mod's lines manually...", command=self._add).pack(side="left", padx=6)
        ttk.Button(b, text="Delete manual entry", command=self._delete).pack(side="left")
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        self.refresh()
        _center(self, app)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for s in all_snippets(self.app.scan_result, self.app.profile):
            on = "No" if s.id in self.app.profile.disabled_snippets else "Yes"
            self.tree.insert("", "end", iid=s.id, values=(on, friendly_mod(s.mod), len(s.entries),
                                                          "(added by you)" if s.manual else s.path))

    def _snip(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return next((s for s in all_snippets(self.app.scan_result, self.app.profile) if s.id == sel[0]), None)

    def _show(self):
        s = self._snip()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if s:
            last = None
            for ctx, e in s.entries:
                if ctx != last:
                    self.text.insert("end", f"[{ctx}]\n")
                    last = ctx
                self.text.insert("end", e.line() + "\n")
        self.text.configure(state="disabled")

    def _toggle(self):
        for sid in self.tree.selection():
            d = self.app.profile.disabled_snippets
            d.remove(sid) if sid in d else d.append(sid)
        self.app.after_profile_change()
        self.refresh()

    def _add(self):
        self.app.add_manual_lines()
        self.refresh()

    def _delete(self):
        sel = self.tree.selection()
        if not sel or not sel[0].startswith("manual:"):
            messagebox.showinfo("Delete", "Select one of the entries you added yourself.", parent=self)
            return
        del self.app.profile.manual_snippets[int(sel[0].split(":")[1])]
        self.app.profile.disabled_snippets = [x for x in self.app.profile.disabled_snippets
                                              if not x.startswith("manual:")]
        self.app.after_profile_change()
        self.refresh()


class ManualLinesDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Add a mod's keybind lines")
        self.transient(master)
        self.configure(padx=14, pady=12)
        self.result = None
        tk.Label(self, text="Mod name:", font=FONT).pack(anchor="w")
        self.name = ttk.Entry(self, width=40)
        self.name.pack(anchor="w", fill="x")
        tk.Label(self, text="Paste the lines from the mod's page or readme (the part with [Exploration] etc.):",
                 font=FONT).pack(anchor="w", pady=(10, 2))
        self.text = tk.Text(self, width=72, height=14, font=("Consolas", 10))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "[Exploration]\nIK_K=(Action=SomeModAction)\n")
        b = tk.Frame(self)
        b.pack(fill="x", pady=(8, 0))
        ttk.Button(b, text="Add", command=self._ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        _center(self, master)
        self.grab_set()

    def _ok(self):
        txt = self.text.get("1.0", "end")
        if not sf.parse_text(txt).entry_count():
            messagebox.showerror("Nothing found", "Couldn't find lines like  IK_K=(Action=Name)  under a "
                                 "[Section] header.", parent=self)
            return
        self.result = {"name": self.name.get().strip() or "My mod", "text": txt}
        self.destroy()


class BackupsDialog(tk.Toplevel):
    def __init__(self, app: "App", backups: list[Path]):
        super().__init__(app)
        self.title("Restore a backup")
        self.transient(app)
        self.configure(padx=14, pady=12)
        self.result: Optional[Path] = None
        tk.Label(self, text="Every save keeps a copy of the previous file. Pick one to put back:",
                 font=FONT).pack(anchor="w")
        self.lb = tk.Listbox(self, height=12, width=50, font=FONT)
        self.lb.pack(fill="both", expand=True, pady=6)
        self.items = backups
        for p in backups:
            ts = datetime.fromtimestamp(p.stat().st_mtime)
            self.lb.insert("end", ts.strftime("%A %d %B %Y, %H:%M:%S"))
        if backups:
            self.lb.selection_set(0)
        b = tk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="Restore", command=self._ok).pack(side="right")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        _center(self, app)
        self.grab_set()

    def _ok(self):
        sel = self.lb.curselection()
        if sel:
            self.result = self.items[sel[0]]
        self.destroy()


# =============================================================================================
class App(tk.Tk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()
        self.title("W3 KeyBinder")
        self._set_icon()
        self.geometry("1180x760")
        self.minsize(940, 600)
        self.data_dir = paths.app_data_dir()
        self.profile_path = self.data_dir / "profile.json"
        try:
            self.profile = Profile.load(self.profile_path)
        except Exception:
            shutil.copy2(self.profile_path, self.profile_path.with_suffix(".broken.json"))
            self.profile = Profile()
        if not self.profile.settings_path or not Path(self.profile.settings_path).exists():
            d = paths.default_settings_path()
            if d.exists() or not self.profile.settings_path:
                self.profile.settings_path = str(d)
        if not self.profile.game_dir or not Path(self.profile.game_dir).is_dir():
            g = paths.guess_game_dir()
            self.profile.game_dir = str(g) if g else self.profile.game_dir

        self.current: Optional[sf.SettingsDoc] = None
        self.settings_error = ""
        self.scan_result = ScanResult()
        self.catalog: dict[str, ActionInfo] = {}
        self.pending: dict[str, list[str]] = {}
        self.pending_ctx: dict[str, list[str]] = {}
        self.pending_pad: dict[str, list[str]] = {}   # controller button changes
        self.resave = False                           # a controller "hide" option changed
        self.conflicts: dict[str, list[str]] = {}
        self.helper = ComboHelper(self.profile.game_exe, self.profile.block_modifiers)
        self.helper.log_path = str(self.data_dir / "combo_helper.log")
        self._helper_state = ""

        self._style()
        self._build_menu()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(30, self.reload)
        if start_minimized:
            self.after(200, self.iconify)

    def _set_icon(self):
        """Window/taskbar icon: the W3 keycap."""
        assets = Path(__file__).with_name("assets")
        try:
            if sys.platform == "win32" and (assets / "icon.ico").exists():
                self.iconbitmap(default=str(assets / "icon.ico"))
            elif (assets / "icon.png").exists():
                self._icon_img = tk.PhotoImage(file=str(assets / "icon.png"))
                self.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ layout
    def _style(self):
        self.profile.theme = theme.apply(self, getattr(self.profile, "theme", "dark"))

    def toggle_theme(self):
        """Switch light/dark and rebuild the window in place."""
        self.profile.theme = "light" if self.profile.theme == "dark" else "dark"
        self.save_profile()
        for w in list(self.children.values()):
            w.destroy()
        self._style()
        self._build_menu()
        self._build()
        self._update_status_card()
        self._update_pending_bar()
        self._update_helper()
        self.refresh_side()

    def _build_menu(self):
        mb = tk.Menu(self)
        f = tk.Menu(mb, tearoff=False)
        f.add_command(label="Reload keybinds and mods", command=self.reload)
        f.add_command(label="Choose game folder...", command=self.choose_game)
        f.add_command(label="Choose input.settings file...", command=self.choose_settings)
        f.add_separator()
        f.add_command(label="Restore a backup...", command=self.restore_backup)
        f.add_command(label="Open the keybind folder",
                      command=lambda: self._open(Path(self.profile.settings_path).parent))
        f.add_separator()
        f.add_command(label="Exit", command=self.on_close)
        mb.add_cascade(label="File", menu=f)
        m = tk.Menu(mb, tearoff=False)
        m.add_command(label="Mod keybind files found...", command=lambda: ModFilesDialog(self))
        m.add_command(label="Add a mod's keybind lines manually...", command=self.add_manual_lines)
        m.add_command(label="Also scan another folder (e.g. mod downloads)...", command=self.add_extra_folder)
        m.add_command(label="Stop scanning extra folders", command=self.clear_extra_folders)
        mb.add_cascade(label="Mods", menu=m)
        o = tk.Menu(mb, tearoff=False)
        self.v_show_all = tk.BooleanVar(value=self.profile.show_no_keyboard)
        o.add_checkbutton(label="Show advanced game actions (menu navigation, debug keys ...)",
                          variable=self.v_show_all, command=self._toggle_show_all)
        self.v_autostart = tk.BooleanVar(value=get_autostart())
        o.add_checkbutton(label="Start with Windows (minimised, so key combos always work)",
                          variable=self.v_autostart, command=self._toggle_autostart,
                          state="normal" if IS_WINDOWS else "disabled")
        self.v_block = tk.BooleanVar(value=self.profile.block_modifiers)
        o.add_checkbutton(label="New combos: hide the held key from the game (can be set per combo)",
                          variable=self.v_block, command=self._toggle_block)
        o.add_command(label="Switch light / dark mode", command=self.toggle_theme)
        o.add_separator()
        o.add_command(label="Test my combos...", command=self.test_combos)
        o.add_command(label="Spare keys used for combos...", command=self.edit_proxy_pool)
        o.add_command(label="Export combos as an AutoHotkey script...", command=self.export_ahk)
        mb.add_cascade(label="Options", menu=o)
        h = tk.Menu(mb, tearoff=False)
        h.add_command(label="How to use", command=self.show_help)
        h.add_command(label="How key combos work", command=self.show_combo_help)
        h.add_command(label="Save a report (if a mod's keys are missing)...", command=self.save_report)
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"W3 KeyBinder {__version__}\nKeybinding manager for The Witcher 3 and its mods."))
        mb.add_cascade(label="Help", menu=h)
        self.config(menu=mb)

    def _build(self):
        # ---- header ----
        head = tk.Frame(self, bg=P["head"], padx=20, pady=14)
        head.pack(fill="x")
        title = tk.Frame(head, bg=P["head"])
        title.pack(side="left")
        tk.Label(title, text="W3", bg=P["head"], fg=P["gold"], font=(theme.FONT_FAMILY, 20, "bold")).pack(side="left")
        tk.Label(title, text=" KeyBinder", bg=P["head"], fg=P["head_fg"],
                 font=(theme.FONT_FAMILY, 20, "bold")).pack(side="left")
        tk.Label(head, text="Pick an action, press the key you want, then Save. Mod keys and combos like Ctrl+Q included.",
                 bg=P["head"], fg=P["head_sub"], font=(theme.FONT_FAMILY, 10)).pack(side="left", padx=(18, 0), pady=(6, 0))
        ttk.Button(head, text="\u2600  Light" if self.profile.theme == "dark" else "\u263e  Dark",
                   command=self.toggle_theme).pack(side="right")

        # ---- status strip ----
        strip = tk.Frame(self, bg=P["panel"], padx=20, pady=8)
        strip.pack(fill="x")
        self.status_rows = {}
        for col, (key, link, cmd) in enumerate((("settings", "Change", self.choose_settings),
                                                 ("game", "Change", self.choose_game),
                                                 ("mods", "Details", lambda: ModFilesDialog(self)))):
            cell = tk.Frame(strip, bg=P["panel"])
            cell.grid(row=0, column=col, sticky="w", padx=(0, 28))
            icon = tk.Label(cell, text="", bg=P["panel"], font=(theme.FONT_FAMILY, 11, "bold"))
            icon.pack(side="left")
            txt = tk.Label(cell, text="", bg=P["panel"], fg=P["fg"], font=(theme.FONT_FAMILY, 9), anchor="w")
            txt.pack(side="left", padx=(4, 0))
            b = tk.Label(cell, text=link, bg=P["panel"], fg=P["accent"], cursor="hand2",
                         font=(theme.FONT_FAMILY, 9, "underline"))
            b.pack(side="left", padx=(8, 0))
            b.bind("<Button-1>", lambda _e, c=cmd: c())
            self.status_rows[key] = (icon, txt)

        # ---- footer (packed before the body so it is never squeezed out) ----
        bottom = ttk.Frame(self, padding=(20, 10))
        bottom.pack(fill="x", side="bottom")
        self.save_btn = ttk.Button(bottom, text="Save keybinds", style="Big.Accent.TButton", command=self.save)
        self.save_btn.pack(side="right")
        self.discard_btn = ttk.Button(bottom, text="Discard changes", command=self.discard)
        self.discard_btn.pack(side="right", padx=10)
        self.v_pending = tk.StringVar()
        ttk.Label(bottom, textvariable=self.v_pending, font=(theme.FONT_FAMILY, 10, "bold")).pack(side="left")
        self.v_helper = tk.StringVar()
        self.helper_lbl = tk.Label(bottom, textvariable=self.v_helper, fg=P["muted"], cursor="hand2")
        self.helper_lbl.pack(side="left", padx=20)
        self.helper_lbl.bind("<Button-1>", lambda _e: self._helper_clicked())
        ttk.Separator(self).pack(fill="x", side="bottom")

        # ---- body: sidebar | list | detail ----
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=10)

        left = ttk.Frame(body)
        self.side = ttk.Treeview(left, show="tree", style="Side.Treeview", selectmode="browse")
        self.side.column("#0", width=220)
        self.side.pack(fill="both", expand=True)
        self.side.bind("<<TreeviewSelect>>", lambda _e: self.refresh_list())
        body.add(left, weight=0)

        mid = ttk.Frame(body, padding=(10, 0, 10, 0))
        body.add(mid, weight=1)
        top = ttk.Frame(mid)
        top.pack(fill="x", pady=(0, 8))
        self.v_title = tk.StringVar()
        tk.Label(top, textvariable=self.v_title, font=(theme.FONT_FAMILY, 14, "bold")).pack(side="left")
        self.v_count = tk.StringVar()
        ttk.Label(top, textvariable=self.v_count, style="Muted.TLabel").pack(side="left", padx=(10, 0), pady=(4, 0))
        self.v_search = tk.StringVar()
        self.v_search.trace_add("write", lambda *_: self.refresh_list())
        se = ttk.Entry(top, textvariable=self.v_search, width=26)
        se.pack(side="right")
        ttk.Label(top, text="Search", style="Muted.TLabel").pack(side="right", padx=(0, 8))

        lf = ttk.Frame(mid)
        lf.pack(fill="both", expand=True)
        self.list = ttk.Treeview(lf, columns=("name", "keys", "pad", "mod", "note"), show="headings",
                                 selectmode="extended")
        for c, t, w, s in (("name", "Action", 190, True), ("keys", "Key", 100, False),
                           ("pad", "Controller", 84, False), ("mod", "Mod", 96, False),
                           ("note", "Status", 100, True)):
            self.list.heading(c, text=t, anchor="w")
            self.list.column(c, width=w, minwidth=60, stretch=s, anchor="w")
        self.list.tag_configure("pending", foreground=P["row_pending"])
        self.list.tag_configure("conflict", background=P["row_conflict"])
        self.list.tag_configure("needs", background=P["row_needs"])
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.list.bind("<Double-1>", lambda _e: self.change_key(add=False))
        self.list.bind("<Return>", lambda _e: self.change_key(add=False))
        self.list.bind("<Delete>", lambda _e: self.remove_keys())
        self.list.bind("<<TreeviewSelect>>", lambda _e: self.show_detail())
        self.list.bind("<Button-3>", self._context_menu)

        # detail card
        self.detail = tk.Frame(body, bg=P["card"], padx=16, pady=14, width=330, highlightthickness=1,
                               highlightbackground=P["key_border"])
        body.add(self.detail, weight=0)
        self._build_detail()
        self.detail.bind("<Configure>", self._wrap_detail)
        self.body = body
        self.after(80, self._place_sashes)

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Change key...", command=lambda: self.change_key(False))
        self.menu.add_command(label="Add another key...", command=lambda: self.change_key(True))
        self.menu.add_command(label="Remove key", command=self.remove_keys)
        self.menu.add_command(label="Change controller button...", command=self.change_pad)
        self.menu.add_command(label="Add controller combo / hold / double-tap...",
                              command=lambda: self.change_pad(True))
        self.menu.add_command(label="Remove controller button", command=self.remove_pad)
        self.menu.add_command(label="Undo change", command=self.undo_selected)
        self.menu.add_separator()
        self.menu.add_command(label="Where it works (advanced)...", command=self.edit_contexts)

    def _place_sashes(self):
        try:
            w = self.body.winfo_width()
            if w > 700:
                self.body.sashpos(0, 230)
                self.body.sashpos(1, w - 340)
        except tk.TclError:
            pass

    def _wrap_detail(self, ev):
        width = max(160, ev.width - 36)
        for w in (self.d_name, self.d_info):
            w.configure(wraplength=width)
        for w in self.d_notes.winfo_children():
            # tick boxes need room for the box itself and the border around them
            w.configure(wraplength=width - 50 if isinstance(w, tk.Checkbutton) else width)

    def _build_detail(self):
        d = self.detail
        bgc = P["card"]
        self.d_kicker = tk.Label(d, text="", bg=bgc, fg=P["muted"], font=(theme.FONT_FAMILY, 9, "bold"), anchor="w")
        self.d_kicker.pack(fill="x")
        self.d_name = tk.Label(d, text="", bg=bgc, fg=P["fg"], font=(theme.FONT_FAMILY, 16, "bold"),
                               anchor="w", justify="left", wraplength=290)
        self.d_name.pack(fill="x", pady=(2, 12))
        self.d_keys = tk.Frame(d, bg=bgc)
        self.d_keys.pack(fill="x")
        self.d_notes = tk.Frame(d, bg=bgc)
        self.d_notes.pack(fill="x", pady=(10, 0))
        btns = tk.Frame(d, bg=bgc)
        btns.pack(fill="x", pady=(14, 0))
        self.d_change = ttk.Button(btns, text="Change key...", style="Wide.Accent.TButton",
                                   command=lambda: self.change_key(False))
        self.d_change.pack(fill="x")
        row = tk.Frame(btns, bg=bgc)
        row.pack(fill="x", pady=(8, 0))
        self.d_add = ttk.Button(row, text="Add key...", command=lambda: self.change_key(True))
        self.d_add.pack(side="left", fill="x", expand=True)
        self.d_remove = ttk.Button(row, text="Remove key", command=self.remove_keys)
        self.d_remove.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.d_undo = ttk.Button(btns, text="Undo change", command=self.undo_selected)
        self.d_undo.pack(fill="x", pady=(8, 0))
        pad = tk.Frame(d, bg=bgc)
        pad.pack(fill="x", pady=(16, 0))
        tk.Label(pad, text="CONTROLLER", bg=bgc, fg=P["muted"], font=(theme.FONT_FAMILY, 9, "bold"),
                 anchor="w").pack(fill="x")
        self.d_pad = tk.Frame(pad, bg=bgc)
        self.d_pad.pack(fill="x", pady=(4, 6))
        prow = tk.Frame(pad, bg=bgc)
        prow.pack(fill="x")
        self.d_pad_change = ttk.Button(prow, text="Change...", command=self.change_pad)
        self.d_pad_change.pack(side="left", fill="x", expand=True)
        self.d_pad_combo = ttk.Button(prow, text="Combo / hold...", command=lambda: self.change_pad(True))
        self.d_pad_combo.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.d_pad_remove = ttk.Button(prow, text="Remove", command=self.remove_pad)
        self.d_pad_remove.pack(side="left", padx=(6, 0))
        ttk.Separator(d).pack(fill="x", pady=14)
        self.d_info = tk.Label(d, text="", bg=bgc, fg=P["muted"], font=(theme.FONT_FAMILY, 9), anchor="nw",
                               justify="left", wraplength=290)
        self.d_info.pack(fill="x")
        self.d_where = tk.Label(d, text="Where it works...", bg=bgc, fg=P["accent"], cursor="hand2",
                                font=(theme.FONT_FAMILY, 9, "underline"), anchor="w")
        self.d_where.bind("<Button-1>", lambda _e: self.edit_contexts())

    def _keycaps(self, parent, combo: str, bgc: str):
        try:
            c = Combo.parse(combo)
            parts = [m for m in ("Ctrl", "Shift", "Alt") if m in c.mods] + [label(m) for m in c.custom_mods] \
                + [label(c.key)]
            kind, ms = c.kind, c.ms
        except ValueError:
            parts, kind, ms = [combo], "press", 0
        small = (theme.FONT_FAMILY, 9)
        if kind != "press":
            tk.Label(parent, text={"hold": "Hold", "double": "Double-tap"}[kind], bg=bgc, fg=P["muted"],
                     font=small).pack(side="left", padx=(0, 6))
        for i, p in enumerate(parts):
            if i:
                tk.Label(parent, text="+", bg=bgc, fg=P["muted"], font=(theme.FONT_FAMILY, 11)).pack(side="left", padx=3)
            tk.Label(parent, text=p, bg=P["key_bg"], fg=P["key_fg"],
                     font=(theme.FONT_FAMILY, 12 if len(parts) < 3 else 10, "bold"),
                     padx=12 if len(parts) < 3 else 7, pady=5, highlightthickness=1,
                     highlightbackground=P["key_border"], highlightcolor=P["key_border"]).pack(side="left")
        if kind == "hold":
            tk.Label(parent, text=f"{ms / 1000:g} s", bg=bgc, fg=P["muted"], font=small).pack(side="left", padx=(6, 0))
        elif kind == "double":
            tk.Label(parent, text=f"{ms} ms", bg=bgc, fg=P["muted"], font=small).pack(side="left", padx=(6, 0))

    # ------------------------------------------------------------------ data
    def keys_of(self, info: ActionInfo) -> list[str]:
        return list(self.pending.get(info.id, info.keys))

    def save_profile(self):
        try:
            self.profile.save(self.profile_path)
        except OSError:
            pass

    def reload(self):
        """Read the current input.settings and rescan mods."""
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            sp = Path(self.profile.settings_path)
            self.current, self.settings_error = None, ""
            if sp.exists():
                try:
                    self.current = sf.load(sp)
                    if self.current.entry_count() == 0:
                        self.settings_error = "has no keybinds in it"
                except Exception as e:
                    self.settings_error = f"couldn't be read ({e})"
            else:
                self.settings_error = "was not found"
            gd = Path(self.profile.game_dir) if self.profile.game_dir else None
            if gd and not gd.is_dir():
                gd = None
            self.scan_result = scan(gd, self.profile.extra_scan_dirs, sp.parent,
                                    self.data_dir / "vanilla_actions_cache.json")
            self.rebuild()
        finally:
            self.config(cursor="")
        self._update_status_card()
        self._update_helper()

    def rebuild(self):
        cur = self.current or sf.SettingsDoc()
        self.catalog = build_catalog(cur, self.scan_result, self.profile)
        self.pending = {k: v for k, v in self.pending.items() if k in self.catalog}
        self._compute_conflicts()
        self.refresh_side()
        self._update_pending_bar()

    def _compute_conflicts(self):
        self.conflicts = {}
        for aid in self._pend_ids():
            info = self.catalog.get(aid)
            if not info or only_narrowed(info, self.pending, self.pending_ctx):
                continue
            for k in self.keys_of(info):
                for o in who_uses(self.catalog, self.profile, k, info, self.pending, self.pending_ctx):
                    self.conflicts.setdefault(aid, []).append(f"{k} is also used by {o.name}")
                    self.conflicts.setdefault(o.id, []).append(f"{k} is also used by {info.name}")
        self._add_pad_conflicts()

    def _pend_ids(self) -> set:
        return set(self.pending) | set(self.pending_ctx) | set(self.pending_pad)

    def pad_of(self, info: ActionInfo) -> list:
        return list(self.pending_pad.get(info.id, info.pad))

    def _add_pad_conflicts(self):
        for aid, btns in self.pending_pad.items():
            info = self.catalog.get(aid)
            if not info:
                continue
            for b in btns:
                for o in pad_users(self.catalog, b, info, self.pending_pad, self.profile):
                    self.conflicts.setdefault(aid, []).append(f"{pad_label(b)} (controller) is also used by {o.name}")
                    self.conflicts.setdefault(o.id, []).append(f"{pad_label(b)} (controller) is also used by {info.name}")

    def change_pad(self, combo_only: bool = False):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Controller", "First click the action you want to change.")
            return
        if self.current is None:
            return
        d = PadCaptureDialog(self, sel[0], combo_only)
        self.wait_window(d)
        if not d.result:
            return
        kind, value = d.result
        if kind != "button":
            self.profile.combo_hide[value] = d.hide
            self.save_profile()
        for info in sel:
            if kind == "button":
                self._set_pad(info, [value])
            else:   # combo / hold / double-tap: works through the combo helper, like a key combo
                cur = self.keys_of(info)
                self._set_pending(info, [k for k in cur if k != value] + [value])
        self._changed()

    def remove_pad(self):
        for info in self._selected():
            self._set_pad(info, [])
        self._changed()

    def _set_pad(self, info: ActionInfo, buttons: list):
        if buttons == info.pad:
            self.pending_pad.pop(info.id, None)
        else:
            self.pending_pad[info.id] = buttons

    def after_profile_change(self):
        self.save_profile()
        self.rebuild()
        self._update_status_card()

    def _visible(self, info: ActionInfo) -> bool:
        return self.profile.show_no_keyboard or info.in_menu or info.id in self.pending

    def _needs_key(self, info: ActionInfo) -> bool:
        return (info.is_mod and not self.keys_of(info) and not self._via(info) and not info.optional
                and not info.borrow_of)  # an emptied "Sneak with Dive's key" was removed on purpose

    # ---- a mod action that works through a game key the mod borrowed (Unseen: Dive's C on land) ----
    def _dropped(self, rid: str) -> bool:
        """True if the game key a mod action works through is set to be removed (not saved yet)."""
        return rid in self.pending and not self.pending[rid]

    def _via(self, info: ActionInfo) -> list:
        return [v for v, rid in zip(info.via, info.via_rows) if not self._dropped(rid)]

    @staticmethod
    def _where(contexts) -> str:
        out = []
        for c in contexts:
            if c.upper().startswith("BASE_"):
                continue
            fc = friendly_context(c)
            if fc not in out:
                out.append(fc)
        return " and ".join([", ".join(out[:-1]), out[-1]] if len(out) > 1 else out)


    # ------------------------------------------------------------------ status card
    def _set_status(self, key, ok, text):
        icon, lbl = self.status_rows[key]
        icon.configure(text={True: "\u2714", False: "\u2716", None: "\u26a0"}[ok],
                       fg={True: P["ok"], False: P["bad"], None: P["warn"]}[ok])
        lbl.configure(text=text)

    @staticmethod
    def _short(path: str) -> str:
        p = Path(path)
        try:
            return "Documents\\" + str(p.relative_to(paths.documents_dir()))
        except ValueError:
            pass
        parts = p.parts
        return str(p) if len(parts) <= 3 else "...\\" + "\\".join(parts[-2:])

    def _update_status_card(self):
        sp = self.profile.settings_path
        if self.current is not None and not self.settings_error:
            self._set_status("settings", True, f"Your keybinds ({self.current.entry_count()} lines)")
        else:
            self._set_status("settings", False, f"Keybind file {self.settings_error or 'was not found'}: start "
                             "the game once, or pick it")
        gd = self.profile.game_dir
        if gd and Path(gd).is_dir():
            n = len(self.scan_result.mods)
            self._set_status("game", True, f"Game folder ({n} mod{'s' if n != 1 else ''})")
        else:
            self._set_status("game", None, "Game folder not found: pick it to scan your mods")
        mod_ids = {m for i in self.catalog.values() if i.in_menu for m in i.all_mods}
        need = sum(1 for i in self.catalog.values() if self._visible(i) and self._needs_key(i))
        if mod_ids:
            txt = f"{len(mod_ids)} mod{'s' if len(mod_ids) != 1 else ''} with keys"
            if need:
                txt += f" \u00b7 {need} need{'s' if need == 1 else ''} a key"
            self._set_status("mods", True if not need else None, txt)
        else:
            self._set_status("mods", None, "No mod keys found")

    def _update_pending_bar(self):
        n = len(self._pend_ids())
        if n:
            self.v_pending.set(f"{n} unsaved change{'s' if n != 1 else ''}")
            self.discard_btn.state(["!disabled"])
        else:
            adds = sum(1 for i in self.catalog.values() if i.from_snippet)
            self.v_pending.set(f"{adds} mod keybind{'s' if adds != 1 else ''} will be added when you save" if adds
                               else "Click Save to apply the controller hide option" if self.resave
                               else "No unsaved changes")
            self.discard_btn.state(["disabled"])

    def _combos_in_file(self) -> dict[str, str]:
        used = {k for i in self.catalog.values() for k in i.keys}
        solo = {label(b) for b in solo_buttons(self.profile.proxies)}   # hidden controller buttons
        return {c: p for c, p in self.profile.proxies.items() if c in used or c in solo}

    def _update_helper(self):
        combos = self._combos_in_file()
        if not combos:
            self.helper.stop()
            self.v_helper.set("")
            return
        if not IS_WINDOWS:
            self.v_helper.set("Key combos only work on Windows (combo helper).")
            self.helper_lbl.configure(fg=P["warn"])
            return
        self.helper.game_exe = self.profile.game_exe.lower()
        self.helper.block_modifiers = self.profile.block_modifiers
        self.helper.set_combos(combos, self.profile.combo_hide)
        if self.helper.start():
            self._helper_state = "on"
            self.v_helper.set(f"\u25cf Key combos on ({len(combos)}). Keep this app open while you play "
                              "(minimised is fine). Click to test.")
            self.helper_lbl.configure(fg=P["ok"])
        else:
            self._helper_state = "failed"
            self.v_helper.set("\u26a0 Key combos are off: the combo helper couldn't start. Click for details.")
            self.helper_lbl.configure(fg=P["bad"])
        if not getattr(self, "_watching", False):
            self._watching = True
            self.after(2000, self._watch_helper)

    # ------------------------------------------------------------------ sidebar + list
    def refresh_side(self):
        sel = self.side.selection()
        sel = sel[0] if sel else None
        self.side.delete(*self.side.get_children())
        vis = [i for i in self.catalog.values() if self._visible(i)]
        self.side.insert("", "end", iid="all", text=f"  All actions  ({len(vis)})")
        n_pend = len(self._pend_ids())
        if n_pend:
            self.side.insert("", "end", iid="pending", text=f"  ✎ Unsaved changes  ({n_pend})")
        need = [i for i in vis if self._needs_key(i)]
        if need:
            self.side.insert("", "end", iid="needs", text=f"  ⚠ Needs a key  ({len(need)})")
        if self.conflicts:
            self.side.insert("", "end", iid="conflicts", text=f"  ⚠ Clashing keys  ({len(self.conflicts)})")
        mods: dict[str, int] = {}
        for i in vis:
            for m in i.all_mods:
                mods[m] = mods.get(m, 0) + 1
        if mods:
            self.side.insert("", "end", iid="mods", text=f"  Mods  ({sum(1 for i in vis if i.all_mods)})", open=True)
            for m in sorted(mods, key=lambda x: friendly_mod(x).lower()):
                self.side.insert("mods", "end", iid="mod:" + m, text=f"{friendly_mod(m)}  ({mods[m]})")
        self.side.insert("", "end", iid="sep", text="  Game", open=True)
        for cat in category_order():
            n = sum(1 for i in vis if self._in_view(i, "cat:" + cat))
            if n:
                self.side.insert("sep", "end", iid="cat:" + cat, text=f"{cat}  ({n})")
        if sel and self.side.exists(sel):
            self.side.selection_set(sel)
        else:
            self.side.selection_set("needs" if need else ("mods" if mods else "all"))
        self.refresh_list()

    def _in_view(self, info: ActionInfo, view: str) -> bool:
        if view in ("all", "sep"):
            return True
        if view == "pending":
            return info.id in self._pend_ids()
        if view == "needs":
            return self._needs_key(info)
        if view == "conflicts":
            return info.id in self.conflicts
        if view == "mods":
            return bool(info.all_mods)
        if view.startswith("mod:"):
            return view[4:] in info.all_mods
        if view.startswith("cat:"):
            return info.category == view[4:] and not info.is_mod
        return True

    def refresh_list(self):
        sel_side = self.side.selection()
        view = sel_side[0] if sel_side else "all"
        titles = {"all": "All actions", "sep": "All actions", "pending": "Unsaved changes",
                  "needs": "Mod actions that need a key", "conflicts": "Keys used by more than one action",
                  "mods": "All mod actions"}
        if view in titles:
            self.v_title.set(titles[view])
        elif view.startswith("mod:"):
            self.v_title.set(friendly_mod(view[4:]))
        else:
            self.v_title.set(view.split(":", 1)[-1])
        q = self.v_search.get().strip().lower()
        keep_sel = set(self.list.selection())
        self.list.delete(*self.list.get_children())
        order = {c: n for n, c in enumerate(category_order())}
        rows = []
        for info in self.catalog.values():
            if not self._visible(info) or not self._in_view(info, view):
                continue
            if q:
                hay = " ".join([info.name, info.action, " ".join(self.keys_of(info)), " ".join(info.mod_names),
                                " ".join(info.mods)]).lower()
                if q not in hay:
                    continue
            rows.append(info)
        grouped = view in ("all", "sep", "pending", "conflicts")
        rows.sort(key=lambda i: (0 if (self._needs_key(i) and not grouped) else 1,
                                 order.get(i.category, 99) if grouped else 0, i.name.lower()))
        for n, info in enumerate(rows):
            keys = self.keys_of(info)
            notes, tags = [], []
            if info.id in self._pend_ids():
                tags.append("pending")
                notes.append("\u270e unsaved")
            if info.id in self.conflicts:
                tags.append("conflict")
                notes.append("\u26a0 clash")
            if self._needs_key(info):
                tags.append("needs")
                notes.append("\u26a0 needs key")
            elif self._via(info) and not keys:
                notes.append("via " + self._via(info)[0].split(" (")[0])
            elif info.optional and not keys:
                notes.append("optional")
            elif info.from_snippet and info.id not in self.pending:
                notes.append("new from mod")
            if info.shared_mods and not info.mods:
                notes.append("game key")
            if info.borrow_of and info.borrow_of in self.catalog:
                notes.append(f"{self.catalog[info.borrow_of].name}'s key")
            from_mod = ", ".join(info.mod_names + [friendly_mod(m) for m in info.shared_mods if m not in info.mods])
            self.list.insert("", "end", iid=info.id, tags=tags,
                             values=(info.name, "   or   ".join(keys) if keys else "\u2013",
                                     " / ".join(pad_label(b) for b in self.pad_of(info)) or info.stick or "\u2013",
                                     from_mod, " \u00b7 ".join(notes)))
        self.v_count.set(f"{len(rows)} action{'s' if len(rows) != 1 else ''}")
        keep = [i for i in keep_sel if self.list.exists(i)]
        if keep:
            self.list.selection_set(keep)
        elif rows:
            self.list.selection_set(rows[0].id)
            self.list.focus(rows[0].id)
        self.show_detail()

    def _selected(self) -> list[ActionInfo]:
        return [self.catalog[i] for i in self.list.selection() if i in self.catalog]

    def show_detail(self):
        if not hasattr(self, "d_name"):
            return
        s = self._selected()
        for w in self.d_keys.winfo_children() + self.d_notes.winfo_children():
            w.destroy()
        self.d_where.pack_forget()
        bgc = P["card"]
        if not s:
            self.d_kicker.configure(text="")
            self.d_name.configure(text="Pick an action on the left")
            self.d_info.configure(text="Double-click any row to change its key.")
            for b in (self.d_change, self.d_add, self.d_remove, self.d_undo, self.d_pad_change, self.d_pad_remove,
                      self.d_pad_combo):
                b.state(["disabled"])
            for w in self.d_pad.winfo_children():
                w.destroy()
            return
        for b in (self.d_change, self.d_add, self.d_remove, self.d_pad_change, self.d_pad_combo):
            b.state(["!disabled"])
        if len(s) > 1:
            self.d_kicker.configure(text=f"{len(s)} ACTIONS SELECTED")
            self.d_name.configure(text=", ".join(i.name for i in s[:4]) + (" ..." if len(s) > 4 else ""))
            self.d_info.configure(text="Change key gives all of them the same key.")
            self.d_undo.state(["!disabled"] if any(i.id in self.pending for i in s) else ["disabled"])
            return
        info = s[0]
        kicker = (" \u00b7 ".join(info.mod_names) if info.mods else
                  ("GAME \u00b7 " + info.category).upper())
        self.d_kicker.configure(text=kicker.upper())
        self.d_name.configure(text=info.name)
        keys = self.keys_of(info)
        if keys:
            for n, k in enumerate(keys):
                row = tk.Frame(self.d_keys, bg=bgc)
                row.pack(anchor="w", pady=(0 if n == 0 else 6, 0))
                if n:
                    tk.Label(row, text="or", bg=bgc, fg=P["muted"]).pack(side="left", padx=(0, 6))
                self._keycaps(row, k, bgc)
                try:
                    combo = Combo.parse(k)
                except ValueError:
                    combo = None
                if combo and combo.hideable:
                    var = tk.BooleanVar(value=self.profile.combo_hide.get(k, self.profile.block_modifiers))
                    tk.Checkbutton(self.d_keys, text=(f"Hide {combo.buttons_text()}'s own actions" if combo.is_pad
                                                      else f"Hide {combo.mods_text()} from the game"
                                                      if combo.kind == "press" else
                                                      f"Keep the normal {label(combo.key)} press from the game"),
                                   variable=var, bg=bgc, fg=P["fg"], selectcolor=P["key_bg"],
                                   activebackground=bgc, activeforeground=P["fg"], anchor="w",
                                   font=(theme.FONT_FAMILY, 9),
                                   command=lambda k=k, var=var: self._set_combo_hide(k, bool(var.get()))
                                   ).pack(anchor="w", pady=(4, 0))
        else:
            tk.Label(self.d_keys, text="No keyboard key", bg=bgc, fg=P["muted"],
                     font=(theme.FONT_FAMILY, 11)).pack(anchor="w")

        for w in self.d_pad.winfo_children():
            w.destroy()
        pads = self.pad_of(info)
        if pads:
            for n, b in enumerate(pads):
                if n:
                    tk.Label(self.d_pad, text="or", bg=bgc, fg=P["muted"]).pack(side="left", padx=6)
                tk.Label(self.d_pad, text=pad_label(b, long=True), bg=P["key_bg"], fg=P["key_fg"],
                         font=(theme.FONT_FAMILY, 10, "bold"), padx=10, pady=4, highlightthickness=1,
                         highlightbackground=P["key_border"]).pack(side="left")
            if info.id in self.pending_pad:
                tk.Label(self.d_pad, text="  \u270e", bg=bgc, fg=P["accent"]).pack(side="left")
        elif info.stick and info.id not in self.pending_pad:
            tk.Label(self.d_pad, text=f"{info.stick} (sticks can't be changed here)", bg=bgc,
                     fg=P["muted"]).pack(anchor="w")
        else:
            tk.Label(self.d_pad, text="No controller button" + ("  \u270e" if info.id in self.pending_pad else ""),
                     bg=bgc, fg=P["muted"]).pack(anchor="w")
        self.d_pad_remove.state(["!disabled"] if pads else ["disabled"])
        self.d_pad_change.state(["disabled"] if info.stick else ["!disabled"])

        def note(text, color):
            tk.Label(self.d_notes, text=text, bg=bgc, fg=color, anchor="w", justify="left",
                     wraplength=max(160, self.detail.winfo_width() - 36), font=(theme.FONT_FAMILY, 9)).pack(fill="x", pady=1)
        if info.id in self.pending or info.id in self.pending_ctx:
            note(f"\u270e Not saved yet (was {', '.join(info.keys) or 'no key'})", P["accent"])
        if info.id in self.pending_pad:
            was = " / ".join(pad_label(b, long=True) for b in info.pad) or "no button"
            note(f"\u270e Controller button not saved yet (was {was})", P["accent"])
        for c in self.conflicts.get(info.id, [])[:3]:
            note("\u26a0 " + c, P["warn"])
        if self._needs_key(info):
            note("\u26a0 This mod action has no key yet", P["warn"])
        elif self._via(info) and not keys:
            note("Keyboard works through " + ", ".join(self._via(info)), P["ok"])
        elif info.optional and not keys:
            note("Optional: only set a key if the mod's description asks for one", P["muted"])
        if info.from_snippet and info.id not in self.pending:
            note("From the mod's instructions: added to your file when you save", P["ok"])
        if info.shared_mods:
            note("Also used by " + ", ".join(friendly_mod(m) for m in info.shared_mods) +
                 ", so changing it changes it for the mod too", P["muted"])
        if info.borrow_of:
            game = self.catalog.get(info.borrow_of)
            gname = game.name if game else "the game action"
            note(f"This is {gname}'s key {self._where(info.contexts)}, added by "
                 f"{', '.join(info.mod_names)}. Changing or removing it here doesn't affect {gname} itself.",
                 P["muted"])
        if info.except_contexts:
            split = self.catalog.get("borrow:" + info.id)
            if split:
                note(f"{', '.join(split.mod_names)} also uses this key {self._where(info.except_contexts)}: that's "
                     f"the separate row '{split.name}' under Mods, so changing it here only affects "
                     f"{info.name} itself.", P["muted"])
        self.d_undo.state(["!disabled"] if (info.id in self._pend_ids())
                          else ["disabled"])

        info_lines = []
        if len(info.members) > 1:
            names = ", ".join(m.split("|")[0] for m in info.members[:4])
            info_lines.append(f"Controls {len(info.members)} game actions together ({names}"
                              f"{' ...' if len(info.members) > 4 else ''}).")
        else:
            where = []
            for c in target_contexts(info, self.profile, self.pending_ctx):
                if c.upper().startswith("BASE_"):
                    continue
                fc = friendly_context(c)
                if fc not in where:
                    where.append(fc)
            if where:
                info_lines.append("Works " + ", ".join(where[:5]) + (" ..." if len(where) > 5 else "") + ".")
            info_lines.append(f"Game name: {info.action}")
        others = [k for k in info.pad_keys if not is_pad_button(k) and not k.startswith("IK_Pad_")]
        if others:
            info_lines.append("Also on PlayStation-only buttons: " + ", ".join(pad_label(k) for k in others[:3]))
        self.d_info.configure(text="\n".join(info_lines))
        if len(info.members) == 1:
            self.d_where.pack(fill="x", pady=(8, 0))

    def _context_menu(self, ev):
        row = self.list.identify_row(ev.y)
        if row:
            if row not in self.list.selection():
                self.list.selection_set(row)
            self.menu.tk_popup(ev.x_root, ev.y_root)

    # ------------------------------------------------------------------ editing
    def _changed(self):
        self._compute_conflicts()
        self.refresh_side()
        self._update_pending_bar()

    def change_key(self, add: bool):
        sel = self._selected()
        if not sel:
            messagebox.showinfo("Change key", "First click the action you want to change.")
            return
        if self.current is None:
            messagebox.showwarning("No keybind file", "Your input.settings wasn't found, so nothing can be "
                                   "changed yet. Start the game once, then use File > Reload.")
            return
        d = KeyCaptureDialog(self, sel[0], add)
        self.wait_window(d)
        if not d.result:
            return
        if Combo.parse(d.result).is_chord:
            self._set_combo_hide(d.result, d.hide)
        for info in sel:
            cur = self.keys_of(info)
            new = [d.result] if not add else [k for k in cur if k != d.result] + [d.result]
            self._set_pending(info, new)
        self._changed()

    def _set_pending(self, info: ActionInfo, keys: list[str]):
        if keys == info.keys:
            self.pending.pop(info.id, None)
        else:
            self.pending[info.id] = keys

    def remove_keys(self):
        for info in self._selected():
            self._set_pending(info, [])
        self._changed()

    def undo_selected(self):
        for info in self._selected():
            self.pending.pop(info.id, None)
            self.pending_ctx.pop(info.id, None)
            self.pending_pad.pop(info.id, None)
        self._changed()

    def discard(self):
        if messagebox.askyesno("Discard", "Throw away all unsaved changes?"):
            self.pending.clear()
            self.pending_ctx.clear()
            self.pending_pad.clear()
            self._changed()

    def edit_contexts(self):
        sel = self._selected()
        if not sel or self.current is None:
            return
        info = sel[0]
        if len(info.members) > 1:
            messagebox.showinfo("Where it works", f"'{info.name}' is a standard game binding. It already "
                                "works everywhere the game uses it, so there's nothing to set here.")
            return
        all_ctx = merged_doc(self.current, self.scan_result, self.profile)[0].context_names()
        d = ContextDialog(self, info, all_ctx, target_contexts(info, self.profile, self.pending_ctx))
        self.wait_window(d)
        if d.reset:
            for i in sel:
                self.pending_ctx.pop(i.id, None)
                self.profile.contexts.pop(i.id, None)
            self.save_profile()
        elif d.result is not None:
            for i in sel:
                self.pending_ctx[i.id] = list(d.result)
        else:
            return
        self._changed()

    # ------------------------------------------------------------------ saving
    def _game_running(self) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {self.profile.game_exe}", "/NH"],
                                 capture_output=True, text=True, creationflags=0x08000000, timeout=5).stdout
            return self.profile.game_exe.lower() in out.lower()
        except Exception:
            return False

    def _backup_dir(self) -> Path:
        return Path(self.profile.settings_path).parent / BACKUP_DIRNAME

    def _backup(self, sp: Path) -> Optional[Path]:
        if not sp.exists():
            return None
        bdir = self._backup_dir()
        bdir.mkdir(exist_ok=True)
        dst = bdir / f"input.settings.{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(sp, dst)
        for old in sorted(bdir.glob("input.settings.*"))[:-KEEP_BACKUPS]:
            try:
                old.unlink()
            except OSError:
                pass
        return dst

    @staticmethod
    def _make_writable(p: Path):
        if p.exists() and not os.access(p, os.W_OK):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)

    def save(self):
        if self.current is None:
            messagebox.showwarning("No keybind file", "Your input.settings wasn't found. Start the game once, "
                                   "then use File > Reload.")
            return
        sp = Path(self.profile.settings_path)
        try:  # re-read right before saving in case the game changed it meanwhile
            self.current = sf.load(sp)
        except Exception as e:
            messagebox.showerror("Can't read", f"Couldn't read {sp}:\n{e}")
            return
        cat = build_catalog(self.current, self.scan_result, self.profile)
        res = compile_settings(self.current, self.scan_result, self.profile, self.pending, self.pending_ctx, cat,
                               self.pending_pad)
        adds = sum(1 for i in cat.values() if i.from_snippet and i.id not in self.pending)
        if not (self._pend_ids() or adds or self.resave):
            messagebox.showinfo("Nothing to save", "There are no changes to save.")
            return
        if self._game_running() and not messagebox.askyesno(
                "The Witcher 3 is running", "The game is running. Restart it after saving so it picks up the new "
                "keys.\n\nSave anyway?"):
            return
        lines = []
        n = len(self._pend_ids())
        if n:
            lines.append(f"• {n} key change{'s' if n != 1 else ''}")
        if adds:
            lines.append(f"• {adds} mod keybind{'s' if adds != 1 else ''} added from your mods")
        if res.conflicts:
            lines.append(f"• Heads up, {len(res.conflicts)} key{'s are' if len(res.conflicts) != 1 else ' is'} "
                         "used by more than one action:")
            lines += ["      " + c for c in res.conflicts[:6]]
        for w in res.warnings[:4]:
            lines.append("• " + w)
        if not messagebox.askyesno("Save keybinds", "Save to input.settings?\n\n" + "\n".join(lines) +
                                   "\n\nA backup of the current file is made first."):
            return
        try:
            bak = self._backup(sp)
            self._make_writable(sp)
            sf.save(res.doc, sp)
        except OSError as e:
            messagebox.showerror("Save failed", f"Couldn't write {sp}:\n{e}")
            return
        self.resave = False
        first_combo = bool(res.proxies) and not self.profile.proxies
        self.profile.proxies = dict(res.proxies)
        done = self._pend_ids()
        self.profile.user_set = sorted(set(self.profile.user_set) |
                                       {m for rid in done if rid in cat for m in cat[rid].members})
        for aid, ctxs in self.pending_ctx.items():
            self.profile.contexts[aid] = ctxs
        self.pending.clear()
        self.pending_ctx.clear()
        self.pending_pad.clear()
        self.save_profile()
        self.reload()
        msg = "Saved! Start (or restart) the game to use your new keys."
        if bak:
            msg += "\n\nThe previous file was backed up (File > Restore a backup)."
        if res.proxies:
            msg += ("\n\nYou're using key combos. They work while W3 KeyBinder is open (minimised is fine).")
        messagebox.showinfo("Saved", msg)
        if first_combo and IS_WINDOWS and not get_autostart():
            if messagebox.askyesno("Key combos", "Start W3 KeyBinder minimised with Windows, so your key combos "
                                   "always work?"):
                self.v_autostart.set(True)
                self._toggle_autostart()

    def restore_backup(self):
        bdir = self._backup_dir()
        backups = sorted(bdir.glob("input.settings.*"), reverse=True) if bdir.is_dir() else []
        if not backups:
            messagebox.showinfo("Backups", "There are no backups yet. One is made every time you save.")
            return
        d = BackupsDialog(self, backups)
        self.wait_window(d)
        if not d.result:
            return
        sp = Path(self.profile.settings_path)
        try:
            self._backup(sp)
            self._make_writable(sp)
            shutil.copy2(d.result, sp)
        except OSError as e:
            messagebox.showerror("Restore failed", str(e))
            return
        self.pending.clear()
        self.pending_ctx.clear()
        self.pending_pad.clear()
        self.reload()
        messagebox.showinfo("Restored", "The backup was restored.")

    # ------------------------------------------------------------------ menus
    def choose_game(self):
        d = filedialog.askdirectory(title="Select your 'The Witcher 3' folder (it contains bin, content, mods)",
                                    initialdir=self.profile.game_dir or None)
        if not d:
            return
        p = Path(d)
        if not (p / "content").is_dir() and not (p / "mods").is_dir():
            if not messagebox.askyesno("Game folder", "That doesn't look like the Witcher 3 folder (no 'content' "
                                       "or 'mods' folder inside). Use it anyway?"):
                return
        self.profile.game_dir = d
        self.save_profile()
        self.reload()

    def choose_settings(self):
        f = filedialog.askopenfilename(title="Select input.settings (Documents\\The Witcher 3)",
                                       initialdir=str(Path(self.profile.settings_path).parent),
                                       filetypes=[("input.settings", "input.settings"), ("All files", "*.*")])
        if f:
            self.profile.settings_path = f
            self.save_profile()
            self.reload()

    def add_manual_lines(self):
        d = ManualLinesDialog(self)
        self.wait_window(d)
        if d.result:
            self.profile.manual_snippets.append(d.result)
            self.after_profile_change()

    def add_extra_folder(self):
        d = filedialog.askdirectory(title="Folder with mod downloads / readmes")
        if d and d not in self.profile.extra_scan_dirs:
            self.profile.extra_scan_dirs.append(d)
            self.save_profile()
            self.reload()

    def clear_extra_folders(self):
        if not self.profile.extra_scan_dirs:
            messagebox.showinfo("Extra folders", "No extra folders are being scanned.")
        elif messagebox.askyesno("Extra folders", "Stop scanning:\n" + "\n".join(self.profile.extra_scan_dirs)):
            self.profile.extra_scan_dirs = []
            self.save_profile()
            self.reload()

    def _set_combo_hide(self, combo: str, hide: bool):
        """Per-combo choice: keep the held key(s) from the game while this combo is pressed."""
        self.profile.combo_hide[combo] = hide
        self.save_profile()
        self._update_helper()  # takes effect straight away for combos that are already saved
        try:
            pad = Combo.parse(combo).is_pad
        except ValueError:
            pad = False
        if pad and not any(combo in v for v in self.pending.values()):
            # for controllers, hiding changes input.settings, so it needs a save
            self.resave = True
            self._update_pending_bar()

    def _watch_helper(self):
        """Every 2 s: warn if the game runs as administrator (then our keyboard hook can't see it)."""
        try:
            if self.helper.running and self.helper.game_elevated and self._helper_state != "elevated":
                self._helper_state = "elevated"
                self.v_helper.set("\u26a0 The game is running as administrator, so combos can't reach it. "
                                  "Click to restart W3 KeyBinder as administrator.")
                self.helper_lbl.configure(fg=P["warn"])
            self.after(2000, self._watch_helper)
        except tk.TclError:
            pass

    def _helper_clicked(self):
        from .combohelper import is_admin, restart_as_admin
        if self._helper_state == "on":
            self.test_combos()
            return
        if self._helper_state == "elevated":
            msg = ("The Witcher 3 is running as administrator. Windows doesn't let normal programs see keys "
                   "going to an administrator program, so the combo helper can't turn Alt+1 into its key "
                   "(and Alt reaches the game, so you dodge).\n\nRestart W3 KeyBinder as administrator now?")
        elif self._helper_state == "failed":
            msg = (f"The combo helper couldn't start.\n\nReason: {self.helper.error}\n\n"
                   "Until it runs, combos don't work in game: the game gets your keys unchanged, so Alt still "
                   f"dodges.\n\nDetails are saved in:\n{self.helper.log_path}\n\n"
                   + ("" if is_admin() else "Try restarting W3 KeyBinder as administrator now?"))
        else:
            return
        if self._helper_state == "failed" and is_admin():
            messagebox.showerror("Combo helper", msg)
            return
        if messagebox.askyesno("Combo helper", msg):
            if self._pend_ids() and not messagebox.askyesno(
                    "Unsaved changes", "You have unsaved changes. Restart without saving them?"):
                return
            if restart_as_admin():
                self.helper.stop()
                self.destroy()
            else:
                messagebox.showerror("Combo helper", "Windows didn't start it as administrator.")

    def test_combos(self):
        TestCombosDialog(self)

    def _toggle_block(self):
        self.profile.block_modifiers = bool(self.v_block.get())
        self.save_profile()
        self._update_helper()

    def _toggle_show_all(self):
        self.profile.show_no_keyboard = bool(self.v_show_all.get())
        self.save_profile()
        self.refresh_side()

    def _autostart_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        return f'"{pyw if pyw.exists() else exe}" -m w3keybinder --minimized'

    def _toggle_autostart(self):
        try:
            set_autostart(bool(self.v_autostart.get()), self._autostart_command())
        except OSError as e:
            messagebox.showerror("Start with Windows", str(e))

    def edit_proxy_pool(self):
        cur = ", ".join(label(k) for k in self.profile.proxy_pool)
        txt = simpledialog.askstring(
            "Spare keys for combos",
            "The game only binds single keys, so each combo (like Ctrl+Q) is stored as one of these spare keys\n"
            "and the combo helper presses it for you. Use keys you never press yourself.\n\n"
            "If combos don't work in game, try numpad keys first (e.g. Num 0, Num 1, ...).",
            initialvalue=cur, parent=self)
        if txt is None:
            return
        pool = []
        for part in txt.split(","):
            ik = to_ik(part)
            if ik and ik not in pool:
                pool.append(ik)
        self.profile.proxy_pool = pool or list(DEFAULT_PROXY_POOL)
        self.save_profile()
        messagebox.showinfo("Spare keys", "Saved. New combos will use these keys.")

    def export_ahk(self):
        combos = self._combos_in_file()
        if not combos:
            messagebox.showinfo("AutoHotkey", "You haven't saved any key combos yet.")
            return
        f = filedialog.asksaveasfilename(title="Save AutoHotkey script", defaultextension=".ahk",
                                         initialfile="W3KeyBinder_combos.ahk", filetypes=[("AutoHotkey", "*.ahk")])
        if f:
            Path(f).write_text(generate_ahk(combos, self.profile.game_exe), encoding="utf-8-sig", newline="")
            messagebox.showinfo("AutoHotkey", "Saved. Use it instead of W3 KeyBinder's own combo helper, "
                                "not both at once.")

    def show_help(self):
        messagebox.showinfo("How to use", (
            "1. W3 KeyBinder reads your current keybinds (Documents\\The Witcher 3\\input.settings) and your mods.\n\n"
            "2. Pick a group on the left, click an action, then click 'Change key...' (or double-click) and press "
            "the key you want, e.g. R, Ctrl+Q or Mouse 4.\n\n"
            "3. Click 'Save keybinds'. A backup is made every time; File > Restore a backup puts an old one back.\n\n"
            "Mods: the keybind lines your mods need are added automatically when you save. If a mod's lines are "
            "only on its Nexus page, use Mods > Add a mod's keybind lines manually."))

    def show_combo_help(self):
        messagebox.showinfo("Key combos", (
            "The Witcher 3 only understands single keys. When you bind something like Ctrl+Q, W3 KeyBinder "
            "gives that action a spare key (F13, F14 ...) in the game, and while the game is in front its "
            "combo helper turns Ctrl+Q into that spare key.\n\n"
            "• Keep W3 KeyBinder open (minimised is fine), or turn on Options > Start with Windows.\n"
            "• Any key or mouse button can be the held key: Ctrl+Q, Alt+1, Mouse 4 + 2, Caps Lock + Q ...\n"
            "• Each combo has a 'Hide ... from the game' box (in the key dialog and on the right). When ticked, "
            "the held key is hidden while you press the combo, so Alt+1 doesn't also dodge; pressed on its own "
            "it still works (the game gets it when you let go, or after a quarter of a second if held).\n"
            "• If combos don't work in game, try Options > Spare keys and put numpad keys first."))

    def save_report(self):
        from .report import build_report
        text = build_report(self.profile.settings_path, self.profile.game_dir,
                            self.current.entry_count() if self.current else 0, self.scan_result, self.catalog,
                            self.helper)
        f = filedialog.asksaveasfilename(title="Save report", defaultextension=".txt",
                                         initialdir=str(paths.documents_dir()),
                                         initialfile="W3KeyBinder report.txt", filetypes=[("Text", "*.txt")])
        if f:
            Path(f).write_text(text, encoding="utf-8")
            messagebox.showinfo("Report saved", f"Saved to:\n{f}\n\nSend this file when asking for help. It "
                                "lists your mods and what was found for each. No personal data is in it "
                                "apart from folder names.")

    @staticmethod
    def _open(p: Path):
        try:
            if sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Open", str(e))

    def on_close(self):
        if self._pend_ids() and not messagebox.askyesno(
                "Unsaved changes", "You have unsaved changes. Close without saving?"):
            return
        if self.helper.running and self._combos_in_file():
            if not messagebox.askyesno("Key combos", "Closing W3 KeyBinder turns your key combos off until you "
                                       "open it again. Close anyway?\n\n(Tip: minimise it instead.)"):
                return
        self.helper.stop()
        self.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App(start_minimized="--minimized" in argv).mainloop()


if __name__ == "__main__":
    main()
