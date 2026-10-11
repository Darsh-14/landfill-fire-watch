/* WeSave dashboard. Plain JS + Leaflet. All decisions come from the API (code);
   this page only displays them and lets the duty officer write, send and review alerts. */
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
  // Per-viewer conveniences (theme, hidden layers). Storage can be blocked: everything works without it.
  const pref = {
    get(k, d) { try { const v = localStorage.getItem(`wesave_${k}`); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(`wesave_${k}`, JSON.stringify(v)); } catch (_) { /* ignore */ } },
  };

  // ------------------------------------------------------------------ plain-language labels
  // Display names only; the statuses themselves are computed by the API's fixed rules.
  const STATUS = {
    PROBABLE: ["Probable fire", "Seen on at least 2 satellite passes within 24 hours, or one strong high-confidence hotspot."],
    CANDIDATE: ["Possible fire", "A satellite saw heat at the site. Not yet strong enough to be probable."],
    CONFIRMED: ["Confirmed fire", "A person confirmed this fire."],
    FALSE_ALARM: ["False alarm", "A person marked this as a false alarm."],
    CLOSED: ["Closed", "A person closed this incident."],
  };
  const statusName = (s) => (STATUS[s] || [s])[0];
  const TIER_NAME = { high: "high", nominal: "medium", low: "low" };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function day(ist) { // "2023-03-02 22:05 IST" -> "2 Mar 2023"
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ist || "");
    return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : fmt(ist);
  }
  function when(ist) { // "2023-03-02 22:05 IST" -> "2 Mar 2023, 22:05"
    const m = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})/.exec(ist || "");
    return m ? `${day(m[1])}, ${m[2]}` : fmt(ist);
  }
  const fromUtc = (utc) => new Date(utc).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) + " IST";
  const DIRS = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest", "west", "west-northwest", "northwest", "north-northwest"];
  const compass = (deg) => DIRS[Math.floor(((deg % 360) / 22.5) + 0.5) % 16];
  const listWords = (a) => (a.length < 2 ? a.join("") : `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}`);

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
      t = await modal({ title: "Duty officer sign-in", text: "Enter the admin token. Demo control, not production authentication.",
        input: true, type: "password", placeholder: "Admin token", ok: "Continue" });
      if (t) { try { sessionStorage.setItem("lfw_admin_token", t); } catch (_) { /* ignore */ } }
    }
    return t;
  }
  async function post(path, body) {
    const t = await token();
    if (!t) throw new Error("Sign-in needed");
    const r = await fetch(API + path, { method: "POST", headers: { "content-type": "application/json", "x-admin-token": t },
      body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) { try { sessionStorage.removeItem("lfw_admin_token"); } catch (_) {} }
    if (!r.ok) throw new Error(r.status === 401 ? "Wrong admin token" : (data.error || `HTTP ${r.status}`));
    return data;
  }

  // ------------------------------------------------------------------ map
  const map = L.map("map", { zoomControl: false }).setView([20.6, 79.5], 5);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    // Licence-required attribution, visible on every screen (OSM ODbL, Open-Meteo CC BY 4.0, NASA FIRMS).
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL) · '
      + 'Fire data <a href="https://earthdata.nasa.gov/firms">NASA FIRMS</a> · '
      + '<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a> (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>)',
  }).addTo(map);
  const zoomClass = () => document.getElementById("map").classList.toggle("lowzoom", map.getZoom() < 8);
  map.on("zoomend", zoomClass); zoomClass();
  const pinLayer = L.layerGroup().addTo(map);
  // Toggleable map layers; an open incident draws into the last four.
  const LAYERS = { sites: L.layerGroup(), hotspots: L.layerGroup(), smoke: L.layerGroup(), schools: L.layerGroup(), hospitals: L.layerGroup() };
  const hidden = new Set(pref.get("hidden_layers", []));
  for (const [k, g] of Object.entries(LAYERS)) if (!hidden.has(k)) g.addTo(map);
  function setLayer(k, on) {
    if (on) LAYERS[k].addTo(map); else map.removeLayer(LAYERS[k]);
    if (on) hidden.delete(k); else hidden.add(k);
    pref.set("hidden_layers", [...hidden]);
    const b = $(`.layer[data-layer="${k}"]`);
    if (b) b.setAttribute("aria-pressed", String(on));
  }
  const TIER = { high: ["#e8553e", "#ffb3a6"], nominal: ["#f39a3c", "#ffd29a"], low: ["#f3e27a", "#fff6c2"] };
  const KIND_COLOR = { school: "#5b8cff", kindergarten: "#5b8cff", college: "#5b8cff", hospital: "#ff6b6b", clinic: "#ff6b6b" };
  const fly = (bounds, opts) => (REDUCE ? map.fitBounds(bounds, { ...opts, animate: false }) : map.flyToBounds(bounds, { ...opts, duration: 1.1 }));

  function pixelBounds(d) {
    // Square sized to the pixel: scan (across track) x track, in km, centred on the hotspot.
    const dLat = (d.track_km / 2) / 111.32;
    const dLon = (d.scan_km / 2) / (111.32 * Math.cos(d.lat * Math.PI / 180));
    return [[d.lat - dLat, d.lon - dLon], [d.lat + dLat, d.lon + dLon]];
  }
  function fitPadding() {
    // Keep fitted content clear of the floating panel (desktop) or the bottom sheet (mobile).
    if (isMobile()) {
      const st = sheetState(); // the sheet's target height, not mid-transition
      const sheet = st === "collapsed" ? 150 : st === "expanded" ? window.innerHeight - 140 : 0.56 * window.innerHeight;
      return { paddingTopLeft: [16, 110], paddingBottomRight: [16, Math.round(sheet) + 16] };
    }
    const panel = document.body.classList.contains("panel-off") ? 0 : $("#side").offsetWidth;
    return { paddingTopLeft: [panel + 40, 80], paddingBottomRight: [70, 40] };
  }
  // Whole monitored area (all sites span roughly 8-32 N, 68-92 E), framed clear of the panel or sheet.
  const INDIA = [[8, 68.5], [31.5, 91.5]];
  const showIndia = () => fly(INDIA, fitPadding());

  // ------------------------------------------------------------------ status (data age + sensors, always visible)
  async function loadHealth() {
    const el = $("#status-strip");
    try {
      const h = await get("/health");
      if (!h.last_scan_utc) { el.innerHTML = `<span class="age">No satellite check yet</span><span>Satellites: <b>${esc(h.sources)}</b></span>`; return; }
      const time = esc(h.last_scan_ist.split(" ")[1]);
      const mins = Number(h.minutes_ago);
      const ago = mins < 1 ? "just now" : mins < 60 ? `${mins} min ago` : `${Math.round(mins / 60)} h ago`;
      const stale = mins > 6 * 60;
      el.innerHTML = `<span class="age${stale ? "" : " fresh"}">${stale ? "Out of date · " : ""}Checked ${time} IST · ${esc(ago)}</span>
        <span>Satellites: <b>${esc(h.sources)}</b></span>
        ${h.latest_detection_utc ? `<span>Newest data: <b>${esc(fromUtc(h.latest_detection_utc))}</b></span>` : ""}`;
    } catch (e) {
      el.innerHTML = '<span class="stale">Cannot reach the server. Data age unknown.</span>';
    }
  }

  // ------------------------------------------------------------------ sites
  let SITES = [];
  const siteOf = (id) => SITES.find((s) => s.site_id === id);
  const siteName = (id) => (siteOf(id) || { name: id }).name;
  const siteCenter = (s) => { try { return L.geoJSON(s.outline).getBounds().getCenter(); } catch (_) { return null; } };

  async function loadSites() {
    try { SITES = await get("/sites"); } catch (e) { SITES = []; }
    if (SITES.length) $("#site-count").textContent = `${SITES.length} Indian`;
    LAYERS.sites.clearLayers();
    for (const s of SITES) {
      L.geoJSON(s.outline, { style: { className: "site-outline", weight: 1.6, fill: true, fillOpacity: 0.04, dashArray: s.verified ? null : "4 4" } })
        .bindTooltip(`${esc(s.name)}, ${esc(s.city)}`).addTo(LAYERS.sites);
    }
  }

  function renderSites() {
    const active = new Set(INCIDENTS.filter((i) => i.mode === "live").map((i) => i.site_id));
    const shownSites = SITES.filter(matches);
    $("#site-list").innerHTML = `<h2 class="view-title">Landfills</h2>
      <p class="view-sub">${QUERY ? `${shownSites.length} of ${SITES.length} match` : `${SITES.length} landfills, checked every 3 hours.`}</p>
      ${shownSites.length ? shownSites.map((s) => `<button class="site-item${active.has(s.site_id) ? " has-inc" : ""}" data-site="${esc(s.site_id)}">
        <span class="inc-ic">${icon("pin")}</span>
        <span class="inc-main"><strong>${esc(s.name)}</strong><small>${esc(s.city)}, ${esc(s.state)}</small></span>
        <span class="${s.verified ? "verified" : "unverified"}" title="${s.verified ? "Outline checked on satellite imagery" : "Outline not checked on imagery yet"}">${s.verified ? "Outline checked" : "Outline not checked"}</span>
        <span class="inc-chev">${icon("chev")}</span></button>`).join("") : `<p class="empty">${SITES.length ? "No landfill matches this search." : "No landfills loaded."}</p>`}`;
    $$(".site-item").forEach((b) => b.addEventListener("click", () => {
      const s = siteOf(b.dataset.site);
      if (!s) return;
      fly(L.geoJSON(s.outline).getBounds(), { ...fitPadding(), maxZoom: 15 });
      if (isMobile()) setSheet("collapsed");
    }));
  }

  // ------------------------------------------------------------------ incidents
  let QUERY = "";
  const matches = (site) => !QUERY || `${site.name} ${site.city} ${site.state}`.toLowerCase().includes(QUERY);
  let INCIDENTS = [];
  let selected = null;
  const RANK = { CONFIRMED: 4, PROBABLE: 3, CANDIDATE: 2, CLOSED: 1, FALSE_ALARM: 0 };

  async function loadIncidents() {
    try { INCIDENTS = await get("/incidents"); } catch (e) { $("#incident-list").innerHTML = '<p class="empty">Cannot load fires. Try refresh.</p>'; return; }
    renderIncidentList();
    drawPins();
    renderSites();
  }
  function renderIncidentList() {
    const list = $("#incident-list");
    const shown = INCIDENTS.filter((i) => matches(siteOf(i.site_id) || { name: i.site_id, city: "", state: "" }));
    const live = shown.filter((i) => i.mode === "live");
    const replay = shown.filter((i) => i.mode === "replay");
    const row = (i) => `<button class="incident-item ${esc(i.status)}${i.incident_id === selected ? " selected" : ""}" data-id="${esc(i.incident_id)}">
        <span class="inc-ic">${icon("flame")}</span>
        <span class="inc-main">
          <span class="inc-title"><strong>${esc(siteName(i.site_id))}</strong>${i.mode === "replay" ? '<span class="badge replay">Replay</span>' : ""}</span>
          <span class="inc-meta"><span class="badge ${esc(i.status)}">${esc(statusName(i.status))}</span>${esc(day(i.first_ist))}</span>
        </span><span class="inc-chev">${icon("chev")}</span></button>`;
    // MVP §2.2 item 12: how many incidents a person has marked, per outcome.
    const count = (s) => INCIDENTS.filter((i) => i.human_status === s).length;
    list.innerHTML = `<h2 class="view-title">Fires</h2>
      <div class="section-label">Now</div>
      ${live.length ? live.map(row).join("") : QUERY ? '<p class="empty">No live fire matches this search.</p>' : `<div class="all-clear">${icon("shield")}<div><b>No fires detected</b><span>at the ${esc(SITES.length)} watched landfills</span></div></div>`}
      ${replay.length ? `<div class="section-label">Past fires · replays</div>${replay.map(row).join("")}` : ""}
      <div class="section-label">Checked by a person</div>
      <div class="review-counts">
        <div><b>${count("CONFIRMED")}</b><span>confirmed</span></div><div><b>${count("FALSE_ALARM")}</b><span>false alarm</span></div>
        <div><b>${count("CLOSED")}</b><span>closed</span></div><div><b>${INCIDENTS.filter((i) => !i.human_status).length}</b><span>waiting</span></div></div>`;
    $$(".incident-item", list).forEach((b) => b.addEventListener("click", () => openIncident(b.dataset.id)));
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
      const m = L.marker(c, { icon: L.divIcon({ className: "", iconSize: [30, 30], iconAnchor: [15, 15],
        html: `<div class="pin ${inc ? esc(inc.status) : "site"}"><span class="pin-dot">${icon("flame")}</span><span class="pin-label">${esc(s.name)}</span></div>` }), riseOnHover: true });
      if (inc) {
        m.bindPopup(`<b>${esc(statusName(inc.status))}</b> · ${esc(s.name)}, ${esc(s.city)}<br>${esc(when(inc.first_ist))}${inc.mode === "replay" ? " · replay" : ""}
          <br><span class="pop-link" data-open="${esc(inc.incident_id)}">Open</span>`);
        m.on("popupopen", (e) => { const a = e.popup.getElement().querySelector("[data-open]"); if (a) a.onclick = () => openIncident(a.dataset.open); });
      } else {
        m.bindTooltip(`${esc(s.name)} · no fire detected`);
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
      g.n += 1; g.tiers.add(TIER_NAME[d.tier] || d.tier);
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
    panel.innerHTML = '<p class="empty"><span class="spinner"></span> Loading</p>';
    $(".panel-body").scrollTop = 0;
    if (isMobile()) setSheet("normal");
    map.closePopup();
    try { history.replaceState(null, "", `#incident=${encodeURIComponent(id)}`); } catch (_) { /* file:// */ }
    let d;
    try { d = await get(`/incidents/${encodeURIComponent(id)}`); } catch (e) { panel.innerHTML = '<p class="empty">Cannot load this fire. Try refresh.</p>'; return; }
    renderIncident(d);
    drawIncident(d);
  }

  function closeIncident() {
    selected = null;
    clearIncident();
    $("#incident-panel").classList.add("hidden");
    $("#incident-list").classList.remove("hidden");
    $$(".incident-item").forEach((b) => b.classList.remove("selected"));
    try { history.replaceState(null, "", location.pathname); } catch (_) {}
    showIndia();
  }

  const clearIncident = () => ["hotspots", "smoke", "schools", "hospitals"].forEach((k) => LAYERS[k].clearLayers());
  function drawIncident(d) {
    clearIncident();
    const inc = d.incident;
    const bounds = L.latLngBounds([]);
    if (inc.smoke && inc.smoke.geometry_geojson) {
      const z = L.geoJSON(inc.smoke.geometry_geojson, { style: { color: "#f3b23c", weight: 1.2, fillColor: "#f3b23c", fillOpacity: 0.16, dashArray: "6 4" } })
        .bindTooltip("Smoke screening sector (wind direction only). Not a pollution forecast.").addTo(LAYERS.smoke);
      bounds.extend(z.getBounds());
    }
    for (const r of d.receptors) {
      L.circleMarker([r.lat, r.lon], { radius: 4, color: "#111", weight: 1, fillColor: KIND_COLOR[r.kind] || "#9aa1ad", fillOpacity: 0.95 })
        .bindTooltip(`${esc(r.name)} · ${esc(r.distance_km)} km`).addTo(["hospital", "clinic"].includes(r.kind) ? LAYERS.hospitals : LAYERS.schools);
    }
    for (const det of d.detections) {
      const [fill, stroke] = TIER[det.tier] || TIER.low;
      const rect = L.rectangle(pixelBounds(det), { color: stroke, weight: 1, fillColor: fill, fillOpacity: 0.5 })
        .bindTooltip(`Satellite hotspot · ${esc(when(det.acq_ist))} · ${esc(TIER_NAME[det.tier] || det.tier)} confidence${det.static ? " (static source)" : ""}`)
        .addTo(LAYERS.hotspots);
      bounds.extend(rect.getBounds());
    }
    const site = siteOf(inc.site_id);
    if (site) bounds.extend(L.geoJSON(site.outline).getBounds());
    if (bounds.isValid()) fly(bounds, fitPadding());
  }

  const progress = (steps) => `<ol class="progress">${steps.map(([label, done]) => `<li class="${done ? "done" : ""}"><i></i><span>${esc(label)}</span></li>`).join("")}</ol>`;

  function renderIncident(d) {
    const inc = d.incident, s = d.summary, z = inc.smoke;
    const draft = d.draft;
    const groups = overpassGroups(d.detections);
    const human = inc.human_action;
    const replay = inc.mode === "replay";
    const sent = d.approvals.length > 0;
    const toward = z && !z.calm ? listWords([...new Set(z.toward_deg.map(compass))]) : "";
    const kinds = (k) => d.receptors.filter((r) => k.includes(r.kind)).length;
    const [label, help] = STATUS[inc.status] || [inc.status, ""];
    const panel = $("#incident-panel");
    panel.innerHTML = `
      <div class="detail-head">
        <button class="icon-btn" id="btn-back" aria-label="Back">${icon("back")}</button>
        <div class="grow"><h2>${esc(d.site ? d.site.name : inc.site_id)}</h2><span class="note">${esc(d.site ? d.site.city + ", " + d.site.state : "")}</span></div>
        <button class="icon-btn" id="btn-link" title="Copy link to this fire" aria-label="Copy link to this fire">${icon("link")}</button>
      </div>
      ${replay ? `<div class="replay-banner">${icon("info")}REPLAY — historical data. Alerts go to the demo topic only.</div>` : ""}
      <div class="status-card ${esc(inc.status)}"><b>${esc(label)}</b><span>${esc(human ? `Marked by a person${human.note ? ": " + human.note : ""}` : help)}</span></div>
      ${progress([["Detected", true], ["Smoke area", !!z], ["Alert written", !!(draft && draft.validated)], ["Sent", sent]])}

      <section class="step">
        <div class="step-head"><span class="step-num">1</span><h3>What the satellites saw</h3></div>
        <div class="stats">
          <div class="stat"><span>First seen</span><b>${esc(when(s.first_ist))}</b></div>
          <div class="stat"><span>Last seen</span><b>${esc(when(s.last_ist))}</b></div>
          <div class="stat"><span>Satellite passes</span><b>${esc(inc.overpass_count)}</b></div>
          <div class="stat"><span>Peak heat</span><b>${esc(fmt(inc.max_frp_mw))} MW</b></div>
        </div>
        <details><summary>Details ${icon("chev")}</summary>
          ${human ? "" : `<p class="reason">Rule result: ${esc(inc.status_reason)}</p>`}
          <ul class="timeline">${groups.map((g) => `<li><b>${esc(when(g.acq_ist))}</b> · ${esc(g.source)} (${esc(g.satellite)}) · ${g.n} pixel${g.n > 1 ? "s" : ""}, ${esc([...g.tiers].join("/"))} confidence · ${esc(fmt(g.maxFrp))} MW</li>`).join("")}</ul>
        </details>
      </section>

      <section class="step">
        <div class="step-head"><span class="step-num">2</span><h3>Where smoke may go</h3></div>
        <p class="headline">${z ? (z.calm ? `Calm wind: up to ${esc(z.length_km)} km around the site` : `Toward the ${esc(toward)}, up to ${esc(z.length_km)} km`) : "No wind data"}</p>
        <div class="kind-row">
          <div><b>${kinds(["school", "kindergarten", "college"])}</b><span><i class="dot school"></i>schools</span></div>
          <div><b>${kinds(["hospital", "clinic"])}</b><span><i class="dot hospital"></i>hospitals</span></div>
        </div>
        <p class="fine">From wind direction only. Not a pollution forecast.</p>
        <details><summary>All ${d.receptors.length} places ${icon("chev")}</summary>
          ${d.receptors.length ? `<div class="scroll">${d.receptors.map((r) => `<div class="rec"><i class="dot ${["hospital", "clinic"].includes(r.kind) ? "hospital" : "school"}"></i><span>${esc(r.name)}</span><small>${esc(r.distance_km)} km</small></div>`).join("")}</div>`
            : '<p class="empty">None inside the area.</p>'}
          ${z ? `<p class="reason">Wind: ${esc(z.wind_hours.length)} hours, average ${esc(fmt(z.mean_speed_ms))} m/s (Open-Meteo, ${esc(fmt(z.wind_point_lat))}, ${esc(fmt(z.wind_point_lon))}).</p>` : ""}
        </details>
      </section>

      <section class="step">
        <div class="step-head"><span class="step-num">3</span><h3>Alert message</h3></div>
        <div id="draft-area">${renderDraft(draft)}</div>
      </section>

      <section class="step s-approve">
        <div class="step-head"><span class="step-num">4</span><h3>Send</h3></div>
        <button class="btn primary big" id="btn-approve" ${draft && draft.validated ? "" : "disabled"}>${icon("shield")}${replay ? "Send demo email" : "Send alert"}</button>
        <p class="fine">${draft && draft.validated ? (replay ? "Replay: goes to the demo email list only." : "Goes to the alert email list.") : "Write the alert first."}</p>
        <div id="action-msg" class="msg"></div>
        ${sent ? sentBlock(d.approvals) : ""}
        <details><summary>Mark this fire ${icon("chev")}</summary>
          <div class="review-row">
            <button class="btn small" data-review="CONFIRMED">Confirmed fire</button>
            <button class="btn small" data-review="FALSE_ALARM">False alarm</button>
            <button class="btn small" data-review="CLOSED">Closed</button></div>
        </details>
      </section>`;
    bindDraftTabs(draft);
    $("#btn-back").addEventListener("click", closeIncident);
    $("#btn-link").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); toast("Link copied"); } catch (_) { toast("Copy the address bar to share this fire"); }
    });
    $$("[data-draft]", panel).forEach((b) => b.addEventListener("click", () => requestDraft(inc.incident_id, draft ? draft.created_utc : null)));
    $("#btn-approve").addEventListener("click", () => approve(inc.incident_id, replay));
    $$("[data-review]", panel).forEach((b) => b.addEventListener("click", () => review(inc.incident_id, b.dataset.review)));
  }

  function sentBlock(approvals) {
    const last = approvals[approvals.length - 1];
    const many = approvals.length > 1;
    return `<div class="sent"><div>${icon("shield")}Sent ${many ? `${approvals.length} times · last ` : ""}${esc(fromUtc(last.approved_utc))}${last.topic === "demo" ? " · demo" : ""}</div>
      ${many ? `<details><summary>All sends ${icon("chev")}</summary>${approvals.map((a) => `<p class="reason">${esc(fromUtc(a.approved_utc))} · ${esc(a.topic)} topic${a.template_used ? " · template" : ""}</p>`).join("")}</details>` : ""}</div>`;
  }

  function renderDraft(draft) {
    if (!draft) {
      return `<p class="lead-sm">No alert written yet.</p>
        <button class="btn wide" data-draft>${icon("pen")}Write alert</button>
        <div id="draft-msg" class="msg"></div>`;
    }
    const checks = draft.report.checks;
    const failed = checks.filter((c) => c.passed === false).length;
    const rejected = draft.attempts.filter((a) => !a.passed && a.source !== "template");
    const tabs = [["resident_advisory_en", "Residents"], ...(draft.hindi_enabled ? [["resident_advisory_hi", "Hindi"]] : []), ["official_alert_en", "Officials"]];
    return `
      <div class="seg draft-tabs">${tabs.map(([k, l], n) => `<button data-t="${k}"${n ? "" : ' class="active"'}>${l}</button>`).join("")}</div>
      <div class="draft-text" id="draft-text"></div>
      <div class="check-line ${failed ? "bad" : "good"}">${icon(failed ? "warn" : "shield")}
        <span>${failed ? `Failed ${failed} of ${checks.length} safety checks` : `Passed all ${checks.length} safety checks`}</span>
        ${draft.template_used ? '<span class="badge template">Template used</span>' : ""}</div>
      <details><summary>Details ${icon("chev")}</summary>
        <ul class="checks">${checks.map((c) => `<li><span class="${c.passed === null ? "skip" : c.passed ? "pass" : "fail"}">${c.passed === null ? "SKIP" : c.passed ? "PASS" : "FAIL"}</span><span>${esc(c.name)}${c.detail ? ` — ${esc(c.detail)}` : ""}</span></li>`).join("")}</ul>
        ${rejected.map((a) => `<p class="reason">Attempt ${esc(a.attempt)} was rejected and rewritten: ${esc(a.errors.join(" | "))}</p>`).join("")}
        <p class="reason">Written by ${esc(draft.model)} · ${esc(fromUtc(draft.created_utc))}</p>
      </details>
      <button class="btn small ghost" data-draft>${icon("pen")}Rewrite</button>
      <div id="draft-msg" class="msg"></div>`;
  }

  function bindDraftTabs(draft) {
    if (!draft) return;
    const show = (key) => {
      $("#draft-text").textContent = draft.draft[key] || "";
      $$(".draft-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.t === key));
    };
    $$(".draft-tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.t)));
    show("resident_advisory_en");
  }

  const msg = (html, id = "action-msg") => { const el = $(`#${id}`); if (el) el.innerHTML = html; };

  async function requestDraft(id, previous) {
    try {
      await post(`/incidents/${encodeURIComponent(id)}/draft`);
      $$("[data-draft]").forEach((b) => { b.disabled = true; });
      msg('<span class="spinner"></span> Writing and checking the alert. This takes up to a minute.', "draft-msg");
      for (let i = 0; i < 40; i++) { // poll up to ~2 minutes (Lambda draft runs asynchronously)
        const d = await get(`/incidents/${encodeURIComponent(id)}`);
        if (d.draft && d.draft.created_utc !== previous) { renderIncident(d); toast(d.draft.validated ? "Alert ready" : "Alert written, but it did not pass the checks", !d.draft.validated); return; }
        await sleep(3000);
      }
      msg('<span class="fail">No alert after 2 minutes. Try again.</span>', "draft-msg");
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`, "draft-msg"); }
  }

  async function approve(id, replay) {
    const ok = await modal({ title: replay ? "Send demo email?" : "Send this alert?", ok: "Send",
      text: replay ? "This replay goes to the demo email list only." : "The alert will be emailed now. You are the person approving it." });
    if (!ok) return;
    try {
      const r = await post(`/incidents/${encodeURIComponent(id)}/approve`);
      toast(r.topic === "demo" ? "Demo email sent" : "Alert sent");
      await openIncident(id);
    } catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); toast(e.message, true); }
  }

  async function review(id, status) {
    const note = await modal({ title: statusName(status), text: "Add a note (optional).", input: true, placeholder: "Note", ok: "Save" });
    if (note === null) return;
    try { await post(`/incidents/${encodeURIComponent(id)}/review`, { status, note }); await loadIncidents(); await openIncident(id); toast("Saved"); }
    catch (e) { msg(`<span class="fail">${esc(e.message)}</span>`); }
  }

  // ------------------------------------------------------------------ backtest
  async function loadBacktest() {
    const el = $("#backtest");
    let b;
    try { b = await get("/backtest"); } catch (e) { el.innerHTML = '<p class="empty">Test results are not available.</p>'; return; }
    const hits = b.events.filter((m) => m.detected).length;
    const quietAlerts = b.quiet_windows.reduce((n, q) => n + q.incidents.length, 0);
    el.innerHTML = `<h2 class="view-title">Tested on past fires</h2>
      <div class="score"><b>${hits} of ${b.events.length}</b><span>documented fires found in archived satellite data</span></div>
      ${b.events.map((m) => { const s = siteOf(m.site_id); const year = String(m.reported_start).slice(0, 4);
        return `<div class="card bt-card">
        <span class="bt-ic${m.detected ? "" : " miss"}">${icon(m.detected ? "flame" : "close")}</span>
        <div><h3>${esc(s ? `${s.name}, ${s.city}` : m.event_id)} · ${esc(year)}</h3>
          <span class="${m.detected ? "pass" : "fail"}">${m.detected ? "Found" : "Missed"}</span>
          <div class="stats">
            <div class="stat"><span>Fire reported</span><b>${esc(day(m.reported_start))}</b></div>
            <div class="stat"><span>First seen</span><b>${esc(m.first_detection_ist ? when(m.first_detection_ist) : "—")}</b></div>
            ${m.detected ? `<div class="stat"><span>Days after report</span><b>${esc(fmt(m.delta_days_from_reported_start))}</b></div>
            <div class="stat"><span>Schools and hospitals in smoke area</span><b>${esc(m.receptor_count)}</b></div>`
              : `<div class="stat wide"><span>Why missed</span><b>Heat seen on only ${esc(m.overpasses_with_detections)} satellite pass</b></div>`}
          </div></div></div>`; }).join("")}
      <div class="card"><h3>Quiet periods</h3>
        <p class="note">${quietAlerts} alerts in ${b.quiet_windows.length} monsoon periods with no reported fire. Cloud also hides fires, so this is weak evidence.</p></div>
      <details class="card"><summary>Details ${icon("chev")}</summary>
        <p class="reason">NASA FIRMS archive (standard processing). Found = at least one probable fire in the window.
          Settings frozen before the first run: <code>${esc(String(b.config_hash).slice(0, 12))}</code> · ${esc(b.freeze)}</p>
        <table><thead><tr><th>Site</th><th>Period</th><th>Matched</th><th>Alerts</th></tr></thead>
        <tbody>${b.quiet_windows.map((q) => `<tr><td>${esc(siteName(q.site_id))}</td><td>${esc(q.start)} to ${esc(q.end)}</td><td>${esc(q.matched)}</td><td>${q.incidents.length}</td></tr>`).join("")}</tbody></table>
      </details>`;
  }

  // ------------------------------------------------------------------ views, sheet, boot
  function showView(view) {
    $$(".nav-btn").forEach((x) => x.classList.toggle("active", x.dataset.view === view));
    for (const v of ["incidents", "backtest", "sites", "about"]) $(`#view-${v}`).classList.toggle("hidden", v !== view);
    if (view === "backtest" && !$("#backtest").innerHTML) loadBacktest();
  }
  const SHEET = ["collapsed", "normal", "expanded"];
  function sheetState() { const p = $("#side"); return p.classList.contains("collapsed") ? "collapsed" : p.classList.contains("expanded") ? "expanded" : "normal"; }
  function setSheet(state) {
    const p = $("#side");
    p.classList.remove("collapsed", "expanded");
    if (state !== "normal") p.classList.add(state);
    setTimeout(() => map.invalidateSize(), 380);
  }
  $("#sheet-handle").addEventListener("click", () => setSheet(SHEET[(SHEET.indexOf(sheetState()) + 1) % 3]));
  $$(".nav-btn").forEach((t) => t.addEventListener("click", () => {
    const already = t.classList.contains("active");
    if (isMobile() && already) { setSheet(sheetState() === "collapsed" ? "normal" : "collapsed"); return; }
    showView(t.dataset.view);
    if (isMobile() && sheetState() === "collapsed") setSheet("normal");
  }));
  $("#legend-toggle").addEventListener("click", () => $(".legend").classList.toggle("open"));
  $$(".layer").forEach((b) => {
    b.setAttribute("aria-pressed", String(!hidden.has(b.dataset.layer)));
    b.addEventListener("click", () => setLayer(b.dataset.layer, hidden.has(b.dataset.layer)));
  });
  $("#btn-home").addEventListener("click", showIndia);
  $("#btn-panel").addEventListener("click", () => {
    if (isMobile()) { setSheet(sheetState() === "collapsed" ? "normal" : "collapsed"); return; }
    document.body.classList.toggle("panel-off");
    setTimeout(() => map.invalidateSize(), 320);
  });
  function applyTheme(t) {
    document.documentElement.dataset.theme = t;
    $("#btn-theme use").setAttribute("href", t === "light" ? "#i-moon" : "#i-sun");
    $('meta[name="theme-color"]').setAttribute("content", t === "light" ? "#eef0f3" : "#1b1e25");
  }
  // ?theme=light|dark in the link wins (handy for sharing or projecting); otherwise the viewer's last choice.
  const linkTheme = new URLSearchParams(location.search).get("theme");
  applyTheme(["light", "dark"].includes(linkTheme) ? linkTheme : pref.get("theme", "dark"));
  $("#btn-theme").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    applyTheme(t);
    pref.set("theme", t);
  });
  let searchTimer = null;
  $("#search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      QUERY = e.target.value.trim().toLowerCase();
      // Show the results: leave an open fire (map stays where it is) or the Tested/About pages.
      const view = $(".nav-btn.active").dataset.view;
      if (QUERY && (view === "backtest" || view === "about")) showView("sites");
      if (QUERY && selected) {
        selected = null;
        clearIncident();
        $("#incident-panel").classList.add("hidden");
        $("#incident-list").classList.remove("hidden");
      }
      renderIncidentList();
      renderSites();
    }, 120);
  });
  $("#search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const site = SITES.find(matches);
    if (!site) return;
    const inc = INCIDENTS.find((i) => i.site_id === site.site_id);
    if (inc) openIncident(inc.incident_id);
    else { fly(L.geoJSON(site.outline).getBounds(), { ...fitPadding(), maxZoom: 15 }); toast(`${site.name}: no fire detected`); }
  });
  document.addEventListener("keydown", (e) => {
    if (!$("#modal").classList.contains("hidden")) return; // the dialog handles its own keys
    const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); $("#search").focus(); }
    else if (e.key === "Escape" && typing) document.activeElement.blur();
    else if (e.key === "Escape" && selected) closeIncident();
  });
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
