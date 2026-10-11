# AWS evidence shots

Shot list from `docs/MVP.md` §14. A shot is "ready" only when the deployed system has produced it.
Record each one; use 2–4 in the video. How to produce each: `docs/deploy.md` §5 (`scripts/aws_check.py`).

Status 2026-10-11 13:45 IST: stack `landfill-fire-watch` deployed in ap-south-1 (Bedrock calls in us-east-1,
model `us.amazon.nova-pro-v1:0`; dashboard on Amplify in us-east-1). `scripts/aws_check.py --draft --approve`
passed all seven steps. "Ready" means the deployed system produced it; "Recorded" is filled in after the
screen recording.

| # | Shot | What must be visible | How to produce it | Status | Recorded |
|---|---|---|---|---|---|
| 1 | EventBridge Scheduler | The `rate(3 hours)` schedule and its last run | EventBridge → Scheduler → Schedules (created by `ScheduleV2` on ScanFunction) | ready (`ScanFunctionEvery3Hours rate(3 hours) ENABLED`) | — |
| 2 | CloudWatch Logs | One scan run with JSON lines (detections fetched, matched, incidents updated) | `aws_check.py` step 1, then ScanFunction log group: `scan_source`, `scan_matched`, `scan_done` | ready (scan 2026-10-11 07:53Z: 2318 raw detections, 4 feeds) | — |
| 3 | DynamoDB | The scan record and one incident item | Explore items: `pk = SCAN`; `pk = INC#brahmapuram-kochi-20230302T1635`, `sk = META` (after `aws_seed.py`) | ready (scan records + 4 replay incidents seeded) | — |
| 4 | S3 | A raw FIRMS CSV with its SHA-256 metadata | bucket → `raw/firms/VIIRS_SNPP_NRT/...csv` → Properties → `x-amz-meta-sha256` | ready | — |
| 5 | Bedrock and Strands | Draft Lambda log with the agent's tool calls and the validator result | `aws_check.py --draft`, DraftFunction log: `agent_tool_call`, `validator_result`, `draft_done` | ready (Nova Pro: attempt 1 rejected, retry passed 11/11, no template) | — |
| 6 | SNS | The approved [REPLAY] email in the inbox | `aws_check.py --approve` (DemoTopic), then the inbox | ready (approved 2026-10-11 08:13Z, model draft, demo topic) | — |
| 7 | Terminal | `sam deploy` output with the stack outputs | `make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0 BEDROCK_REGION=us-east-1` | ready (`Successfully created/updated stack`) | — |

Earlier approvals on 2026-10-11 (07:53Z, 08:04Z) sent template drafts while Bedrock access was blocked
(see `docs/deploy.md`, model access). They are in the inbox too; use the 08:13Z email in the video.

Local equivalents (backup only, clearly labelled "local"): `make scan-local` JSON lines; `make draft`
tool-call and validator lines; `make api-local` outbox message.
