# Demo video script (target 2:50, hard limit 3:00)

Based on `docs/MVP.md` §14, with the real numbers from our runs (out/backtest.md, `make draft`, dashboard).
Every sentence below is in `docs/claims.md` as Sourced, Verified or Measured. Re-check the numbers on the
day of recording (live scan counts change every 3 hours).

| Time | Show | Say |
|---|---|---|
| 0:00–0:18 | Map of Kochi with the Brahmapuram outline; on-screen source line "Gulf News, 9 Mar 2023" | "March 2023. A fire at Kochi's Brahmapuram waste plant sent smoke up to about ten kilometres. Classes for younger students were suspended." |
| 0:18–0:32 | Text card | "Satellite fire alerts in India are built around forests. We found no service that warns the people next to a burning landfill. So we built one." |
| 0:32–0:52 | Dashboard: status strip (last scan, sources), Sites tab | "Every three hours, EventBridge starts a Lambda that pulls NASA satellite hotspots for all of India and checks them against the landfills we monitor." (Say the real site count from the status strip.) |
| 0:52–1:30 | Incidents → Brahmapuram **REPLAY — historical data**; map zooms to the hotspot squares, orange sector, dots | "Code decides, not the model. At 22:05 IST on 2 March a MODIS pixel over the landfill was high confidence at 22.7 megawatts — that rule makes it a probable fire. Wind turned the smoke north, then west over the city. Inside this ten-kilometre screening sector there are 404 schools and hospitals; the nearest college is 1.8 kilometres away. This is a screening sector, not a pollution forecast." |
| 1:30–2:00 | Step 3 "Alert message" (Residents, Officials), "Passed all 11 safety checks", open Details to show the rejected first attempt | "A Strands agent on Amazon Bedrock writes the alerts from tool outputs only. Here a draft named a school that does not exist; the validator rejected it, and the retry passed all checks." (If the rejected draft shown comes from the local test model, keep the on-screen label "local test model".) |
| 2:00–2:15 | Press Approve → inbox with the `[REPLAY]` email | "Nothing goes out until a person approves. Replays can only go to the demo topic." |
| 2:15–2:35 | "Tested" tab | "We replayed three real fires with frozen rules. We caught Deonar and Brahmapuram. We missed Ghazipur 2022: only one satellite pass saw it. And zero alerts in six monsoon months without a reported fire. These are our limits." |
| 2:35–2:50 | AWS console: EventBridge schedule → Lambda log with `agent_tool_call` lines → DynamoDB incident item → S3 object SHA-256 | "It runs on AWS: EventBridge, Lambda, DynamoDB, S3 with checksums, SNS, and Bedrock through Strands." |
| 2:50–2:55 | Repo URL | "It's open source. Link below." |

Recording checklist: status strip visible with data age; REPLAY badge visible; at least two
AWS console shots from `docs/aws-evidence.md`; no admin token or key on screen; browser zoom 110%.
