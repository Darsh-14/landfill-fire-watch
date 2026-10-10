# Site outline review (event sites)

**Who checked:** Claude Code (AI coding agent), on behalf of team member Darsh-14, who asked the
agent to do the check. **No team member has checked these outlines on imagery yet.** This deviates
from MVP §11 P0 ("outlines that a person checked on a map"); `verified_by` in `data/sites.yaml` says so.

**Method (2026-10-10):** `scripts/render_site_review.py` draws the OSM outlines (red = named
`landuse=landfill` match, cyan = nearby unnamed `landuse=landfill`) on Esri World Imagery:
the current basemap and, for Brahmapuram, the Wayback release of 2023-02-23 (tile unchanged since the
2022-09-21 release, so captured on or before that date; exact capture date not retrieved).
Images are in `out/review/` (not committed: imagery licence, review use only). Nearby heat sources
come from `scripts/nearby_heat_sources.py` (`data/sites/_candidates/heat_sources.yaml`).

**Bias note:** the agent saw the P0 archive fixture (FIRMS rows for 2023-02-27..03-03 near
Brahmapuram) before this review. The outline choice below is a superset that includes the named
outline either way, so those rows match or not regardless of the choice. No other event detections
were looked at.

Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community. Outlines © OpenStreetMap contributors.

| Site | Outline chosen | What the imagery shows | Exclusions noted |
|---|---|---|---|
| deonar-mumbai | way/289511744 + way/314528563 (union; team choice) | Named outline encloses the whole dumping ground: mounds and haul roads (north), grey mounds (east, south-east). The 2.86 ha unnamed plot is vegetated with bare patches, no clear mounds; it overlaps the named outline, so the union changes little. | Industrial complex with buildings inside the outline (south-centre). BEST bus depot adjacent (OSM way/222972350). |
| ghazipur-delhi | way/76727509 | Outline fits the large terraced landfill mound closely. | OSM "Bio-Gas Plant" touches the outline (way/283807712); industrial buildings on the west edge; crematorium 481 m (way/25493904). |
| brahmapuram-kochi | way/1262085027 + way/1417183060 (union; agent choice, delegated) | Named 6.48 ha outline: grey waste-like material and a pond beside processing sheds; it is part of the plant, not the main dump. Unnamed 60.58 ha polygon: bare worked ground with haul tracks, terraced edges and a pond on both dates — the main dump area. | KSEB Brahmapuram Diesel Power Plant 287 m (way/310521022); FACT Ambalamedu industrial area 220 m (way/59266110); HPCL 717 m (way/133981662); waste-plant buildings and tanks next to the named outline. |

**Open item (TODO(verify)):** at Brahmapuram, a large white, textured area directly south-west of the
unnamed polygon looks like a waste heap on both dates but is not mapped as landfill in OSM and is not
inside the chosen outline. It may be legacy waste or a quarry. Adding it needs a hand-drawn outline
(`polygon_source: manual`) by a person who can confirm what it is; the agent did not draw one.

## Other monitored sites (checked 2026-10-11, same method, current Esri imagery only)

These sites have no backtest; they are monitored by the live scan. Same caveat: checked by the AI coding
agent on the team's request, not yet by a team member.

| Site | Outline | What the imagery shows | Exclusions noted |
|---|---|---|---|
| kanjurmarg-mumbai | way/257455760 (named "Kanjur Landfill") | Outline encloses the whole landfill complex: mound, processing sheds, ponds | sheds and ponds inside |
| bhalswa-delhi | way/414943488 ("Bhalswa Landfill Area") | Outline fits the terraced mound; small unnamed landfill pieces nearby are not part of it | dense housing around |
| okhla-delhi | way/608169272 ("Okhla Landfill") | Outline fits the mound | container depot east; building complex south-west |
| bandhwari-gurugram | way/34263673 ("Bandhwari Solid Waste Management Plant") | Outline covers most of the bare mound; waste extends a little beyond it west and south | — |
| kodungaiyur-chennai | way/29199633 ("Kodungaiyur Corporation Landfill") | Outline fits the large grey-mound dump | plant with round tanks west; storage tanks north-east |
| dhapa-kolkata | way/325363390 ("Dhapa Landfill") | Outline fits the long dump with mounds and sheds | sheds inside the north end |
| perungudi-chennai | way/84106307 (OSM name "Pallikaranai Dumpyard", found within 3 km of the OSM place "Perungudi") | Large terraced dump | plant with round tanks north-east |
| mandur-bengaluru | way/135169264 + way/285786390 (both "Mandur Landfill") | North polygon shows waste mounds and a pond; south polygon is mostly tree cover (possibly an older covered section) | south part mostly vegetated |

Not monitored (no outline): pirana-ahmedabad and jawahar-nagar-hyderabad (the proximity search found only tiny
dumps near places with the same name in other states, rejected); uruli-devachi-pune, bhandewadi-nagpur,
dadumajra-chandigarh (Overpass unavailable during the searches). 11 sites are monitored; the MVP aimed for 15–25.
