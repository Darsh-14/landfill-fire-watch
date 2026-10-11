# Deploying Landfill Fire Watch on AWS (ap-south-1)

Everything below runs from **Git Bash** in the repo root unless marked PowerShell.
Tools: AWS CLI v2 and AWS SAM CLI (`scoop install aws aws-sam-cli`), Python venv from `make setup`.
No Docker is needed.

## 1. How it fits together

```
EventBridge Scheduler ──rate(3 hours)──► ScanFunction (Lambda, python3.13, 512 MB, 300 s)
                                            │  FIRMS Area API: 4 NRT feeds, India bbox, last 24 h
                                            │  (MAP_KEY from SSM /lfw/firms_map_key)
                                            ├─► S3  raw/firms/<source>/<yyyy>/<mm>/<dd>/<scan>.csv
                                            │       metadata sha256 + S3 ChecksumSHA256
                                            ├─► match to site outlines → incidents (code rules)
                                            ├─► Open-Meteo forecast → smoke screening sector → receptors
                                            └─► DynamoDB table (scan record, detections, incidents)

Amplify Hosting (web/) ──► API Gateway HTTP API (10 req/s, burst 20) ──► ApiFunction (256 MB, 15 s)
        GET  /health /sites /incidents /incidents/{id} /backtest
        POST /incidents/{id}/draft   (x-admin-token) ──async──► DraftFunction (1024 MB, 120 s)
                                                              Strands agent + Amazon Bedrock
                                                              read-only tools → validator → retry → template
        POST /incidents/{id}/approve (x-admin-token) ──► SNS DemoTopic (replay) or LiveTopic (live) ──► email
        POST /incidents/{id}/review  (x-admin-token) ──► CONFIRMED / FALSE_ALARM / CLOSED
```

Nothing is ever sent without the approve call, which a person makes with the admin token.
Replay incidents can only be sent to the demo topic (`lfw.notify.topic_for`, tested).

| Resource | What it holds / does | IAM (least privilege) |
|---|---|---|
| `ScanFunction` | scheduled scan | DynamoDB Put/Get/Query/BatchWrite on the table; `s3:PutObject` on `raw/*`; `ssm:GetParameter` on `/lfw/firms_map_key` |
| `ApiFunction` | HTTP routes | DynamoDB Put/Get/Query; `sns:Publish` on the two topics only; `lambda:InvokeFunction` on DraftFunction; `s3:GetObject` on `backtest/*`; `ssm:GetParameter` on `/lfw/admin_token` |
| `DraftFunction` | Strands + Bedrock | DynamoDB Put/Get/Query; `bedrock:InvokeModel` (no streaming) |
| `Table` | DynamoDB on-demand, `pk`/`sk` + `gsi1` for incident lists | — |
| `Bucket` | raw CSVs, backtest JSON; private, SSE-S3 | — |
| `LiveTopic`, `DemoTopic` | SNS email | — |

## 2. One-time account setup

```bash
aws configure                      # or: aws configure sso
aws sts get-caller-identity        # check you are in the right account
export AWS_REGION=ap-south-1
```

**Bedrock model access.** Console → Amazon Bedrock → *Model access* (region ap-south-1) → request
access to one model that supports tool use. Then list what you can call:

```bash
aws bedrock list-inference-profiles --region ap-south-1 --query "inferenceProfileSummaries[].inferenceProfileId"
aws bedrock list-foundation-models --region ap-south-1 --by-output-modality TEXT --query "modelSummaries[].modelId"
```

Use one of those ids as `BEDROCK_MODEL_ID` below (an inference profile id works too). The id is never
hard-coded in the code. Listed does not mean callable: test one first.

```bash
MSYS_NO_PATHCONV=1 aws bedrock-runtime converse --region <region> --model-id <id> \
  --messages '[{"role":"user","content":[{"text":"Reply with OK"}]}]' --inference-config maxTokens=10
```

On our account every model in ap-south-1 answered `ValidationException: Operation not allowed`, while
`us.anthropic.claude-haiku-4-5-20251001-v1:0` in us-east-1 worked. The stack stays in ap-south-1; only the
model calls go to the other region: `make deploy ... BEDROCK_REGION=us-east-1` (the IAM policy allows it).

**Cost alarm (USD 5).** Put your email into `docs/aws/budget-notifications.json` (do not commit it), then:

```bash
aws budgets create-budget --region us-east-1 \
  --account-id "$(aws sts get-caller-identity --query Account --output text)" \
  --budget file://docs/aws/budget.json \
  --notifications-with-subscribers file://docs/aws/budget-notifications.json
```

**Secrets in SSM Parameter Store** (never in the template or git). The helper reads `.env` and prints nothing;
it generates `ADMIN_TOKEN` into `.env` if it is empty:

```bash
.venv/Scripts/python.exe scripts/aws_put_params.py
```

