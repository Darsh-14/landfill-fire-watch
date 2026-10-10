# Usability test (MVP §9)

**Who:** one person outside the team who has not seen the project.
**Setup:** open the dashboard URL (or `make api-local` + `make web`, then http://localhost:8000). Do not explain anything.
**Task to read out:** "A landfill fire was reported in Kochi in March 2023. Find which schools are downwind."

Observe, do not help. Note where they hesitate, what they click first, and any wrong conclusion.

| Step | Ask the person to… | Success looks like | Watch for |
|---|---|---|---|
| 1 | "Tell me what this page is for and how fresh the data is." | Reads the status strip: last scan time, sources, sites; notices the Limits panel | Thinks it shows confirmed fires; misses "N min ago" |
| 2 | "Find the Kochi fire from March 2023." | Clicks the Brahmapuram item with the **REPLAY — historical data** badge | Confuses replay with a live alert |
| 3 | "Which way was the smoke going, and is that a forecast?" | Reads "Smoke toward N, WNW, W"; says the orange area is a screening sector, not a pollution forecast | Reads the sector as measured pollution |
| 4 | "Name three schools in that area and how far they are." | Scrolls the "Schools and hospitals in the sector" table or hovers blue dots | Cannot find the table; mixes up hospitals and schools |
| 5 | "If you were the duty officer, what would you do before anyone gets a message?" | Opens the draft tabs, sees the validator report and that a person must press Approve (replay → demo topic only) | Thinks messages go out automatically |

**Record:** time to complete each step, the person's words at each hesitation, and every fix made afterwards
(write them below with the commit id).

| Date | Tester (initials) | Finding | Fix (commit) |
|---|---|---|---|
| | | | |
