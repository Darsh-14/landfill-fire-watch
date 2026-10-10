# AWS evidence shots

Shot list from `docs/MVP.md` §14. A shot is "ready" only when the deployed system has produced it.
Record each one; use 2–4 in the video. How to produce each: `docs/deploy.md` §5 (`scripts/aws_check.py`).

Status 2026-10-10 23:55 IST: the stack is built, packaged, `sam validate --lint` and `cfn-lint` pass, and
every code path was run locally (STORE=local). **Nothing is deployed yet**: deploying needs the team's AWS
credentials, Bedrock model access and the SNS email confirmation. Every shot is therefore "not ready".

| # | Shot | What must be visible | How to produce it | Status | Recorded |
|---|---|---|---|---|---|
| 1 | EventBridge Scheduler | The `rate(3 hours)` schedule and its last run | EventBridge → Scheduler → Schedules (created by `ScheduleV2` on ScanFunction) | not ready (needs deploy) | — |
| 2 | CloudWatch Logs | One scan run with JSON lines (detections fetched, matched, incidents updated) | `aws_check.py` step 1, then ScanFunction log group: `scan_source`, `scan_matched`, `scan_done` | not ready (needs deploy) | — |
| 3 | DynamoDB | The scan record and one incident item | Explore items: `pk = SCAN`; `pk = INC#brahmapuram-kochi-20230302T1635`, `sk = META` (after `aws_seed.py`) | not ready (needs deploy) | — |
| 4 | S3 | A raw FIRMS CSV with its SHA-256 metadata | bucket → `raw/firms/VIIRS_SNPP_NRT/...csv` → Properties → `x-amz-meta-sha256` | not ready (needs deploy) | — |
| 5 | Bedrock and Strands | Draft Lambda log with the agent's tool calls and the validator result | `aws_check.py --draft`, DraftFunction log: `agent_tool_call`, `validator_result`, `draft_done` | not ready (needs deploy + Bedrock access) | — |
| 6 | SNS | The approved [REPLAY] email in the inbox | `aws_check.py --approve` (DemoTopic), then the inbox | not ready (needs deploy + email confirmation) | — |
| 7 | Terminal | `sam deploy` output with the stack outputs | `make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=...` | not ready (needs AWS credentials) | — |

Local equivalents already working (usable as a backup in the video, clearly labelled "local"):
`make scan-local` JSON lines; `make draft` tool-call and validator lines; `make api-local` outbox message.
