import struct

from django.core.management.base import BaseCommand

from wbs.fhir_views import _build_bundle
from wbs.metrics_pipeline import recompute_session_metrics
from wbs.models import CalibrationProfile, Device, Patient, RawFrame, Report, Session
from wbs.reports_views import _build_minimal_pdf, _build_weekly_payload, _report_dir, _write_report_pdf


class Command(BaseCommand):
    help = "Seed deterministic demo data for prototype flows"

    def handle(self, *args, **options):
        patients = [
            {
                "external_id": "DEMO-P-001",
                "first_name": "Alex",
                "last_name": "Rivera",
                "sex": "female",
                "metadata": {"demo": True},
            },
            {
                "external_id": "DEMO-P-002",
                "first_name": "Jordan",
                "last_name": "Chen",
                "sex": "male",
                "metadata": {"demo": True},
            },
        ]

        devices = [
            {"serial_number": "DEMO-DEV-001", "model": "wbs-v1", "firmware_version": "1.0.0"},
            {"serial_number": "DEMO-DEV-002", "model": "wbs-v1", "firmware_version": "1.0.1"},
        ]

        seeded_patients = []
        for p in patients:
            obj, _ = Patient.objects.get_or_create(external_id=p["external_id"], defaults=p)
            seeded_patients.append(obj)

        seeded_devices = []
        for d in devices:
            obj, _ = Device.objects.get_or_create(serial_number=d["serial_number"], defaults=d)
            seeded_devices.append(obj)

        calibrations = []
        for idx, d in enumerate(seeded_devices, start=1):
            c, _ = CalibrationProfile.objects.get_or_create(
                device=d,
                profile_name="default",
                version="v1",
                defaults={"parameters": {"gain": 1.0 + idx * 0.1}, "is_active": True},
            )
            calibrations.append(c)

        sessions_cfg = [
            {
                "source": "demo:session:1",
                "started_at_us": 1_700_000_000_000_000,
                "ended_at_us": 1_700_000_000_050_000,
                "patient": seeded_patients[0],
                "device": seeded_devices[0],
                "calibration": calibrations[0],
                "risk_label": "low",
                "risk_score": 18.5,
                "frames": [
                    (1_700_000_000_000_000, [120, 180, 210, 160]),
                    (1_700_000_000_020_000, [140, 190, 220, 170]),
                    (1_700_000_000_040_000, [130, 170, 200, 150]),
                ],
            },
            {
                "source": "demo:session:2",
                "started_at_us": 1_700_000_001_000_000,
                "ended_at_us": 1_700_000_001_060_000,
                "patient": seeded_patients[1],
                "device": seeded_devices[1],
                "calibration": calibrations[1],
                "risk_label": "moderate",
                "risk_score": 52.0,
                "frames": [
                    (1_700_000_001_000_000, [80, 130, 170, 90]),
                    (1_700_000_001_020_000, [70, 110, 160, 85]),
                    (1_700_000_001_040_000, [60, 100, 150, 75]),
                    (1_700_000_001_060_000, [75, 120, 165, 88]),
                ],
            },
            {
                "source": "demo:session:3",
                "started_at_us": 1_700_086_400_000_000,
                "ended_at_us": 1_700_086_400_050_000,
                "patient": seeded_patients[0],
                "device": seeded_devices[0],
                "calibration": calibrations[0],
                "risk_label": "low",
                "risk_score": 16.2,
                "frames": [
                    (1_700_086_400_000_000, [125, 185, 214, 162]),
                    (1_700_086_400_020_000, [138, 192, 226, 174]),
                    (1_700_086_400_040_000, [133, 176, 205, 153]),
                ],
            },
            {
                "source": "demo:session:4",
                "started_at_us": 1_700_172_800_000_000,
                "ended_at_us": 1_700_172_800_050_000,
                "patient": seeded_patients[0],
                "device": seeded_devices[0],
                "calibration": calibrations[0],
                "risk_label": "low",
                "risk_score": 15.4,
                "frames": [
                    (1_700_172_800_000_000, [130, 188, 218, 166]),
                    (1_700_172_800_020_000, [142, 194, 228, 176]),
                    (1_700_172_800_040_000, [136, 179, 209, 157]),
                ],
            },
        ]

        created_sessions = 0
        for cfg in sessions_cfg:
            session, was_created = Session.objects.get_or_create(
                source=cfg["source"],
                defaults={
                    "started_at_us": cfg["started_at_us"],
                    "ended_at_us": cfg["ended_at_us"],
                    "patient": cfg["patient"],
                    "device": cfg["device"],
                    "calibration_profile": cfg["calibration"],
                    "notes": "Seeded demo session",
                    "risk_label": cfg["risk_label"],
                    "risk_score": cfg["risk_score"],
                },
            )
            if was_created:
                created_sessions += 1

            if not RawFrame.objects.filter(session=session).exists():
                for ts_us, adc_values in cfg["frames"]:
                    adc_blob = struct.pack("<" + "h" * len(adc_values), *adc_values)
                    RawFrame.objects.create(
                        session=session,
                        ts_us=ts_us,
                        gw=2,
                        gh=2,
                        battery_pct=90,
                        flags=0,
                        total_load=float(sum(adc_values)),
                        adc_blob=adc_blob,
                    )

            recompute_session_metrics(session)

            if not Report.objects.filter(session=session, report_type="clinical_summary").exists():
                payload = {
                    "session": {
                        "session_id": session.session_id,
                        "source": session.source,
                        "risk_label": session.risk_label,
                        "risk_score": session.risk_score,
                    },
                    "counts": {
                        "raw_frames": session.raw_frames.count(),
                        "computed_metrics": session.computed_metrics.count(),
                    },
                }
                report = Report.objects.create(
                    session=session,
                    report_type="clinical_summary",
                    payload=payload,
                    clinician_notes="Auto-seeded demo report",
                )
                pdf_path = _report_dir() / f"report_{report.report_id}.pdf"
                pdf_path.write_bytes(
                    _build_minimal_pdf(
                        [
                            "Balance Assessment Report (Demo)",
                            f"Report ID: {report.report_id}",
                            f"Session ID: {session.session_id}",
                            f"Risk: {session.risk_label} ({session.risk_score})",
                        ]
                    )
                )
                report.pdf_file_path = str(pdf_path)
                report.save(update_fields=["pdf_file_path"])

            if not Report.objects.filter(session=session, report_type="fhir_export").exists():
                Report.objects.create(
                    session=session,
                    report_type="fhir_export",
                    payload=_build_bundle(session),
                    clinician_notes="",
                )

        weekly_sources = Session.objects.filter(
            source__in=["demo:session:1", "demo:session:3", "demo:session:4"],
            patient=seeded_patients[0],
        ).order_by("started_at_us", "session_id")
        weekly_sessions = list(weekly_sources)
        if weekly_sessions:
            anchor = weekly_sessions[-1]
            # Align to Monday-style label from anchor week via payload helper's date input.
            from datetime import datetime, timedelta
            anchor_date = datetime.utcfromtimestamp(anchor.started_at_us / 1_000_000).date()
            monday = anchor_date - timedelta(days=(anchor_date.weekday() % 7))
            weekly_payload = _build_weekly_payload(seeded_patients[0].patient_id, monday, weekly_sessions, anchor)
            if not Report.objects.filter(session=anchor, report_type="weekly_clinical_summary").exists():
                weekly_report = Report.objects.create(
                    session=anchor,
                    report_type="weekly_clinical_summary",
                    payload=weekly_payload,
                    clinician_notes="Auto-seeded weekly demo report",
                )
                _write_report_pdf(weekly_report)
            if not Report.objects.filter(session=anchor, report_type="weekly_fall_risk_summary").exists():
                weekly_fall = Report.objects.create(
                    session=anchor,
                    report_type="weekly_fall_risk_summary",
                    payload=weekly_payload,
                    clinician_notes="Auto-seeded weekly fall-risk demo report",
                )
                _write_report_pdf(weekly_fall)

        self.stdout.write(
            f"Demo bootstrap complete: patients={Patient.objects.filter(external_id__startswith='DEMO-').count()}, "
            f"devices={Device.objects.filter(serial_number__startswith='DEMO-').count()}, "
            f"sessions={Session.objects.filter(source__startswith='demo:').count()}, "
            f"new_sessions={created_sessions}"
        )
