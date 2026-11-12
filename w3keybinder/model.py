"""Rows (one per binding, like the in-game Key Bindings menu) and the compiler that writes input.settings.

* The user's *current* input.settings is the source of truth.
* Mod keybind lines missing from it are merged in.
* A row groups every action that shares one binding (e.g. "Interact" = Talk, Open, Loot, ...).
  Changing a row swaps the old key for the new one on all of those lines, keeping each line's
  context and parameters. Removing a key writes IK_None, the same as the game does.
* Key combos (Ctrl+Q ...) are written as a spare "proxy" key that the combo helper presses.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from . import settings_file as sf
from .game_actions import GAME_ACTION_CONTEXTS, GAME_ACTIONS
from .groups import VANILLA_ACTIONS, VANILLA_IDS, MenuVar, display_name, vanilla_vars
from .keys import MODIFIER_IK, NONE_KEY, Combo, is_kbm, is_pad_button, label, mod_label, pad_label
from .names import category, friendly_action, friendly_mod
from .profile import Profile
from .scanner import ScanResult, Snippet, parse_snippet_text

DEFAULT_NEW_CONTEXTS = ["Exploration"]
MAX_SHARED_KEYS = 2  # more game keys than this = an overhaul mod, not a keybind feature
_COMBO = "COMBO:"  # placeholder key prefix while compiling


@dataclass
class ActionInfo:
    """One row in the list = one binding."""
    id: str
    name: str
    members: list[str]                                   # action ids ("Talk", "GI_AxisLeftY|1")
    category: str = "Other"
    mods: list[str] = field(default_factory=list)        # mod folder names
    keys: list[str] = field(default_factory=list)        # current keyboard/mouse keys (combo strings)
    pad_keys: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)    # where it has keyboard/mouse lines
    all_contexts: list[str] = field(default_factory=list)
    variants: dict[str, list[str]] = field(default_factory=dict)  # (single-action rows) ctx -> params
    in_base: bool = False        # present in the current input.settings
    from_snippet: bool = False   # some lines come from a mod snippet not yet in the file
    script_only: bool = False    # only found in mod scripts
    in_menu: bool = False        # a row of the game's key menu, or a mod's binding
    shared_mods: list[str] = field(default_factory=list)  # mods that also react to this game binding
    via: list[str] = field(default_factory=list)   # "Dive (C)": the game key this mod action works through
    via_rows: list[str] = field(default_factory=list)  # ids of those game rows
    borrowed: list[str] = field(default_factory=list)  # [sections] where a mod added this game action's key
    only_contexts: list[str] = field(default_factory=list)    # edits touch only these [sections]
    except_contexts: list[str] = field(default_factory=list)  # edits never touch these [sections]
    borrow_of: str = ""          # for a mod's use of a game key: the game row it borrows from
    pad: list[str] = field(default_factory=list)            # controller buttons (IK_Pad_...) we can rebind
    pad_contexts: list[str] = field(default_factory=list)   # [sections] with controller buttons
    stick: str = ""              # "Left stick"/"Right stick" for movement and camera rows (not rebindable)
    optional: bool = False       # only seen in a mod's script, no line anywhere: probably an optional extra

    @property
    def is_mod(self) -> bool:
        return bool(self.mods)

    @property
    def all_mods(self) -> list[str]:
        return self.mods + [m for m in self.shared_mods if m not in self.mods]

    @property
    def mod_names(self) -> list[str]:
        return [friendly_mod(m) for m in self.mods]

    @property
    def action(self) -> str:
        return self.members[0].split("|")[0] if self.members else ""

    @property
    def value(self) -> Optional[str]:
        return self.members[0].split("|")[1] if self.members and "|" in self.members[0] else None


def all_snippets(scan: ScanResult, profile: Profile) -> list[Snippet]:
    out = list(scan.snippets)
    for i, m in enumerate(profile.manual_snippets):
        s = parse_snippet_text(m.get("text", ""), m.get("name") or f"Manual {i + 1}", f"manual:{i}", manual=True)
        if s:
            out.append(s)
    return out


def solo_buttons(proxies: dict) -> dict:
    """{controller button: spare key} for buttons whose own actions the helper sends ("Pad LB": F20)."""
    out = {}
    for c, proxy in proxies.items():
        try:
            combo = Combo.parse(c)
        except ValueError:
            continue
        if combo.is_pad and combo.kind == "press" and not combo.mods:
            out[combo.key] = proxy
    return out


def hidden_pad_buttons(combos, profile: Profile) -> list:
    """Controller buttons used in combo / hold / double-tap bindings that have 'hide' switched on."""
    out = []
    for c in combos:
        try:
            combo = Combo.parse(c)
        except ValueError:
            continue
        if combo.is_pad and (combo.mods or combo.kind != "press") \
                and profile.combo_hide.get(c, profile.block_modifiers):
            for b in sorted(set(combo.mods) | {combo.key}):
                if b not in out:
                    out.append(b)
    return out


def merged_doc(current: sf.SettingsDoc, scan: ScanResult, profile: Profile) -> tuple[sf.SettingsDoc, set[str]]:
    """Current file + mod lines it is missing. Returns (doc, action ids that got lines added)."""
    doc = current.clone()
    # Controller buttons hidden for a combo are stored under a spare key ("Pad LB" -> F20) and sent by
    # the helper. Read them back as the real button, so everything else sees a normal controller binding.
    solo = solo_buttons(profile.proxies)
    if solo:
        back = {proxy: btn for btn, proxy in solo.items()}
        for _, e in doc.iter_entries():
            if e.key in back:
                e.key = back[e.key]
    present = {(ctx, e.action_id) for ctx, e in current.iter_entries()}
    added: set[str] = set()
    for snip in all_snippets(scan, profile):
        if snip.id in profile.disabled_snippets:
            continue
        for ctx, e in snip.entries:
            aid = e.action_id
            if not aid or e.marked_for_removal or aid in profile.user_set or (ctx, aid) in present:
                continue
            name = aid.split("|")[0]
            if name in VANILLA_ACTIONS or name in GAME_ACTIONS or name in scan.vanilla_actions:
                continue  # never let a mod's readme change the game's own controls
            if doc.add(ctx, sf.Entry(e.key, e.params)):
                added.add(aid)
    return doc, added


@dataclass
class _Stats:
    keys: Counter = field(default_factory=Counter)
    pad: list = field(default_factory=list)
    ctx_kbm: list = field(default_factory=list)
    ctx_all: list = field(default_factory=list)
    variants: dict = field(default_factory=dict)
    by_ctx: dict = field(default_factory=dict)   # context -> keyboard/mouse keys there, in order
    pad_ctx: dict = field(default_factory=dict)  # context -> controller buttons there, in order


def _action_stats(doc: sf.SettingsDoc, rev: dict[str, str]) -> dict[str, _Stats]:
    st: dict[str, _Stats] = {}
    for ctx, e in doc.iter_entries():
        aid = e.action_id
        if not aid:
            continue
        s = st.setdefault(aid, _Stats())
        if ctx not in s.ctx_all:
            s.ctx_all.append(ctx)
        if is_kbm(e.key) or e.key == NONE_KEY:
            v = s.variants.setdefault(ctx, [])
            if e.params not in v:
                v.append(e.params)
        if is_kbm(e.key):
            s.keys[rev.get(e.key) or label(e.key)] += 1
            lst = s.by_ctx.setdefault(ctx, [])
            if (rev.get(e.key) or label(e.key)) not in lst:
                lst.append(rev.get(e.key) or label(e.key))
            if ctx not in s.ctx_kbm:
                s.ctx_kbm.append(ctx)
        elif e.key != NONE_KEY and e.key not in s.pad:
            s.pad.append(e.key)
        if is_pad_button(e.key):
            lst = s.pad_ctx.setdefault(ctx, [])
            if e.key not in lst:
                lst.append(e.key)
    return st


def _row_keys(s: _Stats) -> list[str]:
    return [k for k, _ in s.keys.most_common()]


def build_catalog(current: sf.SettingsDoc, scan: ScanResult, profile: Profile) -> dict[str, ActionInfo]:
    doc, added = merged_doc(current, scan, profile)
    rev = {v: k for k, v in profile.proxies.items()}
    stats = _action_stats(doc, rev)
    base_ids = {e.action_id for _, e in current.iter_entries() if e.action_id}

    # ---- which actions belong to which row ----
    menu: list[MenuVar] = []
    seen_var: dict[str, MenuVar] = {}
    for v in vanilla_vars() + list(scan.menu_vars):
        if v.id in seen_var:
            old = seen_var[v.id]
            old.actions += [a for a in v.actions if a not in old.actions]
            if v.mod and not old.mod and v.id not in VANILLA_IDS:
                old.mod = v.mod
            continue
        seen_var[v.id] = v
        menu.append(v)
    by_name: dict[str, list[str]] = defaultdict(list)
    for aid in stats:
        by_name[aid.split("|")[0].lower()].append(aid)
    by_id_lower = {aid.lower(): aid for aid in stats}
    claimed: dict[str, str] = {}
    rows: dict[str, ActionInfo] = {}
    for v in menu:
        members: list[str] = []
        for spec in v.actions:
            if "|" in spec:
                ids = [by_id_lower.get(spec.lower(), spec)]
            else:  # names are matched ignoring capitals, like the game does
                ids = by_name.get(spec.lower()) or [spec]
            for aid in ids:
                # the plain action name only claims un-valued ids (axis halves are claimed explicitly)
                if "|" in aid and "|" not in spec and aid.split("|")[0].startswith("GI_"):
                    continue
                if aid not in claimed and aid not in members:
                    members.append(aid)
        members = [m for m in members if m not in claimed]
        if not members:
            continue
        rid = "row:" + v.id
        for m in members:
            claimed[m] = rid
        mods = [v.mod] if v.mod else []
        if v.id not in VANILLA_IDS and not v.mod:
            names = {m.split("|")[0] for m in members}
            if scan.vanilla_actions:
                game_row = names <= scan.vanilla_actions
            else:  # game scripts not found: rows already bound in the file are probably the game's
                game_row = any(m in base_ids for m in members)
            if not game_row:
                mods = ["(input.xml)"]  # a mod's row; replaced by the real mod below if found
        rows[rid] = ActionInfo(rid, display_name(v), members, v.category or "", mods, in_menu=True)

    # leftovers: one row per action
    for aid in stats:
        if aid not in claimed:
            claimed[aid] = "act:" + aid
            a, _, val = aid.partition("|")
            rows["act:" + aid] = ActionInfo("act:" + aid, friendly_action(a, val or None), [aid])
    # Unknown interaction actions (e.g. added in a patch) that are bound exactly like Interact join it.
    mod_mentioned = {n for names in scan.script_names.values() for n in names}
    mod_mentioned |= {e.action for sn in all_snippets(scan, profile) for _, e in sn.entries if e.action}
    inter = rows.get("row:Interaction")
    if inter:
        ref = next((stats[m] for m in inter.members if m in stats and stats[m].keys), None)
        if ref:
            sig = (set(ref.keys), set(ref.pad))
            for rid in [r for r in rows if r.startswith("act:")]:
                aid = rows[rid].members[0]
                s = stats[aid]
                name = aid.split("|")[0]
                if name in mod_mentioned:
                    continue  # a mod's own action that happens to be on E: keep it as its own row
                if name not in VANILLA_ACTIONS and (set(s.keys), set(s.pad)) == sig and s.keys:
                    inter.members.append(aid)
                    claimed[aid] = inter.id
                    del rows[rid]

    # ---- mod attribution ----
    snippet_game_rows: dict[str, set[str]] = defaultdict(set)
    for snip in all_snippets(scan, profile):
        if snip.id in profile.disabled_snippets:
            continue
        for _, e in snip.entries:
            if e.marked_for_removal:
                continue
            rid = claimed.get(e.action_id)
            if rid and _is_game_row(rows[rid], scan):
                snippet_game_rows[snip.mod].add(rid)  # a game action in the mod's lines: "shared"
                continue
            if rid and snip.mod not in rows[rid].mods:
                rows[rid].mods.append(snip.mod)
                if "(input.xml)" in rows[rid].mods:
                    rows[rid].mods.remove("(input.xml)")
    known_names = {aid.split("|")[0] for aid in claimed}
    rid_by_name = {aid.split("|")[0]: rid for aid, rid in claimed.items()}
    # A mod that hangs a feature on one or two game keys (Elder Blink: hold Dodge) is worth showing.
    # A mod that reacts to many game controls (movement/combat overhauls) adds no keybind of its own.
    shared_rows: dict[str, set[str]] = defaultdict(set)
    def countable(rid: Optional[str], action: str) -> bool:
        # movement axes are read by every movement-related mod: never a "feature key"
        return bool(rid) and rid.startswith("row:") and not rid.startswith("row:Move") \
            and not action.startswith("GI_")
    for mod, rids in snippet_game_rows.items():
        shared_rows[mod] |= {r for r in rids if countable(r, "")}
    for sa in scan.script_actions:
        rid = claimed.get(sa.action) or rid_by_name.get(sa.action)
        if _is_shared(sa) and countable(rid, sa.action):
            shared_rows[sa.mod].add(rid)
    for sa in scan.script_actions:
        rid = claimed.get(sa.action) or rid_by_name.get(sa.action)
        if _is_shared(sa):
            continue
        if sa.action in known_names and rid and _is_game_row(rows[rid], scan):
            continue
        if sa.action in known_names:
            if rid and sa.mod not in rows[rid].mods:
                rows[rid].mods.append(sa.mod)
                if "(input.xml)" in rows[rid].mods:
                    rows[rid].mods.remove("(input.xml)")
            continue
        known_names.add(sa.action)
        rid = "act:" + sa.action
        rows[rid] = ActionInfo(rid, friendly_action(sa.action, None), [sa.action], mods=[sa.mod], script_only=True)
        claimed[sa.action] = rid

    # Game keys a mod accepts as an alternative to its own action are its real feature keys.
    alt_rows: dict[str, set[str]] = defaultdict(set)
    for mod, a, b in scan.alternatives:
        if a not in GAME_ACTIONS and a not in scan.vanilla_actions and _is_game_name(b, scan):
            rid = claimed.get(b) or rid_by_name.get(b)
            if countable(rid, b):
                alt_rows[mod].add(rid)
    for mod, rids in alt_rows.items():
        shared_rows[mod] = set(rids)
    for mod, rids in shared_rows.items():
        if len(rids) <= MAX_SHARED_KEYS:
            for rid in rids:
                if mod not in rows[rid].shared_mods and mod not in rows[rid].mods:
                    rows[rid].shared_mods.append(mod)

    # ---- fill in keys/contexts ----
    for row in rows.values():
        primary = next((m for m in row.members if m in stats and stats[m].keys), None)
        if primary:
            row.keys = _row_keys(stats[primary])
        for m in row.members:
            s = stats.get(m)
            if not s:
                continue
            for p in s.pad:
                if p not in row.pad_keys:
                    row.pad_keys.append(p)
            for c in s.ctx_kbm:
                if c not in row.contexts:
                    row.contexts.append(c)
            for c in s.ctx_all:
                if c not in row.all_contexts:
                    row.all_contexts.append(c)
        first = row.members[0]
        if len(row.members) == 1 and first in stats:
            row.variants = stats[first].variants
        row.in_base = any(m in base_ids for m in row.members)
        row.from_snippet = any(m in added for m in row.members)
        if row.mods:
            row.in_menu = True
        if not row.category:
            row.category = category(row.action, row.all_contexts)
        if row.mods and "(input.xml)" in row.mods and len(row.mods) > 1:
            row.mods.remove("(input.xml)")
        # An action in your input.settings that the game itself never uses was put there for a mod
        # (e.g. IK_C=(Action=Sneak)). Show it, and find the mod whose scripts mention its name.
        if (row.id.startswith("act:") and not row.mods and row.in_base and (row.keys or row.variants)
                and not is_game_action(row.action, scan)):
            owners = sorted(m for m, names in scan.script_names.items() if row.action in names)
            row.mods = owners or ["(input.settings)"]
            row.in_menu = True
        if row.script_only and not row.in_base:
            row.optional = True
        if row.id.startswith("act:") and len(row.action) <= 2:
            row.in_menu = False  # e.g. Bootstrap's typing keys (Action=a, Action=3): not real keybinds
        if row.all_contexts and all(re.match(r"(?i)mod_?ui", c) for c in row.all_contexts):
            row.in_menu = False  # keys that only work inside a mod's own text boxes
    # Game actions bound in sections the unmodded game doesn't use them in were added there by a mod
    # (Unseen puts Dive on C under [Exploration] and [Combat] so C sneaks on land).
    for row in rows.values():
        if len(row.members) == 1:
            home = GAME_ACTION_CONTEXTS.get(row.action)
            if home and row.shared_mods:
                row.borrowed = [c for c in row.contexts if c not in home]

    # A mod action with no keyboard key that the same mod also triggers from a game key
    # (Unseen: SNSneak is on the controller, the keyboard uses Dive on C) - but only while that
    # game key is actually bound where the mod action works.
    for row in rows.values():
        if row.mods and not row.keys:
            alts = {b for (m, a, b) in scan.alternatives if m in row.mods and a == row.action}
            for r in rows.values():
                if not (r.keys and any(m in r.shared_mods for m in row.mods)
                        and alts & {x.split("|")[0] for x in r.members}):
                    continue
                if row.all_contexts and not set(row.all_contexts) & set(r.contexts):
                    continue  # e.g. Dive's C was taken off land: it no longer sneaks
                row.via.append(f"{r.name} ({', '.join(r.keys)})")
                row.via_rows.append(r.id)

    # Split a game key a mod borrowed into its own row, so the two can be changed independently:
    # "Sneak with Dive's key" = C on foot/in combat (Unseen's), "Dive" = C in water (the game's).
    for r in [r for r in rows.values() if r.borrowed]:
        s_ = stats.get(r.members[0])
        if not s_:
            continue
        def keys_in(ctxs):
            out = []
            for c in ctxs:
                for k in s_.by_ctx.get(c, []):
                    if k not in out:
                        out.append(k)
            return out
        users = [m for m in rows.values() if r.id in m.via_rows]
        mods = list(dict.fromkeys(r.shared_mods))
        if users:
            name = f"{users[0].name} with {r.name}'s key"
        else:
            name = f"{r.name} key used by {', '.join(friendly_mod(m) for m in mods)}"
        bid = "borrow:" + r.id
        rows[bid] = ActionInfo(
            bid, name, list(r.members), category=r.category, mods=mods, keys=keys_in(r.borrowed),
            contexts=list(r.borrowed), all_contexts=list(r.borrowed),
            variants={c: v for c, v in r.variants.items() if c in r.borrowed},
            in_base=True, in_menu=True, only_contexts=list(r.borrowed), borrow_of=r.id)
        home = [c for c in r.contexts if c not in r.borrowed]
        r.keys = keys_in(home)
        r.contexts = home
        r.all_contexts = [c for c in r.all_contexts if c not in r.borrowed]
        r.variants = {c: v for c, v in r.variants.items() if c not in r.borrowed}
        r.except_contexts = list(r.borrowed)
        r.shared_mods = [m for m in r.shared_mods if m not in mods]
        for u in users:  # the mod's own action now works through the split-off row
            for i, rid in enumerate(u.via_rows):
                if rid == r.id:
                    u.via_rows[i] = bid
                    u.via[i] = f"{r.name}'s key ({', '.join(rows[bid].keys)})"
    # controller buttons per row, limited to the row's own sections (split rows keep theirs apart).
    # The row shows the buttons of the action its keyboard key comes from (else its first action with a
    # button), so e.g. a dialogue-menu button grouped into "Move forward" doesn't stand in for the row.
    for row in rows.values():
        per_member = {}
        for m in row.members:
            s_ = stats.get(m)
            if not s_:
                continue
            btns = []
            for c, bs in s_.pad_ctx.items():
                if (row.only_contexts and c not in row.only_contexts) or c in row.except_contexts:
                    continue
                if c not in row.pad_contexts:
                    row.pad_contexts.append(c)
                btns += [b for b in bs if b not in btns]
            per_member[m] = btns
        key_member = next((m for m in row.members if m in stats and stats[m].keys), None)
        stick = ""
        for m in row.members:  # movement/camera rows use a whole stick, e.g. GI_AxisLeftY
            base = stats.get(m.split("|")[0])
            for k in (base.pad if base else []):
                if "LeftAxis" in k:
                    stick = "Left stick"
                elif "RightAxis" in k:
                    stick = "Right stick"
        row.stick = stick
        if stick:
            continue
        if key_member and per_member.get(key_member):
            row.pad = per_member[key_member]
        elif not key_member:
            row.pad = next((b for b in per_member.values() if b), [])
    return rows


def _is_game_name(name: str, scan: ScanResult) -> bool:
    return name in GAME_ACTIONS or name in VANILLA_ACTIONS or name in scan.vanilla_actions


def is_game_action(name: str, scan: ScanResult) -> bool:
    return name in GAME_ACTIONS or name in VANILLA_ACTIONS or name in scan.vanilla_actions


def _is_game_row(row: ActionInfo, scan: ScanResult) -> bool:
    """A binding of the base game itself (not one a mod added)."""
    if row.id.startswith("row:") and row.id[4:] in VANILLA_IDS:
        return True
    return all(m.split("|")[0] in VANILLA_ACTIONS or m.split("|")[0] in scan.vanilla_actions for m in row.members)


def _is_shared(sa) -> bool:
    """The mod reacts to one of the game's own actions (not a new action of its own)."""
    return sa.shared or sa.action in VANILLA_ACTIONS or sa.action in GAME_ACTIONS


