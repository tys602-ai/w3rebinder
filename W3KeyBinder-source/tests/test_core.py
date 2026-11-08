import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from w3keybinder import settings_file as sf  # noqa: E402
from w3keybinder.ahk import generate_ahk  # noqa: E402
from w3keybinder.keys import Combo  # noqa: E402
from w3keybinder.model import build_catalog, compile_settings  # noqa: E402
from w3keybinder.names import friendly_mod  # noqa: E402
from w3keybinder.profile import Profile  # noqa: E402
from w3keybinder.scanner import scan  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def setup(profile=None):
    cur = sf.load(FIX / "docs" / "input.settings")
    res = scan(FIX / "game", settings_dir=FIX / "docs")
    prof = profile or Profile()
    return cur, res, prof, build_catalog(cur, res, prof)


def lines(doc, ctx):
    return [e.line() for e in doc.section(ctx).entries()]


def diff(a, b):
    ca = Counter((c, e.line()) for c, e in a.iter_entries())
    cb = Counter((c, e.line()) for c, e in b.iter_entries())
    return ca - cb, cb - ca


def test_roundtrip_keeps_everything():
    cur = sf.load(FIX / "docs" / "input.settings")
    again = sf.parse_text(cur.to_text())
    assert [e.line() for _, e in again.iter_entries()] == [e.line() for _, e in cur.iter_entries()]
    assert "Version=43" in cur.to_text()


def test_interact_is_one_row_including_unknown_interactions():
    *_, cat = setup()
    row = cat["row:Interaction"]
    assert row.name == "Interact / activate"
    assert row.keys == ["E"]
    # TakePaintOrange isn't in input.xml but is bound exactly like Interact -> folded in
    assert set(row.members) >= {"Interact", "InteractHold", "Talk", "Open", "TakePaintOrange"}
    assert not any(r.id == "act:Talk" for r in cat.values())
    # Dismount on E is a different binding in the game's menu
    assert cat["row:HorseDismount"].keys == ["E"]


def test_rows_names_and_hidden_actions():
    *_, cat = setup()
    assert cat["row:MoveFwd"].keys == ["W"]          # GI_AxisLeftY|1 + MovementDoubleTapW
    assert cat["row:MoveBck"].keys == ["S"]
    assert cat["row:Sprint"].keys == ["Left Shift"]
    assert cat["row:SprintToggle"].keys == []         # IK_None is "no key", not a key called None
    assert cat["row:JumpRoll"].keys == ["Space"] and "HorseJump" in cat["row:JumpRoll"].members
    assert not cat["act:DebugInput"].in_menu           # debug keys hidden by default


def test_mods_detected():
    _, res, _, cat = setup()
    assert cat["row:QuickLootAll"].mods == ["modQuickLoot"]
    assert cat["row:QuickLootAll"].name == "Loot everything"
    assert cat["row:QuickLootAll"].from_snippet
    ft = cat["row:FastTravelAnywhere"]
    assert ft.mods == ["modFastTravel"] and ft.keys == []
    # 'Jump' is used by the vanilla scripts, so the mod's use of it isn't a mod action
    assert "modFastTravel" not in cat["row:JumpRoll"].mods
    # disabled in mods.settings
    assert "modOldStuff" in res.disabled_mods and "act:OldModAction" not in cat
    assert friendly_mod("modFriendlyHUD") == "Friendly HUD"


def test_no_changes_only_adds_mod_lines():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {}, None, cat)
    removed, added = diff(cur, r.doc)
    assert not removed
    assert sorted(l for _, l in added) == ["IK_L=(Action=QuickLootAll)"] * 2


def test_rebind_interact_moves_all_interactions_only():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:Interaction": ["G"]}, None, cat)
    removed, added = diff(cur, r.doc)
    assert {l.split("=")[0] for _, l in removed} == {"IK_E"}
    assert len(list(removed.elements())) == 6       # 5 in Exploration + Talk in Combat
    assert "IK_E=(Action=HorseDismount)" in lines(r.doc, "Horse")
    assert "IK_G=(Action=InteractHold,State=Duration,IdleTime=0.1)" in lines(r.doc, "Exploration")
    assert "IK_Pad_A_CROSS=(Action=Talk)" in lines(r.doc, "Exploration")  # controller untouched


