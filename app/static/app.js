const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let refreshing = false;
let eventSource = null;
let selectedPoi = "";
let lastStatus = null;
let lastSlamStatus = null;
let lastPoints = [];

const jsonHeaders = { "Content-Type": "application/json" };
const rvizCommands = {
  mapping: "cd ~/aurora_ws/flyAdapter || exit 1\n./scripts/open_rviz.sh mapping",
  localization: "cd ~/aurora_ws/flyAdapter || exit 1\n./scripts/open_rviz.sh relocation",
};

async function api(path, options = {}) {
  const opts = {
    method: options.method || "GET",
    headers: options.body === undefined ? undefined : jsonHeaders,
  };
  if (options.body !== undefined) {
    opts.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, opts);
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }

  if (!response.ok) {
    data.http_status = response.status;
  }
  if (options.updateLast !== false) {
    setJson("lastResponse", data);
  }
  if (options.log !== false) {
    logOperation(`${opts.method} ${path}`, data);
  }
  return data;
}

function setJson(id, data) {
  $(id).textContent = JSON.stringify(data, null, 2);
}

function logOperation(title, data) {
  const log = $("operationLog");
  const now = new Date().toLocaleTimeString();
  const ok = data && (data.success !== false && data.status !== "failed" && data.status !== "blocked");
  log.textContent += `[${now}] ${ok ? "OK" : "CHECK"} ${title}\n`;
  log.scrollTop = log.scrollHeight;
}

function boolText(value) {
  return value ? "是" : "否";
}

function statusWord(value) {
  return value ? "正常" : "异常";
}

function setAdapter(ok, text) {
  $("adapterDot").className = "dot " + (ok ? "ok" : "bad");
  $("adapterText").textContent = text;
}

function setBadge(id, state, text) {
  const el = $(id);
  el.className = `badge ${state || ""}`.trim();
  el.textContent = text;
}

function setStepState(id, text) {
  $(id).textContent = text;
}

function activeStep(step) {
  $$(".step").forEach((item) => item.classList.toggle("active", item.dataset.step === step));
  $$(".step-panel").forEach((item) => item.classList.toggle("active", item.dataset.panel === step));
}

function currentMapPath() {
  return $("mapPath").value.trim() || "/opt/fftai/nav/maps/showroom_1f_20260429";
}

function poseBody() {
  return {
    x: Number($("initX").value || 0),
    y: Number($("initY").value || 0),
    z: 0,
    yaw: Number($("initYaw").value || 0),
  };
}

function auroraVelocitySource(aurora) {
  return aurora?.raw?.value?.velocity_source_name || aurora?.velocity_source_name || "-";
}

function motionAuthority(status) {
  return status.motion_authority || status.workflow?.motion_authority || {};
}

