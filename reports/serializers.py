from rest_framework import serializers
from django.utils import timezone

from .models import Employee, HazardReport, Site


class VisionVideoAnalyzeSerializer(serializers.Serializer):
    video = serializers.FileField()
    camera_id = serializers.CharField(max_length=40)
    confidence = serializers.FloatField(min_value=0.1, max_value=0.95, default=0.45)

    def validate_video(self, video):
        if video.size > 100 * 1024 * 1024:
            raise serializers.ValidationError("The demo video limit is 100 MB.")
        if not video.name.lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
            raise serializers.ValidationError("Use an MP4, MOV, AVI, or MKV recording.")
        return video


class VisionAlertCreateSerializer(serializers.Serializer):
    scan_id = serializers.UUIDField()
    hazard_type = serializers.ChoiceField(choices=("Fire",))
    camera_id = serializers.CharField(max_length=40)
    personnel_count = serializers.IntegerField(min_value=0)
    selected_exit = serializers.CharField(max_length=120)
    operator_confirmed = serializers.BooleanField()

    def validate_operator_confirmed(self, confirmed):
        if not confirmed:
            raise serializers.ValidationError("An operator must review and confirm the proposed response.")
        return confirmed


class TimezoneAwareDateTimeField(serializers.DateTimeField):
    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError("Timestamp must include a timezone.")
        return super().enforce_timezone(value)


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ("employee_id", "full_name", "role")


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ("site_id", "facility_name", "region")


class HazardReportSyncSerializer(serializers.ModelSerializer):
    report_id = serializers.UUIDField()
    employee_id = serializers.PrimaryKeyRelatedField(
        source="employee",
        queryset=Employee.objects.all(),
    )
    site_id = serializers.PrimaryKeyRelatedField(
        source="site",
        queryset=Site.objects.all(),
    )
    local_timestamp = TimezoneAwareDateTimeField(source="created_at")

    class Meta:
        model = HazardReport
        fields = (
            "report_id",
            "employee_id",
            "site_id",
            "description",
            "risk_score",
            "local_timestamp",
        )

    def validate_description(self, value):
        if not value.strip():
            raise serializers.ValidationError("Description cannot be blank.")
        return value.strip()

    def validate_employee_id(self, value):
        user = self.context["request"].user
        if not user.is_superuser and value.user_id != user.id:
            raise serializers.ValidationError("You can only submit reports for your assigned field account.")
        return value

    def validate_risk_score(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Risk score must be between 1 and 5.")
        return value

class SyncRequestSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=100)
    reports = HazardReportSyncSerializer(many=True, allow_empty=False, max_length=100)
