# Backtest results

- Generated: 2026-10-10T20:24:50Z · git `6abb16d`
- Config hash: `264d376145f22cd62b0d37e6c694a2270534312545cfcf33fc5fe22ef69690de` · frozen 2026-10-10T15:18:15Z at 9f9b2f2
- Outline check (`verified_by` in data/sites.yaml): deonar-mumbai: Claude Code (AI imagery check on Esri World Imagery, 2026-10-10, delegated by Darsh-14; see docs/site-review.md); ghazipur-delhi: Claude Code (AI imagery check on Esri World Imagery, 2026-10-10, delegated by Darsh-14; see docs/site-review.md); brahmapuram-kochi: Claude Code (AI imagery check on Esri World Imagery, 2026-10-10, delegated by Darsh-14; see docs/site-review.md)
- Data: NASA FIRMS archive (standard processing). Detected = at least one PROBABLE incident in the window.

## Documented fires

| Event | Reported start | Sources | Detected | First detection (IST) | Δ days | PROBABLE reached (IST) | Overpasses with detections | Max FRP (MW) | Smoke zone | Receptors |
|---|---|---|---|---|---|---|---|---|---|---|
| deonar-2016 | 2016-01-27 | VIIRS_SNPP_SP, MODIS_SP | yes | 2016-01-28 02:45 IST | 1 | 2016-01-28 13:56 IST | 12 | 49.61 | toward SSW, ESE, SE, SSE; 10 km; half-angle ≤ 45°; 14 wind hours | 217 |
| ghazipur-2022 | 2022-03-28 | VIIRS_SNPP_SP, VIIRS_NOAA20_SP, MODIS_SP | **no (miss)** | — | — | — | 1 | 1.68 | — | — |
| brahmapuram-2023 | 2023-03-02 | VIIRS_SNPP_SP, VIIRS_NOAA20_SP, MODIS_SP | yes | 2023-03-02 22:05 IST | 0 | 2023-03-02 22:05 IST | 13 | 27.1 | toward N, WNW, W; 10 km; half-angle ≤ 45°; 7 wind hours | 404 |

## Alerts in windows with no reported fire

Monsoon windows (15 Jul + 30 days, year before and after each event). No news report does not
prove there was no fire, so these are not called false positives.

| Site | Window (UTC days) | Matched detections | CANDIDATE incidents | PROBABLE incidents |
|---|---|---|---|---|
| deonar-mumbai | 2015-07-15 to 2015-08-13 | 0 | 0 | 0 |
| deonar-mumbai | 2017-07-15 to 2017-08-13 | 0 | 0 | 0 |
| ghazipur-delhi | 2021-07-15 to 2021-08-13 | 0 | 0 | 0 |
| ghazipur-delhi | 2023-07-15 to 2023-08-13 | 0 | 0 | 0 |
| brahmapuram-kochi | 2022-07-15 to 2022-08-13 | 0 | 0 | 0 |
| brahmapuram-kochi | 2024-07-15 to 2024-08-13 | 0 | 0 | 0 |

Raw FIRMS CSVs: 123 calls, each cached with SHA-256 (see JSON `fetches`).
