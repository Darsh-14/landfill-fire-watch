# WeSave — MVP specification

Status: build spec for the hackathon MVP. Deadline: Sunday 11 Oct 2026, 8:00 PM IST. Target: submit by 7:00 PM IST.
Rules for the coding agent are in `/CLAUDE.md`. This file gives the details.

---

## 0. Assumptions (change them if they are wrong)

| # | Assumption | If it is wrong |
|---|---|---|
| A1 | Route is **Ship It**: deploy on AWS, region `ap-south-1` (Mumbai). | Build It route: run the same code with `STORE=local`, Ollama, SAM local. Video shows the AWS open-source tools. |
| A2 | Amazon Bedrock has a usable model in your account. | Use a Bedrock cross-region inference profile, or another region for Bedrock only. Check the Bedrock console. |
| A3 | Track is **Waste and Energy**. | Air track: change the README headline to "warn the people most exposed". |
| A4 | A Hindi speaker on the team reviews the Hindi template and drafts. | Ship English only. Do not ship unreviewed Hindi. |

---

## 1. Problem and users

**Problem.** Fires at Indian landfills send toxic smoke into dense neighbourhoods. Examples:
- **Deonar, Mumbai (Jan 2016):** about four days; more than 70 schools closed.
- **Ghazipur, Delhi:** large fire on 28 Mar 2022.
- **Brahmapuram, Kochi (Mar 2023):** smoke spread up to about 10 km; schools closed.

India's satellite fire alert system is designed for forests. No public service alerts people about landfill fires.

**Primary user: the city solid-waste officer or duty officer.** This person receives the incident, checks it, and approves the alerts.

**People who benefit (not the operator):**
- Residents, schools and hospitals downwind, through the resident welfare association.
- The fire service and the State Pollution Control Board, who receive the official alert.

**What changes for them.** Today they learn about a fire from smoke or the news. With this tool, the officer sees a satellite hotspot within hours of an overpass. The officer also sees which schools are downwind and has a draft alert ready to send.

---

## 2. MVP scope

### 2.1 Must have (P0–P4)

1. Monitor 15–25 named landfills, each with an outline polygon.
2. A scheduled scan every 3 hours fetches FIRMS detections for India and matches them to sites.
3. Group detections into incidents with status `CANDIDATE` or `PROBABLE`, using deterministic rules.
4. For each incident, compute a screening smoke sector from wind, and list the schools and hospitals in it.
5. A Strands agent drafts a resident advisory (English and Hindi) and an official alert (English) from computed facts only.
6. A validator checks each draft against the output contract. On failure: retry once, then use a fixed template.
7. A person approves the draft. Then SNS sends it by email.
8. Backtest: replay 3 documented fires. Report detection results and alerts in quiet windows.
9. A dashboard with a map, incidents, data age, the limits panel, drafts, and the approve button.

### 2.2 Should have (P5, only if P0–P4 pass)

10. **History stat:** count satellite detection-days per site over past years from the archive. Example: "Brahmapuram: N detection-days since 2019." Call it detection-days, never "fires".
11. `make verify`: re-download each source and check its SHA-256.
12. A person can mark an incident "confirmed" or "false alarm". The UI shows the count of each.

### 2.3 Out of scope

Login and accounts, SMS or WhatsApp sending, dispersion models, methane detection, drones, mobile apps, more than 25 sites.

---

## 3. Architecture

```
                 EventBridge Scheduler (rate 3 hours)
                              │
                              ▼
 FIRMS Area API ──► Lambda: scan ──► S3 (raw CSV, sha256)
 (4 NRT sources,        │
  India bbox)           ├─► detect.match()  (sites.yaml + polygons)
                        ├─► incidents.update()
                        ├─► wind.fetch() ─► smoke.sector()
                        ├─► receptors.in_sector() (cached OSM GeoJSON)
                        └─► DynamoDB (scans, detections, incidents)

 Web (Amplify Hosting) ──► API Gateway HTTP API (throttled) ──► Lambda: api
                                                                 │
                    POST /incidents/{id}/draft ─► Lambda: draft (Strands + Bedrock)
                                                   ├─ tools read DynamoDB only
                                                   ├─ contract validator
                                                   └─ fallback template
                    POST /incidents/{id}/approve (admin token) ─► SNS (live or demo topic)

 Local mode: same code, STORE=local, Ollama, `make web`.
```

