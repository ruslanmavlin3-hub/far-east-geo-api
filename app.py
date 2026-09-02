from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from math import radians, sin, cos, sqrt, atan2
import requests
import time
import math


# ============================================================
# FAR EAST LAND GEO API
# VERSION 3.1.0
# ============================================================

app = FastAPI(
    title="Far East Land Geo API",
    description=(
        "Geo, infrastructure and preliminary land analysis API "
        "for Far East / Arctic hectare workflows."
    ),
    version="3.1.0"
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

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

HEADERS = {
    "User-Agent": "FarEastGeoAPI/3.1 land-research-service"
}


# ============================================================
# NSPD SETTINGS
# ============================================================

NSPD_REFERER = "https://nspd.gov.ru/map"

NSPD_HEADERS = {
    "User-Agent": "Mozilla/5.0 FarEastGeoAPI/3.1",
    "Referer": NSPD_REFERER,
    "Accept": "application/json,text/plain,*/*"
}

NSPD_LAYERS = {
    "land_parcels_egrn": {
        "id": "36048",
        "name": "Земельные участки из ЕГРН"
    },
    "cadastral_quarters": {
        "id": "36071",
        "name": "Кадастровые кварталы"
    },
    "scheme_parcels": {
        "id": "37294",
        "name": "Земельные участки, образуемые по схеме"
    },
    "third_party_rights_free": {
        "id": "37298",
        "name": "Земельные участки, свободные от прав третьих лиц"
    },
    "auction_parcels": {
        "id": "37299",
        "name": "Земельные участки, выставленные на аукцион"
    }
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
# BASIC HELPERS
# ============================================================

def haversine(lat1, lon1, lat2, lon2):

    r = 6371.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a)
    )

    return r * c


def clamp(value, low, high):
    return max(low, min(value, high))


# ============================================================
# OVERPASS
# ============================================================

def overpass_request(query):

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

    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"]

    center = element.get("center")

    if center:
        return center.get("lat"), center.get("lon")

    return None, None


def normalize_element(
    element,
    origin_lat,
    origin_lon
):

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
    query,
    origin_lat,
    origin_lon,
    limit=20
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
        key=lambda item:
        item["distance_km"]
        if item["distance_km"] is not None
        else 999999
    )

    return {
        "status": "ok",
        "source": result["source"],
        "items": items[:limit],
        "errors": result["errors"]
    }


# ============================================================
# INFRASTRUCTURE
# ============================================================

