#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from ble_io import serve_tcp
from db import Database
from pad_decoder import iter_length_prefixed_packets
from session_manager import process_packet_stream


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Backend for Wearable Balance Sensor synthetic/live packet ingestion.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("replay", help="Process a generator replay file")
    rp.add_argument("input_bin", help="Length-prefixed packet replay file")
    rp.add_argument("--db", default=None, help="SQLite database path")
    rp.add_argument("--out_ndjson", default=None, help="Write per-frame events and summary to NDJSON")
    rp.add_argument("--stdout_events", action="store_true", help="Emit per-frame events to stdout")
    rp.add_argument("--summary_only", action="store_true", help="Only print session summary")

    sp = sub.add_parser("serve", help="Listen for a live TCP stream of length-prefixed packets")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=9009)
    sp.add_argument("--db", default=None, help="SQLite database path")
    sp.add_argument("--out_ndjson", default=None, help="Write events to NDJSON")
    sp.add_argument("--stdout_events", action="store_true")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.cmd == "replay":
        db = Database(args.db) if args.db else None
        try:
            with open(args.input_bin, "rb") as fh:
                summary = process_packet_stream(
                    iter_length_prefixed_packets(fh),
                    db=db,
                    source=os.path.abspath(args.input_bin),
                    out_ndjson_path=args.out_ndjson,
                    stdout_events=args.stdout_events,
                    summary_only=args.summary_only,
                )
            print(
                f"Processed {summary.frames} frames, duration={summary.duration_s:.2f}s, "
                f"risk={summary.risk_label} ({summary.risk_score:.1f})",
                file=sys.stderr,
            )
            return 0
        finally:
            if db is not None:
                db.close()

    if args.cmd == "serve":
        return serve_tcp(args.host, args.port, args.db, args.out_ndjson, args.stdout_events)

    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
