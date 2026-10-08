import importlib.util
import logging
import os
import tempfile
import threading
import uuid
from functools import lru_cache
from pathlib import Path

from django.conf import settings

_MODEL_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class VisionConfigurationError(Exception):
    pass


class VisionInputError(Exception):
    pass


def load_floor_plan():
    import json

    try:
        with (settings.BASE_DIR / "floorplan.json").open(encoding="utf-8") as floorplan_file:
            floor_plan = json.load(floorplan_file)
    except (OSError, ValueError) as error:
        raise VisionConfigurationError("The camera floor-plan configuration is missing or invalid.") from error

    facilities = floor_plan.get("facilities")
    if not isinstance(facilities, list) or not facilities:
        raise VisionConfigurationError("The camera floor-plan configuration contains no camera zones.")
    camera_ids = set()
    for camera in facilities:
        if not isinstance(camera, dict) or any(
            not isinstance(camera.get(field), str) or not camera[field].strip()
            for field in ("camera_id", "zone_name", "primary_exit", "secondary_exit")
        ):
            raise VisionConfigurationError(
                "Every floor-plan camera must include an ID, zone name, primary exit, and alternate exit."
            )
        if camera["camera_id"] in camera_ids:
            raise VisionConfigurationError("Camera IDs in the floor-plan configuration must be unique.")
        camera_ids.add(camera["camera_id"])
    return facilities


def camera_configuration(camera_id):
    for camera in load_floor_plan():
        if camera.get("camera_id") == camera_id:
            return camera
    raise VisionInputError("The selected camera is not present in the configured floor plan.")


def model_status():
    model_path = getattr(settings, "VISION_MODEL_PATH", "")
    configured = bool(model_path and Path(model_path).is_file())
    dependencies_available = (
        importlib.util.find_spec("cv2") is not None
        and importlib.util.find_spec("ultralytics") is not None
    )
    ready = configured and dependencies_available
    if not model_path:
        message = "Set VISION_MODEL_PATH to a YOLO model trained with fire/flame and person classes."
    elif not configured:
        message = "The configured YOLO model file could not be found."
    elif not dependencies_available:
        message = "Install the vision dependencies from requirements.txt."
    else:
        message = "Vision runtime and model file are configured; class labels are validated before analysis."
    try:
        maximum_sampled_frames = int(os.environ.get("VISION_MAX_VIDEO_FRAMES", "120"))
        maximum_video_seconds = int(os.environ.get("VISION_MAX_VIDEO_SECONDS", "300"))
    except ValueError as error:
        raise VisionConfigurationError("Video sampling limits must be valid positive integers.") from error
    if maximum_sampled_frames < 1 or maximum_video_seconds < 1:
        raise VisionConfigurationError("Video sampling limits must be positive.")
    fire_class_names = [
        name.strip().lower()
        for name in os.environ.get("VISION_FIRE_CLASS_NAMES", "fire,flame").split(",")
        if name.strip()
    ]
    person_class_name = os.environ.get("VISION_PERSON_CLASS_NAME", "person").strip().lower()
    if not fire_class_names or not person_class_name:
        raise VisionConfigurationError("Configure at least one fire class and a person class for the YOLO model.")
    return {
        "ready": ready,
        "message": message,
        "fire_class_names": fire_class_names,
        "person_class_name": person_class_name,
        "sample_interval_seconds": 1,
        "maximum_sampled_frames": maximum_sampled_frames,
        "maximum_video_seconds": maximum_video_seconds,
    }


@lru_cache(maxsize=2)
def _load_model(model_path):
    from ultralytics import YOLO

    with _MODEL_LOCK:
        return YOLO(model_path)


def _normalized_class_names(names):
    if isinstance(names, dict):
        return {str(name).strip().lower() for name in names.values()}
    return {str(name).strip().lower() for name in names}


