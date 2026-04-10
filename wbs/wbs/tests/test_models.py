import pytest
from django.db import IntegrityError

from wbs.models import (
    Annotation,
    CalibrationProfile,
    ComputedMetric,
    Device,
    Patient,
    RawFrame,
    Report,
    Session,
)


@pytest.mark.django_db
def test_patient_device_and_session_creation():
    patient = Patient.objects.create(external_id="P-001", first_name="Ada", last_name="Lovelace")
    device = Device.objects.create(serial_number="DEV-001", firmware_version="1.0.0")

    session = Session.objects.create(
        patient=patient,
        device=device,
        started_at_us=1000,
        source="test-stream",
        notes="baseline",
    )

    assert session.session_id is not None
    assert session.patient_id == patient.patient_id
    assert session.device_id == device.device_id
    assert session.source == "test-stream"


@pytest.mark.django_db
def test_calibration_profile_unique_constraint_per_device_profile_and_version():
    device = Device.objects.create(serial_number="DEV-002")
    CalibrationProfile.objects.create(device=device, profile_name="default", version="v1")

    with pytest.raises(IntegrityError):
        CalibrationProfile.objects.create(device=device, profile_name="default", version="v1")


@pytest.mark.django_db
def test_same_calibration_profile_name_allowed_for_different_devices():
    d1 = Device.objects.create(serial_number="DEV-003")
    d2 = Device.objects.create(serial_number="DEV-004")

    CalibrationProfile.objects.create(device=d1, profile_name="default", version="v1")
    CalibrationProfile.objects.create(device=d2, profile_name="default", version="v1")

    assert CalibrationProfile.objects.count() == 2


@pytest.mark.django_db
def test_raw_frame_and_metric_link_to_session():
    session = Session.objects.create(started_at_us=2000, source="replay.bin")

    frame = RawFrame.objects.create(
        session=session,
        ts_us=2000,
        gw=4,
        gh=4,
        battery_pct=90,
        flags=0,
        total_load=123.4,
        adc_blob=b"\x01\x00\x02\x00",
    )
    metric = ComputedMetric.objects.create(
        session=session,
        ts_us=2000,
        metric_name="cop_x",
        metric_value=1.23,
        unit="grid_x",
    )

    assert frame.session_id == session.session_id
    assert metric.session_id == session.session_id
    assert session.raw_frames.count() == 1
    assert session.computed_metrics.count() == 1


@pytest.mark.django_db
def test_report_and_annotation_relationships():
    patient = Patient.objects.create(external_id="P-002")
    session = Session.objects.create(patient=patient, started_at_us=3000, source="live")
    report = Report.objects.create(session=session, report_type="clinical_summary")

    annotation = Annotation.objects.create(
        patient=patient,
        session=session,
        report=report,
        author="clinician",
        body="Mild asymmetry observed.",
    )

    assert report.session_id == session.session_id
    assert annotation.patient_id == patient.patient_id
    assert annotation.session_id == session.session_id
    assert annotation.report_id == report.report_id


@pytest.mark.django_db
def test_deleting_device_sets_session_device_null_and_removes_calibration_profiles():
    patient = Patient.objects.create(external_id="P-003")
    device = Device.objects.create(serial_number="DEV-005")
    profile = CalibrationProfile.objects.create(device=device, profile_name="default", version="v1")
    session = Session.objects.create(
        patient=patient,
        device=device,
        calibration_profile=profile,
        started_at_us=4000,
        source="live",
    )

    device.delete()
    session.refresh_from_db()

    assert session.device is None
    assert session.calibration_profile is None
    assert CalibrationProfile.objects.count() == 0


@pytest.mark.django_db
def test_deleting_patient_sets_related_foreign_keys_to_null():
    patient = Patient.objects.create(external_id="P-004")
    session = Session.objects.create(patient=patient, started_at_us=5000, source="live")
    report = Report.objects.create(session=session)
    annotation = Annotation.objects.create(patient=patient, session=session, report=report, body="note")

    patient.delete()
    session.refresh_from_db()
    annotation.refresh_from_db()

    assert session.patient is None
    assert annotation.patient is None


@pytest.mark.django_db
def test_deleting_report_sets_annotation_report_null():
    session = Session.objects.create(started_at_us=6000, source="live")
    report = Report.objects.create(session=session)
    annotation = Annotation.objects.create(session=session, report=report, body="report note")

    report.delete()
    annotation.refresh_from_db()

    assert annotation.report is None


@pytest.mark.django_db
def test_deleting_session_cascades_report_and_nulls_annotation_session():
    session = Session.objects.create(started_at_us=7000, source="live")
    report = Report.objects.create(session=session)
    annotation = Annotation.objects.create(session=session, report=report, body="to be preserved")

    session.delete()
    annotation.refresh_from_db()

    assert Report.objects.filter(report_id=report.report_id).count() == 0
    assert annotation.session is None
    assert annotation.report is None


@pytest.mark.django_db
def test_legacy_models_keep_do_nothing_foreign_key_behavior():
    raw_frame_fk = RawFrame._meta.get_field("session")
    metric_fk = ComputedMetric._meta.get_field("session")

    assert raw_frame_fk.remote_field.on_delete.__name__ == "DO_NOTHING"
    assert metric_fk.remote_field.on_delete.__name__ == "DO_NOTHING"


@pytest.mark.django_db
def test_defaults_for_json_fields_are_materialized():
    patient = Patient.objects.create(external_id="P-005")
    device = Device.objects.create(serial_number="DEV-006")
    profile = CalibrationProfile.objects.create(device=device, profile_name="default", version="", parameters={})
    report = Report.objects.create(session=Session.objects.create(started_at_us=9000, source="live"))
    annotation = Annotation.objects.create(body="x")

    assert patient.metadata == {}
    assert device.metadata == {}
    assert profile.parameters == {}
    assert report.payload == {}
    assert annotation.metadata == {}
