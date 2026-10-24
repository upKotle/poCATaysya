import math
from fastapi import HTTPException
from .models import Point
from .settings import CONFIG


def distance(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b.lon-a.lon)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def validate_coverage(point: Point):
    bounds = CONFIG["bounds"]
    if not (bounds["south"] <= point.lat <= bounds["north"] and bounds["west"] <= point.lon <= bounds["east"]):
        raise HTTPException(422, "Выберите точки внутри выделенной области центра Москвы.")
