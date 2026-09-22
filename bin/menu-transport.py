#!/usr/bin/env python3
"""Bounded, per-request Unix socket transport for the QML menu.

The shell receives only a token. It never reads or writes caller-chosen files.
Directory descriptors pin path components while sockets are opened.
"""

import contextlib
import fcntl
import json
import os
import re
import secrets
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

PLUGIN_ID = "jesusarchive.dynamic-menu"
BASE = "omarchy-dynamic-menu"
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 20000
MAX_TEXT = 8192
MAX_OPTIONS = 4096
MAX_OUTPUT = MAX_TEXT * 4  # QML input is capped at 8192 UTF-16 code units.
MAX_EVENT = MAX_OUTPUT * 6 + 256
MAX_REQUEST = MAX_BYTES * 6 + MAX_OPTIONS + 256
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


def peer_uid(connection):
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    if struct.unpack("3i", credentials)[1] != os.getuid():
        raise ValueError("socket peer belongs to a different user")


def encode(message):
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def send(connection, message):
    data = encode(message)
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive(connection, limit, deadline=None):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("menu handshake timed out")
                connection.settimeout(remaining)
            chunk = connection.recv(min(size - len(data), 65536))
            if not chunk:
                raise EOFError("menu connection closed")
            data.extend(chunk)
        return data

    length = struct.unpack("!I", exact(4))[0]
    if length > limit:
        raise ValueError("menu message exceeds its size limit")
    message = json.loads(exact(length))
    if not isinstance(message, dict):
        raise ValueError("menu message must be an object")
    return message


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
    with private_base(create=True) as base_fd:
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
                listener.listen(1)
                listener.settimeout(START_TIMEOUT)
                result = subprocess.run(
                    ["omarchy-shell", "shell", "summon", PLUGIN_ID, json.dumps({"token": token})],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=START_TIMEOUT,
                    env={**os.environ, "OMARCHY_SHELL_IPC_TIMEOUT": "10s"}, check=False,
                )
                if result.returncode or result.stdout.strip() != b"ok":
                    raise ValueError("the Omarchy shell did not open the menu")
                connection, _ = listener.accept()
                with connection:
                    peer_uid(connection)
                    connection.settimeout(START_TIMEOUT)
                    if receive(connection, 256, time.monotonic() + START_TIMEOUT) != {"type": "hello", "token": token}:
                        raise ValueError("incorrect menu request token")
                    send(connection, {"type": "items", "token": token, "options": options, "text": items})
                    connection.settimeout(None)
                    printed = 0
                    while True:
                        event = validate_event(receive(connection, MAX_EVENT))
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


def serve(token):
    if not TOKEN.fullmatch(token):
        raise ValueError("invalid request token")
    with private_base() as base_fd:
        request_fd = os.open(token, DIR_FLAGS, dir_fd=base_fd)
        socket_fd = None
        try:
            check_private(request_fd)
            socket_fd = os.open("socket", os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=request_fd)
            info = os.fstat(socket_fd)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("request endpoint must be an owned socket with mode 0600")
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(START_TIMEOUT)
                connection.connect(f"/proc/self/fd/{socket_fd}")
                peer_uid(connection)
                send(connection, {"type": "hello", "token": token})
                request = receive(connection, MAX_REQUEST, time.monotonic() + START_TIMEOUT)
                if request.get("type") != "items" or request.get("token") != token:
                    raise ValueError("incorrect menu request token")
                options = validate_options(request.get("options"))
                text = validate_items(request.get("text"))
                sys.stdout.buffer.write(encode({"type": "ready", "token": token, "options": options, "text": text}) + b"\n")
                sys.stdout.buffer.flush()
                connection.settimeout(2)
                relay(connection)
        finally:
            if socket_fd is not None:
                os.close(socket_fd)
            os.close(request_fd)
    return 0


def relay(connection):
    # Watch the caller as well as stdin so a dead caller releases the keyboard.
    with selectors.DefaultSelector() as selector:
        selector.register(connection, selectors.EVENT_READ)
        selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
        pending = bytearray()
        printed = 0
        while True:
            for key, _ in selector.select():
                if key.fileobj is connection:
                    # After the initial request, the caller must send no further data.
                    if connection.recv(1):
                        raise ValueError("unexpected data from menu caller")
                    return
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    return
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    pending = bytearray(rest)
                    if len(line) > MAX_EVENT:
                        raise ValueError("menu reply exceeds its size limit")
                    event = validate_event(json.loads(line))
                    if event["type"] == "output":
                        printed += len(event["text"].encode("utf-8")) + 1
                        if printed > MAX_BYTES:
                            raise ValueError("menu output exceeds 2 MiB")
                    send(connection, event)
                    if event["type"] == "exit":
                        return
                if len(pending) > MAX_EVENT:
                    raise ValueError("menu reply exceeds its size limit")


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
            raise ValueError("expected call, serve or paste and one argument")
        action, argument = sys.argv[1:]
        if action == "call":
            return call(json.loads(argument))
        if action == "serve":
            return serve(argument)
        if action == "paste":
            return paste(argument)
        raise ValueError("unknown transport action")
    except (OSError, ValueError, EOFError, subprocess.SubprocessError) as error:
        print(f"dmenu: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
