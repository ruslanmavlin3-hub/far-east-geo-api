from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from math import radians, sin, cos, sqrt, atan2
import requests
import time


# ============================================================
# FAR EAST GEO API
# Stable API contract: v3.0
# ============================================================

app = FastAPI(
    title="Far East Land Geo API",
    description=(
        "Geographic and preliminary land-analysis API for the "
        "Far East / Arctic hectare workflow."
    ),
    version="3.0.0"
)


# ============================================================
# SETTINGS
# ============================================================

OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

NOMINATIM_URLS = [
    "https://nominatim.openstreetmap.org/search"
]

HEADERS = {
    "User-Agent": "FarEastGeoAPI/3.0 land-research-service"
}


# ============================================================
# MODELS
# ============================================================

class ContourRequest(BaseModel):
    type: str = "Polygon"
    coordinates: List[List[List[float]]]


class CandidateScoreRequest(BaseModel):
    purpose: str = "general"

    legal_availability: Optional[float] = None
    roads: Optional[float] = None
    power: Optional[float] = None
    development_drivers: Optional[float] = None
    purpose_fit: Optional[float] = None
    physical_characteristics: Optional[float] = None
    liquidity: Optional[float] = None
    development_cost: Optional[float] = None

    stop_factors: Optional[List[str]] = []


# ============================================================
# HELPERS
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    """
    Distance between two points in kilometers.
    """
    r = 6371.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return r * c


def overpass_request(query: str):
    """
    Try several public Overpass endpoints.

    Failure of one provider does not break the API.
    """

    errors = []

    for url in OVERPASS_URLS:
        try:
            response = requests.post(
                url,
                data={"data": query},
                headers=HEADERS,
                timeout=18
            )

            if response.status_code == 200:
                data = response.json()

                return {
                    "ok": True,
                    "source": url,
                    "elements": data.get("elements", []),
                    "errors": errors
                }

            errors.append(
                f"{url}: HTTP {response.status_code}"
            )

        except Exception as exc:
            errors.append(
                f"{url}: {type(exc).__name__}: {str(exc)[:180]}"
            )

    return {
        "ok": False,
        "source": None,
        "elements": [],
        "errors": errors
    }


def element_coordinates(element):
    """
    Get representative coordinates from an OSM element.
    """

    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]

    center = element.get("center")

    if center:
        return center.get("lat"), center.get("lon")

    return None, None


def normalize_element(element, origin_lat, origin_lon):
    lat, lon = element_coordinates(element)

    distance = None

    if lat is not None and lon is not None:
        distance = round(
            haversine(
                origin_lat,
                origin_lon,
                float(lat),
                float(lon)
            ),
            3
        )

    tags = element.get("tags", {})

    return {
        "osm_type": element.get("type"),
        "osm_id": element.get("id"),
        "name": (
            tags.get("name")
            or tags.get("ref")
            or tags.get("operator")
            or "Unnamed object"
        ),
        "lat": lat,
        "lon": lon,
        "distance_km": distance,
        "tags": tags
    }


def run_category(
    name: str,
    query: str,
    origin_lat: float,
    origin_lon: float,
    limit: int = 20
):
    result = overpass_request(query)

    if not result["ok"]:
        return {
            "status": "source_error",
            "source": None,
            "items": [],
            "errors": result["errors"]
        }

    items = []

    for element in result["elements"]:
        try:
            items.append(
                normalize_element(
                    element,
                    origin_lat,
                    origin_lon
                )
            )
        except Exception:
            continue

    items.sort(
        key=lambda item: (
            item["distance_km"]
            if item["distance_km"] is not None
            else 999999
        )
    )

    return {
        "status": "ok",
        "source": result["source"],
        "items": items[:limit],
        "errors": result["errors"]
    }


def geocode_place(place: str):
    """
    Preliminary geocoding using OpenStreetMap Nominatim.
    """

    errors = []

    for url in NOMINATIM_URLS:
        try:
            response = requests.get(
                url,
                params={
                    "q": place,
                    "format": "jsonv2",
                    "limit": 5,
                    "countrycodes": "ru"
                },
                headers=HEADERS,
                timeout=15
            )

            if response.status_code != 200:
                errors.append(
                    f"{url}: HTTP {response.status_code}"
                )
                continue

            data = response.json()

            results = []

            for item in data:
                results.append({
                    "display_name": item.get("display_name"),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type"),
                    "category": item.get("category"),
                    "importance": item.get("importance")
                })

            return {
                "status": "ok",
                "source": "OpenStreetMap Nominatim",
                "results": results,
                "errors": errors
            }

        except Exception as exc:
            errors.append(
                f"{url}: {type(exc).__name__}: {str(exc)[:180]}"
            )

    return {
        "status": "source_error",
        "source": None,
        "results": [],
        "errors": errors
    }


