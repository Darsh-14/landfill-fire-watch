/* Landfill Fire Watch dashboard. Plain JS + Leaflet. All decisions come from the API (code);
   this page only displays them and lets the duty officer draft, approve and review. */
(() => {
  "use strict";
  const API = (window.LFW_CONFIG && window.LFW_CONFIG.apiBase || "").replace(/\/$/, "");
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = "—") => (v === null || v === undefined || v === "" ? d : v);

  // ------------------------------------------------------------------ API
  async function get(path) {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  function token() {
    let t = null;
    try { t = sessionStorage.getItem("lfw_admin_token"); } catch (_) { /* storage blocked */ }
    if (!t) {
      t = window.prompt("Admin token (duty officer). Demo control, not production authentication:");
      if (t) { try { sessionStorage.setItem("lfw_admin_token", t); } catch (_) { /* ignore */ } }
    }
    return t;
  }
  async function post(path, body) {
    const t = token();
    if (!t) throw new Error("admin token required");
    const r = await fetch(API + path, { method: "POST", headers: { "content-type": "application/json", "x-admin-token": t },
      body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) { try { sessionStorage.removeItem("lfw_admin_token"); } catch (_) {} }
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: true }).setView([20.6, 78.9], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const siteLayer = L.layerGroup().addTo(map);
  const incidentLayer = L.layerGroup().addTo(map);
  const TIER = { high: ["#d7191c", "#8b0000"], nominal: ["#fdae61", "#b35806"], low: ["#ffffbf", "#a6a600"] };
  const KIND_COLOR = { school: "#2563eb", kindergarten: "#2563eb", college: "#2563eb", hospital: "#d0312d", clinic: "#d0312d" };

  function pixelBounds(d) {
    // Square sized to the pixel: scan (across track) x track, in km, centred on the hotspot.
    const dLat = (d.track_km / 2) / 111.32;
    const dLon = (d.scan_km / 2) / (111.32 * Math.cos(d.lat * Math.PI / 180));
    return [[d.lat - dLat, d.lon - dLon], [d.lat + dLat, d.lon + dLon]];
  }

  // ------------------------------------------------------------------ status strip
  async function loadHealth() {
    const el = $("#status-strip");
    try {
      const h = await get("/health");
      if (!h.last_scan_utc) { el.innerHTML = `No scan yet · Sources: ${esc(h.sources)} · Sites monitored: ${esc(h.sites_monitored)}`; return; }
      const time = esc(h.last_scan_ist.split(" ")[1]);
      const stale = h.minutes_ago > 6 * 60 ? ' class="stale"' : "";
      const latest = h.latest_detection_utc ? ` · Newest satellite data: ${esc(new Date(h.latest_detection_utc).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }))} IST` : "";
      el.innerHTML = `<span${stale}>Last scan: ${time} IST (${esc(h.minutes_ago)} min ago)</span> · Sources: ${esc(h.sources)} · Sites monitored: ${esc(h.sites_monitored)}${latest}`;
    } catch (e) {
      el.innerHTML = `<span class="stale">API not reachable (${esc(e.message)}). Data age unknown.</span>`;
    }
  }

  // ------------------------------------------------------------------ sites
  let SITES = [];
  async function loadSites() {
    try { SITES = await get("/sites"); } catch (e) { SITES = []; }
    siteLayer.clearLayers();
    for (const s of SITES) {
      const layer = L.geoJSON(s.outline, { style: { color: "#222", weight: 2, fill: false, dashArray: s.verified ? null : "4 4" } });
      layer.bindTooltip(`${esc(s.name)} (${esc(s.city)})${s.verified ? "" : " · outline not yet checked"}`);
      layer.addTo(siteLayer);
    }
    $("#site-list").innerHTML = SITES.length ? `<table><thead><tr><th>Site</th><th>City</th><th>Outline check</th><th>Last detection</th></tr></thead><tbody>${
      SITES.map((s) => `<tr><td>${esc(s.name)}</td><td>${esc(s.city)}, ${esc(s.state)}</td><td>${s.verified ? esc(s.verified_by) : "not yet checked"}</td><td>${esc(fmt(s.last_detection_utc))}</td></tr>`).join("")
    }</tbody></table><p class="note">Dashed outlines have not been checked on imagery yet.</p>` : '<p class="empty">No sites.</p>';
  }

  // ------------------------------------------------------------------ incidents
  let selected = null;
  async function loadIncidents() {
    const list = $("#incident-list");
    let items = [];
    try { items = await get("/incidents"); } catch (e) { list.innerHTML = `<p class="empty">Cannot load incidents: ${esc(e.message)}</p>`; return; }
    const live = items.filter((i) => i.mode === "live");
    const replay = items.filter((i) => i.mode === "replay");
    const row = (i) => `<button class="incident-item${i.incident_id === selected ? " selected" : ""}" data-id="${esc(i.incident_id)}">
        <span class="badge ${esc(i.status)}">${esc(i.status)}</span>
        ${i.mode === "replay" ? '<span class="badge replay">REPLAY — historical data</span>' : '<span class="badge live">LIVE</span>'}
        <strong>${esc(siteName(i.site_id))}</strong>
        <div class="meta">First detection ${esc(i.first_ist)} · ${esc(i.overpass_count)} overpasses · ${esc(i.receptors_in_zone)} places in sector</div>
      </button>`;
    list.innerHTML = (live.length ? live.map(row).join("") : '<p class="empty">No live incidents. The scheduled scan found no possible fire at the monitored sites.</p>')
      + (replay.length ? '<h3 class="note">Replays</h3>' + replay.map(row).join("") : "");
    list.querySelectorAll(".incident-item").forEach((b) => b.addEventListener("click", () => openIncident(b.dataset.id)));
  }
  const siteName = (id) => (SITES.find((s) => s.site_id === id) || { name: id }).name;

  function overpassGroups(dets) {
    const groups = new Map();
    for (const d of dets) {
      const k = d.overpass; // overpass id from the API: same rule the status logic uses
      if (!groups.has(k)) groups.set(k, { ...d, acq_ist: d.overpass_ist, n: 0, maxFrp: null, tiers: new Set() });
      const g = groups.get(k);
      g.n += 1; g.tiers.add(d.tier);
      if (d.frp_mw !== null && (g.maxFrp === null || d.frp_mw > g.maxFrp)) g.maxFrp = d.frp_mw;
    }
    return [...groups.values()].sort((a, b) => a.acq_utc.localeCompare(b.acq_utc));
  }

  async function openIncident(id) {
    selected = id;
    document.querySelectorAll(".incident-item").forEach((b) => b.classList.toggle("selected", b.dataset.id === id));
    const panel = $("#incident-panel");
    panel.classList.remove("hidden");
    panel.innerHTML = '<p class="empty">Loading…</p>';
    let d;
    try { d = await get(`/incidents/${encodeURIComponent(id)}`); } catch (e) { panel.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
    renderIncident(d);
    drawIncident(d);
  }

  function drawIncident(d) {
    incidentLayer.clearLayers();
    const inc = d.incident;
    const bounds = L.latLngBounds([]);
    if (inc.smoke && inc.smoke.geometry_geojson) {
      const z = L.geoJSON(inc.smoke.geometry_geojson, { style: { color: "#ff8c00", weight: 1, fillColor: "#ff8c00", fillOpacity: 0.22 } })
        .bindTooltip("Smoke screening sector (wind direction only). Not a pollution forecast.").addTo(incidentLayer);
      bounds.extend(z.getBounds());
    }
    for (const r of d.receptors) {
      L.circleMarker([r.lat, r.lon], { radius: 4, color: KIND_COLOR[r.kind] || "#555", weight: 1, fillOpacity: 0.85 })
        .bindTooltip(`${esc(r.name)} (${esc(r.kind)}, ${esc(r.distance_km)} km)`).addTo(incidentLayer);
    }
    for (const det of d.detections) {
      const [fill, stroke] = TIER[det.tier] || TIER.low;
      const rect = L.rectangle(pixelBounds(det), { color: stroke, weight: 1, fillColor: fill, fillOpacity: 0.55 })
        .bindTooltip(`${esc(det.acq_ist)} · ${esc(det.source)} · ${esc(det.tier)}${det.static ? " (static source)" : ""} · FRP ${esc(fmt(det.frp_mw))} MW`)
        .addTo(incidentLayer);
      bounds.extend(rect.getBounds());
    }
    const site = SITES.find((s) => s.site_id === inc.site_id);
    if (site) bounds.extend(L.geoJSON(site.outline).getBounds());
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
  }

  function renderIncident(d) {
    const inc = d.incident, s = d.summary, z = inc.smoke;
    const draft = d.draft;
    const groups = overpassGroups(d.detections);
    const human = inc.human_action;
    const dirs = z ? [...new Set(z.toward_deg.map(compass))].join(", ") : "—";
    const panel = $("#incident-panel");
    panel.innerHTML = `
      ${inc.mode === "replay" ? '<div class="replay-banner">REPLAY — historical data. Alerts go to the demo topic only.</div>' : ""}
      <h2>${esc(d.site ? d.site.name : inc.site_id)} <span class="note">${esc(d.site ? d.site.city + ", " + d.site.state : "")}</span></h2>
      <p><span class="badge ${esc(inc.status)}">${esc(inc.status)}</span>
         <span class="note">${human ? `set by a person (${esc(human.status)}${human.note ? ": " + esc(human.note) : ""})` : "computed by rules: " + esc(inc.status_reason)}</span></p>
      <dl class="kv">
        <dt>First detection</dt><dd>${esc(s.first_ist)}</dd>
        <dt>Last detection</dt><dd>${esc(s.last_ist)}</dd>
        <dt>Overpasses</dt><dd>${esc(inc.overpass_count)}</dd>
        <dt>Max FRP</dt><dd>${esc(fmt(inc.max_frp_mw))} MW</dd>
        <dt>Smoke toward</dt><dd>${z ? (z.calm ? `calm: ${esc(z.length_km)} km circle` : `${esc(dirs)} (${esc(z.toward_deg.join("°, "))}°), ${esc(z.length_km)} km, half-angle ≤ ${esc(z.half_angle_deg)}°`) : "no wind data"}</dd>
        <dt>Wind</dt><dd>${z ? `${esc(z.wind_hours.length)} hours, mean ${esc(fmt(z.mean_speed_ms))} m/s (Open-Meteo grid point ${esc(fmt(z.wind_point_lat))}, ${esc(fmt(z.wind_point_lon))})` : "—"}</dd>
      </dl>
      <p class="note">The smoke zone is a screening sector from wind direction. It is not a pollution forecast.</p>

      <h3>Overpass timeline (${groups.length})</h3>
      <div class="scroll"><ul class="timeline">${groups.map((g) => `<li>${esc(g.acq_ist)} · ${esc(g.source)} (${esc(g.satellite)}) · ${g.n} pixel${g.n > 1 ? "s" : ""} · ${esc([...g.tiers].join("/"))} · max FRP ${esc(fmt(g.maxFrp))} MW</li>`).join("")}</ul></div>

      <h3>Schools and hospitals in the sector (${d.receptors.length})</h3>
      ${d.receptors.length ? `<div class="scroll"><table><thead><tr><th>Name</th><th>Type</th><th>km</th></tr></thead><tbody>${
        d.receptors.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.kind)}</td><td>${esc(r.distance_km)}</td></tr>`).join("")}</tbody></table></div>`
        : '<p class="empty">None in the sector.</p>'}

      <h3>Draft alerts</h3>
      <div id="draft-area">${renderDraft(draft)}</div>
      <div class="actions">
        <button class="btn" id="btn-draft">${draft ? "Redraft with agent" : "Draft with agent"}</button>
        <button class="btn primary" id="btn-approve" ${draft && draft.validated ? "" : "disabled"}>Approve and send${inc.mode === "replay" ? " (demo topic)" : ""}</button>
      </div>
      <div class="actions">
        <span class="note">Review:</span>
        <button class="btn" data-review="CONFIRMED">Confirmed</button>
        <button class="btn" data-review="FALSE_ALARM">False alarm</button>
        <button class="btn" data-review="CLOSED">Closed</button>
      </div>
      <div id="action-msg" class="msg"></div>
      ${d.approvals.length ? `<p class="note">Sent: ${d.approvals.map((a) => `${esc(a.approved_utc)} to ${esc(a.topic)} topic`).join("; ")}</p>` : ""}`;
    bindDraftTabs(draft);
    $("#btn-draft").addEventListener("click", () => requestDraft(inc.incident_id, draft ? draft.created_utc : null));
    $("#btn-approve").addEventListener("click", () => approve(inc.incident_id));
    panel.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", () => review(inc.incident_id, b.dataset.review)));
  }

  function renderDraft(draft) {
    if (!draft) return '<p class="empty">No draft yet. The agent writes text only from facts that code computed.</p>';
    const fails = draft.attempts.filter((a) => !a.passed && a.source !== "template");
    return `
      <p>${draft.template_used ? '<span class="badge template">Template used</span>' : ""}
         <span class="note">model: ${esc(draft.model)} · ${esc(draft.created_utc)} · ${draft.validated ? '<span class="pass">validated</span>' : '<span class="fail">not validated</span>'}</span></p>
      ${fails.map((a) => `<div class="attempt-fail">Attempt ${esc(a.attempt)} rejected by the validator: ${esc(a.errors.join(" | "))}</div>`).join("")}
      <div class="draft-tabs">
        <button data-t="resident_advisory_en" class="active">English</button>
        <button data-t="resident_advisory_hi">Hindi</button>
        <button data-t="official_alert_en">Official</button>
      </div>
      <div class="draft-text" id="draft-text"></div>
      <h3>Validator report</h3>
      <ul class="checks">${draft.report.checks.map((c) => `<li><span class="${c.passed === null ? "skip" : c.passed ? "pass" : "fail"}">${c.passed === null ? "SKIP" : c.passed ? "PASS" : "FAIL"}</span> ${esc(c.check)}. ${esc(c.name)}${c.detail ? ` — <span class="note">${esc(c.detail)}</span>` : ""}</li>`).join("")}</ul>`;
  }

  function bindDraftTabs(draft) {
    if (!draft) return;
    const show = (key) => {
      const txt = draft.draft[key];
      $("#draft-text").textContent = txt || (key === "resident_advisory_hi" ? "Hindi is switched off until a Hindi speaker reviews the template (MVP A4)." : "");
      document.querySelectorAll(".draft-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.t === key));
    };
    document.querySelectorAll(".draft-tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.t)));
    show("resident_advisory_en");
  }

  const msg = (html) => { const el = $("#action-msg"); if (el) el.innerHTML = html; };

  async function requestDraft(id, previous) {
    try {
      msg("Asking the agent to draft…");
      await post(`/incidents/${encodeURIComponent(id)}/draft`);
      for (let i = 0; i < 40; i++) { // poll up to ~2 minutes (Lambda draft runs asynchronously)
        const d = await get(`/incidents/${encodeURIComponent(id)}`);
        if (d.draft && d.draft.created_utc !== previous) { renderIncident(d); return; }
        await new Promise((r) => setTimeout(r, 3000));
      }
      msg('<span class="fail">No draft after 2 minutes. Check the DraftFunction logs.</span>');
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  async function approve(id) {
    if (!window.confirm("Send this validated draft by email now? A person is approving it.")) return;
    try {
      const r = await post(`/incidents/${encodeURIComponent(id)}/approve`);
      msg(`<span class="pass">Sent to the ${esc(r.topic)} topic</span> (message ${esc(r.message_id)}).`);
      openIncident(id);
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  async function review(id, status) {
    const note = window.prompt(`Mark as ${status}. Note (optional):`, "") ?? null;
    if (note === null) return;
    try { await post(`/incidents/${encodeURIComponent(id)}/review`, { status, note }); await loadIncidents(); openIncident(id); }
    catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  function compass(deg) {
    const n = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
    return n[Math.floor(((deg % 360) / 22.5) + 0.5) % 16];
  }

  // ------------------------------------------------------------------ backtest
  async function loadBacktest() {
    const el = $("#backtest");
    let b;
    try { b = await get("/backtest"); } catch (e) { el.innerHTML = `<p class="empty">No backtest available (${esc(e.message)}).</p>`; return; }
    el.innerHTML = `
      <p class="note">NASA FIRMS archive (standard processing). Detected = at least one PROBABLE incident in the window.
        Config hash <code>${esc(String(b.config_hash).slice(0, 12))}</code> · ${esc(b.freeze)}</p>
      <table><thead><tr><th>Event</th><th>Reported start</th><th>Detected</th><th>First detection (IST)</th><th>Δ days</th><th>Overpasses</th><th>Max FRP</th><th>Smoke zone</th><th>Receptors</th></tr></thead>
      <tbody>${b.events.map((m) => `<tr><td>${esc(m.event_id)}</td><td>${esc(m.reported_start)}</td><td>${m.detected ? '<span class="pass">yes</span>' : '<span class="fail">no (miss)</span>'}</td>
        <td>${esc(fmt(m.first_detection_ist))}</td><td>${esc(fmt(m.delta_days_from_reported_start))}</td><td>${esc(m.overpasses_with_detections)}</td>
        <td>${esc(fmt(m.max_frp_mw))}</td><td>${esc(m.smoke_zone)}</td><td>${esc(m.receptor_count)}</td></tr>`).join("")}</tbody></table>
      <h3>Alerts in windows with no reported fire</h3>
      <p class="note">Monsoon windows. No news report does not prove there was no fire, so these are not called false positives.</p>
      <table><thead><tr><th>Site</th><th>Window</th><th>Matched</th><th>CANDIDATE</th><th>PROBABLE</th></tr></thead>
      <tbody>${b.quiet_windows.map((q) => { const st = q.incidents.map((i) => i.status);
        return `<tr><td>${esc(q.site_id)}</td><td>${esc(q.start)} to ${esc(q.end)}</td><td>${esc(q.matched)}</td><td>${st.filter((x) => x === "CANDIDATE").length}</td><td>${st.filter((x) => x === "PROBABLE").length}</td></tr>`; }).join("")}</tbody></table>`;
  }

  // ------------------------------------------------------------------ tabs + boot
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    for (const v of ["incidents", "backtest", "sites"]) $(`#view-${v}`).classList.toggle("hidden", v !== t.dataset.view);
    if (t.dataset.view === "backtest") loadBacktest();
  }));

  (async () => {
    await Promise.all([loadHealth(), loadSites()]);
    await loadIncidents();
    const m = location.hash.match(/^#incident=(.+)$/); // deep link, e.g. #incident=brahmapuram-kochi-20230302T1635
    if (m) openIncident(decodeURIComponent(m[1]));
    setInterval(loadHealth, 60000);
  })();
})();
