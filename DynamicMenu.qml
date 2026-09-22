import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import QtQuick
import qs.Commons
import "Match.js" as Match
import "Engine.js" as Engine

// Engine.js handles dmenu input, matching, and paging. This file renders the
// menu and forwards key events.
Item {
  id: root

  // Injected by omarchy-shell when this plugin is summoned.
  property var shell: null
  property var manifest: null

  property bool opened: false
  property var menu: null
  property int revision: 0
  property var view: {
    root.revision
    return root.menu ? Engine.layout(root.menu) : null
  }

  property bool atBottom: false
  property int monitor: -1
  property var menuScreen: null
  property string selectionFile: ""
  property string doneFile: ""

  // Colors and font follow the live Omarchy theme, so they track
  // `omarchy theme set`. -fn, -nb, -nf, -sb and -sf override them, the same
  // way they override config.def.h in dmenu.
  property string fontSpec: ""
  property string normBgSpec: ""
  property string normFgSpec: ""
  property string selBgSpec: ""
  property string selFgSpec: ""

  property color normBg: normBgSpec || Color.menu.background
  property color normFg: normFgSpec || Color.menu.text
  property color selBg: selBgSpec || Color.menu.selectedBackground
  property color selFg: selFgSpec || Color.menu.selectedText
  // SchemeOut, for items printed with Ctrl+Return, has no flag.
  property color outBg: Color.accent
  property color outFg: Color.menu.background

  property font menuFont: root.parseFont(root.fontSpec)
  // drw.c: fonts->h is ascent + descent, lrpad = fonts->h, bh = fonts->h + 2.
  // That is also dwm's bar height, so dmenu aligns with the dwm bar. Use the
  // Omarchy bar height for the same alignment. A side bar has no height to
  // match.
  property string barPosition: "top"
  readonly property int fontHeight: Math.ceil(metrics.ascent) + Math.ceil(metrics.descent)
  readonly property int lrpad: fontHeight
  readonly property bool matchBar: barPosition === "top" || barPosition === "bottom"
  readonly property int bh: matchBar ? Math.max(Style.bar.sizeHorizontal, fontHeight + 2) : fontHeight + 2

  FontMetrics {
    id: metrics
    font: root.menuFont
  }

  // A font family with an optional size, such as "monospace:size=10",
  // "monospace:pixelsize=14", or "Family-10".
  // Without -fn, the menu uses the theme's font.
  function parseFont(spec) {
    var family = Style.font.menuFamily
    var pixelSize = Style.font.body
    var pointSize = 0
    var parts = String(spec || "").split(":")
    if (parts[0]) {
      var sized = parts[0].match(/^(.*)-(\d+(?:\.\d+)?)$/)
      family = sized ? sized[1] : parts[0]
      if (sized) pointSize = Number(sized[2])
    }
    for (var i = 1; i < parts.length; i++) {
      var kv = parts[i].split("=")
      if (kv[0] === "size") pointSize = Number(kv[1])
      else if (kv[0] === "pixelsize") { pixelSize = Number(kv[1]); pointSize = 0 }
    }
    return pointSize > 0
      ? Qt.font({ family: family, pointSize: pointSize })
      : Qt.font({ family: family, pixelSize: pixelSize })
  }

  function textw(str) {
    return Math.ceil(metrics.advanceWidth(str)) + root.lrpad
  }

  // `omarchy-shell shell summon jesusarchive.dynamic-menu '<json>'` calls this.
  function open(payloadJson) {
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (e) { payload = ({}) }

    // A new request while one is pending cancels the old caller, but does not
    // hide. Hiding would come back through close() and cancel this one too.
    if (root.doneFile) root.writeExit(root.doneFile, 1)

    root.atBottom = payload.bottom === true
    root.monitor = Number.isInteger(payload.monitor) ? payload.monitor : -1
    root.barPosition = String(payload.barPosition || "top")
    root.fontSpec = String(payload.font || "")
    root.normBgSpec = String(payload.normBg || "")
    root.normFgSpec = String(payload.normFg || "")
    root.selBgSpec = String(payload.selBg || "")
    root.selFgSpec = String(payload.selFg || "")
    root.selectionFile = String(payload.selectionFile || "")
    root.doneFile = String(payload.doneFile || "")

    var screen = root.targetScreen()
    if (screen) root.menuScreen = screen

    // bin/dmenu leaves stdin in a temp file. The menu shows once that file has
    // loaded, like dmenu reading all of stdin before it maps its window.
    root.pendingPayload = payload
    root.pendingItemsFile = String(payload.itemsFile || "")
    if (!root.pendingItemsFile) {
      root.show("")
    } else if (itemsView.path === root.pendingItemsFile) {
      itemsView.reload()
    } else {
      itemsView.path = root.pendingItemsFile
    }
  }

  // These properties hold the request until show() consumes it.
  property var pendingPayload: null
  property string pendingItemsFile: ""

  function show(itemsText) {
    var payload = root.pendingPayload
    root.pendingPayload = null
    root.pendingItemsFile = ""
    if (!payload || !root.doneFile) return

    root.menu = Engine.create(Engine.readstdin(itemsText), {
      lines: Number.isInteger(payload.lines) ? payload.lines : 0,
      caseInsensitive: payload.caseInsensitive === true,
      prompt: String(payload.prompt || ""),
      textw: root.textw,
      lrpad: root.lrpad,
      mw: root.menuScreen ? root.menuScreen.width : panel.width,
      match: Match.match
    })
    root.revision++
    root.opened = true
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  function close() {
    root.finish(1)
  }

  // -m picks a screen by index. Otherwise the menu goes where the focus is,
  // like dmenu's default of the monitor holding the focused window.
  function targetScreen() {
    var screens = Quickshell.screens
    if (root.monitor >= 0 && root.monitor < screens.length) return screens[root.monitor]
    var focused = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    for (var i = 0; i < screens.length; i++)
      if (screens[i].name === focused) return screens[i]
    return screens.length > 0 ? screens[0] : null
  }

  // Results go to bin/dmenu through files. The menu appends each printed line
  // to the selection file, then writes the exit status to the done file last.
  // Writes run one at a time so they arrive in order.
  property var writes: []

  function queueWrite(script) {
    root.writes.push(script)
    root.runNextWrite()
  }

  function runNextWrite() {
    if (writer.running || root.writes.length === 0) return
    writer.command = ["bash", "-c", root.writes.shift()]
    writer.running = true
  }

  function printLine(line) {
    if (!root.selectionFile) return
    root.queueWrite("printf '%s\\n' " + Util.shellQuote(line) + " >> " + Util.shellQuote(root.selectionFile))
  }

  function writeExit(doneFile, status) {
    var tmp = Util.shellQuote(doneFile + ".tmp")
    root.queueWrite("printf '%s' " + status + " > " + tmp + " && mv " + tmp + " " + Util.shellQuote(doneFile))
  }

  function finish(status) {
    var doneFile = root.doneFile
    root.opened = false
    root.pendingPayload = null
    root.pendingItemsFile = ""
    if (!doneFile) return
    root.doneFile = ""
    root.writeExit(doneFile, status)
    root.selectionFile = ""
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jesusarchive.dynamic-menu")
  }

  FileView {
    id: itemsView
    printErrors: false
    // A path whose request was cancelled or replaced is ignored.
    onLoaded: if (path === root.pendingItemsFile) root.show(text())
    onLoadFailed: if (path === root.pendingItemsFile) root.show("")
  }

  Process {
    id: writer
    onExited: Qt.callLater(root.runNextWrite)
  }

  Process {
    id: pasteProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (!root.menu || !root.opened) return
        Engine.paste(root.menu, text)
        root.revision++
      }
    }
  }

  // Turns a Qt key event into the keysym names Engine.keypress() expects.
  function keyName(event) {
    var shift = (event.modifiers & Qt.ShiftModifier) !== 0
    if (event.key >= Qt.Key_A && event.key <= Qt.Key_Z) {
      var letter = String.fromCharCode(event.key)
      return shift ? letter : letter.toLowerCase()
    }
    switch (event.key) {
    case Qt.Key_Return:
    case Qt.Key_Enter: return "Return"
    case Qt.Key_Escape: return "Escape"
    case Qt.Key_Tab: return "Tab"
    case Qt.Key_Backspace: return "BackSpace"
    case Qt.Key_Delete: return "Delete"
    case Qt.Key_Home: return "Home"
    case Qt.Key_End: return "End"
    case Qt.Key_Left: return "Left"
    case Qt.Key_Right: return "Right"
    case Qt.Key_Up: return "Up"
    case Qt.Key_Down: return "Down"
    case Qt.Key_PageUp: return "Prior"
    case Qt.Key_PageDown: return "Next"
    case Qt.Key_BracketLeft: return "bracketleft"
    }
    return ""
  }

  function colorsFor(scheme) {
    if (scheme === "sel") return [root.selFg, root.selBg]
    if (scheme === "out") return [root.outFg, root.outBg]
    return [root.normFg, root.normBg]
  }

  PanelWindow {
    id: panel
    visible: root.opened
    screen: root.menuScreen
    anchors { top: !root.atBottom; bottom: root.atBottom; left: true; right: true }
    implicitHeight: (root.view ? root.view.rows : 1) * root.bh
    color: root.normBg
    WlrLayershell.namespace: "omarchy-dynamic-menu"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    onWidthChanged: {
      if (!root.menu || width <= 0 || width === root.menu.mw) return
      Engine.resize(root.menu, width)
      root.revision++
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        event.accepted = true
        if (!root.menu || !root.opened) return
        var result = Engine.keypress(root.menu, {
          key: root.keyName(event),
          text: event.text,
          ctrl: (event.modifiers & Qt.ControlModifier) !== 0,
          shift: (event.modifiers & Qt.ShiftModifier) !== 0,
          alt: (event.modifiers & Qt.AltModifier) !== 0
        })
        if (result.output !== null) root.printLine(result.output)
        if (result.paste && !pasteProc.running) {
          pasteProc.command = result.paste === "primary" ? ["wl-paste", "--primary", "--no-newline"] : ["wl-paste", "--no-newline"]
          pasteProc.running = true
        }
        root.revision++
        if (result.exit !== null) root.finish(result.exit)
      }
    }

    Repeater {
      model: root.view ? root.view.boxes : []

      delegate: Rectangle {
        id: box
        required property var modelData
        readonly property var colors: root.colorsFor(modelData.scheme)

        x: modelData.x
        y: modelData.y * root.bh
        width: modelData.width
        height: root.bh
        color: colors[1]

        // drw_text(): left padding of lrpad / 2, cut off with an ellipsis.
        Text {
          x: root.lrpad / 2
          width: Math.max(0, box.width - root.lrpad / 2)
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: box.modelData.text
          color: box.colors[0]
          font: root.menuFont
          elide: Text.ElideRight
        }
      }
    }

    // dmenu's cursor: 2px wide, bh - 4 tall, 2px from the top. Rows can be
    // taller than the font here, so keep that size and centre it.
    Rectangle {
      visible: root.view !== null && root.view.cursor.visible
      x: root.view ? root.view.cursor.x : 0
      y: Math.round((root.bh - (root.fontHeight - 2)) / 2)
      width: 2
      height: root.fontHeight - 2
      color: root.normFg
    }
  }
}