def infrastructure_queries(lat, lon, radius_km):
    radius_m = int(radius_km * 1000)

    roads = f"""
    [out:json][timeout:12];
    (
      way(around:{radius_m},{lat},{lon})
        ["highway"~"motorway|trunk|primary|secondary|tertiary"];
    );
    out center tags 40;
    """

    settlements = f"""
    [out:json][timeout:12];
    (
      node(around:{radius_m},{lat},{lon})
        ["place"~"city|town|village|hamlet"];
    );
    out tags 30;
    """

    railways = f"""
    [out:json][timeout:12];
    (
      way(around:{radius_m},{lat},{lon})["railway"="rail"];
      node(around:{radius_m},{lat},{lon})
        ["railway"~"station|halt"];
    );
    out center tags 30;
    """

    industrial = f"""
    [out:json][timeout:12];
    (
      way(around:{radius_m},{lat},{lon})["landuse"="industrial"];
      relation(around:{radius_m},{lat},{lon})["landuse"="industrial"];
      node(around:{radius_m},{lat},{lon})["industrial"];
      way(around:{radius_m},{lat},{lon})["industrial"];
    );
    out center tags 30;
    """

    power = f"""
    [out:json][timeout:12];
    (
      node(around:{radius_m},{lat},{lon})
        ["power"~"substation|plant"];
      way(around:{radius_m},{lat},{lon})
        ["power"~"line|minor_line|substation|plant"];
      relation(around:{radius_m},{lat},{lon})
        ["power"~"substation|plant"];
    );
    out center tags 40;
    """

    return {
        "roads": roads,
        "settlements": settlements,
        "railways": railways,
        "industrial": industrial,
        "power": power
    }


def get_infrastructure(lat, lon, radius_km):
    queries = infrastructure_queries(
        lat,
        lon,
        radius_km
    )

    result = {}

    successful = 0

    for category, query in queries.items():
        category_result = run_category(
            category,
            query,
            lat,
            lon
        )

        result[category] = category_result

        if category_result["status"] == "ok":
            successful += 1

        time.sleep(0.15)

    return successful, result


def nearest_distance(category_result):
    if (
        not category_result
        or category_result.get("status") != "ok"
        or not category_result.get("items")
    ):
        return None

    distances = [
        item.get("distance_km")
        for item in category_result["items"]
        if item.get("distance_km") is not None
    ]

    if not distances:
        return None

    return min(distances)


def clamp(value, low, high):
    return max(low, min(value, high))


# ============================================================
# 1. HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Far East Land Geo API",
        "version": "3.0.0",
        "stable_contract": True
    }


# ============================================================
# 2. CHECK POINT
# ============================================================

@app.get("/check-point")
def check_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180)
):
    return {
        "status": "ok",
        "lat": lat,
        "lon": lon,
        "message": (
            "Coordinate point accepted. "
            "Use land-check for preliminary land status and "
            "nearby-infrastructure for surrounding infrastructure."
        )
    }


# ============================================================
# 3. GEOCODE
# ============================================================

@app.get("/geocode")
def geocode(
    place: str = Query(..., min_length=2)
):
    return geocode_place(place)


# ============================================================
# 4. INFRASTRUCTURE
# ============================================================

@app.get("/nearby-infrastructure")
def nearby_infrastructure(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5, ge=0.2, le=25)
):
    successful, data = get_infrastructure(
        lat,
        lon,
        radius_km
    )

    if successful == 0:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "All external infrastructure sources "
                    "are temporarily unavailable."
                ),
                "categories": data
            }
        )

    return {
        "status": "ok",
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "successful_categories": successful,
        **data,
        "warning": (
            "Infrastructure data is preliminary and mainly "
            "derived from OpenStreetMap. Presence of a road, "
            "power line or other object does not confirm legal "
            "access, connection availability or land availability."
        )
    }


# ============================================================
# 5. LAND CHECK
# Permanent response structure.
#
# Important:
# unavailable legal sources MUST return explicit statuses.
# Never fabricate cadastral / NSPD / FIS results.
# ============================================================

@app.get("/land-check")
def land_check(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180)
):
    return {
        "status": "partial",
        "lat": lat,
        "lon": lon,

        "cadastral": {
            "status": "not_connected",
            "objects": [],
            "source": None
        },

        "nspd": {
            "status": "manual_verification_required",
            "objects": [],
            "source": None
        },

        "fis_119fz": {
            "status": "manual_verification_required",
            "available_for_formation": None,
            "source": None
        },

        "zouit": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "public_servitudes": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "forest": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "water": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "protected_areas": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "cultural_heritage": {
            "status": "not_connected",
            "items": [],
            "source": None
        },

        "territorial_zoning": {
            "status": "not_connected",
            "zone": None,
            "permitted_uses": [],
            "source": None
        },

        "legal_conclusion": {
            "land_availability_confirmed": False,
            "status": "insufficient_official_data"
        },

        "message": (
            "The API contract for cadastral, NSPD, FIS 119-FZ, "
            "ZOUIT and other legal layers is active. "
            "Real official sources are not yet connected. "
            "Do not treat this result as confirmation that "
            "the land can be formed or obtained."
        )
    }


