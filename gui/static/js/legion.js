const $ = (id) => document.getElementById(id);

const FIELDS = {
  wifi: [
    ["ssid", "SSID"],
    ["bssid", "BSSID / MAC"],
    ["oui", "OUI"],
  ],
  ble: [
    ["address", "MAC address"],
    ["local_name", "Local name"],
    ["service_uuid", "Service UUID"],
    ["manufacturer_id", "Manufacturer ID"],
    ["oui", "OUI"],
  ],
  bt_classic: [
    ["address", "MAC address"],
    ["device_name", "Device name"],
    ["local_name", "Local name"],
    ["oui", "OUI"],
  ],
};

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2800);
}

function clock() {
  const now = new Date().toISOString().slice(11, 19);
  $("pill-clock").textContent = `${now}Z`;
}

async function getJSON(url) {
  const res = await fetch(url);
  return res.json();
}

async function sendJSON(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

const postJSON = (url, body) => sendJSON(url, "POST", body);

function confirmAction(title, body) {
  return new Promise((resolve) => {
    $("modal-title").textContent = title;
    $("modal-body").textContent = body;
    $("modal").classList.add("show");
    const yes = () => { cleanup(); resolve(true); };
    const no = () => { cleanup(); resolve(false); };
    function cleanup() {
      $("modal").classList.remove("show");
      $("modal-yes").removeEventListener("click", yes);
      $("modal-no").removeEventListener("click", no);
    }
    $("modal-yes").addEventListener("click", yes);
    $("modal-no").addEventListener("click", no);
  });
}

function wifiLabel(row) {
  if (!row.reachable) return "unreachable";
  if (!row.wifi_connected) return "disconnected";
  const band = row.wifi_band || "";
  const pretty = band.replace("ghz", " GHz").replace("2.4", "2.4");
  if (row.wifi_rssi_dbm != null) return `${pretty} / ${row.wifi_rssi_dbm} dBm`;
  return pretty || "connected";
}

let FLEET = { zones: [], cohorts: [], sentinels: [], audit: [] };

function badge(text, cls) {
  return `<span class="badge ${cls}">${text}</span>`;
}

function healthOf(sentinel) {
  return sentinel.health || {};
}

function renderOverview(data) {
  const p = data.presence || {};
  $("pill-count").textContent = `FLEET · ${data.sentinels_total || 0}`;
  $("fleet-stats").innerHTML = [
    ["SENTINELS", data.sentinels_total || 0],
    ["ONLINE", p.online || 0],
    ["DEGRADED", p.degraded || 0],
    ["OFFLINE", p.offline || 0],
    ["DORMANT", p.dormant || 0],
    ["UNKNOWN", p.unknown || 0],
    ["ZONES", data.zones_total || 0],
    ["COHORTS", data.cohorts_total || 0],
  ].map(([label, value]) => `<div class="card"><h3>${label}</h3><div class="meta">${value}</div></div>`).join("");
  const zoneSel = $("filter-zone");
  const current = zoneSel.value;
  zoneSel.innerHTML = '<option value="">All Zones</option>' + (data.zones || []).map((z) =>
    `<option value="${z.zone_id}">${z.name}</option>`
  ).join("");
  zoneSel.value = current;
  const stateSel = $("filter-state");
  if (!stateSel.dataset.ready) {
    ["online", "degraded", "offline", "dormant", "unknown", "nominal", "understrength", "reinforced"].forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      stateSel.appendChild(opt);
    });
    stateSel.dataset.ready = "1";
  }
}