Or by hand. In Git Bash prefix `MSYS_NO_PATHCONV=1`, otherwise Git Bash rewrites `/lfw/...` into a Windows path:

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter --region ap-south-1 --name /lfw/firms_map_key --type SecureString --value "<FIRMS MAP_KEY>"
MSYS_NO_PATHCONV=1 aws ssm put-parameter --region ap-south-1 --name /lfw/admin_token  --type SecureString --value "<ADMIN TOKEN>"
```

(Make a token with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.)

## 3. Deploy the backend

```bash
make check                         # ruff + cfn-lint + all tests (no AWS needed)
make lint                          # cfn-lint on template.yaml
make deploy ALERT_EMAIL=you@example.com BEDROCK_MODEL_ID=<id from step 2> [BEDROCK_REGION=us-east-1]
```

`make deploy` = `make package` (Linux wheels from the committed locks, zipped to `build/<fn>.zip`) then
`sam deploy --template-file template.yaml` with the stack name and region from `samconfig.toml`.
SAM shows the change set; answer `y`. Keep the terminal output: it is evidence shot 7.

> Do **not** run `sam build` for this stack. Without Docker, `sam build` on Windows drops the Linux `.so`
> files from the prebuilt packages and numpy/shapely would fail in Lambda.

Then:

1. **Confirm both SNS subscription emails** ("AWS Notification - Subscription Confirmation" for the LIVE
   and DEMO topics). Without this no alert email arrives.
2. **Seed the replays and the backtest** (cached FIRMS + Open-Meteo data, written to DynamoDB and S3):
   ```bash
   AWS_REGION=ap-south-1 .venv/Scripts/python.exe scripts/aws_seed.py
   ```
3. The first scheduled scan runs within 3 hours. To run one now and verify everything:
   ```bash
   AWS_REGION=ap-south-1 .venv/Scripts/python.exe scripts/aws_check.py
   ```

## 4. Deploy the dashboard (Amplify Hosting, manual deploy)

```bash
AWS_REGION=ap-south-1 .venv/Scripts/python.exe scripts/deploy_web.py
```

It writes `web/config.js` with the stack output `ApiUrl`, creates the Amplify app and branch on the first
run, uploads a zip of `web/` and waits for the deployment. It prints the URL
(`https://main.<appId>.amplifyapp.com`). Then lock CORS to that origin:

```bash
make deploy ALERT_EMAIL=you@example.com BEDROCK_MODEL_ID=<id> BEDROCK_REGION=<region> ALLOWED_ORIGIN=https://main.<appId>.amplifyapp.com
```

Steps the script cannot do for you: confirm the SNS emails; enable Bedrock model access; look at the
deployed page in a browser.

## 5. Verify end to end (fills docs/aws-evidence.md)

```bash
AWS_REGION=ap-south-1 .venv/Scripts/python.exe scripts/aws_check.py --draft --approve
```

| Check | What `aws_check.py` does | Where to look in the console |
|---|---|---|
| 1 scan runs | invokes ScanFunction | Lambda → ScanFunction → Monitor → CloudWatch logs (`scan_source`, `scan_matched`, `scan_done` JSON lines) |
| 2 scan record | newest `pk=SCAN` item | DynamoDB → Tables → Explore items → `pk = SCAN` |
| 3 raw CSV + SHA-256 | newest `raw/firms/...csv` and its metadata | S3 → bucket → `raw/firms/` → object → Properties → Metadata `x-amz-meta-sha256` + Checksums |
| 4 API | `GET /health`, `GET /incidents` | API Gateway → HTTP API → Routes / Throttling |
| 5 Bedrock draft | `POST /incidents/<replay>/draft`, waits for the validated draft | Lambda → DraftFunction logs: `agent_tool_call` and `validator_result` lines (Strands evidence) |
| 6 approval email | `POST /approve` (replay → DemoTopic) | your inbox: subject starts with `[REPLAY]` |
| 7 schedule | finds the `rate(3 hours)` schedule | EventBridge → Scheduler → Schedules → last invocation |

If step 5 shows `template_used=True`, the model failed twice and the fixed template was used: read the
`validator_result` lines in the DraftFunction log. `AccessDeniedException` there means model access is not
enabled for that model/region, or the id is an inference profile from another region (set `BedrockRegion`).

## 6. Day-to-day

| Task | Command |
|---|---|
| Run one scan now | `aws lambda invoke --function-name <ScanFunctionName> --payload '{}' /dev/stdout` |
| Tail scan logs | `aws logs tail /aws/lambda/<ScanFunctionName> --follow` |
| Re-seed a replay | `AWS_REGION=ap-south-1 python scripts/aws_seed.py --events brahmapuram-2023` |
| Update code | `make deploy ALERT_EMAIL=... BEDROCK_MODEL_ID=... BEDROCK_REGION=... ALLOWED_ORIGIN=...` (repeat every value: omitted ones fall back to defaults) |
| Update web | `python scripts/deploy_web.py` |

## 7. Cost and teardown

Expected cost is within free tier or cents: 8 scans per day, on-demand DynamoDB, small Lambdas, Bedrock only
when a person presses *Draft*. To remove everything:

```bash
aws s3 rm "s3://$(aws cloudformation describe-stacks --stack-name landfill-fire-watch --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)" --recursive
sam delete --stack-name landfill-fire-watch --region ap-south-1
aws amplify delete-app --app-id <appId> --region ap-south-1
MSYS_NO_PATHCONV=1 aws ssm delete-parameters --names /lfw/firms_map_key /lfw/admin_token --region ap-south-1
```

## 8. Local mode (no AWS)

```bash
make setup && make test
make backtest                       # out/backtest.md
make replay EVENT=brahmapuram-2023  # replay incidents into out/store/
make draft INCIDENT=brahmapuram-kochi-20230302T1635   # fake model: rejected draft, retry, validator report
make scan-local                     # one real live scan, STORE=local
make api-local                      # API on :8001 (approve writes to out/outbox/ instead of SNS)
make web                            # dashboard on :8000
```
