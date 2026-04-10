from django.db import models


class Patient(models.Model):
    patient_id = models.AutoField(primary_key=True)
    external_id = models.CharField(max_length=64, unique=True)
    first_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=32, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patients"


class Device(models.Model):
    device_id = models.AutoField(primary_key=True)
    serial_number = models.CharField(max_length=128, unique=True)
    model = models.CharField(max_length=128, blank=True)
    firmware_version = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "devices"


class CalibrationProfile(models.Model):
    calibration_profile_id = models.AutoField(primary_key=True)
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        db_column="device_id",
        related_name="calibration_profiles",
    )
    profile_name = models.CharField(max_length=128)
    version = models.CharField(max_length=64, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "calibration_profiles"
        unique_together = [("device", "profile_name", "version")]


class Session(models.Model):
    session_id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="patient_id",
        related_name="sessions",
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="device_id",
        related_name="sessions",
    )
    calibration_profile = models.ForeignKey(
        CalibrationProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="calibration_profile_id",
        related_name="sessions",
    )
    started_at_us = models.BigIntegerField()
    ended_at_us = models.BigIntegerField(null=True, blank=True)
    source = models.TextField()
    notes = models.TextField(null=True, blank=True)
    risk_label = models.TextField(null=True, blank=True)
    risk_score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "sessions"
        indexes = [
            models.Index(fields=["patient"], name="idx_sessions_patient"),
            models.Index(fields=["device"], name="idx_sessions_device"),
        ]


class RawFrame(models.Model):
    frame_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(
        Session,
        on_delete=models.DO_NOTHING,
        db_column="session_id",
        db_index=False,
        related_name="raw_frames",
    )
    ts_us = models.BigIntegerField()
    gw = models.IntegerField()
    gh = models.IntegerField()
    battery_pct = models.IntegerField()
    flags = models.IntegerField()
    total_load = models.FloatField()
    adc_blob = models.BinaryField()

    class Meta:
        db_table = "raw_frames"
        indexes = [
            models.Index(fields=["session"], name="idx_frames_session"),
        ]


class ComputedMetric(models.Model):
    metric_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(
        Session,
        on_delete=models.DO_NOTHING,
        db_column="session_id",
        db_index=False,
        related_name="computed_metrics",
    )
    ts_us = models.BigIntegerField()
    metric_name = models.TextField()
    metric_value = models.FloatField()
    unit = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "computed_metrics"
        indexes = [
            models.Index(fields=["session"], name="idx_metrics_session"),
        ]


class Report(models.Model):
    report_id = models.AutoField(primary_key=True)
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        db_column="session_id",
        related_name="reports",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    report_type = models.CharField(max_length=64, default="clinical_summary")
    pdf_file_path = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    clinician_notes = models.TextField(blank=True)

    class Meta:
        db_table = "reports"
        indexes = [
            models.Index(fields=["session"], name="idx_reports_session"),
        ]


class Annotation(models.Model):
    annotation_id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="patient_id",
        related_name="annotations",
    )
    session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="session_id",
        related_name="annotations",
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="report_id",
        related_name="annotations",
    )
    author = models.CharField(max_length=128, blank=True)
    body = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "annotations"
        indexes = [
            models.Index(fields=["patient"], name="idx_annotations_patient"),
            models.Index(fields=["session"], name="idx_annotations_session"),
            models.Index(fields=["report"], name="idx_annotations_report"),
        ]
