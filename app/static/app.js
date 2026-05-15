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
let pointBundle = {
  map_file: "",
  map_name: "",
  initial_pose: {},
  visualization_topics: {},
};
let mapConfig = {
  map_root: "/opt/fftai/nav",
  default_map_name: "map",
  default_map_path: "/opt/fftai/nav/map",
  current_map: "",
  current_map_name: "",
  save_timeout_sec: 10,
  load_timeout_sec: 10,
};

const actions = {
  refresh: () => refresh(true),
  startMapping,
  stopMapping,
  saveMap,
  setMapPath,
  listMaps,
  loadMapOnly,
  loadMapWait,
  loadBundleMap,
  publishInitialPose,
  savePoint,
  reloadPoints,
  savePointsFile,
  publishPointVisuals,
  clearPoints,
  gotoPoi,
  cancelNavigation,
  currentAction,
  startCruise,
  pauseCruise,
  resumeCruise,
  stopCruise,
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
  const el = $(id);
  if (el) {
    el.textContent = value == null || value === "" ? "-" : String(value);
  }
}

function setJson(id, data) {
  const el = $(id);
  if (el) {
    el.textContent = JSON.stringify(data || {}, null, 2);
  }
}

function setBadge(id, state, text) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.className = `badge ${state || ""}`.trim();
  el.textContent = text || "-";
}

function writeLog(title, data) {
  const el = $("operationLog");
  if (!el) {
    return;
  }
  const mark = isOk(data) ? "OK" : "CHECK";
  const detail = data?.result?.message || data?.message || data?.error || data?.status || "";
  const time = new Date().toLocaleTimeString();
  el.textContent += `[${time}] ${mark} ${title}${detail ? ` - ${detail}` : ""}\n`;
  const lines = el.textContent.split("\n");
  if (lines.length > 220) {
    el.textContent = lines.slice(-200).join("\n");
  }
  el.scrollTop = el.scrollHeight;
}

function isOk(data) {
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

function setMode(mode) {
  $$(".mode-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  $$(".mode-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === mode));
}

function currentMap() {
  return robotStatus.runtime?.current_map || mapConfig.current_map || slamStatus.map_file || "";
}

function targetMap() {
  const explicitPath = $("mapPath")?.value.trim() || "";
  if (explicitPath) {
    return explicitPath;
  }
  const root = String(mapConfig.map_root || "/opt/fftai/nav").replace(/[\\/]+$/, "");
  const name = ($("mapName")?.value.trim() || mapConfig.current_map_name || mapConfig.default_map_name || "map").replace(/^[\\/]+|[\\/]+$/g, "");
  return `${root}/${name}`;
}

function mapPayload() {
  const explicitPath = $("mapPath")?.value.trim() || "";
  if (explicitPath) {
    return { map_path: explicitPath };
  }
  return { map_name: $("mapName")?.value.trim() || mapConfig.current_map_name || mapConfig.default_map_name || "map" };
}

function posePayload() {
  return {
    x: numberOrZero($("initX")?.value),
    y: numberOrZero($("initY")?.value),
    z: 0,
    yaw: numberOrZero($("initYaw")?.value),
  };
}

function bundlePosePayload() {
  const pose = pointBundle.initial_pose || {};
  const hasPose = ["x", "y", "z", "yaw"].some((key) => pose[key] !== undefined && pose[key] !== null && pose[key] !== "");
  if (!hasPose) {
    return posePayload();
  }
  return {
    x: numberOrZero(pose.x),
    y: numberOrZero(pose.y),
    z: numberOrZero(pose.z),
    yaw: numberOrZero(pose.yaw),
  };
}

