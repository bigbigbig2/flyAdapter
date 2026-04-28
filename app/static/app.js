const $ = (id) => document.getElementById(id);
let refreshing = false;
let lastPointsLoad = 0;
let eventSource = null;

async function api(path, options = {}) {
  const opts = {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
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
  if (options.updateLast !== false) {
    $("lastResponse").textContent = JSON.stringify(data, null, 2);
  }
  return data;
}

function setAdapter(ok, text) {
  $("adapterDot").className = "dot " + (ok ? "ok" : "bad");
  $("adapterText").textContent = text;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const status = await api("/robot/status", { updateLast: false });
    setAdapter(true, "online");
    $("namespace").textContent = status.adapter.namespace || "-";
    $("currentMap").textContent = status.runtime.current_map || "-";
    $("slamMode").textContent = status.runtime.slam_mode || "-";
    $("localization").textContent = status.runtime.localization_status || status.readiness.checks.localization_good;
    $("aurora").textContent = status.aurora.connected ? (status.aurora.standing ? "standing" : "connected") : "unavailable";
    $("cruise").textContent = status.runtime.is_cruising ? `${status.runtime.current_nav_index + 1}/${status.runtime.total_nav_points}` : "idle";
    $("readiness").textContent = JSON.stringify(status.readiness, null, 2);
    $("auroraState").textContent = JSON.stringify(status.aurora, null, 2);
    const now = Date.now();
    if (now - lastPointsLoad > 15000) {
      await loadPoints(false);
      lastPointsLoad = now;
    }
  } catch (error) {
    setAdapter(false, "offline");
    $("lastResponse").textContent = String(error);
  } finally {
    refreshing = false;
  }
}

async function loadPoints(updateLast = true) {
  const response = await fetch("/slam/nav_points");
  const data = await response.json();
  if (updateLast) $("lastResponse").textContent = JSON.stringify(data, null, 2);
  const list = $("pointsList");
  list.innerHTML = "";
  for (const point of data.nav_points || []) {
    const item = document.createElement("div");
    item.className = "point";
    const name = document.createElement("strong");
    name.textContent = point.name || "-";
    const coords = document.createElement("span");
    coords.textContent = `x=${Number(point.x).toFixed(2)}, y=${Number(point.y).toFixed(2)}`;
    item.appendChild(name);
    item.appendChild(coords);
    list.appendChild(item);
  }
}

async function loadMap() {
  await api("/robot/map/load", {
    method: "POST",
    body: {
      map_path: $("mapPath").value,
      x: Number($("initX").value),
      y: Number($("initY").value),
      yaw: Number($("initYaw").value),
      wait_for_localization: false,
    },
  });
  await refresh();
}

async function gotoPose() {
  await api("/slam/navigate_to", {
    method: "POST",
    body: {
      name: "debug_pose",
      x: Number($("gotoX").value),
      y: Number($("gotoY").value),
      yaw: Number($("gotoYaw").value),
    },
  });
}

function connectEvents() {
  const log = $("eventsLog");
  if (eventSource) {
    eventSource.close();
  }
  eventSource = new EventSource("/slam/events");
  log.textContent += "connected\n";
  eventSource.onmessage = (event) => {
    log.textContent += event.data + "\n";
    log.scrollTop = log.scrollHeight;
  };
  eventSource.onerror = () => {
    log.textContent += "event stream error\n";
  };
}

$("refreshBtn").onclick = refresh;
$("loadMapBtn").onclick = loadMap;
$("startMappingBtn").onclick = () => api("/slam/start_mapping", { method: "POST" }).then(refresh);
$("stopMappingBtn").onclick = () => api("/slam/stop_mapping", { method: "POST", body: { map_path: $("mapPath").value } }).then(refresh);
$("savePointBtn").onclick = () => api("/slam/add_nav_point", { method: "POST", body: { name: $("pointName").value } }).then(() => loadPoints());
$("reloadPointsBtn").onclick = () => loadPoints();
$("startCruiseBtn").onclick = () => api("/slam/start_cruise", { method: "POST" }).then(refresh);
$("pauseBtn").onclick = () => api("/slam/pause_nav", { method: "POST" }).then(refresh);
$("resumeBtn").onclick = () => api("/slam/resume_nav", { method: "POST" }).then(refresh);
$("stopCruiseBtn").onclick = () => api("/slam/stop_cruise", { method: "POST" }).then(refresh);
$("gotoBtn").onclick = gotoPose;
$("standBtn").onclick = () => api("/robot/aurora/ensure_stand", { method: "POST" }).then(refresh);
$("stopMotionBtn").onclick = () => api("/robot/aurora/stop_motion", { method: "POST" }).then(refresh);
$("connectEventsBtn").onclick = connectEvents;

refresh();
setInterval(refresh, 5000);
