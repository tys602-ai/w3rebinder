"""Small amount of remembered state, saved as JSON in %APPDATA%\\W3KeyBinder."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .keys import DEFAULT_PROXY_POOL


@dataclass
class Profile:
    game_dir: str = ""
    settings_path: str = ""
    extra_scan_dirs: list[str] = field(default_factory=list)
    # combo ("Ctrl+Q") -> spare IK key it is written as in input.settings ("IK_F13")
    proxies: dict[str, str] = field(default_factory=dict)
    proxy_pool: list[str] = field(default_factory=lambda: list(DEFAULT_PROXY_POOL))
    # actions the user has set in this app: mod snippet lines are no longer auto-added for these
    user_set: list[str] = field(default_factory=list)
    # advanced: action id -> contexts it should be bound in
    contexts: dict[str, list[str]] = field(default_factory=dict)
    disabled_snippets: list[str] = field(default_factory=list)
    manual_snippets: list[dict] = field(default_factory=list)  # {"name": str, "text": str}
    game_exe: str = "witcher3.exe"
    show_no_keyboard: bool = False
    theme: str = "dark"
    block_modifiers: bool = True  # default for new combos: hide the held key(s) from the game
    # combo -> hide its held key(s) from the game while it is pressed (per combo; default above)
    combo_hide: dict[str, bool] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> "Profile":
        p = Profile()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(p, k):
                    setattr(p, k, v)
        return p

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