def target_contexts(info: ActionInfo, profile: Profile, pending_ctx: Optional[dict] = None) -> list[str]:
    if pending_ctx and info.id in pending_ctx:
        return list(pending_ctx[info.id])
    if info.id in profile.contexts:
        return list(profile.contexts[info.id])
    return list(info.contexts) or list(info.variants) or list(info.all_contexts) or list(DEFAULT_NEW_CONTEXTS)


def who_uses(cat: dict[str, ActionInfo], profile: Profile, key: str, me: ActionInfo,
             pending: dict[str, list[str]], pending_ctx: Optional[dict] = None) -> list[ActionInfo]:
    """Other rows that would share `key` in at least one game situation with `me`."""
    mine = set(target_contexts(me, profile, pending_ctx))
    out = []
    for info in cat.values():
        if info.id == me.id or not info.in_menu:
            continue
        if key in pending.get(info.id, info.keys) and mine & set(target_contexts(info, profile, pending_ctx)):
            out.append(info)
    return out


@dataclass
class CompileResult:
    doc: sf.SettingsDoc
    proxies: dict[str, str]
    conflicts: list[str]
    warnings: list[str]
    changed: int


def _logical(key: str, rev: dict[str, str]) -> str:
    if key.startswith(_COMBO):
        return key[len(_COMBO):]
    return rev.get(key) or label(key)


