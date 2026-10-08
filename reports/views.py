from django.db import transaction
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Employee, HazardReport, Site
from .serializers import EmployeeSerializer, SiteSerializer, SyncRequestSerializer


class SiteListView(generics.ListAPIView):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer


class EmployeeListView(generics.ListAPIView):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Employee.objects.all()
        return Employee.objects.filter(user=self.request.user)


class HazardSyncView(APIView):
    def post(self, request):
        batch = SyncRequestSerializer(data=request.data, context={"request": request})
        batch.is_valid(raise_exception=True)
        synced_ids = []
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for report in batch.validated_data["reports"]:
                _, created = HazardReport.objects.update_or_create(
                    report_id=report["report_id"],
                    defaults={
                        "employee": report["employee"],
                        "site": report["site"],
                        "description": report["description"],
                        "risk_score": report["risk_score"],
                        "created_at": report["created_at"],
                    },
                )
                created_count += int(created)
                updated_count += int(not created)
                synced_ids.append(str(report["report_id"]))

        return Response(
            {
                "synced_report_ids": synced_ids,
                "created": created_count,
                "updated": updated_count,
            },
            status=status.HTTP_200_OK,
        )
import logging
from uuid import UUID

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Employee, HazardReport, VisionAlert, VisionScan
from .serializers import (
    EmployeeSerializer,
    SiteSerializer,
    SyncRequestSerializer,
    VisionAlertCreateSerializer,
    VisionVideoAnalyzeSerializer,
)
from .vision import (
    VisionConfigurationError,
    VisionInputError,
    analyze_recording,
    camera_configuration,
    load_floor_plan,
    model_status,
)

logger = logging.getLogger(__name__)


class SiteListView(generics.ListAPIView):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer


class EmployeeListView(generics.ListAPIView):
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Employee.objects.all()
        return Employee.objects.filter(user=self.request.user)


class HazardSyncView(APIView):
    def post(self, request):
        batch = SyncRequestSerializer(data=request.data, context={"request": request})
        batch.is_valid(raise_exception=True)
        synced_ids = []
        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for report in batch.validated_data["reports"]:
                _, created = HazardReport.objects.update_or_create(
                    report_id=report["report_id"],
                    defaults={
                        "employee": report["employee"],
                        "site": report["site"],
                        "description": report["description"],
                        "risk_score": report["risk_score"],
                        "created_at": report["created_at"],
                    },
                )
                created_count += int(created)
                updated_count += int(not created)
                synced_ids.append(str(report["report_id"]))

        return Response(
            {
                "synced_report_ids": synced_ids,
                "created": created_count,
                "updated": updated_count,
            },
            status=status.HTTP_200_OK,
        )


class VisionStatusView(APIView):
    def get(self, request):
        try:
            return Response(model_status())
        except VisionConfigurationError as error:
            return Response({"ready": False, "message": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class VisionCameraListView(APIView):
    def get(self, request):
        try:
            return Response({"facilities": load_floor_plan()})
        except VisionConfigurationError as error:
            return Response({"detail": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class VisionAnalyzeView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        serializer = VisionVideoAnalyzeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            camera = camera_configuration(values["camera_id"])
            result = analyze_recording(values["video"], values["camera_id"], values["confidence"])
        except VisionConfigurationError as error:
            return Response({"detail": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except VisionInputError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception("Smart Rig AI video analysis failed for camera %s", values["camera_id"])
            return Response(
                {"detail": "Video analysis failed. No alert was sent. Check the server model configuration and logs."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            VisionScan.objects.create(
                scan_id=UUID(result["scan_id"]),
                user=request.user,
                camera_id=result["camera_id"],
                zone_name=result["zone_name"],
                fire_detected=result["fire_detected"],
                fire_confidence=result["fire_confidence"],
                personnel_count=result["personnel_count"],
                frames_analyzed=result["frames_analyzed"],
                duration_seconds=result["duration_seconds"],
            )
        except Exception:
            logger.exception("Could not persist Smart Rig AI analysis for camera %s", camera["camera_id"])
            return Response(
                {"detail": "The analysis result could not be saved. No alert was sent."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(result, status=status.HTTP_200_OK)


class VisionAlertView(APIView):
    def post(self, request):
        serializer = VisionAlertCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        scan = get_object_or_404(
            VisionScan.objects.filter(user=request.user),
            scan_id=values["scan_id"],
        )
        if not scan.fire_detected:
            return Response(
                {"detail": "This analysis has no fire-class detection to confirm."},
                status=status.HTTP_409_CONFLICT,
            )
        if (
            values["hazard_type"] != "Fire"
            or values["camera_id"] != scan.camera_id
            or values["personnel_count"] != scan.personnel_count
        ):
            return Response(
                {"detail": "The alert details must match the server-recorded video analysis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            camera = camera_configuration(scan.camera_id)
        except VisionConfigurationError as error:
            return Response({"detail": str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except VisionInputError as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        configured_exits = {camera["primary_exit"], camera["secondary_exit"]}
        if values["selected_exit"] not in configured_exits:
            return Response(
                {"detail": "The selected exit is not configured for this camera zone."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_alert = VisionAlert.objects.filter(scan=scan).first()
        if existing_alert:
            if existing_alert.selected_exit != values["selected_exit"]:
                return Response(
                    {"detail": "An alert for this analysis was already recorded with a different route."},
                    status=status.HTTP_409_CONFLICT,
                )
            return self.alert_response(existing_alert, status.HTTP_200_OK)

        try:
            with transaction.atomic():
                alert = VisionAlert.objects.create(
                    scan=scan,
                    user=request.user,
                    selected_exit=values["selected_exit"],
                    operator_confirmed=True,
                )
        except IntegrityError:
            existing_alert = VisionAlert.objects.filter(scan=scan).first()
            if existing_alert and existing_alert.selected_exit == values["selected_exit"]:
                return self.alert_response(existing_alert, status.HTTP_200_OK)
            return Response(
                {"detail": "An alert for this analysis was already recorded."},
                status=status.HTTP_409_CONFLICT,
            )

        return self.alert_response(alert, status.HTTP_201_CREATED)

    @staticmethod
    def alert_response(alert, response_status):
        return Response(
            {
                "alert_id": str(alert.alert_id),
                "scan_id": str(alert.scan_id),
                "hazard_type": "Fire",
                "camera_id": alert.scan.camera_id,
                "zone_name": alert.scan.zone_name,
                "selected_exit": alert.selected_exit,
                "personnel_count": alert.scan.personnel_count,
                "status": "recorded_in_demo_backend",
                "message": "Recorded by the FieldSafe demo backend. No external response unit was contacted.",
            },
            status=response_status,
        )
