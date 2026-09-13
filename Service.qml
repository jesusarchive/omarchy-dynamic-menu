import QtQuick
import Quickshell
import Quickshell.Hyprland

// Super+D runs dmenu_run.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string keybindScript: String(Qt.resolvedUrl("bin/keybind")).replace(/^file:\/\//, "")

  function keybind(action) {
    Quickshell.execDetached(["bash", root.keybindScript, action])
  }

  Component.onCompleted: root.keybind("add")
  Component.onDestruction: root.keybind("remove")

  // A Hyprland config reload drops bindings made at runtime.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (event && event.name === "configreloaded") root.keybind("add")
    }
  }
}
