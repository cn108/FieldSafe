# FieldSafe — HSE Field Reporter

![CI](https://github.com/cn108/FieldSafe/actions/workflows/ci.yml/badge.svg)

An offline-first hazard-reporting MVP inspired by the HSE Field Reporter implementation guide. The installable web app stores reports in IndexedDB, assigns UUIDs on the device, and keeps them queued until an authenticated sync succeeds. The Django API accepts idempotent batches and preserves each report's local event timestamp.

## Run locally on Windows

1. From the project folder, create and activate a virtual environment, then install the backend requirements:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. In that terminal, initialize the database and create a local admin account:

   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```

3. In a second terminal opened in this folder, serve the web app:

   ```powershell
   python -m http.server 5500
   ```

4. Open `http://127.0.0.1:5500`, open **Field settings** from the profile at the bottom of the sidebar, set the sync API address to `http://127.0.0.1:8000/api/v1`, and sign in with the admin account.

The app works without signing in or having a connection: create reports and they stay in this browser's local database. Signing in loads the server's site and employee catalog and enables manual or connection-restored batch sync. In the admin site at `http://127.0.0.1:8000/admin/`, create field-user accounts and assign each account to its `Employee` record before using a non-admin field account. A field user can only sync reports under their assigned employee; admin accounts can manage the demo catalog.

## API

- `POST /api/token/` — obtain a JWT access and refresh token
- `POST /api/token/refresh/` — refresh an expired access token
- `GET /api/v1/sites/` — retrieve the field-site catalog
- `GET /api/v1/employees/` — retrieve the employee catalog
- `POST /api/v1/hazards/sync/` — validate and idempotently upsert up to 100 reports

The sync endpoint accepts `device_id` and a `reports` array containing `report_id`, `employee_id`, `site_id`, `description`, `risk_score` (1–5), and timezone-aware `local_timestamp`. Each report may also carry a follow-up `status` (`open`, `in_progress` or `closed`) and an `evidence_frame` (an embedded JPEG data URL, up to 400 KB). A successful response includes `synced_report_ids`; the browser only marks those reports synced after receiving the success response. Changing a report's status marks it as awaiting sync again, and the retry updates the existing server record. The API uses SQLite for local development; the model schema uses UUID primary keys and can be migrated to PostgreSQL for deployment.

## Dashboard, follow-up and export

- The **Overview** page includes a safety dashboard: hazard status, risk-level mix and a seven-day activity chart, all computed on the device so it works offline.
- Every report has a follow-up status (Open → In progress → Closed) that can be changed from the report list and filtered on the Hazard reports page.
- **Export CSV** downloads all local reports. Cells starting with `=`, `+`, `-` or `@` are prefixed to prevent spreadsheet formula injection.

## Smart Rig AI (recorded-video simulation)

The **Smart Rig AI** workspace adds an authenticated, operator-initiated video-analysis flow:

- `GET /api/v1/vision/status/` — check whether the OpenCV and YOLO runtime and a configured model are ready
- `GET /api/v1/vision/cameras/` — retrieve camera zones and their configured primary/alternate exits
- `POST /api/v1/vision/analyze/` — analyze an uploaded MP4/MOV/AVI/MKV recording; accepts multipart `video`, `camera_id`, and optional `confidence` fields
- `POST /api/v1/vision/alerts/` — record an operator-confirmed alert for a server-recorded fire-positive scan

Install the requirements from the first-run instructions, then configure a **YOLO model whose class list includes both `person` and `fire` or `flame`** before starting Django:

```powershell
$env:VISION_MODEL_PATH = "C:\models\rig-fire-and-person.pt"
$env:VISION_FIRE_CLASS_NAMES = "fire,flame"
python manage.py runserver
```

Point `VISION_MODEL_PATH` to model weights you have obtained and validated for this use; weights are intentionally not bundled or downloaded automatically. The standard COCO `yolov8n.pt` model does **not** contain a fire class and is not a valid fire detector. If your fire model has no `person` class, also set `VISION_PERSON_MODEL_PATH` to a second model (for example COCO `yolov8n.pt`); people are then counted with that model in fire-positive frames. The server returns an explicit service-unavailable error rather than reporting a successful or negative fire analysis when a compatible model is not configured. Set `VISION_PERSON_CLASS_NAME` if the person class uses a different name. Do not use an unvalidated or demo model to direct real-world emergency response.

When fire is detected, the review panel shows the **highest-scoring frame with boxes drawn around detected fire and people**. **Log as hazard report** prefills a hazard report from the analysis and attaches that annotated frame, which can be viewed later from the report list. You can also record a clip directly with the device camera instead of uploading a file.

Edit [`floorplan.json`](./floorplan.json) to configure camera IDs, zones, site UUIDs, and the two displayed exit options. This is a static routing reference—not a live indoor map, route calculation, or confirmation that an exit is safe. The server verifies submitted camera and exit IDs against this file.

The demo accepts videos up to 100 MB and 300 seconds, samples at most 120 frames at approximately one-second intervals, processes the video in a temporary directory, and does not retain the recording. Personnel count is the highest detected number in an individual fire-positive sampled frame, not a unique-person tracking count. Scan results are retained for review; no alert is sent automatically. An alert is recorded in the Django database only after an authenticated operator reviews the clip and confirms the configured route. The backend does not contact an external response unit. The optional spoken prompt uses the browser's speech output on the operator's device; it does not play over CCTV, radios, or site speakers.

This feature is a **simulation, not a certified safety or emergency system**: it does not monitor live CCTV, and computer vision may miss hazards or return false detections. Follow approved site emergency procedures and current on-site instructions; never use the demo output alone to decide whether to evacuate or which exit is safe.

## Known limitations

- Detection accuracy of the community fire model has not been validated on rig footage; treat results as a prompt for human review.
- Evidence frames are stored as base64 text in the database for simplicity; a production build would use object storage.
- No role-based permissions beyond field user vs. admin, and no deployment config (Docker/PostgreSQL) yet.

## Checks

```powershell
python manage.py check
python manage.py test
node --check app.js
node --check sw.js
```

Before deployment, set a strong `DJANGO_SECRET_KEY`, configure `DJANGO_ALLOWED_HOSTS` and `DJANGO_CORS_ALLOWED_ORIGINS`, set `DJANGO_DEBUG=false`, use PostgreSQL, and serve the app over HTTPS. The included settings and seeded catalog are for local development only.
