from django.db import models


class Session(models.Model):
    session_id = models.AutoField(primary_key=True)
    started_at_us = models.BigIntegerField()
    ended_at_us = models.BigIntegerField(null=True, blank=True)
    source = models.TextField()
    notes = models.TextField(null=True, blank=True)
    risk_label = models.TextField(null=True, blank=True)
    risk_score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "sessions"


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
