"""Key names: Witcher 3 ``IK_*`` codes, friendly labels, Windows virtual-key codes and combos."""
from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Optional

MODIFIERS = ("Ctrl", "Shift", "Alt")
PAD_BY_IK: dict = {}   # filled in below, with the controller button table
MODIFIER_IK = {"Ctrl": ("IK_Ctrl", "IK_LControl", "IK_RControl"), "Shift": ("IK_Shift", "IK_LShift", "IK_RShift"),
               "Alt": ("IK_Alt",)}
NONE_KEY = "IK_None"  # what the game writes for "no key"

# (IK name, friendly label, Windows VK code or None, AutoHotkey key name)
_KEYS: list[tuple[str, str, Optional[int], str]] = []


def _k(ik: str, label: str, vk: Optional[int], ahk: Optional[str] = None) -> None:
    _KEYS.append((ik, label, vk, ahk or (f"vk{vk:02X}" if vk is not None else label)))


for c in string.ascii_uppercase:
    _k(f"IK_{c}", c, ord(c))
for d in range(10):
    _k(f"IK_{d}", str(d), 0x30 + d)
for n in range(1, 25):
    _k(f"IK_F{n}", f"F{n}", 0x6F + n)
for d in range(10):
    _k(f"IK_NumPad{d}", f"Num {d}", 0x60 + d)
for ik, label, vk in [
    ("IK_NumStar", "Num *", 0x6A), ("IK_NumPlus", "Num +", 0x6B), ("IK_NumMinus", "Num -", 0x6D),
    ("IK_NumPeriod", "Num .", 0x6E), ("IK_NumSlash", "Num /", 0x6F),
    ("IK_Space", "Space", 0x20), ("IK_Enter", "Enter", 0x0D), ("IK_Escape", "Esc", 0x1B),
    ("IK_Tab", "Tab", 0x09), ("IK_Backspace", "Backspace", 0x08),
    ("IK_Insert", "Insert", 0x2D), ("IK_Delete", "Delete", 0x2E), ("IK_Home", "Home", 0x24),
    ("IK_End", "End", 0x23), ("IK_PageUp", "Page Up", 0x21), ("IK_PageDown", "Page Down", 0x22),
    ("IK_Left", "Left", 0x25), ("IK_Up", "Up", 0x26), ("IK_Right", "Right", 0x27), ("IK_Down", "Down", 0x28),
    ("IK_CapsLock", "Caps Lock", 0x14), ("IK_NumLock", "Num Lock", 0x90), ("IK_ScrollLock", "Scroll Lock", 0x91),
    ("IK_Pause", "Pause", 0x13), ("IK_PrintScrn", "Print Screen", 0x2C),
    ("IK_Semicolon", ";", 0xBA), ("IK_Equals", "=", 0xBB), ("IK_Comma", ",", 0xBC), ("IK_Minus", "-", 0xBD),
    ("IK_Period", ".", 0xBE), ("IK_Slash", "/", 0xBF), ("IK_Tilde", "`", 0xC0), ("IK_LeftBracket", "[", 0xDB),
    ("IK_Backslash", "\\", 0xDC), ("IK_RightBracket", "]", 0xDD), ("IK_SingleQuote", "'", 0xDE),
    ("IK_Shift", "Shift", 0x10), ("IK_Ctrl", "Ctrl", 0x11), ("IK_Alt", "Alt", 0x12),
    ("IK_LShift", "Left Shift", 0xA0), ("IK_RShift", "Right Shift", 0xA1),
    ("IK_LControl", "Left Ctrl", 0xA2), ("IK_RControl", "Right Ctrl", 0xA3),
]:
    _k(ik, label, vk)
for ik, label, ahk in [
    ("IK_LeftMouse", "Mouse Left", "LButton"), ("IK_RightMouse", "Mouse Right", "RButton"),
    ("IK_MiddleMouse", "Mouse Middle", "MButton"), ("IK_Mouse4", "Mouse 4", "XButton1"),
    ("IK_Mouse5", "Mouse 5", "XButton2"), ("IK_MouseWheelUp", "Wheel Up", "WheelUp"),
    ("IK_MouseWheelDown", "Wheel Down", "WheelDown"), ("IK_MouseZ", "Mouse wheel", "WheelUp"),
    ("IK_Mouse6", "Mouse 6", "XButton2"), ("IK_Mouse7", "Mouse 7", "XButton2"), ("IK_Mouse8", "Mouse 8", "XButton2"),
]:
    _k(ik, label, None, ahk)

KEYS_BY_IK = {k[0]: k for k in _KEYS}
IK_BY_LABEL = {k[1].lower(): k[0] for k in _KEYS}
IK_BY_VK = {k[2]: k[0] for k in _KEYS if k[2] is not None and k[0] not in
            ("IK_LShift", "IK_RShift", "IK_LControl", "IK_RControl")}
