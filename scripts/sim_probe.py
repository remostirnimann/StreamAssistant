"""Drive the bridge simulator page from the command line (stdlib only, runs on the HA host).

Usage: python3 sim_probe.py [--port 5390] state|press <device> <key>|plug <device> on|off
`state` prints which keys show images or colours, and the brightness.
"""

import argparse
import base64
import json
import os
import socket
import struct
import time


def connect(port):
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET /sim/ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
    )
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(1)
    assert b" 101 " in response.split(b"\r\n")[0], response
    return sock


def send(sock, message):
    data = json.dumps(message).encode()
    header = (
        bytearray([0x81, 0x80 | len(data)])
        if len(data) < 126
        else bytearray([0x81, 0x80 | 126]) + struct.pack(">H", len(data))
    )
    mask = os.urandom(4)
    sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5390)
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()
    sock = connect(args.port)
    state = recv(sock)
    command = args.command
    if command[0] == "state":
        for device in state["devices"]:
            keys = {int(k): ("image" if "image" in v else v.get("color")) for k, v in device["keys"].items()}
            print(
                f"{device['id']}: plugged={device['plugged']} brightness={device['brightness']} "
                f"keys with content={sorted(keys)} ({len(keys)} of {device['cols'] * device['rows']})"
            )
    elif command[0] == "press":
        send(sock, {"type": "press", "device": command[1], "key": int(command[2]), "pressed": True})
        time.sleep(float(command[3]) if len(command) > 3 else 0.1)
        send(sock, {"type": "press", "device": command[1], "key": int(command[2]), "pressed": False})
        time.sleep(0.2)
        print("pressed")
    elif command[0] == "plug":
        send(sock, {"type": "plug", "device": command[1], "plugged": command[2] == "on"})
        time.sleep(0.3)
        print("done")
    sock.close()


main()
