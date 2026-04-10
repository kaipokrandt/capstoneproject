#!/usr/bin/env python3
from __future__ import annotations

import struct
import zlib
from typing import List

MAGIC = b"WBS1"
VERSION = 1
PAD_TYPE_SINGLE = 1

HEADER_STRUCT = struct.Struct("<4sBBH")
META_STRUCT = struct.Struct("<QHHBBH")
CRC_STRUCT = struct.Struct("<I")
UINT32_STRUCT = struct.Struct("<I")

FLAG_PACKET_LOSS_SIM = 1 << 0
FLAG_INTERPOLATED = 1 << 1
FLAG_CALIB_APPLIED = 1 << 2
FLAG_ACCEL_PRESENT = 1 << 3


def build_packet(
    ts_us: int,
    gw: int,
    gh: int,
    battery_pct: int,
    flags: int,
    adc_flat: List[int],
) -> bytes:
    """
    Build one packet carrying raw ADC-like samples from the sensor grid.
    """
    header = HEADER_STRUCT.pack(MAGIC, VERSION, flags & 0xFF, 0)
    meta = META_STRUCT.pack(ts_us, gw, gh, battery_pct & 0xFF, PAD_TYPE_SINGLE, 0)
    pdata = struct.pack("<" + "h" * (gw * gh), *adc_flat)
    blob_wo_crc = header + meta + pdata
    crc = zlib.crc32(blob_wo_crc) & 0xFFFFFFFF
    return blob_wo_crc + CRC_STRUCT.pack(crc)
