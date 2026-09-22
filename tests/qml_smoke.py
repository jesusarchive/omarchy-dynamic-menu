"""Run the actual QML/socket round trip in an isolated Quickshell on the current Wayland compositor."""
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
WAYLAND = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
if not WAYLAND.startswith("/"):
    WAYLAND = str(Path(os.environ["XDG_RUNTIME_DIR"]) / WAYLAND)
spec = importlib.util.spec_from_file_location("transport", ROOT / "bin/menu-transport.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

with tempfile.TemporaryDirectory(prefix="dmenu-qml-") as directory:
    root = Path(directory)
    config = root / "shell"
    config.mkdir()
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700)
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
import Quickshell.Io
import QtQuick
import "''' + ROOT.as_uri() + '''" as Plugin
Scope {
 Plugin.DynamicMenu {
  id: dynamicMenu
  onOpenedChanged: if (opened && dynamicMenu.menu.prompt !== "hold") {
   if (dynamicMenu.menu.prompt === "cancel") { finish(1); return }
   if (dynamicMenu.menu.prompt === "backpressure") {
    for (var i = 0; i < 300; i++) printLine("x".repeat(8192))
    return
   }
   printLine("QML socket reply 🐈")
   printLine(dynamicMenu.menu.items[0])
   finish(0)
  }
 }
 IpcHandler {
  target: "shell"
  function isOpen(): bool { return dynamicMenu.opened }
  function isBusy(): bool { return !!dynamicMenu.activeToken }
  function summon(plugin: string, payload: string): string {
   delayed.payload = payload
   delayed.restart()
   return "ok"
  }
 }
 Timer {
  id: delayed
  property string payload: ""
  interval: 300
  onTriggered: dynamicMenu.open(payload)
 }
}
''')
    env = {**os.environ, "QT_QPA_PLATFORM": "wayland", "WAYLAND_DISPLAY": WAYLAND,
           "QT_QPA_PLATFORMTHEME": "generic", "QT_QUICK_BACKEND": "software",
           "QT_STYLE_OVERRIDE": "Basic", "XDG_RUNTIME_DIR": str(runtime),
           "OMARCHY_PATH": str(root), "HYPRLAND_INSTANCE_SIGNATURE": "", "DISPLAY": ""}
    log = root / "log"
    with log.open("w") as output:
        process = subprocess.Popen(["quickshell", "--no-color", "-p", str(config)],
                                   stdout=output, stderr=subprocess.STDOUT, env=env)
        attacker = None
        try:
            deadline = time.monotonic() + 8
            while True:
                listed = subprocess.run(["qs", "list", "-p", str(config), "--json"],
                                        capture_output=True, env=env, timeout=2)
                if listed.returncode == 0 and listed.stdout.lstrip().startswith(b"[") and json.loads(listed.stdout):
                    break
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("isolated QML failed to start")
                time.sleep(0.05)
            attacker = subprocess.Popen([sys.executable, "-c", '''
import json, pathlib, socket, sys, time
base = pathlib.Path(sys.argv[1]) / "omarchy-dynamic-menu"
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    paths = list(base.glob("*/socket"))
    if paths: break
    time.sleep(0.001)
else: raise RuntimeError("no request endpoint")
s = socket.socket(socket.AF_UNIX)
s.settimeout(5)
s.connect(str(paths[0]))
# Know the public ID and send both the old hello and a forged command result.
s.sendall((json.dumps({"type":"hello", "token":paths[0].parent.name}) + "\\n" +
           json.dumps({"type":"output", "text":"INJECTED COMMAND"}) + "\\n").encode())
try: data = s.recv(65536)
except ConnectionResetError: data = b""
assert not data, data
print("same-UID racing client rejected without receiving menu data")
''', str(runtime)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            result = subprocess.run(["bash", str(ROOT / "bin/dmenu"), "-p", "Pick 🐈", "-l", "3"],
                                    input="alpha 🐈\nbeta\n".encode(), capture_output=True,
                                    env=env, timeout=10)
            assert result.returncode == 0, result.stderr
            assert result.stdout == "QML socket reply 🐈\nalpha 🐈\n".encode(), result.stdout
            stdout, stderr = attacker.communicate(timeout=3)
            assert attacker.returncode == 0, stderr
            assert list((runtime / t.BASE).iterdir()) == []
            print(stdout.decode().strip())
            print("Actual wrapper → IPC identity → QML socket → output round trip passed.")
            cancelled = subprocess.run(["bash", str(ROOT / "bin/dmenu"), "-p", "cancel"],
                                       input=b"one\n", capture_output=True, env=env, timeout=5)
            assert cancelled.returncode == 1 and cancelled.stdout == b"", cancelled
            print("Cancellation returns status 1 without output.")
            held = subprocess.Popen(["bash", str(ROOT / "bin/dmenu"), "-p", "hold"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=env)
            def is_open():
                check = subprocess.run(["qs", "ipc", "-p", str(config), "call", "shell", "isOpen"],
                                       capture_output=True, env=env, timeout=2)
                return check.stdout.strip() == b"true"
            try:
                deadline = time.monotonic() + 4
                while not is_open():
                    if held.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("held menu did not open")
                    time.sleep(0.02)
                second = subprocess.run(["bash", str(ROOT / "bin/dmenu")], input=b"second\n",
                                        capture_output=True, env=env, timeout=3)
                assert second.returncode == 1 and b"already active" in second.stderr, second
                held.terminate()
                held.communicate(timeout=3)
                deadline = time.monotonic() + 3
                while is_open():
                    if time.monotonic() > deadline: raise RuntimeError("dead caller left menu open")
                    time.sleep(0.02)
                assert list((runtime / t.BASE).iterdir()) == []
                print("Concurrent request rejected; caller termination closes the QML menu and cleans its socket.")
            finally:
                if held.poll() is None:
                    held.kill()
                    held.communicate()

            # A malicious caller owns this endpoint and refuses to read replies.
            # The QML output cap and forced socket destruction must release it.
            token = "d" * 32
            request = runtime / t.BASE / token
            request.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as stalled:
                stalled.bind(str(request / "socket"))
                stalled.listen(1)
                stalled.settimeout(3)
                subprocess.run(["omarchy-shell", "shell", "summon", t.PLUGIN_ID,
                                json.dumps({"token": token})], env=env, check=True, capture_output=True, timeout=3)
                peer, _ = stalled.accept()
                with peer:
                    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    t.send(peer, {"type": "begin", "token": token, "options": {"prompt": "backpressure"}})
                    t.send(peer, {"type": "end"})
                    deadline = time.monotonic() + 5
                    while True:
                        busy = subprocess.run(["qs", "ipc", "-p", str(config), "call", "shell", "isBusy"],
                                              capture_output=True, env=env, timeout=2).stdout.strip()
                        if busy == b"false": break
                        if time.monotonic() > deadline: raise RuntimeError("stalled socket was not destroyed")
                        time.sleep(0.1)
            (request / "socket").unlink()
            request.rmdir()
            recovered = subprocess.run(["bash", str(ROOT / "bin/dmenu"), "-p", "cancel"],
                                       input=b"one\n", capture_output=True, env=env, timeout=5)
            assert recovered.returncode == 1 and recovered.stdout == b"", recovered
            print("Non-reading peer hits the QML output cap; the shutdown deadline releases its socket and the next menu works.")
        except BaseException:
            print(log.read_text())
            raise
        finally:
            if attacker is not None and attacker.poll() is None:
                attacker.kill()
                attacker.communicate()
            process.terminate()
            process.wait(timeout=4)
