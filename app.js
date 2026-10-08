const DB_NAME = "fieldsafe";
const DB_VERSION = 1;
const SITES = [
  { id: "7b0b0e6c-cf30-4d30-94bb-1e60b8323a01", name: "Bonny Island Terminal", region: "Onshore · Niger Delta" },
  { id: "7b0b0e6c-cf30-4d30-94bb-1e60b8323a02", name: "Bonga FPSO", region: "Offshore · Gulf of Guinea" },
  { id: "7b0b0e6c-cf30-4d30-94bb-1e60b8323a03", name: "OML 29", region: "Onshore · Rivers State" },
  { id: "7b0b0e6c-cf30-4d30-94bb-1e60b8323a04", name: "Port Harcourt Refinery", region: "Onshore · Rivers State" },
];
const EMPLOYEES = [
  { id: "8c0b0e6c-cf30-4d30-94bb-1e60b8323a01", name: "Amina Okafor", role: "HSE Officer" },
  { id: "8c0b0e6c-cf30-4d30-94bb-1e60b8323a02", name: "Tunde Eze", role: "Field Technician" },
  { id: "8c0b0e6c-cf30-4d30-94bb-1e60b8323a03", name: "Grace Nwosu", role: "Drilling Engineer" },
];
const DEFAULT_VISION_CAMERAS = [
  {
    camera_id: "CAM-04",
    zone_name: "Sector 3 - Generator Room",
    primary_exit: "North Stairwell",
    secondary_exit: "East Blast Door",
  },
  {
    camera_id: "CAM-02",
    zone_name: "Pump Deck - Transfer Line",
    primary_exit: "West Muster Route",
    secondary_exit: "South Access Stair",
  },
];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let db;
let installPrompt;
let sites = [...SITES];
let employees = [...EMPLOYEES];
let settings = { employeeId: EMPLOYEES[0].id, siteId: SITES[0].id, apiUrl: "" };
let visionCameras = [];
let visionAnalysis = null;
let visionFloorPlanWarning = "";

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      const reports = database.createObjectStore("reports", { keyPath: "reportId" });
      reports.createIndex("localTimestamp", "localTimestamp");
      database.createObjectStore("metadata", { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Close other FieldSafe tabs and try again."));
  });
}

function storeRequest(storeName, mode, action) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, mode);
    const request = action(transaction.objectStore(storeName));
    let result;
    request.onsuccess = () => { result = request.result; };
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => resolve(result);
    transaction.onabort = () => reject(transaction.error || new Error("The local save did not complete."));
  });
}

const getReports = () => storeRequest("reports", "readonly", (store) => store.getAll());
const getMetadata = (key) => storeRequest("metadata", "readonly", (store) => store.get(key));
const saveMetadata = (value) => storeRequest("metadata", "readwrite", (store) => store.put(value));
const saveReport = (report) => storeRequest("reports", "readwrite", (store) => store.put(report));

function formatDate(dateValue, includeTime = true) {
  const date = new Date(dateValue);
  return new Intl.DateTimeFormat("en-GB", includeTime
    ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }
    : { day: "numeric", month: "short", year: "numeric" }).format(date);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function employeeById(id) {
  return employees.find((employee) => employee.id === id) || employees[0];
}

function siteById(id) {
  return sites.find((site) => site.id === id) || sites[0];
}

function riskName(score) {
  return ["", "Low", "Minor", "Moderate", "High", "Critical"][score] || "Unknown";
}

const STATUS_LABELS = { open: "Open", in_progress: "In progress", closed: "Closed" };

function reportStatus(report) {
  return STATUS_LABELS[report.status] ? report.status : "open";
}

function reportMarkup(report) {
  const site = siteById(report.siteId) || {};
  const employee = employeeById(report.employeeId) || {};
  const status = report.isSynced
    ? '<span class="sync-status synced"><span></span> Synced</span>'
    : '<span class="sync-status pending"><span></span> Awaiting sync</span>';
  const currentStatus = reportStatus(report);
  const statusOptions = Object.entries(STATUS_LABELS)
    .map(([value, label]) => `<option value="${value}"${value === currentStatus ? " selected" : ""}>${label}</option>`)
    .join("");
  const evidence = report.evidenceFrame
    ? `<button class="evidence-link" type="button" data-evidence="${escapeHtml(report.reportId)}">View detection frame</button>`
    : "";
  return `<article class="report-row">
    <span class="report-risk risk-${report.riskScore}" title="Risk ${report.riskScore} of 5">${report.riskScore}</span>
    <div class="report-details"><strong>${escapeHtml(report.description)}</strong><div class="report-meta"><span>${escapeHtml(report.siteName || site.name || "Unknown facility")}</span><span class="meta-separator">·</span><span>${escapeHtml(report.employeeName || employee.name || "Unknown reporter")}</span><span class="meta-separator">·</span><time datetime="${escapeHtml(report.localTimestamp)}">${formatDate(report.localTimestamp)}</time></div>
    <div class="report-actions"><label class="status-control status-${currentStatus}"><span>Status</span><select data-status-for="${escapeHtml(report.reportId)}" aria-label="Hazard status">${statusOptions}</select></label>${evidence}</div></div>
    <span class="risk-tag risk-tag-${report.riskScore}">${riskName(report.riskScore)}</span>${status}
  </article>`;
}

