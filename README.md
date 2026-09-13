# Dynamic Menu for Omarchy

[suckless dmenu](https://tools.suckless.org/dmenu/), rebuilt as an
[Omarchy](https://omarchy.org) shell plugin. You get a one-line bar across the
top of the screen: lines piped in on stdin become the items, and your pick is
printed to stdout. It runs inside `omarchy-shell` and follows your Omarchy theme.
Plugin ID: `jesusarchive.dynamic-menu`. MIT licensed.

```bash
printf 'yes\nno\n' | dmenu -p 'Reboot?'
```

- **Same behaviour as dmenu 5.4.** The input handling, matching, paging and
  layout are ported from `dmenu.c`: every key from the dmenu man page, the
  `<` `>` page markers, `-l` vertical lists, and Ctrl+Return to pick several
  items.
- **Same flags**, so existing dmenu scripts work unchanged.
- **Comes with `dmenu_run` and `dmenu_path`.** Press **Super+D** to pick a
  program from your `$PATH` and run it.
- **Themed.** It uses the Omarchy menu colors and font, and its rows are as tall
  as the Omarchy bar, so the menu sits exactly over it. `"style": "dmenu"`
  switches to dmenu's own colors.

## Install

```bash
omarchy plugin add https://github.com/jesusarchive/omarchy-dynamic-menu.git --enable
```

Super+D works as soon as the plugin loads. For scripts that call `dmenu` by
name, put the commands on your `$PATH`:

```bash
plugin=~/.config/omarchy/plugins/jesusarchive.dynamic-menu
ln -s "$plugin/bin/dmenu" "$plugin/bin/dmenu_run" "$plugin/bin/dmenu_path" ~/.local/bin/
```

Manual install from a checkout:

```bash
omarchy plugin validate .
mkdir -p ~/.config/omarchy/plugins/jesusarchive.dynamic-menu
rsync -a --delete --exclude .git ./ ~/.config/omarchy/plugins/jesusarchive.dynamic-menu/
omarchy plugin enable jesusarchive.dynamic-menu
```

Requirements: `bash`, `jq` and `wl-paste` (wl-clipboard). All three ship with
Omarchy.

To remove it, run `omarchy plugin disable jesusarchive.dynamic-menu`, which also
removes the Super+D binding, and delete the `~/.local/bin` links if you made them.

## Use

```bash
dmenu [-bfiv] [-l lines] [-p prompt] [-fn font] [-m monitor]
      [-nb color] [-nf color] [-sb color] [-sf color] [-w windowid]
```

| Flag | Meaning |
|---|---|
| `-b` | Show the menu at the bottom of the screen |
| `-i` | Match items case-insensitively |
| `-l lines` | Show items in a vertical list with this many lines |
| `-m monitor` | Show the menu on this monitor, counting from 0. By default it opens on the focused monitor |
| `-p prompt` | Prompt shown to the left of the input |
| `-fn font` | Font, as a fontconfig pattern such as `monospace:size=10` |
| `-nb` `-nf` | Normal background and foreground color |
| `-sb` `-sf` | Selected background and foreground color |
| `-v` | Print the version and exit |
| `-f`, `-w windowid` | Accepted for compatibility. They are X11 features and do nothing here |

Exit status is 0 when something was printed with Return, and 1 when the menu was
closed with Escape.

**Matching:** each space-separated word you type has to appear in the item.
Items equal to the whole input come first, then items starting with the first
word, then the rest, each group in stdin order.

**Super+D** runs `dmenu_run`. If you've already bound Super+D yourself, the
plugin leaves your binding alone.

### Keys

| Key | Action |
|---|---|
| `Return` | Print the selected item and exit. With no match, print the typed text |
| `Shift+Return` | Print the typed text and exit |
| `Ctrl+Return` | Print the selected item and keep the menu open. The item is marked |
| `Escape` | Exit without printing |
| `Tab` | Copy the selected item into the input |
| `Left` / `Right` | Move the text cursor, or the selection once the cursor is at the edge of the text |
| `Up` / `Down` | Previous / next item |
| `Home` / `End` | First / last item, or the start / end of the text |
| `Page Up` / `Page Down` | Previous / next page |
| `Ctrl+Left` / `Ctrl+Right` | Start / end of the current word |
| `Backspace` / `Delete` | Delete the character before / after the cursor |

Emacs-style keys, as in dmenu:

| Key | Action | Key | Action |
|---|---|---|---|
| `Ctrl+A` | Home | `Ctrl+K` | Delete to the end of the line |
| `Ctrl+B` | Left | `Ctrl+U` | Delete to the start of the line |
| `Ctrl+C` | Escape | `Ctrl+W` | Delete the word before the cursor |
| `Ctrl+D` | Delete | `Ctrl+Y` | Paste the primary selection |
| `Ctrl+E` | End | `Ctrl+Shift+Y` | Paste the clipboard |
| `Ctrl+F` | Right | `Alt+B` / `Alt+F` | Start / end of the word |
| `Ctrl+G` | Escape | `Alt+G` / `Alt+Shift+G` | Home / End |
| `Ctrl+H` | Backspace | `Alt+H` / `Alt+L` | Up / Down |
| `Ctrl+I` | Tab | `Alt+J` / `Alt+K` | Page Down / Page Up |
| `Ctrl+J`, `Ctrl+M` | Return | `Ctrl+N` / `Ctrl+P` | Down / Up |
| `Ctrl+Shift+J`, `Ctrl+Shift+M` | Shift+Return | `Ctrl+[` | Escape |

## Settings

Colors and font come from the `style` key on the plugin's entry in
`~/.config/omarchy/shell.json`:

```json
"plugins": [
  { "id": "jesusarchive.dynamic-menu", "style": "dmenu" }
]
```

| `style` | Colors and font | Row height |
|---|---|---|
| `omarchy` (default) | The Omarchy theme's menu colors and font. Items picked with Ctrl+Return use the theme accent | The Omarchy bar height, while the bar is at the top or bottom |
| `dmenu` | dmenu's defaults: `monospace:size=10`, `#bbbbbb` on `#222222`, selected `#eeeeee` on `#005577` | Font height + 2 px, as in dmenu |

The `-fn`, `-nb`, `-nf`, `-sb` and `-sf` flags override either style, the same
way they override `config.def.h` in dmenu.

## How it works

- **`bin/dmenu`:** parses the flags the way `main()` in `dmenu.c` does. It reads
  stdin and sends the items to the plugin with
  `omarchy-shell shell summon jesusarchive.dynamic-menu '<json>'`.
- **Results:** the menu appends each printed line to a temporary file and writes
  the exit status to a second one when it closes. `bin/dmenu` passes the lines
  on as they arrive, so Ctrl+Return picks reach the caller straight away, the
  same as dmenu writing to stdout.
- **`Engine.js`:** dmenu's `keypress()`, `calcoffsets()` and `drawmenu()`,
  ported function by function and kept free of Qt so node can test it.
  `Match.js` is dmenu's `match()`. `DynamicMenu.qml` draws the result on a
  layer-shell surface that takes the keyboard while it is open.
- **`bin/dmenu_path`:** lists the executables on `$PATH`, cached in
  `~/.cache/dmenu_run`, using the same rules as dmenu's `stest -flx`.
  `bin/dmenu_run` pipes that list into `dmenu` and runs the pick in `$SHELL`.
- **Super+D:** `Service.qml` binds it at runtime with `hyprctl eval`, binds it
  again after a Hyprland config reload, and removes it when the plugin is
  disabled. Nothing is written to `~/.config/hypr`.

**Differences from dmenu:**
- Long items are cut off with `…`, not `...`.
- `-m` counts monitors in the order Quickshell lists them.
- A second `dmenu` started while one is open replaces it. In dmenu, the second
  one fails to grab the keyboard.

## Development

```bash
node --test tests/                        # engine and matching tests
omarchy plugin validate .                 # manifest check
rsync -a --delete --exclude .git ./ ~/.config/omarchy/plugins/jesusarchive.dynamic-menu/
omarchy restart shell                     # QML changes need a restart to show up
printf 'foo\nbar\nfoobar\n' | bin/dmenu -p Pick; echo "exit=$?"
```

**Files:**
- `manifest.json`
- `DynamicMenu.qml`: the bar
- `Engine.js`, `Match.js`: dmenu's logic
- `Service.qml`, `bin/keybind`: Super+D
- `bin/dmenu`, `bin/dmenu_run`, `bin/dmenu_path`
- `tests/`

## License

MIT. The input handling, matching and scripts are ported from dmenu 5.4, whose
MIT/X Consortium licence and copyright notices are included in `LICENSE`.
