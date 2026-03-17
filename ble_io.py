#!/usr/bin/env python3
from __future__ import annotations

import socket
import sys
from typing import Iterator, Optional

from db import Database
from packet_format import UINT32_STRUCT
from session_manager import process_packet_stream


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def iter_socket_packets(conn: socket.socket) -> Iterator[bytes]:
    while True:
        hdr = recv_exact(conn, UINT32_STRUCT.size)
        (n,) = UINT32_STRUCT.unpack(hdr)
        if n <= 0 or n > 10_000_000:
            raise ValueError(f"invalid packet length from socket: {n}")
        yield recv_exact(conn, n)


def serve_tcp(host: str, port: int, db_path: Optional[str], out_ndjson: Optional[str], stdout_events: bool) -> int:
    db = Database(db_path) if db_path else None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(1)
            print(f"Listening on {host}:{port}", file=sys.stderr)
            conn, addr = srv.accept()
            with conn:
                print(f"Client connected: {addr}", file=sys.stderr)
                try:
                    process_packet_stream(
                        iter_socket_packets(conn),
                        db=db,
                        source=f"tcp://{addr[0]}:{addr[1]}",
                        out_ndjson_path=out_ndjson,
                        stdout_events=stdout_events,
                        summary_only=False,
                    )
                except EOFError:
                    print("Client disconnected", file=sys.stderr)
        return 0
    finally:
        if db is not None:
            db.close()