function renderTree(data) {
  const q = ($("fleet-search").value || "").toLowerCase();
  const zoneFilter = $("filter-zone").value;
  const stateFilter = $("filter-state").value;
  const zones = data.zones || [];
  const cohorts = data.cohorts || [];
  const sentinels = data.sentinels || [];
  function matchSentinel(s) {
    const blob = `${s.sentinel_id} ${s.display_name || ""} ${s.zone_name || ""} ${s.cohort_name || ""} ${s.profile_id || ""}`.toLowerCase();
    if (q && !blob.includes(q)) return false;
    if (zoneFilter && s.zone_id !== zoneFilter) return false;
    if (stateFilter && s.presence !== stateFilter && true) {
      const cohort = cohorts.find((c) => c.cohort_id === s.cohort_id);
      if (stateFilter && s.presence !== stateFilter && (!cohort || cohort.readiness !== stateFilter)) return false;
    }
    return true;
  }
  let html = "";
  zones.forEach((zone) => {
    if (zoneFilter && zone.zone_id !== zoneFilter) return;
    html += `<div class="tree-zone" data-kind="zone" data-id="${zone.zone_id}">ZONE // ${zone.name} ${badge(zone.coverage, zone.coverage)}</div>`;
    cohorts.filter((c) => c.zone_id === zone.zone_id).forEach((cohort) => {
      html += `<div class="tree-cohort" data-kind="cohort" data-id="${cohort.cohort_id}">COHORT // ${cohort.display_name} ${badge(cohort.readiness, cohort.readiness)} ${cohort.roster_label}</div>`;
      sentinels.filter((s) => s.cohort_id === cohort.cohort_id && matchSentinel(s)).forEach((s) => {
        const primus = s.role === "Primus" ? badge("PRIMUS", "primus") : "";
        html += `<div class="tree-sentinel" data-kind="sentinel" data-id="${s.sentinel_id}">${s.sentinel_id} ${badge(s.presence, s.presence)} ${primus}</div>`;
      });
    });
  });
  const unassignedCohorts = cohorts.filter((c) => !c.zone_id);
  if (unassignedCohorts.length) {
    html += `<div class="tree-zone">UNASSIGNED COHORTS</div>`;
    unassignedCohorts.forEach((cohort) => {
      html += `<div class="tree-cohort" data-kind="cohort" data-id="${cohort.cohort_id}">COHORT // ${cohort.display_name} ${badge(cohort.readiness, cohort.readiness)}</div>`;
    });
  }
  const loose = sentinels.filter((s) => !s.cohort_id && matchSentinel(s));
  if (loose.length) {
    html += `<div class="tree-zone">UNASSIGNED SENTINELS</div>`;
    loose.forEach((s) => {
      html += `<div class="tree-sentinel" data-kind="sentinel" data-id="${s.sentinel_id}">${s.sentinel_id} ${badge(s.presence, s.presence)}</div>`;
    });
  }
  $("fleet-tree").innerHTML = html || '<div class="empty">NO FLEET HIERARCHY YET</div>';
  const audit = (data.audit || []).slice(0, 6).map((a) => `${a.timestamp_utc || ""} ${a.operation} ${a.result}`).join("<br>");
  if (audit) {
    $("fleet-tree").innerHTML += `<div class="meta" style="margin-top:0.8rem">RECENT AUDIT<br>${audit}</div>`;
  }
}

function showDetail(kind, id) {
  $("fleet-crumb").textContent = "LEGION // FLEET";
  if (kind === "zone") {
    const zone = (FLEET.zones || []).find((z) => z.zone_id === id);
    if (!zone) return;
    $("fleet-crumb").textContent = `ZONE // ${zone.name}`;
    $("fleet-detail").innerHTML = `
      <h3>${zone.name}</h3>
      <div class="meta">ID ${zone.zone_id}<br>Type ${zone.zone_type} · ${badge(zone.coverage, zone.coverage)} · ${zone.status}<br>${zone.description || ""}</div>
      <div class="row-actions">
        <button class="danger" data-archive-zone="${zone.zone_id}">Archive Zone</button>
      </div>`;
    return;
  }
  if (kind === "cohort") {
    const cohort = (FLEET.cohorts || []).find((c) => c.cohort_id === id);
    if (!cohort) return;
    $("fleet-crumb").textContent = `COHORT // ${cohort.display_name}`;
    const members = (FLEET.sentinels || []).filter((s) => s.cohort_id === id);
    const unassigned = (FLEET.unassigned_sentinels || []);
    $("fleet-detail").innerHTML = `
      <h3>${cohort.display_name}</h3>
      <div class="meta">
        ID ${cohort.cohort_id}<br>
        ${badge(cohort.readiness, cohort.readiness)} roster ${cohort.roster_label}<br>
        PRIMUS // ${cohort.primus_sentinel_id || "--"}<br>
        Zone ${cohort.zone_name || "none"}
      </div>
      <p class="meta">Primus is a Legion designation only; it does not enable mesh routing.</p>
      <label>Assign Zone
        <select id="detail-zone">${(FLEET.zones || []).map((z) =>
          `<option value="${z.zone_id}" ${z.zone_id === cohort.zone_id ? "selected" : ""}>${z.name}</option>`
        ).join("")}</select>
      </label>
      <div class="row-actions">
        <button data-assign-zone="${cohort.cohort_id}">Assign Zone</button>
        <button class="danger" data-deactivate-cohort="${cohort.cohort_id}">Deactivate</button>
      </div>
      <label>Add Sentinel
        <select id="detail-add">${unassigned.map((sid) => `<option value="${sid}">${sid}</option>`).join("")}</select>
      </label>
      <div class="row-actions"><button data-add-sentinel="${cohort.cohort_id}">Add to Cohort</button></div>
      <div class="meta">${members.map((s) =>
        `${s.sentinel_id} ${s.role} ${s.presence}
         <button data-set-primus="${cohort.cohort_id}" data-sentinel="${s.sentinel_id}">Make Primus</button>
         <button class="danger" data-remove-sentinel="${cohort.cohort_id}" data-sentinel="${s.sentinel_id}">Remove</button>`
      ).join("<br>")}</div>`;
    return;
  }
  if (kind === "sentinel") {
    const s = (FLEET.sentinels || []).find((row) => row.sentinel_id === id);
    if (!s) return;
    const h = healthOf(s);
    $("fleet-crumb").textContent = `SENTINEL // ${s.sentinel_id}`;
    $("fleet-detail").innerHTML = `
      <h3>${s.sentinel_id}</h3>
      <div class="meta">
        Status: ${s.presence}<br>
        Zone: ${s.zone_name || "--"}<br>
        Cohort: ${s.cohort_name || "--"}<br>
        Role: ${s.role}${s.role === "Primus" ? " " + badge("PRIMUS", "primus") : ""}<br>
        Profile: ${s.profile_id ? s.profile_id + " r" + s.profile_revision : "--"}<br>
        Capabilities: ${(s.capabilities || []).join(", ") || "--"}<br>
        BAT ${h.battery_percent ?? "--"} · ${wifiLabel(h)}
      </div>
      <div class="row-actions">
        <button data-act="alert" data-node="${s.sentinel_id}">Test alert</button>
        <button data-act="scan" data-node="${s.sentinel_id}">Scan 30s</button>
        <button class="danger" data-act="reboot" data-node="${s.sentinel_id}">Reboot</button>
      </div>`;
  }
}

