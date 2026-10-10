# AWS evidence shots

Shot list from `docs/MVP.md` §14. Mark a shot "ready" only when the deployed system can produce it.
Record each one; use 2–4 in the video.

| # | Shot | What must be visible | Status | Recorded |
|---|---|---|---|---|
| 1 | EventBridge Scheduler | The `rate(3 hours)` schedule and its last run | not ready | — |
| 2 | CloudWatch Logs | One scan run with JSON lines (detections fetched, matched, incidents updated) | not ready | — |
| 3 | DynamoDB | The scan record and one incident item | not ready | — |
| 4 | S3 | A raw FIRMS CSV with its SHA-256 metadata | not ready | — |
| 5 | Bedrock and Strands | Draft Lambda log with the agent's tool calls and the validator result | not ready | — |
| 6 | SNS | The approved [REPLAY] email in the inbox | not ready | — |
| 7 | Terminal | `sam deploy` output with the stack outputs | not ready | — |
