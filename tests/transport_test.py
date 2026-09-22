"""Security and integration tests; all sockets and fake shell processes are isolated."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin/menu-transport.py"
spec = importlib.util.spec_from_file_location("transport", HELPER)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dmenu-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.runtime = self.directory / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.env = {**os.environ, "XDG_RUNTIME_DIR": str(self.runtime)}
        self.environment = patch.dict(os.environ, self.env)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.token = "a" * 32

    def cli(self, action, value, data=None):
        return subprocess.run([sys.executable, "-I", str(HELPER), action, value],
                              input=data, capture_output=True, env=self.env, timeout=5)

    def endpoint(self):
        base = self.runtime / t.BASE
        base.mkdir(mode=0o700, exist_ok=True)
        request = base / self.token
        request.mkdir(mode=0o700)
        return request / "socket"

    def listener(self, endpoint):
        listener = socket.socket(socket.AF_UNIX)
        self.addCleanup(listener.close)
        listener.bind(str(endpoint))
        os.chmod(endpoint, 0o600)
        listener.listen(1)
        listener.settimeout(3)
        return listener

    def test_runtime_must_be_private(self):
        self.runtime.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "0700"):
            with t.private_base(create=True):
                pass

    def test_foreign_owner_is_rejected(self):
        with patch.object(t.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, "owned by you"):
                with t.private_base(create=True):
                    pass

    def test_runtime_symlink_is_rejected(self):
        link = self.directory / "alias"
        link.symlink_to(self.runtime, target_is_directory=True)
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(link)}):
            with self.assertRaises(OSError):
                t.open_runtime()

    def test_symlinked_base_is_rejected(self):
        outside = self.directory / "outside"
        outside.mkdir(mode=0o700)
        (self.runtime / t.BASE).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            with t.private_base(create=True):
                pass

    def test_item_limits_are_enforced_by_shell_helper(self):
        invalid = ("a" * (t.MAX_TEXT + 1), "\n" * (t.MAX_ITEMS + 1), "\0", "a" * (t.MAX_BYTES + 1))
        for text in invalid:
            with self.subTest(length=len(text)):
                with self.assertRaises(ValueError):
                    t.validate_items(text)
        self.assertEqual(t.validate_items("alpha\nbeta\n"), "alpha\nbeta\n")

    def test_bad_request_and_reply_types_are_rejected(self):
        for options in (None, [], {"itemsFile": "/etc/passwd"}, {"lines": True}, {"font": "f" * 257}):
            with self.assertRaises(ValueError):
                t.validate_options(options)
        for event in (None, [], {"type": "exit", "status": True}, {"type": "output", "text": "a\nb"}):
            with self.assertRaises(ValueError):
                t.validate_event(event)

    def pidfd(self, pid=None):
        fd = os.pidfd_open(pid or os.getpid())
        self.addCleanup(os.close, fd)
        return fd

    def test_forged_bootstrap_socket_cannot_claim_another_process(self):
        endpoint = self.runtime / "quickshell/by-id/test/ipc.sock"
        endpoint.parent.mkdir(parents=True)
        self.listener(endpoint)
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            result = subprocess.CompletedProcess([], 0, json.dumps([{"id": "test", "pid": process.pid}]).encode())
            with patch.object(t.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(ValueError, "identity changed"):
                    with t.shell_identity():
                        self.fail("accepted forged shell identity")
        finally:
            process.terminate()
            process.wait(timeout=2)

    def test_forged_bootstrap_metadata_cannot_authorize_non_quickshell_process(self):
        endpoint = self.runtime / "quickshell/by-id/test/ipc.sock"
        endpoint.parent.mkdir(parents=True)
        self.listener(endpoint)
        result = subprocess.CompletedProcess([], 0, json.dumps([{"id": "test", "pid": os.getpid()}]).encode())
        with patch.object(t.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ValueError, "not a Quickshell"):
                with t.shell_identity():
                    self.fail("accepted a Python impostor")

    def test_bad_or_ambiguous_bootstrap_metadata_fails_closed(self):
        for instances in ([], [None], [{"id": "../escape", "pid": 1}], [{"id": "x", "pid": True}],
                          [{"id": "a", "pid": 1}, {"id": "b", "pid": 2}]):
            result = subprocess.CompletedProcess([], 0, json.dumps(instances).encode())
            with patch.object(t.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError):
                    with t.shell_identity():
                        self.fail("accepted invalid shell metadata")

    def test_shell_launch_must_name_the_expected_config(self):
        config = self.directory / "shell"
        config.mkdir()
        (config / "shell.qml").write_text("// expected")
        for args in (["qs", "-n", "-p", str(config)],
                     ["qs", "--no-color", "--path", str(config / "shell.qml")],
                     ["qs", "--log-rules", "-p", "--path=" + str(config)]):
            raw = b"\0".join(os.fsencode(arg) for arg in args) + b"\0"
            with patch("builtins.open", return_value=io.BytesIO(raw)):
                t.check_shell_config(os.getpid(), str(config))
        other = self.directory / "other.qml"
        other.write_text("// attacker config")
        alias = self.directory / "alias.qml"
        alias.symlink_to(config / "shell.qml")
        for unrelated in (other, alias):
            with patch("builtins.open", return_value=io.BytesIO(os.fsencode("qs\0-p\0" + str(unrelated) + "\0"))):
                with self.assertRaisesRegex(ValueError, "different config"):
                    t.check_shell_config(os.getpid(), str(config))

    def test_ambiguous_or_implicit_shell_launch_fails_closed(self):
        for raw in (b"qs\0", b"qs\0-c\0omarchy\0", b"qs\0-p\0relative\0",
                    b"qs\0-p\0/a\0-p\0/b\0", b"qs\0--path\0", b"qs\0-p\0/a",
                    b"qs\0--log-rules\0-p\0", b"x" * 65537):
            with self.subTest(raw=raw[:100]), patch("builtins.open", return_value=io.BytesIO(raw)):
                with self.assertRaises(ValueError):
                    t.check_shell_config(os.getpid(), "/unused")

    def test_peer_uid_must_match_even_when_pid_matches(self):
        left, right = socket.socketpair()
        with left, right, patch.object(t.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, "different user"):
                t.peer_pid(left)

    def test_same_uid_impostor_racing_real_peer_gets_no_data(self):
        endpoint = self.endpoint()
        listener = self.listener(endpoint)
        attacker = subprocess.Popen([sys.executable, "-c", '''
import socket, sys
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])
s.sendall(b'{"type":"output","text":"INJECTED"}\\n')
print("connected", flush=True)
try: data = s.recv(65536)
except ConnectionResetError: data = b""
assert not data, data
''', str(endpoint)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # A separate process has the same UID and knows the entire request ID.
        self.assertEqual(attacker.stdout.readline(), b"connected\n")
        received = []
        key = bytes(range(32))
        def legitimate():
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(endpoint))
                frames, nonce = self.client_auth(connection, key, self.token)
                received.append(frames.receive())
        thread = threading.Thread(target=legitimate)
        thread.start()
        channel = t.accept_shell(listener, os.getpid(), self.pidfd(), key, self.token, timeout=1)
        with channel.connection:
            self.assertEqual(t.peer_pid(channel.connection), os.getpid())
            channel.send({"type": "items", "text": "private input"})
        thread.join(timeout=2)
        self.assertIn(b"private input", received[0])
        output, error = attacker.communicate(timeout=2)
        self.assertEqual(attacker.returncode, 0, error)
        self.assertEqual(output, b"")

    def test_rejected_clients_do_not_extend_accept_deadline(self):
        listener = self.listener(self.endpoint())
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            t.accept_shell(listener, os.getpid(), self.pidfd(), bytes(32), self.token, timeout=0.05)
        self.assertLess(time.monotonic() - started, 0.5)

    def replies(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return t.Frames(left, self.pidfd()), right

    def test_reply_frames_are_literal_ordered_and_bounded(self):
        reader, writer = self.replies()
        events = [{"type": "output", "text": "a 'quoted' $(command); value 🐈"},
                  {"type": "output", "text": "second"}, {"type": "exit", "status": 1}]
        for event in events:
            t.send(writer, event)
        self.assertEqual([json.loads(reader.receive()) for _ in events], events)
        writer.sendall(b"x" * 101)
        with self.assertRaisesRegex(ValueError, "size limit"):
            reader.receive(limit=100)

    def test_partial_reply_has_total_deadline_but_idle_user_does_not(self):
        reader, writer = self.replies()
        def delayed():
            time.sleep(0.1)
            writer.sendall(b'{"type":')
        thread = threading.Thread(target=delayed)
        thread.start()
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            reader.receive(frame_timeout=0.05)
        thread.join()
        self.assertGreater(time.monotonic() - started, 0.1)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_dead_shell_is_rejected_even_with_buffered_valid_output(self):
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        fd = self.pidfd(process.pid)
        process.wait(timeout=2)
        left, right = socket.socketpair()
        with left, right:
            reader = t.Frames(left, fd)
            reader.pending = bytearray(b'{"type":"output","text":"stale"}\n')
            with self.assertRaises(EOFError):
                reader.receive()

    def client_auth(self, connection, key, token):
        frames = t.Frames(connection, self.pidfd())
        hello = json.loads(frames.receive(limit=512, deadline=time.monotonic() + 2))
        self.assertEqual(hello["mac"], t.hello_mac(key, token, "server", hello["nonce"]))
        t.send(connection, {"type": "proof", "mac": t.hello_mac(key, token, "client", hello["nonce"])})
        return frames, hello["nonce"]

    def send_reply(self, connection, key, token, nonce, sequence, event):
        payload = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
        mac = t.frame_mac(key, token, nonce, "reply", sequence, payload)
        connection.sendall(f"{sequence}:{mac}:{payload}\n".encode("ascii"))

    def test_caller_round_trip_cleans_endpoint_and_preserves_options(self):
        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(b"alpha\nbeta\n"), encoding="utf-8")
        ready = []
        threads = []
        @contextlib.contextmanager
        def identity():
            yield os.getpid(), self.pidfd(), None
        def summon(ipc, token, secret):
            key = bytes.fromhex(secret)
            def client():
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.connect(str(self.runtime / t.BASE / token / "socket"))
                    frames, nonce = self.client_auth(connection, key, token)
                    sequence = 0
                    while True:
                        seq, mac, payload = frames.receive().decode("ascii").split(":", 2)
                        self.assertEqual(int(seq), sequence)
                        self.assertEqual(mac, t.frame_mac(key, token, nonce, "request", sequence, payload))
                        sequence += 1
                        event = json.loads(payload)
                        ready.append(event)
                        if event["type"] == "end": break
                    for i, event in enumerate([{"type": "output", "text": "first"},
                                               {"type": "output", "text": "second"},
                                               {"type": "exit", "status": 0}]):
                        self.send_reply(connection, key, token, nonce, i, event)
            thread = threading.Thread(target=client)
            thread.start()
            threads.append(thread)
        with patch.object(t, "shell_identity", identity), patch.object(t, "summon_private", summon), \
                patch.object(t.sys, "stdin", stdin), patch.object(t.sys, "stdout", output):
            self.assertEqual(t.call({"prompt": "Pick 'one'", "lines": 3}), 0)
        for thread in threads: thread.join(timeout=2)
        self.assertEqual(output.buffer.getvalue(), b"first\nsecond\n")
        self.assertEqual(ready[0]["options"]["prompt"], "Pick 'one'")
        self.assertEqual(ready[1]["text"], "alpha\nbeta\n")
        self.assertEqual(list((self.runtime / t.BASE).iterdir()), [])

    def test_bad_proof_is_rejected_even_without_pid_gate(self):
        left, right = socket.socketpair()
        with left, right:
            for bad in [{"type": "output", "text": "injected"},
                        {"type": "proof", "mac": "0" * 64}]:
                t.send(right, bad)
                with self.assertRaisesRegex(ValueError, "authentication failed"):
                    t.authenticate(left, self.pidfd(), bytes(32), self.token, time.monotonic() + 0.5)
                self.assertIn(b"challenge", right.recv(1024))

    def test_replayed_proof_is_rejected_on_a_new_connection(self):
        left, right = socket.socketpair()
        with left, right:
            old = t.hello_mac(bytes(32), self.token, "client", "0" * 64)
            t.send(right, {"type": "proof", "mac": old})
            with self.assertRaisesRegex(ValueError, "authentication failed"):
                t.authenticate(left, self.pidfd(), bytes(32), self.token, time.monotonic() + 0.5)

    def test_server_proof_cannot_be_reflected_as_client_proof(self):
        left, right = socket.socketpair()
        with left, right:
            def reflect():
                hello = json.loads(t.Frames(right, self.pidfd()).receive(limit=512))
                t.send(right, {"type": "proof", "mac": hello["mac"]})
            thread = threading.Thread(target=reflect)
            thread.start()
            try:
                with self.assertRaisesRegex(ValueError, "authentication failed"):
                    t.authenticate(left, self.pidfd(), bytes(32), self.token, time.monotonic() + 0.5)
            finally:
                thread.join(timeout=1)

    def test_authenticated_channel_rejects_forged_replayed_and_cross_session_output(self):
        key, nonce = bytes(range(32)), "c" * 64
        event = {"type": "output", "text": "literal"}
        for variant in ("valid", "tamper", "wrong-key", "wrong-request", "wrong-nonce", "out-of-order"):
            left, right = socket.socketpair()
            with left, right:
                channel = t.Channel(left, t.Frames(left, self.pidfd()), key, self.token, nonce)
                self.send_reply(right, bytes(32) if variant == "wrong-key" else key,
                                "b" * 32 if variant == "wrong-request" else self.token,
                                "d" * 64 if variant == "wrong-nonce" else nonce,
                                1 if variant == "out-of-order" else 0, event)
                if variant == "tamper":
                    data = left.recv(4096).replace(b"literal", b"injected")
                    right.sendall(data)
                if variant == "valid":
                    self.assertEqual(channel.receive(), event)
                    self.send_reply(right, key, self.token, nonce, 0, event)
                with self.assertRaises(ValueError):
                    channel.receive()

    def test_private_bootstrap_never_invokes_a_command_with_the_secret(self):
        left, right = socket.socketpair()
        secret = "b" * 64
        with left, right:
            right.sendall(b"\x05\x00" + t.qstring("ok"))
            with patch.object(t.subprocess, "run", side_effect=AssertionError("bootstrap spawned a command")):
                t.summon_private(left, self.token, secret)
            wire = right.recv(4096)
            self.assertTrue(wire.startswith(b"\x03" + t.qstring("shell") + t.qstring("summon")))
            self.assertIn(secret.encode("utf-16-be"), wire)

    def test_private_bootstrap_fails_closed_on_unexpected_or_oversized_responses(self):
        for response in (b"\x04", b"\x05\x01", b"\x05\x00" + struct.pack("!I", 1000000),
                         b"\x05\x00" + t.qstring("no")):
            left, right = socket.socketpair()
            with left, right:
                right.sendall(response)
                with self.assertRaises(ValueError):
                    t.summon_private(left, self.token, "b" * 64)

    def test_private_bootstrap_and_silent_authentication_have_total_deadlines(self):
        left, right = socket.socketpair()
        with left, right, patch.object(t, "START_TIMEOUT", 0.05):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                t.summon_private(left, self.token, "b" * 64)
            self.assertLess(time.monotonic() - started, 0.5)
        left, right = socket.socketpair()
        with left, right:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                t.authenticate(left, self.pidfd(), bytes(32), self.token, started + 0.05)
            self.assertLess(time.monotonic() - started, 0.5)

    def test_cache_rebuild_ignores_predictable_symlinks_and_replaces_cache_link(self):
        cache = self.directory / "cache"
        cache.mkdir(mode=0o700)
        victim = self.directory / "unrelated-file"
        victim.write_text("unchanged")
        os.utime(victim, (1, 1))
        (cache / "dmenu_run").symlink_to(victim)
        result = subprocess.run(
            ["bash", "-c", 'ln -s "$VICTIM" "$XDG_CACHE_HOME/dmenu_run.$$"; exec bash "$SCRIPT"'],
            env={**self.env, "XDG_CACHE_HOME": str(cache), "VICTIM": str(victim),
                 "SCRIPT": str(ROOT / "bin/dmenu_path")}, capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(victim.read_text(), "unchanged")
        self.assertFalse((cache / "dmenu_run").is_symlink())
        self.assertEqual(list(cache.glob(".dmenu_run.*")), [])

    def test_paste_has_size_and_time_limits(self):
        fakebin = self.directory / "clipboard-bin"
        fakebin.mkdir()
        command = fakebin / "wl-paste"
        self.env["PATH"] = str(fakebin) + os.pathsep + self.env["PATH"]
        for script, expected in (("print('hello\\nignored')", b"hello"),
                                 ("print('a' * 9000)", b""),
                                 ("import time; time.sleep(10)", b"")):
            command.write_text(f"#!{sys.executable}\n{script}\n")
            command.chmod(0o700)
            result = self.cli("paste", "clipboard")
            self.assertEqual(result.stdout, expected)
            self.assertEqual(result.returncode, 0 if expected else 1)


if __name__ == "__main__":
    unittest.main()
