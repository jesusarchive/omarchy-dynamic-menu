# Dynamic Menu for Omarchy

Dynamic Menu rebuilds [suckless dmenu](https://tools.suckless.org/dmenu/) as an
[Omarchy](https://omarchy.org) shell plugin. It draws a one-line bar across the
top of the screen, reads its items from stdin and prints the selected item to
stdout. It runs inside `omarchy-shell` and follows the current Omarchy theme.
Its plugin ID is `jesusarchive.dynamic-menu`, and its license is MIT.

![dmenu_run over the Omarchy bar](assets/screenshot.png)

```bash
printf 'yes\nno\n' | dmenu -p 'Reboot?'
```

- **dmenu 5.4 behavior.** This plugin ports the input handling, matching,
  paging and layout from `dmenu.c`. It supports every key from the dmenu man
  page, the `<` `>` page markers, `-l` vertical lists and Ctrl+Return for
  selecting several items.
- **Same flags.** Existing dmenu scripts work unchanged.
- **Includes `dmenu_run` and `dmenu_path`.** Bind `dmenu_run` to a key to
  pick a program from your `$PATH` and run it.
- **Omarchy colors and font.** The menu follows `omarchy theme set`. Its rows
  match the Omarchy bar height. Pass flags to use dmenu's colors instead.

## Install

```bash
omarchy plugin add https://github.com/jesusarchive/omarchy-dynamic-menu.git --enable
```

Manual install from a checkout:

```bash
omarchy plugin validate .
mkdir -p ~/.config/omarchy/plugins/jesusarchive.dynamic-menu
rsync -a --delete --exclude .git ./ ~/.config/omarchy/plugins/jesusarchive.dynamic-menu/
omarchy plugin enable jesusarchive.dynamic-menu
```

Requires Omarchy 4.0 (Quattro) with shell plugin support. The plugin also uses
`bash`, `jq` and `wl-paste` from `wl-clipboard`. Omarchy ships all three.

### Update

Git-managed installations update through Omarchy:

```bash
omarchy plugin update jesusarchive.dynamic-menu
```

### Keybinding

Add a keybinding to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + D", "Dynamic menu", "~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/dmenu_run")
```

Hyprland reloads the file on save, and the binding shows up in Omarchy's
keybindings list (Super+K) as "Dynamic menu".

Change `SUPER + D` to any free key combination.

The command can take dmenu flags too, for example
`".../bin/dmenu_run -i -p run"` for case-insensitive matching with a prompt.

### Scripts that call `dmenu` by name

Scripts that invoke `dmenu` by name look it up on `$PATH`. The plugin directory
is not on `$PATH`, so link the commands into `~/.local/bin` once:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands
```

The helper creates links for `dmenu`, `dmenu_run` and `dmenu_path`. It does not
replace an existing file unless that file is one of its own links. Skip this if
you only use the keybinding.

### Remove

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands --remove
omarchy plugin remove jesusarchive.dynamic-menu
```

Then delete your keybinding from `bindings.lua`.

Removal leaves `~/.cache/dmenu_run`, which contains only cached executable
names. Delete it manually if you do not want to keep the cache.

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
| `-fn font` | Font family with an optional `size` or `pixelsize`, such as `monospace:size=10` |
| `-nb` `-nf` | Normal background and foreground color |
| `-sb` `-sf` | Selected background and foreground color |
| `-v` | Print the version and exit |
| `-f`, `-w windowid` | Compatibility only. These X11 flags have no effect |

Return prints a selection and exits with status 0. Escape exits with status 1
without printing anything.

![A vertical list with -l 5 -p System](assets/screenshot-list.png)

### Examples

Pick from a short list:

```bash
printf 'Lock\nLog out\nSuspend\n' | dmenu -p 'Session:'
```

Search a longer list in vertical mode:

```bash
printf 'Firefox\nChromium\nQutebrowser\n' | dmenu -i -l 5 -p 'Browser:'
```

Capture the selection in a script:

```bash
choice=$(printf 'Light\nDark\n' | dmenu -p 'Theme:') || exit 1
printf 'Selected: %s\n' "$choice"
```

Open the program launcher with matching enabled:

```bash
dmenu_run -i -p 'Run:'
```

### Matching

Each space-separated word you type has to appear in the item. Items equal to
the whole input come first, then items starting with the first word, then the
rest, each group in stdin order.

`dmenu_run` lists the programs on your `$PATH` and runs the one you pick in
`$SHELL`. See [Keybinding](#keybinding) to put it on a key.

### Keys

| Key | Action |
|---|---|
| `Return` | Print the selected item and exit. With no match, print the typed text |
| `Shift+Return` | Print the typed text and exit |
| `Ctrl+Return` | Print and mark the selected item, then keep the menu open |
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

## Colors

Colors and font come from the current Omarchy theme and follow
`omarchy theme set`. Items picked with Ctrl+Return use the theme accent.

`-fn`, `-nb`, `-nf`, `-sb` and `-sf` override the theme, the same way they
override `config.def.h` in dmenu.

### Stock dmenu colors

To get dmenu's own look, pass its `config.def.h` defaults:

```bash
dmenu -fn monospace:size=10 -nb '#222222' -nf '#bbbbbb' -sb '#005577' -sf '#eeeeee'
```

That is exactly what dwm passes, so a dwm keybinding works here unchanged:

```bash
dmenu_run -m 0 -fn monospace:size=10 -nb '#222222' -nf '#bbbbbb' -sb '#005577' -sf '#eeeeee'
```

To use these colors on every launch, put the flags in your keybinding:

```lua
o.bind("SUPER + D", "Dynamic menu",
  "~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/dmenu_run -fn monospace:size=10 -nb '#222222' -nf '#bbbbbb' -sb '#005577' -sf '#eeeeee'")
```

Theme changes do not affect colors set with flags. Omit the flags to follow the
theme.

Rows are always as tall as the Omarchy bar when the bar is horizontal. dmenu
uses font height plus 2 px because that was dwm's bar height. Omarchy's bar has
its own height, so the menu matches that instead.

## How it works

`bin/dmenu` parses the flags the way `main()` in `dmenu.c` does. It streams
stdin into a temporary file and summons the plugin with
`omarchy-shell shell summon jesusarchive.dynamic-menu '<json>'`. The IPC
payload contains the file path instead of the input, so Linux's per-argument
size limit does not restrict stdin.

The menu appends each printed line to a temporary file and writes the exit
status to a second one when it closes. `bin/dmenu` forwards each line as soon as
the plugin writes it, matching dmenu's Ctrl+Return behavior.

`Engine.js` implements dmenu's `keypress()`, `calcoffsets()` and `drawmenu()`
without Qt dependencies. `Match.js` implements dmenu's `match()`.
`DynamicMenu.qml` draws the result on a layer-shell window and takes keyboard
focus while the menu is open.

`bin/dmenu_path` lists the executables on `$PATH` and stores the result in
`~/.cache/dmenu_run`. It uses the same rules as dmenu's `stest -flx`.
`bin/dmenu_run` pipes that list into `dmenu` and runs the pick in `$SHELL`.

### Differences from dmenu

- `-m` counts monitors in Quickshell's display order.
- Starting another menu replaces the one already open.

## Files and permissions

The plugin does not use the network or request administrator access.

`bin/dmenu` creates private temporary files for the input, selected items and
exit status, then removes them when it exits. It reads the clipboard only after
Ctrl+Y or Ctrl+Shift+Y. `bin/dmenu_path` stores the executable-name cache at
`~/.cache/dmenu_run`.

The optional `bin/link-commands` helper writes only the `dmenu`, `dmenu_run`
and `dmenu_path` links under `~/.local/bin`. It refuses to replace files it did
not create, and `bin/link-commands --remove` removes only links that point back
to this plugin.

## Development

```bash
node --test tests/*.test.js                # engine and matching tests
omarchy plugin validate .                 # manifest check
rsync -a --delete --exclude .git ./ ~/.config/omarchy/plugins/jesusarchive.dynamic-menu/
omarchy restart shell                     # QML changes need a restart to show up
printf 'foo\nbar\nfoobar\n' | bin/dmenu -p Pick; echo "exit=$?"
```

### Files

| Path | Purpose |
|---|---|
| `manifest.json` | Plugin metadata and entry point |
| `DynamicMenu.qml` | Menu window and rendering |
| `Engine.js`, `Match.js` | Input, layout and matching |
| `bin/dmenu`, `bin/dmenu_run`, `bin/dmenu_path` | dmenu-compatible commands |
| `bin/link-commands` | Optional links under `~/.local/bin` |
| `tests/` | Engine and matching tests |

## License

MIT. This project ports input handling, matching and scripts from dmenu 5.4.
`THIRD_PARTY_NOTICES.md` contains dmenu's MIT/X Consortium license and
copyright notices.
