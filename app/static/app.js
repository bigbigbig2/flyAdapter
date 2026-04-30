const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const jsonHeaders = { "Content-Type": "application/json" };
const requestTimeoutMs = 12000;
const rvizCommands = {
  mapping: "cd ~/aurora_ws/flyAdapter || exit 1\n./scripts/open_rviz.sh mapping",
  localization: "cd ~/aurora_ws/flyAdapter || exit 1\n./scripts/open_rviz.sh relocation",
};

let refreshing = false;
let eventSource = null;
let selectedPoi = "";
let lastStatus = {};
let lastSlamStatus = {};
let lastPoints = [];
let lastPointIssues = { duplicateNames: [], duplicateCount: 0 };
let currentMapConfig = {
  map_root: "/opt/fftai/nav",
  default_map_name: "map",
  default_map_path: "/opt/fftai/nav/map",
  save_timeout_sec: 120,
};

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), options.timeoutMs || requestTimeoutMs);
  const method = options.method || "GET";
  const fetchOptions = {
    method,
    signal: controller.signal,
    headers: options.body === undefined ? undefined : jsonHeaders,
  };

  if (options.body !== undefined) {
    fetchOptions.body = JSON.stringify(options.body);
  }

  try {
    const response = await fetch(path, fetchOptions);
    const text = await response.text();
    const data = parseResponse(text);
    if (!response.ok) {
      data.http_status = response.status;
    }
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      logOperation(`${method} ${path}`, data);
    }
    return data;
  } catch (error) {
    const message = error.name === "AbortError" ? "请求超时" : String(error);
    const data = { success: false, message, path, method };
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      logOperation(`${method} ${path}`, data);
    }
    throw new Error(message);
  } finally {
    window.clearTimeout(timer);
  }
}

function parseResponse(text) {
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function setText(id, value) {
  const target = $(id);
  if (target) {
    target.textContent = value == null || value === "" ? "-" : String(value);
  }
}

function setJson(id, data) {
  const target = $(id);
  if (target) {
    target.textContent = JSON.stringify(data, null, 2);
  }
}

function resultOk(data) {
  if (!data || data.http_status >= 400) {
    return false;
  }
  if (data.success === false || data.status === "failed" || data.status === "blocked") {
    return false;
  }
  if (data.result && data.result.success === false) {
    return false;
  }
  return true;
}

function logOperation(title, data) {
  const log = $("operationLog");
  if (!log) {
    return;
  }
  const now = new Date().toLocaleTimeString();
  const mark = resultOk(data) ? "OK" : "CHECK";
  const detail = data?.message || data?.error || data?.status || "";
  log.textContent += `[${now}] ${mark} ${title}${detail ? ` - ${detail}` : ""}\n`;
  const lines = log.textContent.split("\n");
  if (lines.length > 240) {
    log.textContent = lines.slice(-220).join("\n");
  }
  log.scrollTop = log.scrollHeight;
}

function boolText(value) {
  return value ? "是" : "否";
}

function statusWord(value) {
  return value ? "正常" : "异常";
}

function readyWord(readiness) {
  if (!readiness || !readiness.checks) {
    return "-";
  }
  return readiness.ready ? "就绪" : blockerText(readiness);
}

function blockerText(readiness) {
  const blockers = readiness?.blockers || [];
  const warnings = readiness?.warnings || [];
  if (blockers.length) {
    return blockers.join(", ");
  }
  if (warnings.length) {
    return warnings.join(", ");
  }
  return readiness?.ready ? "ready" : "-";
}

function setAdapter(ok, text) {
  const dot = $("adapterDot");
  if (dot) {
    dot.className = `dot ${ok ? "ok" : "bad"}`;
  }
  setText("adapterText", text);
  setText("adapterStatus", ok ? "online" : "offline");
}

function setBadge(id, state, text) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.className = `badge ${state || ""}`.trim();
  el.textContent = text;
}

function setStepState(id, text) {
  setText(id, text);
}