ALL_LABELS = [k[1] for k in _KEYS if k[0] not in ("IK_MouseZ", "IK_Mouse6", "IK_Mouse7", "IK_Mouse8")]
WHEEL_KEYS = {"IK_MouseWheelUp", "IK_MouseWheelDown"}
MODIFIER_KEYS = {"IK_Shift", "IK_Ctrl", "IK_Alt", "IK_LShift", "IK_RShift", "IK_LControl", "IK_RControl"}

# Keys the generated AutoHotkey script can press on your behalf for Ctrl/Shift/Alt combos.
# They must be keys the game understands but that you never physically press.
DEFAULT_PROXY_POOL = [f"IK_F{n}" for n in range(13, 25)] + [
    "IK_NumPad0", "IK_NumPad1", "IK_NumPad2", "IK_NumPad3", "IK_NumPad4", "IK_NumPad5",
    "IK_NumPad6", "IK_NumPad7", "IK_NumPad8", "IK_NumPad9", "IK_NumStar", "IK_NumSlash",
    "IK_NumPlus", "IK_NumMinus", "IK_NumPeriod", "IK_ScrollLock", "IK_Pause",
]

_NON_KBM_PREFIXES = ("IK_Pad", "IK_Joy", "IK_Steam", "IK_PS4", "IK_PS5", "IK_Touch")
_AXES = {"IK_MouseX", "IK_MouseY", "IK_MouseW", "IK_None"}


def is_kbm(ik: str) -> bool:
    """Keyboard / mouse button (rebindable here) as opposed to gamepad keys or mouse axes."""
    return not ik.startswith(_NON_KBM_PREFIXES) and ik not in _AXES


def label(ik: str) -> str:
    if ik in PAD_BY_IK:
        return "Pad " + PAD_BY_IK[ik][1]
    k = KEYS_BY_IK.get(ik)
    return k[1] if k else ik[3:] if ik.startswith("IK_") else ik


def to_ik(name: str) -> Optional[str]:
    """Accept 'Q', 'Num 1', 'Mouse 4' or 'IK_Q'."""
    n = name.strip()
    if not n:
        return None
    if n.upper().startswith("IK_"):
        for ik in KEYS_BY_IK:
            if ik.lower() == n.lower():
                return ik
        return "IK_" + n[3:]  # unknown but plausible IK code: pass through
    return IK_BY_LABEL.get(n.lower())


def ahk_name(ik: str) -> str:
    k = KEYS_BY_IK.get(ik)
    if not k:
        raise ValueError(f"No AutoHotkey name known for {ik}")
    return k[3]


STANDARD_MOD_OF = {"IK_Shift": "Shift", "IK_LShift": "Shift", "IK_RShift": "Shift",
                   "IK_Ctrl": "Ctrl", "IK_LControl": "Ctrl", "IK_RControl": "Ctrl", "IK_Alt": "Alt"}
NOT_HOLDABLE = {"IK_MouseWheelUp", "IK_MouseWheelDown", "IK_MouseZ"}


def mod_name(ik_or_name: str) -> str:
    """A held key as stored in a combo: 'Ctrl'/'Shift'/'Alt' (either side), else its IK code."""
    if ik_or_name in MODIFIERS:
        return ik_or_name
    return STANDARD_MOD_OF.get(ik_or_name, ik_or_name)


def mod_label(m: str) -> str:
    return m if m in MODIFIERS else label(m)


KINDS = {"hold": "Hold", "double": "Double-tap"}
DEFAULT_MS = {"hold": 1000, "double": 300}
_TIMED_RE = re.compile(r"^(Hold|Double-tap)\s+(.+?)\s*\((\d+)\s*ms\)$", re.I)


