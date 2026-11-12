"""Scan mod folders for keybinding information.

Two kinds of evidence are collected:

* **Snippets** - text files (README, ``*.txt``, ``input.settings`` parts...) that contain
  ``[Context]`` headers followed by ``IK_Key=(Action=...)`` lines: the lines a mod author tells you to
  paste into input.settings. They give the context and default key.
* **Script actions** - ``.ws`` scripts calling ``theInput.RegisterListener(this, 'OnX', 'ActionName')``
  or ``IsActionPressed('ActionName')``. Many mods ship edited copies of the game's own scripts, so any
  action the *vanilla* scripts already use is ignored; only genuinely new mod actions are kept.
"""
from __future__ import annotations

import json
import os
from collections import Counter
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import settings_file as sf
from .groups import MenuVar, parse_vars

TEXT_EXTS = {".txt", ".settings", ".ini", ".md", ".cfg", ".readme", ".input", ".text", ".xml", ""}
MAX_TEXT_BYTES = 2 * 1024 * 1024
FULL_FILE_THRESHOLD = 400  # more entries than this = someone's whole input.settings, not a snippet
SKIP_NAMES = {"user.settings", "dx12user.settings", "mods.settings", "dx11filelist.txt",
              "dx12filelist.txt"}

_Q = r"['\"]"
LISTENER_RE = re.compile(r"RegisterListener\s*\(\s*[^,()]+,\s*" + _Q + r"(\w+)" + _Q + r"\s*,\s*" + _Q + r"(\w+)"
                         + _Q + r"\s*\)")
INPUT_BUILDER_RE = re.compile(r"builder\s*=\s*['\"]Input['\"]", re.I)
_NAME_RE = re.compile(r"['\"](\w{3,})['\"]")
ACTION_QUERY_RE = re.compile(
    r"\b(?:IsActionPressed|IsActionJustPressed|IsActionReleased|IsActionJustReleased|GetActionValue)"
    r"\s*\(\s*['\"](\w+)['\"]")


@dataclass
class Snippet:
    mod: str          # mod folder name
    path: str
    entries: list[tuple[str, sf.Entry]]
    manual: bool = False

    @property
    def id(self) -> str:
        return self.path


@dataclass
class ScriptAction:
    mod: str
    action: str
    path: str
    shared: bool = False   # a game action the mod also reacts to (e.g. "hold Dodge to blink")


@dataclass
class ScanResult:
    mods: list[str] = field(default_factory=list)            # mod folders found
    disabled_mods: list[str] = field(default_factory=list)   # disabled in mods.settings (skipped)
    snippets: list[Snippet] = field(default_factory=list)
    script_actions: list[ScriptAction] = field(default_factory=list)
    vanilla_actions: set[str] = field(default_factory=set)
    menu_vars: list[MenuVar] = field(default_factory=list)   # keybinding rows from input.xml files
    script_names: dict[str, set[str]] = field(default_factory=dict)  # mod -> every quoted name in its scripts
    # (mod, action, other action): checked as alternatives, e.g. IsActionPressed('SNSneak') || IsActionPressed('DiveDown')
    alternatives: set[tuple[str, str, str]] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def parse_snippet_text(text: str, mod: str, path: str, manual: bool = False) -> Optional[Snippet]:
    doc = sf.parse_text(text)
    entries = list(doc.iter_entries())
    if not entries:
        return None
    return Snippet(mod, path, entries, manual)


def read_disabled_mods(settings_dir: Optional[Path]) -> set[str]:
    """mods.settings (next to input.settings) can switch mods off with Enabled=0."""
    out: set[str] = set()
    if not settings_dir:
        return out
    p = settings_dir / "mods.settings"
    if not p.exists():
        return out
    try:
        text, _ = sf.read_text_any(p)
    except OSError:
        return out
    current = None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            current = m.group(1).strip()
        elif current and re.match(r"^Enabled\s*=\s*0\s*(?:[;#/].*)?$", line, re.I):
            out.add(current.lower())
    return out


def _actions_in(text: str) -> list[str]:
    return [m.group(2) for m in LISTENER_RE.finditer(text)] + [m.group(1) for m in ACTION_QUERY_RE.finditer(text)]


