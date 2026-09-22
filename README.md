# Dynamic Menu for Omarchy

Dynamic Menu is a port of [suckless dmenu](https://tools.suckless.org/dmenu/) for the [Omarchy](https://omarchy.org) shell. It reads newline-separated options from standard input and prints the selected option to standard output. The menu uses the current Omarchy theme.

It supports dmenu 5.4's matching, keyboard controls, paging, vertical lists, fonts, colors, and command-line options.

![dmenu_run on an empty Omarchy workspace](preview.png?raw=true&v=2)

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

Use any unused key combination. `dmenu_run` lists the commands on your `$PATH` and runs the selected command.

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

Then remove its entry from `~/.config/hypr/bindings.lua`. Delete `~/.cache/dmenu_run` if you do not want to keep the executable-name cache.

## License and attribution

The plugin is licensed under the [MIT License](LICENSE). It ports input handling, matching, and scripts from dmenu 5.4. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the upstream license and copyright notices.
