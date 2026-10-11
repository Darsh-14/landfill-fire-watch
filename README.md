# WeSave

**Satellite hotspot screening for Indian landfills, with human-approved alerts for the people downwind.**
WeMakeDevs × AWS "Environmental Hacks" · Track: **Waste and Energy** · Licence: Apache-2.0 (code), ODbL (OSM-derived data).

## The problem

Fires at Indian landfills send smoke into dense neighbourhoods:

- **Deonar, Mumbai (Jan 2016):** satellites detected fire from 27 January; it burned for about four days and
  more than 70 schools closed (NASA Earth Observatory).
- **Ghazipur, Delhi (28 Mar 2022):** a massive fire broke out in the afternoon (Down To Earth).
- **Brahmapuram, Kochi (Mar 2023):** the fire started on 2 March; smoke spread up to about 10 km and classes
  for younger students were suspended (Gulf News).

India's satellite fire alert system is built for forests: the Forest Survey of India's FAST system "filters out
all fires other than forest fires" (FSI, FAST 3.0 technical note, 2019). We found no public service that tells a
city duty officer, or the schools downwind, that a landfill is showing a satellite hotspot. This project is that
screening service. Every claim we make is listed with its source in [`docs/claims.md`](docs/claims.md).

## How it works

```
 EventBridge Scheduler (rate 3 hours)
          │
          ▼
 NASA FIRMS (4 NRT feeds, India) ──► Lambda: scan ──► S3 (raw CSV + SHA-256)
                                       │
                                       ├─ match hotspots to landfill outlines (pixel-sized buffer)
                                       ├─ group into incidents: CANDIDATE / PROBABLE (fixed rules)
                                       ├─ Open-Meteo wind ─► smoke screening sector
                                       ├─ schools / hospitals inside the sector (cached OSM)
                                       └─ DynamoDB (scans, detections, incidents)

 Dashboard (Amplify) ──► API Gateway HTTP API ──► Lambda: api
                              POST draft   ──► Lambda: draft (Strands Agents + Amazon Bedrock)
                                                 read-only tools → validator (11 checks) → retry → template
                              POST approve ──► SNS: demo topic (replays) or live topic ──► email
```

### What code decides, and what the model writes

| Decided by deterministic Python (tested) | Written by the model (checked) |
|---|---|
| Whether a hotspot matches a landfill (outline buffered by half the pixel size + 100 m) | A short resident advisory (English; Hindi path built but switched off until reviewed) |
| Confidence tier (VIIRS l/n/h, MODIS 0–100) and static-source flags | An official alert for the fire service and pollution board |
| Incident grouping (36 h gap) and status: CANDIDATE, PROBABLE | — |
| Smoke screening sector from hourly wind (toward = from + 180°) | — |
| Which schools and hospitals are inside the sector, and how far | — |
| Every number in the text (`facts_used` must equal the computed facts exactly) | — |

The model only sees tool outputs. A validator rejects any draft that names a place not in the computed list,
changes a number, says "confirmed" before a person confirmed it, makes health or AQI claims, cites a rule that a
person has not verified, or drops the `[REPLAY]` label. It gets one retry with the error list; after that a
fixed template filled with the computed facts is used, and the UI says "Template used". **Nothing is sent until
a person presses Approve** (admin token), and replays can only go to the demo topic.

## Backtest (frozen config, first full run)

Rules and thresholds were frozen before the first run (config hash `264d3761…`, `data/config_freeze.yaml`).
Two rule details were decided by the team before any backtest result was seen: rows from the same satellite
at most 10 minutes apart count as one overpass, and static-land-source pixels can make an incident CANDIDATE
but not PROBABLE. NASA FIRMS archive (standard processing); detected = at least one PROBABLE incident.
One change after the freeze, recorded in `data/config_freeze.yaml`: the live scan window `SCAN_DAY_RANGE` went
from 1 to 2 days on 11 Oct, because FIRMS returns only the current UTC date for 1 and the first AWS scan missed
the previous night's VIIRS passes. The backtest does not read it, so the results below are unchanged.