def vanilla_script_actions(game_dir: Optional[Path], cache_file: Optional[Path] = None) -> set[str]:
    """Every action name the unmodded game scripts use (content/content0/scripts)."""
    if not game_dir:
        return set()
    root = game_dir / "content" / "content0" / "scripts"
    if not root.is_dir():
        return set()
    files = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if fn.lower().endswith(".ws"):
                p = os.path.join(dp, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                files.append((p, st.st_size, int(st.st_mtime)))
    sig = f"{root}|{len(files)}|{sum(f[1] for f in files)}|{max((f[2] for f in files), default=0)}"
    if cache_file and cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if data.get("sig") == sig:
                return set(data["actions"])
        except (OSError, ValueError, KeyError):
            pass
    acts: set[str] = set()
    for p, _, _ in files:
        try:
            text, _ = sf.read_text_any(p)
        except OSError:
            continue
        acts.update(_actions_in(text))
    if cache_file:
        try:
            cache_file.write_text(json.dumps({"sig": sig, "actions": sorted(acts)}), encoding="utf-8")
        except OSError:
            pass
    return acts


_PRESS_RE = re.compile(r"(!?)\s*theInput\s*\.\s*(?:IsActionPressed|IsActionJustPressed|GetActionValue)"
                       r"\s*\(\s*['\"](\w+)['\"]")


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments but keep quoted strings and line breaks intact, so a
    commented-out RegisterListener doesn't count and "http://..." inside a string isn't cut."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))  # keep line numbers stable
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


_STATEMENT_SPLIT = re.compile(r"[;{}]")


def _alternatives(text: str) -> set[tuple[str, str]]:
    """Pairs of actions a script accepts as either-or in one condition: A || B (neither negated).
    Works per statement, so conditions spread over several lines are seen whole."""
    out: set[tuple[str, str]] = set()
    for line in _STATEMENT_SPLIT.split(text):
        if "||" not in line:
            continue
        terms = []
        for part in line.split("||"):
            found = _PRESS_RE.findall(part)
            if len(found) == 1 and not found[0][0]:
                terms.append(found[0][1])
        for a in terms:
            for b in terms:
                if a != b:
                    out.add((a, b))
    return out


def _added_script_text(p: Path, game_dir: Optional[Path]) -> str:
    """The part of a mod script that the mod wrote. Mods often ship an edited copy of a game script;
    then only the lines that differ from the game's own copy count."""
    text = strip_comments(sf.read_text_any(p)[0])
    parts = [x.lower() for x in p.parts]
    if game_dir and "scripts" in parts:
        rel = p.parts[len(parts) - parts[::-1].index("scripts"):]
        orig = game_dir / "content" / "content0" / "scripts" / Path(*rel)
        if orig.is_file():
            try:
                vtext, _ = sf.read_text_any(orig)
            except OSError:
                return text
            # Count lines rather than just checking presence, so a mod that adds a second copy of a
            # line the game already has (e.g. another RegisterListener for 'Dodge') is still seen.
            left = Counter(ln.strip() for ln in strip_comments(vtext).splitlines())
            added = []
            for ln in text.splitlines():
                k = ln.strip()
                if left[k] > 0:
                    left[k] -= 1
                else:
                    added.append(ln)
            return "\n".join(added)
    return text


def _mod_roots(game_dir: Optional[Path], extra_dirs: Iterable[str], disabled: set[str],
               res: ScanResult) -> list[tuple[str, Path, bool]]:
    roots: list[tuple[str, Path, bool]] = []
    if game_dir:
        for sub in ("mods", "dlc"):
            d = game_dir / sub
            if not d.is_dir():
                continue
            for child in sorted(d.iterdir(), key=lambda p: p.name.lower()):
                if not child.is_dir():
                    continue
                if sub == "mods" and child.name.lower() in disabled:
                    res.disabled_mods.append(child.name)
                    continue
                if sub == "mods":
                    res.mods.append(child.name)
                roots.append((child.name, child, False))
    for extra in extra_dirs:
        d = Path(extra)
        if d.is_dir():
            roots.append((d.name, d, True))
    return roots


def game_menu_vars(game_dir: Optional[Path]) -> list[MenuVar]:
    """Rows of the in-game Key Bindings menu: input.xml plus any mod .xml next to it (next-gen style)."""
    out: list[MenuVar] = []
    if not game_dir:
        return out
    d = game_dir / "bin" / "config" / "r4game" / "user_config_matrix" / "pc"
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.xml"), key=lambda x: (x.name.lower() != "input.xml", x.name.lower())):
        try:
            text, _ = sf.read_text_any(p)
        except OSError:
            continue
        if not INPUT_BUILDER_RE.search(text):
            continue
        mod = None if p.name.lower() == "input.xml" else p.stem
        out += parse_vars(text, mod, str(p))
    return out


def _is_mod_folder(name: str, parent: str) -> bool:
    low = name.lower()
    return parent.lower() in ("mods", "dlc") or (low.startswith("mod") and low != "mods")


def _owner(root: Path, rel: tuple) -> str:
    """Which mod owns a file in an extra folder (e.g. extracted downloads).
    "Unseen v1.2/mods/modSneak/..." -> modSneak; loose files in "Unseen v1.2/" (its readme) also go
    to modSneak when that download holds exactly one mod; otherwise the top folder's name."""
    if not rel:
        return root.name
    for i, part in enumerate(rel):
        parent = rel[i - 1] if i else ""
        if _is_mod_folder(part, parent) and part.lower() not in ("mods", "dlc"):
            return part
    top = root / rel[0]
    inner = _single_mod_inside(top)
    return inner or rel[0]


_SINGLE_CACHE: dict = {}


def _single_mod_inside(top: Path) -> Optional[str]:
    key = str(top)
    if key not in _SINGLE_CACHE:
        found = set()
        for sub in ("mods", "dlc", ""):
            d = top / sub if sub else top
            try:
                for c in d.iterdir():
                    if c.is_dir() and _is_mod_folder(c.name, sub) and c.name.lower() not in ("mods", "dlc"):
                        found.add(c.name)
            except OSError:
                pass
        mods = {f for f in found if not f.lower().startswith("dlc")} or found
        _SINGLE_CACHE[key] = next(iter(mods)) if len(mods) == 1 else None
    return _SINGLE_CACHE[key]


def scan(game_dir: Optional[Path], extra_dirs: Iterable[str] = (), settings_dir: Optional[Path] = None,
         cache_file: Optional[Path] = None) -> ScanResult:
    res = ScanResult()
    _SINGLE_CACHE.clear()
    res.vanilla_actions = vanilla_script_actions(game_dir, cache_file)
    res.menu_vars = game_menu_vars(game_dir)
    disabled = read_disabled_mods(settings_dir)
    seen_snip_paths: set[str] = set()
    seen_snip_sigs: set[tuple] = set()
    seen_actions: set[tuple[str, str]] = set()
    for mod_name, root, is_extra in _mod_roots(game_dir, list(extra_dirs), disabled, res):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            rel_parts = Path(dirpath).relative_to(root).parts
            owner = _owner(root, rel_parts) if is_extra else mod_name
            for fn in filenames:
                p = Path(dirpath) / fn
                ext = p.suffix.lower()
                if fn.lower() in SKIP_NAMES:
                    continue
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if ext == ".ws":
                    if owner.lower().startswith("mod0000_"):
                        continue  # Script Merger output: copies of other mods' changes
                    try:
                        text = _added_script_text(p, game_dir)
                    except OSError:
                        continue
                    res.script_names.setdefault(owner, set()).update(_NAME_RE.findall(text))
                    res.alternatives |= {(owner, x, y) for x, y in _alternatives(text)}
                    for action in _actions_in(text):
                        if (owner, action) in seen_actions:
                            continue
                        seen_actions.add((owner, action))
                        res.script_actions.append(ScriptAction(owner, action, str(p),
                                                               shared=action in res.vanilla_actions))
                elif ext in TEXT_EXTS and size <= MAX_TEXT_BYTES:
                    sp = str(p)
                    if sp in seen_snip_paths:
                        continue
                    try:
                        text, _ = sf.read_text_any(p)
                    except OSError as e:
                        res.warnings.append(f"Could not read {p}: {e}")
                        continue
                    if INPUT_BUILDER_RE.search(text):
                        res.menu_vars += parse_vars(text, owner, sp)
                    if "IK_" not in text:
                        continue
                    snip = parse_snippet_text(text, owner, sp)
                    if not snip:
                        continue
                    if len(snip.entries) > FULL_FILE_THRESHOLD:
                        res.warnings.append(
                            f"Skipped {p}: it looks like a complete input.settings ({len(snip.entries)} lines), "
                            "not a mod's keybind lines.")
                        continue
                    seen_snip_paths.add(sp)
                    sig = (owner, tuple((c, e.key, e.params) for c, e in snip.entries))
                    if sig in seen_snip_sigs:
                        continue  # same lines in the readme and in a .txt: count them once
                    seen_snip_sigs.add(sig)
                    res.snippets.append(snip)
    return res