def compile_settings(current: sf.SettingsDoc, scan: ScanResult, profile: Profile,
                     pending: dict[str, list[str]], pending_ctx: Optional[dict[str, list[str]]] = None,
                     catalog: Optional[dict[str, ActionInfo]] = None,
                     pending_pad: Optional[dict[str, list[str]]] = None) -> CompileResult:
    pending_ctx = pending_ctx or {}
    pending_pad = pending_pad or {}
    doc, _ = merged_doc(current, scan, profile)
    cat = catalog or build_catalog(current, scan, profile)
    warnings: list[str] = []
    rev = {v: k for k, v in profile.proxies.items()}

    for _, e in doc.iter_entries():  # existing proxy lines -> logical combo placeholders
        if e.key in rev:
            e.key = _COMBO + rev[e.key]

    touched = [rid for rid in cat if rid in pending or rid in pending_ctx]
    for rid in touched:
        row = cat[rid]
        new: list[str] = []
        for s in pending.get(rid, row.keys):
            try:
                c = Combo.parse(s)
                new.append(_COMBO + str(c) if c.is_chord else c.key)
            except ValueError as ex:
                warnings.append(f"{row.name}: ignored '{s}' ({ex})")
        old = set(row.keys)
        members = set(row.members)
        replaced: set[str] = set()   # members that got the new keys somewhere
        only = set(row.only_contexts) if row.only_contexts else None
        skip = set(row.except_contexts)
        for sec in doc.sections:
            if (only is not None and sec.name not in only) or sec.name in skip:
                continue
            items: list = []
            for it in sec.items:
                if not (isinstance(it, sf.Entry) and it.action_id in members):
                    items.append(it)
                    continue
                k = it.key
                is_bind = k.startswith(_COMBO) or is_kbm(k)
                hit = (is_bind and _logical(k, rev) in old) or (k == NONE_KEY and not old)
                if not hit:
                    items.append(it)
                    continue
                # a mod's borrowed copy of a game key is simply removed; elsewhere the game writes IK_None
                for nk in (new or ([] if only is not None else [NONE_KEY])):
                    e2 = sf.Entry(nk, it.params)
                    if not any(isinstance(x, sf.Entry) and x.same(e2) for x in items):
                        items.append(e2)
                if new:
                    replaced.add(it.action_id)
            sec.items = items
        # actions with no keyboard line at all yet (new mod actions): add lines where they belong
        if new and len(row.members) == 1 and row.members[0] not in replaced:
            _add_lines(doc, row, new, target_contexts(row, profile, pending_ctx))
        # "Where it works" (single-action rows only)
        if rid in pending_ctx and len(row.members) == 1:
            aid = row.members[0]
            sel = set(pending_ctx[rid])
            for sec in doc.sections:
                if sec.name not in sel:
                    sec.items = [it for it in sec.items if not (isinstance(it, sf.Entry) and it.action_id == aid
                                                                and (is_kbm(it.key) or it.key.startswith(_COMBO)))]
            _add_lines(doc, row, new, sorted(sel))

    # controller buttons: swap the row's old buttons for the new ones on all its lines
    for rid, new_pad in pending_pad.items():
        row = cat.get(rid)
        if row:
            _apply_pad(doc, row, [b for b in new_pad if is_pad_button(b)], profile, pending_ctx)

    # proxies for every combo still in use
    combos_used = sorted({e.key[len(_COMBO):] for _, e in doc.iter_entries() if e.key.startswith(_COMBO)})
    # hidden controller buttons: their own lines move to a spare key that the helper presses for them
    hidden = [b for b in hidden_pad_buttons(combos_used, profile)
              if any(e.key == b for _, e in doc.iter_entries())]
    combos_used += [label(b) for b in hidden]
    plain = {e.key for _, e in doc.iter_entries() if not e.key.startswith(_COMBO)}
    proxies: dict[str, str] = {}
    taken: set[str] = set()
    for c in combos_used:
        p = profile.proxies.get(c)
        if p and p not in plain and p not in taken and p in profile.proxy_pool:
            proxies[c] = p
            taken.add(p)
    free = [k for k in profile.proxy_pool if k not in plain and k not in taken]
    for c in combos_used:
        if c in proxies:
            continue
        if not free:
            warnings.append(f"No spare keys left for {c}. Add more under Options > Spare keys.")
            continue
        proxies[c] = free.pop(0)
    for sec in doc.sections:
        keep = []
        for it in sec.items:
            if isinstance(it, sf.Entry) and it.key.startswith(_COMBO):
                c = it.key[len(_COMBO):]
                if c not in proxies:
                    continue
                it = sf.Entry(proxies[c], it.params)
                if any(isinstance(k, sf.Entry) and k.same(it) for k in keep):
                    continue
            elif isinstance(it, sf.Entry) and it.key in hidden and label(it.key) in proxies:
                it = sf.Entry(proxies[label(it.key)], it.params, it.comment)
            keep.append(it)
        sec.items = keep

    conflicts = _conflicts(cat, profile, pending, pending_ctx, touched)
    for rid, btns in pending_pad.items():
        row = cat.get(rid)
        for b in btns if row else []:
            for o in pad_users(cat, b, row, pending_pad, profile):
                line = f"{pad_label(b)} (controller): {row.name} / {o.name}"
                if f"{pad_label(b)} (controller): {o.name} / {row.name}" not in conflicts:
                    conflicts.append(line)
    for c in proxies:
        combo = Combo.parse(c)
        hide = profile.combo_hide.get(c, profile.block_modifiers)
        for m in combo.mods:
            iks = MODIFIER_IK.get(m, (m,))
            name = mod_label(m)
            users = sorted({r.name for r in cat.values() if r.in_menu and any(
                label(k) in pending.get(r.id, r.keys) for k in iks)})
            if users and not hide:
                warnings.append(f"{c}: {name} on its own is also bound ({', '.join(users[:3])}), so that also "
                                f"happens when you press {c}.")
            elif users:
                warnings.append(f"{c}: {name} on its own is also bound ({', '.join(users[:3])}). The combo helper "
                                f"hides {name} while you press {c}; tapped on its own it now acts when you let go.")
    changed = sum(1 for rid in touched if pending.get(rid, cat[rid].keys) != cat[rid].keys or rid in pending_ctx)
    return CompileResult(doc, proxies, conflicts, _dedupe(warnings), changed)


