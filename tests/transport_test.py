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
        legitimate = socket.socket(socket.AF_UNIX)
        self.addCleanup(legitimate.close)
        legitimate.connect(str(endpoint))
        with t.accept_shell(listener, os.getpid(), self.pidfd(), timeout=1) as peer:
            self.assertEqual(t.peer_pid(peer), os.getpid())
            t.send(peer, {"type": "items", "text": "private input"})
            self.assertIn(b"private input", legitimate.recv(65536))
        output, error = attacker.communicate(timeout=2)
        self.assertEqual(attacker.returncode, 0, error)
        self.assertEqual(output, b"")

    def test_rejected_clients_do_not_extend_accept_deadline(self):
        listener = self.listener(self.endpoint())
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            t.accept_shell(listener, os.getpid(), self.pidfd(), timeout=0.05)
        self.assertLess(time.monotonic() - started, 0.5)

    def replies(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return t.Replies(left, self.pidfd()), right

    def test_reply_frames_are_literal_ordered_and_bounded(self):
        reader, writer = self.replies()
        events = [{"type": "output", "text": "a 'quoted' $(command); value 🐈"},
                  {"type": "output", "text": "second"}, {"type": "exit", "status": 1}]
        for event in events:
            t.send(writer, event)
        self.assertEqual([reader.receive() for _ in events], events)
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
            reader = t.Replies(left, fd)
            reader.pending = bytearray(b'{"type":"output","text":"stale"}\n')
            with self.assertRaises(EOFError):
                reader.receive()

    def test_caller_round_trip_cleans_endpoint_and_preserves_options(self):
        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stdin = io.TextIOWrapper(io.BytesIO(b"alpha\nbeta\n"), encoding="utf-8")
        ready = []
        threads = []
        @contextlib.contextmanager
        def identity():
            yield os.getpid(), self.pidfd()
        def summon(command, **kwargs):
            token = json.loads(command[-1])["token"]
            def client():
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.connect(str(self.runtime / t.BASE / token / "socket"))
                    with connection.makefile("rb") as stream:
                        while True:
                            event = json.loads(stream.readline())
                            ready.append(event)
                            if event["type"] == "end": break
                    t.send(connection, {"type": "output", "text": "first"})
                    t.send(connection, {"type": "output", "text": "second"})
                    t.send(connection, {"type": "exit", "status": 0})
            thread = threading.Thread(target=client)
            thread.start()
            threads.append(thread)
            return subprocess.CompletedProcess(command, 0, b"ok\n")
        with patch.object(t, "shell_identity", identity), patch.object(t.subprocess, "run", summon), \
                patch.object(t.sys, "stdin", stdin), patch.object(t.sys, "stdout", output):
            self.assertEqual(t.call({"prompt": "Pick 'one'", "lines": 3}), 0)
        for thread in threads: thread.join(timeout=2)
        self.assertEqual(output.buffer.getvalue(), b"first\nsecond\n")
        self.assertEqual(ready[0]["options"]["prompt"], "Pick 'one'")
        self.assertEqual(ready[1]["text"], "alpha\nbeta\n")
        self.assertEqual(list((self.runtime / t.BASE).iterdir()), [])

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