---

## 4. Data sources

| Source | Used for | Access | Notes |
|---|---|---|---|
| NASA FIRMS Area API | Active fire detections (live and archive) | Free MAP_KEY | 1–5 days per call. 5,000 transactions per 10 min. |
| FIRMS data_availability | Archive coverage check | Same key | `/api/data_availability/csv/{KEY}/ALL` |
| Open-Meteo forecast | Live hourly wind | No key | CC BY 4.0. Credit it. |
| Open-Meteo archive | Historical hourly wind for the backtest | No key | Same licence. |
| OpenStreetMap via Overpass | Landfill outlines; schools and hospitals | No key | Scripts only. Cache in `data/`. ODbL credit. |
| Rule documents (SWM Rules 2026, CAQM direction) | Citations in official alerts | Download PDF | Store in S3 with SHA-256. |

**CAUTION:** Run these checks before P1:
1. Call `data_availability`. Confirm the archive covers Jan 2016, Mar 2022 and Mar 2023 for `VIIRS_SNPP_SP` and `MODIS_SP`.
2. Fetch one live CSV and one archive CSV. Save both in `tests/fixtures/`. Read the real column names.

---

## 5. Data models (pydantic)

```python
class Site(BaseModel):
    site_id: str            # "brahmapuram-kochi"
    name: str
    city: str
    state: str
    polygon_path: str       # data/sites/<site_id>.geojson
    polygon_source: Literal["osm", "manual"]
    osm_id: str | None
    exclusions: list[str] = []   # notes on known heat sources near the site
    verified_by: str | None      # person who checked the outline on a map

class Detection(BaseModel):
    key: str                # f"{source}|{acq_date}|{acq_time}|{lat:.4f}|{lon:.4f}"
    source: str             # e.g. VIIRS_SNPP_NRT
    satellite: str
    instrument: Literal["VIIRS", "MODIS"]
    lat: float
    lon: float
    acq_utc: datetime
    confidence_raw: str     # keep the original value
    confidence_tier: Literal["low", "nominal", "high"]
    frp_mw: float | None
    scan_km: float
    track_km: float
    daynight: str
    type_code: int | None   # archive only, if the field exists
    site_id: str | None
    match_distance_m: float | None
    mode: Literal["live", "replay"]

class Incident(BaseModel):
    incident_id: str        # f"{site_id}-{first_utc:%Y%m%dT%H%M}"
    site_id: str
    mode: Literal["live", "replay"]
    status: Literal["CANDIDATE", "PROBABLE", "CONFIRMED", "FALSE_ALARM", "CLOSED"]
    first_utc: datetime
    last_utc: datetime
    detection_keys: list[str]
    overpass_count: int     # distinct (satellite, acq_utc)
    max_frp_mw: float | None
    smoke: SmokeZone | None
    receptor_ids: list[str]
    human_action: HumanAction | None

class SmokeZone(BaseModel):
    computed_utc: datetime
    wind_hours: list[WindHour]   # hours used
    toward_deg: list[int]        # one per hour
    half_angle_deg: int
    length_km: float
    calm: bool
    geometry_geojson: dict       # union of sectors, or a circle if calm

class Receptor(BaseModel):
    receptor_id: str        # f"osm:{type}/{id}"
    name: str | None
    kind: Literal["school", "kindergarten", "college", "hospital", "clinic"]
    lat: float
    lon: float
    distance_km: float      # from the site centroid
```

DynamoDB: one on-demand table `lfw`, keys `pk` and `sk`.

