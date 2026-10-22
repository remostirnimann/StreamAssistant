"""Cora framing used by the Elgato Stream Deck Network Dock.

Every message is a 16 byte header followed by a payload:

    0..3   magic 43 93 8a 41
    4..5   flags (uint16 LE)
    6      HID operation
    8..11  message id (uint32 LE)
    12..15 payload length (uint32 LE)

The dock sends keepalives (payload starting 01 0a) which must be ACKed,
otherwise it drops the connection.

Protocol reference: Julusian/node-elgato-stream-deck (packages/tcp), MIT.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import random
import struct
import time

_LOGGER = logging.getLogger(__name__)

CORA_MAGIC = bytes((0x43, 0x93, 0x8A, 0x41))
HEADER = struct.Struct("<4sHBxII")

FLAG_NONE = 0x0000
FLAG_VERBATIM = 0x8000
FLAG_REQ_ACK = 0x4000
FLAG_ACK_NAK = 0x0200
FLAG_RESULT = 0x0100

OP_WRITE = 0x00
OP_SEND_REPORT = 0x01
OP_GET_REPORT = 0x02

CONNECT_TIMEOUT = 8.0
REPORT_TIMEOUT = 5.0
IDLE_TIMEOUT = 5.0

# Report id the dock uses for "device 2 (child) info", both as reply and as hotplug notification
REPORT_CHILD_INFO = 0x1C


class CoraError(Exception):
    """Raised when talking to a Cora device fails."""


@dataclass(slots=True)
class CoraMessage:
    """A single Cora message."""

    flags: int
    hid_op: int
    message_id: int
    payload: bytes


class CoraConnection:
    """One TCP connection to a dock port (the dock itself or an attached deck)."""

    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.on_input: Callable[[bytes], None] | None = None
        self.on_child_info: Callable[[bytes], None] | None = None
        self.on_closed: Callable[[], None] | None = None

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._pending: dict[int, asyncio.Future[bytes]] = {}
        self._last_received = 0.0
        self._closed = False

    @property
    def connected(self) -> bool:
        """Return True once the first keepalive arrived and the socket is still open."""
        return self._ready.is_set() and not self._closed

    async def connect(self) -> None:
        """Open the socket and wait for the first keepalive."""
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port
                )
                self._last_received = time.monotonic()
                self._read_task = asyncio.create_task(
                    self._read_loop(), name=f"cora-read-{self.name}"
                )
                await self._ready.wait()
        except (OSError, TimeoutError) as err:
            await self.close()
            raise CoraError(
                f"{self.name}: cannot connect to {self.host}:{self.port} ({err!r}). "
                "Is another client (Companion, Stream Deck app) connected?"
            ) from err
        self._watchdog_task = asyncio.create_task(
            self._watchdog(), name=f"cora-watchdog-{self.name}"
        )

    async def close(self) -> None:
        """Close the connection. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        current = asyncio.current_task()
        for task in (self._read_task, self._watchdog_task):
            if task and task is not current:
                task.cancel()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(CoraError(f"{self.name}: disconnected"))
        self._pending.clear()
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        if self.on_closed:
            self.on_closed()

    async def _watchdog(self) -> None:
        while not self._closed:
            await asyncio.sleep(1)
            if time.monotonic() - self._last_received > IDLE_TIMEOUT:
                _LOGGER.debug("%s: no data for %ss, closing", self.name, IDLE_TIMEOUT)
                await self.close()
                return

    async def _read_loop(self) -> None:
        assert self._reader
        buffer = bytearray()
        try:
            while True:
                data = await self._reader.read(65536)
                if not data:
                    break
                self._last_received = time.monotonic()
                buffer += data
                self._consume(buffer)
        except (OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.debug("%s: read error %r", self.name, err)
        except asyncio.CancelledError:
            return
        await self.close()

    def _consume(self, buffer: bytearray) -> None:
        while True:
            start = buffer.find(CORA_MAGIC)
            if start == -1:
                # Keep the tail, it may be the start of the next magic
                del buffer[:-4]
                return
            if start:
                del buffer[:start]
            if len(buffer) < HEADER.size:
                return
            _, flags, hid_op, message_id, length = HEADER.unpack_from(buffer)
            if len(buffer) < HEADER.size + length:
                return
            payload = bytes(buffer[HEADER.size : HEADER.size + length])
            del buffer[: HEADER.size + length]
            self._handle(CoraMessage(flags, hid_op, message_id, payload))

    def _handle(self, msg: CoraMessage) -> None:
        p = msg.payload
        if len(p) > 5 and p[0] == 0x01 and p[1] == 0x0A:
            ack = bytearray(32)
            ack[0], ack[1], ack[2] = 0x03, 0x1A, p[5]
            self._send(FLAG_ACK_NAK, msg.hid_op, msg.message_id, bytes(ack))
            if not self._ready.is_set():
                _LOGGER.debug("%s: connected (connection #%s)", self.name, p[5])
                self._ready.set()
            return

        # Same matching rules as the reference implementation
        if len(p) > 1 and p[0] == 0x01 and p[1] == 0x0B:
            key = REPORT_CHILD_INFO
        elif p and p[0] == 0x01:
            if self.on_input:
                self.on_input(p[1:])
            return
        elif msg.flags & FLAG_VERBATIM:
            key = p[0] if p else -1
        else:
            key = p[1] if len(p) > 1 else -1

        future = self._pending.pop(key, None)
        if future and not future.done():
            future.set_result(p)
        elif key == REPORT_CHILD_INFO and self.on_child_info:
            # Unsolicited: a deck was plugged in or removed
            self.on_child_info(p)
        else:
            _LOGGER.debug(
                "%s: unhandled flags=%#06x op=%s payload=%s",
                self.name,
                msg.flags,
                msg.hid_op,
                p[:24].hex(),
            )

    def _send(self, flags: int, hid_op: int, message_id: int, payload: bytes) -> None:
        if self._closed or not self._writer:
            raise CoraError(f"{self.name}: not connected")
        self._writer.write(
            HEADER.pack(CORA_MAGIC, flags, hid_op, message_id, len(payload)) + payload
        )

    async def drain(self) -> None:
        """Wait until the socket buffer is flushed."""
        if self._writer and not self._closed:
            await self._writer.drain()

    async def get_report(self, command: int, *, to_host: bool) -> bytes:
        """Request a feature report.

        to_host=True addresses the dock itself, False passes the request
        verbatim to the attached deck.
        """
        if command in self._pending:
            return await asyncio.shield(self._pending[command])
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._pending[command] = future
        message_id = random.randrange(0xFFFFFF)
        if to_host:
            self._send(FLAG_NONE, OP_GET_REPORT, message_id, bytes((0x03, command)))
        else:
            self._send(FLAG_VERBATIM, OP_GET_REPORT, message_id, bytes((command,)))
        try:
            async with asyncio.timeout(REPORT_TIMEOUT):
                return await future
        except TimeoutError as err:
            raise CoraError(f"{self.name}: timeout on report {command:#04x}") from err
        finally:
            self._pending.pop(command, None)

    def send_feature_report(self, data: bytes) -> None:
        """Send a feature report to the attached deck."""
        self._send(FLAG_VERBATIM, OP_SEND_REPORT, 0, data)

    def write_reports(self, reports: list[bytes]) -> None:
        """Send output reports to the attached deck (written back to back)."""
        for report in reports:
            self._send(FLAG_VERBATIM, OP_WRITE, 0, report)
