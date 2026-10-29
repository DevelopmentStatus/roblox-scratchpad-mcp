"""Authenticated loopback transport. This is the Studio link, not the MCP transport."""

from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 4 * 1024 * 1024
MAX_SOURCE = 512 * 1024
PEER_TTL = 35
ROOTS = {"Workspace", "ReplicatedFirst", "ReplicatedStorage", "ServerScriptService",
         "ServerStorage", "StarterGui", "StarterPack", "StarterPlayer"}


def safe_path(root: Path, relative: str) -> Path:
    """Reject Windows drives, separators, ADS, device names and link escapes on all OSes."""
    if not isinstance(relative, str) or not relative or len(relative) > 1024:
        raise ValueError("invalid relative path")
    parts = relative.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if any(not p or p in (".", "..") or p.endswith((".", " ")) or
           any(c in p for c in '\\:<>"|?*') or any(ord(c) < 32 for c in p) or
           p.split(".")[0].upper() in reserved for p in parts):
        raise ValueError("unsafe relative path")
    if PureWindowsPath(relative).drive:
        raise ValueError("drive paths are forbidden")
    if parts[0] not in ROOTS or len(parts) < 2 or not relative.endswith(".luau"):
        raise ValueError("use a service-relative .luau path, e.g. ReplicatedStorage/Example.luau")
    base = root.resolve()
    candidate = root.joinpath(*parts)
    if not candidate.resolve().is_relative_to(base):
        raise ValueError("path escapes workspace")
    # Do not read or write through symlinks/junctions, including links inside the root.
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("links are forbidden")
        cursor = cursor.parent
    return candidate


