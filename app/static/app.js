const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const jsonHeaders = { "Content-Type": "application/json" };
const defaultTimeoutMs = 12000;
const localizationTimeoutMs = 45000;

const rvizCommands = {
  mapping: [
    "cd ~/aurora_ws/flyAdapter || exit 1",
    "source /opt/ros/humble/setup.bash",
    "source /opt/fftai/humanoidnav/install/setup.bash",
    "rviz2 -d rviz/mapping_GR301AA0025.rviz \\",
    "  --ros-args \\",
    "  -r tf:=/GR301AA0025/tf \\",
    "  -r tf_static:=/GR301AA0025/tf_static",
  ].join("\n"),
  localization: [
    "cd ~/aurora_ws/flyAdapter || exit 1",
    "source /opt/ros/humble/setup.bash",
    "source /opt/fftai/humanoidnav/install/setup.bash",
    "rviz2 -d rviz/relocation_GR301AA0025.rviz \\",
    "  --ros-args \\",
    "  -r tf:=/GR301AA0025/tf \\",
    "  -r tf_static:=/GR301AA0025/tf_static",
  ].join("\n"),
};

let busy = false;
let refreshing = false;
let eventSource = null;
let selectedPoi = "";
let robotStatus = {};
let slamStatus = {};
let navPoints = [];
let availableMaps = [];
let availableRoutes = [];
let lastLoadInitialPose = {};
let pointBundle = {
  map_file: "",
  map_name: "",
  initial_pose: {},
  visualization_topics: {},
};
let mapConfig = {
  map_root: "",
  default_map_name: "map",
  default_map_path: "",
  current_map: "",
  current_map_name: "",
  target_map: "",
  target_map_name: "",
  save_timeout_sec: 10,
  load_timeout_sec: 10,
};

const actions = {
  refresh: () => refresh(true),
  startMapping,
  stopMapping,
  saveMap,
  loadMapOnly,
  loadMapWait,
  publishInitialPose,
  savePoint,
  reloadPoints,
  publishPointVisuals,
  gotoPoi,
  cancelNavigation,
  startMission,
  stopMission,
  pauseCruise,
  resumeCruise,
  emergencyStop,
  ensureStand,
  copyMappingRviz: () => copyText(rvizCommands.mapping),
  copyLocalizationRviz: () => copyText(rvizCommands.localization),
  toggleEvents,
  clearResponse: () => setText("lastResponse", ""),
  clearLog: () => setText("operationLog", ""),
};

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || defaultTimeoutMs);
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
    const data = parseJson(text);
    if (!response.ok) {
      data.http_status = response.status;
    }
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      writeLog(`${method} ${path}`, data);
    }
    return data;
  } catch (error) {
    const data = {
      success: false,
      message: error.name === "AbortError" ? "请求超时" : String(error.message || error),
      method,
      path,
    };
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      writeLog(`${method} ${path}`, data);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function parseJson(text) {
  if (!text) return {};
  try { return JSON.parse(text); } catch { return { raw: text }; }
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value == null || value === "" ? "-" : String(value);
}

function setJson(id, data) {
  const el = $(id);
  if (el) el.textContent = JSON.stringify(data || {}, null, 2);
}

function setBadge(id, state, text) {
  const el = $(id);
  if (!el) return;
  el.className = `badge ${state || ""}`.trim();
  el.textContent = text || "-";
}

function writeLog(title, data) {
  const el = $("operationLog");
  if (!el) return;
  const mark = isOk(data) ? "OK" : "ERR";
  const detail = data?.result?.message || data?.message || data?.error || data?.status || "";
  const time = new Date().toLocaleTimeString();
  el.textContent += `[${time}] ${mark} ${title}${detail ? ` - ${detail}` : ""}\n`;
  const lines = el.textContent.split("\n");
  if (lines.length > 220) el.textContent = lines.slice(-200).join("\n");
  el.scrollTop = el.scrollHeight;
}

function isOk(data) {
  if (!data || data.http_status >= 400) return false;
  if (data.success === false || data.status === "failed" || data.status === "blocked") return false;
  if (data.result && data.result.success === false) return false;
  return true;
}

function setMode(mode) {
  $$(".mode-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  $$(".mode-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === mode));
}

