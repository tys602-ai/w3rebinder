"""Locating the game install, the Documents folder and the app's own data folder."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "W3KeyBinder"


def documents_dir() -> Path:
    """Real Documents folder (handles OneDrive / relocated Documents on Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                       (wintypes.BYTE * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0:
                p = Path(ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                return p
        except Exception:
            pass
    return Path.home() / "Documents"


def default_settings_path() -> Path:
    return documents_dir() / "The Witcher 3" / "input.settings"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    d = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _is_game_dir(p: Path) -> bool:
    return (p / "bin" / "x64" / "witcher3.exe").exists() or (p / "bin" / "x64_dx12" / "witcher3.exe").exists() \
        or ((p / "content").is_dir() and (p / "bin").is_dir())


def _steam_libraries() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key in [(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")]:
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots.append(Path(r"C:\Program Files (x86)\Steam"))
    else:
        roots += [Path.home() / ".steam" / "steam", Path.home() / ".local" / "share" / "Steam"]
    libs: list[Path] = []
    for r in roots:
        libs.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            try:
                for m in re.finditer(r'"path"\s*"([^"]+)"', vdf.read_text(errors="replace")):
                    libs.append(Path(m.group(1).replace("\\\\", "\\")))
            except OSError:
                pass
    return libs


def find_game_dirs() -> list[Path]:
    cands: list[Path] = []
    for lib in _steam_libraries():
        cands.append(lib / "steamapps" / "common" / "The Witcher 3")
    if sys.platform == "win32":
        try:
            import winreg
            for gid in ("1495134320", "1207664663", "1640424747"):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\GOG.com\Games\{gid}") as k:
                        cands.append(Path(winreg.QueryValueEx(k, "path")[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for drive in "CDEFG":
            cands += [Path(f"{drive}:/GOG Games/The Witcher 3 Wild Hunt GOTY"),
                      Path(f"{drive}:/GOG Games/The Witcher 3 Wild Hunt"),
                      Path(f"{drive}:/Program Files (x86)/GOG Galaxy/Games/The Witcher 3 Wild Hunt GOTY"),
                      Path(f"{drive}:/Program Files/Epic Games/TheWitcher3"),
                      Path(f"{drive}:/SteamLibrary/steamapps/common/The Witcher 3")]
    seen, out = set(), []
    for c in cands:
        try:
            key = str(c.resolve()).lower()
        except OSError:
            continue
        if key not in seen and c.is_dir() and _is_game_dir(c):
            seen.add(key)
            out.append(c)
    return out


def guess_game_dir() -> Optional[Path]:
    found = find_game_dirs()
    return found[0] if found else None
