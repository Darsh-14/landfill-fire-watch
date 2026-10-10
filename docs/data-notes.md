# Data notes (from real fixtures)

Every field name and format below was read from a saved file in `tests/fixtures/` (see
`tests/fixtures/MANIFEST.yaml` for URL, time and SHA-256). Differences from `docs/MVP.md` §5–6 are
marked **DIFF**.

## NASA FIRMS

Files (all fetched 2026-10-10, see MANIFEST):

| File | Source | Query | Data rows |
|---|---|---|---|
| `firms_data_availability_all.csv` | `/api/data_availability/csv/{KEY}/ALL` | — | 11 |
| `firms_live_VIIRS_SNPP_NRT_punjab.csv` | VIIRS_SNPP_NRT | Punjab bbox, day range 1 | 35 |
| `firms_live_MODIS_NRT_punjab.csv` | MODIS_NRT | Punjab bbox, day range 1 | 16 |
| `firms_archive_VIIRS_SNPP_SP_brahmapuram_2023-02-27.csv` | VIIRS_SNPP_SP | Brahmapuram bbox, `5/2023-02-27` | 8 |
| `firms_archive_MODIS_SP_brahmapuram_2023-02-27.csv` | MODIS_SP | Brahmapuram bbox, `5/2023-02-27` | 2 |

### Columns (exact header order)

| Source | Header |
|---|---|
| VIIRS NRT | `latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight` |
| VIIRS SP | same as VIIRS NRT **+ `type`** |
| MODIS NRT | `latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight` |
| MODIS SP | same as MODIS NRT **+ `type`** |
| data_availability | `data_id,min_date,max_date` |

No `source` column: the parser adds the source name from the request. No country column.

### Value formats

| Field | VIIRS | MODIS | Note |
|---|---|---|---|
| `latitude`, `longitude` | 5 decimals (`9.99317`) | 4 decimals (`9.9926`) | Detection key uses `:.4f` (MVP §5) |
| `scan`, `track` | km, e.g. `0.61`, `0.54` | km, e.g. `2`, `1.4` (may print as integer) | Parse as float |
| `acq_date` | `2023-03-02` | same | UTC date |
| `acq_time` | `1955`, `724`, `907` | `450`, `1009`, `1635` | **DIFF:** not zero-padded. MVP says HHMM; values below 1000 have 3 digits. Pad to 4 (`0450`) before parsing and in the detection key. UTC. |
| `satellite` | `N` (S-NPP) | `Terra`, `Aqua` | **DIFF:** the FIRMS attribute page says MODIS `A`/`T`; the CSV has full words |
| `instrument` | `VIIRS` | `MODIS` | matches `Literal["VIIRS","MODIS"]` |
| `confidence` | letters; seen `n`, `h` | integer 0–100; seen `34`..`82` | `l` not present in these samples (TODO(verify) with a larger sample) |
| `version` | `2.0NRT` (NRT), `2` (SP) | `6.1NRT` (NRT), `61.03` (SP) | Keep as string |
| `frp` | MW, e.g. `1.76` | MW, e.g. `22.7` | float |
| `daynight` | `D` / `N` | `D` / `N` | |
| `type` | SP only; seen `0`, `2` | SP only; seen `0` | **DIFF:** the FIRMS attribute page lists `type` for MODIS standard data only; the VIIRS SP CSV has it too. NRT has no `type`, so `type_code = None` live. |
| brightness | `bright_ti4`, `bright_ti5` (K) | `brightness`, `bright_t31` (K) | Not used for decisions |

Observed in the Brahmapuram archive sample: two VIIRS rows with `type = 2` ("other static land source")
on 2023-02-28 and 2023-03-01 at about 9.977–9.979 N, 76.375 E, south-east of the outline. These are
forced to tier `low` by MVP §6.1 step 5.

### data_availability (2026-10-10)

| data_id | min_date | max_date |
|---|---|---|
| MODIS_NRT | 2026-08-01 | 2026-10-10 |
| MODIS_SP | 2000-11-01 | 2026-07-31 |
| VIIRS_NOAA20_NRT | 2026-07-01 | 2026-10-10 |
| VIIRS_NOAA20_SP | 2018-04-01 | 2026-06-30 |
| VIIRS_NOAA21_NRT | 2024-01-17 | 2026-10-10 |
| VIIRS_SNPP_NRT | 2026-07-01 | 2026-10-10 |
| VIIRS_SNPP_SP | 2012-01-20 | 2026-06-30 |
| LANDSAT_NRT, GOES_NRT, BA_MODIS, BA_VIIRS | — | not used |

**DIFF:** CLAUDE.md §6 says NOAA-21 data starts in 2023. FIRMS has no `VIIRS_NOAA21_SP`, and
`VIIRS_NOAA21_NRT` starts 2024-01-17, so NOAA-21 cannot be used for any of the three backtest events.
The availability endpoint gives a date range only, not gaps inside the range.

