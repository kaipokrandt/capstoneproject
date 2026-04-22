# BLE Packet Structure — STEPPA Insole

Last Verified: 2026-04-21
Owner: Firmware / Platform Engineering
Code References: `scripts/bridge_ble_to_api.py`, `wbs/wbs/metrics_pipeline.py`, `wbs/wbs/master_views.py`
Test References: `wbs/wbs/tests/test_ble_bridge.py`

---

## Transport

| Property | Value |
|---|---|
| Protocol | BLE UART (notify) |
| Characteristic UUID | `49535343-1e4d-4bd9-ba61-23c647249616` (TX, board → host) |
| Encoding | UTF-8 text, newline-delimited (`\n`) |
| Direction | Device → Host (notify only) |

---

## Packet Format

Each BLE notification carries one or more bytes of UTF-8 text. The host accumulates bytes until a `\n` is received, then processes the complete line. Each line is a **comma-separated key:value string**.

### Example line
```
AX:-576,AY:-384,AZ:15680,S0:539,405,S1:850,1186,933,1292,S2:388,482,368,526,S3:262,326
```

---

## Fields

### Accelerometer (IMU)

| Field | Type | Description |
|---|---|---|
| `AX` | signed int16 | X-axis acceleration (raw ADC units, LSB = 1/16384 g for ±2g range) |
| `AY` | signed int16 | Y-axis acceleration |
| `AZ` | signed int16 | Z-axis acceleration (at rest ≈ 15680–16000 ≈ +1g up) |

All three fields are **required**. A line missing any of AX/AY/AZ is dropped.

### Pressure Sensors (S0–S3)

The insole has 12 active pressure cells arranged in 4 sensor groups across the sole. Each group provides 2–4 values.

| Group | Cell count | Sole region |
|---|---|---|
| `S0` | 2 | Toe / forefoot top row |
| `S1` | 4 | Forefoot / midfoot |
| `S2` | 4 | Midfoot / arch |
| `S3` | 2 | Heel |

**Parsing rule:** The first value after the `S<n>:` key is parsed inline; subsequent values for the same group follow as bare comma-separated integers until the next `KEY:` token.

```
S0:539,405         → S0 = [539, 405]
S1:850,1186,933,1292 → S1 = [850, 1186, 933, 1292]
S2:388,482,368,526   → S2 = [388, 482, 368, 526]
S3:262,326         → S3 = [262, 326]
```

Values are raw ADC counts (unsigned, 10–12 bit range depending on firmware).  
Resting baseline ≈ 62–70 counts. Under load values rise significantly (hundreds to thousands).

---

## Grid Mapping (4×4 ADC Blob)

The firmware currently sends 12 of 16 cells. The bridge maps these into a fixed **4×4 grid (GW=4, GH=4)** for backend storage. The 4 corner cells are zero-padded.

```
Grid index layout (row-major):
[ 0][ 1][ 2][ 3]     ← S0[0], S0[1], 0,      0
[ 4][ 5][ 6][ 7]     ← S1[0], S1[1], S1[2],  S1[3]
[ 8][ 9][10][11]     ← S2[0], S2[1], S2[2],  S2[3]
[12][13][14][15]     ← S3[0], S3[1], 0,       0
```

The grid is packed as **16× signed int16, little-endian** (32 bytes total) and stored in `RawFrame.adc_blob`.

`total_load` stored on `RawFrame` is the scalar sum of all 16 grid values.

---

## Observed Value Ranges (from live capture — 2026-04-21)

| Field | Typical idle range | Notes |
|---|---|---|
| AX | 64 – 448 | Small positive bias at rest on flat surface |
| AY | -576 – -192 | Negative Y at rest (device orientation) |
| AZ | 15488 – 16192 | ~+1g, gravity dominant |
| S0–S3 (idle) | 62 – 70 | ADC baseline with no weight |
| S0–S3 (loaded) | 300 – 1300+ | Observed during pressure events |

After the `_adc_counts_to_pressure` transform (12-bit, `(x/4095)^2 * 30000`), `total_load` across all 16 cells peaks at **~36,000–40,000 counts** under real foot pressure.

---

## IMU Calibration (Zero Offset)

Before each assessment the clinician clicks **Calibrate** in the Live Session UI with the board placed flat.

- `POST /api/devices/<id>/calibrate-imu/` reads the latest `ble-bridge` heartbeat annotation for the device and stores `{ax, ay, az}` as `imu_offset` in `Device.metadata`.
- The bridge polls `GET /api/devices/<id>/` every 2s. When `imu_offset` changes, it prints `[calibration] IMU offset updated` and subtracts the offset from every subsequent frame before posting.
- Start Assessment in the frontend is blocked until calibration has been confirmed.

---

## Computed Metrics

The metrics pipeline (`wbs/wbs/metrics_pipeline.py`) runs on every frame POST and produces the following metrics:

| Metric | Unit | Description |
|---|---|---|
| `cop_x` | grid_x | Centre of pressure, medial–lateral axis |
| `cop_y` | grid_y | Centre of pressure, anterior–posterior axis |
| `cop_v` | grid_per_s | CoP velocity (sway speed) |
| `sway_path` | grid_units | Cumulative CoP path length for the session |
| `total_load` | counts | Sum of pressure-transformed grid cells |
| `stance_pct` | percent | Estimated stance phase percentage |
| `swing_pct` | percent | Estimated swing phase percentage |
| `asymmetry_index` | ratio | (right−left)/(right+left); 0 = symmetric, ±1 = fully one-sided |
| `cadence_spm` | steps_per_min | Cadence derived from heel-strike intervals |

**Contact threshold:** `5.0e4` counts (post-transform). Frames below this threshold are considered not in contact and do not contribute to step detection or cadence.

---

## Line Validation Rules

A line is **accepted** if:
- All three of `AX`, `AY`, `AZ` are present and parseable as integers.
- At least one `S<n>` group is present (missing groups default to empty list → zero-padded in grid).

A line is **skipped** (logged as `Skipping bad line`) if:
- Any required accelerometer field is missing.
- The line contains non-integer tokens in expected numeric positions.
- Django ORM cannot be called from the async notify callback (see bug note below).

---

## Known Issues

None outstanding as of 2026-04-21. The async ORM context error previously noted in the `run_ble_bridge` management command has been superseded — the recommended bridge is now `scripts/bridge_ble_to_api.py` (HTTP path), which runs on the host Mac outside of Django's async context entirely.

---

## Data Flow Summary

```
STEPPA firmware
    │  BLE UART notify (UTF-8, newline-delimited)
    ▼
bleak _on_notify callback (host Mac)
    │  buffer += data; split on \n
    ▼
parse_steppa_line()
    │  → Frame(ax, ay, az, grid[16])
    ▼
BleToApiBridge._refresh_imu_offset()    ← polls Device.metadata every 2s
    │  apply imu_offset subtraction
    ▼
frame_to_payload()  →  adc_base64, total_load, ts_us …
    ▼
POST /api/sessions/<id>/frames/
    │
    ▼
Django: RawFrame.objects.create()
         recompute_session_metrics()  → ComputedMetric (9 metrics per frame)
    ▼
_maybe_post_log() every 5s
    ▼
POST /api/annotations/  (author=ble-bridge, heartbeat metadata)
    ▼
Live Session UI polls annotations every 5s → BLE Data Stream log box
```