| Item | pk | sk |
|---|---|---|
| Scan record | `SCAN` | `{utc_iso}` |
| Detection | `SITE#{site_id}` | `DET#{acq_utc}#{key}` |
| Incident | `INC#{incident_id}` | `META` |
| Draft | `INC#{incident_id}` | `DRAFT#{utc_iso}` |
| Approval | `INC#{incident_id}` | `APPROVAL#{utc_iso}` |

---

## 6. Deterministic logic

All values live in `config.py`. Each value has a reason comment.

### 6.1 Match a detection to a site

1. Load each site polygon. Project to local metres (equirectangular around the site centroid).
2. Compute the pixel half-size: `r = max(scan_km, track_km) * 1000 / 2`.
3. Buffer the polygon by `r + MATCH_MARGIN_M` (default 100 m).
4. The detection matches if its point is inside the buffered polygon. Store `match_distance_m` (0 if inside the original polygon).
5. If `type_code` is present and shows a static land source, set `confidence_tier = "low"` and flag it.
6. If more than one site matches, keep the nearest one.

**Reason:** a VIIRS pixel is about 375 m at nadir and grows toward the swath edge. A MODIS pixel is about 1 km or more. A fixed buffer would be wrong for one of them.

### 6.2 Confidence tier

- VIIRS: `l → low`, `n → nominal`, `h → high` (confirm the letters from the fixture).
- MODIS: `< 30 → low`, `30–79 → nominal`, `≥ 80 → high`.

### 6.3 Build incidents

1. Sort the matched detections for a site by time.
2. Join a detection to the open incident if the gap since `last_utc` is ≤ `INCIDENT_GAP_H` (default 36 h). If not, start a new incident.
3. Status:
   - `CANDIDATE`: at least 1 detection with tier `nominal` or `high`, **or** 2+ `low` detections from different overpasses.
   - `PROBABLE`: detections from ≥ 2 distinct overpasses within 24 h, **or** one `high` detection with `frp_mw ≥ FRP_HIGH_MW` (default 10).
   - `CONFIRMED`, `FALSE_ALARM`, `CLOSED`: set only by a person through the API.
4. Low-only single detections are stored. They do not create an incident.

### 6.4 Smoke screening sector

1. Get hourly wind at the site centroid for the next 6 hours (live), or for each hour with a detection plus 6 hours (replay).
2. For each hour: `toward = (wind_from + 180) % 360`.
3. Half-angle: 30° normally; 45° if the speed is < 2 m/s.
4. If the mean speed is < 1 m/s, mark `calm = true` and use a circle of radius 2 km.
5. Sector length: `SMOKE_LENGTH_KM` (default 10 km). Reason: Brahmapuram smoke was reported up to about 10 km away.
6. The zone is the union of the hourly sectors.

**WARNING:** This is a screening sector, not a dispersion model. The UI and every draft must say so.

### 6.5 Receptors

1. `scripts/build_receptors.py` queries Overpass once per site for `amenity` in `school, kindergarten, college, hospital, clinic` within 12 km. It saves `data/receptors/<site_id>.geojson`.
2. At run time, code selects the receptors inside the smoke zone and sorts them by distance.
3. Receptors without a name show as "Unnamed school (OSM)". Never invent a name.

---

## 7. Agent

### 7.1 Role

The agent turns computed facts into three texts. It does not decide anything.

### 7.2 Tools (Strands `@tool`, read-only)

| Tool | Returns |
|---|---|
| `get_incident(incident_id)` | Site, status, mode, times (UTC and IST), overpass count, max FRP |
| `get_smoke_zone(incident_id)` | Toward directions, half-angle, length, calm flag, wind hours |
| `list_receptors(incident_id)` | Receptors in the zone: id, name, kind, distance |
| `get_rule(rule_key)` | Verified rule quote, source title, URL, page |
| `get_limits()` | Fixed limits text (§9) |

### 7.3 Output contract

```python
class DraftBundle(BaseModel):
    resident_advisory_en: str = Field(max_length=700)
    resident_advisory_hi: str = Field(max_length=900)
    official_alert_en: str = Field(max_length=1800)
    rule_keys: list[str]
    receptor_ids: list[str]
    facts_used: FactsUsed

class FactsUsed(BaseModel):
    overpass_count: int
    first_detected_ist: str
    smoke_toward_deg: list[int]
    status: str
```

