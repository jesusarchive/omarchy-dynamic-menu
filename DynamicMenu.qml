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
  property string activeToken: ""
  property bool finishing: false
  readonly property string transportPath: decodeURIComponent(String(Qt.resolvedUrl("bin/menu-transport.py")).replace(/^file:\/\//, ""))

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
    // Caller font overrides must not request enormous glyphs or panel sizes.
    pointSize = Number.isFinite(pointSize) ? Math.max(0, Math.min(pointSize, 72)) : 0
    pixelSize = Number.isFinite(pixelSize) ? Math.max(6, Math.min(pixelSize, 96)) : 14
    return pointSize > 0
      ? Qt.font({ family: family, pointSize: pointSize })
      : Qt.font({ family: family, pixelSize: pixelSize })
  }

  function textw(str) {
    return Math.ceil(metrics.advanceWidth(str)) + root.lrpad
  }

  // IPC carries only an unguessable request token. The helper obtains the
  // items and options over that request's socket after validating the endpoint.
  function open(payloadJson) {
    if (root.activeToken || transport.running) return
    if (typeof payloadJson !== "string" || payloadJson.length > 256) return
    var payload
    try { payload = JSON.parse(payloadJson) } catch (e) { return }
    if (!payload || Array.isArray(payload) || typeof payload !== "object") return
    if (Object.keys(payload).length !== 1 || typeof payload.token !== "string"
        || !/^[0-9a-f]{32}$/.test(payload.token)) return

    root.activeToken = payload.token
    root.finishing = false
    transport.command = ["python3", "-I", root.transportPath, "serve", payload.token]
    transport.running = true
    startupTimer.restart()
  }

  function show(message) {
    if (root.finishing || message.type !== "ready" || message.token !== root.activeToken) return
    startupTimer.stop()
    var payload = message.options
    root.atBottom = payload.bottom === true
    root.monitor = Number.isInteger(payload.monitor) ? payload.monitor : -1
    root.barPosition = String(payload.barPosition || "top")
    root.fontSpec = String(payload.font || "")
    root.normBgSpec = String(payload.normBg || "")
    root.normFgSpec = String(payload.normFg || "")
    root.selBgSpec = String(payload.selBg || "")
    root.selFgSpec = String(payload.selFg || "")
    var screen = root.targetScreen()
    if (screen) root.menuScreen = screen

    // Limit rendered rows independently of the total item limit in the helper.
    var maxRows = Math.max(0, Math.min(50, Math.floor((screen ? screen.height : 1080) / root.bh) - 1))
    root.menu = Engine.create(Engine.readstdin(message.text), {
      lines: Math.min(Number.isInteger(payload.lines) ? payload.lines : 0, maxRows),
      caseInsensitive: payload.caseInsensitive === true,
      prompt: String(payload.prompt || ""),
      textw: root.textw,
      lrpad: root.lrpad,
      mw: root.menuScreen ? root.menuScreen.width : panel.width,
      match: Match.match
    })
    root.revision++
    root.opened = true
    Qt.callLater(function() { if (root.opened) keyCatcher.forceActiveFocus() })
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

  function printLine(line) {
    if (!root.activeToken || root.finishing) return
    transport.write(JSON.stringify({ type: "output", text: line }) + "\n")
  }

  function hideMenu() {
    root.opened = false
    root.menu = null
    root.revision++
    pasteProc.running = false
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "jesusarchive.dynamic-menu")
  }

  function finish(status) {
    if (!root.activeToken || root.finishing) return
    root.finishing = true
    startupTimer.stop()
    transport.write(JSON.stringify({ type: "exit", status: status === 0 ? 0 : 1 }) + "\n")
    root.hideMenu()
    // A non-reading peer must not keep this request alive indefinitely.
    shutdownTimer.restart()
  }

  function transportStopped() {
    startupTimer.stop()
    shutdownTimer.stop()
    root.finishing = true
    root.activeToken = ""
    root.hideMenu()
  }

  Timer {
    id: startupTimer
    interval: 20000
    onTriggered: {
      transport.signal(9)
      if (!transport.running) root.transportStopped()
    }
  }

  Timer {
    id: shutdownTimer
    interval: 3000
    onTriggered: transport.signal(9)
  }

  Process {
    id: transport
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(data) {
        try { root.show(JSON.parse(data)) }
        catch (e) { root.finish(1) }
      }
    }
    onExited: root.transportStopped()
  }

  Process {
    id: pasteProc
    property string requestToken: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (!root.menu || !root.opened || root.finishing || pasteProc.requestToken !== root.activeToken) return
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
        if (!root.menu || !root.opened || root.finishing) return
        var result = Engine.keypress(root.menu, {
          key: root.keyName(event),
          text: event.text,
          ctrl: (event.modifiers & Qt.ControlModifier) !== 0,
          shift: (event.modifiers & Qt.ShiftModifier) !== 0,
          alt: (event.modifiers & Qt.AltModifier) !== 0
        })
        if (result.output !== null) root.printLine(result.output)
        if (result.paste && !pasteProc.running) {
          pasteProc.requestToken = root.activeToken
          pasteProc.command = ["python3", "-I", root.transportPath, "paste", result.paste]
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
