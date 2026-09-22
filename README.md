# Dynamic Menu for Omarchy

Dynamic Menu brings [suckless dmenu](https://tools.suckless.org/dmenu/) to the [Omarchy](https://omarchy.org) shell. It reads options from standard input, opens a menu using the current Omarchy theme, and prints the selected option to standard output.

![dmenu_run on an empty Omarchy workspace](preview.png)

## Requirements

- Omarchy Quattro with shell plugin support.
- Bash.
- `jq`.
- `wl-paste` from `wl-clipboard`.

Omarchy includes these dependencies.

## Installation

```bash
omarchy plugin add https://github.com/jesusarchive/omarchy-dynamic-menu.git --enable
```

Add a keybinding to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + D", "Dynamic menu", "~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/dmenu_run")
```

Use any free key combination. `dmenu_run` lists the commands on your `$PATH` and runs the selected command.

### Add the commands to PATH

Some scripts call `dmenu` by name. To make `dmenu`, `dmenu_run`, and `dmenu_path` available in `~/.local/bin`, run:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands
```

The helper does not replace existing files.

## Usage

Pass a list through standard input:

```bash
printf 'Lock\nSuspend\nLog out\n' | dmenu -p 'Session:'
```

Open the program launcher:

```bash
dmenu_run
```

Use `-i` for case-insensitive matching, `-p` to add a prompt, or `-l` to show a vertical list.

## Removal

Remove the optional command links if you created them:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands --remove
```

Remove the plugin:

```bash
omarchy plugin remove jesusarchive.dynamic-menu
```

Then remove its entry from `~/.config/hypr/bindings.lua`. The plugin may leave an executable-name cache at `~/.cache/dmenu_run`.

## License and attribution

The plugin is licensed under the [MIT License](LICENSE). It ports input handling, matching, and scripts from dmenu 5.4. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the upstream license and copyright notices.
