"""Run the actual QML/socket round trip in an isolated Quickshell on the current Wayland compositor."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WAYLAND = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
if not WAYLAND.startswith("/"):
    WAYLAND = str(Path(os.environ["XDG_RUNTIME_DIR"]) / WAYLAND)
spec = importlib.util.spec_from_file_location("transport", ROOT / "bin/menu-transport.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

with tempfile.TemporaryDirectory(prefix="dmenu-qml-") as directory:
    config = Path(directory)
    runtime = config / "runtime"
    runtime.mkdir(mode=0o700)
    base = runtime / t.BASE
    base.mkdir(mode=0o700)
    token = "c" * 32
    request = base / token
    request.mkdir(mode=0o700)
    commons = config / "Commons"
    commons.mkdir()
    (commons / "qmldir").write_text("module qs.Commons\nsingleton Color 1.0 Color.qml\nsingleton Style 1.0 Style.qml\n")
    (commons / "Color.qml").write_text('''pragma Singleton
import QtQuick
QtObject {
 property var menu: ({background:"#111111", text:"#ffffff", selectedBackground:"#444444", selectedText:"#ffffff"})
 property color accent: "#00ff00"
}
''')
    (commons / "Style.qml").write_text('''pragma Singleton
import QtQuick
QtObject {
 property var font: ({menuFamily:"monospace", body:14})
 property var bar: ({sizeHorizontal:28})
}
''')
    (config / "shell.qml").write_text('''import Quickshell
import QtQuick
import "''' + ROOT.as_uri() + '''" as Plugin
Scope {
 Plugin.DynamicMenu {
  id: menu
  onOpenedChanged: if (opened) {
   printLine("QML socket reply")
   finish(0)
  }
 }
 Component.onCompleted: menu.open(JSON.stringify({token: "''' + token + '''"}))
 Timer { interval: 6000; running: true; onTriggered: Qt.quit() }
}
''')
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(request / "socket"))
        os.chmod(request / "socket", 0o600)
        listener.listen(1)
        listener.settimeout(6)
        log = config / "log"
        with log.open("w") as output:
            process = subprocess.Popen(
                ["quickshell", "--no-color", "-p", str(config / "shell.qml")],
                stdout=output, stderr=subprocess.STDOUT,
                env={**os.environ, "QT_QPA_PLATFORM": "wayland", "WAYLAND_DISPLAY": WAYLAND, "QT_QPA_PLATFORMTHEME": "generic",
                     "QT_QUICK_BACKEND": "software", "QT_STYLE_OVERRIDE": "Basic",
                     "XDG_RUNTIME_DIR": str(runtime), "HYPRLAND_INSTANCE_SIGNATURE": "", "DISPLAY": ""},
            )
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(5)
                    assert t.receive(connection, 256) == {"type": "hello", "token": token}
                    t.send(connection, {"type": "items", "token": token, "options": {}, "text": "one\ntwo\n"})
                    assert t.receive(connection, t.MAX_EVENT) == {"type": "output", "text": "QML socket reply"}
                    assert t.receive(connection, t.MAX_EVENT) == {"type": "exit", "status": 0}
                print("Actual QML/socket round trip passed.")
            except BaseException:
                print(log.read_text())
                raise
            finally:
                process.terminate()
                process.wait(timeout=4)
