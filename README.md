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

The keybinding above works without any extra setup.

If you want to run `dmenu`, `dmenu_run`, or `dmenu_path` by name in a terminal or script, create links in `~/.local/bin`:

```bash
~/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/link-commands
```

This step is optional and requires `~/.local/bin` on your `$PATH`. With the links in place, you can pass a list to `dmenu`:

```bash
printf 'Lock\nSuspend\nLog out\n' | dmenu -p 'Session:'
```

Press Enter to select or Escape to cancel. Use `-i` for case-insensitive matching and `-l 10` for a vertical list.

### Create your own menu

This session menu lets you lock, suspend, log out, reboot, or shut down. Save it as `~/session-menu.sh` and run it with `bash ~/session-menu.sh`. It uses the plugin's full path, so command links are not needed.

```bash
#!/bin/bash

dmenu="$HOME/.config/omarchy/plugins/jesusarchive.dynamic-menu/bin/dmenu"
choice=$(printf '%s\n' 'Lock' 'Suspend' 'Log out' 'Reboot' 'Shut down' |
  "$dmenu" -i -p 'Session:' -l 5) || exit

case "$choice" in
  Lock)        omarchy system lock ;;
  Suspend)     systemctl suspend ;;
  'Log out')   omarchy system logout ;;
  Reboot)      omarchy system reboot ;;
  'Shut down') omarchy system shutdown ;;
esac
```

Press Enter to run the selected action or Escape to cancel. Change the labels and their `case` commands to add your own actions.

![Session menu with Lock, Suspend, Log out, Reboot, and Shut down](assets/session-menu.png)

Type `reboot` to filter the menu:

![Session menu filtered to Reboot](assets/session-menu-filtered.png)

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