function currentMap() {
  return robotStatus.runtime?.current_map || mapConfig.current_map || slamStatus.map_file || "";
}

function targetMapPayload() {
  const name = $("mapName")?.value.trim();
  if (name) return { map_name: name };
  return {};
}

function initialPosePayload({ requireExplicit = false } = {}) {
  const raw = {
    x: $("initX")?.value.trim() ?? "",
    y: $("initY")?.value.trim() ?? "",
    yaw: $("initYaw")?.value.trim() ?? "",
  };
  const provided = Object.entries(raw).filter(([, value]) => value !== "").map(([key]) => key);
  if (!provided.length) {
    if (requireExplicit) throw new Error("请填写初始位姿 x / y / yaw");
    return {};
  }
  const missing = Object.entries(raw).filter(([, value]) => value === "").map(([key]) => key);
  if (missing.length) throw new Error(`初始位姿不完整，缺少：${missing.join(", ")}`);
  const payload = {
    x: numberOrNull(raw.x),
    y: numberOrNull(raw.y),
    z: 0,
    yaw: numberOrNull(raw.yaw),
  };
  if ([payload.x, payload.y, payload.yaw].some((value) => value === null)) throw new Error("初始位姿必须是数字");
  const allowZero = Boolean($("allowZeroInitialPose")?.checked);
  const isZero = Math.abs(payload.x) < 1e-6 && Math.abs(payload.y) < 1e-6 && Math.abs(payload.yaw) < 1e-6;
  if (isZero && !allowZero) throw new Error("初始位姿为原点。确认机器人就在地图原点时，请勾选“允许原点初始化”。");
  if (allowZero) payload.allow_zero_initial_pose = true;
  return payload;
}

function bundlePosePayload() {
  const pose = pointBundle.initial_pose || {};
  if (!hasStoredInitialPose(pose)) return {};
  return {
    x: numberOrZero(pose.x),
    y: numberOrZero(pose.y),
    z: numberOrZero(pose.z),
    yaw: pose.yaw !== undefined ? numberOrZero(pose.yaw) : yawFromQuaternion(pose),
    source: pose.source || "stored",
  };
}

