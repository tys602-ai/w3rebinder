# W3 KeyBinder

Change any Witcher 3 key, including your mods' keys and combos like **Ctrl+Q** or **Ctrl+1**.

## Use it

1. Run **W3KeyBinder.exe**. Nothing needs installing. (Start the game once first, so it has created
   your keybind file.)
2. It reads your current keybinds (`Documents\The Witcher 3\input.settings`) and your mods.
3. Click an action, click **Change key...** (or double-click), and press the key or combo you want.
4. Click **Save keybinds**.

The list shows the same bindings as the game's own Key Bindings menu. For example, **Interact /
activate** is one row, and changing it moves every interaction (talk, open, loot ...) together.
Mod keys show up under **Mods**. Any that still need a key are listed under **Needs a key**.

## Key combos

The game itself only understands single keys. When you bind something like Ctrl+Q, the app gives
that action a spare key (F13, F14 ...) inside the game, and while the game is in front it turns
Ctrl+Q into that spare key. Keep W3 KeyBinder open while you play (minimised is fine), or turn on
**Options > Start with Windows**.

- **Any key or mouse button can be held**: Ctrl+Q, Alt+1, Mouse 4 + 2, Caps Lock + Mouse 5. In the
  key window, hold the first key or button and press the second.
- **Hide the held key, per combo**: tick "Hide ... from the game" (in the key window or next to
  the key on the right) so Alt+1 doesn't also dodge. Pressed on its own, the held key still works:
  the game gets it when you let go, or after a quarter of a second if you keep holding it.

## Safety

- Every save backs up your previous file. **File > Restore a backup** puts one back.
- Only keyboard and mouse keys are changed. Controller bindings are left alone.
- Mods switched off in `mods.settings` are skipped.

## If a mod's keys aren't found

If a mod only lists its keybind lines on its Nexus page, use **Mods > Add a mod's keybind lines
manually** and paste them in. Or use **Mods > Also scan another folder** and point it at the folder
where you unpacked the download.

## For developers

- Run from source with Python 3.9+: `python W3KeyBinder.pyw`
- Run the tests with `python -m pytest tests`
- Build the exe on Windows with `build_exe.bat`