def _apply_pad(doc: sf.SettingsDoc, row: ActionInfo, new: list[str], profile: Profile, pending_ctx: dict) -> None:
    old = set(row.pad)
    members = set(row.members)
    only = set(row.only_contexts) if row.only_contexts else None
    skip = set(row.except_contexts)
    done = False
    for sec in doc.sections:
        if (only is not None and sec.name not in only) or sec.name in skip:
            continue
        items: list = []
        for it in sec.items:
            if isinstance(it, sf.Entry) and it.action_id in members and it.key in old:
                for nk in new:  # removing a controller button just drops the line
                    e2 = sf.Entry(nk, it.params)
                    if not any(isinstance(x, sf.Entry) and x.same(e2) for x in items):
                        items.append(e2)
                done = True
                continue
            items.append(it)
        sec.items = items
    if new and not done:  # the action had no controller button yet: add one where it works
        aid = row.members[0]
        counts: Counter = Counter(p for vs in row.variants.values() for p in vs)
        a, _, v = aid.partition("|")
        params = counts.most_common(1)[0][0] if counts else f"Action={a}" + (f",Value={v}" if v else "")
        for ctx in row.pad_contexts or target_contexts(row, profile, pending_ctx):
            for b in new:
                doc.add(ctx, sf.Entry(b, params))


