#!/usr/bin/env python3
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import BinaryIO, Iterator, List

from packet_format import CRC_STRUCT, HEADER_STRUCT, MAGIC, META_STRUCT, UINT32_STRUCT, VERSION


@dataclass
class PacketDecoded:
    ts_us: int
    gw: int
    gh: int
    battery_pct: int
    pad_type: int
    flags: int
    adc_flat: List[int]


def verify_and_decode_packet(packet: bytes) -> PacketDecoded:
    min_len = HEADER_STRUCT.size + META_STRUCT.size + CRC_STRUCT.size
    if len(packet) < min_len:
        raise ValueError("packet too short")

    payload = packet[:-CRC_STRUCT.size]
    crc_expected = CRC_STRUCT.unpack(packet[-CRC_STRUCT.size:])[0]
    crc_actual = zlib.crc32(payload) & 0xFFFFFFFF
    if crc_actual != crc_expected:
        raise ValueError(f"crc mismatch: expected={crc_expected:#010x}, actual={crc_actual:#010x}")

    magic, version, flags, _ = HEADER_STRUCT.unpack_from(packet, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported version: {version}")

    off = HEADER_STRUCT.size
    ts_us, gw, gh, battery_pct, pad_type, _ = META_STRUCT.unpack_from(packet, off)
    off += META_STRUCT.size

    count = gw * gh
    adc_len = 2 * count
    if len(packet) != HEADER_STRUCT.size + META_STRUCT.size + adc_len + CRC_STRUCT.size:
        raise ValueError("packet length inconsistent with grid dimensions")

    adc_flat = list(struct.unpack_from("<" + "h" * count, packet, off))
    return PacketDecoded(
        ts_us=ts_us,
        gw=gw,
        gh=gh,
        battery_pct=battery_pct,
        pad_type=pad_type,
        flags=flags,
        adc_flat=adc_flat,
    )


def iter_length_prefixed_packets(fp: BinaryIO) -> Iterator[bytes]:
    while True:
        hdr = fp.read(UINT32_STRUCT.size)
        if not hdr:
            break
        if len(hdr) != UINT32_STRUCT.size:
            raise ValueError("truncated packet length prefix")
        (n,) = UINT32_STRUCT.unpack(hdr)
        if n <= 0:
            raise ValueError("invalid packet length")
        data = fp.read(n)
        if len(data) != n:
            raise ValueError("truncated packet body")
        yield data