| Event | Reported start | Sources | Detected | First detection (IST) | Δ days | Passes with heat in the window (all incidents) | Max FRP (MW) | Smoke zone at PROBABLE | Receptors in zone |
|---|---|---|---|---|---|---|---|---|---|
| deonar-2016 | 2016-01-27 | VIIRS S-NPP, MODIS | yes | 2016-01-28 02:45 | +1 | 12 | 49.61 | toward SSW, ESE, SE, SSE; 10 km | 217 |
| ghazipur-2022 | 2022-03-28 | VIIRS S-NPP, NOAA-20, MODIS | **no (miss)** | — | — | 1 | 1.68 | — | — |
| brahmapuram-2023 | 2023-03-02 | VIIRS S-NPP, NOAA-20, MODIS | yes | 2023-03-02 22:05 | 0 | 13 | 27.1 | toward N, WNW, W; 10 km | 404 |

**The miss:** at Ghazipur the satellites recorded heat on the landfill on only one overpass (NOAA-20, 01:25 IST on
29 March, two nominal pixels, FRP ≤ 1.7 MW), so the system raised a CANDIDATE, not a PROBABLE. The archive has
data for that day (over 10,000 India-wide detections), so this is a real miss of a short fire, not a data gap.
We did not change any rule after seeing it.

**Alerts in windows with no reported fire:** 0 incidents in all six 30-day monsoon windows (15 Jul + 30 days, the
year before and after each event). Monsoon cloud also hides fires, so this is weak evidence; no news report does
not prove there was no fire, so we do not call these false positives. Full output: [`out/backtest.md`](out/backtest.md).

**History stat** ([`out/history.md`](out/history.md)): satellite *detection-days* from 1 Jan 2019 to 30 Jun 2026
(VIIRS S-NPP archive, the same sensor every year) — Deonar 11, Brahmapuram 10, Ghazipur 2. A detection-day is a
day with at least one hotspot on the outline; it is not a count of fires.

## Limits

- Detects surface fires only. Fires that smoulder underground can be missed.
- Pixel size is about 375 m (VIIRS) to 1 km or more (MODIS). A hotspot can come from a nearby heat source.
- Satellites pass a few times a day. Cloud and thick smoke can block detection.
- A detection is not a confirmation. A person must check.
- The smoke zone is a screening sector from wind direction. It is not a pollution forecast.

Also: 30 landfills are monitored. 11 come from the project's candidate list (five other candidates had no usable
OpenStreetMap outline); their outlines were checked on satellite imagery by the AI coding agent at the team's
request, not yet by a team member ([`docs/site-review.md`](docs/site-review.md)). 19 more were found by
`scripts/discover_sites.py`: every named OSM landfill in India of at least 10 ha that is not industrial waste by name
(ash ponds, slag, mine tailings, coal and ore dumps are excluded) and not already monitored. Nine of them are 10 to
20 ha, smaller than one VIIRS pixel (about 14 ha), so heat from neighbouring land is more likely to be matched to
them. Those 19 outlines are not checked yet and show dashed on the map ([`data/sites_discovery_report.yaml`](data/sites_discovery_report.yaml)). No rule text is verified yet, so
the agent cites none ([`data/rules.yaml`](data/rules.yaml)). The admin token is a demo control, not production
authentication. Hindi drafts are off until a Hindi speaker reviews them.

## AWS services