def pad_users(cat: dict[str, ActionInfo], button: str, me: ActionInfo,
              pending_pad: dict[str, list[str]], profile: Profile) -> list[ActionInfo]:
    """Other rows with the same controller button in at least one of the same [sections]."""
    mine = set(me.pad_contexts or target_contexts(me, profile))
    out = []
    for info in cat.values():
        if info.id == me.id or not info.in_menu:
            continue
        if button in pending_pad.get(info.id, info.pad) and mine & set(info.pad_contexts):
            out.append(info)
    return out


def _add_lines(doc: sf.SettingsDoc, row: ActionInfo, keys: list[str], contexts: list[str]) -> None:
    aid = row.members[0]
    counts: Counter = Counter(p for vs in row.variants.values() for p in vs)
    if counts:
        fallback = [counts.most_common(1)[0][0]]
    else:
        a, _, v = aid.partition("|")
        fallback = [f"Action={a}" + (f",Value={v}" if v else "")]
    for ctx in contexts:
        sec = doc.section(ctx, create=True)
        have = any(e.action_id == aid and (is_kbm(e.key) or e.key.startswith(_COMBO)) for e in sec.entries())
        if have:
            continue
        sec.items = [it for it in sec.items if not (isinstance(it, sf.Entry) and it.action_id == aid
                                                    and it.key == NONE_KEY)]
        for k in keys:
            for params in row.variants.get(ctx) or fallback:
                doc.add(ctx, sf.Entry(k, params))


def only_narrowed(row: ActionInfo, pending: dict, pending_ctx: dict) -> bool:
    """A change that only takes the key out of some sections can't create a new clash."""
    return (row.id not in pending and row.id in pending_ctx
            and set(pending_ctx[row.id]) <= set(row.contexts or row.all_contexts))


def _conflicts(cat, profile, pending, pending_ctx, touched) -> list[str]:
    out = []
    for rid in touched:
        row = cat[rid]
        if only_narrowed(row, pending, pending_ctx):
            continue
        for k in pending.get(rid, row.keys):
            for o in who_uses(cat, profile, k, row, pending, pending_ctx):
                line = f"{k}: {row.name} / {o.name}"
                if f"{k}: {o.name} / {row.name}" not in out:
                    out.append(line)
    return _dedupe(out)


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