function numberOrZero(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function readiness(kind) {
  if (kind === "mapping") {
    return robotStatus.mapping_readiness || robotStatus.workflow?.manual_mapping || slamStatus.mapping_readiness || {};
  }
  if (kind === "poi") {
    return robotStatus.poi_readiness || robotStatus.workflow?.manual_poi || slamStatus.poi_readiness || {};
  }
  return robotStatus.navigation_readiness || robotStatus.readiness || robotStatus.workflow?.auto_navigation || {};
}

function readinessText(item) {
  if (!item) {
    return "-";
  }
  if (item.ready) {
    return "就绪";
  }
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

function nextActionText() {
  const slamMode = robotStatus.runtime?.slam_mode || slamStatus.slam_mode || "";
  if (slamMode === "mapping") {
    return "正在建图。完成后使用“停止并保存”。";
  }
  if (!currentMap()) {
    return "先加载地图。后续要打点或导航时，使用“加载并等待稳定”。";
  }
  if (bundleMap() && !mapMatches()) {
    return "点位文件地图与当前地图不一致，请先加载点位地图。";
  }
  if (!readiness("poi").ready) {
    return "地图已加载，等待定位稳定后再打点。";
  }
  if (!navPoints.length) {
    return "定位稳定，可以开始保存点位。";
  }
  if (!readiness("navigation").ready) {
    return "已有点位，导航 readiness 还未就绪。";
  }
  return "可以单点导航或开始巡航。";
}

function syncMapInputs() {
  const nameInput = $("mapName");
  const pathInput = $("mapPath");
  if (nameInput && !nameInput.value.trim() && document.activeElement !== nameInput) {
    nameInput.value = mapConfig.current_map_name || mapConfig.default_map_name || "map";
  }
  if (pathInput && document.activeElement !== pathInput) {
    pathInput.placeholder = `留空使用 ${targetMap()}`;
  }
  setText("targetMap", targetMap());
}

function renderStatus() {
  const ros = robotStatus.ros || {};
  const runtime = robotStatus.runtime || {};
  const aurora = robotStatus.aurora || {};
  const motion = robotStatus.motion_authority || robotStatus.workflow?.motion_authority || {};
  const mapping = readiness("mapping");
  const poi = readiness("poi");
  const nav = readiness("navigation");
  const slamMode = runtime.slam_mode || slamStatus.slam_mode || "-";
  const cruising = Boolean(runtime.is_cruising || slamStatus.is_cruising);
  const paused = Boolean(runtime.is_paused || slamStatus.is_paused);
  const topics = pointBundle.visualization_topics || {};
  const bundlePose = bundlePosePayload();

  $("adapterDot")?.classList.toggle("ok", Boolean(ros.ready));
  $("adapterDot")?.classList.toggle("bad", !ros.ready);
  setText("adapterText", ros.ready ? "online" : "partial");
  setText("namespaceLabel", robotStatus.adapter?.namespace || robotStatus.namespace || ros.namespace || "GR3");
  setText("rosStatus", ros.ready ? "ready" : "not ready");
  setText("slamMode", slamMode);
  setText("localizationStatus", slamStatus.localization_status || readinessText(poi));
  setText("pointCount", `${navPoints.length} 个点`);
  setText("currentMap", currentMap() || "-");
  setText("targetMap", targetMap());
  setText("poseAge", poseAgeText(runtime.pose_age_sec ?? slamStatus.pose_age_sec));
  setText("motionSource", mapping.checks?.motion_source || "remote_or_joystick");
  setText("mappingReady", readinessText(mapping));
  setText("bundleMap", bundleMap() || "-");
  setText("mapMatch", bundleMap() ? (mapMatches() ? "一致" : "不一致") : "无点位文件");
  setText("bundlePose", `x=${bundlePose.x}, y=${bundlePose.y}, yaw=${bundlePose.yaw}`);
  setText("visualTopics", [topics.nav_points, topics.current_goal, topics.cruise_path].filter(Boolean).join(" / ") || "-");
  setText("nextAction", nextActionText());

  setBadge("mappingBadge", mapping.ready ? "ok" : "warn", readinessText(mapping));
  setBadge("localizationBadge", poi.ready ? "ok" : "warn", readinessText(poi));
  setBadge("navigationBadge", nav.ready ? "ok" : "warn", cruising ? (paused ? "暂停中" : "巡航中") : readinessText(nav));
  setText("mappingHint", `目标地图：${targetMap()}`);
  setText("localizationHint", poi.ready ? "定位稳定，可以打点或导航。" : "定位未稳定时不建议保存点位。");
  setText("pointSaveHint", poi.ready ? "当前位置可保存为点位。" : "后端会阻止不安全的打点保存。");
  setText("navigationHint", mapMatches() ? "点位地图与当前地图一致。" : "请先加载点位文件绑定的地图。");

  setJson("mappingBox", {
    target_map: targetMap(),
    current_map: currentMap(),
    slam_mode: slamMode,
    mapping_readiness: mapping,
  });
  setJson("localizationBox", {
    target_map: targetMap(),
    current_map: currentMap(),
    localization_status: slamStatus.localization_status,
    poi_readiness: poi,
    navigation_readiness: nav,
  });
  setJson("cruiseBox", {
    is_cruising: cruising,
    is_paused: paused,
    current_nav_index: runtime.current_nav_index ?? slamStatus.current_nav_index,
    total_nav_points: runtime.total_nav_points ?? slamStatus.total_nav_points,
    current_target: runtime.current_target,
  });

  setText("flowMapping", readinessText(mapping));
  setText("flowLocalization", readinessText(poi));
  setText("flowNavigation", navPoints.length ? readinessText(nav) : "还没有点位");
  setText("checkRos", ros.ready ? "ready" : (ros.error || "not ready"));
  setText("checkMapping", readinessText(mapping));
  setText("checkPoi", readinessText(poi));
  setText("checkNav", readinessText(nav));
  setText("checkAurora", aurora.connected ? (aurora.standing ? "standing" : "connected") : (aurora.error || "optional"));
  setText("checkMotion", `${motion.policy || "none"} / ${motion.authority || "external"}`);
  setJson("readinessBox", {
    map_config: mapConfig,
    mapping_readiness: mapping,
    poi_readiness: poi,
    navigation_readiness: nav,
    aurora,
    motion_authority: motion,
  });
}

function yawFromQuaternion(point) {
  if (Number.isFinite(Number(point.yaw))) {
    return Number(point.yaw);
  }
  const x = numberOrZero(point.q_x);
  const y = numberOrZero(point.q_y);
  const z = numberOrZero(point.q_z);
  const w = Number.isFinite(Number(point.q_w)) ? Number(point.q_w) : 1;
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}

function normalizePoint(point, index) {
  return {
    ...point,
    name: String(point.name || `point_${index + 1}`),
    x: numberOrZero(point.x),
    y: numberOrZero(point.y),
    z: numberOrZero(point.z),
    yaw: yawFromQuaternion(point),
    frame_id: point.frame_id || "map",
  };
}

function selectedPoint() {
  return navPoints.find((point) => point.name === selectedPoi) || null;
}

function renderPoints() {
  const list = $("pointsList");
  const select = $("poiSelect");
  if (!list || !select) {
    return;
  }
  const query = ($("pointSearch")?.value || "").trim().toLowerCase();
  const filtered = query ? navPoints.filter((point) => point.name.toLowerCase().includes(query)) : navPoints;
  const names = Array.from(new Set(navPoints.map((point) => point.name)));
  list.innerHTML = "";
  select.innerHTML = "";

  if (!names.length) {
    selectedPoi = "";
    list.innerHTML = `<div class="empty-state">暂无点位</div>`;
    select.appendChild(new Option("暂无点位", ""));
    return;
  }
  if (!selectedPoi || !names.includes(selectedPoi)) {
    selectedPoi = names[0];
  }
  for (const name of names) {
    select.appendChild(new Option(name, name));
  }
  select.value = selectedPoi;

  if (!filtered.length) {
    list.innerHTML = `<div class="empty-state">没有匹配点位</div>`;
    return;
  }

  for (const point of filtered) {
    const item = document.createElement("div");
    item.className = `point-item ${point.name === selectedPoi ? "selected" : ""}`;
    item.onclick = () => {
      selectedPoi = point.name;
      renderPoints();
    };

    const title = document.createElement("strong");
    title.textContent = point.name;

    const meta = document.createElement("span");
    meta.textContent = `x=${point.x.toFixed(2)}, y=${point.y.toFixed(2)}, yaw=${point.yaw.toFixed(2)}${point.map_name ? ` / ${point.map_name}` : ""}`;

    const actions = document.createElement("div");
    actions.className = "point-actions";
    actions.innerHTML = `<button type="button" data-point-action="go">导航</button><button type="button" data-point-action="delete">删除</button>`;
    actions.onclick = (event) => {
      event.stopPropagation();
      const action = event.target?.dataset?.pointAction;
      if (action === "go") {
        selectedPoi = point.name;
        gotoPoi();
      }
      if (action === "delete") {
        deletePoi(point.name);
      }
    };

    item.append(title, meta, actions);
    list.appendChild(item);
  }
}

async function refresh(updateLast = false) {
  if (refreshing) {
    return;
  }
  refreshing = true;
  try {
    const [statusResult, slamResult] = await Promise.allSettled([
      api("/robot/status", { updateLast, log: updateLast }),
      api("/slam/status", { updateLast: false, log: updateLast }),
    ]);
    if (statusResult.status === "fulfilled") {
      robotStatus = statusResult.value || {};
    }
    if (slamResult.status === "fulfilled") {
      slamStatus = slamResult.value || {};
    }
    mapConfig = { ...mapConfig, ...(robotStatus.map_config || slamStatus.map_config || {}) };
    syncMapInputs();
    renderStatus();
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
  const data = await api("/slam/nav_points", { updateLast, log: updateLast });
  navPoints = (data.nav_points || data.points || []).map(normalizePoint);
  pointBundle = {
    map_file: data.map_file || "",
    map_name: data.map_name || "",
    initial_pose: data.initial_pose || {},
    visualization_topics: data.visualization_topics || {},
  };
  renderPoints();
  renderStatus();
}

async function runAction(actionName, button) {
  const action = actions[actionName];
  if (!action || busy) {
    return;
  }
  busy = true;
  const original = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "处理中";
  }
  try {
    await action();
  } catch (error) {
    setJson("lastResponse", { success: false, message: String(error.message || error) });
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original;
    }
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
  await api("/slam/start_mapping", { method: "POST", body: mapPayload() });
  await refresh(false);
}

async function stopMapping() {
  if (!window.confirm("停止建图并保存当前地图？")) {
    return;
  }
  await api("/slam/stop_mapping", { method: "POST", body: mapPayload(), timeoutMs: saveTimeoutMs() });
  await refresh(false);
}

async function saveMap() {
  if (!window.confirm("重新调用 save_map 保存当前地图？")) {
    return;
  }
  await api("/robot/map/save", { method: "POST", body: mapPayload(), timeoutMs: saveTimeoutMs() });
  await refresh(false);
}

async function setMapPath() {
  await api("/slam/set_map_path", { method: "POST", body: mapPayload() });
  await refresh(false);
}

async function listMaps() {
  const data = await api("/robot/map/list");
  setJson("mapListBox", data);
}

async function loadMapOnly() {
  await api("/slam/relocation", {
    method: "POST",
    body: { ...mapPayload(), ...posePayload(), wait_for_localization: false },
    timeoutMs: loadTimeoutMs(),
  });
  await refresh(false);
}

async function loadMapWait() {
  await api("/slam/relocation", {
    method: "POST",
    body: { ...mapPayload(), ...posePayload(), wait_for_localization: true },
    timeoutMs: localizationTimeoutMs,
  });
  await refresh(false);
}

async function loadBundleMap() {
  if (!bundleMap()) {
    setJson("lastResponse", { success: false, message: "当前没有点位文件绑定地图" });
    return;
  }
  await api("/slam/relocation", {
    method: "POST",
    body: { map_path: bundleMap(), ...bundlePosePayload(), wait_for_localization: true },
    timeoutMs: localizationTimeoutMs,
  });
  await refresh(false);
}

async function publishInitialPose() {
  await api("/robot/localization/initial_pose", { method: "POST", body: { ...posePayload(), frame_id: "map" } });
  await refresh(false);
}

async function savePoint() {
  const name = $("pointName")?.value.trim();
  if (!name) {
    setJson("lastResponse", { success: false, message: "请先填写点位名称" });
    return;
  }
  if (navPoints.some((point) => point.name === name) && !window.confirm(`点位 ${name} 已存在，继续会覆盖同名点。`)) {
    return;
  }
  await api("/robot/poi/save_current", { method: "POST", body: { name } });
  selectedPoi = name;
  await loadPoints(false);
}

async function reloadPoints() {
  await api("/slam/load_nav_points", { method: "POST" });
  await loadPoints(false);
}

async function savePointsFile() {
  await api("/slam/save_nav_points", { method: "POST" });
  await loadPoints(false);
}

async function publishPointVisuals() {
  await api("/robot/visualization/nav_points", { method: "POST" });
}

async function clearPoints() {
  if (!window.confirm("确认清空当前点位？")) {
    return;
  }
  await api("/slam/clear_nav_points", { method: "POST" });
  selectedPoi = "";
  await loadPoints(false);
}

async function deletePoi(name) {
  if (!window.confirm(`确认删除点位 ${name}？`)) {
    return;
  }
  await api(`/robot/poi/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (selectedPoi === name) {
    selectedPoi = "";
  }
  await loadPoints(false);
}

async function gotoPoi() {
  const name = $("poiSelect")?.value || selectedPoi;
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
  await api("/slam/start_cruise", { method: "POST", body: { force: Boolean($("forceCruise")?.checked) } });
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

async function stopCruise() {
  await api("/slam/stop_cruise", { method: "POST" });
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
  if (!logBox) {
    return;
  }
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    if (button) {
      button.textContent = "连接事件流";
    }
    logBox.textContent += "event stream closed\n";
    return;
  }
  eventSource = new EventSource("/slam/events");
  if (button) {
    button.textContent = "断开事件流";
  }
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

  $("mapName")?.addEventListener("input", syncMapInputs);
  $("mapPath")?.addEventListener("input", syncMapInputs);
  $("pointSearch")?.addEventListener("input", renderPoints);
  $("poiSelect")?.addEventListener("change", () => {
    selectedPoi = $("poiSelect").value;
    renderPoints();
  });
}

function init() {
  setText("mappingRvizCommand", rvizCommands.mapping);
  setText("localizationRvizCommand", rvizCommands.localization);
  bindEvents();
  refresh(false);
  window.setInterval(() => refresh(false), 5000);
}

init();