function renderDashboard(reports) {
  const statusCounts = { open: 0, in_progress: 0, closed: 0 };
  const riskCounts = [0, 0, 0, 0, 0];
  reports.forEach((report) => {
    statusCounts[reportStatus(report)] += 1;
    if (report.riskScore >= 1 && report.riskScore <= 5) riskCounts[report.riskScore - 1] += 1;
  });
  const total = reports.length;
  const bar = (label, count, cssClass) => `<div class="bar-row"><span class="bar-label">${label}</span><span class="bar-track"><span class="bar-fill ${cssClass}" style="width:${total ? Math.round((count / total) * 100) : 0}%"></span></span><strong class="bar-count">${count}</strong></div>`;
  $("#status-chart").innerHTML = Object.entries(STATUS_LABELS).map(([key, label]) => bar(label, statusCounts[key], `status-fill-${key}`)).join("");
  $("#risk-chart").innerHTML = riskCounts.map((count, index) => bar(`${index + 1} · ${riskName(index + 1)}`, count, `risk-fill-${index + 1}`)).join("");

  const days = [];
  for (let offset = 6; offset >= 0; offset -= 1) {
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    day.setDate(day.getDate() - offset);
    days.push({ key: day.toDateString(), label: new Intl.DateTimeFormat("en-GB", { weekday: "short" }).format(day), count: 0 });
  }
  reports.forEach((report) => {
    const match = days.find((day) => day.key === new Date(report.localTimestamp).toDateString());
    if (match) match.count += 1;
  });
  const peak = Math.max(1, ...days.map((day) => day.count));
  $("#trend-chart").innerHTML = days.map((day) => `<div class="trend-col"><strong>${day.count}</strong><span class="trend-bar"><span style="height:${Math.round((day.count / peak) * 100)}%"></span></span><small>${day.label}</small></div>`).join("");
}

function renderReports(reports) {
  reports.sort((a, b) => new Date(b.localTimestamp) - new Date(a.localTimestamp));
  const pending = reports.filter((report) => !report.isSynced).length;
  const today = new Date().toDateString();
  $("#stat-total").textContent = reports.length;
  $("#stat-pending").textContent = pending;
  $("#stat-today").textContent = reports.filter((report) => new Date(report.localTimestamp).toDateString() === today).length;
  $("#stat-high").textContent = reports.filter((report) => report.riskScore >= 4).length;
  $("#nav-pending").textContent = pending;
  $("#sync-count").textContent = pending;
  $("#sync-now").disabled = pending === 0;
  const recent = reports.slice(0, 4);
  $("#recent-list").innerHTML = recent.length
    ? recent.map(reportMarkup).join("")
    : '<div class="empty-state"><span class="empty-icon">✳</span><strong>No hazards logged yet</strong><span>Your observations will show up here.</span><button class="text-link" data-go="new-report" type="button">Log your first report <span aria-hidden="true">→</span></button></div>';

  const search = ($("#report-search")?.value || "").trim().toLowerCase();
  const riskFilter = $("#risk-filter")?.value || "all";
  const syncFilter = $("#sync-filter")?.value || "all";
  const statusFilter = $("#status-filter")?.value || "all";
  renderDashboard(reports);
  const filtered = reports.filter((report) => {
    const searchable = `${report.description} ${report.area || ""} ${report.siteName || siteById(report.siteId)?.name || ""} ${report.employeeName || employeeById(report.employeeId)?.name || ""}`.toLowerCase();
    return (!search || searchable.includes(search))
      && (statusFilter === "all" || reportStatus(report) === statusFilter)
      && (riskFilter === "all" || (riskFilter === "high" ? report.riskScore >= 4 : report.riskScore <= 3))
      && (syncFilter === "all" || (syncFilter === "pending" ? !report.isSynced : report.isSynced));
  });
  $("#all-reports-list").innerHTML = filtered.length
    ? filtered.map(reportMarkup).join("")
    : '<div class="empty-state"><span class="empty-icon">⌕</span><strong>No matching reports</strong><span>Try changing your search or filters.</span></div>';
}

