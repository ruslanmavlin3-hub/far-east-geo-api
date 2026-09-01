from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List
import math
import requests
import time

app = FastAPI(
    title="Far East Land Geo API",
    description="Geo API for searching and checking land areas in the Russian Far East",
    version="2.1.0"
)

OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
]

REQUEST_HEADERS = {
    "User-Agent": "FarEastLandGeoAPI/2.1"
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
                timeout=40
            )

            if response.status_code == 200:
                data = response.json()
                data["_source_url"] = url
                return data

            errors.append(
                f"{url}: HTTP {response.status_code}"
            )

        except Exception as e:
            errors.append(
                f"{url}: {type(e).__name__}: {str(e)}"
            )

        time.sleep(1)

    raise HTTPException(
        status_code=502,
        detail={
            "message": "All Overpass API endpoints failed",
            "errors": errors
        }
    )


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


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "far-east-geo-api",
        "version": "2.1.0",
        "geo_source": "OpenStreetMap / Overpass API"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "far-east-geo-api",
        "version": "2.1.0"
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
        "message": "Point accepted. Use nearby-infrastructure for real geographic analysis."
    }


@app.get("/nearby-infrastructure")
def nearby_infrastructure(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10, gt=0, le=50)
):
    radius_m = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:25];
    (
      way(around:{radius_m},{lat},{lon})["highway"];
      node(around:{radius_m},{lat},{lon})["place"];
      way(around:{radius_m},{lat},{lon})["railway"];
      node(around:{radius_m},{lat},{lon})["railway"="station"];
      way(around:{radius_m},{lat},{lon})["landuse"="industrial"];
      relation(around:{radius_m},{lat},{lon})["landuse"="industrial"];
      node(around:{radius_m},{lat},{lon})["power"="substation"];
      way(around:{radius_m},{lat},{lon})["power"="line"];
      node(around:{radius_m},{lat},{lon})["power"="plant"];
    );
    out center tags;
    """

    data = overpass_request(query)

    result = {
        "roads": [],
        "railways": [],
        "settlements": [],
        "industrial": [],
        "power": []
    }

    for element in data.get("elements", []):
        tags = element.get("tags", {})

        item = normalize_element(
            element,
            lat,
            lon
        )

        if "highway" in tags:
            result["roads"].append(item)

        elif "place" in tags:
            result["settlements"].append(item)

        elif "railway" in tags:
            result["railways"].append(item)

        elif tags.get("landuse") == "industrial":
            result["industrial"].append(item)

        elif "power" in tags:
            result["power"].append(item)

    for category in result:
        result[category].sort(
            key=lambda x: (
                x["distance_km"]
                if x["distance_km"] is not None
                else 999999
            )
        )

        result[category] = result[category][:20]

    return {
        "status": "ok",
        "source": "OpenStreetMap / Overpass API",
        "source_endpoint": data.get("_source_url"),
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        **result,
        "warning": (
            "OpenStreetMap data is preliminary and does not confirm "
            "legal availability, cadastral boundaries, ZOUIT, "
            "ownership, public servitudes or eligibility under Federal Law 119-FZ."
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
            "Automatic candidate generation will be added after "
            "the infrastructure and cadastral modules are validated."
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
            "Do not treat this response as confirmation that the land is available."
        )
    }