function renderFleet(sentinels) {
  const grid = $("fleet-grid");
  const q = ($("fleet-search").value || "").toLowerCase();
  const rows = (sentinels || []).filter((s) => {
    const blob = `${s.sentinel_id} ${s.display_name || ""} ${s.zone_name || ""} ${s.cohort_name || ""} ${s.profile_id || ""}`.toLowerCase();
    return !q || blob.includes(q);
  });
  if (!rows.length) {
    grid.innerHTML = '<div class="empty">NO SENTINEL NODES IN INVENTORY</div>';
    return;
  }
  grid.innerHTML = rows.map((s) => {
    const h = healthOf(s);
    return `
    <article class="card ${s.presence === "offline" ? "down" : ""}">
      <h3>${s.sentinel_id} ${s.role === "Primus" ? badge("PRIMUS", "primus") : ""} ${badge(s.presence, s.presence)}</h3>
      <div class="meta">
        ZONE ${s.zone_name || "--"} · COHORT ${s.cohort_name || "--"}<br>
        BAT ${h.battery_percent != null ? h.battery_percent + "%" : "--"}
        · ${wifiLabel(h)}<br>
        PROFILE ${s.profile_id ? s.profile_id + " r" + s.profile_revision : "--"}
      </div>
      <div class="row-actions">
        <button data-kind="sentinel" data-id="${s.sentinel_id}">Details</button>
        <button data-act="alert" data-node="${s.sentinel_id}">Test alert</button>
        <button class="danger" data-act="reboot" data-node="${s.sentinel_id}">Reboot</button>
      </div>
    </article>`;
  }).join("");
}

function fieldInput(name, label, value) {
  return `<label>${label}<input data-field="${name}" type="text" value="${value || ""}" autocomplete="off" /></label>`;
}

