from django.urls import path

from .views import (
    EmployeeListView,
    HazardSyncView,
    SiteListView,
    VisionAlertView,
    VisionAnalyzeView,
    VisionCameraListView,
    VisionStatusView,
)

urlpatterns = [
    path("sites/", SiteListView.as_view(), name="site-list"),
    path("employees/", EmployeeListView.as_view(), name="employee-list"),
    path("hazards/sync/", HazardSyncView.as_view(), name="hazard-sync"),
    path("vision/status/", VisionStatusView.as_view(), name="vision-status"),
    path("vision/cameras/", VisionCameraListView.as_view(), name="vision-cameras"),
    path("vision/analyze/", VisionAnalyzeView.as_view(), name="vision-analyze"),
    path("vision/alerts/", VisionAlertView.as_view(), name="vision-alert"),
]
