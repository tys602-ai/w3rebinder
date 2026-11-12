"""Human-friendly names and categories for Witcher 3 input actions.

Unknown action names fall back to a readable version of the raw name ("SpawnHorse" -> "Spawn horse"),
so a name missing here is never shown wrong, just plainer.
"""
from __future__ import annotations

import re
from typing import Optional

# Exact action name (or "Action|Value" for the two halves of an axis) -> friendly name
FRIENDLY = {
    "GI_AxisLeftY|1": "Move forward", "GI_AxisLeftY|-1": "Move backward",
    "GI_AxisLeftX|1": "Move right", "GI_AxisLeftX|-1": "Move left",
    "GI_AxisLeftY|1.0": "Move forward", "GI_AxisLeftY|-1.0": "Move backward",
    "GI_AxisLeftX|1.0": "Move right", "GI_AxisLeftX|-1.0": "Move left",
    "Sprint": "Sprint", "SprintToggle": "Sprint (toggle)", "WalkToggle": "Walk / run toggle",
    "Walk": "Walk", "Jump": "Jump", "Dodge": "Dodge", "CbtRoll": "Roll", "Roll": "Roll",
    "Interact": "Interact", "InteractHold": "Interact (hold)",
    "AttackLight": "Fast attack", "AttackHeavy": "Strong attack", "AttackWithAlternateLight": "Fast attack (alternate)",
    "AttackWithAlternateHeavy": "Strong attack (alternate)", "SpecialAttackLight": "Whirl (special fast attack)",
    "SpecialAttackHeavy": "Rend (special strong attack)", "LockAndGuard": "Block / parry", "Guard": "Block / parry",
    "Parry": "Parry", "CameraLock": "Lock on target", "CameraLockOrSpawnHorse": "Lock on target / call horse",
    "SpawnHorse": "Call horse", "HorseDismount": "Get off horse", "HorseJump": "Horse jump",
    "Canter": "Horse canter", "Gallop": "Horse gallop", "HorseStop": "Horse stop",
    "CastSign": "Cast sign", "CastSignHold": "Cast sign (alternate / hold)",
    "SelectAard": "Select Aard", "SelectYrden": "Select Yrden", "SelectIgni": "Select Igni",
    "SelectQuen": "Select Quen", "SelectAxii": "Select Axii",
    "ThrowItem": "Throw bomb / shoot crossbow", "ThrowItemHold": "Aim bomb / crossbow", "UseItem": "Use item",
    "DrinkPotion1": "Drink potion 1", "DrinkPotion2": "Drink potion 2", "DrinkPotion3": "Drink potion 3",
    "DrinkPotion4": "Drink potion 4", "DrinkPotionUpperHeld": "Drink potion (upper)",
    "DrinkPotionLowerHeld": "Drink potion (lower)",
    "SteelSword": "Draw / sheathe steel sword", "SilverSword": "Draw / sheathe silver sword",
    "SwordSheathe": "Sheathe sword",
    "Focus": "Witcher Senses", "FocusMode": "Witcher Senses", "Medallion": "Medallion",
    "HighlightObjective": "Highlight objective", "ToggleHud": "Show / hide HUD",
    "RadialMenu": "Quick access menu", "HubMenu": "Game menu", "IngameMenu": "Pause menu",
    "PanelInv": "Open inventory", "PanelMap": "Open map", "PanelJour": "Open journal", "PanelChar": "Open character",
    "PanelAlch": "Open alchemy", "PanelCrafting": "Open crafting", "PanelBestiary": "Open bestiary",
    "PanelGlossary": "Open glossary", "PanelMeditation": "Meditate", "PanelGwintDeckEditor": "Open Gwent deck",
    "PanelFakeHud": "Hide HUD", "QuickSave": "Quick save", "QuickLoad": "Quick load",
    "Screenshot": "Screenshot", "PhotoMode": "Photo mode",
    "Diving": "Dive", "DiveUp": "Swim up", "DiveDown": "Dive down", "Swim": "Swim",
    "BoatForward": "Boat forward", "BoatBackward": "Boat backward", "BoatDismount": "Leave boat",
    "SkipCutscene": "Skip cutscene", "SkipDialog": "Skip dialogue",
}