function addTarget(data = {}) {
  const tech = data.technology || "ble";
  const wrap = document.createElement("div");
  wrap.className = "target-card";
  wrap.innerHTML = `
    <h4>SOI TARGET</h4>
    <div class="fields">
      <label>Name<input data-field="name" type="text" value="${data.name || ""}" placeholder="FOX-03" /></label>
      <label>Technology
        <select data-field="technology">
          <option value="wifi" ${tech === "wifi" ? "selected" : ""}>Wi-Fi</option>
          <option value="ble" ${tech === "ble" ? "selected" : ""}>BLE</option>
          <option value="bt_classic" ${tech === "bt_classic" ? "selected" : ""}>BT Classic</option>
        </select>
      </label>
      <label class="wifi-only">Band
        <select data-field="band">
          <option value="">any</option>
          <option value="2.4ghz" ${data.band === "2.4ghz" ? "selected" : ""}>2.4 GHz</option>
          <option value="5ghz" ${data.band === "5ghz" ? "selected" : ""}>5 GHz</option>
        </select>
      </label>
      <div class="wide ident-fields"></div>
      <label>Min RSSI dBm<input data-field="minimum_rssi_dbm" type="text" value="${data.minimum_rssi_dbm ?? -80}" /></label>
      <label>Required hits<input data-field="required_hits" type="text" value="${data.required_hits ?? 2}" /></label>
      <label>Severity
        <select data-field="severity">
          ${["low", "medium", "high", "critical"].map((s) =>
            `<option value="${s}" ${ (data.severity || "medium") === s ? "selected" : ""}>${s}</option>`
          ).join("")}
        </select>
      </label>
    </div>
    <div class="row-actions"><button class="danger remove-target">Remove</button></div>
  `;
  $("target-list").appendChild(wrap);
  const select = wrap.querySelector('[data-field="technology"]');
  const ident = wrap.querySelector(".ident-fields");
  function paint() {
    const current = select.value;
    wrap.querySelector(".wifi-only").style.display = current === "wifi" ? "block" : "none";
    ident.innerHTML = FIELDS[current].map(([name, label]) => fieldInput(name, label, data[name])).join("");
  }
  select.addEventListener("change", paint);
  wrap.querySelector(".remove-target").addEventListener("click", () => wrap.remove());
  paint();
}

function readTarget(card) {
  const get = (name) => {
    const el = card.querySelector(`[data-field="${name}"]`);
    return el ? el.value.trim() : "";
  };
  const technology = get("technology") || "ble";
  const target = {
    name: get("name"),
    technology,
    band: get("band"),
    minimum_rssi_dbm: get("minimum_rssi_dbm"),
    required_hits: get("required_hits"),
    severity: get("severity") || "medium",
  };
  for (const [name] of FIELDS[technology]) {
    target[name] = get(name);
  }
  return target;
}

function loadEditor(profile) {
  $("p-id").value = profile.profile_id || "";
  $("p-desc").value = profile.description || "";
  $("target-list").innerHTML = "";
  (profile.targets || []).forEach((target) => addTarget(target));
  if (!(profile.targets || []).length) addTarget();
}

function renderProfiles(profiles) {
  const grid = $("profile-grid");
  if (!profiles.length) {
    grid.innerHTML = '<div class="empty">NO SOI PROFILES INSTALLED</div>';
    return;
  }
  grid.innerHTML = profiles.map((p) => `
    <article class="card" data-load="${p.profile_id}">
      <h3>${p.profile_id}</h3>
      <div class="meta">
        REV ${p.revision} · TARGETS ${(p.targets || []).length}<br>
        ${(p.targets || []).map((t) => t.technology).filter(Boolean).join(" · ") || "none"}<br>
        ${p.description || ""}
      </div>
      <div class="row-actions">
        <button data-load="${p.profile_id}">Edit</button>
      </div>
    </article>
  `).join("");
}

async function refresh() {
  try {
    const data = await getJSON("/api/fleet?live=1");
    FLEET = data;
    renderOverview(data);
    renderTree(data);
    renderFleet(data.sentinels || []);
    const sel = $("event-node");
    const current = sel.value;
    sel.innerHTML = (data.sentinels || []).map((r) =>
      `<option value="${r.sentinel_id}">${r.sentinel_id}</option>`
    ).join("");
    if (current) sel.value = current;
  } catch (err) {
    toast("status feed offline");
  }
  try {
    const profiles = await getJSON("/api/profiles");
    renderProfiles(profiles.profiles || []);
  } catch (_err) {
    /* profiles optional */
  }
}

async function runAction(act, node) {
  const labels = {
    alert: ["TEST ALERT", `Send a Discord test alert from ${node}?`],
    scan: ["DIAGNOSTIC SCAN", `Start a 30s BLE scan on ${node}?`],
    reboot: ["REBOOT", `Reboot Sentinel ${node}?`],
  };
  const [title, body] = labels[act];
  if (!(await confirmAction(title, body))) return;
  const path = act === "alert" ? "test-alert" : act;
  const payload = { node, confirm: true };
  if (act === "scan") {
    payload.technology = "ble";
    payload.duration = 30;
  }
  const data = await postJSON(`/api/actions/${path}`, payload);
  toast(data.ok ? `${act} sent` : (data.error || "failed"));
  refresh();
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
  });
});

