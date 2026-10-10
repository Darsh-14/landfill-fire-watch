# Claims register

Every claim in the README, the writeup, the blog post and the video, with its source and status (MVP §13).
Only claims with status **Sourced**, **Verified** or **Measured** may appear in the video or the writeup.
Do not delete or rewrite entries without telling the team (CLAUDE.md §9).

Status meanings: **Sourced** = a person-readable source was fetched and the quoted sentence read (2026-10-10);
**Measured** = produced by this repository's code on real data (file given); **Design** = true by construction
(code / template given); **Team statement** = our own finding, worded as such; **TODO(verify)** = must not be
used publicly yet.

## Problem and context

| # | Claim (as worded publicly) | Source | Status | Used in |
|---|---|---|---|---|
| 1 | Deonar, Mumbai, Jan 2016: satellites detected fire from 27 January; it burned for about four days; more than 70 schools closed | NASA Earth Observatory, "Fire Burns in Mumbai Landfill", 2016-02-02 (`data/events.yaml`) | Sourced | README, writeup |
| 2 | Ghazipur, Delhi: a massive fire broke out on the afternoon of 28 March 2022 | Down To Earth, 2022-03-29 (`data/events.yaml`) | Sourced | README |
| 3 | Brahmapuram, Kochi: fire started on 2 March 2023 | Down To Earth 2023-03-06; Gulf News 2023-03-09 | Sourced | README, video |
| 4 | Brahmapuram 2023: smoke spread up to about 10 km | Gulf News 2023-03-09: "The toxic smoke spread up to 10km around Brahamapuram" | Sourced | README, writeup, video |
| 5 | Brahmapuram 2023: classes for younger students were suspended | Gulf News 2023-03-09: "Classes for younger students in schools in Kochi city and neighbouring areas have been suspended from Monday." | Sourced | README, writeup, video |
| 6 | Brahmapuram 2023: 95% of the fire doused on 12 March | Onmanorama 2023-03-12 (quote read); Deccan Herald (HTTP 403, not read) | Sourced (Onmanorama) | not used |
| 7 | India's satellite forest fire alert system (FSI FAST) filters out all fires other than forest fires | FSI Technical Information Series Vol. I No. 2 (2019), p.4 (`data/sources.yaml` fsi-fast-3-2019) | Sourced (2019 document; may have changed since) | README, writeup ("built around forests"), video |
| 8 | We found no public service that alerts the people near a burning landfill | our own search during the hackathon | Team statement (say "we found no…") | README, writeup, video |
| 9 | Fire services attended only 15 Brahmapuram fires in 5 years | The Hindu, 31 Mar 2023 (clipping) | TODO(verify): original not found | not used |
| 10 | About 3,000 landfills in India | CNN (URL not recorded) | TODO(verify) | not used |
| 11 | CAQM issued Direction No. 91 (3 June 2025) on fires at landfills and dumpsites in NCR | CAQM press release (search result); the caqm.nic.in PDF URLs now return the site's HTML app | TODO(verify): read the PDF | not used |
| 12 | SWM Rules 2026 require fire prevention at dumpsites (Rule 15(4), Schedule IV) | Gazette not located; secondary sources cite S.O. 388(E), 27 Jan 2026 | TODO(verify) | not used |

## What the system does (design)

| # | Claim | Source | Status | Used in |
|---|---|---|---|---|
| 13 | A scan runs every 3 hours and pulls NASA FIRMS hotspots for all of India (4 NRT feeds) | `template.yaml` (ScheduleV2 `rate(3 hours)`), `config.LIVE_SOURCES`, `config.INDIA_BBOX` | Design | README, writeup, video |
| 13b | 11 landfills are monitored (MVP aimed for 15–25) | `data/sites.yaml`, `docs/site-review.md` | Measured | README, video (status strip) |
| 14 | Code, not the model, decides matches, status, smoke zone and the list of places | `src/lfw/detect.py`, `incidents.py`, `smoke.py`, `pipeline.py`; agent tools are read-only | Design | README, writeup, video |
| 15 | The validator has 11 checks and rejects invented places, changed numbers, "confirmed", health claims, unverified rules, missing [REPLAY] | `src/lfw/agent/contract.py`; `tests/test_contract.py` | Design + tested | README, writeup, video |
| 16 | Nothing is sent until a person approves; replays go only to the demo topic | `handlers/api.py` approve route, `lfw/notify.topic_for`; `tests/test_api.py` | Design + tested | README, writeup, video |
| 17 | Raw FIRMS CSVs are stored in S3 with their SHA-256 | `handlers/scan.py` (`x-amz-meta-sha256`, `ChecksumSHA256`) | Design (AWS shot after deploy) | writeup, video |
| 18 | Runs on EventBridge, Lambda, DynamoDB, S3, SNS, API Gateway, SSM, CloudWatch, Amplify, Bedrock via Strands | `template.yaml`, `docs/deploy.md` | Design; **show only after deploy** | README, writeup, video |

## Results (measured)

| # | Claim | Source | Status | Used in |
|---|---|---|---|---|
| 19 | Backtest with rules frozen before the first run (config hash 264d3761…) | `data/config_freeze.yaml`, `out/backtest.md` | Measured | README, writeup |
| 20 | Deonar 2016 detected, first detection 2016-01-28 02:45 IST (+1 day IST) | `out/backtest.md` | Measured | README, writeup |
| 21 | Brahmapuram 2023 detected on the same day (2023-03-02 22:05 IST) | `out/backtest.md` | Measured | README, writeup, video |
| 22 | Ghazipur 2022 missed: one overpass with detections, CANDIDATE only | `out/backtest.md`, `out/backtest.json` | Measured | README, writeup, video |
| 23 | Zero alerts in six 30-day monsoon windows with no reported fire | `out/backtest.md` | Measured | README, writeup, video |
| 24 | Brahmapuram replay: MODIS pixel at 22:05 IST, high confidence, 22.7 MW → PROBABLE | `make replay EVENT=brahmapuram-2023` (status_reason) | Measured | video |
| 25 | Brahmapuram replay: smoke toward N, then WNW and W; 404 schools/hospitals in the 10 km sector; nearest college 1.79 km | replay incident + `data/receptors/brahmapuram-kochi.geojson` | Measured | README, video |
| 26 | A draft naming an invented school was rejected and the retry passed | `make draft` with the local test model (fake) | Measured (local test model; label it so) | video |
| 27 | Detection-days per site since 2019 | `out/history.md` | Measured (VIIRS S-NPP only) | README (link) |

## Honesty notes that must stay visible

| # | Statement | Where |
|---|---|---|
| 28 | Event-site outlines were checked on imagery by the AI coding agent at the team's request, not yet by a team member | README Limits, `docs/site-review.md` |
| 29 | No rule text is verified, so the agent cites none | README Limits, `data/rules.yaml` |
| 30 | Hindi is built but switched off until a Hindi speaker reviews it | README Limits, dashboard |
| 31 | The admin token is a demo control, not production authentication | README Limits |