def test_unbind_writes_none_and_rebind_fills_none():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:Sprint": [], "row:SprintToggle": ["Caps Lock"]}, None, cat)
    ex = lines(r.doc, "Exploration")
    assert "IK_None=(Action=Sprint)" in ex and "IK_LShift=(Action=Sprint)" not in ex
    assert "IK_CapsLock=(Action=SprintToggle)" in ex and "IK_None=(Action=SprintToggle)" not in ex


def test_combo_proxy_roundtrip_and_ahk():
    cur, res, prof, cat = setup()
    pend = {"row:QuickLootAll": ["Ctrl+Q"], "row:SelectAard": ["Ctrl+1", "3"], "row:FastTravelAnywhere": ["Alt+T"]}
    r = compile_settings(cur, res, prof, pend, None, cat)
    assert r.proxies == {"Alt+T": "IK_F13", "Ctrl+1": "IK_F14", "Ctrl+Q": "IK_F15"}
    assert "IK_F15=(Action=QuickLootAll)" in lines(r.doc, "Horse")
    assert "IK_F14=(Action=SelectAard)" in lines(r.doc, "Combat") and "IK_3=(Action=SelectAard)" in lines(r.doc, "Combat")
    assert "IK_F13=(Action=FastTravelAnywhere)" in lines(r.doc, "Exploration")
    assert any("Ctrl on its own" in w for w in r.warnings)  # Left Ctrl = walk toggle
    # after saving, the app reads the file back and shows the combos again
    prof.proxies = r.proxies
    prof.user_set = [m for rid in pend for m in cat[rid].members]
    cat2 = build_catalog(r.doc, res, prof)
    assert cat2["row:QuickLootAll"].keys == ["Ctrl+Q"]
    assert cat2["row:SelectAard"].keys == ["Ctrl+1", "3"] or cat2["row:SelectAard"].keys == ["3", "Ctrl+1"]
    # saving again with no changes is a no-op
    r2 = compile_settings(r.doc, res, prof, {}, None, cat2)
    assert diff(r.doc, r2.doc) == (Counter(), Counter())
    ahk = generate_ahk(r.proxies)
    assert '^vk51::Press("vk51", "vk7E")' in ahk and '~*vk51 up::Release("vk51")' in ahk


def test_removed_combo_frees_proxy():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:QuickLootAll": ["Ctrl+Q"]}, None, cat)
    prof.proxies, prof.user_set = r.proxies, ["QuickLootAll"]
    cat2 = build_catalog(r.doc, res, prof)
    r2 = compile_settings(r.doc, res, prof, {"row:QuickLootAll": ["K"]}, None, cat2)
    assert r2.proxies == {}
    assert not any("IK_F13" in l for _, e in r2.doc.iter_entries() for l in [e.line()])


def test_conflict_reported():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:Interaction": ["F"]}, None, cat)
    assert any("Potion slot 2" in c for c in r.conflicts)


def test_where_it_works_for_new_mod_action():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:FastTravelAnywhere": ["K"]},
                         {"row:FastTravelAnywhere": ["Exploration", "Horse"]}, cat)
    assert "IK_K=(Action=FastTravelAnywhere)" in lines(r.doc, "Horse")
    assert "IK_K=(Action=FastTravelAnywhere)" in lines(r.doc, "Exploration")


def test_utf16_preserved(tmp_path):
    f = tmp_path / "input.settings"
    f.write_text((FIX / "docs" / "input.settings").read_text(), encoding="utf-16")
    doc = sf.load(f)
    n = doc.entry_count()
    assert doc.encoding == "utf-16" and n > 20
    sf.save(doc, f)
    assert f.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") and sf.load(f).entry_count() == n


def test_combo_parse():
    assert str(Combo.parse("ctrl+shift+q")) == "Ctrl+Shift+Q"
    assert Combo.parse("Mouse 4").key == "IK_Mouse4"
    assert Combo.parse("Left Shift").key == "IK_LShift"


def test_mod_that_reuses_a_game_key_is_shown():
    # Elder Blink style: the mod reacts to the game's Dodge (Alt)
    *_, cat = setup()
    dodge = cat["row:Dodge"]
    assert "modElderBlink" in dodge.shared_mods and dodge.keys == ["Alt"]
    assert dodge.mods == []  # still the game's binding, not a separate mod key


def test_installed_mod_action_already_in_file_is_attributed():
    # Sneak style: IK_C=(Action=Sneak) is already in input.settings
    *_, cat = setup()
    sneak = cat["act:Sneak"]
    assert sneak.mods == ["modSneak"] and sneak.in_menu and sneak.keys == ["C"]


