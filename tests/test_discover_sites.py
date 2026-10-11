"""Discovery keeps municipal landfills and drops industrial waste that OSM also tags landuse=landfill."""

import pytest

import scripts.discover_sites as ds


@pytest.mark.parametrize("name", ["Flyash Dump", "Fly Ash Pond", "Ash pond", "Reclaimed Sea Land - Ash Dyke A1",
                                  "NTPC Ash Ground", "Khetri Mine Tailing Resrvoir", "Tailings Dump", "spoil heaps",
                                  "Cyanide dump", "Slag Dumping"])
def test_industrial_waste_is_excluded(name):
    assert ds.INDUSTRIAL.search(name)


@pytest.mark.parametrize("name", ["Nashik Municipal Dumping Ground", "Mavallipura BBMP Landfill", "Municipal Landfill",
                                  "GVMC Dumpyard", "Mulund Dumping Ground", "Ramanchak Bairiya Landfill"])
def test_municipal_landfills_are_kept(name):
    assert not ds.INDUSTRIAL.search(name)  # "Nashik" contains "ash": whole words only


def test_generic_names_are_detected():
    assert set(ds.slug("Municipal Landfill").split("-")) <= ds.GENERIC
    assert not set(ds.slug("Mulund Dumping Ground").split("-")) <= ds.GENERIC


def test_every_discovered_site_has_an_unchecked_osm_outline():
    import yaml
    sites = yaml.safe_load((ds.ROOT / "data" / "sites.yaml").read_text(encoding="utf-8"))
    report = yaml.safe_load(ds.REPORT.read_text(encoding="utf-8"))
    kept = {d["site_id"] for d in report["decisions"] if d["decision"] == "kept"}
    by_id = {s["site_id"]: s for s in sites}
    for sid in kept:
        s = by_id[sid]
        assert s["polygon_source"] == "osm" and s["verified_by"] is None
        assert (ds.ROOT / s["polygon_path"]).exists()
