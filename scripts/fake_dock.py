"""Simulated Elgato Stream Deck Network Dock with a Stream Deck MK.2 attached.

Speaks the same Cora/TCP protocol as the real dock, so the integration (or
scripts/live_test.py) can be tested without hardware.

    .venv\\Scripts\\python.exe scripts\\fake_dock.py [--host 0.0.0.0] [--port 5343]
        [--child-port 20002] [--out fake_dock_out] [--mdns]

Interactive commands (stdin):  p <key>   press and release key (0-based)
                               h <key> <seconds>   hold key
                               q         quit
Received key images are saved to --out (key_<n>.jpg) plus sheet.png, an upright
view of the whole deck. --mdns announces the dock like a real one (_elg._tcp),
so Home Assistant will discover it: only use it on purpose.

Also importable: FakeDock is used by scripts/selftest_transport.py.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
from pathlib import Path
import struct
import sys
import threading

from PIL import Image

_LOGGER = logging.getLogger("fake_dock")

CORA_MAGIC = bytes((0x43, 0x93, 0x8A, 0x41))
HEADER = struct.Struct("<4sHBxII")
FLAG_VERBATIM = 0x8000
FLAG_ACK_NAK = 0x0200
OP_WRITE, OP_SEND_REPORT, OP_GET_REPORT = 0x00, 0x01, 0x02

DOCK_SERIAL = "FAKEDOCK000001"
DOCK_FIRMWARE = "1.01.013"
DOCK_MAC = "02:00:00:5a:00:01"
DECK_SERIAL = "FAKEDECK000001"
DECK_FIRMWARE = "1.02.000"
ELGATO_VID = 0x0FD9
MK2_PID = 0x0080
COLS, ROWS, KEY_SIZE = 5, 3, 72
KEYS = COLS * ROWS
KEEPALIVE_INTERVAL = 1.0


def _message(flags: int, op: int, message_id: int, payload: bytes) -> bytes:
    return HEADER.pack(CORA_MAGIC, flags, op, message_id, len(payload)) + payload


class _Connection:
    """One client connection to the dock port or the deck port."""

    def __init__(self, dock: FakeDock, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, child: bool) -> None:
        self.dock = dock
        self.reader = reader
        self.writer = writer
        self.child = child
        self.name = "deck" if child else "dock"

    def send(self, flags: int, op: int, message_id: int, payload: bytes) -> None:
        self.writer.write(_message(flags, op, message_id, payload))

    async def run(self) -> None:
        keepalive = asyncio.create_task(self._keepalive())
        buffer = bytearray()
        try:
            while data := await self.reader.read(65536):
                buffer += data
                while True:
                    start = buffer.find(CORA_MAGIC)
                    if start == -1:
                        del buffer[:-4]
                        break
                    del buffer[:start]
                    if len(buffer) < HEADER.size:
                        break
                    _, flags, op, message_id, length = HEADER.unpack_from(buffer)
                    if len(buffer) < HEADER.size + length:
                        break
                    payload = bytes(buffer[HEADER.size : HEADER.size + length])
                    del buffer[: HEADER.size + length]
                    self._handle(flags, op, message_id, payload)
                await self.writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            keepalive.cancel()
            self.writer.close()
            self.dock.connections.discard(self)
            _LOGGER.info("%s client disconnected", self.name)

    async def _keepalive(self) -> None:
        counter = 0
        while True:
            payload = bytearray(32)
            payload[0], payload[1], payload[5] = 0x01, 0x0A, counter & 0xFF
            self.send(0, OP_WRITE, counter, bytes(payload))
            counter += 1
            await asyncio.sleep(KEEPALIVE_INTERVAL)

    def _handle(self, flags: int, op: int, message_id: int, payload: bytes) -> None:
        if flags & FLAG_ACK_NAK:
            return  # keepalive acknowledged
        if op == OP_GET_REPORT:
            self._get_report(flags, message_id, payload)
        elif op == OP_SEND_REPORT:
            self.dock.feature_report(payload)
        elif op == OP_WRITE:
            self.dock.output_report(payload)

    def _get_report(self, flags: int, message_id: int, payload: bytes) -> None:
        if not self.child and payload[:1] == b"\x03":
            command = payload[1]
            reply = bytearray(128 if command == 0x1C else 32)
            if command == 0x80:
                reply[0], reply[1] = 0x03, 0x80
                reply[12:14] = ELGATO_VID.to_bytes(2, "little")
                reply[14:16] = (0xFFFF).to_bytes(2, "little")
            elif command == 0x83:
                reply[0], reply[1] = 0x03, 0x83
                reply[8:16] = DOCK_FIRMWARE.encode()
            elif command == 0x84:
                reply[0], reply[1], reply[3] = 0x03, 0x84, len(DOCK_SERIAL)
                reply[4 : 4 + len(DOCK_SERIAL)] = DOCK_SERIAL.encode()
            elif command == 0x1C:
                reply[0], reply[1] = 0x01, 0x0B
                if self.dock.deck_attached:
                    reply[4] = 0x02
                    reply[26:28] = ELGATO_VID.to_bytes(2, "little")
                    reply[28:30] = MK2_PID.to_bytes(2, "little")
                    reply[94 : 94 + len(DECK_SERIAL)] = DECK_SERIAL.encode()
                    reply[126:128] = self.dock.child_port.to_bytes(2, "little")
            else:
                _LOGGER.info("dock: unknown report %#04x", command)
                return
            self.send(0, OP_GET_REPORT, message_id, bytes(reply))
        elif self.child and payload:
            command = payload[0]
            if command == 0x05:
                firmware = DECK_FIRMWARE.encode()
                reply = bytearray(32)
                reply[0], reply[1] = 0x05, 4 + len(firmware)
                reply[6 : 6 + len(firmware)] = firmware
                self.send(FLAG_VERBATIM, OP_GET_REPORT, message_id, bytes(reply))
            else:
                _LOGGER.info("deck: unknown report %#04x", command)


class FakeDock:
    """The simulated dock: two TCP servers plus the state of the simulated deck."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5343, child_port: int = 20002, out: Path | None = None) -> None:
        self.host = host
        self.port = port
        self.child_port = child_port
        self.out = out
        self.deck_attached = True
        self.brightness: int | None = None
        self.resets = 0
        self.images: dict[int, bytes] = {}
        self.connections: set[_Connection] = set()
        self._parts: dict[int, bytearray] = {}
        self._servers: list[asyncio.base_events.Server] = []

    async def start(self) -> None:
        """Start listening on the dock and deck ports."""
        dock = await asyncio.start_server(lambda r, w: self._accept(r, w, child=False), self.host, self.port)
        deck = await asyncio.start_server(lambda r, w: self._accept(r, w, child=True), self.host, self.child_port)
        self._servers = [dock, deck]
        # Port 0 means "pick a free one" (used by the self test)
        self.port = dock.sockets[0].getsockname()[1]
        self.child_port = deck.sockets[0].getsockname()[1]
        _LOGGER.info("fake dock on %s:%s, deck on port %s", self.host, self.port, self.child_port)

    async def stop(self) -> None:
        """Close servers and connections."""
        for conn in list(self.connections):
            conn.writer.close()
        for server in self._servers:
            server.close()
            try:
                # Since Python 3.12 this also waits for open client connections
                async with asyncio.timeout(2):
                    await server.wait_closed()
            except TimeoutError:
                _LOGGER.info("clients still connected while stopping")

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, child: bool) -> None:
        conn = _Connection(self, reader, writer, child)
        self.connections.add(conn)
        _LOGGER.info("%s client connected", conn.name)
        await conn.run()

    def _deck_connections(self) -> list[_Connection]:
        return [c for c in self.connections if c.child]

    # Reports from the client

    def feature_report(self, payload: bytes) -> None:
        if payload[:2] == b"\x03\x08":
            self.brightness = payload[2]
            _LOGGER.info("brightness %s %%", self.brightness)
        elif payload[:2] == b"\x03\x02":
            self.resets += 1
            _LOGGER.info("reset to logo")

    def output_report(self, payload: bytes) -> None:
        if payload[:2] != b"\x02\x07":
            return
        key, last = payload[2], payload[3]
        length = int.from_bytes(payload[4:6], "little")
        part = int.from_bytes(payload[6:8], "little")
        if part == 0:
            self._parts[key] = bytearray()
        self._parts.setdefault(key, bytearray()).extend(payload[8 : 8 + length])
        if last:
            self.images[key] = bytes(self._parts.pop(key))
            self._save(key)

    def _save(self, key: int) -> None:
        if not self.out:
            return
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f"key_{key}.jpg").write_bytes(self.images[key])
        sheet = Image.new("RGB", (COLS * (KEY_SIZE + 8) + 8, ROWS * (KEY_SIZE + 8) + 8), (23, 24, 26))
        for index, jpeg in self.images.items():
            with Image.open(io.BytesIO(jpeg)) as tile:
                # The MK.2 shows images rotated by 180°; turn them back for an upright view
                upright = tile.rotate(180)
                sheet.paste(upright, (8 + (index % COLS) * (KEY_SIZE + 8), 8 + (index // COLS) * (KEY_SIZE + 8)))
        sheet.save(self.out / "sheet.png")

    # Simulated user input

    def set_key(self, index: int, pressed: bool) -> None:
        """Send a key state report (only this key changes)."""
        states = bytearray(KEYS)
        if pressed:
            states[index] = 1
        payload = bytes([0x01, 0x00, KEYS, 0x00]) + bytes(states)
        for conn in self._deck_connections():
            conn.send(FLAG_VERBATIM, OP_WRITE, 0, payload)
        _LOGGER.info("key %s %s", index, "down" if pressed else "up")

    async def press(self, index: int, hold: float = 0.1) -> None:
        """Press and release a key."""
        self.set_key(index, True)
        await asyncio.sleep(hold)
        self.set_key(index, False)

    def set_attached(self, attached: bool) -> None:
        """Plug the deck in or out: the dock announces it, an unplugged deck drops its connection."""
        self.deck_attached = attached
        for conn in [c for c in self.connections if not c.child]:
            # Unsolicited "device 2 info", like the real dock on hot-plug
            conn.send(0, OP_GET_REPORT, 0, bytes([0x01, 0x0B]) + bytes(126))
        if not attached:
            for conn in self._deck_connections():
                conn.writer.close()


async def _announce(dock: FakeDock):  # pragma: no cover - manual use only
    from zeroconf import IPVersion, ServiceInfo
    from zeroconf.asyncio import AsyncZeroconf

    import socket

    address = socket.gethostbyname(socket.gethostname()) if dock.host in ("0.0.0.0", "") else dock.host
    info = ServiceInfo(
        "_elg._tcp.local.",
        f"Fake Stream Deck Network Dock {DOCK_SERIAL[-4:]}._elg._tcp.local.",
        addresses=[socket.inet_aton(address)],
        port=dock.port,
        properties={"dt": "215", "sn": DOCK_SERIAL, "id": DOCK_MAC.upper(), "fw": DOCK_FIRMWARE, "mf": "Elgato"},
    )
    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    await zc.async_register_service(info)
    _LOGGER.info("announced via mDNS at %s:%s", address, dock.port)
    return zc


async def _main(args: argparse.Namespace) -> None:  # pragma: no cover - manual use only
    dock = FakeDock(args.host, args.port, args.child_port, Path(args.out))
    await dock.start()
    zc = await _announce(dock) if args.mdns else None
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _stdin() -> None:
        for line in sys.stdin:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "q":
                loop.call_soon_threadsafe(stop.set)
                return
            if parts[0] in ("p", "h") and len(parts) >= 2:
                hold = float(parts[2]) if parts[0] == "h" and len(parts) > 2 else 0.1
                asyncio.run_coroutine_threadsafe(dock.press(int(parts[1]), hold), loop)
        loop.call_soon_threadsafe(stop.set)

    threading.Thread(target=_stdin, daemon=True).start()
    print("commands: p <key> | h <key> <seconds> | q", flush=True)
    await stop.wait()
    if zc:
        await zc.async_close()
    await dock.stop()


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5343)
    parser.add_argument("--child-port", type=int, default=20002)
    parser.add_argument("--out", default="fake_dock_out")
    parser.add_argument("--mdns", action="store_true")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(_main(parser.parse_args()))