| Service | Use |
|---|---|
| Amazon EventBridge Scheduler | `rate(3 hours)` trigger for the scan |
| AWS Lambda (Python 3.13) | `scan`, `api`, `draft` functions |
| Amazon DynamoDB (on-demand) | scans, detections, incidents, drafts, approvals |
| Amazon S3 | raw FIRMS CSVs with SHA-256 metadata, backtest JSON |
| Amazon Bedrock | the drafting model, called through Strands Agents |
| Amazon SNS | live and demo email topics (sent only on approval) |
| Amazon API Gateway (HTTP API) | dashboard API, throttled to 10 req/s, burst 20 |
| AWS Systems Manager Parameter Store | FIRMS key and admin token (SecureString) |
| Amazon CloudWatch Logs | JSON-line logs, including agent tool calls and validator results |
| AWS Amplify Hosting | the static dashboard |

**AWS open-source tools used:** [Strands Agents SDK](https://github.com/strands-agents/sdk-python) (agent, tools,
structured output, Bedrock provider) and [AWS SAM CLI](https://github.com/aws/aws-sam-cli) (deployment).

**AI coding tools used:** Claude Code (Anthropic's Claude) wrote the code, tests and docs with the team, and did the
satellite-imagery check of the event-site outlines at the team's request.

## How to run

```bash
make setup                 # venv + dependencies (Python 3.13)
make check                 # ruff + cfn-lint + all tests (AWS paths run on moto; the agent runs on a scripted model)
cp .env.example .env       # add FIRMS_MAP_KEY (free key from NASA FIRMS)
make backtest              # out/backtest.md (refuses to run unless outlines are checked and config is frozen)
make replay EVENT=brahmapuram-2023
make draft INCIDENT=brahmapuram-kochi-20230302T1635   # local fake model: a rejected draft, retry, validator report
make scan-local            # one real live scan into out/store/
make api-local             # local API on :8001 (approvals go to out/outbox/, not SNS)
make web                   # dashboard on http://localhost:8000
```

Deploy to AWS (ap-south-1): see **[`docs/deploy.md`](docs/deploy.md)** — SSM parameters, budget alarm,
`make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=...`, seeding, Amplify, and an end-to-end check script.
Lambda packages are built from Linux wheels without Docker (`make lock`, `make package`).

## Repository

`src/lfw/` detection core, smoke, receptors, store, agent · `handlers/` Lambda entry points · `scripts/` data
builders, backtest, deploy helpers · `web/` dashboard · `data/` sites, receptors, events, rules, sources ·
`tests/` (fixtures are real API samples) · `docs/` spec, claims, evidence, writeup, demo script.

## Credits and licences

**Data**
- Fire data: We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management
  System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for
  Earth observations (LANCE) (https://earthdata.nasa.gov/lance) and NASA's Earth Science Data and Information
  System (ESDIS).
- Landfill outlines, schools, hospitals, place search: © OpenStreetMap contributors, ODbL 1.0
  (https://www.openstreetmap.org/copyright), via the Overpass API and Nominatim. `data/sites/` and
  `data/receptors/` are ODbL; see [`data/LICENSE-DATA.md`](data/LICENSE-DATA.md).
- Wind: Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0 (free non-commercial use).
- Outline review imagery (not redistributed): Esri World Imagery and Wayback — Esri, Maxar, Earthstar Geographics,
  and the GIS User Community.
- Map tiles in the dashboard: © OpenStreetMap contributors.

**Software** (licence from each package's metadata)

| Library / tool | Licence |
|---|---|
| Strands Agents SDK (`strands-agents`) | Apache-2.0 |
| boto3 | Apache-2.0 |
| httpx | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| PyYAML | MIT |
| Shapely | BSD-3-Clause |
| NumPy | BSD-3-Clause (bundled parts under 0BSD, MIT, Zlib and others) |
| Leaflet 1.9.4 (cdnjs) | BSD-2-Clause |
| pytest | MIT |
| Pillow (outline review images only) | MIT-CMU |
| uv (Linux dependency locks) | MIT OR Apache-2.0 |
| cfn-lint | MIT-0 |
| AWS SAM CLI, AWS CLI | Apache-2.0 |
| gitleaks (secret scan) | MIT |

Code in this repository: Apache-2.0 ([`LICENSE`](LICENSE)).
