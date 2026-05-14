const $ = (id) => document.getElementById(id);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const jsonHeaders = { "Content-Type": "application/json" };
const requestTimeoutMs = 12000;
const localizationWaitFloorMs = 45000;
const rvizCommands = {
  mapping:
    "cd ~/aurora_ws/flyAdapter || exit 1\n" +
    "source /opt/ros/humble/setup.bash\n" +
    "source /opt/fftai/humanoidnav/install/setup.bash\n" +
    "rviz2 -d rviz/mapping_GR301AA0025.rviz \\\n" +
    "  --ros-args \\\n" +
    "  -r tf:=/GR301AA0025/tf \\\n" +
    "  -r tf_static:=/GR301AA0025/tf_static",
  localization:
    "cd ~/aurora_ws/flyAdapter || exit 1\n" +
    "source /opt/ros/humble/setup.bash\n" +
    "source /opt/fftai/humanoidnav/install/setup.bash\n" +
    "rviz2 -d rviz/relocation_GR301AA0025.rviz \\\n" +
    "  --ros-args \\\n" +
    "  -r tf:=/GR301AA0025/tf \\\n" +
    "  -r tf_static:=/GR301AA0025/tf_static",
};

let refreshing = false;
let eventSource = null;
let selectedPoi = "";
let lastStatus = {};
let lastSlamStatus = {};
let lastPoints = [];
let lastPointIssues = { duplicateNames: [], duplicateCount: 0, counts: new Map() };
let currentPointBundle = {
  map_file: "",
  map_name: "",
  current_map: "",
  current_map_name: "",
  bundle_matches_current: false,
  initial_pose: {},
  visualization_topics: {},
  unitree_style: true,
};
let currentMapConfig = {
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
    const message = error.name === "AbortError" ? "请求超时" : String(error.message || error);
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

function responseMessage(data) {
  return data?.result?.message || data?.message || data?.error || data?.status || "";
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
    el.textContent = JSON.stringify(data, null, 2);
  }
}

