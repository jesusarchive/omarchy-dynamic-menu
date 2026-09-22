# Dynamic Menu for Omarchy

A port of [dmenu](https://tools.suckless.org/dmenu/) by [suckless](https://suckless.org/) for the Omarchy shell.

It reads a list from standard input and writes your selection to standard output.

![dmenu_run on an empty Omarchy workspace](preview.png?raw=true&v=2)

## Requirements

Omarchy Quattro with shell plugin support, Bash, Python 3, `jq`, and `wl-clipboard`. Omarchy includes these dependencies.

## Installation

```bash
omarchy plugin add https://github.com/jesusarchive/omarchy-dynamic-menu.git --enable
```

Add an unused keybinding to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + D", "Dynamic menu", "~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/dmenu_run")
```

`dmenu_run` lists commands from your `$PATH` and runs the one you select.

## Usage

To use `dmenu`, `dmenu_run`, and `dmenu_path` by name, create the optional command links:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands
```

Make sure `~/.local/bin` is on your `$PATH`. Then pass a list to `dmenu`:

```bash
printf 'Lock\nSuspend\nLog out\n' | dmenu -p 'Session:'
```

Press Enter to select or Escape to cancel. Use `-i` for case-insensitive matching and `-l 10` for a vertical list.

## Removal

Remove the optional command links if you created them:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands --remove
```

Remove the plugin:

```bash
omarchy plugin remove jesusarchive.dynamic-menu
```

Remove the keybinding from `~/.config/hypr/bindings.lua`.

## License and attribution

This plugin uses the [MIT license](LICENSE). See [the third-party notices](THIRD_PARTY_NOTICES.md) for dmenu's license and attribution.