def atomic_write(path: Path, source: str) -> None:
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE:
        raise ValueError("source must be text of at most 512 KiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        temporary.write_text(source, encoding="utf-8", newline="")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Bridge:
    def __init__(self, project: Path, port: int):
        self.project = project.resolve()
        self.state = self.project / ".scratchpad-bridge"
        if self.state.is_symlink() or (hasattr(self.state, "is_junction") and self.state.is_junction()):
            raise ValueError("state directory must not be a link")
        self.work = self.state / "work"
        self.exports = self.state / "exports"
        for directory in (self.work, self.exports):
            if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                raise ValueError("state subdirectory must not be a link")
            directory.mkdir(parents=True, exist_ok=True)
        token_path = self.state / "token"
        if token_path.is_symlink():
            raise ValueError("token file must not be a link")
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
        self.token = token_path.read_text(encoding="utf-8").strip()
        if len(self.token) < 32:
            raise ValueError("invalid pairing token; remove the token file to regenerate it")
        self.port = port
        self.condition = threading.Condition(threading.RLock())
        self.peers: dict[str, dict] = {}
        self.selected: str | None = None
        self.commands: dict[str, dict] = {}
        self.events = collections.deque(maxlen=500)
        self.event_id = 0
        self.sent: dict[str, str] = {}
        self.pending_files: dict[str, dict] = {}
        self.batches: dict[str, dict] = {}

    def active(self) -> dict[str, dict]:
        now = time.monotonic()
        return {k: v for k, v in self.peers.items() if now - v["seen"] < PEER_TTL}

    def status(self) -> dict:
        with self.condition:
            return {"version": "0.1.0a1", "port": self.port, "selected_edit_peer": self.selected,
                    "work_directory": str(self.work),
                    "peers": [{"peer_id": k, **{a: b for a, b in v.items() if a != "seen"}}
                              for k, v in self.active().items()]}

    def select(self, peer: str) -> dict:
        with self.condition:
            if self.active().get(peer, {}).get("target") != "edit":
                raise ValueError("select a connected edit peer from scratchpad_status")
            if self.selected != peer:
                self.selected = peer
                self.sent.clear()
                self.pending_files.clear()
            return self.status()

    def log(self, kind: str, message: str, path: str | None = None) -> None:
        with self.condition:
            self.event_id += 1
            self.events.append({"id": self.event_id, "kind": kind[:40], "message": message[:8000], "path": path})

    def changes(self, peer: str) -> list[dict]:
        with self.condition:
            if self.selected != peer or peer not in self.active():
                return []
            files = []
            for path in sorted(self.work.rglob("*.luau")):
                relative = path.relative_to(self.work).as_posix()
                path = safe_path(self.work, relative)
                source = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(source.encode()).hexdigest()
                if self.sent.get(relative) != digest:
                    files.append({"path": relative, "source": source, "revision": digest})
                    if len(json.dumps(files).encode()) > MAX_BODY:
                        files.pop()
                        break
                    self.pending_files[relative] = {"peer": peer, "revision": digest}
            return files

    def acknowledge(self, payload: dict) -> None:
        with self.condition:
            path = payload["path"]
            pending = self.pending_files.get(path)
            if pending != {"peer": payload["peer"], "revision": payload["revision"]}:
                raise ValueError("unknown file revision")
            # Errors are logged and marked delivered; fixing/re-saving the file retries it.
            self.sent[path] = pending["revision"]
            self.pending_files.pop(path)
            self.log("applied" if payload["ok"] else "error", str(payload.get("message", "")), path)

    def poll(self, peer: str, target: str, place: str, place_id: str) -> dict | None:
        if target not in ("edit", "server", "client") or not peer or len(peer) > 100:
            raise ValueError("invalid peer or target")
        deadline = time.monotonic() + 10
        with self.condition:
            self.peers[peer] = {"target": target, "place": place[:200], "place_id": place_id[:30], "seen": time.monotonic()}
            # Dispatched commands are not replayed: execution is at most once.
            while True:
                now = time.monotonic()
                for command in self.commands.values():
                    if command["peer"] == peer and command["state"] == "queued":
                        if command["expires"] <= now:
                            command["state"] = "expired"
                        else:
                            command["state"] = "dispatched"
                            return {k: command[k] for k in ("id", "code", "action")}
                remaining = deadline - now
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)

    def execute(self, peer: str, code: str, timeout: float = 30, action: str = "execute") -> dict:
        if not 1 <= timeout <= 120 or len(code.encode()) > MAX_SOURCE:
            raise ValueError("timeout must be 1..120 seconds and code at most 512 KiB")
        with self.condition:
            info = self.active().get(peer)
            if not info:
                raise ValueError("peer is disconnected; use scratchpad_status")
            if action == "export" and (peer != self.selected or info["target"] != "edit"):
                raise ValueError("export requires the selected edit peer")
            # Bound retained command state, including late and abandoned results.
            now = time.monotonic()
            self.commands = {k: v for k, v in self.commands.items() if v["expires"] + 120 > now}
            if len(self.commands) >= 100:
                raise ValueError("command limit reached; wait for existing commands to expire")
            cid = secrets.token_hex(16)
            self.commands[cid] = {"id": cid, "peer": peer, "code": code, "action": action,
                                  "expires": now + timeout, "state": "queued"}
            self.condition.notify_all()
            while "result" not in self.commands[cid]:
                left = self.commands[cid]["expires"] - time.monotonic()
                if left <= 0:
                    command = self.commands[cid]
                    was_dispatched = command["state"] == "dispatched"
                    if not was_dispatched:
                        command["state"] = "expired"
                    return {"id": cid, "ok": False, "timed_out": True, "may_still_be_running": was_dispatched,
                            "error": "Timed out. Dispatched Luau cannot be interrupted; do not blindly retry."}
                self.condition.wait(left)
            return self.commands.pop(cid)["result"]

    def result(self, payload: dict) -> None:
        with self.condition:
            command = self.commands.get(payload["id"])
            if not command or command["peer"] != payload["peer"] or command["state"] != "dispatched":
                raise ValueError("unknown command or wrong peer")
            command["result"] = {k: v for k, v in payload.items() if k != "peer"}
            command["state"] = "completed"
            self.condition.notify_all()

    def export(self, payload: dict) -> str:
        with self.condition:
            peer, batch = payload["peer"], payload["batch"]
            part, total, files = payload["part"], payload["parts"], payload["files"]
            if files == []:  # HttpService encodes an empty Luau table as an array.
                files = {}
            if peer != self.selected or self.active().get(peer, {}).get("target") != "edit":
                raise ValueError("select this edit peer before exporting")
            if not isinstance(batch, str) or len(batch) > 100 or not batch:
                raise ValueError("invalid export batch")
            if type(part) is not int or type(total) is not int or not 1 <= part <= total <= 200:
                raise ValueError("invalid export parts")
            if not isinstance(files, dict):
                raise ValueError("files must be an object")
            for relative, source in files.items():
                safe_path(self.work, relative)
                if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE:
                    raise ValueError("invalid export source")
            now = time.monotonic()
            self.batches = {k: v for k, v in self.batches.items() if now - v["started"] < 120}
            if batch not in self.batches:
                if len(self.batches) >= 3:
                    raise ValueError("too many pending exports")
                self.batches[batch] = {"peer": peer, "parts": total, "chunks": {}, "started": now}
            pending = self.batches[batch]
            if pending["peer"] != peer or pending["parts"] != total:
                raise ValueError("inconsistent export batch")
            pending["chunks"][part] = files
            if sum(len(json.dumps(c).encode()) for c in pending["chunks"].values()) > 32 * 1024 * 1024:
                del self.batches[batch]
                raise ValueError("export exceeds 32 MiB")
            if len(pending["chunks"]) < total:
                return f"received part {part}/{total}"
            merged = {}
            for index in range(1, total + 1):
                chunk = pending["chunks"][index]
                if merged.keys() & chunk.keys():
                    raise ValueError("duplicate script path across export parts")
                merged.update(chunk)
            # Each export is a new snapshot. Never delete/replace the user's source tree.
            destination = self.exports / secrets.token_hex(16)
            destination.mkdir()
            for relative, source in merged.items():
                atomic_write(safe_path(destination, relative), source)
            del self.batches[batch]
            message = f"exported {len(merged)} scripts to {destination}"
            self.log("export", message)
            return message