function numberOrZero(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function numberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function yawFromQuaternion(pose) {
  const qx = numberOrZero(pose.q_x);
  const qy = numberOrZero(pose.q_y);
  const qz = numberOrZero(pose.q_z);
  const qw = Number.isFinite(Number(pose.q_w)) ? Number(pose.q_w) : 1;
  const siny = 2 * (qw * qz + qx * qy);
  const cosy = 1 - 2 * (qy * qy + qz * qz);
  return Math.atan2(siny, cosy);
}

function hasStoredInitialPose(pose) {
  if (!pose || pose.source === "unset") return false;
  return ["x", "y", "yaw", "q_z", "q_w"].some((key) => pose[key] !== undefined && pose[key] !== null && pose[key] !== "");
}

function readiness(kind) {
  if (kind === "mapping") return robotStatus.mapping_readiness || robotStatus.workflow?.manual_mapping || slamStatus.mapping_readiness || {};
  if (kind === "poi") return robotStatus.poi_readiness || robotStatus.workflow?.manual_poi || slamStatus.poi_readiness || {};
  return robotStatus.navigation_readiness || robotStatus.readiness || robotStatus.workflow?.auto_navigation || {};
}

function readinessText(item) {
  if (!item) return "-";
  if (item.ready) return "就绪";
  return (item.blockers || [])[0] || (item.warnings || [])[0] || "未就绪";
}

function poseAgeText(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(1)}s` : "-";
}

function bundleMap() {
  return pointBundle.map_file || "";
}

function mapMatches() {
  const current = currentMap();
  const bundle = bundleMap();
  return Boolean(current && bundle && current === bundle);
}

function renderSelects() {
  const mapSelect = $("mapSelect");
  if (mapSelect && availableMaps.length) {
    const currentVal = mapSelect.value;
    mapSelect.innerHTML = `<option value="">-- 选择地图 --</option>` + availableMaps.map(m => `<option value="${m.path}">${m.name} (${m.path})</option>`).join("");
    if (currentVal && availableMaps.find(m => m.path === currentVal)) mapSelect.value = currentVal;
    else if (mapConfig.current_map) mapSelect.value = mapConfig.current_map;
  }
  
  const routeSelect = $("routeSelect");
  if (routeSelect && availableRoutes.length) {
    const currentVal = routeSelect.value;
    routeSelect.innerHTML = `<option value="">-- 选择任务 --</option>` + availableRoutes.map(r => `<option value="${r.name}">${r.name} (${r.points?.length || 0} 个点位)</option>`).join("");
    if (currentVal) routeSelect.value = currentVal;
  }
}

function renderStatus() {
  const ros = robotStatus.ros || {};
  const runtime = robotStatus.runtime || {};
  const motion = robotStatus.motion_authority || robotStatus.workflow?.motion_authority || {};
  const mapping = readiness("mapping");
  const poi = readiness("poi");
  const nav = readiness("navigation");
  const slamMode = runtime.slam_mode || slamStatus.slam_mode || "-";
  
  $("adapterDot")?.classList.toggle("ok", Boolean(ros.ready));
  $("adapterDot")?.classList.toggle("bad", !ros.ready);
  setText("adapterText", ros.ready ? "online" : "partial");
  setText("namespaceLabel", robotStatus.adapter?.namespace || robotStatus.namespace || ros.namespace || "GR3");
  
  setText("rosStatus", ros.ready ? "ready" : "not ready");
  setText("slamMode", slamMode);
  setText("localizationStatus", slamStatus.localization_status || readinessText(poi));
  setText("pointCount", `${navPoints.length} 个`);
  setText("currentMap", currentMap() || "-");
  
  setText("poseAge", poseAgeText(runtime.pose_age_sec ?? slamStatus.pose_age_sec));
  setText("motionSource", mapping.checks?.motion_source || "remote_or_joystick");
  setText("mappingReady", readinessText(mapping));
  setText("bundleMap", bundleMap() || "-");
  setText("mapMatch", bundleMap() ? (mapMatches() ? "一致" : "不一致") : "无点位文件");
  const bp = bundlePosePayload();
  setText("bundlePose", bp.x === undefined ? "未保存初始位姿" : `x=${bp.x}, y=${bp.y}, yaw=${Number(bp.yaw).toFixed(2)}`);
  const loadPose = lastLoadInitialPose.source ? lastLoadInitialPose : bp;
  setText(
    "loadPoseDebug",
    loadPose?.source
      ? `${loadPose.source}: x=${numberOrZero(loadPose.x)}, y=${numberOrZero(loadPose.y)}, yaw=${numberOrZero(loadPose.yaw).toFixed(2)}`
      : "空输入将使用建图原点"
  );
  setText("navPointsFile", pointBundle.nav_points_file || mapConfig.current_nav_points_file || mapConfig.target_nav_points_file || "-");
  
  setText("checkMotion", `${motion.policy || "none"} / ${motion.authority || "external"}`);
  
  setBadge("mappingBadge", mapping.ready ? "ok" : "warn", readinessText(mapping));
  setBadge("localizationBadge", poi.ready ? "ok" : "warn", readinessText(poi));
  setBadge("navigationBadge", nav.ready ? "ok" : "warn", readinessText(nav));
}

function normalizePoint(point, index) {
  return {
    ...point,
    name: String(point.name || `point_${index + 1}`),
    x: numberOrZero(point.x),
    y: numberOrZero(point.y),
    z: numberOrZero(point.z),
    yaw: Number(point.yaw) || 0,
    frame_id: point.frame_id || "map",
  };
}

function renderPoints() {
  const list = $("pointsList");
  const select = $("poiSelect");
  if (!list || !select) return;

  const names = Array.from(new Set(navPoints.map((point) => point.name)));
  list.innerHTML = "";
  select.innerHTML = "";

  if (!names.length) {
    selectedPoi = "";
    list.innerHTML = `<div class="text-dim" style="text-align: center; padding: 20px;">当前地图暂无保存的点位</div>`;
    select.appendChild(new Option("暂无点位", ""));
    return;
  }
  
  if (!selectedPoi || !names.includes(selectedPoi)) selectedPoi = names[0];
  for (const name of names) select.appendChild(new Option(name, name));
  select.value = selectedPoi;

  for (const point of navPoints) {
    const item = document.createElement("div");
    item.className = `point-item ${point.name === selectedPoi ? "selected" : ""}`;
    
    const info = document.createElement("div");
    info.innerHTML = `<strong>${point.name}</strong><span>x=${point.x.toFixed(2)}, y=${point.y.toFixed(2)}, yaw=${point.yaw.toFixed(2)}</span>`;
    
    const actions = document.createElement("div");
    actions.className = "button-row compact";
    actions.innerHTML = `<button type="button" class="button ghost" data-point-action="go">前往</button><button type="button" class="button ghost" data-point-action="delete" style="color:var(--danger)">删除</button>`;
    
    actions.onclick = (event) => {
      event.stopPropagation();
      const action = event.target?.dataset?.pointAction;
      if (action === "go") { selectedPoi = point.name; gotoPoi(); }
      if (action === "delete") deletePoi(point.name);
    };

    item.append(info, actions);
    list.appendChild(item);
  }
}

async function fetchAssets() {
  try {
    const mapsRes = await api("/robot/map/list", { log: false });
    if (mapsRes.maps) availableMaps = mapsRes.maps;
    const routesRes = await api("/robot/routes", { log: false });
    if (routesRes.routes) availableRoutes = routesRes.routes;
    renderSelects();
  } catch (e) {
    console.error("Failed to fetch assets", e);
  }
}

async function refresh(updateLast = false) {
  if (refreshing) return;
  refreshing = true;
  try {
    const [statusResult, slamResult] = await Promise.allSettled([
      api("/robot/status", { updateLast, log: updateLast }),
      api("/slam/status", { updateLast: false, log: updateLast }),
    ]);
    if (statusResult.status === "fulfilled") robotStatus = statusResult.value || {};
    if (slamResult.status === "fulfilled") slamStatus = slamResult.value || {};
    mapConfig = { ...mapConfig, ...(robotStatus.map_config || slamStatus.map_config || {}) };
    
    renderStatus();
    await fetchAssets();
  } finally {
    refreshing = false;
  }

  try {
    await loadPoints(false);
  } catch {
    renderPoints();
  }
}

async function loadPoints(updateLast = true) {
  // Try to use POI endpoints specifically for current map if possible, but fallback to all
  const data = await api("/robot/poi/list?use_current_map=true", { updateLast, log: updateLast });
  navPoints = (data.points || data.nav_points || []).map(normalizePoint);
  renderPoints();
  renderStatus();
}

async function runAction(actionName, button) {
  const action = actions[actionName];
  if (!action || busy) return;
  busy = true;
  const original = button?.textContent;
  if (button) { button.disabled = true; button.textContent = "处理中..."; }
  try { await action(); } 
  catch (error) { setJson("lastResponse", { success: false, message: String(error.message || error) }); } 
  finally {
    if (button) { button.disabled = false; button.textContent = original; }
    busy = false;
  }
}

function saveTimeoutMs() {
  const seconds = Number(mapConfig.save_timeout_sec);
  return Number.isFinite(seconds) ? Math.max(defaultTimeoutMs, (seconds + 2) * 1000) : defaultTimeoutMs;
}

function loadTimeoutMs() {
  const seconds = Number(mapConfig.load_timeout_sec);
  return Number.isFinite(seconds) ? Math.max(defaultTimeoutMs, (seconds + 2) * 1000) : defaultTimeoutMs;
}

async function startMapping() {
  await api("/slam/start_mapping", { method: "POST", body: targetMapPayload() });
  await refresh(false);
}

async function stopMapping() {
  if (!window.confirm("停止建图并保存当前地图？")) return;
  await api("/slam/stop_mapping", { method: "POST", body: targetMapPayload(), timeoutMs: saveTimeoutMs() });
  await refresh(false);
}

async function saveMap() {
  if (!window.confirm("重试保存当前地图？")) return;
  await api("/robot/map/save", { method: "POST", body: targetMapPayload(), timeoutMs: saveTimeoutMs() });
  await refresh(false);
}

async function loadMapOnly() {
  const path = $("mapSelect")?.value;
  if (!path) return alert("请先选择地图");
  const data = await api("/slam/relocation", { method: "POST", body: { map_path: path, ...initialPosePayload(), wait_for_localization: false }, timeoutMs: loadTimeoutMs() });
  lastLoadInitialPose = data?.result?.initial_pose || {};
  await refresh(false);
}

async function loadMapWait() {
  const path = $("mapSelect")?.value;
  if (!path) return alert("请先选择地图");
  const data = await api("/slam/relocation", { method: "POST", body: { map_path: path, ...initialPosePayload(), wait_for_localization: true }, timeoutMs: localizationTimeoutMs });
  lastLoadInitialPose = data?.result?.initial_pose || {};
  await refresh(false);
}

async function publishInitialPose() {
  await api("/robot/localization/initial_pose", { method: "POST", body: { ...initialPosePayload({ requireExplicit: true }), frame_id: "map" } });
  await refresh(false);
}

async function savePoint() {
  const name = $("pointName")?.value.trim();
  if (!name) return alert("请先填写点位名称");
  if (navPoints.some((p) => p.name === name) && !window.confirm(`点位 ${name} 已存在，继续会覆盖同名点。`)) return;
  await api("/robot/poi/save_current", { method: "POST", body: { name, map_name: mapConfig.current_map_name } });
  selectedPoi = name;
  await loadPoints(false);
}

async function reloadPoints() {
  await loadPoints(true);
}

async function publishPointVisuals() {
  await api("/robot/visualization/nav_points", { method: "POST" });
}

async function deletePoi(name) {
  if (!window.confirm(`确认删除点位 ${name}？`)) return;
  await api(`/robot/poi/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (selectedPoi === name) selectedPoi = "";
  await loadPoints(false);
}

