from django.conf import settings
from django.db import models


def default_sensor_layout():
    return {
        "left": [
            {"x": 0.565234030210846, "y": 0.28328029898064006, "w": 0.9},
            {"x": 0.3291048740877326, "y": 0.30385444660162475, "w": 0.95},
            {"x": 0.5933446440350261, "y": 0.42729933232753287, "w": 0.9},
            {"x": 0.4387362680020352, "y": 0.44787347994851756, "w": 0.9},
            {"x": 0.2897500147338804, "y": 0.4684476275695022, "w": 0.95},
            {"x": 0.1463858842305616, "y": 0.4928794278694215, "w": 0.9},
            {"x": 0.4921464342679775, "y": 0.5443147969218832, "w": 0.88},
            {"x": 0.41343671556027306, "y": 0.5558877549586871, "w": 0.92},
            {"x": 0.30380532164597046, "y": 0.5687465972218025, "w": 0.88},
            {"x": 0.19136286634924984, "y": 0.5867489763901641, "w": 0.9},
            {"x": 0.7114092220965827, "y": 0.9313659490416576, "w": 0.96},
            {"x": 0.5708561529756819, "y": 0.9390812543995268, "w": 0.9},
        ],
        "right": [
            {"x": 0.38707760044028616, "y": 0.2386495808262632, "w": 0.9},
            {"x": 0.5730544854155201, "y": 0.2554064600589109, "w": 0.95},
            {"x": 0.42089157952669237, "y": 0.4139523174139624, "w": 0.9},
            {"x": 0.5945253728095258, "y": 0.4323258163392478, "w": 0.9},
            {"x": 0.7377047930297224, "y": 0.4580103545889714, "w": 0.95},
            {"x": 0.8556172567404725, "y": 0.48883180048863956, "w": 0.9},
            {"x": 0.5299542617298294, "y": 0.5383662692126507, "w": 0.88},
            {"x": 0.6394444066040973, "y": 0.5512085383375125, "w": 0.92},
            {"x": 0.7405122326418832, "y": 0.5679034881998327, "w": 0.88},
            {"x": 0.8331577398431868, "y": 0.5858826649746391, "w": 0.9},
            {"x": 0.4625757110379721, "y": 0.9300554775209341, "w": 0.96},
            {"x": 0.31658885120561486, "y": 0.928771250608448, "w": 0.9},
        ],
    }


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


class ClinicianUiPreference(models.Model):
    preference_id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ui_preference",
    )
    sensor_layout = models.JSONField(default=default_sensor_layout, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clinician_ui_preferences"
