"""Plain-text report of what was found, to send when something is missing."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import __version__
from .model import ActionInfo
from .names import friendly_mod
from .scanner import ScanResult


def build_report(settings_path: str, game_dir: str, entry_count: int, scan: ScanResult,
                 catalog: dict[str, ActionInfo], helper=None) -> str:
    out = [f"W3 KeyBinder {__version__} report, {datetime.now():%Y-%m-%d %H:%M}",
           f"input.settings: {settings_path} ({entry_count} lines read)",
           f"Game folder: {game_dir or '(not set)'}",
           f"Game scripts found: {'yes' if scan.vanilla_actions else 'NO'} ({len(scan.vanilla_actions)} game actions)",
           f"Key menu rows read from input.xml files: {len(scan.menu_vars)}",
           f"Mods folders: {len(scan.mods)}   Disabled in mods.settings: {', '.join(scan.disabled_mods) or 'none'}"]
    if helper is not None:
        out.append(f"Combo helper: {'running' if helper.running else 'NOT running'}"
                   + (f" - {helper.error}" if helper.error else "")
                   + (" - game runs as administrator" if helper.game_elevated else ""))
        if helper.log_path and Path(helper.log_path).exists():
            out.append("Combo helper log (last lines):")
            out += ["   " + l for l in
                    Path(helper.log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-15:]]
    out.append("")
    mods = sorted(set(scan.mods) | {m for r in catalog.values() for m in r.all_mods}, key=str.lower)
    for m in mods:
        snips = [s for s in scan.snippets if s.mod == m]
        own = sorted({a.action for a in scan.script_actions if a.mod == m and not a.shared})
        shared = sorted({a.action for a in scan.script_actions if a.mod == m and a.shared})
        rows = [r for r in catalog.values() if m in r.all_mods]
        out.append(f"== {friendly_mod(m)}  [{m}]")
        out.append(f"   keybind text files: {', '.join(Path(s.path).name for s in snips) or 'none'}")
        out.append(f"   own actions in scripts: {', '.join(own[:40]) or 'none'}")
        if shared:
            out.append(f"   game actions it reacts to: {', '.join(shared[:20])}")
        for r in rows:
            state = "shown" if r.in_menu else "hidden"
            how = "shares game key" if m in r.shared_mods else "own"
            out.append(f"   - {r.name}: {', '.join(r.keys) or 'no key in input.settings'}  "
                       f"({how}, {state}; actions: {', '.join(r.members[:5])})")
        if not rows:
            out.append("   (no keybinds found for this mod)")
        out.append("")
    hidden = [r for r in catalog.values() if not r.in_menu and r.keys]
    out.append("Hidden actions that have a key (Options > Show advanced):")
    out += [f"   - {r.action}: {', '.join(r.keys)}" for r in sorted(hidden, key=lambda r: r.action.lower())]
    return "\n".join(out) + "\n"