# ============================================================
# 6. RESTRICTIONS
# ============================================================

@app.get("/restrictions")
def restrictions(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(100, ge=1, le=5000)
):
    return {
        "status": "partial",
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,

        "zouit": [],
        "public_servitudes": [],
        "forest": [],
        "water": [],
        "protected_areas": [],
        "cultural_heritage": [],
        "other": [],

        "sources": {
            "nspd": "manual_verification_required",
            "egrn": "not_connected",
            "other_official_sources": "not_connected"
        },

        "restriction_free_confirmed": False,

        "message": (
            "Restriction-source adapters are reserved in API v3.0 "
            "but official restriction datasets are not yet connected."
        )
    }


# ============================================================
# 7. CONTOUR CHECK
# ============================================================

@app.post("/check-contour")
def check_contour(data: ContourRequest):
    coordinates = data.coordinates

    if not coordinates or not coordinates[0]:
        raise HTTPException(
            status_code=400,
            detail="Polygon coordinates are required."
        )

    ring = coordinates[0]

    if len(ring) < 4:
        raise HTTPException(
            status_code=400,
            detail=(
                "Polygon must contain at least four coordinate "
                "pairs including the closing point."
            )
        )

    normalized = []

    for pair in ring:
        if len(pair) < 2:
            raise HTTPException(
                status_code=400,
                detail="Each coordinate must contain longitude and latitude."
            )

        lon = float(pair[0])
        lat = float(pair[1])

        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise HTTPException(
                status_code=400,
                detail="Invalid polygon coordinates."
            )

        normalized.append([lon, lat])

    lons = [point[0] for point in normalized]
    lats = [point[1] for point in normalized]

    center_lon = sum(lons) / len(lons)
    center_lat = sum(lats) / len(lats)

    return {
        "status": "partial",
        "geometry": {
            "type": data.type,
            "coordinates": coordinates,
            "center": {
                "lat": center_lat,
                "lon": center_lon
            }
        },

        "existing_parcel_intersections": {
            "status": "not_connected",
            "items": []
        },

        "nspd": {
            "status": "manual_verification_required",
            "items": []
        },

        "fis_119fz": {
            "status": "manual_verification_required",
            "available_for_formation": None
        },

        "restrictions": {
            "status": "not_connected",
            "items": []
        },

        "formation_possible_confirmed": False,

        "warnings": [
            (
                "Contour geometry is accepted, but official cadastral "
                "and legal layers are not yet connected."
            ),
            (
                "A visually free area must not be treated as legally "
                "available under Federal Law 119-FZ."
            )
        ]
    }


# ============================================================
# 8. SEARCH AREA
#
# This is a geographic candidate search.
# It does NOT assert cadastral availability.
# ============================================================