### Archive coverage for the backtest events

Computed from `firms_data_availability_all.csv` (date ranges only):

| event_id | window | VIIRS_SNPP_SP | VIIRS_NOAA20_SP | MODIS_SP | VIIRS_NOAA21_SP |
|---|---|---|---|---|---|
| deonar-2016 | 2016-01-24 → 2016-02-03 | covered | not covered (starts 2018-04-01) | covered | no such source |
| ghazipur-2022 | 2022-03-25 → 2022-04-04 | covered | covered | covered | no such source |
| brahmapuram-2023 | 2023-02-27 → 2023-03-14 | covered | covered | covered | no such source |

The MVP §4 check (VIIRS_SNPP_SP and MODIS_SP cover Jan 2016, Mar 2022 and Mar 2023) passes.

### Bounding boxes

- Live fixture: Nominatim `boundingbox` of Punjab, India. The rectangle also covers part of Pakistan,
  so some live rows are outside India. Harmless: detections only matter when they match a site.
  The India scan bbox (`config.INDIA_BBOX`) also covers neighbouring countries for the same reason.
- Archive fixture: OSM outline bounds of `brahmapuram-kochi` ± 0.05°.

## Open-Meteo (forecast and archive)

Files: `openmeteo_forecast_brahmapuram.json` (today, forecast API) and
`openmeteo_archive_brahmapuram_2023-03-02.json` (archive API). Query: `hourly=wind_speed_10m,wind_direction_10m`,
`wind_speed_unit=ms`, `timezone=GMT`, point = OSM centroid of `brahmapuram-kochi`.

| Item | Value in fixture | Note |
|---|---|---|
| Top-level keys | `latitude, longitude, generationtime_ms, utc_offset_seconds, timezone, timezone_abbreviation, elevation, hourly_units, hourly` | Same for both APIs |
| `hourly` keys | `time`, `wind_speed_10m`, `wind_direction_10m` | Parallel arrays, 24 entries for one day |
| `hourly_units` | `time: iso8601`, `wind_speed_10m: m/s`, `wind_direction_10m: °` | `m/s` confirms `wind_speed_unit=ms` |
| `time` format | `2023-03-02T00:00` | No zone suffix. `utc_offset_seconds = 0` with `timezone=GMT`, so parse as UTC. |
| `wind_speed_10m` | float, e.g. `1.14` | Range in samples 0.18–4.37 m/s |
| `wind_direction_10m` | int degrees, e.g. `38` | Direction the wind comes FROM (CLAUDE.md §6). Smoke TOWARD = `(from + 180) % 360`. No nulls in samples. |
| Returned point | `10.017574, 76.36602` for a request at `9.991888, 76.366982` | **DIFF / note:** Open-Meteo snaps to its grid cell (~2.9 km north here). Store the returned point with the wind hours. |

Forecast vs archive: the forecast API serves current dates, so the live fixture is today's forecast
(2026-10-10) at the same point. The 2023-03-02 sample comes from the archive API (agreed in P0).

## Nominatim (OpenStreetMap)

Files: `nominatim_india.json`, `nominatim_punjab.json` (`format=jsonv2`).
`boundingbox` is a list of 4 **strings** in the order **south, north, west, east** — not the FIRMS
order `west,south,east,north`. Convert explicitly.

| Area | OSM | boundingbox (S, N, W, E) | Used for |
|---|---|---|---|
| India | relation 304716 | 6.5531169, 35.6729307, 67.9160885, 97.3950905 | `config.INDIA_BBOX` (live scan) |
| Punjab, India | relation 1942686 | 29.5429378, 32.5111793, 73.8798336, 76.9390583 | Live FIRMS fixture bbox |

## OpenStreetMap landfill outlines

See `data/sites_build_report.yaml` (every search, candidate and decision) and `data/sites/*.geojson`.

## Credit texts (copied from the providers, 2026-10-10; for README § Credits in P5)

- **NASA FIRMS** (https://www.earthdata.nasa.gov/data/tools/firms): "We acknowledge the use of data
  and/or imagery from NASA's Fire Information for Resource Management System (FIRMS)
  (https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for
  Earth observations (LANCE) (https://earthdata.nasa.gov/lance) and NASA's Earth Science Data and
  Information System (ESDIS)."
- **OpenStreetMap**: "© OpenStreetMap contributors", linked to https://www.openstreetmap.org/copyright
  (OSMF attribution guidelines). Data under ODbL; see `data/LICENSE-DATA.md`.
- **Open-Meteo**: CC BY 4.0. TODO(verify): copy the exact attribution wording from open-meteo.com/en/license in P5.
