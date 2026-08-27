"""Tests for chatterbox/power/ipc.py. encode_msg/decode_line are pure and always run. The
PowerdServer live-loopback test needs a real unix socket -- skipped on Windows (this repo's dev
checkout), matching the platform-gated pattern tests/test_profiling.py already uses for
Linux-only hardware I/O."""
import asyncio
import sys

import pytest

import chatterbox.power.ipc as ipc
from chatterbox.power.ipc import PowerdServer, decode_line, encode_msg


def test_encode_msg_is_newline_terminated_utf8_json():
    data = encode_msg({"type": "activity"})
    assert isinstance(data, bytes)
    assert data.endswith(b"\n")
    assert data == b'{"type": "activity"}\n'


def test_decode_line_accepts_bytes_and_str():
    assert decode_line(b'{"type": "activity"}\n') == {"type": "activity"}
    assert decode_line('{"type": "activity"}') == {"type": "activity"}


def test_encode_decode_roundtrip():
    payload = {"type": "amp_ack", "state": "on"}
    assert decode_line(encode_msg(payload)) == payload


def test_decode_line_missing_type_raises_value_error():
    with pytest.raises(ValueError):
        decode_line('{"value": "no type field"}')


def test_decode_line_malformed_json_raises_value_error():
    with pytest.raises(ValueError):
        decode_line("not json at all {")


def test_decode_line_empty_raises_value_error():
    with pytest.raises(ValueError):
        decode_line("")
    with pytest.raises(ValueError):
        decode_line("   \n")


def test_decode_line_non_dict_raises_value_error():
    with pytest.raises(ValueError):
        decode_line("[1, 2, 3]")


class _StubFSM:
    """Minimal stand-in for chatterbox.power.fsm.PowerFSM's on_activity/on_command surface."""

    def __init__(self):
        self.activity_calls = []
        self.commands = []

    def on_activity(self, source):
        self.activity_calls.append(source)

    def on_command(self, cmd):
        self.commands.append(cmd)
        if cmd == "AMP_ON":
            return ("amp_ack", "on")
        if cmd == "AMP_OFF":
            return ("amp_ack", "off")
        if cmd == "GET_STATE":
            return ("state", "ACTIVE")
        return None


async def _server_client_roundtrip(socket_path):
    fsm = _StubFSM()
    server = PowerdServer(socket_path, "chatterbox", fsm)
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(path=socket_path)

        writer.write(encode_msg({"type": "activity"}))
        await writer.drain()
        await asyncio.sleep(0.05)  # give the server's reader loop a moment to run
        assert fsm.activity_calls == ["socket"]

        writer.write(encode_msg({"type": "amp_on"}))
        await writer.drain()
        reply = decode_line(await reader.readline())
        assert reply == {"type": "amp_ack", "state": "on"}

        writer.write(encode_msg({"type": "get_state"}))
        await writer.drain()
        reply = decode_line(await reader.readline())
        assert reply == {"type": "state", "value": "ACTIVE"}

        # Server-initiated broadcast (PowerFSM's broadcast_fn) reaches the connected client too.
        server.broadcast({"type": "state", "value": "DIM"})
        reply = decode_line(await reader.readline())
        assert reply == {"type": "state", "value": "DIM"}

        writer.close()
    finally:
        server.close()


@pytest.mark.skipif(sys.platform.startswith("win"),
                     reason="asyncio unix-domain sockets are unavailable on Windows")
def test_server_client_roundtrip(tmp_path):
    socket_path = str(tmp_path / "powerd_test.sock")
    asyncio.run(_server_client_roundtrip(socket_path))
