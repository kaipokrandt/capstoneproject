from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from wbs.models import Patient, Report, Session


class Command(BaseCommand):
    help = "Backfill sessions missing patient links and patch report payload.session.patient_id"

    def add_arguments(self, parser):
        parser.add_argument(
            "--patient-external-id",
            type=str,
            default="",
            help="Fallback patient external_id to use when source-based inference is ambiguous",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without writing",
        )

    def handle(self, *args, **options):
        fallback_external_id = (options.get("patient_external_id") or "").strip()
        dry_run = bool(options.get("dry_run"))

        fallback_patient = None
        if fallback_external_id:
            fallback_patient = Patient.objects.filter(external_id=fallback_external_id).first()
            if fallback_patient is None:
                self.stderr.write(f"Fallback patient not found: {fallback_external_id}")
                return

        source_to_patients = defaultdict(list)
        for row in Session.objects.filter(patient__isnull=False).values("source", "patient_id"):
            source = (row["source"] or "").strip().lower()
            if source:
                source_to_patients[source].append(int(row["patient_id"]))

        source_to_inferred_patient = {}
        for source, patient_ids in source_to_patients.items():
            counts = Counter(patient_ids)
            top_patient_id, top_count = counts.most_common(1)[0]
            if top_count >= 1:
                source_to_inferred_patient[source] = top_patient_id

        unassigned_sessions = list(Session.objects.filter(patient__isnull=True).order_by("session_id"))
        if not unassigned_sessions:
            self.stdout.write("No unassigned sessions found.")
            return

        if fallback_patient is None:
            fallback_patient = Patient.objects.order_by("patient_id").first()

        if fallback_patient is None and not source_to_inferred_patient:
            self.stderr.write("No patients available for fallback and no source inference available. Nothing to update.")
            return

        patched_sessions = 0
        patched_reports = 0

        with transaction.atomic():
            for session in unassigned_sessions:
                source_key = (session.source or "").strip().lower()
                inferred_patient_id = source_to_inferred_patient.get(source_key)
                patient_id = inferred_patient_id or (fallback_patient.patient_id if fallback_patient else None)
                if not patient_id:
                    continue

                if not dry_run:
                    session.patient_id = patient_id
                    session.save(update_fields=["patient"])
                patched_sessions += 1

                reports = Report.objects.filter(session=session)
                for report in reports:
                    payload = report.payload if isinstance(report.payload, dict) else {}
                    session_payload = payload.get("session")
                    if not isinstance(session_payload, dict):
                        session_payload = {}
                        payload["session"] = session_payload
                    if session_payload.get("patient_id") == patient_id:
                        continue
                    session_payload["patient_id"] = patient_id
                    if not dry_run:
                        report.payload = payload
                        report.save(update_fields=["payload"])
                    patched_reports += 1

            if dry_run:
                transaction.set_rollback(True)

        mode = "Dry run" if dry_run else "Applied"
        fallback_label = fallback_patient.external_id if fallback_patient else "none"
        self.stdout.write(
            f"{mode}: sessions_updated={patched_sessions}, reports_payload_updated={patched_reports}, "
            f"fallback_patient={fallback_label}"
        )
