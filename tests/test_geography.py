"""Demo geography: synthetic sites placed inside the real OSM area boundaries."""

import json
import math
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "backend" / "fixtures"
PROFILES = json.loads((FIXTURES / "site_profiles.json").read_text(encoding="utf-8"))
AREAS = json.loads((FIXTURES / "bucharest_areas.geojson").read_text(encoding="utf-8"))
AREA_IDS = [f"sector-{n}" for n in range(1, 7)] + ["ilfov"]
SITES = PROFILES["profiles"]
CLUSTER_KINDS = {"residential", "hospitality", "commercial", "industrial", "logistics"}


def _in_ring(ring, lon, lat):
    """Even-odd ray casting; GeoJSON positions are [longitude, latitude]."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _polygons(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    assert geometry["type"] == "MultiPolygon"
    return geometry["coordinates"]


def areas_at(latitude, longitude):
    """Every area whose polygon (outer ring minus holes) contains the point."""
    return [
        feature["properties"]["area_id"]
        for feature in AREAS["features"]
        if any(
            _in_ring([p[:2] for p in polygon[0]], longitude, latitude)
            and not any(
                _in_ring([p[:2] for p in hole], longitude, latitude)
                for hole in polygon[1:]
            )
            for polygon in _polygons(feature["geometry"])
        )
    ]


def km(a, b):
    mean = math.radians((a["latitude"] + b["latitude"]) / 2)
    dy = (a["latitude"] - b["latitude"]) * 111.2
    dx = (a["longitude"] - b["longitude"]) * 111.2 * math.cos(mean)
    return math.hypot(dx, dy)


def test_boundaries_cover_the_seven_areas_with_attribution():
    assert [f["properties"]["area_id"] for f in AREAS["features"]].count("ilfov") == 1
    assert sorted(f["properties"]["area_id"] for f in AREAS["features"]) == sorted(
        AREA_IDS
    )
    assert "OpenStreetMap" in AREAS["attribution"] and "ODbL" in AREAS["attribution"]
    # Ilfov surrounds the city: the centre of Bucharest is in a sector, not in Ilfov.
    assert areas_at(44.4268, 26.1025) in (["sector-1"], ["sector-3"])


def test_areas_are_the_six_sectors_and_ilfov():
    assert list(PROFILES["areas"]) == AREA_IDS
    labels = [area["label"] for area in PROFILES["areas"].values()]
    assert labels == [f"Sector {n}" for n in range(1, 7)] + ["Ilfov"]
    for area_id, area in PROFILES["areas"].items():
        assert areas_at(area["latitude"], area["longitude"]) == [area_id]
    assert "SYNTHETIC" in PROFILES["note"]


@pytest.mark.parametrize("site", SITES, ids=[site["site_id"] for site in SITES])
def test_every_site_lies_inside_its_area(site):
    assert areas_at(site["latitude"], site["longitude"]) == [site["area_id"]]


def test_site_ids_names_and_distribution():
    ids = [site["site_id"] for site in SITES]
    assert len(ids) == len(set(ids))
    assert len({site["name"] for site in SITES}) == len(SITES)
    assert 55 <= len(SITES) <= 65
    prefix = {f"sector-{n}": f"s{n}" for n in range(1, 7)} | {"ilfov": "ilfov"}
    for area_id in AREA_IDS:
        numbers = [site["site_id"] for site in SITES if site["area_id"] == area_id]
        assert len(numbers) >= 4, area_id
        assert numbers == [
            f"{prefix[area_id]}-{n:02d}" for n in range(1, len(numbers) + 1)
        ]
    segments = Counter(site["segment"] for site in SITES)
    assert 30 <= segments["home"] <= 40 and set(segments) == {"home", "business"}
    business = [site for site in SITES if site["segment"] == "business"]
    # Restaurants, cafés, bars, a hotel and shops versus factories, warehouses and parks.
    small = [site for site in business if site["installed_kwp"] < 100]
    heavy = [site for site in business if site["installed_kwp"] >= 100]
    assert 8 <= len(small) <= 12 and 12 <= len(heavy) <= 18
    assert sum(site["area_id"] == "ilfov" for site in heavy) > len(heavy) / 2
    for site in SITES:
        assert site["business_type"] if site["segment"] == "business" else True
        low, high = (4, 10) if site["segment"] == "home" else (10, 600)
        assert low <= site["installed_kwp"] <= high, site["site_id"]
        if site["segment"] == "home":
            assert site["name"].startswith("Home · ")


def test_clusters_group_nearby_sites_in_one_area():
    clusters = {cluster["id"]: cluster for cluster in PROFILES["clusters"]}
    assert len(clusters) == len(PROFILES["clusters"])
    for cluster in clusters.values():
        assert cluster["area_id"] in AREA_IDS and cluster["kind"] in CLUSTER_KINDS
        members = [site for site in SITES if site["cluster"] == cluster["id"]]
        assert len(members) >= 2, cluster["id"]
        assert {site["area_id"] for site in members} == {cluster["area_id"]}
        for a, b in combinations(members, 2):
            assert km(a, b) <= 1.5, (a["site_id"], b["site_id"])
    assert {site["cluster"] for site in SITES} - {None} == set(clusters)
    militari = [site for site in SITES if site["cluster"] == "militari-homes"]
    assert len(militari) >= 6 and {site["area_id"] for site in militari} == {"sector-6"}
