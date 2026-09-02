from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List
import math
import requests
import time

app = FastAPI(
    title="Far East Land Geo API",
    description="Geo API for searching and checking land areas in the Russian Far East",
    version="2.2.0"
)

OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

REQUEST_HEADERS = {
    "User-Agent": "FarEastLandGeoAPI/2.2"
}


class ContourRequest(BaseModel):
    type: str = "Polygon"
    coordinates: List[List[List[float]]]


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    return 2 * r * math.asin(math.sqrt(a))


def overpass_request(query):
    errors = []

    for url in OVERPASS_URLS:
        try:
            response = requests.post(
                url,
                data={"data": query},
                headers=REQUEST_HEADERS,
                timeout=20
            )

            if response.status_code == 200:
                data = response.json()

                return {
                    "ok": True,
                    "source": url,
                    "elements": data.get("elements", [])
                }

            errors.append(
                f"{url}: HTTP {response.status_code}"
            )

        except Exception as e:
            errors.append(
                f"{url}: {type(e).__name__}: {str(e)}"
            )

        time.sleep(0.4)

    return {
        "ok": False,
        "source": None,
        "elements": [],
        "errors": errors
    }


def element_location(element):
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]

    center = element.get("center")

    if center:
        return center.get("lat"), center.get("lon")

    return None, None


def normalize_element(element, lat, lon):
    tags = element.get("tags", {})

    obj_lat, obj_lon = element_location(element)

    distance = None

    if obj_lat is not None and obj_lon is not None:
        distance = round(
            haversine(lat, lon, obj_lat, obj_lon),
            3
        )

    return {
        "osm_type": element.get("type"),
        "osm_id": element.get("id"),
        "name": tags.get("name", "Unnamed"),
        "lat": obj_lat,
        "lon": obj_lon,
        "distance_km": distance,
        "tags": tags
    }


def run_category(query, lat, lon, limit=15):
    response = overpass_request(query)

    items = []

    for element in response.get("elements", []):
        items.append(
            normalize_element(
                element,
                lat,
                lon
            )
        )

    items.sort(
        key=lambda x:
        x["distance_km"]
        if x["distance_km"] is not None
        else 999999
    )

    return {
        "status": "ok" if response["ok"] else "unavailable",
        "source": response.get("source"),
        "items": items[:limit],
        "errors": response.get("errors", [])
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "far-east-geo-api",
        "version": "2.2.0",
        "geo_source": "OpenStreetMap / multiple Overpass endpoints"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "far-east-geo-api",
        "version": "2.2.0"
    }


@app.get("/check-point")
def check_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180)
):
    return {
        "lat": lat,
        "lon": lon,
        "status": "accepted",
        "message": (
            "Point accepted. "
            "Use nearby-infrastructure for geographic analysis."
        )
    }


@app.get("/nearby-infrastructure")
def nearby_infrastructure(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5, gt=0, le=25)
):

    radius_m = int(radius_km * 1000)

    road_query = f"""
    [out:json][timeout:12];
    way(around:{radius_m},{lat},{lon})
      ["highway"~"motorway|trunk|primary|secondary|tertiary"];
    out center tags 20;
    """

    settlement_query = f"""
    [out:json][timeout:12];
    node(around:{radius_m},{lat},{lon})
      ["place"~"city|town|village|hamlet"];
    out tags 15;
    """

    railway_query = f"""
    [out:json][timeout:12];
    (
      way(around:{radius_m},{lat},{lon})
        ["railway"="rail"];
      node(around:{radius_m},{lat},{lon})
        ["railway"="station"];
    );
    out center tags 15;
    """

    industrial_query = f"""
    [out:json][timeout:12];
    (
      way(around:{radius_m},{lat},{lon})
        ["landuse"="industrial"];
      relation(around:{radius_m},{lat},{lon})
        ["landuse"="industrial"];
    );
    out center tags 15;
    """

    power_query = f"""
    [out:json][timeout:12];
    (
      node(around:{radius_m},{lat},{lon})
        ["power"="substation"];
      way(around:{radius_m},{lat},{lon})
        ["power"="line"];
      node(around:{radius_m},{lat},{lon})
        ["power"="plant"];
    );
    out center tags 15;
    """

    roads = run_category(
        road_query,
        lat,
        lon
    )

    settlements = run_category(
        settlement_query,
        lat,
        lon
    )

    railways = run_category(
        railway_query,
        lat,
        lon
    )

    industrial = run_category(
        industrial_query,
        lat,
        lon
    )

    power = run_category(
        power_query,
        lat,
        lon
    )

    successful_categories = sum([
        roads["status"] == "ok",
        settlements["status"] == "ok",
        railways["status"] == "ok",
        industrial["status"] == "ok",
        power["status"] == "ok"
    ])

    return {
        "status": (
            "ok"
            if successful_categories > 0
            else "external_sources_unavailable"
        ),
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "successful_categories": successful_categories,
        "roads": roads,
        "settlements": settlements,
        "railways": railways,
        "industrial": industrial,
        "power": power,
        "warning": (
            "OpenStreetMap data is preliminary. "
            "It does not confirm legal availability, "
            "cadastral boundaries, ZOUIT, ownership, "
            "public servitudes or eligibility under Federal Law 119-FZ."
        )
    }


@app.get("/search-area")
def search_area(
    region: str,
    center: str = "",
    radius_km: float = Query(20, gt=0, le=100),
    purpose: str = "warehouse"
):
    return {
        "region": region,
        "center": center,
        "radius_km": radius_km,
        "purpose": purpose,
        "status": "preliminary",
        "candidates": [],
        "message": (
            "Automatic candidate generation will be added "
            "after infrastructure and cadastral modules are validated."
        )
    }


@app.post("/check-contour")
def check_contour(data: ContourRequest):
    coordinates = data.coordinates

    if not coordinates or not coordinates[0]:
        raise HTTPException(
            status_code=400,
            detail="Polygon coordinates are required."
        )

    return {
        "status": "preliminary",
        "received": data.model_dump(),
        "intersections": [],
        "restrictions": [],
        "warnings": [
            "Cadastral and legal restriction sources are not connected yet."
        ],
        "message": (
            "Contour geometry accepted. "
            "Do not treat this response as confirmation "
            "that the land is available."
        )
    }
