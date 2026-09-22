#!/usr/bin/env python3
"""Bounded, per-request Unix socket transport for the QML menu.

The request ID is public. Only the process serving the selected Quickshell IPC
endpoint can return menu results. Linux SO_PEERCRED supplies that identity.
"""

import contextlib
import fcntl
import json
import os
import re
import secrets
import select
import selectors
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

PLUGIN_ID = "jesusarchive.dynamic-menu"
BASE = "omarchy-dynamic-menu"
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 20000
MAX_TEXT = 8192
MAX_OPTIONS = 4096
MAX_OUTPUT = MAX_TEXT * 4  # QML input is capped at 8192 UTF-16 code units.
MAX_EVENT = MAX_OUTPUT * 6 + 256
START_TIMEOUT = 15
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def check_private(fd):
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("runtime directories must be owned by you with mode 0700")


def open_runtime():
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not runtime.startswith("/") or ".." in runtime.split("/"):
        raise ValueError("XDG_RUNTIME_DIR must be an absolute path without '..'")
    fd = os.open("/", DIR_FLAGS)
    try:
        for component in filter(None, runtime.split("/")):
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        check_private(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def private_base(create=False):
    runtime_fd = open_runtime()
    try:
        if create:
            try:
                os.mkdir(BASE, 0o700, dir_fd=runtime_fd)
            except FileExistsError:
                pass
        fd = os.open(BASE, DIR_FLAGS, dir_fd=runtime_fd)
        try:
            check_private(fd)
            yield fd
        finally:
            os.close(fd)
    finally:
        os.close(runtime_fd)


def peer_pid(connection):
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    pid, uid, _ = struct.unpack("3i", credentials)
    if uid != os.getuid():
        raise ValueError("socket peer belongs to a different user")
    return pid


def encode(message):
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def send(connection, message):
    # ASCII JSON avoids splitting UTF-8 characters across QML's raw read chunks.
    connection.sendall(json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n")


class Replies:
    def __init__(self, connection, pid_fd):
        self.connection = connection
        self.pid_fd = pid_fd
        self.pending = bytearray()

    def receive(self, limit=MAX_EVENT, frame_timeout=2):
        deadline = None
        while True:
            if select.select([self.pid_fd], [], [], 0)[0]:
                raise EOFError("the Omarchy shell exited")
            if b"\n" in self.pending:
                line, _, rest = self.pending.partition(b"\n")
                self.pending = bytearray(rest)
                if len(line) > limit:
                    raise ValueError("menu message exceeds its size limit")
                message = json.loads(line)
                return validate_event(message)
            if len(self.pending) > limit:
                raise ValueError("menu message exceeds its size limit")
            if self.pending and deadline is None:
                deadline = time.monotonic() + frame_timeout
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            ready, _, _ = select.select([self.connection, self.pid_fd], [], [], remaining)
            if not ready:
                raise TimeoutError("incomplete menu reply timed out")
            if self.pid_fd in ready:
                raise EOFError("the Omarchy shell exited")
            chunk = self.connection.recv(65536)
            if not chunk:
                raise EOFError("menu connection closed")
            self.pending.extend(chunk)


@contextlib.contextmanager
def shell_identity():
    # Use qs for instance selection, then authenticate the selected endpoint with
    # kernel credentials. Keep a pidfd to reject shell exit and numeric PID reuse.
    config = os.path.join(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"), "shell")
    result = subprocess.run(["qs", "list", "-p", config, "--json"],
                            capture_output=True, timeout=START_TIMEOUT, check=True)
    instances = json.loads(result.stdout)
    if not isinstance(instances, list) or len(instances) != 1:
        raise ValueError("expected one running Omarchy shell")
    instance = instances[0]
    if not isinstance(instance, dict):
        raise ValueError("invalid Quickshell instance identity")
    instance_id, pid = instance.get("id"), instance.get("pid")
    if (not isinstance(instance_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", instance_id)
            or type(pid) is not int or pid <= 0):
        raise ValueError("invalid Quickshell instance identity")
    with contextlib.ExitStack() as stack:
        pid_fd = os.pidfd_open(pid)
        stack.callback(os.close, pid_fd)
        # A substituted IPC socket owned by another same-UID process is not the
        # selected shell, even when it can forge a normal IPC response.
        runtime_fd = open_runtime()
        stack.callback(os.close, runtime_fd)
        connection = stack.enter_context(socket.socket(socket.AF_UNIX))
        connection.settimeout(START_TIMEOUT)
        connection.connect(f"/proc/self/fd/{runtime_fd}/quickshell/by-id/{instance_id}/ipc.sock")
        if peer_pid(connection) != pid:
            raise ValueError("Quickshell IPC process identity changed")
        executable = shutil.which("qs")
        if not executable or not os.path.samefile(f"/proc/{pid}/exe", executable):
            raise ValueError("IPC endpoint is not a Quickshell process")
        if select.select([pid_fd], [], [], 0)[0]:
            raise EOFError("the Omarchy shell exited")
        yield pid, pid_fd


def accept_shell(listener, pid, pid_fd, timeout=START_TIMEOUT):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("the Omarchy shell did not connect")
        ready, _, _ = select.select([listener, pid_fd], [], [], remaining)
        if pid_fd in ready:
            raise EOFError("the Omarchy shell exited")
        if listener not in ready:
            raise TimeoutError("the Omarchy shell did not connect")
        connection, _ = listener.accept()
        try:
            if peer_pid(connection) == pid:
                return connection
        except ValueError:
            pass
        connection.close()


def validate_options(options):
    if not isinstance(options, dict) or len(encode(options)) > MAX_OPTIONS:
        raise ValueError("invalid or oversized menu options")
    allowed = {"barPosition", "prompt", "font", "normBg", "normFg", "selBg", "selFg",
               "lines", "monitor", "bottom", "caseInsensitive"}
    if options.keys() - allowed:
        raise ValueError("unsupported menu option")
    for key, value in options.items():
        if key in {"bottom", "caseInsensitive"}:
            valid = type(value) is bool
        elif key in {"lines", "monitor"}:
            valid = type(value) is int and -(2**31) <= value < 2**31
        else:
            valid = isinstance(value, str) and len(value) <= (1024 if key == "prompt" else 256)
        if not valid:
            raise ValueError(f"invalid menu option: {key}")
    return options


def validate_items(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES or "\0" in text:
        raise ValueError("items must be UTF-8 text, without NUL, at most 2 MiB")
    lines = text.split("\n") if text else []
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) > MAX_ITEMS:
        raise ValueError("too many menu items, maximum 20000")
    if any(len(line.encode("utf-8")) > MAX_TEXT for line in lines):
        raise ValueError("a menu item exceeds 8192 bytes")
    return text


def validate_event(event):
    if not isinstance(event, dict):
        raise ValueError("invalid menu reply")
    if event.get("type") == "exit" and type(event.get("status")) is int and event["status"] in (0, 1):
        return event
    if event.get("type") == "output":
        text = event.get("text")
        if isinstance(text, str) and len(text.encode("utf-8")) <= MAX_OUTPUT and "\n" not in text and "\0" not in text:
            return event
    raise ValueError("invalid menu reply")


def call(options):
    options = validate_options(options)
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("menu input exceeds 2 MiB")
    items = validate_items(raw.decode("utf-8"))
    with private_base(create=True) as base_fd, shell_identity() as (shell_pid, pid_fd):
        try:
            fcntl.flock(base_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another menu is already active") from None
        token = secrets.token_hex(16)
        os.mkdir(token, 0o700, dir_fd=base_fd)
        request_fd = os.open(token, DIR_FLAGS, dir_fd=base_fd)
        try:
            check_private(request_fd)
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(f"/proc/self/fd/{request_fd}/socket")
                os.chmod("socket", 0o600, dir_fd=request_fd, follow_symlinks=False)
                listener.listen(64)
                listener.settimeout(START_TIMEOUT)
                result = subprocess.run(
                    ["omarchy-shell", "shell", "summon", PLUGIN_ID, json.dumps({"token": token})],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=START_TIMEOUT,
                    env={**os.environ, "OMARCHY_SHELL_IPC_TIMEOUT": "10s"}, check=False,
                )
                if result.returncode or result.stdout.strip() != b"ok":
                    raise ValueError("the Omarchy shell did not open the menu")
                with accept_shell(listener, shell_pid, pid_fd) as connection:
                    connection.settimeout(START_TIMEOUT)
                    send(connection, {"type": "begin", "token": token, "options": options})
                    for offset in range(0, len(items), 4096):
                        send(connection, {"type": "items", "text": items[offset:offset + 4096]})
                    send(connection, {"type": "end"})
                    connection.settimeout(None)
                    replies = Replies(connection, pid_fd)
                    printed = 0
                    while True:
                        event = replies.receive()
                        if event["type"] == "exit":
                            return event["status"]
                        data = (event["text"] + "\n").encode("utf-8")
                        printed += len(data)
                        if printed > MAX_BYTES:
                            raise ValueError("menu output exceeds 2 MiB")
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
        finally:
            # Never recursively remove a request path that another process could replace.
            with contextlib.suppress(FileNotFoundError):
                os.unlink("socket", dir_fd=request_fd)
            os.close(request_fd)
            with contextlib.suppress(FileNotFoundError, OSError):
                os.rmdir(token, dir_fd=base_fd)


def paste(selection):
    command = ["wl-paste", "--no-newline"]
    if selection == "primary":
        command.append("--primary")
    elif selection != "clipboard":
        raise ValueError("invalid clipboard selection")
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 2
                data = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ValueError("clipboard read timed out")
                    chunk = os.read(process.stdout.fileno(), MAX_TEXT + 1 - len(data))
                    data.extend(chunk)
                    if b"\n" in data:
                        data = data.partition(b"\n")[0]
                        break
                    if len(data) > MAX_TEXT:
                        raise ValueError("clipboard text exceeds 8192 bytes")
                    if not chunk:
                        break
                sys.stdout.write(data.decode("utf-8"))
        finally:
            if process.poll() is None:
                process.kill()
    return 0


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main():
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if len(sys.argv) != 3:
            raise ValueError("expected call or paste and one argument")
        action, argument = sys.argv[1:]
        if action == "call":
            return call(json.loads(argument))
        if action == "paste":
            return paste(argument)
        raise ValueError("unknown transport action")
    except (OSError, ValueError, EOFError, RecursionError, subprocess.SubprocessError) as error:
        print(f"dmenu: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
