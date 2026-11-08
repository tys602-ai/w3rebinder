"""What one row in the list is.

The game's own Key Bindings menu (bin/config/r4game/user_config_matrix/pc/input.xml) groups many
input.settings actions into one binding: "Interact" alone covers ~75 actions (Talk, Open, Loot...),
"Jump" covers Jump/Roll/HorseJump, and so on. We show exactly those rows, so changing "Interact"
moves all of them together. Mods add their own rows to input.xml (or ship them as text to paste).

VANILLA_ROWS is a built-in copy of the base game's rows so grouping works even if input.xml can't be read.
Entries are action names, or "Action|Value" for one half of an axis.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import settings_file as sf

# (row id, friendly name, category, actions)
VANILLA_ROWS = [
    ('PauseGameToggle', 'Pause game', 'Menus & interface', ['PauseGameToggle']),
    ('quickLoad', 'Quick load', 'Menus & interface', ['QuickLoad']),
    ('MoveFwd', 'Move forward', 'Movement', ['MoveForward', 'MovementDoubleTapW', 'ChangeChoiceUp', 'GI_AxisLeftY|1']),
    ('MoveBck', 'Move backward', 'Movement', ['MoveBackward', 'MovementDoubleTapS', 'ChangeChoiceDown', 'GI_Decelerate', 'GI_AxisLeftY|-1']),
    ('MoveLft', 'Move left', 'Movement', ['MoveLeft', 'MovementDoubleTapA', 'GI_AxisLeftX|-1']),
    ('MoveRght', 'Move right', 'Movement', ['MoveRight', 'MovementDoubleTapD', 'GI_AxisLeftX|1']),
    ('Sprint', 'Sprint', 'Movement', ['Sprint']),
    ('SprintToggle', 'Sprint (toggle)', 'Movement', ['SprintToggle']),
    ('WalkToggle', 'Walk / run toggle', 'Movement', ['WalkToggle']),
    ('JumpRoll', 'Jump / roll', 'Movement', ['Jump', 'ExplorationInteraction', 'Roll', 'HorseJump']),
    ('CameraLock', 'Lock on target', 'Combat', ['CameraLock']),
    ('Interaction', 'Interact / activate', 'Movement', ['PickOilLamp', 'PlaceOilLamp', 'PlaceCrystal', 'SitDown', 'Knock', 'Spare', 'Unequip', 'FastTravel', 'GatherHerbs', 'Examine', 'EnterBoat', 'EnterBoatFromSwimming', 'MountHorse', 'Talk', 'Container', 'Interact', 'InteractHold', 'Use', 'UseDevice', 'Open', 'Close', 'Lock', 'Unlock', 'Take', 'Push', 'Pull', 'Locked', 'Finisher', 'Destroy', 'PrayForSun', 'PrayForStorm', 'Arm', 'Disarm', 'GatherBrushwood', 'PlaceHerbs', 'Drink', 'PlaceOffering', 'Grab', 'Free', 'Ignite', 'UnblockGate', 'UseItem', 'Read', 'PullAxe', 'Interaction', 'Extinguish', 'CallJohnny', 'HideBible', 'SitAndWait', 'PlaceBottle', 'WineSlot', 'BurnBody', 'PutBack', 'Debung', 'Touch', 'CutRope', 'KneelDown', 'PlaceTribute', 'HangPainting', 'PlaceArmor', 'PlaceSword', 'GiveAlms', 'PlaceLure', 'PlaceBeans', 'Stash', 'Look', 'TakePaintGreen', 'TakePaintBlue', 'TakePaintRed', 'TakePaintYellow', 'TakePaintPurple', 'DisposePaint', 'HideIn', 'PlaceTrophy']),
    ('gatherHerbs', 'Gather herbs from horseback', 'Horse', ['GatherHerbsHorse']),
    ('AttackLight', 'Fast attack', 'Combat', ['AttackWithAlternateLight', 'SpecialAttackWithAlternateLight', 'Finish', 'Finisher', 'VehicleAttack']),
    ('AttackHeavy', 'Strong attack', 'Combat', ['AttackWithAlternateHeavy', 'SpecialAttackWithAlternateHeavy', 'CiriAttackHeavy', 'CiriSpecialAttackHeavy']),
    ('AttackWithAlternate', 'Strong attack modifier', 'Combat', ['PCAlternate']),
    ('LockAndGuard', 'Block / parry', 'Combat', ['LockAndGuard']),
    ('Dodge', 'Dodge', 'Combat', ['Dodge', 'CiriDodge']),
    ('CbtRoll', 'Roll (combat)', 'Combat', ['CbtRoll', 'CiriDash']),
    ('ThrowItem', 'Use quick item (bomb / crossbow)', 'Combat', ['ThrowItem', 'ThrowItemHold', 'VehicleItemAction', 'VehicleItemActionHold']),
    ('Focus', 'Witcher Senses', 'Movement', ['Focus']),
    ('CastSign', 'Cast sign', 'Signs', ['CastSign', 'CastSignHold', 'VehicleCastSign', 'CiriSpecialAttack']),
    ('ToggleSigns', 'Next sign', 'Signs', ['ToggleSigns']),
    ('SpawnHorse', 'Call horse', 'Horse', ['SpawnHorse']),
    ('GallopCanter', 'Gallop / canter', 'Horse', ['Gallop', 'Canter']),
    ('StopHorse', 'Stop horse', 'Horse', ['Stop']),
    ('HorseDismount', 'Dismount', 'Horse', ['HorseDismount', 'BoatDismount']),
    ('DiveUp', 'Swim up', 'Swimming & boat', ['DiveUp']),
    ('DiveDown', 'Dive', 'Swimming & boat', ['DiveDown']),
    ('DrinkPotion1', 'Potion slot 1', 'Combat', ['DrinkPotion1']),
    ('DrinkPotion2', 'Potion slot 2', 'Combat', ['DrinkPotion2']),
    ('DrinkPotion3', 'Potion slot 3', 'Combat', ['DrinkPotion3']),
    ('DrinkPotion4', 'Potion slot 4', 'Combat', ['DrinkPotion4']),
    ('SteelSword', 'Steel sword', 'Combat', ['SteelSword', 'SwordSheatheSteel', 'CiriDrawWeapon']),
    ('SilverSword', 'Silver sword', 'Combat', ['SilverSword', 'SwordSheatheSilver', 'CiriDrawWeaponAlternative']),
    ('SwitchCrossbow', 'Switch quick item', 'Combat', ['SwitchCrossbow']),
    ('SelectAard', 'Select Aard', 'Signs', ['SelectAard']),
    ('SelectIgni', 'Select Igni', 'Signs', ['SelectIgni']),
    ('SelectYrden', 'Select Yrden', 'Signs', ['SelectYrden']),
    ('SelectQuen', 'Select Quen', 'Signs', ['SelectQuen']),
    ('SelectAxii', 'Select Axii', 'Signs', ['SelectAxii']),
    ('ToggleHud', 'Show / hide HUD', 'Menus & interface', ['ToggleHud']),
    ('Toggle3DMarkers', 'Show / hide 3D markers', 'Menus & interface', ['Toggle3DMarkers']),
    ('ToggleEssentials', 'Show / hide essential HUD', 'Menus & interface', ['ToggleEssentials']),
    ('HoldToSeeEssentials', 'Hold to see essential HUD', 'Menus & interface', ['HoldToSeeEssentials']),
    ('HoldToSeeCharStats', 'Hold to see character stats', 'Menus & interface', ['HoldToSeeCharStats']),
    ('HoldToSeeMap', 'Hold to see minimap', 'Menus & interface', ['HoldToSeeMap']),
    ('HoldToSeeQuests', 'Hold to see objectives', 'Menus & interface', ['HoldToSeeQuests']),
    ('PinModuleModfier', 'Pin HUD module', 'Menus & interface', ['PinModuleModfier']),
    ('ChangeQuest', 'Change tracked objective', 'Menus & interface', ['HighlightObjective', 'TrackQuest']),
    ('RadialMenu', 'Quick access menu', 'Menus & interface', ['RadialMenu']),
    ('ActiveQuickSlot', 'Switch quick slot set', 'Menus & interface', ['ToggleQuickSlotsActiveSet']),
    ('HubMenu', 'Game menu', 'Menus & interface', ['HubMenu']),
    ('PanelChar', 'Character panel', 'Menus & interface', ['PanelChar']),
    ('PanelInv', 'Inventory', 'Menus & interface', ['PanelInv']),
    ('quickInv', 'Quick inventory', 'Menus & interface', ['QuickInventory']),
    ('Stash', 'Stash', 'Menus & interface', ['OpenStash']),
    ('PanelMap', 'Map', 'Menus & interface', ['PanelMapPC']),
    ('PanelJour', 'Journal', 'Menus & interface', ['PanelJour']),
    ('PanelMeditation', 'Meditation', 'Menus & interface', ['PanelMeditation']),
    ('PanelAlch', 'Alchemy', 'Menus & interface', ['PanelAlch']),
    ('PanelCraft', 'Crafting', 'Menus & interface', ['PanelCrafting']),
    ('PanelBestiary', 'Bestiary', 'Menus & interface', ['PanelBestiary']),
    ('PanelGlossary', 'Glossary', 'Menus & interface', ['PanelGlossary']),
    ('PanelGwintDeckEditor', 'Gwent deck', 'Menus & interface', ['PanelGwintDeckEditor']),
    ('SwordSheathe', 'Sheathe sword', 'Combat', ['SwordSheathe']),
    ('FastMenu', 'Quick menu', 'Menus & interface', ['FastMenu', 'HoldFastMenu']),
    ('GotoGlossary', 'Open glossary entry', 'Menus & interface', ['GotoGlossary']),
    ('OpenMeditation', 'Meditate (open)', 'Menus & interface', ['OpenMeditation']),
    ('Follow', 'Horse: follow road', 'Horse', ['Follow']),
]
VANILLA_IDS = {r[0] for r in VANILLA_ROWS}
VANILLA_ACTIONS = {a.split("|")[0] for r in VANILLA_ROWS for a in r[3]}


@dataclass
class MenuVar:
    id: str
    display: str
    actions: list[str]
    mod: Optional[str] = None     # mod folder name when known
    path: str = ""
    name: str = ""                # friendly name if known
    category: str = ""


_VAR_RE = re.compile(r"<Var\b([^>]*?)/?>", re.S)
_ATTR_RE = re.compile(r"""(\w+)\s*=\s*(["'])(.*?)\2""", re.S)


def parse_vars(text: str, mod: Optional[str] = None, path: str = "") -> list[MenuVar]:
    """All keybinding rows (<Var builder="Input" ... actions="a;b"/>) in an input.xml or a mod's snippet."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out = []
    for m in _VAR_RE.finditer(text):
        a = {k: v for k, _q, v in _ATTR_RE.findall(m.group(1))}
        if a.get("builder", "").lower() != "input" or not a.get("actions") or not a.get("id"):
            continue
        acts = [x.strip() for x in a["actions"].split(";") if x.strip()]
        out.append(MenuVar(a["id"], a.get("displayName", a["id"]), acts, mod, path))
    return out


def vanilla_vars() -> list[MenuVar]:
    return [MenuVar(i, i, list(acts), None, "", n, c) for i, n, c, acts in VANILLA_ROWS]


def display_name(v: MenuVar) -> str:
    """Best readable name for a row from input.xml."""
    from .names import FRIENDLY, humanize
    if v.name:
        return v.name
    d = v.display.strip()
    if " " in d and not d.startswith("Mods."):
        return d  # plain-text names some mods use, e.g. "Head Gear/Cape Toggle"
    if len(v.actions) == 1 and v.actions[0] in FRIENDLY:
        return FRIENDLY[v.actions[0]]
    if v.display.lower().startswith("keybind_"):
        return humanize(v.display[8:])
    # mods usually put a translation key in displayName ("ft_key"); the id reads better
    return humanize(v.id)
