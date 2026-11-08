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

    def release_all(self) -> list:
        with self.lock:
            acts = [("up", pvk) for pvk in self.held.values()]
            for src, st in self.state.items():
                if st[1] == "passed":
                    acts.append(("mup", src[1:]) if isinstance(src, tuple) else ("up", src))
            self.held.clear()
            self.state.clear()
            return acts


class ComboHelper:
    def __init__(self, game_exe: str = "witcher3.exe", block_modifiers: bool = True):
        self.game_exe = game_exe.lower()
        self.block_modifiers = block_modifiers
        self.engine = ComboEngine({}, {}, {})
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
        for c, proxy_ik in proxies.items():
            try:
                combo = Combo.parse(c)
            except ValueError:
                continue
            pvk = _vk(proxy_ik)
            toks = frozenset(filter(None, (_token(m) for m in combo.mods)))
            if pvk is None or not combo.mods or len(toks) != len(combo.mods):
                continue
            entry = (toks, pvk, bool(hide.get(c, self.block_modifiers)))
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
            self.presses = self.engine.presses

        def kb_proc(nCode, wParam, lParam):
            if nCode == 0:
                k = ctypes.cast(lParam, ctypes.POINTER(KBDLL)).contents
                if not (k.flags & 0x10):  # ignore injected events (including our own)
                    self.events_seen += 1
                    down = wParam in (0x0100, 0x0104)
                    if down or wParam in (0x0101, 0x0105):
                        swallow, acts = self.engine.key(k.vkCode, down, game_in_front(), mods_down())
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
                        swallow, acts = self.engine.mouse_button(wParam, xb, True, game_in_front(), mods_down())
                    elif wParam in (0x0202, 0x0205, 0x0208, 0x020C):
                        xb = hi if wParam == 0x020C else 0
                        swallow, acts = self.engine.mouse_button(wParam - 1, xb, False, game_in_front(), mods_down())
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
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        perform(self.engine.release_all())
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