function renderStatus(status, slamStatus) {
  const runtime = status.runtime || {};
  const readiness = status.readiness || {};
  const mappingReadiness = status.mapping_readiness || slamStatus.mapping_readiness || {};
  const poiReadiness = status.poi_readiness || status.workflow?.manual_poi || {};
  const aurora = status.aurora || {};
  const motion = motionAuthority(status);
  const ros = status.ros || {};
  const mapPath = runtime.current_map || slamStatus.map_file || "-";
  const slamMode = runtime.slam_mode || slamStatus.slam_mode || "-";
  const navReady = Boolean(readiness.ready);
  const mapReady = Boolean(mappingReadiness.ready || slamStatus.ready_for_mapping);
  const auroraRequired = Boolean(motion.aurora_required || readiness.checks?.aurora_required);

  $("rosStatus").textContent = ros.ready ? "ready" : "not ready";
  $("auroraStatus").textContent = aurora.connected
    ? (aurora.standing ? `standing · ${auroraVelocitySource(aurora)}` : "connected")
    : (auroraRequired ? "unavailable" : `optional · ${motion.policy || "none"}`);
  $("slamStatus").textContent = slamMode;
  $("mappingReady").textContent = boolText(mapReady);
  $("navigationReady").textContent = boolText(navReady);
  $("currentMap").textContent = mapPath;

  $("checkAdapter").textContent = "online";
  $("checkRos").textContent = statusWord(ros.ready);
  $("checkAurora").textContent = auroraRequired ? (aurora.connected ? "connected" : "required") : `optional (${motion.policy || "none"})`;
  $("checkBody").textContent = motion.authority || (aurora.standing ? "standing" : "external");

  $("mappingModeCheck").textContent = mappingReadiness.checks?.mapping_mode ? "mapping" : slamMode;
  $("mappingPoseCheck").textContent = statusWord(mappingReadiness.checks?.pose_fresh);
  $("mappingHealthCheck").textContent = statusWord(mappingReadiness.checks?.health_ok);
  $("mappingControlSource").textContent = mappingReadiness.checks?.motion_source || "remote_or_joystick";

  setJson("readinessBox", {
    motion_authority: motion,
    mapping_readiness: mappingReadiness,
    poi_readiness: poiReadiness,
    navigation_readiness: readiness,
  });
  setJson("mappingBox", {
    ready_for_mapping: mapReady,
    slam_mode: slamMode,
    localization_status: slamStatus.localization_status,
    mapping_readiness: mappingReadiness,
  });
  setJson("localizationBox", {
    slam_mode: slamMode,
    odom_status_code: runtime.odom_status_code ?? slamStatus.odom_status_code,
    localization_status: slamStatus.localization_status,
    readiness,
  });
  setJson("cruiseBox", {
    is_cruising: runtime.is_cruising,
    is_paused: runtime.is_paused,
    current_nav_index: runtime.current_nav_index,
    total_nav_points: runtime.total_nav_points,
    current_target: runtime.current_target,
  });

  setBadge("mappingHint", mapReady ? "ok" : "warn", mapReady ? "建图就绪" : "待确认");
  setBadge("localizationHint", navReady ? "ok" : "warn", navReady ? "导航就绪" : "定位未就绪");
  setBadge("cruiseHint", runtime.is_cruising ? "ok" : "warn", runtime.is_cruising ? "巡航中" : "未巡航");
  setBadge("saveHint", mapPath !== "-" ? "ok" : "warn", mapPath !== "-" ? "地图路径已记录" : "待保存");

  setStepState("stepCheckState", ros.ready ? "通过" : "待处理");
  setStepState("stepMappingState", mapReady ? "可建图" : "待确认");
  setStepState("stepSaveState", mapPath !== "-" ? "路径已记录" : "待保存");
  setStepState("stepLocalizationState", navReady ? "可导航" : "待定位");
  setStepState("stepCruiseState", runtime.is_cruising ? "运行中" : "待启动");
}

async function refresh(updateLast = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    const [status, slamStatus] = await Promise.all([
      api("/robot/status", { updateLast, log: updateLast }),
      api("/slam/status", { updateLast: false, log: updateLast }),
    ]);
    lastStatus = status;
    lastSlamStatus = slamStatus;
    setAdapter(true, "online");
    renderStatus(status, slamStatus);
    await loadPoints(false);
  } catch (error) {
    setAdapter(false, "offline");
    $("lastResponse").textContent = String(error);
  } finally {
    refreshing = false;
  }
}

async function loadPoints(updateLast = true) {
  const data = await api("/slam/nav_points", { updateLast, log: updateLast });
  lastPoints = data.nav_points || data.points || [];
  renderPoints(lastPoints);
  setStepState("stepPointsState", `${lastPoints.length} 点`);
  setBadge("pointsHint", lastPoints.length > 0 ? "ok" : "warn", `${lastPoints.length} 点`);
  setStepState("stepVerifyState", selectedPoi || "待选择");
  return data;
}

