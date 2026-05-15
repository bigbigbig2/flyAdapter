const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const requestTimeoutMs = 12000;
const localizationWaitTimeoutMs = 45000;
const jsonHeaders = { "Content-Type": "application/json" };

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
let lastStatus = {};
let lastSlamStatus = {};
let points = [];
let pointBundle = {
  map_file: "",
  map_name: "",
  current_map: "",
  current_map_name: "",
  initial_pose: {},
  visualization_topics: {},
  bundle_matches_current: false,
};
let mapConfig = {
  map_root: "/opt/fftai/nav",
  default_map_name: "map",
  default_map_path: "/opt/fftai/nav/map",
  current_map: "",
  current_map_name: "",
  load_timeout_sec: 10,
  save_timeout_sec: 10,
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
    const data = parseJson(text);
    if (!response.ok) {
      data.http_status = response.status;
    }
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      log(`${method} ${path}`, data);
    }
    return data;
  } catch (error) {
    const message = error.name === "AbortError" ? "请求超时" : String(error.message || error);
    const data = { success: false, message, path, method };
    if (options.updateLast !== false) {
      setJson("lastResponse", data);
    }
    if (options.log !== false) {
      log(`${method} ${path}`, data);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
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
    el.textContent = value === undefined || value === null || value === "" ? "-" : String(value);
  }
}