function setHtml(id, html) {
  const el = $(id);
  if (el) {
    el.innerHTML = html;
  }
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

function logOperation(title, data) {
  const log = $("operationLog");
  if (!log) {
    return;
  }
  const now = new Date().toLocaleTimeString();
  const mark = resultOk(data) ? "OK" : "CHECK";
  const detail = responseMessage(data);
  log.textContent += `[${now}] ${mark} ${title}${detail ? ` - ${detail}` : ""}\n`;
  const lines = log.textContent.split("\n");
  if (lines.length > 240) {
    log.textContent = lines.slice(-220).join("\n");
  }
  log.scrollTop = log.scrollHeight;
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

function setNotice(id, state, text) {
  const el = $(id);
  if (!el) {
    return;
  }
  if (!text) {
    el.className = "notice hidden";
    el.textContent = "";
    return;
  }
  el.className = `notice ${state || ""}`.trim();
  el.textContent = text;
}

function setActionHint(id, state, text) {
  const el = $(id);
  if (!el) {
    return;
  }
  el.className = `action-hint ${state || ""}`.trim();
  el.textContent = text || "-";
}

function activeStep(step) {
  $$(".step").forEach((item) => item.classList.toggle("active", item.dataset.step === step));
  $$(".step-panel").forEach((item) => item.classList.toggle("active", item.dataset.panel === step));
}

function configuredMapName() {
  return $("mapName")?.value.trim() || currentMapConfig.default_map_name || "map";
}

function explicitMapPath() {
  return $("mapPath")?.value.trim() || "";
}

function joinMapPath(root, name) {
  const cleanRoot = String(root || "/opt/fftai/nav").replace(/[\\/]+$/, "");
  const cleanName = String(name || "map").replace(/^[\\/]+|[\\/]+$/g, "");
  return `${cleanRoot}/${cleanName}`;
}

function configuredMapPath() {
  return explicitMapPath() || joinMapPath(currentMapConfig.map_root, configuredMapName());
}

function currentMapPayload() {
  const payload = {};
  const path = explicitMapPath();
  const name = configuredMapName();
  if (path) {
    payload.map_path = path;
  } else if (name) {
    payload.map_name = name;
  }
  return payload;
}

function mapOperationTimeoutMs(value) {
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Math.max(requestTimeoutMs, (seconds + 2) * 1000);
  }
  return requestTimeoutMs;
}

function mapSaveTimeoutMs() {
  return mapOperationTimeoutMs(currentMapConfig.save_timeout_sec);
}

function mapLoadTimeoutMs() {
  return mapOperationTimeoutMs(currentMapConfig.load_timeout_sec);
}

function localizationWaitTimeoutMs() {
  return Math.max(localizationWaitFloorMs, mapLoadTimeoutMs());
}

function syncMapControls(mapConfig = {}) {
  currentMapConfig = { ...currentMapConfig, ...mapConfig };
  const mapNameInput = $("mapName");
  const mapPathInput = $("mapPath");
  if (mapNameInput && !mapNameInput.value.trim() && document.activeElement !== mapNameInput) {
    mapNameInput.value = currentMapConfig.current_map_name || currentMapConfig.default_map_name || "map";
  }
  if (mapPathInput && document.activeElement !== mapPathInput) {
    mapPathInput.placeholder = `留空则使用 ${joinMapPath(currentMapConfig.map_root, configuredMapName())}`;
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

function bundlePoseBody() {
  const pose = currentPointBundle.initial_pose || {};
  const hasPose = ["x", "y", "z", "yaw"].some((key) => pose[key] !== undefined && pose[key] !== null && pose[key] !== "");
  if (!hasPose) {
    return poseBody();
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

function basenameFromPath(path) {
  const value = String(path || "").trim().replace(/[\\/]+$/, "");
  if (!value) {
    return "";
  }
  const parts = value.split(/[\\/]/);
  return parts[parts.length - 1] || "";
}

function loadedMapPath() {
  return (
    lastStatus.runtime?.current_map ||
    currentMapConfig.current_map ||
    lastSlamStatus.map_file ||
    ""
  );
}

function loadedMapName() {
  return (
    currentMapConfig.current_map_name ||
    lastStatus.runtime?.current_map_name ||
    basenameFromPath(loadedMapPath())
  );
}

function bundleMapPath() {
  return currentPointBundle.map_file || "";
}

function bundleMapName() {
  return currentPointBundle.map_name || basenameFromPath(bundleMapPath());
}

function bundleMatchesCurrent() {
  const bundle = bundleMapPath();
  const current = loadedMapPath();
  if (!bundle || !current) {
    return false;
  }
  return bundle === current;
}

function pointReadiness() {
  return lastStatus.poi_readiness || lastSlamStatus.poi_readiness || {};
}

function mappingReadiness() {
  return lastStatus.mapping_readiness || lastSlamStatus.mapping_readiness || {};
}

function navigationReadiness() {
  return lastStatus.navigation_readiness || lastStatus.readiness || {};
}

function motionAuthority() {
  return lastStatus.motion_authority || lastStatus.workflow?.motion_authority || {};
}

function formatAge(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  return `${parsed.toFixed(1)}s`;
}

function nextActionText() {
  const slamMode = lastStatus.runtime?.slam_mode || lastSlamStatus.slam_mode || "-";
  const mapReady = Boolean(mappingReadiness().ready || lastSlamStatus.ready_for_mapping);
  const poiReady = Boolean(pointReadiness().ready || lastSlamStatus.ready_for_poi);
  const navReady = Boolean(navigationReadiness().ready);
  const hasPoints = lastPoints.length > 0;
  const current = loadedMapPath();
  const bundle = bundleMapPath();

  if (slamMode === "mapping") {
    return mapReady ? "可以继续手动建图，结束时用“停止建图并保存”落盘地图。" : "先确认 ROS、位姿和手动控制链路，再开始建图。";
  }
  if (!current) {
    return "先加载地图。只想切到定位模式时用“仅加载地图”，要等定位稳定再打点或导航时用“加载并等待定位稳定”。";
  }
  if (bundle && current !== bundle) {
    return "当前加载地图和点位文件绑定地图不一致。先用“按点位文件加载地图并定位”再导航。";
  }
  if (!poiReady) {
    return "地图已加载，但定位还没稳。等定位 readiness 变好后再打点。";
  }
  if (!hasPoints) {
    return "定位已经可用，可以先保存 POI。";
  }
  if (!navReady) {
    return "点位文件已就绪，但自动导航还没 ready。先看 readiness 阻塞项。";
  }
  return "当前可以做单点导航或开始巡航。";
}

function selectedPoiRecord() {
  return lastPoints.find((point) => point.name === selectedPoi) || null;
}

function renderFlowCards() {
  const current = loadedMapPath();
  const bundle = bundleMapPath();
  const mapReady = Boolean(mappingReadiness().ready || lastSlamStatus.ready_for_mapping);
  const poiReady = Boolean(pointReadiness().ready || lastSlamStatus.ready_for_poi);
  const navReady = Boolean(navigationReadiness().ready);
  const hasPoints = lastPoints.length > 0;

  setText("flowMappingStatus", mapReady ? "可以开始建图" : blockerText(mappingReadiness()));
  setText("flowLocalizationStatus", current ? (poiReady ? "已加载，可继续打点" : "地图已加载，等待定位稳定") : "还没加载地图");
  setText(
    "flowNavigationStatus",
    !hasPoints
      ? "还没有点位文件"
      : !bundleMatchesCurrent()
        ? "点位文件和当前地图不一致"
        : navReady
          ? "可以导航"
          : blockerText(navigationReadiness())
  );
  setText("nextAction", nextActionText());
}

function renderStatus(status = {}, slamStatus = {}) {
  const runtime = status.runtime || {};
  const mapping = mappingReadiness();
  const poi = pointReadiness();
  const navigation = navigationReadiness();
  const ros = status.ros || {};
  const aurora = status.aurora || {};
  const motion = motionAuthority();
  const namespace = status.adapter?.namespace || status.namespace || ros.namespace || "-";
  const mapConfig = status.map_config || slamStatus.map_config || {};
  const slamMode = runtime.slam_mode || slamStatus.slam_mode || "-";
  const currentMap = runtime.current_map || mapConfig.current_map || slamStatus.map_file || "-";
  const currentMapName = mapConfig.current_map_name || basenameFromPath(currentMap) || "-";
  const isCruising = Boolean(runtime.is_cruising || slamStatus.is_cruising);
  const isPaused = Boolean(runtime.is_paused || slamStatus.is_paused);
  const poseAge = runtime.pose_age_sec ?? slamStatus.pose_age_sec;
  const navTask = runtime.navigation_task || {};
  const mapReady = Boolean(mapping.ready || slamStatus.ready_for_mapping);
  const poiReady = Boolean(poi.ready || slamStatus.ready_for_poi);
  const navReady = Boolean(navigation.ready);
  const lastError = slamStatus.last_error || status.last_error || status.error || "";

  syncMapControls(mapConfig);
  setAdapter(true, "online");
  setText("namespaceLabel", namespace);
  setText("rosStatus", ros.ready ? "ready" : "not ready");
  setText("motionStatus", `${motion.policy || "none"} / ${motion.authority || "external"}`);
  setText("slamStatus", slamMode);
  setText("navigationReady", boolText(navReady));
  setText("currentMap", currentMap);
  setText("currentMapName", currentMapName);
  setText("poseAge", formatAge(poseAge));
  setText("navTask", isCruising ? (isPaused ? "paused" : "cruising") : (navTask.status || "idle"));

  setText("checkAdapter", "online");
  setText("checkRos", ros.ready ? "ready" : (ros.error || "not ready"));
  setText("checkMapping", readyWord(mapping));
  setText("checkPoi", readyWord(poi));
  setText("checkNavigation", readyWord(navigation));
  setText("checkAurora", aurora.connected ? (aurora.standing ? "standing" : "connected") : (aurora.error || "optional"));
  setText("checkBody", motion.authority || "external");
  setText("healthLine", lastError ? `最近错误: ${lastError}` : nextActionText());
  setText("opsCurrentMap", currentMap === "-" ? "未加载" : currentMap);
  setText("opsBundleMap", bundleMapPath() || "未绑定点位文件");
  setText("opsPoseState", poiReady ? "定位稳定，可打点" : blockerText(poi));
  setText("opsActionState", nextActionText());

  setText("mappingModeCheck", mapping.checks?.mapping_mode ? "mapping" : slamMode);
  setText("mappingPoseCheck", statusWord(mapping.checks?.pose_fresh));
  setText("mappingHealthCheck", statusWord(mapping.checks?.health_ok));
  setText("mappingControlSource", mapping.checks?.motion_source || "remote_or_joystick");

  setJson("readinessBox", {
    map_config: currentMapConfig,
    motion_authority: motion,
    mapping_readiness: mapping,
    poi_readiness: poi,
    navigation_readiness: navigation,
    aurora,
    ros,
  });
  setJson("mappingBox", {
    target_map: configuredMapPath(),
    current_map: currentMap,
    slam_mode: slamMode,
    mapping_readiness: mapping,
  });
  setJson("localizationBox", {
    target_map: configuredMapPath(),
    current_map: currentMap,
    current_map_name: currentMapName,
    localization_status: slamStatus.localization_status,
    odom_status_code: runtime.odom_status_code ?? slamStatus.odom_status_code,
    odom_status_score: runtime.odom_status_score ?? slamStatus.odom_status_score,
    poi_readiness: poi,
    navigation_readiness: navigation,
  });
  setJson("cruiseBox", {
    is_cruising: isCruising,
    is_paused: isPaused,
    current_nav_index: runtime.current_nav_index ?? slamStatus.current_nav_index,
    total_nav_points: runtime.total_nav_points ?? slamStatus.total_nav_points,
    current_target: runtime.current_target,
    task: navTask,
  });

  setBadge("mappingHint", mapReady ? "ok" : "warn", mapReady ? "建图链路可用" : blockerText(mapping));
  setBadge("localizationHint", poiReady ? "ok" : "warn", poiReady ? "定位稳定，可打点" : blockerText(poi));
  setBadge("pointsHint", lastPoints.length ? (lastPointIssues.duplicateNames.length ? "warn" : "ok") : "warn", `${lastPoints.length} 个点位`);
  setBadge("verifyHint", navReady ? "ok" : "warn", navReady ? "可以导航" : blockerText(navigation));
  setBadge("cruiseHint", isCruising ? "ok" : "warn", isCruising ? (isPaused ? "巡航暂停" : "巡航运行中") : "未开始");

  setText("stepCheckState", ros.ready ? "通过" : "待处理");
  setText("stepMappingState", mapReady ? "可建图" : blockerText(mapping));
  setText("stepLocalizationState", poiReady ? "可打点" : blockerText(poi));
  setText("stepPointsState", `${lastPoints.length} 个点位`);
  setText("stepVerifyState", selectedPoi || "待选择");
  setText("stepCruiseState", isCruising ? (isPaused ? "已暂停" : "运行中") : "待启动");
  setText("stepAcceptanceState", navReady ? "可验收" : "待准备");

  setText("saveNote", `目标地图: ${configuredMapPath()}`);
  setText("cruiseSummary", isCruising ? `当前索引 ${(runtime.current_nav_index ?? 0) + 1} / ${runtime.total_nav_points || 0}` : "未启动");
  setText("localizationSummary", currentMap === "-" ? "当前未加载地图" : `当前地图: ${currentMapName}`);

  setNotice(
    "localizationNotice",
    poiReady ? "ok" : "warn",
    poiReady
      ? "定位已经稳定，可以安全打点。"
      : "打点前先让定位 readiness 变好。否则点可能记在错误位姿上，后面导航就会出现超出地图范围。"
  );

  setActionHint(
    "localizationActionHint",
    poiReady ? "ok" : "warn",
    poiReady
      ? "地图已加载且定位稳定。现在适合打点，或者直接做单点验证。"
      : "如果只是切到 localization 看图，用“仅加载地图”；如果后面要打点或导航，优先用“加载并等待定位稳定”。"
  );

  renderFlowCards();
  updateControls();
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
    if (statusResult.status === "rejected" && slamResult.status === "rejected") {
      throw statusResult.reason || slamResult.reason || new Error("status unavailable");
    }

    renderStatus(lastStatus, lastSlamStatus);
    if (statusResult.status === "rejected" || slamResult.status === "rejected") {
      const failed = [
        statusResult.status === "rejected" ? `/robot/status: ${statusResult.reason?.message || statusResult.reason}` : "",
        slamResult.status === "rejected" ? `/slam/status: ${slamResult.reason?.message || slamResult.reason}` : "",
      ].filter(Boolean);
      setAdapter(true, "partial");
      setText("healthLine", `部分状态接口异常: ${failed.join("; ")}`);
    }
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
    renderPointBundle();
  }
}

async function loadPoints(updateLast = true) {
  const data = await api("/slam/nav_points", { updateLast, log: updateLast });
  lastPoints = normalizePoints(data.nav_points || data.points || []);
  currentPointBundle = {
    map_file: data.map_file || "",
    map_name: data.map_name || "",
    current_map: data.current_map || "",
    current_map_name: data.current_map_name || "",
    bundle_matches_current: Boolean(data.bundle_matches_current),
    initial_pose: data.initial_pose || {},
    visualization_topics: data.visualization_topics || {},
    unitree_style: data.unitree_style !== false,
  };
  lastPointIssues = analyzePoints(lastPoints);
  renderPoints(lastPoints);
  updatePointSummary();
  renderPointBundle();
  updateControls();
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
  setText("pointsSummary", duplicateNames.length ? `${count} 个点位，存在重名` : `${count} 个点位`);
  setText("stepPointsState", `${count} 个点位`);
  setBadge("pointsHint", count ? (duplicateNames.length ? "warn" : "ok") : "warn", `${count} 个点位`);
  setNotice(
    "duplicateNotice",
    "warn",
    duplicateNames.length
      ? `检测到同名点位: ${duplicateNames.join(", ")}。按名称导航时只会命中第一个匹配点，建议覆盖保存或删掉重名点。`
      : ""
  );
}

function renderPointBundle() {
  const topics = currentPointBundle.visualization_topics || {};
  const current = loadedMapPath() || currentPointBundle.current_map || "";
  const currentName = loadedMapName() || currentPointBundle.current_map_name || "-";
  const bundle = bundleMapPath() || "-";
  const bundleNameValue = bundleMapName() || "-";
  const match = bundleMatchesCurrent();
  const initial = bundlePoseBody();
  const rawInitial = currentPointBundle.initial_pose || {};
  const hasInitial = ["x", "y", "z", "yaw"].some((key) => rawInitial[key] !== undefined && rawInitial[key] !== null && rawInitial[key] !== "");
  const topicText = [topics.nav_points, topics.current_goal, topics.cruise_path].filter(Boolean).join(" / ") || "-";

  setText("pointBundleStyle", currentPointBundle.unitree_style ? "Unitree navigation_points.json" : "custom");
  setText("pointBundleMap", bundle);
  setText("pointBundleName", bundleNameValue);
  setText("pointBundleCurrentMap", current || "-");
  setText("pointBundleCurrentName", currentName);
  setText("pointBundleInitialPose", hasInitial ? `x=${num(initial.x)}, y=${num(initial.y)}, yaw=${num(initial.yaw)}` : "未保存，使用定位输入框");
  setText("pointBundleTopics", topicText);
  setBadge("bundleMatchBadge", match ? "ok" : "warn", match ? "地图一致" : "地图不一致");

  setNotice(
    "bundleNotice",
    match ? "ok" : "warn",
    bundle === "-"
      ? "当前没有读取到点位文件。先加载或保存点位文件。"
      : match
        ? "点位文件和当前加载地图一致，可以继续单点导航或巡航。"
        : `点位文件绑定地图是 ${bundle}，当前底层加载的是 ${current || "未加载"}。导航前先点“按点位文件加载地图并定位”。`
  );

  setNotice(
    "navigationNotice",
    (!lastPoints.length || match) ? "ok" : "warn",
    !lastPoints.length
      ? "还没有点位，先去打点。"
      : match
        ? "当前地图和点位文件一致，可以做单点验证。"
        : "当前地图与点位文件不一致，页面会优先阻止直接导航。"
  );
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
    renderSelectedPoiMeta();
    return;
  }

  if (!filtered.length) {
    list.appendChild(emptyPoint("没有匹配点位"));
  }

  for (const point of filtered) {
    const duplicate = (counts.get(point.name) || 0) > 1;
    const item = document.createElement("div");
    item.className = `point ${duplicate ? "duplicate" : ""} ${selectedPoi === point.name ? "selected" : ""}`.trim();
    item.onclick = () => selectPoi(point.name);

    const title = document.createElement("strong");
    title.textContent = duplicate ? `${point.name}（重名）` : point.name;

    const coords = document.createElement("span");
    const mapText = point.map_name ? ` / map=${point.map_name}` : "";
    coords.textContent = `x=${num(point.x)}, y=${num(point.y)}, yaw=${num(point.yaw)} / ${point.frame_id}${mapText}`;

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
    const count = counts.get(name) || 0;
    const label = count > 1 ? `${name}（重名 ${count}）` : name;
    select.appendChild(new Option(label, name));
  }

  if (!selectedPoi || !uniqueNames.includes(selectedPoi)) {
    selectedPoi = uniqueNames[0] || "";
  }
  select.value = selectedPoi;
  const selectedDuplicate = (counts.get(selectedPoi) || 0) > 1;
  setBadge("verifyHint", selectedPoi ? (selectedDuplicate ? "warn" : "ok") : "warn", selectedPoi || "待选择");
  setText("verifySummary", selectedPoi ? `目标: ${selectedPoi}` : "未选择目标");
  renderSelectedPoiMeta();
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
  setText("verifySummary", `目标: ${name}`);
  setText("stepVerifyState", name);
  renderSelectedPoiMeta();
  renderPoints(lastPoints);
  activeStep("verify");
  updateControls();
}

function renderSelectedPoiMeta() {
  const point = selectedPoiRecord();
  if (!point) {
    setText("selectedPoiMeta", "未选择");
    return;
  }
  const mapText = point.map_name || bundleMapName() || loadedMapName() || "-";
  setText(
    "selectedPoiMeta",
    `${point.name} / x=${num(point.x)}, y=${num(point.y)}, yaw=${num(point.yaw)} / map=${mapText}`
  );
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
  if (!window.confirm("停止建图并调用 save_map 保存当前地图？")) {
    return;
  }
  const result = await api("/slam/stop_mapping", {
    method: "POST",
    body: currentMapPayload(),
    timeoutMs: mapSaveTimeoutMs(),
  });
  if (resultOk(result)) {
    await api("/slam/set_map_path", {
      method: "POST",
      body: currentMapPayload(),
      updateLast: false,
      log: false,
    });
  }
  await refresh(false);
}

async function saveMap() {
  if (!window.confirm("重新调用 save_map 保存当前地图？")) {
    return;
  }
  const result = await api("/robot/map/save", {
    method: "POST",
    body: currentMapPayload(),
    timeoutMs: mapSaveTimeoutMs(),
  });
  if (resultOk(result)) {
    await api("/slam/set_map_path", {
      method: "POST",
      body: currentMapPayload(),
      updateLast: false,
      log: false,
    });
  }
  await refresh(false);
}

async function setMapPathOnly() {
  await api("/slam/set_map_path", {
    method: "POST",
    body: currentMapPayload(),
  });
  await refresh(false);
}

async function listMaps() {
  const data = await api("/robot/map/list");
  setJson("mapListBox", data);
}

async function loadMapOnly() {
  await api("/slam/relocation", {
    method: "POST",
    body: {
      ...currentMapPayload(),
      ...poseBody(),
      wait_for_localization: false,
    },
    timeoutMs: mapLoadTimeoutMs(),
  });
  await refresh(false);
  activeStep("localization");
}

async function loadMapAndWait() {
  await api("/slam/relocation", {
    method: "POST",
    body: {
      ...currentMapPayload(),
      ...poseBody(),
      wait_for_localization: true,
    },
    timeoutMs: localizationWaitTimeoutMs(),
  });
  await refresh(false);
  activeStep("localization");
}

async function loadBundleMap() {
  if (!bundleMapPath()) {
    setJson("lastResponse", { success: false, message: "当前没有点位文件绑定地图" });
    return;
  }
  const pose = bundlePoseBody();
  await api("/slam/relocation", {
    method: "POST",
    body: {
      map_path: bundleMapPath(),
      x: pose.x,
      y: pose.y,
      z: pose.z,
      yaw: pose.yaw,
      wait_for_localization: true,
    },
    timeoutMs: localizationWaitTimeoutMs(),
  });
  await refresh(false);
  activeStep("verify");
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

async function publishPointVisuals() {
  const data = await api("/robot/visualization/nav_points", { method: "POST" });
  setJson("lastResponse", data);
}

async function reloadPointBundle() {
  await api("/slam/load_nav_points", { method: "POST" });
  await loadPoints(false);
  await refresh(false);
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
  const suffix = count > 1 ? `（会删除 ${count} 个同名点）` : "";
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
  const motion = workflow.motion_authority || motionAuthority();
  const aurora = workflow.aurora || status.aurora || {};
  const mapping = workflow.manual_mapping || status.mapping_readiness || {};
  const poi = workflow.manual_poi || status.poi_readiness || {};
  const navigation = workflow.auto_navigation || status.readiness || {};
  const normalizedPoints = normalizePoints(points.nav_points || points.points || []);
  const issues = analyzePoints(normalizedPoints);
  const bundlePathValue = points.map_file || "";
  const currentPathValue = points.current_map || status.runtime?.current_map || "";
  const bundleOk = Boolean(bundlePathValue && currentPathValue && bundlePathValue === currentPathValue);
  const checks = [
    ["Adapter", Boolean(health.ok), health.namespace || health.error || ""],
    ["ROS", Boolean(status.ros?.ready), status.ros?.error || "ready"],
    ["运动策略", true, `${motion.policy || "none"} / ${motion.authority || "external"}`],
    ["Aurora", !motion.aurora_required || Boolean(aurora.connected), motion.aurora_required ? (aurora.standing ? "standing" : "required") : "optional"],
    ["当前地图", Boolean(currentPathValue), currentPathValue || "-"],
    ["建图 readiness", Boolean(mapping.ready), blockerText(mapping)],
    ["打点 readiness", Boolean(poi.ready), blockerText(poi)],
    ["点位数量", normalizedPoints.length > 0, `${normalizedPoints.length} 个点位`],
    ["点位唯一性", issues.duplicateNames.length === 0, issues.duplicateNames.length ? issues.duplicateNames.join(", ") : "ok"],
    ["点位地图绑定", bundleOk, bundleOk ? bundlePathValue : `${bundlePathValue || "-"} / ${currentPathValue || "-"}`],
    ["导航 readiness", Boolean(navigation.ready), blockerText(navigation)],
  ];
  renderAcceptance(checks);
  const passed = checks.every(([, ok]) => ok);
  setJson("acceptanceBox", {
    health,
    workflow,
    status,
    points,
    point_issues: issues,
  });
  setText("acceptanceSummary", passed ? "全部通过" : "存在待处理项");
  setText("stepAcceptanceState", passed ? "通过" : "待处理");
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
    setJson("lastResponse", { success: true, message: "命令已复制", command: text });
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
  const poiReady = Boolean(pointReadiness().ready || lastSlamStatus.ready_for_poi);
  const navReady = Boolean(navigationReadiness().ready);
  const runtime = lastStatus.runtime || {};
  const isCruising = Boolean(runtime.is_cruising || lastSlamStatus.is_cruising);
  const isPaused = Boolean(runtime.is_paused || lastSlamStatus.is_paused);
  const forceNav = Boolean($("forceNav")?.checked);
  const forceCruise = Boolean($("forceCruise")?.checked);
  const mapAligned = !bundleMapPath() || bundleMatchesCurrent();
  const pointName = $("pointName")?.value.trim() || "";
  const hasBundleMap = Boolean(bundleMapPath());
  const currentMapLoaded = Boolean(loadedMapPath());
  const selectedPoint = selectedPoiRecord();

  setDisabled("savePointBtn", !pointName || !poiReady);
  setDisabled("savePointsFileBtn", !hasPoints);
  setDisabled("publishPointVisualsBtn", !hasPoints);
  setDisabled("reloadPointsBtn", false);
  setDisabled("clearPointsBtn", !hasPoints);
  setDisabled("loadBundleMapBtn", !hasBundleMap);
  setDisabled("gotoPoiBtn", !selectedPoi || ((!navReady || !mapAligned) && !forceNav));
  setDisabled("startCruiseBtn", !hasPoints || isCruising || ((!navReady || !mapAligned) && !forceCruise));
  setDisabled("pauseBtn", !isCruising || isPaused);
  setDisabled("resumeBtn", !isCruising || !isPaused);
  setDisabled("stopCruiseBtn", !isCruising);

  setActionHint(
    "pointActionHint",
    poiReady ? "ok" : "warn",
    poiReady
      ? "当前位置位姿可用，保存点位会直接绑定到当前真实加载地图。"
      : "定位还没稳，暂不建议保存点位。等打点 readiness 变好再保存，能避开“点超出地图范围”的脏数据。"
  );

  let navHint = "先选一个点位。";
  let navState = "warn";
  if (selectedPoint) {
    if (!currentMapLoaded) {
      navHint = "还没加载地图。先去定位面板加载地图。";
    } else if (!mapAligned && !forceNav) {
      navHint = "点位文件地图和当前加载地图不一致。先按点位文件加载地图并定位。";
    } else if (!navReady && !forceNav) {
      navHint = `自动导航还没 ready：${blockerText(navigationReadiness())}`;
    } else {
      navState = "ok";
      navHint = forceNav
        ? "将按强制模式下发导航。注意先确认当前地图和环境一致。"
        : "当前点位与地图关系正常，可以做单点验证。";
    }
  }
  setActionHint("navActionHint", navState, navHint);

  let cruiseHint = "至少需要一组可用点位。";
  let cruiseState = "warn";
  if (isCruising) {
    cruiseState = "ok";
    cruiseHint = isPaused ? "巡航已暂停，可以恢复或停止。" : "巡航运行中，留意事件流和当前目标。";
  } else if (hasPoints) {
    if (!mapAligned && !forceCruise) {
      cruiseHint = "点位文件地图与当前加载地图不一致，暂不建议直接开始巡航。";
    } else if (!navReady && !forceCruise) {
      cruiseHint = `自动导航还没 ready：${blockerText(navigationReadiness())}`;
    } else {
      cruiseState = "ok";
      cruiseHint = forceCruise
        ? "将按强制模式开始巡航。确认路径和地图一致后再执行。"
        : "点位和地图关系正常，可以开始巡航。";
    }
  }
  setActionHint("cruiseActionHint", cruiseState, cruiseHint);
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

  bindAction("flowMappingBtn", async () => activeStep("mapping"));
  bindAction("flowLocalizationBtn", async () => activeStep("localization"));
  bindAction("flowNavigationBtn", async () => activeStep("verify"));

  bindAction("startMappingBtn", startMapping);
  bindAction("mappingStatusBtn", () => refresh(true));
  bindAction("copyMappingRvizBtn", () => copyText(rvizCommands.mapping));
  bindAction("stopMappingBtn", stopMapping);
  bindAction("saveMapBtn", saveMap);
  bindAction("setMapPathBtn", setMapPathOnly);
  bindAction("listMapsBtn", listMaps);

  bindAction("loadMapOnlyBtn", loadMapOnly);
  bindAction("loadMapWaitBtn", loadMapAndWait);
  bindAction("loadBundleMapBtn", loadBundleMap);
  bindAction("initialPoseBtn", publishInitialPose);
  bindAction("localizationStatusBtn", () => refresh(true));
  bindAction("copyLocalizationRvizBtn", () => copyText(rvizCommands.localization));

  bindAction("savePointBtn", savePoint);
  bindAction("savePointsFileBtn", savePointsFile);
  bindAction("publishPointVisualsBtn", publishPointVisuals);
  bindAction("reloadPointsBtn", reloadPointBundle);
  bindAction("clearPointsBtn", clearPoints);

  bindAction("gotoPoiBtn", () => gotoPoi());
  bindAction("cancelNavBtn", cancelNavigation);
  bindAction("currentActionBtn", currentAction);

  bindAction("startCruiseBtn", startCruise);
  bindAction("pauseBtn", pauseCruise);
  bindAction("resumeBtn", resumeCruise);
  bindAction("stopCruiseBtn", stopCruise);

  bindAction("runAcceptanceBtn", runAcceptance);

  const connectEventsBtn = $("connectEventsBtn");
  if (connectEventsBtn) {
    connectEventsBtn.onclick = connectEvents;
  }

  const poiSelect = $("poiSelect");
  if (poiSelect) {
    poiSelect.onchange = () => selectPoi(poiSelect.value);
  }
  const pointSearch = $("pointSearch");
  if (pointSearch) {
    pointSearch.oninput = () => renderPoints(lastPoints);
  }
  const pointNameInput = $("pointName");
  if (pointNameInput) {
    pointNameInput.oninput = updateControls;
  }
  const mapNameInput = $("mapName");
  if (mapNameInput) {
    mapNameInput.oninput = () => {
      syncMapControls();
      setText("saveNote", `目标地图: ${configuredMapPath()}`);
      renderPointBundle();
    };
  }
  const mapPathInput = $("mapPath");
  if (mapPathInput) {
    mapPathInput.oninput = () => {
      setText("saveNote", `目标地图: ${configuredMapPath()}`);
      renderPointBundle();
    };
  }
  const forceNav = $("forceNav");
  if (forceNav) {
    forceNav.onchange = updateControls;
  }
  const forceCruise = $("forceCruise");
  if (forceCruise) {
    forceCruise.onchange = updateControls;
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

function initStaticText() {
  setText("mappingRvizCommand", rvizCommands.mapping);
  setText("localizationRvizCommand", rvizCommands.localization);
}

bindEvents();
initStaticText();
refresh(false);
window.setInterval(() => refresh(false), 5000);
