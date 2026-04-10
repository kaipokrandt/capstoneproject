#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import request
from urllib.error import HTTPError
from http.cookiejar import CookieJar


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _import_legacy_modules() -> None:
    legacy_path = _repo_root() / "legacy"
    if str(legacy_path) not in sys.path:
        sys.path.insert(0, str(legacy_path))


def _json_bytes(data: Dict[str, Any]) -> bytes:
    return json.dumps(data).encode("utf-8")


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie_jar = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookie_jar))

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _csrf(self) -> str:
        req = request.Request(self._url("/api/auth/csrf/"), method="GET")
        with self.opener.open(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["csrfToken"]

    def get_json(self, path: str) -> Dict[str, Any]:
        req = request.Request(self._url(path), method="GET")
        try:
            with self.opener.open(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {path} failed ({e.code}): {body}") from e

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        csrf = self._csrf()
        req = request.Request(
            self._url(path),
            data=_json_bytes(payload),
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": csrf,
            },
            method="POST",
        )
        try:
            with self.opener.open(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"POST {path} failed ({e.code}): {body}") from e

    def login(self, username: str, password: str) -> None:
        self.post_json("/api/auth/login/", {"username": username, "password": password})


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Bridge legacy replay packets into Django session ingestion APIs.",
    )
    ap.add_argument("replay_bin", help="Path to length-prefixed packet replay file")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000", help="Django API base URL")
    ap.add_argument("--username", required=True, help="Session auth username")
    ap.add_argument("--password", required=True, help="Session auth password")
    ap.add_argument("--patient-id", type=int, default=None)
    ap.add_argument("--device-id", type=int, default=None)
    ap.add_argument("--calibration-profile-id", type=int, default=None)
    ap.add_argument("--source", default=None, help="Session source override")
    ap.add_argument("--notes", default="")
    ap.add_argument("--max-frames", type=int, default=None, help="Optional cap for replay frames")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    _import_legacy_modules()

    # Imported lazily after sys.path update to legacy/.
    from calibration import adc_counts_to_pressure
    from gait_features import compute_cop_from_grid
    from pad_decoder import iter_length_prefixed_packets, verify_and_decode_packet

    replay_path = Path(args.replay_bin).resolve()
    if not replay_path.exists():
        print(f"Replay file not found: {replay_path}", file=sys.stderr)
        return 2

    client = ApiClient(args.base_url)

    print(f"Logging in to {args.base_url} as {args.username}...", file=sys.stderr)
    client.login(args.username, args.password)

    frames_sent = 0
    session_id: Optional[int] = None
    first_ts_us: Optional[int] = None
    last_ts_us: Optional[int] = None

    with replay_path.open("rb") as fh:
        for packet in iter_length_prefixed_packets(fh):
            dec = verify_and_decode_packet(packet)

            if session_id is None:
                first_ts_us = dec.ts_us
                start_payload: Dict[str, Any] = {
                    "started_at_us": dec.ts_us,
                    "source": args.source or str(replay_path),
                    "notes": args.notes,
                }
                if args.patient_id is not None:
                    start_payload["patient_id"] = args.patient_id
                if args.device_id is not None:
                    start_payload["device_id"] = args.device_id
                if args.calibration_profile_id is not None:
                    start_payload["calibration_profile_id"] = args.calibration_profile_id

                start_resp = client.post_json("/api/sessions/start/", start_payload)
                session_id = int(start_resp["session_id"])
                print(f"Started session {session_id}", file=sys.stderr)

            pressure_grid = adc_counts_to_pressure(dec.adc_flat)
            _, _, total_load = compute_cop_from_grid(dec.gw, dec.gh, pressure_grid)
            adc_blob = struct.pack("<" + "h" * len(dec.adc_flat), *dec.adc_flat)

            frame_payload = {
                "ts_us": dec.ts_us,
                "gw": dec.gw,
                "gh": dec.gh,
                "battery_pct": dec.battery_pct,
                "flags": dec.flags,
                "total_load": total_load,
                "adc_base64": base64.b64encode(adc_blob).decode("ascii"),
            }
            client.post_json(f"/api/sessions/{session_id}/frames/", frame_payload)
            frames_sent += 1
            last_ts_us = dec.ts_us

            if args.max_frames is not None and frames_sent >= args.max_frames:
                break

    if session_id is None:
        print("No frames found in replay; no session created.", file=sys.stderr)
        return 1

    end_payload: Dict[str, Any] = {}
    if last_ts_us is not None:
        end_payload["ended_at_us"] = last_ts_us
    client.post_json(f"/api/sessions/{session_id}/end/", end_payload)

    summary = client.get_json(f"/api/sessions/{session_id}/")
    print(
        json.dumps(
            {
                "session_id": session_id,
                "frames_sent": frames_sent,
                "started_at_us": first_ts_us,
                "ended_at_us": last_ts_us,
                "raw_frame_count": summary.get("raw_frame_count"),
                "computed_metric_count": summary.get("computed_metric_count"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