def test_edited_game_script_only_counts_added_lines():
    *_, cat = setup()
    assert "modTweaks" in cat["row:CastSign"].shared_mods
    assert "modTweaks" not in cat["row:JumpRoll"].shared_mods  # unchanged copied line
    assert "mod0000_MergedFiles" not in cat["row:FastTravelAnywhere"].mods


def test_overhaul_mod_using_many_game_keys_is_not_listed():
    # Responsive Movement style: reacts to Interact, Walk, Cast sign, Jump, Dodge -> no keybinds of its own
    *_, cat = setup()
    assert not any("modResponsiveMovement" in r.all_mods for r in cat.values())
    assert "modElderBlink" in cat["row:Dodge"].shared_mods  # one game key -> still shown


def test_mod_action_already_in_file_is_found_even_when_script_uses_a_variable():
    # the mod registers its action through a constant, not a literal in RegisterListener
    *_, cat = setup()
    row = cat["act:ToggleStealth"]
    assert row.mods == ["modSneakyGeralt"] and row.keys == ["V"] and row.in_menu


def test_unknown_non_game_action_in_file_is_shown_as_mod():
    *_, cat = setup()
    row = cat["act:MysteryModThing"]
    assert row.in_menu and row.mods == ["(input.settings)"] and row.keys == ["B"]
    assert not cat["act:DebugInput"].in_menu  # game debug keys stay hidden


def test_line_with_trailing_comment_is_read():
    *_, cat = setup()
    row = cat["act:ToggleCompass"]
    assert row.keys == ["N"] and row.mods == ["modFriendlyCompass"]


def test_mod_action_on_e_is_not_swallowed_by_interact():
    *_, cat = setup()
    assert cat["act:QuickPickup"].keys == ["E"] and cat["act:QuickPickup"].mods == ["modQuickPickup"]
    assert "QuickPickup" not in cat["row:Interaction"].members


def test_delete_marked_mod_line_is_ignored():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {}, None, cat)
    assert "IK_LShift=(Action=Sprint) // DELETE" not in r.doc.to_text()
    assert "modQuickPickup" not in cat["row:Sprint"].all_mods


def test_input_xml_action_matched_ignoring_capitals():
    *_, cat = setup()
    row = cat["row:HudToggleMinimap"]
    assert row.keys == ["J"] and row.mods == ["modMinimapToggle"] and row.name == "Toggle minimap"


def test_typing_keys_of_text_input_mods_hidden():
    *_, cat = setup()
    assert not cat["act:a"].in_menu


def test_unseen_style_mod_using_dive_key_on_land():
    # Unseen (Stealth Overhaul): IK_C=(Action=DiveDown) under [Combat]; its own action is pad-only;
    # the script checks IsActionPressed('XXSneak') || IsActionPressed('DiveDown').
    *_, cat = setup()
    dive, land = cat["row:DiveDown"], cat["borrow:row:DiveDown"]
    # the game's Dive (water) and the mod's use of Dive's key (on land) are separate rows
    assert dive.keys == ["C"] and dive.contexts == ["Swimming"] and dive.mods == []
    assert land.name == "Sneak with Dive's key" and land.keys == ["C"] and land.contexts == ["Combat"]
    assert land.mods == ["modUnseenLike"] and land.in_menu
    assert "modUnseenLike" not in cat["row:Sprint"].shared_mods   # only checked to cancel sneaking
    sneak = cat["act:XXSneak"]
    assert sneak.name == "Sneak" and sneak.mods == ["modUnseenLike"] and sneak.via == ["Dive's key (C)"]
    assert sneak.via_rows == ["borrow:row:DiveDown"]
    assert cat["act:XXSneakCombo"].optional and cat["act:XXSneakMod"].optional


def test_binding_unseen_style_action_goes_where_the_mod_needs_it():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"act:XXSneak": ["V"]}, None, cat)
    assert "IK_V=(Action=XXSneak)" in lines(r.doc, "Combat")


# ---- detection fixes (review round) ----
from w3keybinder import scanner as sc  # noqa: E402
from w3keybinder.groups import parse_vars  # noqa: E402


