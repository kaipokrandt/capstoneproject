import io

import pytest
from django.core.management import call_command

from wbs.models import CalibrationProfile, ComputedMetric, Device, Patient, RawFrame, Report, Session


@pytest.mark.django_db
def test_bootstrap_demo_data_creates_expected_objects(settings, tmp_path):
    settings.REPORTS_DIR = str(tmp_path)

    out = io.StringIO()
    call_command("bootstrap_demo_data", stdout=out)

    assert Patient.objects.filter(external_id__startswith="DEMO-").count() == 2
    assert Device.objects.filter(serial_number__startswith="DEMO-").count() == 2
    assert CalibrationProfile.objects.filter(device__serial_number__startswith="DEMO-").count() >= 2
    assert Session.objects.filter(source__startswith="demo:").count() == 2
    assert RawFrame.objects.filter(session__source__startswith="demo:").count() >= 6
    assert ComputedMetric.objects.filter(session__source__startswith="demo:").count() > 0
    assert Report.objects.filter(session__source__startswith="demo:", report_type="clinical_summary").count() == 2
    assert Report.objects.filter(session__source__startswith="demo:", report_type="fhir_export").count() == 2

    text = out.getvalue()
    assert "Demo bootstrap complete" in text


@pytest.mark.django_db
def test_bootstrap_demo_data_is_idempotent(settings, tmp_path):
    settings.REPORTS_DIR = str(tmp_path)

    call_command("bootstrap_demo_data")

    counts_before = {
        "patients": Patient.objects.filter(external_id__startswith="DEMO-").count(),
        "devices": Device.objects.filter(serial_number__startswith="DEMO-").count(),
        "sessions": Session.objects.filter(source__startswith="demo:").count(),
        "reports": Report.objects.filter(session__source__startswith="demo:").count(),
    }

    call_command("bootstrap_demo_data")

    counts_after = {
        "patients": Patient.objects.filter(external_id__startswith="DEMO-").count(),
        "devices": Device.objects.filter(serial_number__startswith="DEMO-").count(),
        "sessions": Session.objects.filter(source__startswith="demo:").count(),
        "reports": Report.objects.filter(session__source__startswith="demo:").count(),
    }

    assert counts_after == counts_before