Use Strands structured output if the installed version supports it. In all cases, validate with pydantic.

### 7.4 Validator (`agent/contract.py`): reject the draft if any check fails

1. JSON parses into `DraftBundle`.
2. Each `rule_key` exists in `rules.yaml` with `verified: true`.
3. Each `receptor_id` is in the incident's receptor list.
4. Each receptor name that appears in any text belongs to a listed `receptor_id`.
5. `facts_used` equals the computed values exactly.
6. The word "confirmed" (any case) appears only if status is `CONFIRMED`.
7. Each text contains "possible fire" or "satellite hotspot".
8. The official alert contains the screening-sector sentence and the data-age sentence.
9. Health claims ("toxic levels", "dangerous AQI", a specific AQI number) appear only if a measured value was given as a tool output. MVP: no AQI tool, so these phrases are banned.
10. The Hindi text contains Devanagari characters.
11. For replay incidents, every text starts with `[REPLAY]`.

On failure: send the error list back to the model and retry once. If the retry fails, use `agent/fallback.py`: fixed English and Hindi templates filled with the computed facts. Show "Template used" in the UI. Log every validator result.

### 7.5 Prompt rules (system prompt summary)

- "Use only tool outputs. Do not add places, numbers or rules."
- "Say 'possible fire'. Never say 'confirmed' unless the status is CONFIRMED."
- "Residents: short, calm, practical. Close windows, avoid outdoor activity near the zone, protect children, older people and people with breathing illness."
- "Official alert: site, first detection time (IST), overpass count, smoke direction, receptors with distance, rule citations by key, limits."

---

## 8. API (HTTP API, throttled: 10 req/s, burst 20)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Returns the last scan time |
| GET | `/sites` | none | Sites with outline and last detection |
| GET | `/incidents?mode=live\|replay` | none | List incidents |
| GET | `/incidents/{id}` | none | Incident, smoke zone, receptors, latest draft |
| POST | `/incidents/{id}/draft` | admin token | Run the agent, store the draft and validator report |
| POST | `/incidents/{id}/approve` | admin token | Publish the approved draft to SNS. Replay incidents go to the demo topic only. |
| POST | `/incidents/{id}/review` | admin token | Body `{status: CONFIRMED\|FALSE_ALARM\|CLOSED, note}` |
| GET | `/backtest` | none | Latest backtest JSON (from S3) |

Admin token: header `x-admin-token`. Value in SSM `/lfw/admin_token`. This is a demo control, not production authentication. Say so in the README.

---

## 9. Web dashboard

**Layout:** a header with the status strip, a map on the left, an incident panel on the right.

1. **Status strip:** "Last scan: HH:MM IST (N min ago) · Sources: VIIRS S-NPP, NOAA-20, NOAA-21, MODIS · Sites monitored: N".
2. **Map:** site outlines; detections as squares sized to the pixel; smoke sector in a translucent colour; receptors as icons; OSM attribution.
3. **Incident list:** live incidents first, then replays with a "REPLAY — historical data" badge.
4. **Incident panel:** status badge; timeline of overpasses; max FRP; wind and direction; receptor table (name, type, km); a draft tab with English, Hindi and Official versions; validator report (pass/fail per check); "Template used" badge if any; Approve button; Review buttons.
5. **Backtest page:** results table from §10.
6. **Limits panel (always visible, fixed text):**
   - Detects surface fires only. Fires that smoulder underground can be missed.
   - Pixel size is about 375 m (VIIRS) to 1 km or more (MODIS). A hotspot can come from a nearby heat source.
   - Satellites pass a few times a day. Cloud and thick smoke can block detection.
   - A detection is not a confirmation. A person must check.
   - The smoke zone is a screening sector from wind direction. It is not a pollution forecast.

**Usability test:** ask one person outside the team to open the page and find which schools are downwind in the Brahmapuram replay. Fix whatever confuses them.

