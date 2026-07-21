#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The powerd<->client socket protocol (chatterbox-powerd_spec_v0.1.md Sec6): a unix stream
socket, newline-delimited JSON, bidirectional. powerd is the server; the GUI process (which
contains playback) is one persistent client, reconnectable.

encode_msg/decode_line are pure (tested directly, no socket needed -- tests/test_power_ipc.py).
PowerdServer does the actual asyncio unix-socket I/O; only exercised end-to-end on Linux (the
platform-gated half of test_power_ipc.py), since asyncio's unix-socket support isn't available on
Windows.
"""
import asyncio
import json
import os
import subprocess
import sys
import time

_COMMANDS = {
    "amp_on": "AMP_ON",
    "amp_off": "AMP_OFF",
    "put_away": "PUT_AWAY",
    "get_state": "GET_STATE",
    "reload": "RELOAD",
}


def encode_msg(payload):
    """dict -> newline-terminated UTF-8 JSON bytes, ready to write to the socket."""
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode_line(line):
    """bytes or str (one line, with or without the trailing newline) -> dict. Raises ValueError
    (json.JSONDecodeError is a ValueError subclass) on anything malformed -- callers should catch
    ValueError and log+skip rather than let one bad client message take the connection down."""
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    if not line:
        raise ValueError("empty line")
    parsed = json.loads(line)
    if not isinstance(parsed, dict) or "type" not in parsed:
        raise ValueError("message missing 'type' field: {!r}".format(parsed))
    return parsed


class PowerdServer:
    """Server half of the protocol. Owns the client connection set and dispatches parsed messages
    into a PowerFSM. Server-initiated broadcasts (state changes, forwarded switch presses) go to
    every connected client."""

    def __init__(self, socket_path, group, fsm):
        self.socket_path = socket_path
        self.group = group
        self.fsm = fsm
        self._clients = set()
        self._server = None

    async def start(self):
        run_dir = os.path.dirname(self.socket_path) or "."
        os.makedirs(run_dir, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)  # stale socket from a previous crash/unclean shutdown
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        self._chmod_and_chown()
        print("[powerd] socket: listening on {}".format(self.socket_path))

    def _chmod_and_chown(self):
        try:
            os.chmod(self.socket_path, 0o660)
        except OSError as exc:
            print("[powerd] socket: chmod failed: {}".format(exc), file=sys.stderr)
        try:
            import grp
            gid = grp.getgrnam(self.group).gr_gid
            os.chown(self.socket_path, -1, gid)
        except (ImportError, KeyError, OSError, PermissionError) as exc:
            print("[powerd] socket: could not chgrp to '{}': {} -- clients in that group may not "
                  "be able to connect".format(self.group, exc), file=sys.stderr)

    async def _handle_client(self, reader, writer):
        self._clients.add(writer)
        peer = "client#{}".format(id(writer))
        print("[powerd] {} connected".format(peer))
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = decode_line(line)
                except ValueError as exc:
                    print("[powerd] {}: malformed message ignored: {}".format(peer, exc), file=sys.stderr)
                    continue
                await self._dispatch(msg, writer)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._clients.discard(writer)
            writer.close()
            print("[powerd] {} disconnected".format(peer))

    async def _dispatch(self, msg, writer):
        msg_type = msg.get("type")
        if msg_type == "activity":
            self.fsm.on_activity("socket")
            return
        cmd = _COMMANDS.get(msg_type)
        if cmd is None:
            print("[powerd] unknown message type ignored: {!r}".format(msg_type), file=sys.stderr)
            return
        reply = self.fsm.on_command(cmd)
        if reply is None:
            return
        reply_type, reply_value = reply
        if reply_type == "amp_ack":
            payload = {"type": "amp_ack", "state": reply_value}
        else:  # "state"
            payload = {"type": "state", "value": reply_value}
        writer.write(encode_msg(payload))
        try:
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def broadcast(self, payload):
        """Sync (not async) by design -- this is PowerFSM's broadcast_fn, called inline from
        plain synchronous FSM code. Best-effort: a full transport buffer or a dead client is
        logged and dropped, never raised back into the FSM."""
        data = encode_msg(payload)
        for writer in list(self._clients):
            try:
                writer.write(data)
            except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                print("[powerd] broadcast to a client failed, dropping it: {}".format(exc), file=sys.stderr)
                self._clients.discard(writer)

    def dispatch_action(self, action):
        """Forward a physical switch press to every connected client (chatterbox/power/inputs.py's
        dispatch_action callback)."""
        self.broadcast({"type": "input", "action": action})

    def close(self):
        """Best-effort synchronous shutdown for PowerFSM's halt_fn (DEEP is a one-way trip to
        `systemctl halt` -- there's no point awaiting a graceful asyncio drain when the process is
        about to halt regardless). Gives the kernel a brief moment to flush the already-queued DEEP
        broadcast before closing."""
        for writer in list(self._clients):
            try:
                writer.close()
            except OSError:
                pass
        self._clients.clear()
        if self._server is not None:
            self._server.close()
        time.sleep(0.05)
        try:
            os.remove(self.socket_path)
        except OSError:
            pass

    def halt(self):
        self.close()
        print("[powerd] halting: systemctl halt")
        subprocess.run(["systemctl", "halt"])