function activeStep(step) {
  $$(".step").forEach((item) => item.classList.toggle("active", item.dataset.step === step));
  $$(".step-panel").forEach((item) => item.classList.toggle("active", item.dataset.panel === step));
}

function mapNameValue() {
  return $("mapName")?.value.trim() || currentMapConfig.default_map_name || "map";
}

function explicitMapPath() {
  return $("mapPath")?.value.trim() || "";
}

function currentMapPath() {
  return explicitMapPath() || joinMapPath(currentMapConfig.map_root, mapNameValue());
}

function currentMapPayload() {
  const payload = {};
  const path = explicitMapPath();
  const name = mapNameValue();
  if (path) {
    payload.map_path = path;
  } else if (name) {
    payload.map_name = name;
  }
  return payload;
}

function mapSaveTimeoutMs() {
  const seconds = Number(currentMapConfig.save_timeout_sec);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.max(requestTimeoutMs, (seconds + 15) * 1000);
  }
  return 150000;
}

function joinMapPath(root, name) {
  const cleanRoot = String(root || "/opt/fftai/nav").replace(/[\\/]+$/, "");
  const cleanName = String(name || "map").replace(/^[\\/]+|[\\/]+$/g, "");
  return `${cleanRoot}/${cleanName}`;
}

function syncMapControls(mapConfig = {}) {
  currentMapConfig = { ...currentMapConfig, ...mapConfig };
  const nameInput = $("mapName");
  const pathInput = $("mapPath");
  if (nameInput && !nameInput.value.trim() && document.activeElement !== nameInput) {
    nameInput.value = currentMapConfig.default_map_name || currentMapConfig.current_map_name || "";
  }
  if (pathInput && document.activeElement !== pathInput) {
    pathInput.placeholder = `自动：${joinMapPath(currentMapConfig.map_root, mapNameValue())}`;
  }
}

function poseBody() {
  return {
    x: numberOrZero($("initX")?.value),
    y: numberOrZero($("initY")?.value),
    z: 0,
    yaw: numberOrZero($("initYaw")?.value),
  };
}