---

## 10. Backtest

### 10.1 Ground truth (`data/events.yaml`)

| event_id | Site | Reported start | Window to query | Sources for the date |
|---|---|---|---|---|
| deonar-2016 | Deonar, Mumbai | 2016-01-27 | 2016-01-24 → 2016-02-03 | NASA Earth Observatory |
| ghazipur-2022 | Ghazipur, Delhi | 2022-03-28 | 2022-03-25 → 2022-04-04 | Down To Earth |
| brahmapuram-2023 | Brahmapuram, Kochi | 2023-03-02 | 2023-02-27 → 2023-03-14 | Down To Earth; Gulf News; Deccan Herald (95% doused on 12 Mar) |

Store the source URL for each event in the YAML.

### 10.2 Quiet windows

For each event site, choose two 30-day windows in the monsoon (Jul–Sep) of other years. Count the incidents raised.

Report them as **"alerts in windows with no reported fire"**. Do not call them false positives. No news report does not prove no fire.

### 10.3 Metrics per event

- Detected: yes/no (≥ 1 `PROBABLE` incident in the window).
- First detection (IST), and the difference in days from the reported start.
- Overpasses with detections; max FRP.
- Smoke zone and receptor count on the first `PROBABLE` detection.

### 10.4 Output

`out/backtest.md` (table) and `out/backtest.json`. Show the table in the README and in the video.

**NOTE:** If an event is not detected, report it. A tool that shows its misses is more credible. Do not tune thresholds on the three events and then claim accuracy. Freeze `config.py` values before the first full run. Record any later change in the README.

---

## 11. Phase plan with acceptance criteria

Times are IST. Start Sat 17:30.

| Phase | Time | Work | Acceptance criteria |
|---|---|---|---|
| P0 | Sat 17:30–19:00 | Repo, Makefile, FIRMS key, fixtures, availability check, `events.yaml`, `sites.yaml` draft, `build_sites.py` | Fixtures saved. Archive coverage confirmed. 3 event sites have outlines that a person checked on a map. |
| P1 | Sat 19:00–23:30 | `firms.py`, `geo.py`, `detect.py`, `incidents.py`, `backtest.py`, tests | `make test` passes. `make backtest` produces a table for all 3 events. |
| P2 | Sat 23:30–Sun 03:00 | `wind.py`, `smoke.py`, `build_receptors.py`, agent, contract, fallback | `make draft` on the Brahmapuram replay gives a validated draft. A test proves that an invented school is rejected. |
| Sleep | Sun 03:00–08:00 | — | Sleep. Tired teams lose on execution. |
| P3 | Sun 08:00–11:30 | SAM template, deploy, scheduler, API, SNS (live + demo topics), SSM | The scheduled scan runs in AWS and writes a scan record. `/incidents` returns data. A demo email arrives. |
| P4 | Sun 11:30–14:30 | Dashboard, Amplify deploy, usability test | §9 items 1–6 work on the deployed URL. |
| P5 | Sun 14:30–16:00 | History stat, `make verify`, README, `claims.md` complete | README has all items in CLAUDE.md §10. |
| Video | Sun 16:00–18:30 | Record, edit, upload to YouTube | Video ≤ 3:00, shows AWS console. |
| Submit | Sun 18:30–19:00 | Writeup, AI tools list, submit | Submitted before 19:00. |

**Cut lines (in this order, if you are late at Sun 12:00):**
1. Drop the history stat.
2. Drop the review endpoint.
3. Drop Hindi (ship English only).
4. Serve the web from local `make web` in the video, and show the AWS backend only.

Never cut: the backtest, the validator, human approval, the limits panel.

---

## 12. AWS deployment

