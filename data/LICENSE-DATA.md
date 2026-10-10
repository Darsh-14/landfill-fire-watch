# Data licence

## OpenStreetMap-derived data (`data/sites/`, `data/receptors/`)

The files in `data/sites/` (landfill outlines) and `data/receptors/` (schools, kindergartens,
colleges, hospitals and clinics) are extracted from OpenStreetMap through the Overpass API.

Map data © OpenStreetMap contributors — https://www.openstreetmap.org/copyright

This database is made available under the Open Database License:
http://opendatacommons.org/licenses/odbl/1.0/. Any rights in individual contents
of the database are licensed under the Database Contents License:
http://opendatacommons.org/licenses/dbcl/1.0/

If you alter or build upon this data, you may distribute the result only under the same licence (ODbL).

Each GeoJSON file records the OSM element id and the retrieval time of every feature it contains.

## Other data in this repository

- `data/events.yaml`, `data/rules.yaml`, `data/sources.yaml`: written by the project team.
  They link to third-party sources, which keep their own licences and copyright.
- NASA FIRMS and Open-Meteo data are not redistributed here except as small test fixtures in
  `tests/fixtures/`. Their credits and licences are listed in `README.md` § Credits.