function renderPoints(points) {
  const list = $("pointsList");
  const select = $("poiSelect");
  list.innerHTML = "";
  select.innerHTML = "";

  if (!points.length) {
    const empty = document.createElement("div");
    empty.className = "point";
    empty.textContent = "暂无点位";
    list.appendChild(empty);
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无点位";
    select.appendChild(option);
    return;
  }

  for (const point of points) {
    const name = point.name || "-";
    const item = document.createElement("div");
    item.className = "point";

    const title = document.createElement("strong");
    title.textContent = name;
    const coords = document.createElement("span");
    coords.textContent = `x=${num(point.x)}, y=${num(point.y)}, yaw=${num(point.yaw)}`;
    const actions = document.createElement("div");
    actions.className = "mini-actions";

    const selectBtn = document.createElement("button");
    selectBtn.className = "small-btn";
    selectBtn.textContent = "选择";
    selectBtn.onclick = () => {
      selectedPoi = name;
      $("poiSelect").value = name;
      setBadge("verifyHint", "ok", name);
      activeStep("verify");
    };

    const gotoBtn = document.createElement("button");
    gotoBtn.className = "small-btn";
    gotoBtn.textContent = "导航";
    gotoBtn.onclick = () => gotoPoi(name);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "small-btn danger";
    deleteBtn.textContent = "删除";
    deleteBtn.onclick = () => deletePoi(name);

    actions.append(selectBtn, gotoBtn, deleteBtn);
    item.append(title, coords, actions);
    list.appendChild(item);

    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }

  if (selectedPoi && points.some((point) => point.name === selectedPoi)) {
    select.value = selectedPoi;
  } else {
    selectedPoi = points[0]?.name || "";
    select.value = selectedPoi;
  }
  setBadge("verifyHint", selectedPoi ? "ok" : "warn", selectedPoi || "待选择");
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : "-";
}

async function startMapping() {
  await api("/slam/start_mapping", { method: "POST" });
  await refresh(false);
  activeStep("mapping");
}

async function stopMapping() {
  await api("/slam/stop_mapping", {
    method: "POST",
    body: { map_path: currentMapPath() },
  });
  await refresh(false);
  activeStep("save");
}

async function saveMap() {
  await api("/robot/map/save", {
    method: "POST",
    body: { map_path: currentMapPath() },
  });
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
      map_path: currentMapPath(),
      ...poseBody(),
      wait_for_localization: true,
    },
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
  const name = $("pointName").value.trim();
  if (!name) {
    alert("请先填写点位名称");
    return;
  }
  await api("/slam/add_nav_point", { method: "POST", body: { name } });
  selectedPoi = name;
  await loadPoints(false);
  await refresh(false);
}

async function savePointsFile() {
  await api("/slam/save_nav_points", { method: "POST" });
  await loadPoints(false);
}

async function clearPoints() {
  if (!confirm("确认清空当前点位？")) return;
  await api("/slam/clear_nav_points", { method: "POST" });
  selectedPoi = "";
  await loadPoints(false);
}