function setJson(id, value) {
  const el = $(id);
  if (el) {
    el.textContent = JSON.stringify(value || {}, null, 2);
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

function setNotice(id, state, text) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.className = `notice ${state || ""}`.trim();
  el.textContent = text || "-";
}

function log(title, data) {
  const el = $("operationLog");
  if (!el) {
    return;
  }
  const ok = isOk(data) ? "OK" : "CHECK";
  const detail = messageOf(data);
  const time = new Date().toLocaleTimeString();
  el.textContent += `[${time}] ${ok} ${title}${detail ? ` - ${detail}` : ""}\n`;
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

function messageOf(data) {
  return data?.result?.message || data?.message || data?.error || data?.status || "";
}

function activePanel(name) {
  $$(".step").forEach((el) => el.classList.toggle("active", el.dataset.step === name));
  $$(".panel").forEach((el) => el.classList.toggle("active", el.dataset.panel === name));
}

function numberOrZero(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function basename(path) {
  const clean = String(path || "").replace(/[\\/]+$/, "");
  if (!clean) {
    return "";
  }
  return clean.split(/[\\/]/).pop() || "";
}

function mapName() {
  return $("mapName")?.value.trim() || mapConfig.current_map_name || mapConfig.default_map_name || "map";
}

function mapPathInput() {
  return $("mapPath")?.value.trim() || "";
}

function joinMapPath(root, name) {
  const cleanRoot = String(root || "/opt/fftai/nav").replace(/[\\/]+$/, "");
  const cleanName = String(name || "map").replace(/^[\\/]+|[\\/]+$/g, "");
  return `${cleanRoot}/${cleanName}`;
}

function targetMapPath() {
  return mapPathInput() || joinMapPath(mapConfig.map_root, mapName());
}

function mapPayload() {
  const path = mapPathInput();
  return path ? { map_path: path } : { map_name: mapName() };
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

function currentMapPath() {
  return lastStatus.runtime?.current_map || mapConfig.current_map || lastSlamStatus.map_file || "";
}

function bundleMapPath() {
  return pointBundle.map_file || "";
}

function mapMatches() {
  const current = currentMapPath();
  const bundle = bundleMapPath();
  return Boolean(current && bundle && current === bundle);
}

function readiness(name) {
  if (name === "mapping") {
    return lastStatus.mapping_readiness || lastStatus.workflow?.manual_mapping || lastSlamStatus.mapping_readiness || {};
  }
  if (name === "poi") {
    return lastStatus.poi_readiness || lastStatus.workflow?.manual_poi || lastSlamStatus.poi_readiness || {};
  }
  return lastStatus.navigation_readiness || lastStatus.readiness || lastStatus.workflow?.auto_navigation || {};
}

function blockerText(item) {
  if (!item) {
    return "-";
  }
  if (item.ready) {
    return "就绪";
  }
  const blockers = item.blockers || [];
  const warnings = item.warnings || [];
  return blockers[0] || warnings[0] || "未就绪";
}

function poseAgeText(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(1)}s` : "-";
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
  return points.find((point) => point.name === selectedPoi) || null;
}

function nextActionText() {
  const current = currentMapPath();
  const bundle = bundleMapPath();
  const poiReady = Boolean(readiness("poi").ready || lastSlamStatus.ready_for_poi);
  const navReady = Boolean(readiness("navigation").ready);
  const slamMode = lastStatus.runtime?.slam_mode || lastSlamStatus.slam_mode || "";
  if (slamMode === "mapping") {
    return "正在建图，完成后停止建图并保存。";
  }
  if (!current) {
    return "先加载地图；后续要打点或导航时请选择“加载并等待定位稳定”。";
  }
  if (bundle && current !== bundle) {
    return "点位文件地图与当前加载地图不一致，先按点位文件加载地图。";
  }
  if (!poiReady) {
    return "地图已加载，等待定位稳定后再打点。";
  }
  if (!points.length) {
    return "定位稳定，可以开始保存点位。";
  }
  if (!navReady) {
    return "点位已存在，但导航 readiness 未就绪。";
  }
  return "可以做单点导航或开始巡航。";
}

function renderStatus() {
  const ros = lastStatus.ros || {};
  const runtime = lastStatus.runtime || {};
  const motion = lastStatus.motion_authority || lastStatus.workflow?.motion_authority || {};
  const aurora = lastStatus.aurora || {};
  const mapping = readiness("mapping");
  const poi = readiness("poi");
  const nav = readiness("navigation");
  const current = currentMapPath();
  const bundle = bundleMapPath();
  const slamMode = runtime.slam_mode || lastSlamStatus.slam_mode || "-";
  const poseAge = runtime.pose_age_sec ?? lastSlamStatus.pose_age_sec;
  const cruising = Boolean(runtime.is_cruising || lastSlamStatus.is_cruising);
  const paused = Boolean(runtime.is_paused || lastSlamStatus.is_paused);

  setAdapter(Boolean(ros.ready), ros.ready ? "online" : "partial");
  setText("namespaceLabel", lastStatus.adapter?.namespace || lastStatus.namespace || ros.namespace || "GR3");
  setText("rosStatus", ros.ready ? "ready" : "not ready");
  setText("slamMode", slamMode);
  setText("localizationState", lastSlamStatus.localization_status || blockerText(poi));
  setText("navState", cruising ? (paused ? "paused" : "cruising") : blockerText(nav));
  setText("currentMap", current || "-");
  setText("targetMap", targetMapPath());
  setText("poseAge", poseAgeText(poseAge));
  setText("bundleMap", bundle || "-");
  setText("mapMatch", bundle ? (mapMatches() ? "一致" : "不一致") : "无点位文件");
  setText("nextAction", nextActionText());
  setText("healthLine", lastSlamStatus.last_error ? `最近错误：${lastSlamStatus.last_error}` : nextActionText());

  setText("flowMapping", blockerText(mapping));
  setText("flowLocalization", blockerText(poi));
  setText("flowNavigation", points.length ? blockerText(nav) : "还没有点位");
  setText("checkRos", ros.ready ? "ready" : (ros.error || "not ready"));
  setText("checkMapping", blockerText(mapping));
  setText("checkPoi", blockerText(poi));
  setText("checkNav", blockerText(nav));
  setText("checkAurora", aurora.connected ? (aurora.standing ? "standing" : "connected") : (aurora.error || "optional"));
  setText("checkMotion", `${motion.policy || "none"} / ${motion.authority || "external"}`);

  setBadge("checkBadge", ros.ready ? "ok" : "warn", ros.ready ? "online" : "partial");
  setBadge("mappingBadge", mapping.ready ? "ok" : "warn", blockerText(mapping));
  setBadge("localizationBadge", poi.ready ? "ok" : "warn", blockerText(poi));
  setBadge("pointsBadge", points.length ? "ok" : "warn", `${points.length} 个点`);
  setBadge("navigateBadge", nav.ready ? "ok" : "warn", blockerText(nav));
  setBadge("cruiseBadge", cruising ? "ok" : "warn", cruising ? (paused ? "paused" : "running") : "idle");

  setText("stepCheck", ros.ready ? "通过" : "待处理");
  setText("stepMapping", blockerText(mapping));
  setText("stepLocalization", blockerText(poi));
  setText("stepPoints", `${points.length} 个点`);
  setText("stepNavigate", selectedPoi || "待选择");
  setText("stepCruise", cruising ? (paused ? "已暂停" : "运行中") : "待启动");

  setText("mappingHint", `目标地图：${targetMapPath()}`);
  setNotice("localizationNotice", poi.ready ? "ok" : "warn", poi.ready ? "定位稳定，可以打点或导航。" : "定位未稳定时可以加载地图，但不建议打点。");
  setNotice("pointsNotice", poi.ready ? "ok" : "warn", poi.ready ? "保存点位会绑定当前加载地图。" : "打点按钮仍可点击，但后端会阻止不安全的保存。");
  setNotice("navNotice", nav.ready ? "ok" : "warn", nav.ready ? "可以下发导航。" : `导航未就绪：${blockerText(nav)}`);
  setNotice("cruiseNotice", nav.ready ? "ok" : "warn", nav.ready ? "可以开始巡航。" : `巡航前请确认导航就绪：${blockerText(nav)}`);

  setJson("readinessBox", {
    map_config: mapConfig,
    mapping_readiness: mapping,
    poi_readiness: poi,
    navigation_readiness: nav,
    ros,
    aurora,
    motion_authority: motion,
  });
  setJson("mappingBox", {
    target_map: targetMapPath(),
    current_map: current,
    slam_mode: slamMode,
    mapping_readiness: mapping,
  });
  setJson("localizationBox", {
    target_map: targetMapPath(),
    current_map: current,
    localization_status: lastSlamStatus.localization_status,
    odom_status_code: runtime.odom_status_code ?? lastSlamStatus.odom_status_code,
    poi_readiness: poi,
    navigation_readiness: nav,
  });
  setJson("cruiseBox", {
    is_cruising: cruising,
    is_paused: paused,
    current_nav_index: runtime.current_nav_index ?? lastSlamStatus.current_nav_index,
    total_nav_points: runtime.total_nav_points ?? lastSlamStatus.total_nav_points,
    current_target: runtime.current_target,
  });
}

function renderPointBundle() {
  const topics = pointBundle.visualization_topics || {};
  const initial = bundlePosePayload();
  setText("pointBundleMap", bundleMapPath() || "-");
  setText("pointCurrentMap", currentMapPath() || "-");
  setText("pointInitialPose", `x=${initial.x}, y=${initial.y}, yaw=${initial.yaw}`);
  setText("pointTopics", [topics.nav_points, topics.current_goal, topics.cruise_path].filter(Boolean).join(" / ") || "-");
}

function renderPoints() {
  const list = $("pointsList");
  const select = $("poiSelect");
  if (!list || !select) {
    return;
  }

  const query = ($("pointSearch")?.value || "").trim().toLowerCase();
  const filtered = query ? points.filter((point) => point.name.toLowerCase().includes(query)) : points;
  list.innerHTML = "";
  select.innerHTML = "";

  if (!points.length) {
    list.innerHTML = `<div class="empty">暂无点位</div>`;
    select.appendChild(new Option("暂无点位", ""));
    selectedPoi = "";
    setText("pointsSummary", "暂无点位");
    setText("selectedPoiText", "未选择目标点");
    return;
  }

  const names = Array.from(new Set(points.map((point) => point.name)));
  if (!selectedPoi || !names.includes(selectedPoi)) {
    selectedPoi = names[0] || "";
  }

  for (const point of filtered) {
    const item = document.createElement("div");
    item.className = `point ${point.name === selectedPoi ? "selected" : ""}`;
    item.onclick = () => {
      selectedPoi = point.name;
      renderPoints();
      renderStatus();
    };

    const title = document.createElement("strong");
    title.textContent = point.name;
    const detail = document.createElement("span");
    detail.textContent = `x=${point.x.toFixed(2)}, y=${point.y.toFixed(2)}, yaw=${point.yaw.toFixed(2)} / ${point.frame_id}${point.map_name ? ` / map=${point.map_name}` : ""}`;
    const actions = document.createElement("span");
    actions.className = "point-actions";
    actions.innerHTML = `<button type="button" data-action="go">导航</button><button type="button" data-action="delete">删除</button>`;
    actions.onclick = (event) => {
      event.stopPropagation();
      const action = event.target?.dataset?.action;
      if (action === "go") {
        selectedPoi = point.name;
        gotoPoi();
      }
      if (action === "delete") {
        deletePoi(point.name);
      }
    };

    item.append(title, detail, actions);
    list.appendChild(item);
  }

  if (!filtered.length) {
    list.innerHTML = `<div class="empty">没有匹配点位</div>`;
  }

  for (const name of names) {
    select.appendChild(new Option(name, name));
  }
  select.value = selectedPoi;

  const selected = selectedPoint();
  setText("pointsSummary", `共 ${points.length} 个点位`);
  setText("selectedPoiText", selected ? `${selected.name} / x=${selected.x.toFixed(2)}, y=${selected.y.toFixed(2)}, yaw=${selected.yaw.toFixed(2)}` : "未选择目标点");
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
      lastStatus = statusResult.value || {};
    }
    if (slamResult.status === "fulfilled") {
      lastSlamStatus = slamResult.value || {};
    }
    const config = lastStatus.map_config || lastSlamStatus.map_config || {};
    mapConfig = { ...mapConfig, ...config };
    syncMapInputs();
    renderStatus();
  } catch (error) {
    setAdapter(false, "offline");
    setText("healthLine", String(error.message || error));
  } finally {
    refreshing = false;
  }

  try {
    await loadPoints(false);
  } catch {
    renderPointBundle();
    renderPoints();
  }
}

function syncMapInputs() {
  const nameInput = $("mapName");
  const pathInput = $("mapPath");
  if (nameInput && !nameInput.value.trim() && document.activeElement !== nameInput) {
    nameInput.value = mapConfig.current_map_name || mapConfig.default_map_name || "map";
  }
  if (pathInput && document.activeElement !== pathInput) {
    pathInput.placeholder = `留空则使用 ${joinMapPath(mapConfig.map_root, mapName())}`;
  }
  setText("targetMap", targetMapPath());
}

function setAdapter(ok, text) {
  const dot = $("adapterDot");
  if (dot) {
    dot.className = `dot ${ok ? "ok" : "bad"}`;
  }
  setText("adapterText", text);
}

async function loadPoints(updateLast = true) {
  const data = await api("/slam/nav_points", { updateLast, log: updateLast });
  points = (data.nav_points || data.points || []).map(normalizePoint);
  pointBundle = {
    map_file: data.map_file || "",
    map_name: data.map_name || "",
    current_map: data.current_map || "",
    current_map_name: data.current_map_name || "",
    initial_pose: data.initial_pose || {},
    visualization_topics: data.visualization_topics || {},
    bundle_matches_current: Boolean(data.bundle_matches_current),
  };
  renderPointBundle();
  renderPoints();
  renderStatus();
  return data;
}

async function withBusy(buttonId, fn) {
  if (busy) {
    return;
  }
  busy = true;
  const button = $(buttonId);
  const text = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "处理中";
  }
  try {
    await fn();
  } catch (error) {
    setJson("lastResponse", { success: false, message: String(error.message || error) });
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = text;
    }
    busy = false;
  }
}

function bind(id, fn) {
  const el = $(id);
  if (el) {
    el.onclick = () => withBusy(id, fn);
  }
}

function saveTimeoutMs() {
  const seconds = Number(mapConfig.save_timeout_sec);
  return Number.isFinite(seconds) ? Math.max(requestTimeoutMs, (seconds + 2) * 1000) : requestTimeoutMs;
}

function loadTimeoutMs() {
  const seconds = Number(mapConfig.load_timeout_sec);
  return Number.isFinite(seconds) ? Math.max(requestTimeoutMs, (seconds + 2) * 1000) : requestTimeoutMs;
}

async function startMapping() {
  await api("/slam/start_mapping", { method: "POST", body: mapPayload() });
  await refresh(false);
  activePanel("mapping");
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

async function setMapPathOnly() {
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

async function loadMapAndWait() {
  await api("/slam/relocation", {
    method: "POST",
    body: { ...mapPayload(), ...posePayload(), wait_for_localization: true },
    timeoutMs: localizationWaitTimeoutMs,
  });
  await refresh(false);
}

async function loadBundleMap() {
  if (!bundleMapPath()) {
    setJson("lastResponse", { success: false, message: "当前没有点位文件绑定地图" });
    return;
  }
  await api("/slam/relocation", {
    method: "POST",
    body: { map_path: bundleMapPath(), ...bundlePosePayload(), wait_for_localization: true },
    timeoutMs: localizationWaitTimeoutMs,
  });
  await refresh(false);
  activePanel("navigate");
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
  if (points.some((point) => point.name === name) && !window.confirm(`点位 ${name} 已存在，继续会覆盖同名点。`)) {
    return;
  }
  await api("/robot/poi/save_current", { method: "POST", body: { name } });
  selectedPoi = name;
  await loadPoints(false);
}

async function reloadPointBundle() {
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

async function gotoPoi(name = $("poiSelect")?.value || selectedPoi) {
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

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    setJson("lastResponse", { success: true, message: "已复制命令", command: text });
  } catch {
    setJson("lastResponse", { success: false, message: "浏览器未允许复制，命令如下", command: text });
  }
}

function connectEvents() {
  const logBox = $("eventsLog");
  const button = $("connectEventsBtn");
  if (!logBox || !button) {
    return;
  }
  if (eventSource) {
    eventSource.close();
    eventSource = null;
    button.textContent = "连接事件";
    logBox.textContent += "event stream closed\n";
    return;
  }
  eventSource = new EventSource("/slam/events");
  button.textContent = "断开事件";
  eventSource.onopen = () => { logBox.textContent += "event stream connected\n"; };
  eventSource.onmessage = (event) => {
    logBox.textContent += `${event.data}\n`;
    logBox.scrollTop = logBox.scrollHeight;
  };
  eventSource.onerror = () => { logBox.textContent += "event stream error\n"; };
}

function bindEvents() {
  $$(".step").forEach((item) => {
    item.onclick = () => activePanel(item.dataset.step);
  });
  bind("refreshBtn", () => refresh(true));
  bind("goMappingBtn", async () => activePanel("mapping"));
  bind("goLocalizationBtn", async () => activePanel("localization"));
  bind("goNavigateBtn", async () => activePanel("navigate"));
  bind("startMappingBtn", startMapping);
  bind("stopMappingBtn", stopMapping);
  bind("saveMapBtn", saveMap);
  bind("setMapPathBtn", setMapPathOnly);
  bind("listMapsBtn", listMaps);
  bind("copyMappingRvizBtn", () => copyText(rvizCommands.mapping));
  bind("loadMapOnlyBtn", loadMapOnly);
  bind("loadMapWaitBtn", loadMapAndWait);
  bind("loadBundleMapBtn", loadBundleMap);
  bind("initialPoseBtn", publishInitialPose);
  bind("copyLocalizationRvizBtn", () => copyText(rvizCommands.localization));
  bind("savePointBtn", savePoint);
  bind("reloadPointsBtn", reloadPointBundle);
  bind("savePointsFileBtn", savePointsFile);
  bind("publishPointVisualsBtn", publishPointVisuals);
  bind("clearPointsBtn", clearPoints);
  bind("gotoPoiBtn", () => gotoPoi());
  bind("cancelNavBtn", cancelNavigation);
  bind("currentActionBtn", currentAction);
  bind("startCruiseBtn", startCruise);
  bind("pauseBtn", pauseCruise);
  bind("resumeBtn", resumeCruise);
  bind("stopCruiseBtn", stopCruise);
  bind("ensureStandBtn", ensureStand);
  bind("stopMotionBtn", stopMotion);
  bind("auroraResetBtn", auroraReset);

  const poiSelect = $("poiSelect");
  if (poiSelect) {
    poiSelect.onchange = () => {
      selectedPoi = poiSelect.value;
      renderPoints();
      renderStatus();
    };
  }
  const search = $("pointSearch");
  if (search) {
    search.oninput = renderPoints;
  }
  const mapNameInput = $("mapName");
  if (mapNameInput) {
    mapNameInput.oninput = syncMapInputs;
  }
  const pathInput = $("mapPath");
  if (pathInput) {
    pathInput.oninput = syncMapInputs;
  }
  const clearResponse = $("clearResponseBtn");
  if (clearResponse) {
    clearResponse.onclick = () => { $("lastResponse").textContent = ""; };
  }
  const clearLog = $("clearLogBtn");
  if (clearLog) {
    clearLog.onclick = () => { $("operationLog").textContent = ""; };
  }
  const connectEventsBtn = $("connectEventsBtn");
  if (connectEventsBtn) {
    connectEventsBtn.onclick = connectEvents;
  }
}

function init() {
  setText("mappingRvizCommand", rvizCommands.mapping);
  setText("localizationRvizCommand", rvizCommands.localization);
  bindEvents();
  refresh(false);
  window.setInterval(() => refresh(false), 5000);
}

init();
