import io

import pytest
from django.core.management import call_command

from wbs.models import Patient, Report, Session


@pytest.mark.django_db
def test_backfill_unassigned_sessions_updates_session_and_report_payload():
    patient = Patient.objects.create(external_id="P-BACKFILL-1", first_name="Maya", last_name="Singh")
    session = Session.objects.create(started_at_us=1000, source="show:session:alpha")
    report = Report.objects.create(
        session=session,
        report_type="clinical_summary",
        payload={"session": {"source": "show:session:alpha"}},
    )

    out = io.StringIO()
    call_command("backfill_unassigned_sessions", patient_external_id=patient.external_id, stdout=out)

    session.refresh_from_db()
    report.refresh_from_db()
    assert session.patient_id == patient.patient_id
    assert report.payload["session"]["patient_id"] == patient.patient_id
    assert "sessions_updated=1" in out.getvalue()


@pytest.mark.django_db
def test_backfill_unassigned_sessions_dry_run_makes_no_changes():
    patient = Patient.objects.create(external_id="P-BACKFILL-2")
    session = Session.objects.create(started_at_us=1000, source="show:session:beta")

    out = io.StringIO()
    call_command(
        "backfill_unassigned_sessions",
        patient_external_id=patient.external_id,
        dry_run=True,
        stdout=out,
    )

    session.refresh_from_db()
    assert session.patient_id is None
    assert "Dry run" in out.getvalue()