function populateSelects() {
  $("#site").innerHTML = sites.map((site) => `<option value="${site.id}">${escapeHtml(site.name)}</option>`).join("");
  $("#default-site").innerHTML = sites.map((site) => `<option value="${site.id}">${escapeHtml(site.name)}</option>`).join("");
  $("#employee").innerHTML = employees.map((employee) => `<option value="${employee.id}">${escapeHtml(employee.name)} — ${escapeHtml(employee.role)}</option>`).join("");
  $("#site").value = siteById(settings.siteId).id;
  $("#employee").value = employeeById(settings.employeeId).id;
  $("#default-site").value = siteById(settings.siteId).id;
  $("#api-url").value = settings.apiUrl;
  updateProfile();
}

function updateProfile() {
  const employee = employeeById(settings.employeeId);
  const site = siteById(settings.siteId);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  $("#welcome-title").textContent = `Good ${greeting}, ${employee.name.split(/\s+/)[0]}.`;
  $("#profile-name").textContent = employee.name;
  $("#profile-site").textContent = site.name;
  $("#profile-avatar").textContent = employee.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase();
  $("#banner-site").textContent = site.name;
  $("#banner-region").textContent = site.region.toUpperCase();
}

function updateConnection() {
  const online = navigator.onLine;
  $("#connection-label").textContent = online ? "Connection available" : "You're offline";
  $("#sync-label").textContent = online ? "Saved reports are ready to sync" : "Reports save safely on this device";
  $("#connection-dot").classList.toggle("is-offline", !online);
  $("#top-connection").classList.toggle("is-offline", !online);
  $("#top-connection").lastElementChild.textContent = online ? "Online" : "Offline";
}

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  toast.textContent = message;
  $("#toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 4000);
}

function apiBaseUrl() {
  if (!settings.apiUrl) throw new Error("Configure the API address and sign in from Field settings first.");
  return settings.apiUrl.replace(/\/+$/, "");
}

async function authorizedApiFetch(path, options = {}) {
  if (!navigator.onLine) throw new Error("The analysis server is unavailable while offline.");
  const baseUrl = apiBaseUrl();
  const token = await getMetadata("authToken");
  if (!token?.value) throw new Error("Sign in from Field settings before using Smart Rig AI.");
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${token.value}`);
  let response = await fetch(`${baseUrl}${path}`, { ...options, headers });
  if (response.status === 401) {
    const refresh = await getMetadata("refreshToken");
    if (refresh?.value) {
      const rootUrl = baseUrl.replace(/\/api\/v1$/i, "");
      const refreshed = await fetch(`${rootUrl}/api/token/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: refresh.value }),
      });
      if (refreshed.ok) {
        const tokens = await refreshed.json();
        await saveMetadata({ key: "authToken", value: tokens.access });
        headers.set("Authorization", `Bearer ${tokens.access}`);
        response = await fetch(`${baseUrl}${path}`, { ...options, headers });
      }
    }
  }
  return response;
}

async function responseError(response, fallback) {
  let detail = fallback;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (typeof body.error === "string") detail = body.error;
  } catch {
    if (response.statusText) detail = `${fallback} (${response.status} ${response.statusText})`;
  }
  return new Error(detail);
}

