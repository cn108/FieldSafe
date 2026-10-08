import uuid

from django.conf import settings
from django.db import models


class Employee(models.Model):
    employee_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="field_employee",
    )
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=50)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} — {self.role}"


class Site(models.Model):
    site_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    facility_name = models.CharField(max_length=100, unique=True)
    region = models.CharField(max_length=50)

    class Meta:
        ordering = ["facility_name"]

    def __str__(self):
        return self.facility_name


class HazardReport(models.Model):
    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="reports")
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="reports")
    description = models.TextField()
    risk_score = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(risk_score__gte=1, risk_score__lte=5),
                name="hazard_risk_score_1_to_5",
            ),
        ]

    def __str__(self):
        return f"{self.site} — risk {self.risk_score} — {self.created_at:%Y-%m-%d %H:%M}"


class VisionScan(models.Model):
    scan_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vision_scans")
    camera_id = models.CharField(max_length=40)
    zone_name = models.CharField(max_length=120)
    fire_detected = models.BooleanField()
    fire_confidence = models.FloatField()
    personnel_count = models.PositiveSmallIntegerField()
    frames_analyzed = models.PositiveIntegerField()
    duration_seconds = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.camera_id} — {'fire signal' if self.fire_detected else 'no fire signal'} — {self.created_at:%Y-%m-%d %H:%M}"


class VisionAlert(models.Model):
    alert_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.OneToOneField(VisionScan, on_delete=models.PROTECT, related_name="alert")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vision_alerts")
    selected_exit = models.CharField(max_length=120)
    operator_confirmed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Confirmed demo alert — {self.scan.camera_id} — {self.created_at:%Y-%m-%d %H:%M}"