@dataclass(frozen=True)
class Combo:
    """A binding the combo helper can turn into one key for the game.

    Ctrl+Q, Alt+1, Mouse 4+2 ............ hold key(s)/button(s), press another
    Pad LB+Pad RB+Pad A ................. up to three controller buttons together
    Hold R (1500ms) ..................... keep one key/button down that long
    Double-tap Pad R3 (300ms) ........... press one key/button twice within that time
    A plain key ("Q") is a Combo too; it needs no helper.
    """
    key: str                         # IK code of the key pressed last
    mods: frozenset = frozenset()    # held keys: "Ctrl"/"Shift"/"Alt" or any IK code (e.g. "IK_Mouse4")
    kind: str = "press"              # "press", "hold" or "double"
    ms: int = 0                      # hold time / double-tap window

    @property
    def is_pad(self) -> bool:
        return self.key in PAD_BY_IK

    @property
    def is_chord(self) -> bool:
        """Needs the combo helper (and a spare key in input.settings)."""
        return bool(self.mods) or self.kind != "press" or self.is_pad

    @property
    def hideable(self) -> bool:
        """Has a 'hide' option: keep the keys' / buttons' own actions from firing with this binding."""
        return bool(self.mods) or self.kind != "press"

    def buttons_text(self) -> str:
        names = [label(m) for m in self.custom_mods] + [label(self.key)]
        return ", ".join(n.replace("Pad ", "") for n in names)

    @property
    def custom_mods(self) -> list:
        return sorted((m for m in self.mods if m not in MODIFIERS), key=lambda m: label(m).lower())

    def base_text(self) -> str:
        parts = [m for m in MODIFIERS if m in self.mods] + [label(m) for m in self.custom_mods]
        return "+".join(parts + [label(self.key)])

    def __str__(self) -> str:
        if self.kind in KINDS:
            return f"{KINDS[self.kind]} {self.base_text()} ({self.ms}ms)"
        return self.base_text()

    def mods_text(self) -> str:
        return " + ".join([m for m in MODIFIERS if m in self.mods] + [label(m) for m in self.custom_mods])

    @staticmethod
    def parse(text: str) -> "Combo":
        text = text.strip()
        kind, ms = "press", 0
        m = _TIMED_RE.match(text)
        if m:
            kind = "hold" if m.group(1).lower() == "hold" else "double"
            text, ms = m.group(2), int(m.group(3))
            if not 50 <= ms <= 10000:
                raise ValueError("The time must be between 50 and 10000 ms")
        t = text.replace("Num +", "Num\x00")       # the only key label that contains '+'
        tokens = [x.strip().replace("Num\x00", "Num +") for x in t.split("+")]
        if not tokens or not tokens[-1]:
            raise ValueError(f"Unknown key '{text}'")
        aliases = {"ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt"}
        mods = set()
        for tok in tokens[:-1]:
            mm = aliases.get(tok.lower())
            if not mm:
                ik = to_ik(tok)
                if not ik:
                    raise ValueError(f"Unknown key '{tok}'")
                if ik in NOT_HOLDABLE:
                    raise ValueError(f"'{tok}' can't be held as part of a combo")
                mm = mod_name(ik)
            mods.add(mm)
        ik = to_ik(tokens[-1])
        if not ik:
            raise ValueError(f"Unknown key '{tokens[-1]}'")
        if mods and (ik in MODIFIER_KEYS or mod_name(ik) in mods):
            raise ValueError("The last key of a combo can't also be one of the held keys")
        pads = [x for x in list(mods) + [ik] if x in PAD_BY_IK]
        if pads and len(pads) != len(mods) + 1:
            raise ValueError("Controller buttons and keyboard keys can't be mixed in one combo")
        if len(pads) > 3:
            raise ValueError("A controller combo can have up to three buttons")
        if kind != "press" and mods:
            raise ValueError("Hold and double-tap work with a single key or button")
        if kind != "press" and ik in NOT_HOLDABLE:
            raise ValueError("The mouse wheel can't be held or double-tapped")
        return Combo(ik, frozenset(mods), kind, ms)


# ---- controller buttons ----
# (game name, short label, long label, XInput button bit or None for triggers)
PAD_BUTTONS = [
    ("IK_Pad_A_CROSS", "A", "A / Cross", 0x1000), ("IK_Pad_B_CIRCLE", "B", "B / Circle", 0x2000),
    ("IK_Pad_X_SQUARE", "X", "X / Square", 0x4000), ("IK_Pad_Y_TRIANGLE", "Y", "Y / Triangle", 0x8000),
    ("IK_Pad_LeftShoulder", "LB", "LB / L1", 0x0100), ("IK_Pad_RightShoulder", "RB", "RB / R1", 0x0200),
    ("IK_Pad_LeftTrigger", "LT", "LT / L2", None), ("IK_Pad_RightTrigger", "RT", "RT / R2", None),
    ("IK_Pad_LeftThumb", "L3", "L3 (left stick click)", 0x0040),
    ("IK_Pad_RightThumb", "R3", "R3 (right stick click)", 0x0080),
    ("IK_Pad_DigitUp", "D-pad Up", "D-pad Up", 0x0001), ("IK_Pad_DigitDown", "D-pad Down", "D-pad Down", 0x0002),
    ("IK_Pad_DigitLeft", "D-pad Left", "D-pad Left", 0x0004),
    ("IK_Pad_DigitRight", "D-pad Right", "D-pad Right", 0x0008),
    ("IK_Pad_Start", "Menu", "Menu / Start / Options", 0x0010),
    ("IK_Pad_Back_Select", "View", "View / Back / Select", 0x0020),
]
PAD_BY_IK.update({p[0]: p for p in PAD_BUTTONS})
IK_BY_LABEL.update({("pad " + p[1]).lower(): p[0] for p in PAD_BUTTONS})
PAD_BY_LONG = {p[2].lower(): p[0] for p in PAD_BUTTONS}
PAD_LONG_LABELS = [p[2] for p in PAD_BUTTONS]
PAD_BY_BIT = {p[3]: p[0] for p in PAD_BUTTONS if p[3]}


def is_pad_button(ik: str) -> bool:
    """A controller button we can rebind (sticks and PlayStation-only extras are left alone)."""
    return ik in PAD_BY_IK


def pad_label(ik: str, long: bool = False) -> str:
    p = PAD_BY_IK.get(ik)
    if p:
        return p[2] if long else p[1]
    return ik[3:].replace("Pad_", "").replace("_", " ") if ik.startswith("IK_") else ik