async function loadVisionCameras() {
  try {
    const response = await fetch("./floorplan.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`Could not load the camera floor plan (HTTP ${response.status}).`);
    const floorPlan = await response.json();
    if (!Array.isArray(floorPlan.facilities) || !floorPlan.facilities.length) {
      throw new Error("The floor plan has no camera zones configured.");
    }
    visionCameras = floorPlan.facilities;
    visionFloorPlanWarning = "";
  } catch (error) {
    if (!visionCameras.length) visionCameras = DEFAULT_VISION_CAMERAS;
    visionFloorPlanWarning = "Using the built-in demo camera map because the configured floor plan could not be loaded.";
    console.warn("Smart Rig is using its built-in demo floor plan:", error);
  }
  $("#vision-camera").innerHTML = visionCameras.map((camera) =>
    `<option value="${escapeHtml(camera.camera_id)}">${escapeHtml(camera.camera_id)} · ${escapeHtml(camera.zone_name)}</option>`,
  ).join("");
  $("#analyze-video").disabled = false;
  updateCameraRoute();
  if (visionFloorPlanWarning) updateVisionBackendStatus(visionFloorPlanWarning, false);
}

async function refreshVisionBackendStatus() {
  const token = await getMetadata("authToken");
  if (!settings.apiUrl || !token?.value) {
    updateVisionBackendStatus("Sign in and configure the analysis API in Field settings.", false);
    return;
  }
  try {
    const response = await authorizedApiFetch("/vision/status/");
    if (!response.ok) throw await responseError(response, "Could not check the vision service.");
    const health = await response.json();
    updateVisionBackendStatus(
      visionFloorPlanWarning ? `${visionFloorPlanWarning} ${health.message}` : health.message,
      health.ready && !visionFloorPlanWarning,
    );
  } catch (error) {
    updateVisionBackendStatus(
      visionFloorPlanWarning ? `${visionFloorPlanWarning} ${error.message}` : error.message,
      false,
    );
  }
}

function updateCameraRoute() {
  const camera = visionCameras.find((item) => item.camera_id === $("#vision-camera").value);
  if (!camera) return;
  $("#route-primary").textContent = camera.primary_exit;
  $("#route-secondary").textContent = camera.secondary_exit;
}

function updateVisionBackendStatus(message, ready = false) {
  $("#vision-backend-dot").classList.toggle("is-online", ready);
  $("#vision-backend-dot").classList.toggle("is-offline", !ready);
  $("#vision-backend-label").textContent = message;
}

function resetVisionReview() {
  visionAnalysis = null;
  $("#vision-result").hidden = true;
  $("#vision-alert-review").hidden = true;
  $("#vision-no-fire").hidden = true;
  $("#vision-evidence").hidden = true;
  $("#play-voice-prompt").hidden = true;
  $("#operator-confirm").checked = false;
  $("#send-vision-alert").disabled = true;
  $("#vision-result-status").textContent = "REVIEW";
}

function showVisionAnalysis(result) {
  visionAnalysis = result;
  const camera = visionCameras.find((item) => item.camera_id === result.camera_id);
  if (!camera) throw new Error("The analysis result refers to a camera not in the configured floor plan.");
  $("#vision-result").hidden = false;
  $("#vision-result-status").textContent = result.fire_detected ? "OPERATOR REVIEW REQUIRED" : "NO FIRE CLASS DETECTED";
  $("#result-fire").textContent = result.fire_detected ? "Possible fire" : "Not detected";
  $("#result-confidence").textContent = result.fire_detected
    ? `Highest model score ${(result.fire_confidence * 100).toFixed(1)}% · not a verified probability`
    : "No fire-class detection in sampled frames";
  $("#result-personnel").textContent = String(result.personnel_count);
  $("#result-frames").textContent = `${result.frames_analyzed} · ${Math.round(result.duration_seconds)}s`;
  $("#result-zone").textContent = camera.zone_name;
  $("#result-exit").innerHTML = [
    `<option value="${escapeHtml(camera.primary_exit)}">${escapeHtml(camera.primary_exit)} · configured primary</option>`,
    `<option value="${escapeHtml(camera.secondary_exit)}">${escapeHtml(camera.secondary_exit)} · configured alternate</option>`,
  ].join("");
  $("#vision-alert-review").hidden = !result.fire_detected;
  $("#vision-no-fire").hidden = result.fire_detected;
  $("#vision-evidence").hidden = !result.evidence_frame;
  if (result.evidence_frame) $("#vision-evidence-image").src = result.evidence_frame;
  $("#operator-confirm").checked = false;
  $("#send-vision-alert").disabled = true;
  $("#play-voice-prompt").hidden = true;
  $("#vision-result").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyzeVisionVideo(event) {
  event.preventDefault();
  const file = $("#vision-video").files[0];
  const cameraId = $("#vision-camera").value;
  if (!file) {
    showToast("Choose a recorded video first.", "error");
    return;
  }
  if (file.size > 100 * 1024 * 1024) {
    showToast("The recording is larger than the 100 MB demo limit.", "error");
    return;
  }
  if (!/\.(mp4|mov|avi|mkv)$/i.test(file.name)) {
    showToast("Choose an MP4, MOV, AVI, or MKV recording.", "error");
    return;
  }
  resetVisionReview();
  const button = $("#analyze-video");
  button.disabled = true;
  $("#vision-progress").hidden = false;
  $("#vision-progress-label").textContent = "Sampling video frames and running the configured model…";
  try {
    const body = new FormData();
    body.append("video", file);
    body.append("camera_id", cameraId);
    body.append("confidence", $("#vision-confidence").value);
    const response = await authorizedApiFetch("/vision/analyze/", { method: "POST", body });
    if (!response.ok) throw await responseError(response, "Video analysis failed.");
    const result = await response.json();
    showVisionAnalysis(result);
    updateVisionBackendStatus("Analysis completed by the configured server model.", true);
    showToast(result.fire_detected
      ? "Possible fire-class signal found. Review it; no alert has been sent."
      : "Analysis complete. No fire-class signal was found in sampled frames.");
  } catch (error) {
    updateVisionBackendStatus(error.message, false);
    showToast(error instanceof Error ? error.message : "Video analysis failed.", "error");
  } finally {
    button.disabled = false;
    $("#vision-progress").hidden = true;
  }
}

async function sendVisionAlert() {
  if (!visionAnalysis || !$("#operator-confirm").checked) return;
  const button = $("#send-vision-alert");
  button.disabled = true;
  button.textContent = "Sending confirmed alert…";
  try {
    const response = await authorizedApiFetch("/vision/alerts/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scan_id: visionAnalysis.scan_id,
        hazard_type: "Fire",
        camera_id: visionAnalysis.camera_id,
        personnel_count: visionAnalysis.personnel_count,
        selected_exit: $("#result-exit").value,
        operator_confirmed: true,
      }),
    });
    if (!response.ok) throw await responseError(response, "The confirmed alert could not be recorded.");
    const alert = await response.json();
    $("#vision-result-status").textContent = "CONFIRMATION RECORDED";
    $("#play-voice-prompt").hidden = false;
    button.textContent = "Alert recorded in demo API";
    showToast(`Operator-confirmed alert ${alert.alert_id} was recorded by the demo API.`);
  } catch (error) {
    button.disabled = false;
    button.textContent = "Confirm & send alert to demo API";
    showToast(error instanceof Error ? error.message : "The alert could not be recorded.", "error");
  }
}

