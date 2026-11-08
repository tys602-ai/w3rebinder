"""Key names: Witcher 3 ``IK_*`` codes, friendly labels, Windows virtual-key codes and combos."""
from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Optional

MODIFIERS = ("Ctrl", "Shift", "Alt")
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


@dataclass(frozen=True)
class Combo:
    """A key, optionally with keys/buttons held first: Ctrl+Q, Alt+1, Mouse 4+2, Caps Lock+Mouse 5."""
    key: str                         # IK code of the key pressed last
    mods: frozenset = frozenset()    # held keys: "Ctrl"/"Shift"/"Alt" or any IK code (e.g. "IK_Mouse4")

    @property
    def is_chord(self) -> bool:
        return bool(self.mods)

    @property
    def custom_mods(self) -> list:
        return sorted((m for m in self.mods if m not in MODIFIERS), key=lambda m: label(m).lower())

    def __str__(self) -> str:
        parts = [m for m in MODIFIERS if m in self.mods] + [label(m) for m in self.custom_mods]
        return "+".join(parts + [label(self.key)])

    def mods_text(self) -> str:
        return " + ".join([m for m in MODIFIERS if m in self.mods] + [label(m) for m in self.custom_mods])

    @staticmethod
    def parse(text: str) -> "Combo":
        t = text.strip().replace("Num +", "Num\x00")       # the only key label that contains '+'
        tokens = [x.strip().replace("Num\x00", "Num +") for x in t.split("+")]
        if not tokens or not tokens[-1]:
            raise ValueError(f"Unknown key '{text.strip()}'")
        aliases = {"ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt"}
        mods = set()
        for tok in tokens[:-1]:
            m = aliases.get(tok.lower())
            if not m:
                ik = to_ik(tok)
                if not ik:
                    raise ValueError(f"Unknown key '{tok}'")
                if ik in NOT_HOLDABLE:
                    raise ValueError(f"'{tok}' can't be held as part of a combo")
                m = mod_name(ik)
            mods.add(m)
        ik = to_ik(tokens[-1])
        if not ik:
            raise ValueError(f"Unknown key '{tokens[-1]}'")
        if mods and (ik in MODIFIER_KEYS or mod_name(ik) in mods):
            raise ValueError("The last key of a combo can't also be one of the held keys")
        return Combo(ik, frozenset(mods))