**`template.yaml` resources:**
- `ScanFunction`: `python3.13`, 512 MB, 120 s timeout. Event: `ScheduleV2`, `rate(3 hours)`.
- `ApiFunction`: `python3.13`, 256 MB, 15 s. Event: HTTP API, with routes from §8.
- `DraftFunction`: `python3.13`, 1024 MB, 120 s. Invoked by `ApiFunction` (async), or directly by the API route.
- Packaging without Docker: a `make package` target installs Linux wheels into `build/<function>/` (see CLAUDE.md §3), and `CodeUri` points there.
- `Table`: DynamoDB, `PAY_PER_REQUEST`.
- `Bucket`: S3 for raw CSV, source documents, backtest output, receptor cache.
- `LiveTopic`, `DemoTopic`: SNS. Email subscription as a parameter. Confirm the email.
- IAM: least privilege. Only `DraftFunction` gets `bedrock:InvokeModel`. Only `ApiFunction` gets `sns:Publish`.

**Secrets:** create these with the AWS CLI, not in the template:
```
aws ssm put-parameter --name /lfw/firms_map_key --type SecureString --value <KEY>
aws ssm put-parameter --name /lfw/admin_token --type SecureString --value <TOKEN>
```

**Cost control:** set an AWS Budget alert at USD 5. On-demand DynamoDB, 8 scans per day, and small Lambdas stay within free or near-free use. Bedrock calls happen only on a person's request.

**Bedrock:** enable model access in the console first. Set `BEDROCK_MODEL_ID` as a parameter. Check that the model is available in your region.

**Web:** build `web/config.js` with the API URL. Deploy the `web/` folder with Amplify Hosting (manual deploy).

---

## 13. Proof and honesty

- `data/sources.yaml`: each source document (URL, title, retrieved date, SHA-256, S3 key).
- `scripts/verify_sources.py` (`make verify`): download each source again, compare SHA-256, and print OK/CHANGED/UNREACHABLE.
- `data/rules.yaml` entry format:
  ```yaml
  - key: swm2026_dumpsite_fire_prevention
    text: "TODO(verify): exact English text"
    source_id: swm-rules-2026-gazette
    page: TODO
    verified: false      # set true only after a person reads the source
  ```
- `docs/claims.md`: every claim in the video, README or blog post, with its source and status.

| Claim | Source | Status |
|---|---|---|
| India's satellite fire alert system (FAST) filters out fires outside forests | PreventionWeb (World Bank) article; FSI paper | Verify it is still current. Say "designed for forests" if unsure. |
| Deonar 2016: about 4 days; more than 70 schools closed | NASA Earth Observatory | Sourced |
| Brahmapuram 2023: smoke up to about 10 km; schools closed | Gulf News; Onmanorama | Sourced |
| Fire services attended only 15 Brahmapuram fires in 5 years | The Hindu, 31 Mar 2023 (clipping) | Verify the original |
| About 3,000 landfills in India | CNN | Sourced (approximate) |
| CAQM direction on fire prevention at landfills and dumpsites (NCR) | caqm.nic.in PDF | Get the number and date |
| SWM Rules 2026 require fire prevention at dumpsites (Rule 15(4), Schedule IV) | Gazette (Hindi) | Verify the English text |

---

## 14. Demo video script (3:00)

| Time | Show | Say (summary) |
|---|---|---|
| 0:00–0:20 | Brahmapuram news photo + map of Kochi | "March 2023. A landfill fire covered Kochi in smoke for days. Schools closed." |
| 0:20–0:35 | Text card | "India watches forest fires from space. Nobody watches its landfills. We built that." |
| 0:35–0:55 | Dashboard, status strip, site list | "Every 3 hours, AWS pulls NASA satellite detections and checks 20 landfills." |
| 0:55–1:35 | Brahmapuram REPLAY: detections appear, status changes to PROBABLE, smoke sector, receptors | "Code decides. Two overpasses, so: probable fire. The wind blows west, so these 14 schools are in the zone." (Use the real numbers from your run.) |
| 1:35–2:05 | Draft tab: English, Hindi, Official; validator report; one rejected draft | "The agent writes the alerts. A validator rejects any place or number that code did not compute." |
| 2:05–2:20 | Approve, email arrives | "A person approves. Then it goes out." |
| 2:20–2:40 | Backtest table + limits panel | "We tested 3 real fires. Here are the results and our limits." |
| 2:40–2:55 | AWS console: EventBridge schedule, Lambda logs, DynamoDB items | "Built on AWS: EventBridge, Lambda, DynamoDB, S3, SNS, Bedrock with Strands." |
| 2:55–3:00 | Repo URL | "Open source. Link below." |