let pendingReportEvidence = "";

function setReportEvidence(dataUrl) {
  pendingReportEvidence = dataUrl;
  $("#report-evidence").hidden = !dataUrl;
  if (dataUrl) $("#report-evidence-image").src = dataUrl;
}

function logVisionAsReport() {
  if (!visionAnalysis) return;
  const camera = visionCameras.find((item) => item.camera_id === visionAnalysis.camera_id);
  const zone = camera ? camera.zone_name : visionAnalysis.zone_name;
  const fileName = $("#vision-video").files[0]?.name || "uploaded recording";
  const summary = visionAnalysis.fire_detected
    ? `Smart Rig AI flagged a possible fire in ${zone} (camera ${visionAnalysis.camera_id}, model score ${(visionAnalysis.fire_confidence * 100).toFixed(1)}%, ${visionAnalysis.fire_positive_frames} of ${visionAnalysis.frames_analyzed} sampled frames). Up to ${visionAnalysis.personnel_count} people were visible in a fire-positive frame.`
    : `Smart Rig AI reviewed a recording from ${zone} (camera ${visionAnalysis.camera_id}) and found no fire-class signal in ${visionAnalysis.frames_analyzed} sampled frames.`;
  const description = `${summary} Source video: ${fileName}. Scan ${visionAnalysis.scan_id}. Automated model output; verify on site.`;
  $("#description").value = description.slice(0, 2000);
  $("#description").setCustomValidity("");
  $("#character-count").textContent = `${$("#description").value.length} / 2000`;
  $("#area").value = zone.slice(0, 120);
  setReportEvidence(visionAnalysis.evidence_frame || "");
  const riskValue = visionAnalysis.fire_detected ? (visionAnalysis.personnel_count > 0 ? "5" : "4") : null;
  document.querySelectorAll('input[name="risk"]').forEach((input) => {
    input.checked = input.value === riskValue;
  });
  navigate("new-report");
  showToast(visionAnalysis.fire_detected
    ? "Report prefilled with the analysis. Review it, confirm the risk and save."
    : "Report prefilled. Choose a risk level, review and save.");
}

function playVisionPrompt() {
  if (!visionAnalysis || !window.speechSynthesis) {
    showToast("Speech output is unavailable in this browser.", "error");
    return;
  }
  const camera = visionCameras.find((item) => item.camera_id === visionAnalysis.camera_id);
  const exit = $("#result-exit").value;
  const message = `Demonstration prompt. Possible fire reported in ${camera.zone_name}. ${visionAnalysis.personnel_count} personnel detected in sampled frames. Follow official site emergency procedures and use ${exit} only if verified safe by site personnel.`;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(message));
}

function navigate(view) {
  const validViews = ["overview", "reports", "new-report", "smart-rig"];
  const target = validViews.includes(view) ? view : "overview";
  $$(".view").forEach((section) => {
    const active = section.id === `view-${target}`;
    section.hidden = !active;
    section.classList.toggle("active-view", active);
  });
  $$(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.view === target));
  $("#page-crumb").textContent = { overview: "Overview", reports: "Hazard reports", "new-report": "Log a hazard", "smart-rig": "Smart Rig AI" }[target];
  if (location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (target === "new-report") $("#description").focus({ preventScroll: true });
  if (target === "smart-rig" && visionFloorPlanWarning) {
    loadVisionCameras().then(refreshVisionBackendStatus);
  }
}