$("fleet-grid").addEventListener("click", (ev) => {
  const detail = ev.target.closest("[data-kind]");
  if (detail && detail.dataset.kind) {
    showDetail(detail.dataset.kind, detail.dataset.id);
    return;
  }
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  runAction(btn.dataset.act, btn.dataset.node);
});

$("fleet-tree").addEventListener("click", (ev) => {
  const item = ev.target.closest("[data-kind]");
  if (!item) return;
  showDetail(item.dataset.kind, item.dataset.id);
});

$("fleet-search").addEventListener("input", () => {
  renderTree(FLEET);
  renderFleet(FLEET.sentinels || []);
});
$("filter-zone").addEventListener("change", () => renderTree(FLEET));
$("filter-state").addEventListener("change", () => renderTree(FLEET));

$("create-zone").addEventListener("click", async () => {
  const name = $("new-zone-name").value.trim();
  if (!name) return toast("zone name required");
  if (!(await confirmAction("CREATE ZONE", `Create Zone '${name}'?`))) return;
  const data = await postJSON("/api/zones", { confirm: true, name });
  toast(data.ok ? "zone created" : (data.error || "failed"));
  refresh();
});

$("create-cohort").addEventListener("click", async () => {
  const name = $("new-cohort-name").value.trim();
  if (!name) return toast("cohort name required");
  if (!(await confirmAction("CREATE COHORT", `Create Cohort '${name}'?`))) return;
  const data = await postJSON("/api/cohorts", { confirm: true, display_name: name });
  toast(data.ok ? "cohort created" : (data.error || "failed"));
  refresh();
});

$("fleet-detail").addEventListener("click", async (ev) => {
  const act = ev.target.closest("button");
  if (!act) return;
  if (act.dataset.act) {
    runAction(act.dataset.act, act.dataset.node);
    return;
  }
  if (act.dataset.archiveZone) {
    if (!(await confirmAction("ARCHIVE ZONE", `Archive Zone ${act.dataset.archiveZone}?`))) return;
    const data = await postJSON(`/api/zones/${act.dataset.archiveZone}/archive`, { confirm: true });
    toast(data.ok ? "archived" : (data.error || "failed"));
    refresh();
  }
  if (act.dataset.assignZone) {
    const zoneId = $("detail-zone").value;
    if (!(await confirmAction("ASSIGN ZONE", `Assign Cohort ${act.dataset.assignZone} to Zone ${zoneId}?`))) return;
    const data = await postJSON(`/api/cohorts/${act.dataset.assignZone}/assign-zone`, { confirm: true, zone_id: zoneId });
    toast(data.ok ? "assigned" : (data.error || "failed"));
    refresh();
  }
  if (act.dataset.addSentinel) {
    const sid = $("detail-add").value;
    if (!(await confirmAction("ADD SENTINEL", `Add ${sid} to Cohort ${act.dataset.addSentinel}?`))) return;
    const data = await postJSON(`/api/cohorts/${act.dataset.addSentinel}/add-sentinel`, { confirm: true, sentinel_id: sid });
    toast(data.ok ? "added" : (data.error || "failed"));
    refresh();
  }
  if (act.dataset.setPrimus) {
    if (!(await confirmAction("TRANSFER PRIMUS", `Cohort ${act.dataset.setPrimus}\nNew Primus: ${act.dataset.sentinel}`))) return;
    const data = await postJSON(`/api/cohorts/${act.dataset.setPrimus}/set-primus`, { confirm: true, primus_sentinel_id: act.dataset.sentinel });
    toast(data.ok ? "primus updated" : (data.error || "failed"));
    refresh();
  }
  if (act.dataset.removeSentinel) {
    if (!(await confirmAction("REMOVE SENTINEL", `Remove ${act.dataset.sentinel} from ${act.dataset.removeSentinel}?`))) return;
    const data = await postJSON(`/api/cohorts/${act.dataset.removeSentinel}/remove-sentinel`, { confirm: true, sentinel_id: act.dataset.sentinel });
    toast(data.ok ? "removed" : (data.error || "failed"));
    refresh();
  }
  if (act.dataset.deactivateCohort) {
    if (!(await confirmAction("DEACTIVATE COHORT", `Deactivate ${act.dataset.deactivateCohort}?`))) return;
    const data = await postJSON(`/api/cohorts/${act.dataset.deactivateCohort}/deactivate`, { confirm: true });
    toast(data.ok ? "deactivated" : (data.error || "failed"));
    refresh();
  }
});

