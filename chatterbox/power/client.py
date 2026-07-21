#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The "tiny reusable powerd client" asked for by chatterbox-powerd_spec_v0.1.md Sec9.3/9.4 --
one implementation, one process-wide shared singleton (get_client()), used by both
chatterbox/audio/playback.py (amp handshake) and chatterbox/gui/app.py (activity/put_away/input).

Tkinter's mainloop is not asyncio-aware, so this runs its own background thread with its own
asyncio event loop and exposes a small thread-safe, blocking-with-timeout API. Every public method
degrades to a silent no-op (never raises, never blocks longer than its stated timeout) if powerd
isn't reachable -- this is what keeps playback/GUI behavior identical to a no-powerd checkout (any
PC dev machine, or a Pi before powerd is set up).

v0.1 scope note: if the initial connection fails, or an established connection drops, this client
does not auto-reconnect -- it becomes a permanent no-op for the rest of the process (get_client()
still returns the same, now-disabled, instance). A GUI/CLI restart is required to reconnect if
powerd restarts mid-session. See docs/power/POWERD.md.
"""
import asyncio
import sys
import threading
import time

from . import ipc
from . import config as power_config
from chatterbox.config import paths as cb_paths

DEFAULT_SOCKET_PATH = "/run/chatterbox/powerd.sock"


class PowerdClient:
    def __init__(self, socket_path=None, connect_timeout=0.3):
        self._explicit_socket_path = socket_path
        self.connect_timeout = connect_timeout

        self._loop = None
        self._thread = None
        self._start_lock = threading.Lock()

        self._writer = None
        self._connected = False
        self._disabled = False

        self._pending = {}  # msg type -> asyncio.Future, at most one outstanding request per type
        self._input_handler = None

    # -- lifecycle ------------------------------------------------------------------

    def _resolve_socket_path(self):
        if self._explicit_socket_path:
            return self._explicit_socket_path
        try:
            cfg, _warnings = power_config.load_config(str(cb_paths.USER_PREFS_PATH))
            return cfg["socket"]["path"]
        except Exception:  # noqa: BLE001 -- socket-path resolution must never block startup;
            # fall back to the documented default and let the connect attempt itself fail loudly.
            return DEFAULT_SOCKET_PATH

    def _ensure_started(self):
        with self._start_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run_loop, name="powerd-client", daemon=True)
            self._thread.start()
            for _ in range(100):  # up to ~1s; in practice self._loop is set within a millisecond
                if self._loop is not None:
                    return
                time.sleep(0.01)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_serve())
        finally:
            self._disabled = True
            self._loop.close()

    async def _connect_and_serve(self):
        socket_path = self._resolve_socket_path()
        try:
            reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(path=socket_path), timeout=self.connect_timeout)
        except Exception as exc:  # noqa: BLE001 -- any connect failure (no socket, refused,
            # timeout, not-unix-capable platform) degrades to "power features disabled", not a
            # crash -- this is the behavior that keeps every non-Pi/no-powerd checkout unaffected.
            print("[powerd-client] could not connect to {}: {} -- power features disabled for "
                  "this process".format(socket_path, exc), file=sys.stderr)
            return

        self._connected = True
        print("[powerd-client] connected to {}".format(socket_path))
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = ipc.decode_line(line)
                except ValueError:
                    continue
                self._handle_message(msg)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self._connected = False
            print("[powerd-client] disconnected from powerd", file=sys.stderr)

    def _handle_message(self, msg):
        """Runs on the client's own loop thread (called from _connect_and_serve's reader loop)."""
        msg_type = msg.get("type")
        if msg_type == "input":
            if self._input_handler is not None:
                try:
                    self._input_handler(msg.get("action"))
                except Exception as exc:  # noqa: BLE001 -- a broken handler must not kill the
                    # client's read loop.
                    print("[powerd-client] input handler raised: {}".format(exc), file=sys.stderr)
            return
        future = self._pending.pop(msg_type, None)
        if future is not None and not future.done():
            future.set_result(msg)

    def _send(self, payload):
        if self._writer is None:
            return False
        try:
            self._writer.write(ipc.encode_msg(payload))
        except Exception:  # noqa: BLE001 -- a write against a half-closed socket must not raise
            # into the (possibly cross-thread) caller.
            return False
        return True

    async def _async_request(self, payload, expect_type, timeout):
        if not self._connected:
            return None
        future = self._loop.create_future()
        self._pending[expect_type] = future
        if not self._send(payload):
            self._pending.pop(expect_type, None)
            return None
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending.pop(expect_type, None)

    def _call_async(self, make_coro, timeout):
        """Runs a coroutine (built by make_coro(), a zero-arg callable so it's only constructed on
        the loop thread) on the client's background loop from any external thread, blocking the
        caller up to `timeout`. Returns None on any failure/timeout/disabled-client."""
        if self._disabled:
            return None
        self._ensure_started()
        if self._loop is None or self._disabled:
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(make_coro(), self._loop)
            return future.result(timeout=timeout)
        except Exception:  # noqa: BLE001 -- covers concurrent.futures.TimeoutError, a closed
            # loop, or any protocol-level failure; all mean "treat as unreachable this time".
            return None

    # -- public, thread-safe API -----------------------------------------------------

    def set_input_handler(self, callback):
        """callback(action: str), invoked on the client's background thread for every forwarded
        switch press -- callers (chatterbox/gui/app.py) must marshal it onto their own thread
        (e.g. a queue.Queue drained via Tk's window.after()) before touching Tk widgets."""
        self._input_handler = callback

    def send_activity(self):
        """Fire-and-forget -- never blocks, never raises."""
        if self._disabled:
            return
        self._ensure_started()
        if self._loop is None or self._disabled:
            return
        self._loop.call_soon_threadsafe(self._send, {"type": "activity"})

    def request_amp(self, on, timeout=0.05):
        """Blocking up to `timeout`. Returns True iff powerd acked with the requested state;
        False (never raises) if powerd is unreachable, the request times out, or it acks with an
        unexpected state -- callers should treat False as "proceed without the amp handshake"."""
        payload = {"type": "amp_on" if on else "amp_off"}
        reply = self._call_async(
            lambda: self._async_request(payload, "amp_ack", timeout), timeout + 0.1)
        return bool(reply) and reply.get("state") == ("on" if on else "off")

    def send_put_away(self):
        if self._disabled:
            return
        self._ensure_started()
        if self._loop is None or self._disabled:
            return
        self._loop.call_soon_threadsafe(self._send, {"type": "put_away"})

    def send_reload(self):
        """Fire-and-forget -- tells powerd to re-read user_prefs.yaml (chatterbox/gui/settings.py
        calls this after a successful save)."""
        if self._disabled:
            return
        self._ensure_started()
        if self._loop is None or self._disabled:
            return
        self._loop.call_soon_threadsafe(self._send, {"type": "reload"})

    def get_state(self, timeout=0.2):
        """Returns the FSM state name, or None if unreachable/timed out."""
        reply = self._call_async(
            lambda: self._async_request({"type": "get_state"}, "state", timeout), timeout + 0.1)
        return reply.get("value") if reply else None

    def is_connected(self):
        return self._connected


_client = None
_client_lock = threading.Lock()


def get_client():
    """The process-wide shared PowerdClient -- see module docstring."""
    global _client
    with _client_lock:
        if _client is None:
            _client = PowerdClient()
        return _client