async function exportReportsCsv() {
  const reports = await getReports();
  if (!reports.length) {
    showToast("There are no reports to export yet.", "error");
    return;
  }
  const cell = (value) => {
    let text = String(value ?? "");
    if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const header = ["Report ID", "Date", "Facility", "Reporter", "Risk", "Status", "Synced", "Has detection frame", "Description"];
  const rows = reports
    .sort((a, b) => new Date(b.localTimestamp) - new Date(a.localTimestamp))
    .map((report) => [
      report.reportId,
      report.localTimestamp,
      report.siteName || siteById(report.siteId)?.name || "",
      report.employeeName || employeeById(report.employeeId)?.name || "",
      `${report.riskScore} ${riskName(report.riskScore)}`,
      STATUS_LABELS[reportStatus(report)],
      report.isSynced ? "Yes" : "No",
      report.evidenceFrame ? "Yes" : "No",
      report.description,
    ]);
  const csv = [header, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
  link.download = `fieldsafe-hazards-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  showToast(`Exported ${reports.length} ${reports.length === 1 ? "report" : "reports"}.`);
}

async function syncPendingReports() {
  const pending = (await getReports()).filter((report) => !report.isSynced);
  if (!pending.length) {
    showToast("All reports are up to date.");
    return;
  }
  if (!navigator.onLine) {
    showToast("You're offline. Reports are safe on this device.", "error");
    return;
  }
  if (!settings.apiUrl) {
    showToast("Reports are saved locally. Add a sync API address in field settings to upload them.", "error");
    return;
  }
  const button = $("#sync-now");
  button.disabled = true;
  button.classList.add("is-syncing");
  try {
    const payload = {
        device_id: await getDeviceId(),
        reports: pending.map(({ reportId, employeeId, siteId, description, riskScore, localTimestamp, status, evidenceFrame }) => ({
          report_id: reportId,
          employee_id: employeeId,
          site_id: siteId,
          description,
          risk_score: riskScore,
          local_timestamp: localTimestamp,
          status: STATUS_LABELS[status] ? status : "open",
          ...(evidenceFrame ? { evidence_frame: evidenceFrame } : {}),
        })),
      };
    const response = await authorizedApiFetch("/hazards/sync/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw await responseError(response, "Report sync failed.");
    const result = await response.json();
    const syncedIds = new Set(result.synced_report_ids || pending.map((report) => report.reportId));
    for (const report of pending) {
      if (syncedIds.has(report.reportId)) await saveReport({ ...report, isSynced: true });
    }
    await refreshReports();
    showToast(`${syncedIds.size} ${syncedIds.size === 1 ? "report" : "reports"} synced successfully.`);
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Could not sync reports. They remain saved on this device.", "error");
  } finally {
    button.classList.remove("is-syncing");
    await refreshReports();
  }
}

async function signIn(event) {
  event.preventDefault();
  const apiUrl = String($("#api-url").value || "").trim().replace(/\/+$/, "");
  const username = $("#api-username").value.trim();
  const password = $("#api-password").value;
  if (!apiUrl || !username || !password) {
    showToast("Enter the API address, username, and password to sign in.", "error");
    return;
  }
  const signInButton = $("#sign-in");
  signInButton.disabled = true;
  try {
    const rootUrl = apiUrl.replace(/\/api\/v1$/i, "");
    const response = await fetch(`${rootUrl}/api/token/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) throw new Error(response.status === 401 ? "Username or password was not accepted." : `Sign in failed (HTTP ${response.status}).`);
    const token = await response.json();
    await saveMetadata({ key: "authToken", value: token.access });
    await saveMetadata({ key: "refreshToken", value: token.refresh });
    settings.apiUrl = apiUrl;
    await saveMetadata({ key: "settings", value: settings });
    const headers = { Authorization: `Bearer ${token.access}` };
    const [siteResponse, employeeResponse] = await Promise.all([
      fetch(`${apiUrl}/sites/`, { headers }),
      fetch(`${apiUrl}/employees/`, { headers }),
    ]);
    if (!siteResponse.ok || !employeeResponse.ok) throw new Error("Signed in, but the server could not load the site and employee lists.");
    const [siteData, employeeData] = await Promise.all([siteResponse.json(), employeeResponse.json()]);
    sites = siteData.map((site) => ({ id: site.site_id, name: site.facility_name, region: site.region }));
    employees = employeeData.map((employee) => ({ id: employee.employee_id, name: employee.full_name, role: employee.role }));
    if (!sites.length || !employees.length) throw new Error("The server has no facilities or employees configured yet.");
    const availableEmployee = employees.find((employee) => employee.id === settings.employeeId) || employees[0];
    settings.employeeId = availableEmployee.id;
    await saveMetadata({ key: "remoteCatalog", value: { sites, employees } });
    await saveMetadata({ key: "settings", value: settings });
    populateSelects();
    $("#api-password").value = "";
    $("#auth-status").textContent = `Signed in as ${username}.`;
    $("#sign-out").hidden = false;
    $("#sign-in").textContent = "Refresh session";
    await refreshVisionBackendStatus();
    showToast("Connected. Your field lists are up to date.");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Could not sign in.", "error");
  } finally {
    signInButton.disabled = false;
  }
}