$("add-target").addEventListener("click", () => addTarget());

$("save-profile").addEventListener("click", async () => {
  const payload = {
    profile_id: $("p-id").value.trim(),
    description: $("p-desc").value.trim(),
    targets: [...document.querySelectorAll(".target-card")].map(readTarget),
  };
  const data = await sendJSON("/api/profiles", "PUT", payload);
  toast(data.ok ? `saved ${data.profile.profile_id} r${data.profile.revision}` : (data.error || "save failed"));
  if (data.ok) {
    loadEditor(data.profile);
    refresh();
  }
});

$("push-profile").addEventListener("click", async () => {
  const profileId = $("p-id").value.trim();
  if (!profileId) {
    toast("save a profile first");
    return;
  }
  if (!(await confirmAction("PUSH PROFILE", `Deploy ${profileId} to all Sentinel nodes?`))) return;
  const data = await postJSON(`/api/profiles/${encodeURIComponent(profileId)}/push`, { confirm: true });
  toast(data.ok ? "profile pushed" : (data.error || "push failed"));
  refresh();
});

$("profile-grid").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-load]");
  if (!btn) return;
  const data = await getJSON(`/api/profiles/${encodeURIComponent(btn.dataset.load)}`);
  if (data.ok) loadEditor(data.profile);
});

$("load-events").addEventListener("click", async () => {
  const node = $("event-node").value;
  if (!node) return;
  const data = await getJSON(`/api/events?node=${encodeURIComponent(node)}`);
  const events = ((data.results || [])[0] || {}).events || [];
  if (!events.length) {
    $("event-table").innerHTML = '<div class="empty">NO EVENTS</div>';
    return;
  }
  $("event-table").innerHTML = `
    <table>
      <thead><tr><th>Time</th><th>Type</th><th>SOI</th><th>Tech</th><th>RSSI</th></tr></thead>
      <tbody>
        ${events.map((e) => `<tr>
          <td>${e.timestamp_utc || "--"}</td>
          <td>${e.event_type || "--"}</td>
          <td>${e.soi_id || "--"}</td>
          <td>${e.technology || "--"}</td>
          <td>${e.rssi_dbm ?? "--"}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
});

async function hudWindow(action) {
  if (action === "maximize") {
    try {
      const el = document.documentElement;
      if (!document.fullscreenElement && el.requestFullscreen) el.requestFullscreen();
    } catch (err) {}
  }
  if (action === "minimize") {
    try {
      if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen();
    } catch (err) {}
  }
  try {
    await postJSON("/api/ui/window", { action });
  } catch (err) {}
}

$("win-min").addEventListener("click", () => hudWindow("minimize"));
$("win-max").addEventListener("click", () => hudWindow("maximize"));
$("win-close").addEventListener("click", () => hudWindow("close"));

function showTab(tabId) {
  // hide all panels
  document.querySelectorAll(".panel").forEach(p => p.style.display = "none");
  // show selected
  const panel = document.getElementById(tabId);
  if (panel) panel.style.display = "block";
}

// initialize active tab
showTab("fleet");

// tab click handler
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".panel").forEach(p => p.style.display = "none");
    const active = document.querySelector(`.panel[data-tab="${btn.dataset.tab}"]`);
    if (active) active.style.display = "block";
  });
});

// Map import support
async function importMap() {
  const name = document.getElementById("map-name").value.trim() || "New map";
  const desc = document.getElementById("map-desc").value.trim() || "";
  // file input
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async e => {
      const base64 = reader.result.split(",")[1];
      const mime = file.type || "image/png";
      try {
        const resp = await postJSON("/api/maps", {
          name,
          description: desc,
          fileBase64: base64,
          mimeType: mime,
        });
        if (resp.ok) {
          document.getElementById("map-status").textContent = `Map "${name}" imported (${resp.map_id})`;
          // optionally refresh map display
          loadMap(resp.map_id);
        } else {
          document.getElementById("map-status").textContent = "Import failed: " + (resp.error || "unknown");
        }
      } catch (err) {
        document.getElementById("map-status").textContent = "Import error: " + err.message;
      }
    };
    reader.readAsDataURL(file);
  };
  input.click();
}

$("import-map").addEventListener("click", importMap);

// initialize map tab hidden, show status
document.getElementById("map-status").textContent = "No map loaded. Use Import map to add one.";

clock();
setInterval(clock, 1000);
addTarget();
refresh();
setInterval(refresh, 8000);