@app.get("/search-area")
def search_area(
    region: str = Query(..., min_length=2),
    center: Optional[str] = Query(None),
    radius_km: float = Query(20, ge=1, le=100),
    purpose: str = Query("general")
):
    search_name = center if center else region

    geo = geocode_place(search_name)

    if geo["status"] != "ok" or not geo["results"]:
        return {
            "status": "geocode_failed",
            "region": region,
            "center": center,
            "purpose": purpose,
            "radius_km": radius_km,
            "candidates": [],
            "geocode": geo
        }

    origin = geo["results"][0]

    lat = origin["lat"]
    lon = origin["lon"]

    # A small permanent search grid.
    # This can later be upgraded internally without changing the API contract.

    delta_lat = min(radius_km, 25) / 111.0
    cos_lat = max(cos(radians(lat)), 0.2)
    delta_lon = min(radius_km, 25) / (111.0 * cos_lat)

    candidate_points = [
        {
            "name": "Center",
            "lat": lat,
            "lon": lon
        },
        {
            "name": "North sector",
            "lat": lat + delta_lat * 0.55,
            "lon": lon
        },
        {
            "name": "South sector",
            "lat": lat - delta_lat * 0.55,
            "lon": lon
        },
        {
            "name": "East sector",
            "lat": lat,
            "lon": lon + delta_lon * 0.55
        },
        {
            "name": "West sector",
            "lat": lat,
            "lon": lon - delta_lon * 0.55
        }
    ]

    candidates = []

    # Limit external calls to avoid excessive Overpass load.
    for point in candidate_points[:3]:
        successful, infra = get_infrastructure(
            point["lat"],
            point["lon"],
            min(10, radius_km)
        )

        road_distance = nearest_distance(
            infra.get("roads")
        )

        settlement_distance = nearest_distance(
            infra.get("settlements")
        )

        industrial_distance = nearest_distance(
            infra.get("industrial")
        )

        power_distance = nearest_distance(
            infra.get("power")
        )

        score = 0

        if road_distance is not None:
            if road_distance <= 1:
                score += 30
            elif road_distance <= 3:
                score += 24
            elif road_distance <= 5:
                score += 18
            elif road_distance <= 10:
                score += 10

        if power_distance is not None:
            if power_distance <= 2:
                score += 20
            elif power_distance <= 5:
                score += 14
            elif power_distance <= 10:
                score += 8

        if settlement_distance is not None:
            if settlement_distance <= 5:
                score += 20
            elif settlement_distance <= 15:
                score += 12
            elif settlement_distance <= 25:
                score += 6

        if industrial_distance is not None:
            if industrial_distance <= 5:
                score += 20
            elif industrial_distance <= 15:
                score += 12

        score += min(successful * 2, 10)

        candidates.append({
            **point,
            "geographic_score": min(score, 100),
            "nearest": {
                "road_km": road_distance,
                "settlement_km": settlement_distance,
                "industrial_km": industrial_distance,
                "power_km": power_distance
            },
            "successful_infrastructure_categories": successful,

            "legal_status": {
                "status": "not_verified",
                "land_availability_confirmed": False,
                "nspd": "manual_verification_required",
                "fis_119fz": "manual_verification_required"
            }
        })

    candidates.sort(
        key=lambda item: item["geographic_score"],
        reverse=True
    )

    return {
        "status": "preliminary",
        "region": region,
        "center": center,
        "resolved_center": origin,
        "purpose": purpose,
        "radius_km": radius_km,
        "candidates": candidates,
        "warning": (
            "Candidates are ranked only by preliminary geographic "
            "and infrastructure factors. They are NOT confirmed as "
            "free, cadastral-free, or available under Federal Law 119-FZ."
        )
    }


# ============================================================
# 9. CANDIDATE SCORE
#
# Permanent investment scoring contract.
# ============================================================

@app.post("/candidate-score")
def candidate_score(data: CandidateScoreRequest):
    if data.stop_factors:
        return {
            "status": "stop",
            "purpose": data.purpose,
            "score": 0,
            "rating": "STOP",
            "stop_factors": data.stop_factors,
            "message": (
                "One or more stop factors were supplied. "
                "Candidate should not receive a positive investment rating "
                "until they are resolved."
            )
        }

    components = {
        "legal_availability": {
            "weight": 25,
            "value": data.legal_availability
        },
        "roads": {
            "weight": 15,
            "value": data.roads
        },
        "power": {
            "weight": 10,
            "value": data.power
        },
        "development_drivers": {
            "weight": 15,
            "value": data.development_drivers
        },
        "purpose_fit": {
            "weight": 15,
            "value": data.purpose_fit
        },
        "physical_characteristics": {
            "weight": 10,
            "value": data.physical_characteristics
        },
        "liquidity": {
            "weight": 5,
            "value": data.liquidity
        },
        "development_cost": {
            "weight": 5,
            "value": data.development_cost
        }
    }

    total_score = 0
    evaluated_weight = 0
    breakdown = {}

    for name, component in components.items():
        weight = component["weight"]
        value = component["value"]

        if value is None:
            breakdown[name] = {
                "weight": weight,
                "input": None,
                "points": None,
                "status": "not_evaluated"
            }
            continue

        value = clamp(float(value), 0, 100)

        points = round(
            weight * value / 100,
            2
        )

        total_score += points
        evaluated_weight += weight

        breakdown[name] = {
            "weight": weight,
            "input": value,
            "points": points,
            "status": "evaluated"
        }

    total_score = round(total_score, 2)

    if total_score >= 80:
        rating = "HIGH"
    elif total_score >= 60:
        rating = "MEDIUM_HIGH"
    elif total_score >= 40:
        rating = "MEDIUM"
    else:
        rating = "LOW"

    legal_confirmed = (
        data.legal_availability is not None
        and data.legal_availability >= 80
    )

    return {
        "status": "ok",
        "purpose": data.purpose,
        "score": total_score,
        "max_score": 100,
        "evaluated_weight": evaluated_weight,
        "rating": rating,
        "breakdown": breakdown,

        "legal_availability_confirmed": legal_confirmed,

        "warning": (
            "A high investment score must not be treated as confirmation "
            "of legal availability. Official cadastral, NSPD, FIS 119-FZ "
            "and restriction checks prevail."
        )
    }
