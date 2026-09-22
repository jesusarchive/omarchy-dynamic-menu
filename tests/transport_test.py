"""Security and integration tests; all sockets and fake shell processes are isolated."""
import importlib.util
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

    def start_server(self, listener, code=None):
        command = [sys.executable, "-I", str(HELPER), "serve", self.token]
        if code:
            command = [sys.executable, "-I", "-B", "-c", code]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=self.env)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)
        self.addCleanup(cleanup)
        connection, _ = listener.accept()
        self.addCleanup(connection.close)
        connection.settimeout(3)
        self.assertEqual(t.receive(connection, 256), {"type": "hello", "token": self.token})
        return process, connection

    def ready(self, process, connection, text="one\ntwo\n"):
        t.send(connection, {"type": "items", "token": self.token, "options": {}, "text": text})
        message = json.loads(process.stdout.readline())
        self.assertEqual(message["text"], text)
        self.assertEqual(message["token"], self.token)

    def test_tokens_cannot_supply_paths(self):
        for token in ("", "../" + "a" * 32, "/tmp/owned", "a" * 33, "A" * 32, "a" * 32 + "\n"):
            with self.subTest(token=token):
                result = self.cli("serve", token)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"invalid request token", result.stderr)

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
        self.env["XDG_RUNTIME_DIR"] = str(link)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)

    def test_symlinked_base_and_request_are_rejected(self):
        base = self.runtime / t.BASE
        outside = self.directory / "outside"
        outside.mkdir(mode=0o700)
        base.symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)
        base.unlink()
        base.mkdir(mode=0o700)
        (base / self.token).symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)

    def test_files_fifos_and_socket_symlinks_are_rejected_without_blocking(self):
        endpoint = self.endpoint()
        endpoint.write_text("do not change")
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)
        self.assertEqual(endpoint.read_text(), "do not change")
        endpoint.unlink()
        os.mkfifo(endpoint, mode=0o600)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)
        endpoint.unlink()
        other = self.directory / "other-socket"
        self.listener(other)
        endpoint.symlink_to(other)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)

    def test_public_socket_is_rejected(self):
        endpoint = self.endpoint()
        self.listener(endpoint)
        endpoint.chmod(0o666)
        self.assertNotEqual(self.cli("serve", self.token).returncode, 0)

    def test_socket_is_pinned_across_path_replacement(self):
        endpoint = self.endpoint()
        listener = self.listener(endpoint)
        outside = self.directory / "outside-socket"
        self.listener(outside)
        code = f'''
import importlib.util, os, socket
spec = importlib.util.spec_from_file_location("transport", {str(HELPER)!r})
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
original = socket.socket
class SwappedSocket(original):
    def connect(self, path):
        os.rename({str(endpoint)!r}, {str(endpoint) + '.old'!r})
        os.symlink({str(outside)!r}, {str(endpoint)!r})
        super().connect(path)
socket.socket = SwappedSocket
t.serve({self.token!r})
'''
        process, connection = self.start_server(listener, code)
        self.ready(process, connection)
        connection.close()
        self.assertEqual(process.wait(timeout=3), 0)

    def test_output_is_literal_ordered_and_cancel_retains_prior_output(self):
        process, connection = self.start_server(self.listener(self.endpoint()))
        self.ready(process, connection)
        events = [{"type": "output", "text": "a 'quoted' $(command); value"},
                  {"type": "output", "text": "second"}, {"type": "exit", "status": 1}]
        process.stdin.write(b"".join(t.encode(event) + b"\n" for event in events))
        process.stdin.flush()
        self.assertEqual([t.receive(connection, t.MAX_EVENT) for _ in events], events)
        self.assertEqual(process.wait(timeout=3), 0)

    def test_disconnected_caller_terminates_helper(self):
        process, connection = self.start_server(self.listener(self.endpoint()))
        self.ready(process, connection)
        connection.close()
        self.assertEqual(process.wait(timeout=3), 0)

    def test_oversized_frame_is_rejected_before_reading_body(self):
        process, connection = self.start_server(self.listener(self.endpoint()))
        connection.sendall(struct.pack("!I", t.MAX_REQUEST + 1))
        self.assertEqual(process.wait(timeout=3), 1)
        self.assertIn(b"size limit", process.stderr.read())

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

    def test_handshake_has_total_deadline(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        right.sendall(struct.pack("!I", 10))
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            t.receive(left, 100, started + 0.05)
        self.assertLess(time.monotonic() - started, 0.5)

    def install_fake_shell(self, mode="accept"):
        fakebin = self.directory / "bin"
        fakebin.mkdir()
        command = fakebin / "omarchy-shell"
        command.write_text(f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys, time
helper = {str(HELPER)!r}
directory = pathlib.Path({str(self.directory)!r})
mode = {mode!r}
if sys.argv[1] != "--controller":
    token = json.loads(sys.argv[-1])["token"]
    subprocess.Popen([sys.executable, __file__, "--controller", token], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print("ok")
else:
    process = subprocess.Popen([sys.executable, "-I", helper, "serve", sys.argv[2]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        message = json.loads(process.stdout.readline())
        (directory / "ready").write_text(json.dumps(message))
        if mode == "hold":
            deadline = time.monotonic() + 5
            while not (directory / "release").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        events = [{{"type": "output", "text": "first"}}, {{"type": "output", "text": "second"}}, {{"type": "exit", "status": 0}}]
        process.stdin.write(b"".join((json.dumps(event) + "\\n").encode() for event in events))
        process.stdin.flush()
        process.wait(timeout=3)
    finally:
        if process.poll() is None: process.kill()
        process.wait()
''')
        command.chmod(0o700)
        self.env["PATH"] = str(fakebin) + os.pathsep + self.env["PATH"]

    def test_wrapper_end_to_end_streams_results_and_cleans_socket(self):
        self.install_fake_shell()
        result = subprocess.run([str(ROOT / "bin/dmenu"), "-p", "Pick 'one'", "-l", "3"],
                                input=b"alpha\nbeta\n", env=self.env, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"first\nsecond\n")
        message = json.loads((self.directory / "ready").read_text())
        self.assertEqual(message["text"], "alpha\nbeta\n")
        self.assertEqual(message["options"]["prompt"], "Pick 'one'")
        self.assertEqual(list((self.runtime / t.BASE).iterdir()), [])

    def test_concurrent_wrapper_cannot_replace_active_request(self):
        self.install_fake_shell("hold")
        first = subprocess.Popen([sys.executable, "-I", str(HELPER), "call", "{}"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        first.stdin.close()
        first.stdin = None
        try:
            deadline = time.monotonic() + 4
            while not (self.directory / "ready").exists():
                if time.monotonic() > deadline:
                    self.fail("first menu did not become ready")
                time.sleep(0.01)
            second = self.cli("call", "{}", b"second request")
            self.assertEqual(second.returncode, 1)
            self.assertIn(b"already active", second.stderr)
            (self.directory / "release").touch()
            output, error = first.communicate(timeout=4)
            self.assertEqual(first.returncode, 0, error)
            self.assertEqual(output, b"first\nsecond\n")
        finally:
            if first.poll() is None:
                first.kill()
                first.communicate()

    def test_wrapper_signal_removes_only_its_request(self):
        self.install_fake_shell("hold")
        process = subprocess.Popen([sys.executable, "-I", str(HELPER), "call", "{}"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        try:
            deadline = time.monotonic() + 4
            while not (self.directory / "ready").exists():
                if time.monotonic() > deadline:
                    self.fail("menu did not become ready")
                time.sleep(0.01)
            process.terminate()
            process.communicate(timeout=3)
            self.assertEqual(list((self.runtime / t.BASE).iterdir()), [])
        finally:
            (self.directory / "release").touch()
            if process.poll() is None:
                process.kill()
                process.communicate()

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

    def test_helper_rejects_bad_items_even_when_wrapper_is_bypassed(self):
        process, connection = self.start_server(self.listener(self.endpoint()))
        t.send(connection, {"type": "items", "token": self.token, "options": {}, "text": "a" * (t.MAX_TEXT + 1)})
        self.assertEqual(process.wait(timeout=3), 1)
        self.assertEqual(process.stdout.read(), b"")
        self.assertIn(b"8192 bytes", process.stderr.read())

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