def _mkgame(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_single_quoted_input_xml_rows_in_mod_folder(tmp_path):
    g = _mkgame(tmp_path, {"mods/modX/input_xml.txt":
                           "<Var builder='Input' id='XToggle' displayName='Toggle X' displayType='INPUTPC' actions='XToggle'/>"})
    res = sc.scan(g)
    assert [(v.id, v.actions, v.mod) for v in res.menu_vars] == [("XToggle", ["XToggle"], "modX")]
    assert parse_vars('<Var builder="Input" id="A" actions="A;B"/>')[0].actions == ["A", "B"]


def test_commented_out_code_is_ignored(tmp_path):
    g = _mkgame(tmp_path, {"mods/modX/content/scripts/local/x.ws":
                           "// theInput.RegisterListener(this, 'OnOld', 'OldAction');\n"
                           "/* theInput.IsActionPressed('AlsoOld')\n   it's 'ProseName' here */\n"
                           "url = \"http://example\"; theInput.RegisterListener(this, 'OnNew', \"NewAction\");\n"})
    res = sc.scan(g)
    assert {a.action for a in res.script_actions} == {"NewAction"}
    assert "ProseName" not in res.script_names["modX"] and "NewAction" in res.script_names["modX"]


def test_multiline_either_or_conditions():
    code = ("if ( theInput.IsActionPressed('XSneak') ||\n     theInput.IsActionPressed('DiveDown') ) {}\n"
            "if ( theInput.IsActionPressed('YBlink')\n     || theInput.IsActionPressed('Dodge') ) {}\n"
            "if ( theInput.IsActionPressed('Sprint') && !theInput.IsActionPressed('XSneak') ) {}\n")
    alts = sc._alternatives(code)
    assert ("XSneak", "DiveDown") in alts and ("YBlink", "Dodge") in alts
    assert ("XSneak", "Sprint") not in alts and ("Sprint", "XSneak") not in alts


def test_mod_adding_a_second_copy_of_a_game_line_is_seen(tmp_path):
    line = "theInput.RegisterListener( this, 'OnCbtDodge', 'Dodge' );"
    g = _mkgame(tmp_path, {"content/content0/scripts/game/p.ws": f"{line}\nx = 1;\n",
                           "mods/modBlink/content/scripts/game/p.ws": f"{line}\nx = 1;\nfunction Blink() {{\n{line}\n}}\n"})
    res = sc.scan(g)
    assert [(a.mod, a.action, a.shared) for a in res.script_actions] == [("modBlink", "Dodge", True)]


def test_extra_folder_with_wrapper_attributes_to_inner_mod(tmp_path):
    dl = _mkgame(tmp_path, {"Unseen v1.2/mods/modSneak/content/scripts/local/s.ws":
                            "theInput.RegisterListener(this, 'OnS', 'XSneak');",
                            "Unseen v1.2/readme.txt": "[Exploration]\nIK_C=(Action=XSneak)\n",
                            "Other Mod/modOther/content/scripts/local/o.ws":
                            "theInput.RegisterListener(this, 'OnO', 'OtherAction');"})
    res = sc.scan(None, [str(dl)])
    assert {(a.mod, a.action) for a in res.script_actions} == {("modSneak", "XSneak"), ("modOther", "OtherAction")}
    assert [s.mod for s in res.snippets] == ["modSneak"]


def test_same_lines_in_two_files_count_once(tmp_path):
    lines_ = "[Exploration]\nIK_K=(Action=XThing)\n"
    g = _mkgame(tmp_path, {"mods/modX/readme.txt": "Install:\n" + lines_, "mods/modX/keys.txt": lines_})
    assert len(sc.scan(g).snippets) == 1


def test_disabled_mod_with_trailing_comment(tmp_path):
    (tmp_path / "mods.settings").write_text("[modA]\nEnabled=0 ; off for now\n[modB]\nEnabled=1\n")
    assert sc.read_disabled_mods(tmp_path) == {"moda"}


def test_do_not_remove_comment_is_not_a_delete_marker():
    d = sf.parse_text("[E]\nIK_A=(Action=A) // do not remove\nIK_B=(Action=B) // DELETE\n"
                      "IK_C=(Action=C) // don't delete this\nIK_D=(Action=D) ; remove this line\n")
    assert [e.marked_for_removal for _, e in d.iter_entries()] == [False, True, False, True]


def test_params_with_one_level_of_brackets_are_read():
    d = sf.parse_text("[E]\nIK_A=(Action=A,Hint=(x))\n")
    assert [e.key for _, e in d.iter_entries()] == ["IK_A"]


# ---- combo helper: hiding held keys from the game ----
from w3keybinder.combohelper import ComboEngine, ComboHelper  # noqa: E402

LALT, LCTRL, LSHIFT, K1, K2, KQ, KW, TAB, CAPS = 0xA4, 0xA2, 0xA0, 0x31, 0x32, 0x51, 0x57, 0x09, 0x14
F13, F14, F15, F16, F17 = 0x7C, 0x7D, 0x7E, 0x7F, 0x80
X1 = (0x020B, 1)  # Mouse 4
ALT = frozenset({"Alt"})


def _engine(hide=True):
    kb = {K1: [(ALT, F13, hide)], K2: [(ALT, F14, hide)]}
    ms = {X1: [(ALT, F15, hide)]}  # Alt+Mouse 4
    return ComboEngine(kb, ms, {})


def test_alt_combo_hides_alt_from_the_game():
    e = _engine()
    assert e.key(LALT, True, True) == (True, [("timer", LALT, 1)])   # held back
    assert e.key(K1, True, True) == (True, [("down", F13)])          # combo fires, 1 swallowed
    assert e.key(K1, False, True) == (True, [("up", F13)])
    assert e.key(LALT, False, True) == (True, [])                    # game never sees Alt -> no dodge
    assert e.timeout(LALT, 1) == []                                  # late timer does nothing


def test_two_combos_while_holding_alt():
    e = _engine()
    e.key(LALT, True, True)
    e.key(K1, True, True); e.key(K1, False, True)
    assert e.key(K2, True, True) == (True, [("down", F14)])
    e.key(K2, False, True)
    assert e.key(LALT, False, True) == (True, [])


def test_alt_tapped_alone_still_dodges_on_release():
    e = _engine()
    e.key(LALT, True, True)
    assert e.key(LALT, False, True) == (True, [("tap", LALT)])


def test_alt_held_alone_reaches_game_after_delay():
    e = _engine()
    _, acts = e.key(LALT, True, True)
    assert e.key(LALT, True, True) == (True, [])                     # key repeat while waiting
    assert e.timeout(LALT, acts[0][2]) == [("down", LALT)]
    assert e.key(LALT, True, True) == (False, [])                    # repeats now pass through
    assert e.key(LALT, False, True) == (False, [])                   # real key-up passes through


def test_modifier_then_other_key_passes_modifier_first():
    e = _engine()
    e.key(LALT, True, True)
    assert e.key(TAB, True, True) == (False, [("down", LALT)])       # Alt+Tab still works
    assert e.key(TAB, False, True) == (False, [])
    assert e.key(LALT, False, True) == (False, [])


def test_mouse_combo_and_plain_click():
    e = _engine()
    e.key(LALT, True, True)
    assert e.mouse_button(*X1, True, True) == (True, [("down", F15)])
    assert e.mouse_button(*X1, False, True) == (True, [("up", F15)])
    assert e.key(LALT, False, True) == (True, [])
    e.key(LALT, True, True)
    assert e.mouse_button(0x0201, 0, True, True) == (False, [("down", LALT)])  # Alt+left click passes


def test_unused_modifiers_untouched_and_outside_game():
    e = _engine()
    assert e.key(LSHIFT, True, True) == (False, [])                  # Shift isn't in any combo
    assert e.key(KW, True, True, frozenset({"Shift"})) == (False, [])
    assert e.key(LALT, True, False) == (False, [])                   # not in the game: hands off
    assert e.key(K1, True, False, ALT) == (False, [])
    assert e.key(LALT, False, False) == (False, [])


def test_wrong_modifiers_do_not_fire_combo():
    e = ComboEngine({KQ: [(frozenset({"Ctrl"}), F13, True)]}, {}, {})
    e.key(LCTRL, True, True)
    assert e.key(KQ, True, True, frozenset({"Shift"})) == (False, [("down", LCTRL)])  # Ctrl+Shift+Q isn't Ctrl+Q


def test_hide_off_for_a_combo_lets_the_held_key_through():
    e = _engine(hide=False)
    assert e.key(LALT, True, True) == (False, [])                    # passes straight to the game
    assert e.key(K1, True, True) == (True, [("down", F13), ("down", 0xE8), ("up", 0xE8)])
    assert e.key(K1, False, True) == (True, [("up", F13)])
    assert e.key(LALT, False, True) == (False, [])


def test_mouse_button_as_the_held_key():
    m4 = ("m",) + X1
    e = ComboEngine({K1: [(frozenset({m4}), F16, True)]}, {}, {})
    assert e.mouse_button(*X1, True, True) == (True, [("timer", m4, 1)])   # Mouse 4 held back
    assert e.key(K1, True, True) == (True, [("down", F16)])                 # Mouse 4 + 1
    e.key(K1, False, True)
    assert e.mouse_button(*X1, False, True) == (True, [])                   # game never saw Mouse 4
    e.mouse_button(*X1, True, True)
    assert e.mouse_button(*X1, False, True) == (True, [("mtap", X1)])       # clicked alone: still a click
    assert e.key(K1, True, True) == (False, [])                             # plain 1 untouched


def test_any_key_as_the_held_key_and_mixed_hide():
    caps = ("k", CAPS)
    e = ComboEngine({KQ: [(frozenset({caps}), F17, True)],
                     K2: [(frozenset({caps}), F14, False)]}, {}, {})
    e.key(CAPS, True, True)
    assert e.key(KQ, True, True) == (True, [("down", F17)])                 # Caps Lock + Q, Caps hidden
    e.key(KQ, False, True)
    assert e.key(CAPS, False, True) == (True, [])
    e.key(CAPS, True, True)
    assert e.key(K2, True, True) == (True, [("down", CAPS), ("down", F14)])  # this combo lets Caps through
    e.key(K2, False, True)
    assert e.key(CAPS, False, True) == (False, [])


def test_helper_builds_tables_from_saved_combos():
    h = ComboHelper("witcher3.exe", block_modifiers=True)
    h.set_combos({"Alt+1": "IK_F13", "Mouse 4+2": "IK_F14", "Caps Lock+Mouse 5": "IK_F15"},
                 {"Mouse 4+2": False})
    assert h.kb_combos[K1] == [(ALT, F13, True)]
    assert h.kb_combos[K2] == [(frozenset({("m", 0x020B, 1)}), F14, False)]
    assert h.mouse_combos[(0x020B, 2)] == [(frozenset({("k", CAPS)}), F15, True)]


def test_removing_the_mods_key_keeps_the_game_action():
    # "Remove key" on "Sneak with Dive's key": C stops sneaking on land but still dives in water.
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"borrow:row:DiveDown": [], "act:XXSneak": ["V"]}, None, cat)
    assert not any("DiveDown" in l for l in lines(r.doc, "Combat"))      # removed, not IK_None
    assert "IK_C=(Action=DiveDown)" in lines(r.doc, "Swimming")            # C still dives
    assert "IK_V=(Action=XXSneak)" in lines(r.doc, "Combat")               # sneak has its own key
    prof.user_set = ["DiveDown", "XXSneak"]
    cat2 = build_catalog(r.doc, res, prof)
    assert "borrow:row:DiveDown" not in cat2                               # nothing borrowed any more
    assert cat2["row:DiveDown"].keys == ["C"] and cat2["act:XXSneak"].keys == ["V"]
    assert cat2["act:XXSneak"].via == []


def test_changing_dive_leaves_the_mods_key_alone():
    cur, res, prof, cat = setup()
    r = compile_settings(cur, res, prof, {"row:DiveDown": ["X"]}, None, cat)
    assert "IK_X=(Action=DiveDown)" in lines(r.doc, "Swimming")            # dive moved to X
    assert "IK_C=(Action=DiveDown)" in lines(r.doc, "Combat")              # sneak still on C
    r2 = compile_settings(cur, res, prof, {"borrow:row:DiveDown": ["B"]}, None, cat)
    assert "IK_B=(Action=DiveDown)" in lines(r2.doc, "Combat")             # sneak (via dive) moved to B
    assert "IK_C=(Action=DiveDown)" in lines(r2.doc, "Swimming")           # dive untouched


def test_combo_helper_failure_is_reported_and_logged(tmp_path):
    import threading
    h = ComboHelper("witcher3.exe")
    h.log_path = str(tmp_path / "combo_helper.log")

    def boom(ready):
        raise OSError("hook refused")
    h._run_inner = boom
    ready = threading.Event()
    h._run(ready)
    assert ready.is_set() and not h.running
    assert h.error == "OSError: hook refused"
    assert "hook refused" in (tmp_path / "combo_helper.log").read_text()
