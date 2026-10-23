"""Minimal WebSocket client (stdlib only) to exercise the Stream Assistant API on the HA host.

Runs inside the SSH add-on, which has no third-party packages but has
$SUPERVISOR_TOKEN and reaches Core through the Supervisor proxy.

Usage (on the HA host): python3 ws_probe.py '<json command without id>' ['<json>' ...]
Prints each result, base64 image payloads shortened.
"""

import base64
import json
import os
import socket
import struct
import sys

HOST, PORT, PATH = "supervisor", 80, "/core/websocket"


def send(sock, text):
    data = text.encode()
    header = bytearray([0x81])
    if len(data) < 126:
        header.append(0x80 | len(data))
    elif len(data) < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", len(data))
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", len(data))
    mask = os.urandom(4)
    header += mask
    sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def recv(sock):
    message = b""
    while True:
        b1, b2 = recv_exact(sock, 2)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", recv_exact(sock, 8))[0]
        message += recv_exact(sock, length)
        if b1 & 0x80:
            return json.loads(message)


def shorten(value):
    if isinstance(value, dict):
        return {k: shorten(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 40 and all(isinstance(v, str) for v in value):
            return f"[{len(value)} strings]"
        return [shorten(v) for v in value]
    if isinstance(value, str) and len(value) > 120:
        return f"<{len(value)} chars>"
    return value


sock = socket.create_connection((HOST, PORT), timeout=20)
key = base64.b64encode(os.urandom(16)).decode()
sock.sendall(
    f"GET {PATH} HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
)
response = b""
while b"\r\n\r\n" not in response:
    response += sock.recv(1)
assert b" 101 " in response.split(b"\r\n")[0], response
recv(sock)  # auth_required
send(sock, json.dumps({"type": "auth", "access_token": os.environ["SUPERVISOR_TOKEN"]}))
auth = recv(sock)
assert auth["type"] == "auth_ok", auth

for i, raw in enumerate(sys.argv[1:], start=1):
    command = json.loads(raw)
    command["id"] = i
    send(sock, json.dumps(command))
    while True:
        reply = recv(sock)
        if reply.get("id") == i:
            print(json.dumps(shorten(reply), ensure_ascii=False))
            break
