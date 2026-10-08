from django.contrib import admin

from .models import Employee, HazardReport, Site, VisionAlert, VisionScan


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "role", "user")
    list_filter = ("role",)
    search_fields = ("full_name", "role")


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("facility_name", "region")
    list_filter = ("region",)
    search_fields = ("facility_name", "region")


@admin.register(HazardReport)
class HazardReportAdmin(admin.ModelAdmin):
    list_display = ("report_id", "site", "employee", "risk_score", "status", "created_at", "received_at")
    list_filter = ("status", "risk_score", "site", "created_at")
    search_fields = ("description", "site__facility_name", "employee__full_name")
    readonly_fields = ("report_id", "received_at")


@admin.register(VisionScan)
class VisionScanAdmin(admin.ModelAdmin):
    list_display = ("scan_id", "camera_id", "fire_detected", "personnel_count", "fire_confidence", "user", "created_at")
    list_filter = ("fire_detected", "camera_id", "created_at")
    readonly_fields = (
        "scan_id",
        "user",
        "camera_id",
        "zone_name",
        "fire_detected",
        "fire_confidence",
        "personnel_count",
        "frames_analyzed",
        "duration_seconds",
        "created_at",
    )


@admin.register(VisionAlert)
class VisionAlertAdmin(admin.ModelAdmin):
    list_display = ("alert_id", "scan", "selected_exit", "operator_confirmed", "user", "created_at")
    list_filter = ("operator_confirmed", "created_at")
    readonly_fields = ("alert_id", "scan", "user", "selected_exit", "operator_confirmed", "created_at")