def analyze_recording(uploaded_file, camera_id, confidence):
    status = model_status()
    if not status["ready"]:
        raise VisionConfigurationError(status["message"])

    try:
        import cv2
    except ImportError as error:
        raise VisionConfigurationError("OpenCV is not installed. Install the vision dependencies from requirements.txt.") from error

    camera = camera_configuration(camera_id)
    model_path = str(Path(settings.VISION_MODEL_PATH).resolve())
    try:
        model = _load_model(model_path)
    except Exception as error:
        logger.exception("Could not load the configured Smart Rig YOLO model")
        raise VisionConfigurationError("The configured YOLO model could not be loaded. Check VISION_MODEL_PATH and the model file.") from error
    try:
        model_classes = _normalized_class_names(model.names)
    except (AttributeError, TypeError) as error:
        raise VisionConfigurationError("The configured YOLO model does not expose a valid class list.") from error
    has_fire_class = bool(set(status["fire_class_names"]) & model_classes)
    person_model = None
    person_model_path = getattr(settings, "VISION_PERSON_MODEL_PATH", "")
    if person_model_path:
        try:
            person_model = _load_model(str(Path(person_model_path).resolve()))
            person_model_classes = _normalized_class_names(person_model.names)
        except Exception as error:
            logger.exception("Could not load the Smart Rig person YOLO model")
            raise VisionConfigurationError("The configured person model could not be loaded. Check VISION_PERSON_MODEL_PATH.") from error
        if status["person_class_name"] not in person_model_classes:
            raise VisionConfigurationError("The configured person model does not include the person class.")
        has_person_class = True
    else:
        has_person_class = status["person_class_name"] in model_classes
    if not has_fire_class or not has_person_class:
        raise VisionConfigurationError(
            "The configured YOLO model must include a fire/flame class and a person class, or set VISION_PERSON_MODEL_PATH."
        )
    suffix = Path(uploaded_file.name).suffix.lower()
    sampled_frames = 0
    positive_frames = 0
    maximum_personnel = 0
    maximum_fire_confidence = 0.0
    fire_class_names = set(status["fire_class_names"])
    person_class_name = status["person_class_name"]
    maximum_frames = status["maximum_sampled_frames"]
    maximum_seconds = status["maximum_video_seconds"]

    with tempfile.TemporaryDirectory(prefix="fieldsafe-vision-") as temporary_directory:
        video_path = Path(temporary_directory) / f"{uuid.uuid4()}{suffix}"
        with video_path.open("wb") as output_file:
            for chunk in uploaded_file.chunks():
                output_file.write(chunk)

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise VisionInputError("OpenCV could not read this recording. Try a standard MP4 video.")
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            total_frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            duration_seconds = total_frames / fps if fps > 0 and total_frames > 0 else 0
            if duration_seconds > maximum_seconds:
                raise VisionInputError(
                    f"The recording is {duration_seconds:.0f}s long; this demo accepts up to {maximum_seconds}s."
                )

            frames_per_sample = max(round(fps), 1)
            while sampled_frames < maximum_frames:
                target_frame = sampled_frames * frames_per_sample
                if total_frames > 0 and target_frame >= total_frames:
                    break
                capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                success, frame = capture.read()
                if not success:
                    break
                with _MODEL_LOCK:
                    results = model.predict(source=frame, conf=confidence, verbose=False)
                if results and results[0].boxes is not None:
                    result = results[0]
                    names = result.names
                    class_ids = result.boxes.cls.tolist()
                    confidences = result.boxes.conf.tolist()
                    frame_has_fire = False
                    frame_personnel = 0
                    for class_id, score in zip(class_ids, confidences):
                        class_name = names[int(class_id)].strip().lower()
                        if class_name in fire_class_names:
                            frame_has_fire = True
                            maximum_fire_confidence = max(maximum_fire_confidence, float(score))
                        elif person_model is None and class_name == person_class_name:
                            frame_personnel += 1
                    if frame_has_fire and person_model is not None:
                        with _MODEL_LOCK:
                            person_results = person_model.predict(source=frame, conf=confidence, classes=None, verbose=False)
                        if person_results and person_results[0].boxes is not None:
                            person_names = person_results[0].names
                            frame_personnel = sum(
                                1
                                for class_id in person_results[0].boxes.cls.tolist()
                                if person_names[int(class_id)].strip().lower() == person_class_name
                            )
                    if frame_has_fire:
                        positive_frames += 1
                        maximum_personnel = max(maximum_personnel, frame_personnel)
                sampled_frames += 1
        finally:
            capture.release()

    if sampled_frames == 0:
        raise VisionInputError("No readable video frames were found in this recording.")

    scan_id = uuid.uuid4()
    return {
        "scan_id": str(scan_id),
        "camera_id": camera["camera_id"],
        "zone_name": camera["zone_name"],
        "fire_detected": positive_frames > 0,
        "fire_confidence": round(maximum_fire_confidence, 4),
        "personnel_count": maximum_personnel,
        "frames_analyzed": sampled_frames,
        "fire_positive_frames": positive_frames,
        "duration_seconds": round(duration_seconds, 2),
        "sample_interval_seconds": 1,
    }
