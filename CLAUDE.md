# CLAUDE.md — WeSave

Read this file first. Read `docs/MVP.md` for the full specification.
This file holds the rules you must follow. `docs/MVP.md` holds the details.

## 1. What this project is

WeSave detects possible fires at Indian landfills from NASA satellite data.
It then tells the people downwind, and the officials who must act.

- Hackathon: WeMakeDevs × AWS "Environmental Hacks". Deadline: **Sunday 11 Oct 2026, 8:00 PM IST**.
- Track: Waste and Energy.
- The gap: India's satellite fire alert system serves forests. It does not alert anyone about landfill fires.
- Judges see only a public repo, a 3-minute video, and a short writeup. The video must show AWS.

## 2. Non-negotiable rules

Obey these rules in every task. If a task conflicts with a rule, stop and tell the user.

1. **Code decides. The model explains.** Only deterministic Python decides if a detection is a possible fire, the incident status, the smoke zone, and the list of affected places. The language model only writes text from facts that code computed.
2. **Never invent data.** Do not type coordinates, polygons, dates, field names, rule text, or statistics from memory. Get them from an API, a file in `data/`, or the user. If you cannot get a value, write `TODO(verify)` and tell the user.
3. **Fetch before you parse.** Before you write a parser for any API, fetch one real sample. Save it in `tests/fixtures/`. Write the parser against that sample.
4. **No message leaves without a human.** The system drafts alerts. A person approves each one. Never call SNS publish from a code path that a person did not trigger.
5. **Label replays.** Each incident built from historical data has `mode = "replay"`. The UI shows "REPLAY — historical data" on it. A replay alert never goes to the live SNS topic.
6. **Show the limits.** The UI always shows data age, the sensors used, and the limits list in `docs/MVP.md` §9.
7. **Use careful words.** Say "possible fire" or "satellite hotspot". Say "confirmed" only when a person marked the incident as confirmed.
8. **No secrets in git.** The FIRMS key and the admin token go in `.env` (local) or SSM Parameter Store (AWS). Keep `.env` in `.gitignore`.
9. **Cite only verified rules.** The agent can cite a rule only if its entry in `data/rules.yaml` has `verified: true`.
10. **One working feature beats five partial features.** Finish each phase and its tests before you start the next phase.

## 3. Stack

