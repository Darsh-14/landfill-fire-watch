# Feature ledger

Judges score only the video and the submission (CLAUDE.md §10). A feature without a video timestamp must not
appear in `docs/writeup.md`. Timestamps below are **planned** from `docs/demo-script.md`; replace them with the
real ones after recording and delete any feature that did not make it into the video.

| # | Feature | Works? | Evidence | Video timestamp |
|---|---|---|---|---|
| 1 | Scheduled scan of 4 FIRMS NRT feeds for India (EventBridge → Lambda) | locally yes (`make scan-local`: 1100 detections, 4 feeds); AWS: after deploy | `scan_done` JSON line; aws-evidence shots 1–2 | 0:32 (planned) + 2:35 |
| 2 | Match hotspots to landfill outlines with a pixel-sized buffer | yes | tests/test_geo.py, test_detect.py | 0:52 (planned) |
| 3 | Incident status by fixed rules (CANDIDATE / PROBABLE) | yes | tests/test_incidents.py; replay incident reason text | 0:52 (planned) |
| 4 | Smoke screening sector from hourly wind | yes | tests/test_smoke.py; dashboard sector | 0:52 (planned) |
| 5 | Schools and hospitals inside the sector, with distance | yes | data/receptors/, dashboard table (404 for Brahmapuram) | 0:52 (planned) |
| 6 | REPLAY labelling of historical incidents | yes | badge + banner; validator check 11 | 0:52 (planned) |
| 7 | Strands agent drafts from read-only tools | locally with the test model; Bedrock after deploy | `agent_tool_call` lines; aws-evidence shot 5 | 1:30 (planned) |
| 8 | Validator (11 checks), retry once, fixed-template fallback | yes | tests/test_contract.py (one test per check) | 1:30 (planned) |
| 9 | Human approval before any message; replay → demo topic only | yes locally (outbox); SNS after deploy | tests/test_api.py; aws-evidence shot 6 | 2:00 (planned) |
| 10 | Backtest on 3 documented fires + 6 quiet windows, frozen config | yes | out/backtest.md | 2:15 (planned) |
| 11 | Limits panel always visible | yes | tests/test_web.py | 2:15 (planned) |
| 12 | Raw CSV archive in S3 with SHA-256 | code yes; AWS after deploy | aws-evidence shot 4 | 2:35 (planned) |
| 13 | History stat (detection-days per site) | see out/history.md | scripts/history.py | not in the video (planned: none) |
| 14 | `make verify` source re-check | yes (reports the CAQM PDFs as UNREACHABLE: the URLs now return HTML) | data/sources.yaml | not in the video |
| 15 | Hindi resident advisory | built, switched off (no reviewer) | fallback.py TODO(verify) | not in the video |