async function gotoPoi() {
  const name = $("poiSelect")?.value || selectedPoi;
  if (!name) return alert("请先选择点位");
  selectedPoi = name;
  await api("/robot/navigation/goto_poi", { method: "POST", body: { name, force: true } });
  await refresh(false);
}

async function cancelNavigation() {
  await api("/robot/navigation/cancel", { method: "POST" });
  await refresh(false);
}

async function startMission() {
  const route = $("routeSelect")?.value;
  if(!route) return alert("请先选择任务路线");
  await api("/robot/patrol/start", { method: "POST", body: { route_name: route, force: true } });
  await refresh(false);
}

async function stopMission() {
  await api("/robot/patrol/stop", { method: "POST" });
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

// Safety endpoints
async function emergencyStop() {
  await api("/robot/motion/safety_stop", { method: "POST" });
  await refresh(false);
}

async function ensureStand() {
  await api("/robot/aurora/ensure_stand", { method: "POST" });
  await refresh(false);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    setJson("lastResponse", { success: true, message: "已复制命令", command: text });
  } catch {
    setJson("lastResponse", { success: false, message: "浏览器未允许复制", command: text });
  }
}

function toggleEvents() {
  const button = document.querySelector('[data-action="toggleEvents"]');
  const logBox = $("eventsLog");
  if (!logBox) return;
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    if (button) button.textContent = "连接";
    logBox.textContent += "event stream closed\n";
    return;
  }
  eventSource = new EventSource("/slam/events");
  if (button) button.textContent = "断开";
  eventSource.onopen = () => { logBox.textContent += "event stream connected\n"; };
  eventSource.onmessage = (event) => {
    logBox.textContent += `${event.data}\n`;
    logBox.scrollTop = logBox.scrollHeight;
  };
  eventSource.onerror = () => { logBox.textContent += "event stream error\n"; };
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const modeTab = event.target.closest("[data-mode]");
    if (modeTab) {
      setMode(modeTab.dataset.mode);
      return;
    }
    const actionButton = event.target.closest("[data-action]");
    if (actionButton) {
      runAction(actionButton.dataset.action, actionButton);
    }
  });

  $("poiSelect")?.addEventListener("change", () => {
    selectedPoi = $("poiSelect").value;
    renderPoints();
  });
  
  // Drawer Toggle
  $("drawerToggle")?.addEventListener("click", () => {
    $("terminalDrawer")?.classList.toggle("collapsed");
  });
}

function init() {
  bindEvents();
  refresh(false);
  window.setInterval(() => refresh(false), 5000);
}

init();