**AWS evidence shots (`local/aws-evidence.md (kept out of the repo)`).** Record each one; use 2–4 in the video:
1. EventBridge Scheduler: the `rate(3 hours)` schedule and its last run.
2. CloudWatch Logs: one scan run with JSON lines (detections fetched, matched, incidents updated).
3. DynamoDB: the scan record and one incident item.
4. S3: a raw FIRMS CSV with its SHA-256 metadata.
5. Bedrock and Strands: the draft Lambda log that shows the agent's tool calls and the validator result.
6. SNS: the approved [REPLAY] email in the inbox.
7. Terminal: `sam deploy` output with the stack outputs.

---

## 15. Writeup and blog outline

1. The problem in one paragraph, with the three fires.
2. The gap: forest alerts exist, landfill alerts do not.
3. How it works: diagram from §3.
4. What code decides and what the model writes.
5. Backtest results, including any miss.
6. Limits.
7. What we would do next: a city pilot; a ground-truth loop; more sites from official dumpsite lists.

---

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Archive does not cover an event | Check in P0. Replace the event with another documented one. Say so in the README. |
| No OSM outline for a site | Draw the outline in geojson.io from satellite imagery. Mark `polygon_source: manual`. |
| A nearby factory triggers detections | Add a note in `exclusions`. Show `match_distance_m`. A person reviews. |
| Bedrock is not available or is slow | Fallback template always works. Local Ollama for development. |
| Overpass is down or rate-limited | Run the receptor script early (P2). Commit the cache. |
| No live fire during judging | Expected. The status strip shows live scans. Replays are clearly labelled. |
| Hindi quality | A Hindi speaker reviews the template. Otherwise drop Hindi (cut line 3). |

---

## 17. Candidate sites (verify each one; do not trust this list blindly)

Event sites (required): Deonar (Mumbai), Ghazipur (Delhi), Brahmapuram (Kochi).

Other candidates: Kanjurmarg (Mumbai), Bhalswa (Delhi), Okhla (Delhi), Bandhwari (Gurugram), Perungudi (Chennai), Kodungaiyur (Chennai), Pirana (Ahmedabad), Dhapa (Kolkata), Jawahar Nagar (Hyderabad), Uruli Devachi (Pune), Bhandewadi (Nagpur), Dadumajra (Chandigarh), Mandur (Bengaluru).

For each site: find the OSM `landuse=landfill` outline. A person checks it on satellite imagery. Then set `verified_by`. Some sites may be closed or under remediation. Keep them, and note the status if known.

---

## 18. Final checklist before you submit

- [ ] Public repo; README complete; LICENSE (Apache-2.0); `data/LICENSE-DATA.md` (ODbL).
- [ ] Git history: first commit on or after 8 Oct 2026; many small commits; no rewritten history.
- [ ] Secret scan of the full git history is clean.
- [ ] Video under 3:00 on YouTube (public or unlisted); the link opens in a signed-out browser; shows the AWS console shots in `local/aws-evidence.md (kept out of the repo)`; shows the limits panel.
- [ ] Every feature in `docs/writeup.md` appears in the video.
- [ ] `docs/writeup.md` covers the problem, the build, where AWS fits, the track, and the AI coding tools used.
- [ ] Backtest table in the README matches `out/backtest.md`.
- [ ] Every claim in the video is in `docs/claims.md` with status "Sourced" or "Verified".
- [ ] AI coding tools listed (Claude Code; Claude).
- [ ] Credits: NASA FIRMS (copy their acknowledgment text), OpenStreetMap (ODbL), Open-Meteo (CC BY 4.0).
- [ ] No secrets in git history.
- [ ] Optional: submit a blog post for the blog prize.
