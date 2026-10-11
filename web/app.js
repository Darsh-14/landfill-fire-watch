/* Landfill Fire Watch dashboard. Plain JS + Leaflet. All decisions come from the API (code);
   this page only displays them and lets the duty officer draft, approve and review. */
(() => {
  "use strict";
  const API = (window.LFW_CONFIG && window.LFW_CONFIG.apiBase || "").replace(/\/$/, "");
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = "—") => (v === null || v === undefined || v === "" ? d : v);
  const icon = (id) => `<svg class="ic"><use href="#i-${id}"/></svg>`;
  const isMobile = () => window.matchMedia("(max-width: 899px)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const REDUCE = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fly = (bounds, opts) => (REDUCE ? map.fitBounds(bounds, { ...opts, animate: false }) : map.flyToBounds(bounds, { ...opts, duration: 1.1 }));

  // ------------------------------------------------------------------ dialog + toast
  function modal({ title, text, input = false, placeholder = "", ok = "OK", type = "text" }) {
    return new Promise((resolve) => {
      const m = $("#modal"), inp = $("#modal-input");
      $("#modal-title").textContent = title;
      $("#modal-text").textContent = text || "";
      inp.classList.toggle("hidden", !input);
      inp.value = ""; inp.type = type; inp.placeholder = placeholder;
      $("#modal-ok").textContent = ok;
      m.classList.remove("hidden");
      if (input) setTimeout(() => inp.focus(), 50);
      const done = (v) => { m.classList.add("hidden"); cleanup(); resolve(v); };
      const onOk = () => done(input ? inp.value.trim() : true);
      const onCancel = () => done(null);
      const onKey = (e) => { if (e.key === "Enter") onOk(); if (e.key === "Escape") onCancel(); };
      const cleanup = () => { $("#modal-ok").removeEventListener("click", onOk); $("#modal-cancel").removeEventListener("click", onCancel);
        document.removeEventListener("keydown", onKey); };
      $("#modal-ok").addEventListener("click", onOk);
      $("#modal-cancel").addEventListener("click", onCancel);
      document.addEventListener("keydown", onKey);
    });
  }
  let toastTimer = null;
  function toast(text, bad = false) {
    const t = $("#toast");
    t.textContent = text; t.classList.toggle("bad", bad); t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 4200);
  }

  // ------------------------------------------------------------------ API
  async function get(path) {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  async function token() {
    let t = null;
    try { t = sessionStorage.getItem("lfw_admin_token"); } catch (_) { /* storage blocked */ }
    if (!t) {
      t = await modal({ title: "Duty officer token", text: "Enter the admin token to draft, approve or review. Demo control, not production authentication.",
        input: true, type: "password", placeholder: "Admin token", ok: "Continue" });
      if (t) { try { sessionStorage.setItem("lfw_admin_token", t); } catch (_) { /* ignore */ } }
    }
    return t;
  }
  async function post(path, body) {
    const t = await token();
    if (!t) throw new Error("admin token required");
    const r = await fetch(API + path, { method: "POST", headers: { "content-type": "application/json", "x-admin-token": t },
      body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) { try { sessionStorage.removeItem("lfw_admin_token"); } catch (_) {} }
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: false, attributionControl: true }).setView([20.6, 79.5], 5);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Fire data NASA FIRMS · Wind Open-Meteo',
  }).addTo(map);
  const zoomClass = () => document.getElementById("map").classList.toggle("lowzoom", map.getZoom() < 8);
  map.on("zoomend", zoomClass); zoomClass();
  const siteLayer = L.layerGroup().addTo(map);
  const pinLayer = L.layerGroup().addTo(map);
  const incidentLayer = L.layerGroup().addTo(map);
  const TIER = { high: ["#e8553e", "#ffb3a6"], nominal: ["#f39a3c", "#ffd29a"], low: ["#f3e27a", "#fff6c2"] };
  const KIND_COLOR = { school: "#5b8cff", kindergarten: "#5b8cff", college: "#5b8cff", hospital: "#ff6b6b", clinic: "#ff6b6b" };

  function pixelBounds(d) {
    // Square sized to the pixel: scan (across track) x track, in km, centred on the hotspot.
    const dLat = (d.track_km / 2) / 111.32;
    const dLon = (d.scan_km / 2) / (111.32 * Math.cos(d.lat * Math.PI / 180));
    return [[d.lat - dLat, d.lon - dLon], [d.lat + dLat, d.lon + dLon]];
  }
  function fitPadding() {
    // Keep fitted content clear of the floating panel (desktop) or the bottom sheet (mobile).
    if (isMobile()) {
      const st = sheetState();  // fit into the strip of map above the bottom sheet (its target height, not mid-transition)
      const sheet = st === "collapsed" ? 150 : st === "expanded" ? window.innerHeight - 140 : 0.56 * window.innerHeight;
      return { paddingTopLeft: [16, 110], paddingBottomRight: [16, Math.round(sheet) + 16] };
    }
    return { paddingTopLeft: [$("#side").offsetWidth + 40, 80], paddingBottomRight: [40, 40] };
  }

  // ------------------------------------------------------------------ status (data age + sensors, always visible)
  async function loadHealth() {
    const el = $("#status-strip");
    try {
      const h = await get("/health");
      if (!h.last_scan_utc) { el.innerHTML = `<span class="age">No scan yet</span><span>${esc(h.sources)}</span>`; return; }
      const time = esc(h.last_scan_ist.split(" ")[1]);
      const mins = Number(h.minutes_ago);
      const ago = mins < 60 ? `${mins} min ago` : `${Math.round(mins / 60)} h ago`;
      const stale = mins > 6 * 60;
      const latest = h.latest_detection_utc ? new Date(h.latest_detection_utc).toLocaleString("en-IN",
        { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" }) : null;
      el.innerHTML = `<span class="age${stale ? "" : " fresh"}">${stale ? "Stale · " : ""}Last scan ${time} IST · ${esc(ago)}</span>
        <span>Sources: <b>${esc(h.sources)}</b></span>
        ${latest ? `<span>Newest satellite data: <b>${esc(latest)} IST</b></span>` : ""}
        <span class="extra">Sites monitored: <b>${esc(h.sites_monitored)}</b></span>`;
    } catch (e) {
      el.innerHTML = `<span class="stale">API not reachable (${esc(e.message)}). Data age unknown.</span>`;
    }
  }

  // ------------------------------------------------------------------ sites
  let SITES = [];
  const siteName = (id) => (SITES.find((s) => s.site_id === id) || { name: id }).name;
  const siteCenter = (s) => { try { return L.geoJSON(s.outline).getBounds().getCenter(); } catch (_) { return null; } };

  async function loadSites() {
    try { SITES = await get("/sites"); } catch (e) { SITES = []; }
    siteLayer.clearLayers();
    for (const s of SITES) {
      const layer = L.geoJSON(s.outline, { style: { color: "#dfe3ea", weight: 1.6, fill: true, fillOpacity: 0.04, dashArray: s.verified ? null : "4 4" } });
      layer.bindTooltip(`${esc(s.name)} (${esc(s.city)})${s.verified ? "" : " · outline not yet checked"}`);
      layer.addTo(siteLayer);
    }
  }

  function renderSites() {
    const withInc = new Set(INCIDENTS.map((i) => i.site_id));
    $("#site-list").innerHTML = `<h2 class="view-title">Monitored sites</h2>
      <p class="view-sub">${SITES.length} landfills with outlines from OpenStreetMap. Dashed outlines have not been checked on imagery yet.</p>
      ${SITES.length ? SITES.map((s) => `<button class="site-item${withInc.has(s.site_id) ? " has-inc" : ""}" data-site="${esc(s.site_id)}">
        <span class="inc-ic">${icon("pin")}</span>
        <span class="inc-main"><strong>${esc(s.name)}</strong><small>${esc(s.city)}, ${esc(s.state)}</small>
          <span class="${s.verified ? "verified" : "unverified"}">${s.verified ? "Outline checked: " + esc(s.verified_by) : "Outline not yet checked"}</span></span>
        <span class="inc-chev">${icon("chev")}</span></button>`).join("") : '<p class="empty">No sites.</p>'}`;
    $$(".site-item").forEach((b) => b.addEventListener("click", () => {
      const s = SITES.find((x) => x.site_id === b.dataset.site);
      if (!s) return;
      fly(L.geoJSON(s.outline).getBounds(), { ...fitPadding(), maxZoom: 15 });
      if (isMobile()) setSheet("collapsed");
    }));
  }

  // ------------------------------------------------------------------ incidents
  let INCIDENTS = [];
  let selected = null;
  const RANK = { CONFIRMED: 4, PROBABLE: 3, CANDIDATE: 2, CLOSED: 1, FALSE_ALARM: 0 };

  async function loadIncidents() {
    const list = $("#incident-list");
    try { INCIDENTS = await get("/incidents"); } catch (e) { list.innerHTML = `<p class="empty">Cannot load incidents: ${esc(e.message)}</p>`; return; }
    const live = INCIDENTS.filter((i) => i.mode === "live");
    const replay = INCIDENTS.filter((i) => i.mode === "replay");
    const row = (i) => `<button class="incident-item ${esc(i.status)}${i.incident_id === selected ? " selected" : ""}" data-id="${esc(i.incident_id)}">
        <span class="inc-ic">${icon("flame")}</span>
        <span class="inc-main">
          <span class="inc-title"><strong>${esc(siteName(i.site_id))}</strong>
            <span class="badge ${esc(i.status)}">${esc(i.status)}</span>
            ${i.mode === "replay" ? '<span class="badge replay">REPLAY — historical data</span>' : '<span class="badge live">LIVE</span>'}</span>
          <span class="inc-meta">First detection ${esc(i.first_ist)} · ${esc(i.overpass_count)} overpasses · ${esc(i.receptors_in_zone)} places in sector</span>
        </span><span class="inc-chev">${icon("chev")}</span></button>`;
    // MVP §2.2 item 12: how many incidents a person has marked, per outcome.
    const count = (s) => INCIDENTS.filter((i) => i.human_status === s).length;
    list.innerHTML = `<div class="list-head"><h2 class="view-title">Incidents</h2></div>
      <p class="view-sub">Possible fires found by fixed rules. A person checks each one before any alert is sent.</p>
      <div class="review-counts" title="Reviewed by a person">
        <div><b>${count("CONFIRMED")}</b><span>confirmed</span></div><div><b>${count("FALSE_ALARM")}</b><span>false alarm</span></div>
        <div><b>${count("CLOSED")}</b><span>closed</span></div><div><b>${INCIDENTS.filter((i) => !i.human_status).length}</b><span>not reviewed</span></div></div>
      <div class="section-label">Live</div>
      ${live.length ? live.map(row).join("") : '<p class="empty">No live incidents. The scheduled scan found no possible fire at the monitored sites.</p>'}
      ${replay.length ? '<div class="section-label">Replays of documented fires</div>' + replay.map(row).join("") : ""}`;
    $$(".incident-item", list).forEach((b) => b.addEventListener("click", () => openIncident(b.dataset.id)));
    drawPins();
    renderSites();
  }

  function drawPins() {
    pinLayer.clearLayers();
    const bySite = new Map();
    for (const i of INCIDENTS) {
      const cur = bySite.get(i.site_id);
      if (!cur || (RANK[i.status] ?? 0) > (RANK[cur.status] ?? 0)) bySite.set(i.site_id, i);
    }
    for (const s of SITES) {
      const c = siteCenter(s);
      if (!c) continue;
      const inc = bySite.get(s.site_id);
      const cls = inc ? `pin ${esc(inc.status)}` : "pin site";
      const label = inc ? `${esc(s.name)}${inc.mode === "replay" ? " · replay" : ""}` : esc(s.name);
      const m = L.marker(c, { icon: L.divIcon({ className: "", html: `<div class="${cls}"><span class="pin-dot">${icon("flame")}</span><span class="pin-label">${label}</span></div>`,
        iconSize: [30, 30], iconAnchor: [15, 15] }), riseOnHover: true });
      if (inc) {
        m.bindPopup(`<b>${esc(inc.first_ist)}</b><br>${esc(inc.status)} possible fire at ${esc(s.name)}, ${esc(s.city)}.
          ${inc.mode === "replay" ? "<br>REPLAY — historical data." : ""}<br>${esc(inc.receptors_in_zone)} schools and hospitals in the smoke screening sector.
          <br><span class="pop-link" data-open="${esc(inc.incident_id)}">Open incident →</span>`);
        m.on("popupopen", (e) => { const a = e.popup.getElement().querySelector("[data-open]"); if (a) a.onclick = () => openIncident(a.dataset.open); });
      } else {
        m.bindTooltip(`${esc(s.name)} · monitored, no incident`);
      }
      m.addTo(pinLayer);
    }
  }

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
    showView("incidents");
    $("#incident-list").classList.add("hidden");
    const panel = $("#incident-panel");
    panel.classList.remove("hidden");
    panel.innerHTML = '<p class="empty"><span class="spinner"></span> Loading incident…</p>';
    $(".panel-body").scrollTop = 0;
    if (isMobile()) setSheet("normal");
    map.closePopup();
    try { history.replaceState(null, "", `#incident=${encodeURIComponent(id)}`); } catch (_) { /* file:// */ }
    let d;
    try { d = await get(`/incidents/${encodeURIComponent(id)}`); } catch (e) { panel.innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
    renderIncident(d);
    drawIncident(d);
  }

  // Whole monitored area (all sites span roughly 8-32 N, 68-92 E), framed clear of the panel or sheet.
  const INDIA = [[8, 68.5], [31.5, 91.5]];
  function showIndia() { fly(INDIA, fitPadding()); }

  function closeIncident() {
    selected = null;
    incidentLayer.clearLayers();
    $("#incident-panel").classList.add("hidden");
    $("#incident-list").classList.remove("hidden");
    $$(".incident-item").forEach((b) => b.classList.remove("selected"));
    try { history.replaceState(null, "", location.pathname); } catch (_) {}
    showIndia();
  }

  function drawIncident(d) {
    incidentLayer.clearLayers();
    const inc = d.incident;
    const bounds = L.latLngBounds([]);
    if (inc.smoke && inc.smoke.geometry_geojson) {
      const z = L.geoJSON(inc.smoke.geometry_geojson, { style: { color: "#f3b23c", weight: 1.2, fillColor: "#f3b23c", fillOpacity: 0.16, dashArray: "6 4" } })
        .bindTooltip("Smoke screening sector (wind direction only). Not a pollution forecast.").addTo(incidentLayer);
      bounds.extend(z.getBounds());
    }
    for (const r of d.receptors) {
      L.circleMarker([r.lat, r.lon], { radius: 4, color: "#111", weight: 1, fillColor: KIND_COLOR[r.kind] || "#9aa1ad", fillOpacity: 0.95 })
        .bindTooltip(`${esc(r.name)} (${esc(r.kind)}, ${esc(r.distance_km)} km)`).addTo(incidentLayer);
    }
    for (const det of d.detections) {
      const [fill, stroke] = TIER[det.tier] || TIER.low;
      const rect = L.rectangle(pixelBounds(det), { color: stroke, weight: 1, fillColor: fill, fillOpacity: 0.5 })
        .bindTooltip(`Satellite hotspot · ${esc(det.acq_ist)} · ${esc(det.source)} · ${esc(det.tier)}${det.static ? " (static source)" : ""} · FRP ${esc(fmt(det.frp_mw))} MW`)
        .addTo(incidentLayer);
      bounds.extend(rect.getBounds());
    }
    const site = SITES.find((s) => s.site_id === inc.site_id);
    if (site) bounds.extend(L.geoJSON(site.outline).getBounds());
    if (bounds.isValid()) fly(bounds, fitPadding());
  }

  function compass(deg) {
    const n = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
    return n[Math.floor(((deg % 360) / 22.5) + 0.5) % 16];
  }

  function renderIncident(d) {
    const inc = d.incident, s = d.summary, z = inc.smoke;
    const draft = d.draft;
    const groups = overpassGroups(d.detections);
    const human = inc.human_action;
    const dirs = z ? [...new Set(z.toward_deg.map(compass))].join(", ") : "—";
    const kinds = (k) => d.receptors.filter((r) => k.includes(r.kind)).length;
    const replay = inc.mode === "replay";
    const panel = $("#incident-panel");
    panel.innerHTML = `
      <div class="detail-head">
        <button class="icon-btn" id="btn-back" aria-label="Back to incidents">${icon("back")}</button>
        <div><h2>${esc(d.site ? d.site.name : inc.site_id)}</h2><span class="note">${esc(d.site ? d.site.city + ", " + d.site.state : "")}</span></div>
      </div>
      ${replay ? `<div class="replay-banner">${icon("info")}REPLAY — historical data. Alerts go to the demo topic only.</div>` : ""}
      <div class="status-line"><span class="badge ${esc(inc.status)}">${esc(inc.status)}</span>
        <span class="note">${human ? `set by a person (${esc(human.status)}${human.note ? ": " + esc(human.note) : ""})` : "possible fire, computed by fixed rules"}</span></div>

      <div class="step">
        <div class="step-head"><span class="step-num">${icon("sat")}</span><h3>1 · Satellite detection<small>NASA FIRMS hotspots on the landfill outline</small></h3></div>
        <div class="stats">
          <div class="stat"><span>First detection</span><b>${esc(s.first_ist)}</b></div>
          <div class="stat"><span>Last detection</span><b>${esc(s.last_ist)}</b></div>
          <div class="stat"><span>Overpasses</span><b>${esc(inc.overpass_count)}</b></div>
          <div class="stat"><span>Max FRP</span><b>${esc(fmt(inc.max_frp_mw))} MW</b></div>
        </div>
        ${human ? "" : `<p class="reason">Rule: ${esc(inc.status_reason)}</p>`}
        <details><summary>Overpass timeline (${groups.length}) ${icon("chev")}</summary>
          <div class="scroll"><ul class="timeline">${groups.map((g) => `<li><b>${esc(g.acq_ist)}</b> · ${esc(g.source)} (${esc(g.satellite)}) · ${g.n} pixel${g.n > 1 ? "s" : ""} · ${esc([...g.tiers].join("/"))} · max FRP ${esc(fmt(g.maxFrp))} MW</li>`).join("")}</ul></div>
        </details>
      </div>

      <div class="step">
        <div class="step-head"><span class="step-num">${icon("wind")}</span><h3>2 · Smoke screening sector<small>From hourly wind. Not a pollution forecast.</small></h3></div>
        <div class="stats">
          <div class="stat wide"><span>Smoke toward</span><b>${z ? (z.calm ? `Calm: ${esc(z.length_km)} km circle` : `${esc(dirs)} · ${esc(z.length_km)} km`) : "No wind data"}</b></div>
          <div class="stat wide"><span>Wind</span><b>${z ? `${esc(z.wind_hours.length)} h, mean ${esc(fmt(z.mean_speed_ms))} m/s` : "—"}</b>
            ${z ? `<div class="note">Open-Meteo grid point ${esc(fmt(z.wind_point_lat))}, ${esc(fmt(z.wind_point_lon))} · bearings ${esc(z.toward_deg.join("°, "))}° · half-angle ≤ ${esc(z.half_angle_deg)}°</div>` : ""}</div>
        </div>
        <div class="kind-row">
          <div><b>${kinds(["school", "kindergarten", "college"])}</b><span class="dot school"></span> schools / colleges</div>
          <div><b>${kinds(["hospital", "clinic"])}</b><span class="dot hospital"></span> hospitals / clinics</div>
        </div>
        <details><summary>Places inside the sector (${d.receptors.length}) ${icon("chev")}</summary>
          ${d.receptors.length ? `<div class="scroll">${d.receptors.map((r) => `<div class="rec"><span class="dot ${["hospital", "clinic"].includes(r.kind) ? "hospital" : "school"}"></span><span>${esc(r.name)}</span><small>${esc(r.kind)} · ${esc(r.distance_km)} km</small></div>`).join("")}</div>`
            : '<p class="empty">None in the sector.</p>'}
        </details>
      </div>

      <div class="step">
        <div class="step-head"><span class="step-num">${icon("pen")}</span><h3>3 · Alert draft<small>AI writes from computed facts only; 11 checks validate it</small></h3></div>
        <div id="draft-area">${renderDraft(draft)}</div>
      </div>

      <div class="step s-approve">
        <div class="step-head"><span class="step-num">${icon("shield")}</span><h3>4 · Human approval<small>Nothing is sent until a person approves</small></h3></div>
        <div class="actions">
          <button class="btn primary" id="btn-approve" ${draft && draft.validated ? "" : "disabled"}>${icon("shield")}Approve and send${replay ? " (demo topic)" : ""}</button>
          <button class="btn" id="btn-draft">${icon("pen")}${draft ? "Redraft with agent" : "Draft with agent"}</button>
        </div>
        ${draft && !draft.validated ? '<p class="note">Approve needs a validated draft.</p>' : ""}
        <div class="review-row"><span class="note">Mark as:</span>
          <button class="btn small" data-review="CONFIRMED">Confirmed</button>
          <button class="btn small" data-review="FALSE_ALARM">False alarm</button>
          <button class="btn small" data-review="CLOSED">Closed</button></div>
        <div id="action-msg" class="msg"></div>
        ${d.approvals.length ? `<div class="sent">Sent ${d.approvals.length} time${d.approvals.length > 1 ? "s" : ""}:<ul>${d.approvals.map((a) => `<li>${esc(a.approved_utc)} to the ${esc(a.topic)} topic${a.template_used ? " (template)" : ""}</li>`).join("")}</ul></div>` : ""}
      </div>`;
    bindDraftTabs(draft);
    $("#btn-back").addEventListener("click", closeIncident);
    $("#btn-draft").addEventListener("click", () => requestDraft(inc.incident_id, draft ? draft.created_utc : null));
    $("#btn-approve").addEventListener("click", () => approve(inc.incident_id, replay));
    $$("[data-review]", panel).forEach((b) => b.addEventListener("click", () => review(inc.incident_id, b.dataset.review)));
  }

  function renderDraft(draft) {
    if (!draft) return '<p class="empty">No draft yet. The agent writes text only from facts that code computed.</p>';
    const fails = draft.attempts.filter((a) => !a.passed && a.source !== "template");
    const checks = draft.report.checks;
    const passed = checks.filter((c) => c.passed).length;
    const failed = checks.filter((c) => c.passed === false).length;
    return `
      <div class="draft-meta">${draft.template_used ? '<span class="badge template">Template used</span>' : ""}
        ${draft.validated ? '<span class="pass">Validated</span>' : '<span class="fail">Not validated</span>'}
        <span>${esc(draft.model)}</span><span>${esc(draft.created_utc)}</span></div>
      ${fails.map((a) => `<div class="attempt-fail">Attempt ${esc(a.attempt)} rejected by the validator: ${esc(a.errors.join(" | "))}</div>`).join("")}
      <div class="seg draft-tabs">
        <button data-t="resident_advisory_en" class="active">Residents</button>
        <button data-t="resident_advisory_hi">Hindi</button>
        <button data-t="official_alert_en">Officials</button>
      </div>
      <div class="draft-text" id="draft-text"></div>
      <details><summary>Validator: <span class="check-score ${failed ? "fail" : "pass"}">${passed}/${checks.length} checks passed</span> ${icon("chev")}</summary>
        <ul class="checks">${checks.map((c) => `<li><span class="${c.passed === null ? "skip" : c.passed ? "pass" : "fail"}">${c.passed === null ? "SKIP" : c.passed ? "PASS" : "FAIL"}</span><span>${esc(c.check)}. ${esc(c.name)}${c.detail ? ` — ${esc(c.detail)}` : ""}</span></li>`).join("")}</ul>
      </details>`;
  }

  function bindDraftTabs(draft) {
    if (!draft) return;
    const show = (key) => {
      const txt = draft.draft[key];
      $("#draft-text").textContent = txt || (key === "resident_advisory_hi" ? "Hindi is switched off until a Hindi speaker reviews the template (MVP A4)." : "");
      $$(".draft-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.t === key));
    };
    $$(".draft-tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.t)));
    show("resident_advisory_en");
  }

  const msg = (html) => { const el = $("#action-msg"); if (el) el.innerHTML = html; };

  async function requestDraft(id, previous) {
    try {
      await post(`/incidents/${encodeURIComponent(id)}/draft`);
      msg('<span class="spinner"></span> The agent is drafting. The validator checks the text before you see it…');
      for (let i = 0; i < 40; i++) { // poll up to ~2 minutes (Lambda draft runs asynchronously)
        const d = await get(`/incidents/${encodeURIComponent(id)}`);
        if (d.draft && d.draft.created_utc !== previous) { renderIncident(d); toast(d.draft.validated ? "New draft ready and validated" : "New draft ready"); return; }
        await sleep(3000);
      }
      msg('<span class="fail">No draft after 2 minutes. Check the DraftFunction logs.</span>');
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  async function approve(id, replay) {
    const ok = await modal({ title: "Send this alert?", ok: "Approve and send",
      text: `The validated draft will be emailed now${replay ? " to the demo topic (replay)" : ""}. You are the person approving it.` });
    if (!ok) return;
    try {
      const r = await post(`/incidents/${encodeURIComponent(id)}/approve`);
      toast(`Sent to the ${r.topic} topic`);
      await openIncident(id);
      msg(`<span class="pass">Sent to the ${esc(r.topic)} topic</span> (message ${esc(r.message_id)}).`);
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); toast(e.message, true); }
  }

  async function review(id, status) {
    const note = await modal({ title: `Mark as ${status.replace("_", " ").toLowerCase()}`, text: "Add a short note for the record (optional).",
      input: true, placeholder: "Note", ok: "Save review" });
    if (note === null) return;
    try { await post(`/incidents/${encodeURIComponent(id)}/review`, { status, note }); await loadIncidents(); await openIncident(id); toast("Review saved"); }
    catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  // ------------------------------------------------------------------ backtest
  async function loadBacktest() {
    const el = $("#backtest");
    let b;
    try { b = await get("/backtest"); } catch (e) { el.innerHTML = `<p class="empty">No backtest available (${esc(e.message)}).</p>`; return; }
    const hits = b.events.filter((m) => m.detected).length;
    el.innerHTML = `<h2 class="view-title">Backtest</h2>
      <p class="view-sub">${hits} of ${b.events.length} documented fires detected. NASA FIRMS archive (standard processing). Detected = at least one
        PROBABLE incident in the window. Config hash <code>${esc(String(b.config_hash).slice(0, 12))}</code> · ${esc(b.freeze)}</p>
      ${b.events.map((m) => `<div class="card bt-card">
        <span class="bt-ic${m.detected ? "" : " miss"}">${icon(m.detected ? "flame" : "close")}</span>
        <div><h3>${esc(m.event_id)}</h3><span class="${m.detected ? "pass" : "fail"}">${m.detected ? "Detected" : "Missed"}</span>
          <span class="note"> · reported start ${esc(m.reported_start)}</span>
          <div class="stats">
            <div class="stat"><span>First detection</span><b>${esc(fmt(m.first_detection_ist))}</b></div>
            <div class="stat"><span>Δ days</span><b>${esc(fmt(m.delta_days_from_reported_start))}</b></div>
            <div class="stat"><span>Overpasses</span><b>${esc(m.overpasses_with_detections)}</b></div>
            <div class="stat"><span>Max FRP</span><b>${esc(fmt(m.max_frp_mw))} MW</b></div>
            <div class="stat wide"><span>Smoke zone · receptors</span><b>${esc(m.smoke_zone)} · ${esc(m.receptor_count)}</b></div>
          </div></div></div>`).join("")}
      <div class="section-label">Alerts in windows with no reported fire</div>
      <p class="note">Monsoon windows. No news report does not prove there was no fire, so these are not called false positives.</p>
      <div class="card"><table><thead><tr><th>Site</th><th>Window</th><th>Matched</th><th>Cand.</th><th>Prob.</th></tr></thead>
      <tbody>${b.quiet_windows.map((q) => { const st = q.incidents.map((i) => i.status);
        return `<tr><td>${esc(q.site_id)}</td><td>${esc(q.start)} to ${esc(q.end)}</td><td>${esc(q.matched)}</td><td>${st.filter((x) => x === "CANDIDATE").length}</td><td>${st.filter((x) => x === "PROBABLE").length}</td></tr>`; }).join("")}</tbody></table></div>`;
  }

  // ------------------------------------------------------------------ views, sheet, boot
  function showView(view) {
    $$(".nav-btn").forEach((x) => x.classList.toggle("active", x.dataset.view === view));
    for (const v of ["incidents", "backtest", "sites", "about"]) $(`#view-${v}`).classList.toggle("hidden", v !== view);
    if (view === "backtest" && !$("#backtest").innerHTML) loadBacktest();
  }
  const SHEET = ["collapsed", "normal", "expanded"];
  function setSheet(state) {
    const p = $("#side");
    p.classList.remove("collapsed", "expanded");
    if (state !== "normal") p.classList.add(state);
    setTimeout(() => map.invalidateSize(), 380);
  }
  const sheetState = () => { const p = $("#side"); return p.classList.contains("collapsed") ? "collapsed" : p.classList.contains("expanded") ? "expanded" : "normal"; };
  $("#sheet-handle").addEventListener("click", () => setSheet(SHEET[(SHEET.indexOf(sheetState()) + 1) % 3]));
  $$(".nav-btn").forEach((t) => t.addEventListener("click", () => {
    const already = t.classList.contains("active");
    if (isMobile() && already) { setSheet(sheetState() === "collapsed" ? "normal" : "collapsed"); return; }
    showView(t.dataset.view);
    if (isMobile() && sheetState() === "collapsed") setSheet("normal");
  }));
  $("#legend-toggle").addEventListener("click", () => $(".legend").classList.toggle("open"));
  $("#btn-refresh").addEventListener("click", async () => {
    await Promise.all([loadHealth(), loadIncidents()]);
    if (selected) openIncident(selected);
    toast("Updated");
  });

  const hideSplash = () => $("#splash").classList.add("done");
  setTimeout(hideSplash, 5000); // failsafe: never leave the splash up if a request hangs
  (async () => {
    const minSplash = sleep(900);
    await Promise.all([loadHealth(), loadSites()]);
    await loadIncidents();
    await minSplash;
    hideSplash();
    map.invalidateSize();
    if (!location.hash) map.fitBounds(INDIA, fitPadding());
    const m = location.hash.match(/^#incident=(.+)$/); // deep link, e.g. #incident=brahmapuram-kochi-20230302T1635
    if (m) openIncident(decodeURIComponent(m[1]));
    setInterval(loadHealth, 60000);
  })();
})();
