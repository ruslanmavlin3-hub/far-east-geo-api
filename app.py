from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Far East Land Geo API",
    description="Geo API for searching and checking land areas in the Russian Far East",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "Far East Land Geo API",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "far-east-geo-api"
    }


@app.get("/check-point")
def check_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180)
):
    return {
        "lat": lat,
        "lon": lon,
        "status": "prototype",
        "message": "Point accepted. Geo data sources will be connected in the next stage."
    }


@app.get("/nearby-infrastructure")
def nearby_infrastructure(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10, gt=0, le=50)
):
    return {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "status": "prototype",
        "roads": [],
        "railways": [],
        "settlements": [],
        "industrial": [],
        "power": [],
        "message": "Infrastructure search module will be connected in the next stage."
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
        "status": "prototype",
        "candidates": [],
        "message": "Candidate-area search module will be connected in the next stage."
    }


@app.post("/check-contour")
def check_contour(data: dict):
    return {
        "status": "prototype",
        "received": data,
        "intersections": [],
        "restrictions": [],
        "warnings": [],
        "message": "Contour accepted. Spatial intersection checks will be connected in the next stage."
    }