async function getDeviceId() {
  const current = await getMetadata("deviceId");
  if (current?.value) return current.value;
  const value = crypto.randomUUID();
  await saveMetadata({ key: "deviceId", value });
  return value;
}

async function refreshReports() {
  renderReports(await getReports());
}

function registerEvents() {
  document.addEventListener("click", (event) => {
    const navigation = event.target.closest("[data-go], [data-view]");
    if (navigation) {
      event.preventDefault();
      navigate(navigation.dataset.go || navigation.dataset.view);
    }
  });
  window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));
  window.addEventListener("hashchange", () => {
    if (location.hash === "#smart-rig") refreshVisionBackendStatus();
  });
  $("#report-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const reportForm = event.currentTarget;
    if (!reportForm.reportValidity()) return;
    const form = new FormData(reportForm);
    const description = String(form.get("description")).trim();
    if (!description) {
      $("#description").setCustomValidity("Please describe what you observed.");
      $("#description").reportValidity();
      return;
    }
    const report = {
      reportId: crypto.randomUUID(),
      employeeId: settings.employeeId,
      siteId: String(form.get("site")),
      siteName: siteById(String(form.get("site"))).name,
      employeeName: employeeById(settings.employeeId).name,
      area: String(form.get("area") || "").trim(),
      description: description + (String(form.get("area") || "").trim() ? ` — Area: ${String(form.get("area")).trim()}` : ""),
      riskScore: Number(form.get("risk")),
      status: "open",
      evidenceFrame: pendingReportEvidence,
      localTimestamp: new Date().toISOString(),
      isSynced: false,
    };
    try {
      await saveReport(report);
      reportForm.reset();
      setReportEvidence("");
      $("#site").value = settings.siteId;
      $("#character-count").textContent = "0 / 2000";
      await refreshReports();
      showToast("Hazard saved on this device.");
      navigate("overview");
    } catch (error) {
      showToast(`Could not save your report: ${error.message}`, "error");
    }
  });
  $("#description").addEventListener("input", (event) => {
    event.currentTarget.setCustomValidity("");
    $("#character-count").textContent = `${event.currentTarget.value.length} / 2000`;
  });
  $("#open-settings").addEventListener("click", () => $("#settings-dialog").showModal());
  $("#settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const apiUrl = String(form.get("api-url") || "").trim().replace(/\/+$/, "");
    if (apiUrl && !/^https?:\/\//i.test(apiUrl)) {
      $("#api-url").setCustomValidity("Enter a complete URL beginning with http:// or https://.");
      $("#api-url").reportValidity();
      return;
    }
    $("#api-url").setCustomValidity("");
    settings = { employeeId: String(form.get("employee")), siteId: String(form.get("default-site")), apiUrl };
    await saveMetadata({ key: "settings", value: settings });
    populateSelects();
    if ($("#auth-status").textContent.startsWith("Signed in")) {
      $("#auth-status").textContent = "Server address or field settings changed. Refresh your session if needed.";
    }
    await refreshVisionBackendStatus();
    $("#settings-dialog").close();
    showToast("Field settings saved.");
  });
  $("#sign-in").addEventListener("click", signIn);
  $("#sign-out").addEventListener("click", async () => {
    await storeRequest("metadata", "readwrite", (store) => {
      store.delete("authToken");
      store.delete("refreshToken");
      return store.get("authToken");
    });
    $("#auth-status").textContent = "Signed out. Reports remain on this device.";
    updateVisionBackendStatus("Sign in and configure the analysis API in Field settings.", false);
    $("#sign-out").hidden = true;
    $("#sign-in").textContent = "Sign in to sync";
    showToast("Signed out. Your saved reports are unchanged.");
  });
  $("#sync-now").addEventListener("click", syncPendingReports);
  $("#report-search").addEventListener("input", refreshReports);
  $("#risk-filter").addEventListener("change", refreshReports);
  $("#sync-filter").addEventListener("change", refreshReports);
  $("#status-filter").addEventListener("change", refreshReports);
  $("#remove-evidence").addEventListener("click", () => setReportEvidence(""));
  $("#export-reports").addEventListener("click", exportReportsCsv);
  document.addEventListener("change", async (event) => {
    const select = event.target.closest?.("select[data-status-for]");
    if (!select) return;
    const report = (await getReports()).find((item) => item.reportId === select.dataset.statusFor);
    if (!report || !STATUS_LABELS[select.value]) return;
    await saveReport({ ...report, status: select.value, isSynced: false });
    await refreshReports();
    showToast(`Marked ${STATUS_LABELS[select.value].toLowerCase()}. Sync to share the update.`);
  });
  document.addEventListener("click", async (event) => {
    const button = event.target.closest?.("button[data-evidence]");
    if (!button) return;
    const report = (await getReports()).find((item) => item.reportId === button.dataset.evidence);
    if (!report?.evidenceFrame) return;
    $("#evidence-dialog-image").src = report.evidenceFrame;
    $("#evidence-dialog").showModal();
  });
  window.addEventListener("online", async () => {
    updateConnection();
    if (settings.apiUrl) await syncPendingReports();
  });
  window.addEventListener("offline", updateConnection);
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    $("#install-app").hidden = false;
  });
  $("#install-app").addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    $("#install-app").hidden = true;
  });
  $("#vision-camera").addEventListener("change", updateCameraRoute);
  $("#vision-confidence").addEventListener("input", (event) => {
    $("#vision-confidence-value").textContent = `${Math.round(Number(event.currentTarget.value) * 100)}%`;
  });
  $("#vision-video").addEventListener("change", () => {
    const file = $("#vision-video").files[0];
    resetVisionReview();
    $("#video-filename").textContent = file ? file.name : "Choose a recording to analyze";
    $("#video-filemeta").textContent = file
      ? `${(file.size / (1024 * 1024)).toFixed(1)} MB · recording is not stored in the reports history`
      : "Your video stays on the analysis server only for processing.";
  });
  $("#vision-form").addEventListener("submit", analyzeVisionVideo);
  $("#analyze-video").disabled = true;
  $("#operator-confirm").addEventListener("change", (event) => {
    $("#send-vision-alert").disabled = !event.currentTarget.checked || !visionAnalysis;
  });
  $("#send-vision-alert").addEventListener("click", sendVisionAlert);
  $("#log-vision-report").addEventListener("click", logVisionAsReport);
  $("#vision-record").addEventListener("change", (event) => {
    const file = event.currentTarget.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    $("#vision-video").files = transfer.files;
    $("#vision-video").dispatchEvent(new Event("change"));
    event.currentTarget.value = "";
  });
  $("#play-voice-prompt").addEventListener("click", playVisionPrompt);
}