_CATEGORY_ORDER = ["Movement", "Combat", "Signs", "Horse", "Swimming & boat", "Camera",
                   "Menus & interface", "Other"]


def category_order() -> list[str]:
    return list(_CATEGORY_ORDER)


def humanize(raw: str) -> str:
    """'SpawnHorse' -> 'Spawn horse', 'mod_quick_loot' -> 'Mod quick loot', 'HUDToggle' -> 'HUD toggle'."""
    s = raw.replace("_", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z])(?=[0-9])", " ", s)
    words = s.split()
    out = []
    for i, w in enumerate(words):
        out.append(w if (w.isupper() and len(w) > 1) or i == 0 else w.lower())
    r = " ".join(out)
    return r[:1].upper() + r[1:]


def friendly_action(action: str, value: Optional[str]) -> str:
    key = f"{action}|{value}" if value is not None else action
    if key in FRIENDLY:
        return FRIENDLY[key]
    base = action[3:] if action.startswith("GI_") else action
    # mods often prefix their actions with 2 capitals of the mod name: SNSneak -> Sneak
    m = re.match(r"^[A-Z]{2}_?([A-Z][a-z].*)$", base)
    if m:
        base = m.group(1)
    name = FRIENDLY.get(action) or humanize(base)
    if value is not None:
        name += f" ({'+' if not value.startswith('-') else ''}{value})"
    return name


def friendly_mod(folder: str) -> str:
    """'modFriendlyHUD' -> 'Friendly HUD', 'mod_quick_loot' -> 'Quick loot'."""
    if folder in ("(input.xml)", "(input.settings)"):
        return "Unknown mod"
    if folder.lower().startswith("mod0000_mergedfiles"):
        return "Script Merger merged files"
    name = folder
    if re.match(r"^mod[A-Z_\-0-9]", name):
        name = name[3:]
    elif name.lower().startswith("mod_"):
        name = name[4:]
    name = name.strip("_- ")
    return humanize(name) if name else folder


_GAMEPLAY_CTX = ("exploration", "combat", "horse", "swim", "boat", "diving", "replacer", "fistfight", "jump",
                 "climb", "ciri", "aim", "throw", "sail")


def category(action: str, contexts: list[str]) -> str:
    a = action.lower()
    ctx = [c.lower() for c in contexts]
    if any(s in a for s in ("sign", "aard", "igni", "quen", "yrden", "axii")):
        return "Signs"
    if "horse" in a or a in ("canter", "gallop") or (ctx and all("horse" in c for c in ctx)):
        return "Horse"
    if any(s in a for s in ("boat", "swim", "dive", "diving", "sail")) or \
            (ctx and all(any(w in c for w in ("boat", "swim", "diving")) for c in ctx)):
        return "Swimming & boat"
    if a.startswith(("panel", "menu", "hub", "hud", "quicksave", "quickload", "ingame", "gwint", "gwent",
                     "screenshot", "photo")) or "menu" in a or "hud" in a or \
            (ctx and not any(any(g in c for g in _GAMEPLAY_CTX) for c in ctx)):
        return "Menus & interface"
    if a.startswith("gi_axisleft") or any(s in a for s in ("sprint", "walk", "jump", "run", "climb", "crouch",
                                                            "move", "interact")):
        return "Movement"
    if a.startswith("gi_axisright") or "camera" in a or "zoom" in a or "focus" in a:
        return "Camera" if "focus" not in a else "Other"
    if any(s in a for s in ("attack", "guard", "parry", "counter", "lock", "sword", "dodge", "roll", "cbt",
                            "throw", "bomb", "crossbow", "potion", "useitem", "item")):
        return "Combat"
    return "Other"
