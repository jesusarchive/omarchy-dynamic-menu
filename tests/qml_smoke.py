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
from unittest.mock import patch

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
import "''' + ROOT.as_uri() + '''/Auth.js" as TestAuth
Scope {
 id: harness
 // Trusted test code can inspect QML children. The real host dispatcher only
 // invokes root methods and cannot traverse this object graph.
 function actions() {
  for (var i = 0; i < dynamicMenu.data.length; i++)
   if (typeof dynamicMenu.data[i].printLine === "function") return dynamicMenu.data[i]
  throw new Error("missing private logic")
 }
 Plugin.DynamicMenu {
  id: dynamicMenu
  onOpenedChanged: if (opened && dynamicMenu.menu.prompt !== "hold") {
   var actions = harness.actions()
   if (dynamicMenu.menu.prompt === "cancel") { actions.finish(1); return }
   if (dynamicMenu.menu.prompt === "forged-reply") {
    dynamicMenu.transport.write("0:" + "0".repeat(64) + ':{"type":"output","text":"INJECTED"}\\n')
    dynamicMenu.transport.flush()
    return
   }
   if (dynamicMenu.menu.prompt === "replayed-reply") {
    var reply = TestAuth.sign(dynamicMenu.authentication, {type: "output", text: "once"})
    dynamicMenu.transport.write(reply + reply)
    dynamicMenu.transport.flush()
    return
   }
   if (dynamicMenu.menu.prompt === "backpressure") {
    for (var i = 0; i < 300; i++) actions.printLine("x".repeat(8192))
    return
   }
   actions.printLine("QML socket reply 🐈")
   actions.printLine(dynamicMenu.menu.items[0])
   actions.finish(0)
  }
 }
 IpcHandler {
  target: "shell"
  // Match the host's generic call dispatcher for the IPC bypass regression.
  function call(plugin: string, method: string, arg: string): string {
   if (typeof dynamicMenu[method] !== "function") return "unknown"
   dynamicMenu[method](arg)
   return "ok"
  }
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
            # Forge discovery metadata to point at a real qs executable running
            # another configuration. Kernel UID/PID/executable checks alone pass.
            other = root / "other" / "shell"
            other.mkdir(parents=True)
            (other / "shell.qml").write_text("// different expected shell")
            with patch.dict(os.environ, {**env, "OMARCHY_PATH": str(other.parent)}), \
                    patch.object(t.subprocess, "run", return_value=listed):
                try:
                    with t.shell_identity():
                        raise AssertionError("accepted another QML configuration as Omarchy")
                except ValueError as error:
                    assert "different config" in str(error), error
            print("Forged discovery metadata cannot authorize qs running a different configuration.")
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
try:
    s.sendall((json.dumps({"type":"hello", "token":paths[0].parent.name}) + "\\n" +
               json.dumps({"type":"output", "text":"INJECTED COMMAND"}) + "\\n").encode())
except BrokenPipeError: pass  # Rejection may precede the first write.
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
            print("Actual wrapper → private bootstrap → challenge-response → authenticated QML output passed.")
            for prompt, expected in [("forged-reply", b""), ("replayed-reply", b"once\n")]:
                rejected = subprocess.run(["bash", str(ROOT / "bin/dmenu"), "-p", prompt],
                                          input=b"one\n", capture_output=True, env=env, timeout=5)
                assert rejected.returncode == 1 and rejected.stdout == expected, rejected
            print("Forged MAC and replayed output from the genuine QML process are rejected.")

            attacker = subprocess.Popen([sys.executable, "-c", '''
import json, pathlib, socket, sys, time
base = pathlib.Path(sys.argv[1]) / "omarchy-dynamic-menu"
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    paths = list(base.glob("*/socket"))
    if paths: break
    time.sleep(0.001)
else: raise RuntimeError("no endpoint")
with socket.socket(socket.AF_UNIX) as peer:
    peer.settimeout(4); peer.connect(str(paths[0]))
    hello = b""
    while not hello.endswith(b"\\n"): hello += peer.recv(512)
    assert json.loads(hello)["type"] == "challenge"
    peer.sendall((json.dumps({"type":"proof", "mac":"0" * 64}) + "\\n" +
                  json.dumps({"type":"output", "text":"FORGED WITHOUT PID GATE"}) + "\\n").encode())
    try: reply = peer.recv(4096)
    except ConnectionResetError: reply = b""
    assert not reply, reply
''', str(runtime)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            without_pid_gate = '''
import importlib.util, pathlib, sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("transport", sys.argv[1])
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
original = t.accept_shell
def accept(listener, pid, pid_fd, key, token, **kwargs):
    # Test-only bypass. There is no runtime flag to disable PID authentication.
    with patch.object(t, "peer_pid", return_value=pid):
        return original(listener, pid, pid_fd, key, token, **kwargs)
t.accept_shell = accept
sys.exit(t.call({}))
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", without_pid_gate,
                                     str(ROOT / "bin/menu-transport.py")],
                                    input=b"alpha\n", capture_output=True, env=env, timeout=8)
            out, error = attacker.communicate(timeout=2)
            assert attacker.returncode == 0, error
            assert result.returncode == 0 and result.stdout == "QML socket reply 🐈\nalpha\n".encode(), result
            print("The secret independently rejects a racing impostor with the PID gate bypassed only in the test.")

            cancelled = subprocess.run(["bash", str(ROOT / "bin/dmenu"), "-p", "cancel"],
                                       input=b"one\n", capture_output=True, env=env, timeout=5)
            assert cancelled.returncode == 1 and cancelled.stdout == b"", cancelled
            print("Cancellation returns status 1 without output.")
            audit_parent, audit_child = socket.socketpair()
            audit_parent.settimeout(5)
            audit_code = '''
import importlib.util, socket, sys
spec = importlib.util.spec_from_file_location("transport", sys.argv[1])
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
original = t.summon_private
audit_fd = int(sys.argv[2])
def audit(ipc, token, secret):
    with socket.socket(fileno=audit_fd) as channel:
        channel.sendall(secret.encode("ascii"))
    return original(ipc, token, secret)
t.summon_private = audit
sys.argv = ["transport", "call", '{"prompt":"hold"}']
sys.exit(t.main())
'''
            held = subprocess.Popen([sys.executable, "-I", "-B", "-c", audit_code,
                                     str(ROOT / "bin/menu-transport.py"), str(audit_child.fileno())],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=env, pass_fds=(audit_child.fileno(),))
            audit_child.close()
            with audit_parent:
                secret = audit_parent.recv(64)
            assert len(secret) == 64
            def is_open():
                check = subprocess.run(["qs", "ipc", "-p", str(config), "call", "--", "shell", "isOpen"],
                                       capture_output=True, env=env, timeout=2)
                return check.stdout.strip() == b"true"
            try:
                deadline = time.monotonic() + 4
                while not is_open():
                    if held.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("held menu did not open")
                    time.sleep(0.02)
                for method in ["printLine", "finish", "show", "logic.printLine", "authentication.sign"]:
                    invoked = subprocess.run(["qs", "ipc", "-p", str(config), "call", "--", "shell", "call",
                                              t.PLUGIN_ID, method, "IPC_INJECTED"],
                                             capture_output=True, env=env, timeout=2)
                    assert invoked.stdout.strip() == b"unknown", (method, invoked.stdout)
                print("Generic host IPC cannot invoke the private output, finish, show or authentication methods.")
                # Inspect only the isolated test processes and files, never other user data.
                for pid in [held.pid, process.pid]:
                    for name in ["cmdline", "environ"]:
                        assert secret not in Path(f"/proc/{pid}/{name}").read_bytes(), name
                needles = [secret, secret.decode().encode("utf-16-be"), bytes.fromhex(secret.decode())]
                for path in root.rglob("*"):
                    assert secret.decode() not in str(path), "secret in pathname"
                    if path.is_file() and not path.is_symlink():
                        data = path.read_bytes()
                        assert not any(needle in data for needle in needles), "secret in test file or log"
                print("Runtime secret absent from caller/shell argv, environment, runtime filenames, files and logs.")
                second = subprocess.run(["bash", str(ROOT / "bin/dmenu")], input=b"second\n",
                                        capture_output=True, env=env, timeout=3)
                assert second.returncode == 1 and b"already active" in second.stderr, second
                held.terminate()
                held_output, held_error = held.communicate(timeout=3)
                assert held_output == b"", held_output
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

            # A replaced endpoint must prove the bootstrap secret before QML
            # sends a client proof or opens the menu.
            fake_request = runtime / t.BASE / ("e" * 32)
            fake_request.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as fake_server:
                fake_server.bind(str(fake_request / "socket"))
                fake_server.listen(1)
                fake_server.settimeout(3)
                with patch.dict(os.environ, env):
                    with t.shell_identity() as (_, _, ipc):
                        t.summon_private(ipc, "e" * 32, os.urandom(32).hex())
                peer, _ = fake_server.accept()
                with peer:
                    peer.settimeout(2)
                    t.send(peer, {"type": "challenge", "nonce": "0" * 64, "mac": "0" * 64})
                    assert peer.recv(512) == b"", "unauthenticated endpoint received a proof"
                assert not is_open()
            (fake_request / "socket").unlink()
            fake_request.rmdir()
            print("QML rejects a substituted endpoint before sending proof or opening a menu.")

            # A malicious caller owns this endpoint and refuses to read replies.
            # The QML output cap and forced socket destruction must release it.
            token = "d" * 32
            request = runtime / t.BASE / token
            request.mkdir(mode=0o700)
            with socket.socket(socket.AF_UNIX) as stalled:
                stalled.bind(str(request / "socket"))
                stalled.listen(1)
                stalled.settimeout(3)
                secret = os.urandom(32).hex()
                with patch.dict(os.environ, env):
                    with t.shell_identity() as (pid, pid_fd, ipc):
                        t.summon_private(ipc, token, secret)
                        peer, _ = stalled.accept()
                        channel = t.authenticate(peer, pid_fd, bytes.fromhex(secret), token, time.monotonic() + 2)
                with peer:
                    peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                    channel.send({"type": "begin", "token": token, "options": {"prompt": "backpressure"}})
                    channel.send({"type": "end"})
                    deadline = time.monotonic() + 5
                    while True:
                        busy = subprocess.run(["qs", "ipc", "-p", str(config), "call", "--", "shell", "isBusy"],
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
