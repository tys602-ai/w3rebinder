"""Built-in combo helper (Windows only).

The Witcher 3 can't bind Ctrl+Q, so input.settings gets a spare key (e.g. F13) for that action instead.
While the game window is in front, this low-level keyboard/mouse hook watches for Ctrl+Q, swallows the
Q, and holds F13 down for as long as Q is held. Everything else passes through untouched.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from typing import Optional

from .keys import KEYS_BY_IK, Combo

IS_WINDOWS = sys.platform == "win32"

# mouse IK -> (down msg, up msg, xbutton number)
_MOUSE = {
    "IK_LeftMouse": (0x0201, 0x0202, 0), "IK_RightMouse": (0x0204, 0x0205, 0),
    "IK_MiddleMouse": (0x0207, 0x0208, 0), "IK_Mouse4": (0x020B, 0x020C, 1), "IK_Mouse5": (0x020B, 0x020C, 2),
}
_EXTENDED_VK = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0x90, 0xA3, 0xA5}
MASK_VK = 0xE8  # unassigned key, tapped after Alt combos so Windows doesn't open the window menu


def _token(m: str):
    """Combo held key -> engine token."""
    if m in ("Ctrl", "Shift", "Alt"):
        return m
    if m in _MOUSE:
        down, _, xb = _MOUSE[m]
        return ("m", down, xb)
    vk = _vk(m)
    return ("k", vk) if vk is not None else None


def _vk(ik: str) -> Optional[int]:
    k = KEYS_BY_IK.get(ik)
    return k[2] if k else None



# Windows virtual-key codes of the left/right modifier keys, as a low-level hook reports them
MOD_VKS = {0xA0: "Shift", 0xA1: "Shift", 0xA2: "Ctrl", 0xA3: "Ctrl", 0xA4: "Alt", 0xA5: "Alt"}
HOLD_DELAY = 0.25  # seconds a held-back key waits before the game gets it anyway


class ComboEngine:
    """Decides what happens to each key/mouse event. Pure Python, so it can be tested anywhere.

    A combo is (held keys, last key). Held keys ("tokens") are "Ctrl"/"Shift"/"Alt" (either side),
    ("k", vk) for any other key, or ("m", down_msg, xbutton) for a mouse button.
    Table entries are (tokens, proxy_vk, hide): with hide=True the held keys are kept from the game:
      * the combo follows        -> only the combo's spare key reaches the game (Alt+1 doesn't dodge)
      * tapped on its own        -> the game gets the tap when you let go
      * held on its own          -> the game gets it after HOLD_DELAY
      * another key/button comes -> the game gets the held key first, then that one (Shift+W, Alt+Tab)
    With hide=False the held key always reaches the game as normal.

    Every method returns (swallow, actions). swallow=True means the real event must not reach the game.
    Actions: ("down"|"up"|"tap", vk) keyboard keys, ("mdown"|"mup"|"mtap", (msg, xbutton)) mouse
    buttons, and ("timer", source, generation): call timeout(source, generation) after HOLD_DELAY.
    """

    def __init__(self, kb_combos, mouse_combos, wheel_combos):
        self.kb = kb_combos            # vk -> [(tokens, proxy_vk, hide)]
        self.mouse = mouse_combos      # (down_msg, xbutton) -> [...]
        self.wheel = wheel_combos      # +1 / -1 -> [...]
        entries = [e for table in (kb_combos, mouse_combos, wheel_combos) for es in table.values() for e in es]
        self.tokens = {t for toks, _, _ in entries for t in toks}
        self.hideable = {t for toks, _, hide in entries if hide for t in toks}
        self.state: dict = {}          # source (vk or ("m", msg, xb)) -> [token, "pending"|"passed"|"used"|"through", gen]
        self.held: dict = {}           # combo trigger -> proxy vk currently held down
        self.gen = 0
        self.lock = threading.RLock()
        self.presses = 0

    # ---- helpers ----
    @staticmethod
    def _token_for_vk(vk: int):
        return MOD_VKS.get(vk, ("k", vk))

    def _tokens_now(self, async_mods: frozenset) -> frozenset:
        mine = {st[0] for st in self.state.values()}
        return frozenset(mine | {m for m in async_mods if m not in self.tokens})

    def _match(self, entries, async_mods):
        now = self._tokens_now(async_mods)
        for toks, pvk, hide in entries:
            if toks == now:
                return toks, pvk, hide
        return None

    @staticmethod
    def _down_action(src):
        return ("mdown", src[1:]) if isinstance(src, tuple) else ("down", src)

    def _flush(self) -> list:
        acts = []
        for src, st in self.state.items():
            if st[1] == "pending":
                st[1] = "passed"
                acts.append(self._down_action(src))
        return acts

    def _fire(self, trigger, toks, pvk, hide) -> list:
        acts = []
        for src, st in self.state.items():
            if st[0] in toks and st[1] == "pending":
                if hide:
                    st[1] = "used"
                else:
                    st[1] = "passed"
                    acts.append(self._down_action(src))
        acts.append(("down", pvk))
        self.held[trigger] = pvk
        self.presses += 1
        alt_hidden = any(st[0] == "Alt" and st[1] == "used" for st in self.state.values())
        if "Alt" in toks and not alt_hidden:
            acts += [("down", MASK_VK), ("up", MASK_VK)]  # stop Windows opening the window menu
        return acts

    def _held_key_down(self, src, token, in_game):
        """A key/button that is held as part of a combo was pressed. Returns (swallow, actions)."""
        if not in_game:
            return False, []
        if token in self.hideable:
            self.gen += 1
            self.state[src] = [token, "pending", self.gen]
            return True, [("timer", src, self.gen)]
        self.state[src] = [token, "through", 0]
        return False, []

    def _held_key_up(self, src):
        st = self.state.pop(src)
        if st[1] == "pending":
            return True, [("mtap", src[1:]) if isinstance(src, tuple) else ("tap", src)]
        return st[1] == "used", []

    # ---- events ----
    def key(self, vk: int, down: bool, in_game: bool, async_mods: frozenset = frozenset()):
        with self.lock:
            if down:
                if vk in self.state:                    # key repeat of a held key
                    return self.state[vk][1] in ("pending", "used"), []
                if vk in self.held:                     # key repeat of a combo
                    return True, []
                entries = self.kb.get(vk)
                if entries and in_game:
                    hit = self._match(entries, async_mods)
                    if hit:
                        return True, self._fire(vk, *hit)
                token = self._token_for_vk(vk)
                if token in self.tokens:
                    return self._held_key_down(vk, token, in_game)
                return False, self._flush()
            if vk in self.state:
                return self._held_key_up(vk)
            pvk = self.held.pop(vk, None)
            return (True, [("up", pvk)]) if pvk is not None else (False, [])

    def mouse_button(self, down_msg: int, xbutton: int, down: bool, in_game: bool,
                     async_mods: frozenset = frozenset()):
        with self.lock:
            src = ("m", down_msg, xbutton)
            if down:
                if src in self.held:
                    return True, []
                entries = self.mouse.get((down_msg, xbutton))
                if entries and in_game:
                    hit = self._match(entries, async_mods)
                    if hit:
                        return True, self._fire(src, *hit)
                if src in self.tokens:
                    return self._held_key_down(src, src, in_game)
                return False, self._flush()
            if src in self.state:
                return self._held_key_up(src)
            pvk = self.held.pop(src, None)
            return (True, [("up", pvk)]) if pvk is not None else (False, [])

    def wheel_turn(self, direction: int, in_game: bool, async_mods: frozenset = frozenset()):
        with self.lock:
            entries = self.wheel.get(direction)
            if entries and in_game:
                hit = self._match(entries, async_mods)
                if hit:
                    acts = self._fire(("w", direction), *hit)
                    pvk = self.held.pop(("w", direction))
                    return True, [("tap", pvk) if a == ("down", pvk) else a for a in acts]
            return False, self._flush()

    def timeout(self, src, generation: int) -> list:
        """The key has been held on its own long enough: let the game have it."""
        with self.lock:
            st = self.state.get(src)
            if st and st[1] == "pending" and st[2] == generation:
                st[1] = "passed"
                return [self._down_action(src)]
            return []

    def flush(self) -> list:
        with self.lock:
            return self._flush()

    def claims(self, src, async_mods: frozenset = frozenset()) -> bool:
        """This key/button is (or is about to be) part of a combo, so the combo logic must handle it."""
        with self.lock:
            if src in self.held or src in self.state:
                return True
            if isinstance(src, tuple):
                if src in self.tokens:
                    return True
                entries = self.mouse.get(src[1:])
            else:
                if self._token_for_vk(src) in self.tokens:
                    return True
                entries = self.kb.get(src)
            return bool(entries and self._match(entries, async_mods))

    def release_all(self) -> list:
        with self.lock:
            acts = [("up", pvk) for pvk in self.held.values()]
            for src, st in self.state.items():
                if st[1] == "passed":
                    acts.append(("mup", src[1:]) if isinstance(src, tuple) else ("up", src))
            self.held.clear()
            self.state.clear()
            return acts


class TimedEngine:
    """Hold-for-a-while and double-tap triggers on a single key or mouse button.

    table: source -> {"hold": (ms, proxy_vk), "double": (ms, proxy_vk), "hide": bool}
    A source is a virtual-key code or ("m", down_msg, xbutton).
    hide=False: the key reaches the game as usual; the proxy key is pressed in addition.
    hide=True:  the key is held back until we know what the press is:
        held long enough      -> hold proxy (the game never sees the key)
        tapped twice in time  -> double-tap proxy
        a single tap          -> the game gets the tap (after the double-tap window, if there is one)
        held, with no hold trigger -> the game gets the key once the double-tap window has passed
    Methods return (swallow, actions) like ComboEngine; ("ttimer", src, gen, kind, seconds) asks the
    caller to call timeout(src, gen, kind, now) after that delay.
    """

    def __init__(self, table: dict):
        self.table = table
        self.st: dict = {}
        self.lock = threading.RLock()
        self.presses = 0

    def owns(self, src) -> bool:
        return src in self.table

    def busy(self, src) -> bool:
        s = self.st.get(src)
        return bool(s and (s["state"] != "idle" or s["down"]))

    @staticmethod
    def _k(kind, src):
        return ("m" + kind, src[1:]) if isinstance(src, tuple) else (kind, src)

    def _s(self, src):
        return self.st.setdefault(src, {"state": "idle", "down": False, "gen": 0, "t0": 0.0, "last": None,
                                        "held": [], "dbl_open": False})

    def event(self, src, down: bool, in_game: bool, now: float):
        with self.lock:
            cfg = self.table.get(src)
            if not cfg:
                return False, []
            s = self._s(src)
            if not in_game and s["state"] == "idle" and not s["down"]:
                return False, []
            hold, dbl = cfg.get("hold"), cfg.get("double")
            if not cfg.get("hide"):
                return self._watch(src, s, down, now, hold, dbl)
            return self._hidden(src, s, down, now, hold, dbl)

    # the key always reaches the game; we only add the proxy
    def _watch(self, src, s, down, now, hold, dbl):
        acts = []
        if down:
            if s["down"]:
                return False, []
            s["down"] = True
            s["gen"] += 1
            if dbl and s["last"] is not None and (now - s["last"]) * 1000 <= dbl[0]:
                acts.append(("down", dbl[1]))
                s["held"].append(dbl[1])
                s["last"] = None
                self.presses += 1
            else:
                s["last"] = now
            if hold:
                acts.append(("ttimer", src, s["gen"], "hold", hold[0] / 1000))
        else:
            s["down"] = False
            s["gen"] += 1
            acts += [("up", p) for p in s["held"]]
            s["held"] = []
        return False, acts

    def _hidden(self, src, s, down, now, hold, dbl):
        st = s["state"]
        if down:
            if s["down"]:
                return True, []                       # key repeat
            s["down"] = True
            if st == "idle":
                s.update(state="first", t0=now, dbl_open=bool(dbl))
                s["gen"] += 1
                acts = []
                if dbl:
                    acts.append(("ttimer", src, s["gen"], "double", dbl[0] / 1000))
                if hold:
                    acts.append(("ttimer", src, s["gen"], "hold", hold[0] / 1000))
                return True, acts
            if st == "wait2":
                s["state"] = "dbl"
                s["gen"] += 1
                self.presses += 1
                return True, [("down", dbl[1])]
            return True, []
        s["down"] = False
        if st == "first":
            if s["dbl_open"]:
                s["state"] = "wait2"                  # maybe the first half of a double tap
                return True, []
            s["state"] = "idle"
            s["gen"] += 1
            return True, [self._k("tap", src)]
        if st == "holding":
            s["state"] = "idle"
            return True, [("up", hold[1])]
        if st == "dbl":
            s["state"] = "idle"
            return True, [("up", dbl[1])]
        if st == "passed":
            s["state"] = "idle"
            return True, [self._k("up", src)]
        return st != "idle", []

    def timeout(self, src, gen: int, kind: str, now: float) -> list:
        with self.lock:
            cfg, s = self.table.get(src), self.st.get(src)
            if not cfg or not s or s["gen"] != gen:
                return []
            hold, dbl = cfg.get("hold"), cfg.get("double")
            if not cfg.get("hide"):
                if kind == "hold" and s["down"] and hold:
                    s["held"].append(hold[1])
                    self.presses += 1
                    return [("down", hold[1])]
                return []
            if kind == "hold" and s["state"] == "first" and s["down"]:
                s["state"] = "holding"
                self.presses += 1
                return [("down", hold[1])]
            if kind == "double":
                s["dbl_open"] = False
                if s["state"] == "wait2":             # it was a single tap after all
                    s["state"] = "idle"
                    return [self._k("tap", src)]
                if s["state"] == "first" and s["down"] and not hold:
                    s["state"] = "passed"             # plain long press: hand the key to the game
                    return [self._k("down", src)]
            return []

    def release_all(self) -> list:
        with self.lock:
            acts = []
            for src, s in self.st.items():
                cfg = self.table.get(src, {})
                acts += [("up", p) for p in s["held"]]
                if s["state"] == "holding" and cfg.get("hold"):
                    acts.append(("up", cfg["hold"][1]))
                if s["state"] == "dbl" and cfg.get("double"):
                    acts.append(("up", cfg["double"][1]))
                if s["state"] == "passed":
                    acts.append(self._k("up", src))
            self.st.clear()
            return acts


class PadEngine:
    """Controller combos (2-3 buttons together), hold and double-tap, from polled button states.

    combos: [(frozenset of buttons, proxy_vk)]; holds/doubles: button -> (ms, proxy_vk).
    solo: button -> proxy_vk for "hidden" buttons. The game has no binding on such a button any more;
    its own actions sit on the proxy key, which we press when the button is used on its own:
        part of a combo / hold fired / double-tapped -> nothing else is sent
        tapped alone                                 -> proxy tapped on release
        held alone                                   -> proxy held after HOLD_DELAY
        another, unrelated button pressed            -> proxy held at once
    Buttons not in solo reach the game directly, as always.
    update() returns ("down"|"up"|"tap", proxy_vk) actions.
    """

    def __init__(self, combos, holds, doubles, solo=None):
        self.combos, self.holds, self.doubles = list(combos), dict(holds), dict(doubles)
        self.solo = dict(solo or {})
        self.prev: set = set()
        self.active: dict = {}        # combo index -> proxy held
        self.since: dict = {}         # button -> time it went down
        self.last: dict = {}          # button -> time of the previous press (for double tap)
        self.hold_on: dict = {}       # button -> proxy held
        self.dbl_on: dict = {}
        self.tainted: set = set()     # buttons that took part in a combo during this press
        self.sstate: dict = {}        # hidden button -> "pending" | "passed" | "used" | "wait2"
        self.presses = 0

    @property
    def empty(self) -> bool:
        return not (self.combos or self.holds or self.doubles)

    def _related(self, a, b) -> bool:
        return any(a in btns and b in btns for btns, _ in self.combos)

    def update(self, pressed: set, in_game: bool, now: float) -> list:
        acts = []
        if not in_game:
            acts += [("up", self.solo[b]) for b, st in self.sstate.items() if st == "passed"]
            self.sstate.clear()
            pressed = set()
        for b in pressed - self.prev:
            self.since[b] = now
            d = self.doubles.get(b)
            if d and b in self.last and (now - self.last[b]) * 1000 <= d[0]:
                acts.append(("down", d[1]))
                self.dbl_on[b] = d[1]
                self.last.pop(b)
                self.presses += 1
                if b in self.solo:
                    self.sstate[b] = "used"
            else:
                self.last[b] = now
                if b in self.solo:
                    self.sstate[b] = "pending"
            for o, st in self.sstate.items():      # an unrelated button: the waiting one is a normal press
                if st == "pending" and o != b and o in pressed and not self._related(o, b):
                    self.sstate[o] = "passed"
                    acts.append(("down", self.solo[o]))
        for b in self.prev - pressed:
            self.since.pop(b, None)
            self.tainted.discard(b)
            for held in (self.hold_on, self.dbl_on):
                if b in held:
                    acts.append(("up", held.pop(b)))
            st = self.sstate.pop(b, None)
            if st == "passed":
                acts.append(("up", self.solo[b]))
            elif st == "pending":
                d = self.doubles.get(b)
                if d and b in self.last and (now - self.last[b]) * 1000 <= d[0]:
                    self.sstate[b] = "wait2"       # maybe the first half of a double tap
                else:
                    acts.append(("tap", self.solo[b]))
        ok = [i for i, (btns, _) in enumerate(self.combos) if btns <= pressed]
        want = {i for i in ok if not any(self.combos[j][0] > self.combos[i][0] for j in ok)}
        for i in [i for i in self.active if i not in want]:
            acts.append(("up", self.active.pop(i)))
        for i in sorted(want - set(self.active)):
            self.active[i] = self.combos[i][1]
            acts.append(("down", self.combos[i][1]))
            self.presses += 1
        for i in want:
            self.tainted |= self.combos[i][0]
            for b in self.combos[i][0]:
                if self.sstate.get(b) == "pending":
                    self.sstate[b] = "used"
        for b, (ms, pvk) in self.holds.items():
            if b in pressed and b not in self.hold_on and b not in self.tainted \
                    and (now - self.since.get(b, now)) * 1000 >= ms:
                self.hold_on[b] = pvk
                acts.append(("down", pvk))
                self.presses += 1
                if self.sstate.get(b) == "pending":
                    self.sstate[b] = "used"
        for b, st in list(self.sstate.items()):
            if st == "pending" and b in pressed and b not in self.holds \
                    and now - self.since.get(b, now) >= HOLD_DELAY:
                self.sstate[b] = "passed"          # held on its own: a normal long press
                acts.append(("down", self.solo[b]))
            elif st == "wait2" and b not in pressed:
                d = self.doubles.get(b)
                if not d or b not in self.last or (now - self.last[b]) * 1000 > d[0]:
                    del self.sstate[b]             # it was a single tap after all
                    acts.append(("tap", self.solo[b]))
        self.prev = set(pressed)
        return acts


class XInput:
    """Read Xbox-style controllers (and PlayStation pads through Steam Input / DS4Windows) on Windows."""

    def __init__(self):
        self.ok = False
        if not IS_WINDOWS:
            return
        from ctypes import wintypes as wt
        from .keys import PAD_BY_BIT

        class GAMEPAD(ctypes.Structure):
            _fields_ = [("wButtons", wt.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                        ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                        ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]

        class STATE(ctypes.Structure):
            _fields_ = [("dwPacketNumber", wt.DWORD), ("Gamepad", GAMEPAD)]

        self._STATE, self._bits = STATE, PAD_BY_BIT
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = ctypes.WinDLL(name)
                self.ok = True
                break
            except OSError:
                continue

    def pressed(self) -> set:
        """Controller buttons held right now on any connected controller."""
        out = set()
        if not self.ok:
            return out
        for i in range(4):
            st = self._STATE()
            if self.dll.XInputGetState(i, ctypes.byref(st)) != 0:
                continue
            g = st.Gamepad
            out |= {ik for bit, ik in self._bits.items() if g.wButtons & bit}
            if g.bLeftTrigger > 100:
                out.add("IK_Pad_LeftTrigger")
            if g.bRightTrigger > 100:
                out.add("IK_Pad_RightTrigger")
        return out

    def connected(self) -> bool:
        if not self.ok:
            return False
        return any(self.dll.XInputGetState(i, ctypes.byref(self._STATE())) == 0 for i in range(4))


class ComboHelper:
    def __init__(self, game_exe: str = "witcher3.exe", block_modifiers: bool = True):
        self.game_exe = game_exe.lower()
        self.block_modifiers = block_modifiers
        self.engine = ComboEngine({}, {}, {})
        self.timed = TimedEngine({})
        self.pad = PadEngine([], {}, {})
        self.kb_combos: dict[int, list[tuple[frozenset, int]]] = {}
        self.mouse_combos: dict[tuple[int, int], list[tuple[frozenset, int]]] = {}  # (downmsg, xbtn)
        self.wheel_combos: dict[int, list[tuple[frozenset, int]]] = {}              # +1 / -1
        self.held: dict[object, int] = {}
        self.thread: Optional[threading.Thread] = None
        self.thread_id = 0
        self.running = False
        self.error: Optional[str] = None
        self.log_path: Optional[str] = None     # where start-up problems are written (set by the app)
        self.game_elevated = False              # game window in front belongs to an admin process
        self.test_hwnds: set = set()            # extra windows treated as "the game" (Test my combos)
        self.events_seen = 0
        self._fg_cache: tuple[int, bool] = (0, False)
        self.presses = 0

    # ---------- configuration ----------
    def set_combos(self, proxies: dict[str, str], hide: Optional[dict] = None) -> None:
        """proxies: combo -> spare IK key; hide: combo -> keep the held keys from the game
        (missing combos use self.block_modifiers)."""
        hide = hide or {}
        kb, ms, wh = {}, {}, {}
        timed: dict = {}
        pad_combos, pad_holds, pad_doubles, pad_solo = [], {}, {}, {}
        for c, proxy_ik in proxies.items():
            try:
                combo = Combo.parse(c)
            except ValueError:
                continue
            pvk = _vk(proxy_ik)
            if pvk is None or not combo.is_chord:
                continue
            hide_it = bool(hide.get(c, self.block_modifiers))
            if combo.is_pad and combo.kind == "press" and not combo.mods:
                pad_solo[combo.key] = pvk          # a hidden button's own actions
                continue
            if combo.is_pad:
                if combo.kind == "hold":
                    pad_holds[combo.key] = (combo.ms, pvk)
                elif combo.kind == "double":
                    pad_doubles[combo.key] = (combo.ms, pvk)
                else:
                    pad_combos.append((frozenset(combo.mods) | {combo.key}, pvk))
                continue
            if combo.kind != "press":
                src = _token(combo.key)
                src = src[1] if isinstance(src, tuple) and src[0] == "k" else src
                if src is None or isinstance(src, str):
                    continue
                cfg = timed.setdefault(src, {"hide": False})
                cfg[combo.kind] = (combo.ms, pvk)
                cfg["hide"] = cfg["hide"] or hide_it
                continue
            toks = frozenset(filter(None, (_token(m) for m in combo.mods)))
            if len(toks) != len(combo.mods):
                continue
            entry = (toks, pvk, hide_it)
            if combo.key in _MOUSE:
                down, _, xb = _MOUSE[combo.key]
                ms.setdefault((down, xb), []).append(entry)
            elif combo.key in ("IK_MouseWheelUp", "IK_MouseWheelDown"):
                wh.setdefault(1 if combo.key == "IK_MouseWheelUp" else -1, []).append(entry)
            else:
                vk = _vk(combo.key)
                if vk is not None:
                    kb.setdefault(vk, []).append(entry)
        self.kb_combos, self.mouse_combos, self.wheel_combos = kb, ms, wh
        self.engine = ComboEngine(kb, ms, wh)
        self.timed = TimedEngine(timed)
        self.pad = PadEngine(pad_combos, pad_holds, pad_doubles, pad_solo)

    @property
    def has_combos(self) -> bool:
        return bool(self.kb_combos or self.mouse_combos or self.wheel_combos)

    # ---------- lifecycle ----------
    def start(self) -> bool:
        if not IS_WINDOWS:
            self.error = "The combo helper only works on Windows."
            return False
        if self.running:
            return True
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True, name="ComboHelper")
        self.thread.start()
        ready.wait(5)
        return self.running

    def stop(self) -> None:
        if self.running and self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
            if self.thread:
                self.thread.join(2)
        self.running = False

    # ---------- Win32 plumbing ----------
    def _log(self, text: str) -> None:
        if self.log_path:
            try:
                from datetime import datetime
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
            except OSError:
                pass

    def _run(self, ready: threading.Event) -> None:
        try:
            self._run_inner(ready)
        except Exception as e:  # never die silently: the app shows this text
            import traceback
            self.error = f"{type(e).__name__}: {e}"
            self._log("combo helper crashed:\n" + traceback.format_exc())
            self.running = False
            ready.set()

    def _run_inner(self, ready: threading.Event) -> None:
        from ctypes import wintypes as wt
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        LRESULT = ctypes.c_ssize_t
        ULONG_PTR = ctypes.c_size_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

        class KBDLL(ctypes.Structure):
            _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MSLL(ctypes.Structure):
            _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wt.DWORD), ("u", _U)]

        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
        user32.SetWindowsHookExW.restype = wt.HHOOK
        user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.MapVirtualKeyW.restype = wt.UINT
        user32.GetForegroundWindow.restype = wt.HWND
        user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        kernel32.OpenProcess.restype = wt.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        kernel32.GetModuleHandleW.restype = wt.HMODULE

        def send_key(vk: int, up: bool) -> None:
            flags = 0x0002 if up else 0  # KEYEVENTF_KEYUP
            if vk in _EXTENDED_VK:
                flags |= 0x0001
            inp = INPUT(type=1)
            inp.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0), flags, 0, 0)
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        def game_in_front() -> bool:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            if hwnd in self.test_hwnds:
                return True
            if self._fg_cache[0] == hwnd:
                return self._fg_cache[1]
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            ok = False
            h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                n = wt.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    ok = os.path.basename(buf.value).lower() == self.game_exe
                kernel32.CloseHandle(h)
            if ok:  # an admin game can't be seen by a normal app's keyboard hook
                h2 = kernel32.OpenProcess(0x0400, False, pid.value)  # PROCESS_QUERY_INFORMATION
                self.game_elevated = not h2 and ctypes.get_last_error() == 5 and not is_admin()
                if h2:
                    kernel32.CloseHandle(h2)
            self._fg_cache = (hwnd, ok)
            return ok

        def mods_down() -> frozenset:
            m = set()
            if user32.GetAsyncKeyState(0x11) & 0x8000:
                m.add("Ctrl")
            if user32.GetAsyncKeyState(0x10) & 0x8000:
                m.add("Shift")
            if user32.GetAsyncKeyState(0x12) & 0x8000:
                m.add("Alt")
            return frozenset(m)

        _MBTN = {0x0201: (0x0002, 0x0004), 0x0204: (0x0008, 0x0010), 0x0207: (0x0020, 0x0040),
                 0x020B: (0x0080, 0x0100)}

        def send_mouse(btn, up: bool) -> None:
            msg, xb = btn
            dn, upf = _MBTN[msg]
            inp = INPUT(type=0)
            inp.mi = MOUSEINPUT(0, 0, xb if msg == 0x020B else 0, upf if up else dn, 0, 0)
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        def perform(actions) -> None:
            for a in actions:
                if a[0] == "mdown":
                    send_mouse(a[1], False)
                elif a[0] == "mup":
                    send_mouse(a[1], True)
                elif a[0] == "mtap":
                    send_mouse(a[1], False)
                    threading.Timer(0.03, send_mouse, args=(a[1], True)).start()
                elif a[0] == "down":
                    send_key(a[1], False)
                elif a[0] == "up":
                    send_key(a[1], True)
                elif a[0] == "tap":  # short press: give the game a frame to notice it
                    send_key(a[1], False)
                    threading.Timer(0.03, send_key, args=(a[1], True)).start()
                elif a[0] == "timer":
                    src, gen = a[1], a[2]
                    threading.Timer(HOLD_DELAY, lambda: perform(self.engine.timeout(src, gen))).start()
                elif a[0] == "ttimer":
                    src, gen, kind = a[1], a[2], a[3]
                    threading.Timer(a[4], lambda: perform(
                        self.timed.timeout(src, gen, kind, time.monotonic()))).start()
            self.presses = self.engine.presses + self.timed.presses + self.pad.presses

        def timed_takes(src, mods) -> bool:
            t = self.timed
            return t.owns(src) and (t.busy(src) or not self.engine.claims(src, mods))

        def route_key(vk, down, in_game, mods):
            if timed_takes(vk, mods):
                extra = self.engine.flush() if down and in_game else []
                sw, acts = self.timed.event(vk, down, in_game, time.monotonic())
                return sw, extra + acts
            return self.engine.key(vk, down, in_game, mods)

        def route_mouse(msg, xb, down, in_game, mods):
            src = ("m", msg, xb)
            if timed_takes(src, mods):
                extra = self.engine.flush() if down and in_game else []
                sw, acts = self.timed.event(src, down, in_game, time.monotonic())
                return sw, extra + acts
            return self.engine.mouse_button(msg, xb, down, in_game, mods)

        def pad_loop():
            xi = XInput()
            if not xi.ok:
                self._log("controller combos: XInput not available")
                return
            while self.running:
                if self.pad.empty:
                    time.sleep(0.25)
                    continue
                try:
                    perform(self.pad.update(xi.pressed(), game_in_front(), time.monotonic()))
                except Exception as e:  # keep the keyboard side alive whatever happens here
                    self._log(f"controller polling error: {e}")
                    time.sleep(1)
                time.sleep(0.008)
            perform(self.pad.update(set(), False, time.monotonic()))

        def kb_proc(nCode, wParam, lParam):
            if nCode == 0:
                k = ctypes.cast(lParam, ctypes.POINTER(KBDLL)).contents
                if not (k.flags & 0x10):  # ignore injected events (including our own)
                    self.events_seen += 1
                    down = wParam in (0x0100, 0x0104)
                    if down or wParam in (0x0101, 0x0105):
                        swallow, acts = route_key(k.vkCode, down, game_in_front(), mods_down())
                        perform(acts)
                        if swallow:
                            return 1
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        def mouse_proc(nCode, wParam, lParam):
            if nCode == 0 and wParam != 0x0200:  # ignore plain mouse movement
                m = ctypes.cast(lParam, ctypes.POINTER(MSLL)).contents
                if not (m.flags & 0x01):
                    hi = (m.mouseData >> 16) & 0xFFFF
                    swallow, acts = False, []
                    if wParam == 0x020A:  # wheel
                        delta = ctypes.c_short(hi).value
                        swallow, acts = self.engine.wheel_turn(1 if delta > 0 else -1, game_in_front(), mods_down())
                    elif wParam in (0x0201, 0x0204, 0x0207, 0x020B):
                        xb = hi if wParam == 0x020B else 0
                        swallow, acts = route_mouse(wParam, xb, True, game_in_front(), mods_down())
                    elif wParam in (0x0202, 0x0205, 0x0208, 0x020C):
                        xb = hi if wParam == 0x020C else 0
                        swallow, acts = route_mouse(wParam - 1, xb, False, game_in_front(), mods_down())
                    perform(acts)
                    if swallow:
                        return 1
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._kb_cb = HOOKPROC(kb_proc)   # keep references alive
        self._ms_cb = HOOKPROC(mouse_proc)
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
        kh = mh = None
        errors = []
        # Different Windows setups accept different module handles for low-level hooks: try each.
        for hmod in (kernel32.GetModuleHandleW(None), kernel32.GetModuleHandleW("user32.dll"), None):
            kh = user32.SetWindowsHookExW(13, self._kb_cb, hmod, 0)  # WH_KEYBOARD_LL
            if kh:
                mh = user32.SetWindowsHookExW(14, self._ms_cb, hmod, 0)  # WH_MOUSE_LL
                break
            errors.append(ctypes.get_last_error())
        if not kh:
            code = errors[-1] if errors else 0
            why = {5: "Windows or your security software refused it (access denied). Try running W3 KeyBinder "
                      "as administrator, or allow it in your antivirus.",
                   1428: "Windows wanted a module handle and refused all three that were tried.",
                   126: "a Windows module could not be found."}.get(code, "Windows refused it.")
            self.error = f"Could not watch the keyboard: {why} (Windows error {code}; tried {errors})"
            self._log(self.error)
            ready.set()
            return
        self._log(f"combo helper started (mouse hook {'on' if mh else 'off'})")
        self.thread_id = kernel32.GetCurrentThreadId()
        self.running = True
        ready.set()
        threading.Thread(target=pad_loop, daemon=True, name="ComboHelperPad").start()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        perform(self.engine.release_all() + self.timed.release_all())
        user32.UnhookWindowsHookEx(kh)
        if mh:
            user32.UnhookWindowsHookEx(mh)
        self.running = False


def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restart_as_admin(args: str = "") -> bool:
    """Start this program again with administrator rights (Windows asks the user). True if it started."""
    import sys
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, args
    else:
        exe, params = sys.executable, f'-m w3keybinder {args}'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return r > 32


def set_autostart(enabled: bool, command: str) -> None:
    """Start W3 KeyBinder (minimised, helper on) when Windows starts."""
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, "W3KeyBinder", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(k, "W3KeyBinder")
            except FileNotFoundError:
                pass


def get_autostart() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "W3KeyBinder")
            return True
    except OSError:
        return False