def infrastructure_queries(
    lat,
    lon,
    radius_km
):

    radius_m = int(radius_km * 1000)

    return {

        "roads": f"""
        [out:json][timeout:12];
        (
          way(around:{radius_m},{lat},{lon})
          ["highway"~"motorway|trunk|primary|secondary|tertiary"];
        );
        out center tags 40;
        """,

        "settlements": f"""
        [out:json][timeout:12];
        (
          node(around:{radius_m},{lat},{lon})
          ["place"~"city|town|village|hamlet"];
        );
        out tags 30;
        """,

        "railways": f"""
        [out:json][timeout:12];
        (
          way(around:{radius_m},{lat},{lon})
          ["railway"="rail"];

          node(around:{radius_m},{lat},{lon})
          ["railway"~"station|halt"];
        );
        out center tags 30;
        """,

        "industrial": f"""
        [out:json][timeout:12];
        (
          way(around:{radius_m},{lat},{lon})
          ["landuse"="industrial"];

          relation(around:{radius_m},{lat},{lon})
          ["landuse"="industrial"];

          node(around:{radius_m},{lat},{lon})
          ["industrial"];

          way(around:{radius_m},{lat},{lon})
          ["industrial"];
        );
        out center tags 30;
        """,

        "power": f"""
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
    }


def get_infrastructure(
    lat,
    lon,
    radius_km
):

    queries = infrastructure_queries(
        lat,
        lon,
        radius_km
    )

    result = {}
    successful = 0

    for category, query in queries.items():

        category_result = run_category(
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
        item["distance_km"]
        for item in category_result["items"]
        if item.get("distance_km") is not None
    ]

    if not distances:
        return None

    return min(distances)


# ============================================================
# GEOCODING
# ============================================================

def geocode_place(place):

    try:

        response = requests.get(
            NOMINATIM_URL,
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

            return {
                "status": "source_error",
                "results": [],
                "error": f"HTTP {response.status_code}"
            }

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
            "results": results
        }

    except Exception as exc:

        return {
            "status": "source_error",
            "results": [],
            "error": str(exc)
        }


# ============================================================
# NSPD
# ============================================================

def wgs84_to_web_mercator(
    lat,
    lon
):

    x = lon * 20037508.34 / 180.0

    lat = max(
        min(lat, 89.5),
        -89.5
    )

    y = math.log(
        math.tan(
            (90 + lat)
            * math.pi
            / 360
        )
    )

    y = (
        y
        / (math.pi / 180)
        * 20037508.34
        / 180
    )

    return x, y


def nspd_get_feature_info(
    lat,
    lon,
    layer_id,
    size_meters=100,
    feature_count=20
):

    x, y = wgs84_to_web_mercator(
        lat,
        lon
    )

    half = max(
        size_meters / 2,
        1
    )

    bbox = (
        f"{x-half},{y-half},"
        f"{x+half},{y+half}"
    )

    url = (
        f"https://nspd.gov.ru/"
        f"api/aeggis/v3/"
        f"{layer_id}/wms"
    )

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetFeatureInfo",
        "LAYERS": str(layer_id),
        "QUERY_LAYERS": str(layer_id),
        "CRS": "EPSG:3857",
        "BBOX": bbox,
        "WIDTH": 800,
        "HEIGHT": 800,
        "I": 400,
        "J": 400,
        "INFO_FORMAT": "application/json",
        "STYLES": "",
        "FORMAT": "image/png",
        "FEATURE_COUNT": feature_count
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=NSPD_HEADERS,
            timeout=20
        )

        if response.status_code != 200:

            return {
                "status": "source_error",
                "features": [],
                "source": url,
                "http_status": response.status_code,
                "error": response.text[:300]
            }

        try:
            data = response.json()

        except Exception:

            return {
                "status": "invalid_response",
                "features": [],
                "source": url,
                "error": response.text[:300]
            }

        return {
            "status": "checked",
            "features": data.get(
                "features",
                []
            ),
            "source": url
        }

    except Exception as exc:

        return {
            "status": "source_error",
            "features": [],
            "source": url,
            "error": (
                f"{type(exc).__name__}: "
                f"{str(exc)[:250]}"
            )
        }


def extract_nspd_objects(features):

    objects = []

    for feature in features:

        props = (
            feature.get(
                "properties",
                {}
            )
            or {}
        )

        options = (
            props.get(
                "options",
                {}
            )
            or {}
        )

        cadastral_number = (
            options.get("cad_num")
            or options.get("cad_number")
            or options.get("cn")
            or props.get("descr")
            or props.get("name")
        )

        objects.append({
            "cadastral_number": cadastral_number,
            "feature_id": feature.get("id"),
            "geometry_type": (
                feature.get(
                    "geometry",
                    {}
                )
                or {}
            ).get("type"),
            "properties": props
        })

    return objects


def check_nspd_layer(
    lat,
    lon,
    layer_key,
    size_meters=100,
    feature_count=20
):

    layer = NSPD_LAYERS[
        layer_key
    ]

    result = nspd_get_feature_info(
        lat=lat,
        lon=lon,
        layer_id=layer["id"],
        size_meters=size_meters,
        feature_count=feature_count
    )

    objects = extract_nspd_objects(
        result.get(
            "features",
            []
        )
    )

    return {
        "status": result.get(
            "status",
            "source_error"
        ),
        "layer_id": layer["id"],
        "layer_name": layer["name"],
        "objects_found": len(objects),
        "objects": objects,
        "source": result.get("source"),
        "error": result.get("error")
    }


# ============================================================
# API 1 — HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "Far East Land Geo API",
        "version": "3.1.0",
        "stable_contract": True
    }


# ============================================================
# API 2 — CHECK POINT
# ============================================================

@app.get("/check-point")
def check_point(
    lat: float = Query(
        ...,
        ge=-90,
        le=90
    ),
    lon: float = Query(
        ...,
        ge=-180,
        le=180
    )
):

    return {
        "status": "ok",
        "lat": lat,
        "lon": lon
    }


# ============================================================
# API 3 — GEOCODE
# ============================================================

@app.get("/geocode")
def geocode(
    place: str = Query(
        ...,
        min_length=2
    )
):

    return geocode_place(place)


# ============================================================
# API 4 — INFRASTRUCTURE
# ============================================================

@app.get("/nearby-infrastructure")
def nearby_infrastructure(
    lat: float = Query(
        ...,
        ge=-90,
        le=90
    ),
    lon: float = Query(
        ...,
        ge=-180,
        le=180
    ),
    radius_km: float = Query(
        5,
        ge=0.2,
        le=25
    )
):

    successful, data = (
        get_infrastructure(
            lat,
            lon,
            radius_km
        )
    )

    if successful == 0:

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                "All infrastructure sources unavailable.",
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
            "Infrastructure data is preliminary. "
            "It does not confirm legal access, "
            "connection possibility or land availability."
        )
    }


# ============================================================
# API 5 — LAND CHECK
# ============================================================

@app.get("/land-check")
def land_check(
    lat: float = Query(
        ...,
        ge=-90,
        le=90
    ),
    lon: float = Query(
        ...,
        ge=-180,
        le=180
    )
):

    land_parcels = check_nspd_layer(
        lat,
        lon,
        "land_parcels_egrn",
        80,
        20
    )

    cadastral_quarters = check_nspd_layer(
        lat,
        lon,
        "cadastral_quarters",
        200,
        10
    )

    scheme_parcels = check_nspd_layer(
        lat,
        lon,
        "scheme_parcels",
        100,
        20
    )

    rights_free = check_nspd_layer(
        lat,
        lon,
        "third_party_rights_free",
        100,
        20
    )

    auction = check_nspd_layer(
        lat,
        lon,
        "auction_parcels",
        100,
        20
    )

    all_layers = [
        land_parcels,
        cadastral_quarters,
        scheme_parcels,
        rights_free,
        auction
    ]

    successful_layers = sum(
        1
        for layer in all_layers
        if layer["status"] == "checked"
    )

    mapped_parcel = None

    if land_parcels["status"] == "checked":
        mapped_parcel = (
            land_parcels[
                "objects_found"
            ] > 0
        )

    scheme_detected = (
        scheme_parcels[
            "status"
        ] == "checked"
        and
        scheme_parcels[
            "objects_found"
        ] > 0
    )

    rights_free_detected = (
        rights_free[
            "status"
        ] == "checked"
        and
        rights_free[
            "objects_found"
        ] > 0
    )

    auction_detected = (
        auction[
            "status"
        ] == "checked"
        and
        auction[
            "objects_found"
        ] > 0
    )

    positive_signals = []
    verification_required = []

    if mapped_parcel is False:

        positive_signals.append(
            "В слое участков ЕГРН "
            "объект в точке не обнаружен."
        )

    if rights_free_detected:

        positive_signals.append(
            "НСПД отображает объект "
            "в слое свободных от прав "
            "третьих лиц."
        )

    if mapped_parcel is True:

        verification_required.append(
            "В точке обнаружен "
            "кадастровый объект."
        )

    if scheme_detected:

        verification_required.append(
            "Обнаружен участок, "
            "образуемый по схеме."
        )

    if auction_detected:

        verification_required.append(
            "Обнаружен объект "
            "аукционного слоя."
        )

    return {

        "status": (
            "partial"
            if successful_layers > 0
            else "source_error"
        ),

        "lat": lat,
        "lon": lon,

        "nspd": {

            "status": (
                "checked"
                if successful_layers > 0
                else "source_error"
            ),

            "successful_layers":
            successful_layers,

            "total_layers": 5,

            "layers": {

                "land_parcels_egrn":
                land_parcels,

                "cadastral_quarters":
                cadastral_quarters,

                "scheme_parcels":
                scheme_parcels,

                "third_party_rights_free":
                rights_free,

                "auction_parcels":
                auction
            },

            "source_type":
            "NSPD_WMS_preliminary"
        },

        "cadastral": {

            "status":
            land_parcels["status"],

            "point_has_mapped_parcel":
            mapped_parcel,

            "objects":
            land_parcels["objects"],

            "cadastral_quarters":
            cadastral_quarters["objects"]
        },

        "formation_context": {

            "scheme_parcel_detected":
            scheme_detected,

            "third_party_rights_free_detected":
            rights_free_detected,

            "auction_parcel_detected":
            auction_detected,

            "scheme_parcels":
            scheme_parcels["objects"],

            "third_party_rights_free":
            rights_free["objects"],

            "auction_parcels":
            auction["objects"]
        },

        "fis_119fz": {
            "status":
            "manual_verification_required",

            "checked": False,

            "available_for_formation":
            None,

            "objects": [],

            "source": None
        },

        "restrictions": {
            "status":
            "not_connected",

            "all_critical_layers_checked":
            False
        },

        "zouit": {
            "status": "not_connected",
            "items": []
        },

        "public_servitudes": {
            "status": "not_connected",
            "items": []
        },

        "forest": {
            "status": "not_connected",
            "items": []
        },

        "water": {
            "status": "not_connected",
            "items": []
        },

        "protected_areas": {
            "status": "not_connected",
            "items": []
        },

        "cultural_heritage": {
            "status": "not_connected",
            "items": []
        },

        "territorial_zoning": {
            "status": "not_connected",
            "zone": None,
            "permitted_uses": []
        },

        "analysis": {

            "positive_signals":
            positive_signals,

            "verification_required":
            verification_required,

            "stop_factors": []
        },

        "legal_conclusion": {

            "land_availability_confirmed":
            False,

            "mapped_cadastral_parcel_detected":
            mapped_parcel,

            "scheme_parcel_detected":
            scheme_detected,

            "third_party_rights_free_detected":
            rights_free_detected,

            "auction_parcel_detected":
            auction_detected,

            "nspd_checked":
            successful_layers > 0,

            "fis_119fz_checked":
            False,

            "restrictions_checked":
            False,

            "status":
            "insufficient_official_data"
        },

        "warnings": [

            "NSPD WMS используется "
            "для предварительного "
            "картографического анализа.",

            "Отсутствие участка в слое "
            "ЕГРН не подтверждает "
            "свободную землю.",

            "Слой свободных от прав "
            "третьих лиц сам по себе "
            "не подтверждает возможность "
            "получения участка по 119-ФЗ.",

            "Необходима отдельная проверка "
            "ФИС, ЗОУИТ и иных ограничений."
        ]
    }


# ============================================================
# API 6 — RESTRICTIONS
# ============================================================

@app.get("/restrictions")
def restrictions(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: float = Query(
        100,
        ge=1,
        le=5000
    )
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

        "restriction_free_confirmed":
        False
    }


# ============================================================
# API 7 — CHECK CONTOUR
# ============================================================

@app.post("/check-contour")
def check_contour(
    data: ContourRequest
):

    coordinates = data.coordinates

    if (
        not coordinates
        or not coordinates[0]
    ):

        raise HTTPException(
            status_code=400,
            detail="Polygon coordinates required."
        )

    ring = coordinates[0]

    if len(ring) < 4:

        raise HTTPException(
            status_code=400,
            detail="Polygon requires at least 4 points."
        )

    lons = [
        float(p[0])
        for p in ring
    ]

    lats = [
        float(p[1])
        for p in ring
    ]

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
            "status":
            "manual_verification_required"
        },

        "fis_119fz": {
            "status":
            "manual_verification_required",

            "available_for_formation":
            None
        },

        "formation_possible_confirmed":
        False
    }


# ============================================================
# API 8 — SEARCH AREA
# ============================================================

@app.get("/search-area")
def search_area(
    region: str = Query(...),
    center: Optional[str] = None,
    radius_km: float = Query(
        20,
        ge=1,
        le=100
    ),
    purpose: str = "general"
):

    search_name = (
        center
        if center
        else region
    )

    geo = geocode_place(
        search_name
    )

    if (
        geo["status"] != "ok"
        or not geo["results"]
    ):

        return {
            "status":
            "geocode_failed",

            "candidates": [],

            "geocode": geo
        }

    origin = geo["results"][0]

    lat = origin["lat"]
    lon = origin["lon"]

    delta_lat = (
        min(radius_km, 25)
        / 111
    )

    cos_lat = max(
        cos(radians(lat)),
        0.2
    )

    delta_lon = (
        min(radius_km, 25)
        /
        (111 * cos_lat)
    )

    points = [

        {
            "name": "Center",
            "lat": lat,
            "lon": lon
        },

        {
            "name": "North sector",
            "lat":
            lat + delta_lat * 0.55,
            "lon": lon
        },

        {
            "name": "South sector",
            "lat":
            lat - delta_lat * 0.55,
            "lon": lon
        }
    ]

    candidates = []

    for point in points:

        successful, infra = (
            get_infrastructure(
                point["lat"],
                point["lon"],
                min(
                    radius_km,
                    10
                )
            )
        )

        road = nearest_distance(
            infra.get("roads")
        )

        settlement = nearest_distance(
            infra.get("settlements")
        )

        industrial = nearest_distance(
            infra.get("industrial")
        )

        power = nearest_distance(
            infra.get("power")
        )

        score = 0

        if road is not None:

            if road <= 1:
                score += 30

            elif road <= 3:
                score += 24

            elif road <= 5:
                score += 18

            elif road <= 10:
                score += 10

        if power is not None:

            if power <= 2:
                score += 20

            elif power <= 5:
                score += 14

            elif power <= 10:
                score += 8

        if settlement is not None:

            if settlement <= 5:
                score += 20

            elif settlement <= 15:
                score += 12

        if industrial is not None:

            if industrial <= 5:
                score += 20

            elif industrial <= 15:
                score += 12

        score += min(
            successful * 2,
            10
        )

        candidates.append({

            **point,

            "geographic_score":
            min(score, 100),

            "nearest": {
                "road_km": road,
                "settlement_km":
                settlement,
                "industrial_km":
                industrial,
                "power_km": power
            },

            "legal_status": {
                "status":
                "not_verified",

                "land_availability_confirmed":
                False
            }
        })

    candidates.sort(
        key=lambda x:
        x["geographic_score"],
        reverse=True
    )

    return {

        "status":
        "preliminary",

        "region":
        region,

        "center":
        center,

        "resolved_center":
        origin,

        "purpose":
        purpose,

        "radius_km":
        radius_km,

        "candidates":
        candidates,

        "warning":
        (
            "Candidate ranking is geographic only. "
            "119-FZ availability is not confirmed."
        )
    }


# ============================================================
# API 9 — CANDIDATE SCORE
# ============================================================

@app.post("/candidate-score")
def candidate_score(
    data: CandidateScoreRequest
):

    if data.stop_factors:

        return {
            "status": "stop",
            "score": 0,
            "rating": "STOP",
            "stop_factors":
            data.stop_factors
        }

    components = {

        "legal_availability":
        (25, data.legal_availability),

        "roads":
        (15, data.roads),

        "power":
        (10, data.power),

        "development_drivers":
        (15, data.development_drivers),

        "purpose_fit":
        (15, data.purpose_fit),

        "physical_characteristics":
        (10, data.physical_characteristics),

        "liquidity":
        (5, data.liquidity),

        "development_cost":
        (5, data.development_cost)
    }

    total = 0
    evaluated_weight = 0
    breakdown = {}

    for name, (
        weight,
        value
    ) in components.items():

        if value is None:

            breakdown[name] = {
                "weight": weight,
                "input": None,
                "points": None
            }

            continue

        value = clamp(
            float(value),
            0,
            100
        )

        points = round(
            weight
            * value
            / 100,
            2
        )

        total += points
        evaluated_weight += weight

        breakdown[name] = {
            "weight": weight,
            "input": value,
            "points": points
        }

    total = round(
        total,
        2
    )

    if total >= 80:
        rating = "HIGH"

    elif total >= 60:
        rating = "MEDIUM_HIGH"

    elif total >= 40:
        rating = "MEDIUM"

    else:
        rating = "LOW"

    return {

        "status": "ok",

        "purpose":
        data.purpose,

        "score":
        total,

        "max_score":
        100,

        "evaluated_weight":
        evaluated_weight,

        "rating":
        rating,

        "breakdown":
        breakdown,

        "legal_availability_confirmed":
        (
            data.legal_availability
            is not None
            and
            data.legal_availability >= 80
        ),

        "warning":
        (
            "Investment score does not replace "
            "official land availability checks."
        )
    }
