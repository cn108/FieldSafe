import uuid
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Employee, HazardReport, Site, VisionAlert, VisionScan
from .vision import VisionConfigurationError, analyze_recording


class HazardSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="field-user", password="a-safe-test-password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.employee = Employee.objects.get(full_name="Amina Okafor")
        self.employee.user = self.user
        self.employee.save(update_fields=["user"])
        self.site = Site.objects.get(facility_name="Bonny Island Terminal")

    def payload(self, report_id=None):
        return {
            "device_id": "test-device",
            "reports": [
                {
                    "report_id": str(report_id or uuid.uuid4()),
                    "employee_id": str(self.employee.employee_id),
                    "site_id": str(self.site.site_id),
                    "description": "Oil spill near pump P-302.",
                    "risk_score": 4,
                    "local_timestamp": "2026-10-07T14:32:00Z",
                },
            ],
        }

    def test_sync_creates_report_using_client_timestamp(self):
        response = self.client.post("/api/v1/hazards/sync/", self.payload(), format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 1)
        self.assertEqual(response.data["updated"], 0)
        report = HazardReport.objects.get()
        self.assertEqual(report.description, "Oil spill near pump P-302.")
        self.assertEqual(report.risk_score, 4)
        self.assertEqual(report.created_at.isoformat(), "2026-10-07T14:32:00+00:00")

    def test_retry_updates_the_existing_report_without_duplicating_it(self):
        report_id = uuid.uuid4()
        payload = self.payload(report_id)
        self.client.post("/api/v1/hazards/sync/", payload, format="json")
        payload["reports"][0]["description"] = "Oil spill contained near pump P-302."

        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(response.data["updated"], 1)
        self.assertEqual(HazardReport.objects.count(), 1)
        self.assertEqual(HazardReport.objects.get().description, "Oil spill contained near pump P-302.")

    def test_status_and_evidence_sync_and_update(self):
        report_id = uuid.uuid4()
        payload = self.payload(report_id)
        evidence = "data:image/jpeg;base64,/9j/4AAQ"
        payload["reports"][0].update({"status": "in_progress", "evidence_frame": evidence})
        self.client.post("/api/v1/hazards/sync/", payload, format="json")
        report = HazardReport.objects.get()
        self.assertEqual(report.status, "in_progress")
        self.assertEqual(report.evidence_frame, evidence)

        payload["reports"][0]["status"] = "closed"
        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(HazardReport.objects.get().status, "closed")

    def test_sync_without_status_defaults_to_open_and_keeps_existing_status(self):
        report_id = uuid.uuid4()
        payload = self.payload(report_id)
        self.client.post("/api/v1/hazards/sync/", payload, format="json")
        self.assertEqual(HazardReport.objects.get().status, "open")
        HazardReport.objects.update(status="closed")
        self.client.post("/api/v1/hazards/sync/", payload, format="json")
        self.assertEqual(HazardReport.objects.get().status, "closed")

    def test_rejects_invalid_status_and_non_jpeg_evidence(self):
        payload = self.payload()
        payload["reports"][0]["status"] = "archived"
        self.assertEqual(self.client.post("/api/v1/hazards/sync/", payload, format="json").status_code, 400)
        payload = self.payload()
        payload["reports"][0]["evidence_frame"] = "javascript:alert(1)"
        self.assertEqual(self.client.post("/api/v1/hazards/sync/", payload, format="json").status_code, 400)
        self.assertEqual(HazardReport.objects.count(), 0)

    def test_invalid_batch_does_not_partially_sync(self):
        payload = self.payload()
        payload["reports"].append({
            **payload["reports"][0],
            "report_id": str(uuid.uuid4()),
            "site_id": str(uuid.uuid4()),
        })

        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HazardReport.objects.count(), 0)

    def test_rejects_risk_outside_the_required_range(self):
        payload = self.payload()
        payload["reports"][0]["risk_score"] = 6

        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HazardReport.objects.count(), 0)

    def test_rejects_timezone_naive_client_timestamp(self):
        payload = self.payload()
        payload["reports"][0]["local_timestamp"] = "2026-10-07T14:32:00"

        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HazardReport.objects.count(), 0)

    def test_user_cannot_sync_for_an_unassigned_employee(self):
        other_employee = Employee.objects.create(full_name="Grace Nwosu", role="Drilling Engineer")
        payload = self.payload()
        payload["reports"][0]["employee_id"] = str(other_employee.employee_id)

        response = self.client.post("/api/v1/hazards/sync/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(HazardReport.objects.count(), 0)

    def test_sync_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post("/api/v1/hazards/sync/", self.payload(), format="json")

        self.assertEqual(response.status_code, 401)

    def test_jwt_login_allows_catalog_access(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/token/",
            {"username": "field-user", "password": "a-safe-test-password"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        catalog = self.client.get("/api/v1/employees/")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual([employee["employee_id"] for employee in catalog.data], [str(self.employee.employee_id)])


class SmartRigVisionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="vision-user", password="a-safe-test-password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.camera_id = "CAM-04"

    def create_scan(self, fire_detected=True):
        return VisionScan.objects.create(
            user=self.user,
            camera_id=self.camera_id,
            zone_name="Sector 3 - Generator Room",
            fire_detected=fire_detected,
            fire_confidence=0.87 if fire_detected else 0,
            personnel_count=3 if fire_detected else 0,
            frames_analyzed=10,
            duration_seconds=10,
        )

    def test_camera_catalog_uses_floor_plan(self):
        response = self.client.get("/api/v1/vision/cameras/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.camera_id, [camera["camera_id"] for camera in response.data["facilities"]])

    def test_vision_status_reports_model_setup_state_without_faking_readiness(self):
        with patch("reports.views.model_status", return_value={
            "ready": False,
            "message": "Set VISION_MODEL_PATH to a fire-and-person model.",
            "fire_class_names": ["fire", "flame"],
            "person_class_name": "person",
            "sample_interval_seconds": 1,
            "maximum_sampled_frames": 120,
            "maximum_video_seconds": 300,
        }):
            response = self.client.get("/api/v1/vision/status/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["ready"])
        self.assertIn("VISION_MODEL_PATH", response.data["message"])

    @override_settings(VISION_MODEL_PATH="")
    def test_vision_status_does_not_claim_ready_without_model_weights(self):
        response = self.client.get("/api/v1/vision/status/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["ready"])
        self.assertIn("VISION_MODEL_PATH", response.data["message"])

    def test_unconfigured_model_returns_explicit_service_unavailable(self):
        upload = SimpleUploadedFile("rig.mp4", b"demo video", content_type="video/mp4")

        with patch("reports.views.analyze_recording", side_effect=VisionConfigurationError("Set VISION_MODEL_PATH.")):
            response = self.client.post(
                "/api/v1/vision/analyze/",
                {"video": upload, "camera_id": self.camera_id, "confidence": "0.45"},
                format="multipart",
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("VISION_MODEL_PATH", response.data["detail"])
        self.assertEqual(VisionScan.objects.count(), 0)

    def test_video_sampler_counts_people_from_fire_positive_frames(self):
        import cv2
        import numpy as np

        class Values:
            def __init__(self, values):
                self.values = values

            def tolist(self):
                return self.values

        class Boxes:
            def __init__(self, classes, confidences):
                self.cls = Values(classes)
                self.conf = Values(confidences)
                self.xyxy = Values([[2, 2, 20, 20] for _ in classes])

        class Result:
            names = {0: "fire", 1: "person"}

            def __init__(self, boxes):
                self.boxes = boxes

        class FakeModel:
            names = {0: "fire", 1: "person"}

            def __init__(self):
                self.frame_number = 0

            def predict(self, source, conf, verbose):
                self.frame_number += 1
                if self.frame_number == 1:
                    return [Result(Boxes([0, 1, 1], [0.91, 0.8, 0.7]))]
                return [Result(Boxes([1, 1, 1, 1], [0.9, 0.8, 0.7, 0.6]))]

        with tempfile.TemporaryDirectory() as directory:
            video_path = f"{directory}\\sample.avi"
            writer = cv2.VideoWriter(
                video_path,
                cv2.VideoWriter_fourcc(*"MJPG"),
                2.0,
                (32, 32),
            )
            self.assertTrue(writer.isOpened(), "OpenCV MJPG video writer is required by the vision tests.")
            for _ in range(4):
                writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
            writer.release()

            with open(video_path, "rb") as video_file:
                upload = SimpleUploadedFile("sample.avi", video_file.read(), content_type="video/x-msvideo")

        vision_status = {
            "ready": True,
            "fire_class_names": ["fire", "flame"],
            "person_class_name": "person",
            "maximum_sampled_frames": 120,
            "maximum_video_seconds": 300,
        }
        with (
            patch("reports.vision.model_status", return_value=vision_status),
            patch("reports.vision._load_model", return_value=FakeModel()),
        ):
            result = analyze_recording(upload, self.camera_id, 0.45)

        self.assertTrue(result["fire_detected"])
        self.assertEqual(result["personnel_count"], 2)
        self.assertEqual(result["frames_analyzed"], 2)
        self.assertEqual(result["fire_positive_frames"], 1)
        self.assertTrue(result["evidence_frame"].startswith("data:image/jpeg;base64,"))

    def test_no_fire_analysis_has_no_evidence_frame(self):
        import cv2
        import numpy as np

        class Empty:
            names = {0: "fire", 1: "person"}
            boxes = None

        class FakeModel:
            names = {0: "fire", 1: "person"}

            def predict(self, source, conf, verbose):
                return [Empty()]

        with tempfile.TemporaryDirectory() as directory:
            video_path = f"{directory}\\blank.avi"
            writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (32, 32))
            for _ in range(2):
                writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
            writer.release()
            with open(video_path, "rb") as video_file:
                upload = SimpleUploadedFile("blank.avi", video_file.read(), content_type="video/x-msvideo")
        vision_status = {
            "ready": True,
            "fire_class_names": ["fire"],
            "person_class_name": "person",
            "maximum_sampled_frames": 120,
            "maximum_video_seconds": 300,
        }
        with (
            patch("reports.vision.model_status", return_value=vision_status),
            patch("reports.vision._load_model", return_value=FakeModel()),
        ):
            result = analyze_recording(upload, self.camera_id, 0.45)
        self.assertFalse(result["fire_detected"])
        self.assertIsNone(result["evidence_frame"])

    def test_analysis_persists_model_result_without_sending_alert(self):
        scan_id = uuid.uuid4()
        result = {
            "scan_id": str(scan_id),
            "camera_id": self.camera_id,
            "zone_name": "Sector 3 - Generator Room",
            "fire_detected": True,
            "fire_confidence": 0.87,
            "personnel_count": 3,
            "frames_analyzed": 10,
            "fire_positive_frames": 2,
            "duration_seconds": 10,
            "sample_interval_seconds": 1,
        }
        upload = SimpleUploadedFile("rig.mp4", b"demo video", content_type="video/mp4")

        with patch("reports.views.analyze_recording", return_value=result):
            response = self.client.post(
                "/api/v1/vision/analyze/",
                {"video": upload, "camera_id": self.camera_id, "confidence": "0.45"},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["personnel_count"], 3)
        self.assertTrue(VisionScan.objects.get(scan_id=scan_id).fire_detected)
        self.assertEqual(VisionAlert.objects.count(), 0)

    def test_video_analysis_rejects_unconfigured_camera(self):
        upload = SimpleUploadedFile("rig.mp4", b"demo video", content_type="video/mp4")

        response = self.client.post(
            "/api/v1/vision/analyze/",
            {"video": upload, "camera_id": "UNKNOWN", "confidence": "0.45"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(VisionScan.objects.count(), 0)

    def test_operator_confirmation_records_alert_once(self):
        scan = self.create_scan()
        payload = {
            "scan_id": str(scan.scan_id),
            "hazard_type": "Fire",
            "camera_id": self.camera_id,
            "personnel_count": 3,
            "selected_exit": "North Stairwell",
            "operator_confirmed": True,
        }

        first = self.client.post("/api/v1/vision/alerts/", payload, format="json")
        retry = self.client.post("/api/v1/vision/alerts/", payload, format="json")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["status"], "recorded_in_demo_backend")
        self.assertEqual(first.data["hazard_type"], "Fire")
        self.assertEqual(first.data["personnel_count"], 3)
        self.assertIn("No external response unit was contacted", first.data["message"])
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.data["alert_id"], first.data["alert_id"])
        self.assertEqual(VisionAlert.objects.count(), 1)

    def test_alert_requires_operator_confirmation_and_a_configured_exit(self):
        scan = self.create_scan()
        payload = {
            "scan_id": str(scan.scan_id),
            "hazard_type": "Fire",
            "camera_id": self.camera_id,
            "personnel_count": 3,
            "selected_exit": "North Stairwell",
            "operator_confirmed": False,
        }
        unconfirmed = self.client.post("/api/v1/vision/alerts/", payload, format="json")
        self.assertEqual(unconfirmed.status_code, 400)

        payload["operator_confirmed"] = True
        payload["selected_exit"] = "Unconfigured exit"
        invalid_exit = self.client.post("/api/v1/vision/alerts/", payload, format="json")
        self.assertEqual(invalid_exit.status_code, 400)
        self.assertEqual(VisionAlert.objects.count(), 0)

    def test_alert_rejects_no_fire_and_other_users_scans(self):
        no_fire_scan = self.create_scan(fire_detected=False)
        no_fire_response = self.client.post(
            "/api/v1/vision/alerts/",
            {
                "scan_id": str(no_fire_scan.scan_id),
                "hazard_type": "Fire",
                "camera_id": self.camera_id,
                "personnel_count": 0,
                "selected_exit": "North Stairwell",
                "operator_confirmed": True,
            },
            format="json",
        )
        self.assertEqual(no_fire_response.status_code, 409)

        other_user = get_user_model().objects.create_user(username="another-operator", password="a-safe-test-password")
        other_scan = VisionScan.objects.create(
            user=other_user,
            camera_id=self.camera_id,
            zone_name="Sector 3 - Generator Room",
            fire_detected=True,
            fire_confidence=0.8,
            personnel_count=1,
            frames_analyzed=4,
            duration_seconds=4,
        )
        other_response = self.client.post(
            "/api/v1/vision/alerts/",
            {
                "scan_id": str(other_scan.scan_id),
                "hazard_type": "Fire",
                "camera_id": self.camera_id,
                "personnel_count": 1,
                "selected_exit": "North Stairwell",
                "operator_confirmed": True,
            },
            format="json",
        )
        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(VisionAlert.objects.count(), 0)

    def test_alert_rejects_client_details_that_do_not_match_analysis(self):
        scan = self.create_scan()
        response = self.client.post(
            "/api/v1/vision/alerts/",
            {
                "scan_id": str(scan.scan_id),
                "hazard_type": "Fire",
                "camera_id": "CAM-02",
                "personnel_count": 99,
                "selected_exit": "North Stairwell",
                "operator_confirmed": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(VisionAlert.objects.count(), 0)