function numberOrZero(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function motionAuthority(status) {
  return status?.motion_authority || status?.workflow?.motion_authority || {};
}

function auroraVelocitySource(aurora) {
  return aurora?.raw?.value?.velocity_source_name || aurora?.velocity_source_name || "-";
}

function formatAge(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  return `${parsed.toFixed(1)}s`;
}

function renderStatus(status = {}, slamStatus = {}) {
  const runtime = status.runtime || {};
  const workflow = status.workflow || {};
  const mappingReadiness = status.mapping_readiness || workflow.manual_mapping || slamStatus.mapping_readiness || {};
  const poiReadiness = status.poi_readiness || workflow.manual_poi || slamStatus.poi_readiness || {};
  const navigationReadiness = status.navigation_readiness || status.readiness || workflow.auto_navigation || {};
  const aurora = status.aurora || {};
  const motion = motionAuthority(status);
  const ros = status.ros || {};
  const mapConfig = status.map_config || slamStatus.map_config || {};
  syncMapControls(mapConfig);
  const mapPath = runtime.current_map || mapConfig.current_map || slamStatus.map_file || "-";
  const slamMode = runtime.slam_mode || slamStatus.slam_mode || "-";
  const navTask = runtime.navigation_task || {};
  const isCruising = Boolean(runtime.is_cruising || slamStatus.is_cruising);
  const isPaused = Boolean(runtime.is_paused || slamStatus.is_paused);
  const poseAge = runtime.pose_age_sec ?? slamStatus.pose_age_sec;
  const auroraRequired = Boolean(motion.aurora_required || navigationReadiness.checks?.aurora_required);
  const navReady = Boolean(navigationReadiness.ready);
  const mapReady = Boolean(mappingReadiness.ready || slamStatus.ready_for_mapping);
  const poiReady = Boolean(poiReadiness.ready || slamStatus.ready_for_poi);

  setAdapter(true, "online");
  setText("rosStatus", ros.ready ? "ready" : "not ready");
  setText("motionStatus", `${motion.policy || "none"} / ${motion.authority || "external"}`);
  setText("slamStatus", slamMode);
  setText("navigationReady", boolText(navReady));
  setText("currentMap", mapPath);
  setText("poseAge", formatAge(poseAge));
  setText("navTask", isCruising ? (isPaused ? "paused" : "cruising") : (navTask.status || "idle"));

  setText("checkAdapter", "online");
  setText("checkRos", ros.ready ? "ready" : (ros.error || "not ready"));
  setText("checkMapping", readyWord(mappingReadiness));
  setText("checkPoi", readyWord(poiReadiness));
  setText("checkNavigation", readyWord(navigationReadiness));
  setText(
    "checkAurora",
    aurora.connected
      ? (aurora.standing ? `standing / ${auroraVelocitySource(aurora)}` : "connected")
      : (auroraRequired ? "required" : `optional / ${motion.policy || "none"}`)
  );
  setText("checkBody", motion.authority || (aurora.standing ? "standing" : "external"));
  setText("healthLine", `${ros.ready ? "ROS ready" : "ROS not ready"} / ${motion.policy || "none"} / ${currentMapPath()}`);

  setText("mappingModeCheck", mappingReadiness.checks?.mapping_mode ? "mapping" : slamMode);
  setText("mappingPoseCheck", statusWord(mappingReadiness.checks?.pose_fresh));
  setText("mappingHealthCheck", statusWord(mappingReadiness.checks?.health_ok));
  setText("mappingControlSource", mappingReadiness.checks?.motion_source || "remote_or_joystick");

  setJson("readinessBox", {
    motion_authority: motion,
    map_config: currentMapConfig,
    manual_mapping: mappingReadiness,
    manual_poi: poiReadiness,
    auto_navigation: navigationReadiness,
    aurora,
  });
  setJson("mappingBox", {
    target_map: currentMapPath(),
    map_name: mapNameValue(),
    ready_for_mapping: mapReady,
    slam_mode: slamMode,
    pose_age_sec: poseAge,
    localization_status: slamStatus.localization_status,
    mapping_readiness: mappingReadiness,
  });
  setJson("localizationBox", {
    target_map: currentMapPath(),
    current_map: mapPath,
    slam_mode: slamMode,
    odom_status_code: runtime.odom_status_code ?? slamStatus.odom_status_code,
    odom_status_score: runtime.odom_status_score ?? slamStatus.odom_status_score,
    localization_status: slamStatus.localization_status,
    poi_readiness: poiReadiness,
    navigation_readiness: navigationReadiness,
  });
  setJson("cruiseBox", {
    is_cruising: isCruising,
    is_paused: isPaused,
    current_nav_index: runtime.current_nav_index ?? slamStatus.current_nav_index,
    total_nav_points: runtime.total_nav_points ?? slamStatus.total_nav_points,
    current_target: runtime.current_target,
    task: navTask,
  });

  setBadge("mappingHint", mapReady ? "ok" : "warn", mapReady ? "建图就绪" : blockerText(mappingReadiness));
  setBadge("saveHint", mapPath !== "-" ? "ok" : "warn", mapPath !== "-" ? "路径已记录" : "待保存");
  setBadge("localizationHint", navReady ? "ok" : "warn", navReady ? "导航就绪" : blockerText(navigationReadiness));
  setBadge("cruiseHint", isCruising ? "ok" : "warn", isCruising ? (isPaused ? "已暂停" : "巡航中") : "未巡航");

  setStepState("stepCheckState", ros.ready ? "通过" : "待处理");
  setStepState("stepMappingState", mapReady ? "可建图" : "待确认");
  setStepState("stepSaveState", mapPath !== "-" ? "路径已记录" : "待保存");
  setStepState("stepLocalizationState", navReady ? "可导航" : (poiReady ? "可打点" : "待定位"));
  setStepState("stepCruiseState", isCruising ? (isPaused ? "已暂停" : "运行中") : "待启动");
  setText("saveNote", `目标：${currentMapPath()}`);
  setText("cruiseSummary", isCruising ? `第 ${(runtime.current_nav_index ?? 0) + 1} / ${runtime.total_nav_points || 0} 点` : "未启动");

  updateControls();
}

async function refresh(updateLast = false) {
  if (refreshing) {
    return;
  }
  refreshing = true;
  try {
    const [status, slamStatus] = await Promise.all([
      api("/robot/status", { updateLast, log: updateLast }),
      api("/slam/status", { updateLast: false, log: updateLast }),
    ]);
    lastStatus = status || {};
    lastSlamStatus = slamStatus || {};
    renderStatus(lastStatus, lastSlamStatus);
  } catch (error) {
    setAdapter(false, "offline");
    setText("healthLine", String(error.message || error));
  } finally {
    refreshing = false;
  }

  try {
    await loadPoints(false);
  } catch {
    renderPoints(lastPoints);
  }
}

async function loadPoints(updateLast = true) {
  const data = await api("/slam/nav_points", { updateLast, log: updateLast });
  lastPoints = normalizePoints(data.nav_points || data.points || []);
  lastPointIssues = analyzePoints(lastPoints);
  renderPoints(lastPoints);
  updatePointSummary();
  return data;
}

function normalizePoints(points) {
  return points.map((point, index) => {
    const yaw = Number.isFinite(Number(point.yaw))
      ? Number(point.yaw)
      : yawFromQuaternion(point.q_x, point.q_y, point.q_z, point.q_w);
    return {
      ...point,
      name: String(point.name || `point_${index + 1}`),
      x: numberOrZero(point.x),
      y: numberOrZero(point.y),
      z: numberOrZero(point.z),
      q_x: numberOrZero(point.q_x),
      q_y: numberOrZero(point.q_y),
      q_z: numberOrZero(point.q_z),
      q_w: Number.isFinite(Number(point.q_w)) ? Number(point.q_w) : 1,
      yaw,
      frame_id: point.frame_id || "map",
    };
  });
}

function yawFromQuaternion(qx, qy, qz, qw) {
  const x = numberOrZero(qx);
  const y = numberOrZero(qy);
  const z = numberOrZero(qz);
  const w = Number.isFinite(Number(qw)) ? Number(qw) : 1;
  const siny = 2 * (w * z + x * y);
  const cosy = 1 - 2 * (y * y + z * z);
  return Math.atan2(siny, cosy);
}

function analyzePoints(points) {
  const counts = new Map();
  for (const point of points) {
    counts.set(point.name, (counts.get(point.name) || 0) + 1);
  }
  const duplicateNames = Array.from(counts.entries())
    .filter(([, count]) => count > 1)
    .map(([name]) => name);
  const duplicateCount = duplicateNames.reduce((total, name) => total + counts.get(name), 0);
  return { counts, duplicateNames, duplicateCount };
}

function updatePointSummary() {
  const count = lastPoints.length;
  const duplicateNames = lastPointIssues.duplicateNames;
  const duplicateText = duplicateNames.length ? `，重复 ${duplicateNames.length} 组` : "";
  setText("pointsSummary", `共 ${count} 点${duplicateText}`);
  setStepState("stepPointsState", `${count} 点`);
  setBadge("pointsHint", count > 0 ? (duplicateNames.length ? "warn" : "ok") : "warn", `${count} 点`);
  const notice = $("duplicateNotice");
  if (notice) {
    if (duplicateNames.length) {
      notice.classList.remove("hidden");
      notice.textContent = `检测到同名点：${duplicateNames.join(", ")}。按名称导航会使用第一个匹配点，建议覆盖保存或删除后重打。`;
    } else {
      notice.classList.add("hidden");
      notice.textContent = "";
    }
  }
  setStepState("stepVerifyState", selectedPoi || "待选择");
  updateControls();
}

function renderPoints(points) {
  const list = $("pointsList");
  const select = $("poiSelect");
  if (!list || !select) {
    return;
  }

  const query = ($("pointSearch")?.value || "").trim().toLowerCase();
  const filtered = query ? points.filter((point) => point.name.toLowerCase().includes(query)) : points;
  const counts = lastPointIssues.counts || new Map();
  list.innerHTML = "";
  select.innerHTML = "";

  if (!points.length) {
    list.appendChild(emptyPoint("暂无点位"));
    select.appendChild(new Option("暂无点位", ""));
    selectedPoi = "";
    setBadge("verifyHint", "warn", "待选择");
    setText("verifySummary", "未选择目标");
    return;
  }

  if (!filtered.length) {
    list.appendChild(emptyPoint("没有匹配点位"));
  }

  for (const point of filtered) {
    const duplicate = (counts.get(point.name) || 0) > 1;
    const item = document.createElement("div");
    item.className = `point ${duplicate ? "duplicate" : ""}`.trim();

    const title = document.createElement("strong");
    title.textContent = duplicate ? `${point.name}（重复）` : point.name;

    const coords = document.createElement("span");
    coords.textContent = `x=${num(point.x)}, y=${num(point.y)}, yaw=${num(point.yaw)} / ${point.frame_id}`;

    const actions = document.createElement("div");
    actions.className = "mini-actions";
    actions.append(
      smallButton("选择", () => selectPoi(point.name)),
      smallButton("导航", () => gotoPoi(point.name)),
      smallButton("删除", () => deletePoi(point.name), "danger")
    );

    item.append(title, coords, actions);
    list.appendChild(item);
  }

  const uniqueNames = Array.from(new Set(points.map((point) => point.name)));
  for (const name of uniqueNames) {
    const label = (counts.get(name) || 0) > 1 ? `${name}（重复 ${counts.get(name)}）` : name;
    select.appendChild(new Option(label, name));
  }

  if (!selectedPoi || !uniqueNames.includes(selectedPoi)) {
    selectedPoi = uniqueNames[0] || "";
  }
  select.value = selectedPoi;
  setBadge("verifyHint", selectedPoi ? ((counts.get(selectedPoi) || 0) > 1 ? "warn" : "ok") : "warn", selectedPoi || "待选择");
  setText("verifySummary", selectedPoi ? `目标：${selectedPoi}` : "未选择目标");
}

function emptyPoint(text) {
  const item = document.createElement("div");
  item.className = "point";
  const strong = document.createElement("strong");
  strong.textContent = text;
  item.appendChild(strong);
  return item;
}

function smallButton(text, handler, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `small-btn ${extraClass}`.trim();
  button.textContent = text;
  button.onclick = () => runInline(handler);
  return button;
}

async function runInline(handler) {
  try {
    await handler();
  } catch (error) {
    setJson("lastResponse", { success: false, message: String(error.message || error) });
  }
}

function selectPoi(name) {
  selectedPoi = name;
  const select = $("poiSelect");
  if (select) {
    select.value = name;
  }
  const duplicate = (lastPointIssues.counts?.get(name) || 0) > 1;
  setBadge("verifyHint", duplicate ? "warn" : "ok", name);
  setText("verifySummary", `目标：${name}`);
  activeStep("verify");
  updateControls();
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : "-";
}

async function startMapping() {
  await api("/slam/start_mapping", {
    method: "POST",
    body: currentMapPayload(),
  });
  await refresh(false);
  activeStep("mapping");
}

async function stopMapping() {
  const result = await api("/slam/stop_mapping", {
    method: "POST",
    body: currentMapPayload(),
    timeoutMs: mapSaveTimeoutMs(),
  });
  if (resultOk(result)) {
    await api("/slam/set_map_path", { method: "POST", body: currentMapPayload(), updateLast: false });
  }
  await refresh(false);
  activeStep("save");
}

async function saveMap() {
  const result = await api("/robot/map/save", {
    method: "POST",
    body: currentMapPayload(),
    timeoutMs: mapSaveTimeoutMs(),
  });
  if (resultOk(result)) {
    await api("/slam/set_map_path", { method: "POST", body: currentMapPayload(), updateLast: false });
  }
  await refresh(false);
}

async function setMapPathOnly() {
  await api("/slam/set_map_path", { method: "POST", body: currentMapPayload() });
  await refresh(false);
}

async function listMaps() {
  const data = await api("/robot/map/list");
  setJson("mapListBox", data);
}

async function loadMap() {
  await api("/slam/relocation", {
    method: "POST",
    body: {
      ...currentMapPayload(),
      ...poseBody(),
      wait_for_localization: true,
    },
    timeoutMs: 35000,
  });
  await refresh(false);
  activeStep("localization");
}

async function publishInitialPose() {
  await api("/robot/localization/initial_pose", {
    method: "POST",
    body: { ...poseBody(), frame_id: "map" },
  });
  await refresh(false);
}

async function savePoint() {
  const name = $("pointName")?.value.trim();
  if (!name) {
    setJson("lastResponse", { success: false, message: "请先填写点位名称" });
    return;
  }
  const existed = lastPoints.some((point) => point.name === name);
  if (existed && !window.confirm(`点位 ${name} 已存在，继续会覆盖同名点。`)) {
    return;
  }
  await api("/robot/poi/save_current", {
    method: "POST",
    body: { name },
  });
  selectedPoi = name;
  await loadPoints(false);
  await refresh(false);
}

async function savePointsFile() {
  await api("/slam/save_nav_points", { method: "POST" });
  await loadPoints(false);
}

async function clearPoints() {
  if (!window.confirm("确认清空当前点位？")) {
    return;
  }
  await api("/slam/clear_nav_points", { method: "POST" });
  selectedPoi = "";
  await loadPoints(false);
  await refresh(false);
}

async function deletePoi(name) {
  const count = lastPointIssues.counts?.get(name) || 0;
  const suffix = count > 1 ? `（将删除 ${count} 个同名点）` : "";
  if (!window.confirm(`确认删除点位 ${name}${suffix}？`)) {
    return;
  }
  await api(`/robot/poi/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (selectedPoi === name) {
    selectedPoi = "";
  }
  await loadPoints(false);
  await refresh(false);
}

async function gotoPoi(name = $("poiSelect")?.value) {
  if (!name) {
    setJson("verifyBox", { success: false, message: "请先选择点位" });
    return;
  }
  selectedPoi = name;
  const data = await api("/robot/navigation/goto_poi", {
    method: "POST",
    body: { name, force: Boolean($("forceNav")?.checked) },
  });
  setJson("verifyBox", data);
  await refresh(false);
}

async function cancelNavigation() {
  const data = await api("/robot/navigation/cancel", { method: "POST" });
  setJson("verifyBox", data);
  await refresh(false);
}

async function currentAction() {
  const data = await api("/robot/navigation/current_action");
  setJson("verifyBox", data);
}

async function startCruise() {
  await api("/slam/start_cruise", {
    method: "POST",
    body: { force: Boolean($("forceCruise")?.checked) },
  });
  await refresh(false);
  activeStep("cruise");
}

async function stopCruise() {
  await api("/slam/stop_cruise", { method: "POST" });
  await refresh(false);
}

async function pauseCruise() {
  await api("/slam/pause_nav", { method: "POST" });
  await refresh(false);
}

async function resumeCruise() {
  await api("/slam/resume_nav", { method: "POST" });
  await refresh(false);
}

function connectEvents() {
  const log = $("eventsLog");
  const button = $("connectEventsBtn");
  if (!log || !button) {
    return;
  }
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    button.textContent = "连接事件";
    appendEvent("event stream closed");
    return;
  }
  eventSource = new EventSource("/slam/events");
  button.textContent = "断开事件";
  appendEvent("event stream connecting");
  eventSource.onopen = () => appendEvent("event stream connected");
  eventSource.onmessage = (event) => appendEvent(event.data);
  eventSource.onerror = () => appendEvent("event stream error");
}

function appendEvent(text) {
  const log = $("eventsLog");
  if (!log) {
    return;
  }
  log.textContent += `${text}\n`;
  const lines = log.textContent.split("\n");
  if (lines.length > 260) {
    log.textContent = lines.slice(-240).join("\n");
  }
  log.scrollTop = log.scrollHeight;
}

async function ensureStand() {
  await api("/robot/aurora/ensure_stand", { method: "POST" });
  await refresh(false);
}

async function stopMotion() {
  await api("/robot/aurora/stop_motion", { method: "POST" });
  await refresh(false);
}

async function auroraReset() {
  await api("/robot/aurora/reset", { method: "POST" });
  await refresh(false);
}

async function runAcceptance() {
  const [health, status, workflow, points] = await Promise.all([
    safeApi("/healthz"),
    safeApi("/robot/status"),
    safeApi("/robot/workflow/status"),
    safeApi("/slam/nav_points"),
  ]);
  const motion = workflow.motion_authority || motionAuthority(status);
  const auroraRequired = Boolean(motion.aurora_required);
  const aurora = workflow.aurora || status.aurora || {};
  const mapping = workflow.manual_mapping || status.mapping_readiness || {};
  const poi = workflow.manual_poi || status.poi_readiness || {};
  const navigation = workflow.auto_navigation || status.readiness || {};
  const normalizedPoints = normalizePoints(points.nav_points || points.points || []);
  const issues = analyzePoints(normalizedPoints);
  const checks = [
    ["Adapter", Boolean(health.ok), health.namespace || health.error || ""],
    ["ROS", Boolean(status.ros?.ready), status.ros?.error || "ready"],
    ["运动策略", true, `${motion.policy || "none"} / ${motion.authority || "external"}`],
    ["Aurora", !auroraRequired || Boolean(aurora.connected), auroraRequired ? (aurora.standing ? "standing" : "required") : "optional"],
    ["地图", Boolean(status.runtime?.current_map), status.runtime?.current_map || "-"],
    ["手动建图", Boolean(mapping.ready), blockerText(mapping)],
    ["手动打点", Boolean(poi.ready), blockerText(poi)],
    ["点位", normalizedPoints.length > 0, `${normalizedPoints.length} 点`],
    ["点位唯一", issues.duplicateNames.length === 0, issues.duplicateNames.length ? issues.duplicateNames.join(", ") : "ok"],
    ["导航就绪", Boolean(navigation.ready), blockerText(navigation)],
  ];
  renderAcceptance(checks);
  const passed = checks.every(([, ok]) => ok);
  setJson("acceptanceBox", { health, workflow, points, status, point_issues: issues });
  setText("acceptanceSummary", passed ? "全部通过" : "存在待处理项");
  setStepState("stepAcceptanceState", passed ? "通过" : "待处理");
}

async function safeApi(path) {
  try {
    return await api(path, { updateLast: false, log: false });
  } catch (error) {
    return { success: false, error: String(error.message || error) };
  }
}

function renderAcceptance(checks) {
  const target = $("acceptanceList");
  if (!target) {
    return;
  }
  target.innerHTML = "";
  for (const [name, ok, detail] of checks) {
    const item = document.createElement("div");
    item.className = `check-item ${ok ? "ok" : "bad"}`;
    const title = document.createElement("strong");
    title.textContent = `${ok ? "通过" : "未通过"} / ${name}`;
    const desc = document.createElement("span");
    desc.textContent = detail || "-";
    item.append(title, desc);
    target.appendChild(item);
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    setJson("lastResponse", { success: true, message: "已复制命令", command: text });
  } catch {
    setJson("lastResponse", { success: false, message: "浏览器未允许剪贴板，命令如下", command: text });
  }
}

async function runWithButton(buttonId, handler) {
  const button = $(buttonId);
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "处理中";
  }
  try {
    await handler();
  } catch (error) {
    setJson("lastResponse", { success: false, message: String(error.message || error) });
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
    updateControls();
  }
}

function updateControls() {
  const hasPoints = lastPoints.length > 0;
  const runtime = lastStatus.runtime || {};
  const isCruising = Boolean(runtime.is_cruising || lastSlamStatus.is_cruising);
  const isPaused = Boolean(runtime.is_paused || lastSlamStatus.is_paused);
  setDisabled("gotoPoiBtn", !selectedPoi);
  setDisabled("startCruiseBtn", !hasPoints || isCruising);
  setDisabled("pauseBtn", !isCruising || isPaused);
  setDisabled("resumeBtn", !isCruising || !isPaused);
  setDisabled("stopCruiseBtn", !isCruising);
}

function setDisabled(id, disabled) {
  const el = $(id);
  if (el) {
    el.disabled = Boolean(disabled);
  }
}

function bindAction(id, handler) {
  const el = $(id);
  if (el) {
    el.onclick = () => runWithButton(id, handler);
  }
}

function bindEvents() {
  $$(".step").forEach((item) => {
    item.onclick = () => activeStep(item.dataset.step);
  });
  bindAction("refreshBtn", () => refresh(true));
  bindAction("runAcceptanceTopBtn", async () => {
    activeStep("acceptance");
    await runAcceptance();
  });
  bindAction("ensureStandBtn", ensureStand);
  bindAction("stopMotionBtn", stopMotion);
  bindAction("auroraResetBtn", auroraReset);
  bindAction("startMappingBtn", startMapping);
  bindAction("mappingStatusBtn", () => refresh(true));
  bindAction("copyMappingRvizBtn", () => copyText(rvizCommands.mapping));
  bindAction("stopMappingBtn", stopMapping);
  bindAction("saveMapBtn", saveMap);
  bindAction("setMapPathBtn", setMapPathOnly);
  bindAction("listMapsBtn", listMaps);
  bindAction("loadMapBtn", loadMap);
  bindAction("initialPoseBtn", publishInitialPose);
  bindAction("localizationStatusBtn", () => refresh(true));
  bindAction("copyLocalizationRvizBtn", () => copyText(rvizCommands.localization));
  bindAction("savePointBtn", savePoint);
  bindAction("savePointsFileBtn", savePointsFile);
  bindAction("reloadPointsBtn", () => loadPoints(true));
  bindAction("clearPointsBtn", clearPoints);
  bindAction("gotoPoiBtn", () => gotoPoi());
  bindAction("cancelNavBtn", cancelNavigation);
  bindAction("currentActionBtn", currentAction);
  bindAction("startCruiseBtn", startCruise);
  bindAction("pauseBtn", pauseCruise);
  bindAction("resumeBtn", resumeCruise);
  bindAction("stopCruiseBtn", stopCruise);
  const connectEventsBtn = $("connectEventsBtn");
  if (connectEventsBtn) {
    connectEventsBtn.onclick = connectEvents;
  }
  bindAction("runAcceptanceBtn", runAcceptance);

  const poiSelect = $("poiSelect");
  if (poiSelect) {
    poiSelect.onchange = () => selectPoi(poiSelect.value);
  }
  const pointSearch = $("pointSearch");
  if (pointSearch) {
    pointSearch.oninput = () => renderPoints(lastPoints);
  }
  const pointName = $("pointName");
  if (pointName) {
    pointName.oninput = updateControls;
  }
  const mapName = $("mapName");
  if (mapName) {
    mapName.oninput = () => {
      syncMapControls();
      setText("saveNote", `目标：${currentMapPath()}`);
    };
  }
  const mapPath = $("mapPath");
  if (mapPath) {
    mapPath.oninput = () => {
      setText("saveNote", `目标：${currentMapPath()}`);
    };
  }
  const clearResponse = $("clearResponseBtn");
  if (clearResponse) {
    clearResponse.onclick = () => {
      $("lastResponse").textContent = "";
    };
  }
  const clearLog = $("clearLogBtn");
  if (clearLog) {
    clearLog.onclick = () => {
      $("operationLog").textContent = "";
    };
  }
}

bindEvents();
refresh(false);
window.setInterval(() => refresh(false), 5000);