def start_http(bridge: Bridge) -> tuple[ThreadingHTTPServer, threading.Thread]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args):
            pass

        def reply(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def handle_request(self):
            if self.headers.get("Origin") or not hmac.compare_digest(
                self.headers.get("X-Scratchpad-Token", "").encode(), bridge.token.encode()
            ):
                return self.reply(403, {"error": "pairing token required; browser origins are forbidden"})
            try:
                url = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if self.command == "GET":
                    if url.path == "/api/status":
                        return self.reply(200, bridge.status())
                    if url.path == "/api/changes":
                        return self.reply(200, {"files": bridge.changes(query["peer"])})
                    if url.path == "/api/commands/next":
                        command = bridge.poll(query["peer"], query["target"], query.get("place", ""), query.get("place_id", ""))
                        return self.reply(200, {"command": command})
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY:
                        return self.reply(413, {"error": "body must be 1 byte..4 MiB"})
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("expected a JSON object")
                    if url.path == "/api/results":
                        bridge.result(payload)
                        return self.reply(200, {"ok": True})
                    if url.path == "/api/ack":
                        bridge.acknowledge(payload)
                        return self.reply(200, {"ok": True})
                    if url.path == "/api/export":
                        return self.reply(200, {"message": bridge.export(payload)})
                    if url.path == "/api/log":
                        bridge.log(str(payload.get("kind", "info")), str(payload.get("message", "")), payload.get("path"))
                        return self.reply(200, {"ok": True})
                self.reply(404, {"error": "unknown endpoint"})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})
            except Exception:
                self.reply(500, {"error": "internal bridge error; check local files and permissions"})

        do_GET = handle_request
        do_POST = handle_request

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

    server = ThreadingHTTPServer(("127.0.0.1", bridge.port), Handler)
    server.daemon_threads = True
    bridge.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