- Python 3.13, locally and in Lambda (runtime `python3.13`). The dev machine is Windows with Python 3.13.
- Lambda packages: build from Linux wheels only, with `pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.13 --implementation cp --target <build_dir>`. Never ship Windows wheels. Docker is not available.
- Shell: run `make` from Git Bash. Keep Makefile recipes POSIX-sh compatible. Call `python`, not `python3`.
- Geometry: `shapely` 2.x. Do not use geopandas or pyproj. Use a local equirectangular projection for distances under 20 km (see `src/lfw/geo.py`).
- HTTP: `httpx`. Config: `pydantic-settings`. Data models: `pydantic` v2. YAML: `pyyaml`. Tests: `pytest`.
- Agent: Strands Agents SDK. Install it with `pip install strands-agents strands-agents-tools`.
  - Model on AWS: Amazon Bedrock. Model ID comes from env var `BEDROCK_MODEL_ID`. Never hard-code it.
  - Model locally: Ollama, through the Strands Ollama provider.
  - Before you write agent code, read the Strands docs for model providers and structured output (https://strandsagents.com). Confirm the import paths for the installed version. Do not guess them.
  - Optional: copy `.agents/skills/strands` from the Strands GitHub repo (`strands-agents/harness-sdk`) to `.claude/skills/strands`.
- AWS: SAM CLI, Lambda, EventBridge Scheduler, DynamoDB (on-demand), S3, SNS, API Gateway HTTP API, SSM Parameter Store, CloudWatch Logs, Amplify Hosting (static web).
- Web: one static page. Plain HTML, CSS and JS. Use Leaflet from cdnjs, with OpenStreetMap tiles and attribution.

## 4. Repository layout

```
CLAUDE.md
README.md
Makefile
pyproject.toml
template.yaml                # SAM
.env.example
docs/
  MVP.md                     # full spec (read it)
  claims.md                  # every public claim + source + status
  demo-script.md
data/
  sites.yaml                 # monitored landfills (built by script, then checked by a person)
  sites/<site_id>.geojson    # outline of each landfill
  receptors/<site_id>.geojson# schools/hospitals within 12 km (from OSM, cached)
  events.yaml                # backtest ground truth with sources
  rules.yaml                 # rule quotes + source + verified flag
  sources.yaml               # source documents + sha256
src/lfw/
  config.py  firms.py  sites.py  geo.py  detect.py  incidents.py
  wind.py  smoke.py  receptors.py  store.py  notify.py
  agent/ tools.py  contract.py  prompts.py  fallback.py  run.py
handlers/
  scan.py   api.py   draft.py
scripts/
  build_sites.py  build_receptors.py  backtest.py  history.py  verify_sources.py
web/
  index.html  app.js  style.css  config.js
tests/
  fixtures/  test_geo.py  test_detect.py  test_incidents.py  test_smoke.py
  test_contract.py  test_backtest_small.py
```

## 5. Commands

Put each command in the `Makefile`. Keep these names.

| Command | What it does |
|---|---|
| `make setup` | Create venv and install dependencies |
| `make test` | Run pytest |
| `make sites` | Run `scripts/build_sites.py` (OSM Overpass → `data/sites/`) |
| `make receptors` | Run `scripts/build_receptors.py` |
| `make backtest` | Run the backtest on `data/events.yaml`. Write `out/backtest.md` and `out/backtest.json` |
| `make scan-local` | Run one live scan with `STORE=local` |
| `make replay EVENT=brahmapuram-2023` | Build replay incidents for one event |
| `make draft INCIDENT=<id>` | Run the agent on one incident and print the draft and the validator report |
| `make verify` | Re-download each source in `data/sources.yaml` and check its SHA-256 |
| `make web` | Serve `web/` locally on port 8000 |
| `make deploy` | `sam build && sam deploy` |

## 6. Data facts you must respect

- **FIRMS Area API:** `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}[/{YYYY-MM-DD}]`
  - `DAY_RANGE` is 1 to 5. For longer periods, make more than one call.
  - Live sources: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`.
  - Archive sources: `VIIRS_SNPP_SP`, `VIIRS_NOAA20_SP`, `MODIS_SP`.
  - Check archive coverage with `/api/data_availability/csv/{MAP_KEY}/ALL`.
  - Limit: 5,000 transactions per 10 minutes. Cache raw CSV in `cache/` (local) or S3.
- **Satellite dates:** NOAA-20 data starts in 2018. NOAA-21 data starts in 2023. For the 2016 Deonar event, use only S-NPP and MODIS.
- **Field names:** VIIRS and MODIS use different field names (VIIRS `confidence` is a letter; MODIS `confidence` is a number). Confirm all field names from your saved fixture (Rule 3).
- **Time zone:** `acq_time` is UTC as HHMM. Store UTC. Show IST in the UI.
- **Wind:** Open-Meteo gives `wind_direction_10m` as the direction the wind comes FROM. Smoke travels TOWARD `(from + 180) % 360`. Test this.
  - Live: `https://api.open-meteo.com/v1/forecast`
  - History: `https://archive-api.open-meteo.com/v1/archive`
  - Pass `wind_speed_unit=ms`.
- **OpenStreetMap:** Use the Overpass API only in scripts. Do not call it from Lambda. Cache results in `data/`. Credit OSM (ODbL) in the UI and the README.

## 7. Build order (follow it)

Each phase has acceptance criteria in `docs/MVP.md` §11. Do not start a phase until the previous phase passes.

1. **P0 Setup.** Repo, Makefile, config, FIRMS fixture, Open-Meteo fixture, `data/events.yaml`.
2. **P1 Detection core + backtest.** `firms.py`, `sites.py`, `geo.py`, `detect.py`, `incidents.py`, `scripts/backtest.py`. This is the core evidence. Protect it.
3. **P2 Smoke zone, receptors, agent, contract, fallback.**
4. **P3 AWS.** SAM template, scheduled scan, API, DynamoDB, SNS, deploy.
5. **P4 Web dashboard.**
6. **P5 History stat, `make verify`, README, demo assets.**

## 8. Coding conventions

- Type hints everywhere. Pydantic models for every record that crosses a module boundary.
- Pure functions in `geo.py`, `detect.py`, `incidents.py` and `smoke.py`. No network calls there.
- All network calls in `firms.py`, `wind.py` and `scripts/`. Use timeouts and 2 retries with backoff.
- `store.py` has two backends with one interface: `local` (JSON files in `out/store/`) and `dynamodb`. Select with env var `STORE`.
- Log JSON lines. Lambda logs go to CloudWatch.
- Every threshold lives in `config.py`, with a comment that gives the reason.
- Keep each Lambda package small. Do not bundle test data.

## 9. Do not

- Do not use a model to decide if there is a fire, or to compute any number.
- Do not show a smoke zone as a pollution forecast. It is a screening sector.
- Do not scrape news sites in code.
- Do not add sign-up, login, or user accounts. Use one admin token for approve actions.
- Do not add features that are not in `docs/MVP.md` before P5 is done.
- Do not delete or rewrite `data/events.yaml`, `data/rules.yaml` or `docs/claims.md` entries without telling the user.

## 10. Hackathon compliance (from the official rules page)

- **Repo history must match the event dates (8–11 Oct 2026).** A mismatch disqualifies the team. Write all code new. Do not import code from older projects. Commit small and often (at least once per hour of work). Never squash, rebase or rewrite pushed history.
- Open-source libraries, public APIs and templates are allowed. Credit each one with its licence in `README.md` § Credits.
- **Data licences:** `data/sites/` and `data/receptors/` are derived from OpenStreetMap, so they are under ODbL. Put `data/LICENSE-DATA.md` with the ODbL notice. Credit NASA FIRMS and Open-Meteo (CC BY 4.0).
- **Submission = public repo + YouTube video under 3:00 + short writeup** (problem, build, where AWS fits). Write the writeup in `docs/writeup.md`. List the AI coding tools used in it.
- **Judges score only the video and the submission.** A feature that is not in the video does not count. Every feature named in the writeup must appear in the video.
- **The video must show AWS.** Keep `docs/aws-evidence.md` with the console shots to record (see `docs/MVP.md` §14).
- Before the repo goes public: run a secret scan on the full git history. Add a LICENSE file (Apache-2.0).

## 11. Definition of done

- `make test` passes.
- `make backtest` runs from a clean checkout with a FIRMS key, and writes `out/backtest.md`.
- The deployed scheduled scan writes a scan record to DynamoDB every 3 hours.
- The dashboard URL shows sites, the last scan time, one replay incident with smoke zone and receptors, a validated draft, and the approve button.
- An approved replay alert arrives by email from the demo SNS topic.
- The README lists: AWS services used, AI coding tools used (Claude Code), how to run, backtest results, limits, data credits.