async function deletePoi(name) {
  if (!confirm(`确认删除点位 ${name}？`)) return;
  await api(`/robot/poi/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (selectedPoi === name) selectedPoi = "";
  await loadPoints(false);
}

async function gotoPoi(name = $("poiSelect").value) {
  if (!name) {
    alert("请先选择点位");
    return;
  }
  selectedPoi = name;
  const data = await api("/robot/navigation/goto_poi", {
    method: "POST",
    body: { name, force: false },
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
  await api("/slam/start_cruise", { method: "POST", body: { force: false } });
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
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    $("connectEventsBtn").textContent = "连接事件";
    log.textContent += "event stream closed\n";
    return;
  }
  eventSource = new EventSource("/slam/events");
  $("connectEventsBtn").textContent = "断开事件";
  log.textContent += "event stream connected\n";
  eventSource.onmessage = (event) => {
    log.textContent += `${event.data}\n`;
    log.scrollTop = log.scrollHeight;
  };
  eventSource.onerror = () => {
    log.textContent += "event stream error\n";
    log.scrollTop = log.scrollHeight;
  };
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
    api("/healthz", { updateLast: false, log: false }),
    api("/robot/status", { updateLast: false, log: false }),
    api("/robot/workflow/status", { updateLast: false, log: false }),
    api("/slam/nav_points", { updateLast: false, log: false }),
  ]);
  const motion = workflow.motion_authority || motionAuthority(status);
  const auroraRequired = Boolean(motion.aurora_required);
  const aurora = workflow.aurora || status.aurora || {};
  const mapping = workflow.manual_mapping || status.mapping_readiness || {};
  const poi = workflow.manual_poi || status.poi_readiness || {};
  const navigation = workflow.auto_navigation || status.readiness || {};
  const checks = [
    ["Adapter", Boolean(health.ok), health.namespace || ""],
    ["ROS", Boolean(status.ros?.ready), status.ros?.error || "ready"],
    ["运动策略", true, `${motion.policy || "none"} · ${motion.authority || "external"}`],
    ["Aurora", !auroraRequired || Boolean(aurora.connected), auroraRequired ? (aurora.standing ? "standing" : "required") : "optional"],
    ["地图", Boolean(status.runtime?.current_map), status.runtime?.current_map || "-"],
    ["手动建图", Boolean(mapping.ready), (mapping.blockers || []).join(", ") || "ready"],
    ["手动打点", Boolean(poi.ready), (poi.blockers || []).join(", ") || "ready"],
    ["点位", (points.count || 0) > 0, `${points.count || 0} 点`],
    ["导航就绪", Boolean(navigation.ready), (navigation.blockers || []).join(", ") || "ready"],
  ];
  renderAcceptance(checks);
  setJson("acceptanceBox", { health, workflow, points, status });
  setStepState("stepAcceptanceState", checks.every((item) => item[1]) ? "通过" : "待处理");
}

function renderAcceptance(checks) {
  const target = $("acceptanceList");
  target.innerHTML = "";
  for (const [name, ok, detail] of checks) {
    const item = document.createElement("div");
    item.className = `check-item ${ok ? "ok" : "bad"}`;
    const title = document.createElement("strong");
    title.textContent = `${ok ? "通过" : "未通过"} · ${name}`;
    const desc = document.createElement("span");
    desc.textContent = detail || "-";
    item.append(title, desc);
    target.appendChild(item);
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    $("lastResponse").textContent = `已复制命令：\n${text}`;
  } catch {
    $("lastResponse").textContent = text;
  }
}

function bindEvents() {
  $$(".step").forEach((item) => {
    item.onclick = () => activeStep(item.dataset.step);
  });
  $("refreshBtn").onclick = () => refresh(true);
  $("runAcceptanceTopBtn").onclick = () => {
    activeStep("acceptance");
    runAcceptance();
  };
  $("ensureStandBtn").onclick = ensureStand;
  $("stopMotionBtn").onclick = stopMotion;
  $("auroraResetBtn").onclick = auroraReset;
  $("startMappingBtn").onclick = startMapping;
  $("mappingStatusBtn").onclick = () => refresh(true);
  $("copyMappingRvizBtn").onclick = () => copyText(rvizCommands.mapping);
  $("stopMappingBtn").onclick = stopMapping;
  $("saveMapBtn").onclick = saveMap;
  $("listMapsBtn").onclick = listMaps;
  $("loadMapBtn").onclick = loadMap;
  $("initialPoseBtn").onclick = publishInitialPose;
  $("localizationStatusBtn").onclick = () => refresh(true);
  $("copyLocalizationRvizBtn").onclick = () => copyText(rvizCommands.localization);
  $("savePointBtn").onclick = savePoint;
  $("savePointsFileBtn").onclick = savePointsFile;
  $("reloadPointsBtn").onclick = () => loadPoints(true);
  $("clearPointsBtn").onclick = clearPoints;
  $("poiSelect").onchange = () => {
    selectedPoi = $("poiSelect").value;
    setBadge("verifyHint", selectedPoi ? "ok" : "warn", selectedPoi || "待选择");
  };
  $("gotoPoiBtn").onclick = () => gotoPoi();
  $("cancelNavBtn").onclick = cancelNavigation;
  $("currentActionBtn").onclick = currentAction;
  $("startCruiseBtn").onclick = startCruise;
  $("pauseBtn").onclick = pauseCruise;
  $("resumeBtn").onclick = resumeCruise;
  $("stopCruiseBtn").onclick = stopCruise;
  $("connectEventsBtn").onclick = connectEvents;
  $("runAcceptanceBtn").onclick = runAcceptance;
  $("clearResponseBtn").onclick = () => { $("lastResponse").textContent = ""; };
  $("clearLogBtn").onclick = () => { $("operationLog").textContent = ""; };
}

bindEvents();
refresh(false);
setInterval(() => refresh(false), 5000);
