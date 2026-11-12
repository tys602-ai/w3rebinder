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

## Controller

Each action shows its controller button in the **Controller** column. Select an action and use
**Change button...** (under Controller on the right): press the button on your controller (Xbox-style
pads, or PlayStation pads through Steam Input / DS4Windows) or pick it from the list. **Remove**
takes the button off. Movement and camera use the sticks, which are shown but can't be changed.
**Combo / hold...** adds a controller combo of two or three buttons (LB + RB + A), or a hold or
double-tap on one button. These work through the combo helper, so keep the app open. With **Hide ...'s own
actions** ticked (the default), the buttons' normal actions don't fire with the combo: the app moves
them onto spare keys and sends them itself when a button is pressed on its own. The app must then be
running while you play, or those buttons do nothing; untick and save to put them back.

## Hold and double-tap

In the key window, **Press type** lets a binding trigger on **Hold for** N seconds or **Double-tap
within** N ms instead of a normal press. This works for keyboard keys, mouse buttons and controller
buttons, and each binding has its own time.

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
