import Quickshell
import Quickshell.Wayland
import QtQuick
import qs.Commons

Item {
  id: root

  // Injected by omarchy-shell when this plugin is summoned.
  property var shell: null
  property var manifest: null

  property bool opened: false
  property string prompt: ""
  property var items: []
  property var matches: []
  property string filterText: ""
  property int selectedIndex: 0
  property string selectionFile: ""
  property string doneFile: ""

  property color background: Color.menu.background
  property color foreground: Color.menu.text
  property color selectedBackground: Color.menu.selectedBackground
  property color selectedText: Color.menu.selectedText
  property string fontFamily: Style.font.menuFamily
  property int fontSize: Style.font.body
  property int barHeight: fontSize + Style.spacing.controlPaddingY * 2
  property int itemPadding: Style.spacing.controlPaddingX

  // `omarchy-shell shell summon jesusarchive.dynamic-menu '<json>'` lands here.
  // Payload: { prompt, items, selectionFile, doneFile }.
  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }

    // A new request while one is pending cancels the old caller. Only its done
    // file is touched: hiding here would come back through close() and cancel
    // the new request too.
    if (root.doneFile) Quickshell.execDetached(["bash", "-c", ": > " + Util.shellQuote(root.doneFile)])

    root.prompt = String(payload.prompt || "")
    root.items = Array.isArray(payload.items) ? payload.items.map(String) : []
    root.selectionFile = String(payload.selectionFile || "")
    root.doneFile = String(payload.doneFile || "")
    root.setFilter("")
    root.opened = true
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.finish(null)
  }

  function dismiss() {
    root.opened = false
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jesusarchive.dynamic-menu")
  }

  // Writes the pick for bin/dmenu, then touches the done file it waits on.
  // null means cancelled: done file only, so the caller exits 1.
  function finish(selection) {
    var selectionFile = root.selectionFile
    var doneFile = root.doneFile
    root.selectionFile = ""
    root.doneFile = ""
    root.opened = false
    if (!doneFile) return

    var script = ": > " + Util.shellQuote(doneFile)
    if (selection !== null && selection !== undefined)
      script = "printf '%s\\n' " + Util.shellQuote(selection) + " > " + Util.shellQuote(selectionFile) + "; " + script
    Quickshell.execDetached(["bash", "-c", script])
    root.dismiss()
  }

  function setFilter(text) {
    root.filterText = text
    root.matches = root.items.filter(function(item) { return item.indexOf(text) !== -1 })
    root.selectedIndex = 0
    itemRow.positionViewAtBeginning()
  }

  function move(delta) {
    if (root.matches.length === 0) return
    root.selectedIndex = Math.max(0, Math.min(root.matches.length - 1, root.selectedIndex + delta))
    itemRow.positionViewAtIndex(root.selectedIndex, ListView.Contain)
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; left: true; right: true }
    implicitHeight: root.barHeight
    color: root.background
    WlrLayershell.namespace: "omarchy-dynamic-menu"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          root.finish(null)
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          if (root.matches.length > 0) root.finish(root.matches[root.selectedIndex])
        } else if (event.key === Qt.Key_Left) {
          root.move(-1)
        } else if (event.key === Qt.Key_Right) {
          root.move(1)
        } else if (Util.editsFilter(event, root.filterText)) {
          root.setFilter(Util.editedFilter(event, root.filterText))
        } else if (event.text && event.text.length === 1 && event.text.charCodeAt(0) >= 32 && event.text.charCodeAt(0) !== 127) {
          root.setFilter(root.filterText + event.text)
        } else {
          return
        }
        event.accepted = true
      }
    }

    Row {
      anchors.fill: parent

      Rectangle {
        visible: root.prompt.length > 0
        width: promptText.implicitWidth + root.itemPadding * 2
        height: parent.height
        color: root.selectedBackground

        Text {
          id: promptText
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.prompt
          color: root.selectedText
          font.family: root.fontFamily
          font.pixelSize: root.fontSize
        }
      }

      // Stock dmenu gives the input a third of the bar, at least.
      Item {
        width: Math.max(panel.width / 3, inputText.implicitWidth + root.itemPadding * 2)
        height: parent.height

        Text {
          id: inputText
          anchors.left: parent.left
          anchors.leftMargin: root.itemPadding
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: root.filterText
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: root.fontSize
        }

        Rectangle {
          anchors.left: inputText.right
          anchors.verticalCenter: parent.verticalCenter
          width: 2
          height: root.fontSize
          color: root.foreground
        }
      }

      ListView {
        id: itemRow
        width: parent.width - x
        height: parent.height
        orientation: ListView.Horizontal
        clip: true
        interactive: false
        model: root.matches

        delegate: Rectangle {
          required property int index
          required property string modelData

          width: label.implicitWidth + root.itemPadding * 2
          height: itemRow.height
          color: index === root.selectedIndex ? root.selectedBackground : "transparent"

          Text {
            id: label
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: parent.modelData
            color: index === root.selectedIndex ? root.selectedText : root.foreground
            font.family: root.fontFamily
            font.pixelSize: root.fontSize
          }
        }
      }
    }
  }
}