async function initialize() {
  $("#today-date").textContent = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date());
  try {
    db = await openDatabase();
    const saved = await getMetadata("settings");
    if (saved?.value) settings = { ...settings, ...saved.value };
    const remote = await getMetadata("remoteCatalog");
    if (remote?.value?.sites?.length && remote.value.employees?.length) {
      sites = remote.value.sites;
      employees = remote.value.employees;
    }
    populateSelects();
    registerEvents();
    updateConnection();
    await refreshReports();
    try {
      await loadVisionCameras();
    } catch (error) {
      $("#analyze-video").disabled = true;
      updateVisionBackendStatus(error.message, false);
      console.error("Smart Rig camera configuration could not be loaded:", error);
    }
    const token = await getMetadata("authToken");
    if (token?.value) {
      $("#auth-status").textContent = "A sync session is saved on this device.";
      $("#sign-out").hidden = false;
      $("#sign-in").textContent = "Refresh session";
      await refreshVisionBackendStatus();
    } else {
      const statusMessage = "Sign in and configure the analysis API in Field settings.";
      updateVisionBackendStatus(
        visionFloorPlanWarning ? `${visionFloorPlanWarning} ${statusMessage}` : statusMessage,
        false,
      );
    }
    navigate(location.hash.slice(1) || "overview");
    if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
      navigator.serviceWorker.register("./sw.js").catch((error) => console.error("Service worker registration failed:", error));
    }
  } catch (error) {
    console.error("FieldSafe could not start:", error);
    showToast(`FieldSafe could not open its local database: ${error.message}`, "error");
  }
}

initialize();
