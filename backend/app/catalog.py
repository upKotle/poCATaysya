"""Каталог загружается локально; сетевые обращения при старте не нужны."""
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pyproj import Transformer
from shapely.geometry import LineString, Point as ShapePoint
from shapely.ops import transform

from .models import Geometry, Point
from .settings import CONFIG, ROOT

PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:32637", always_xy=True).transform


def metric_line(coordinates):
    return transform(PROJECT, LineString(coordinates))


class Scores(BaseModel):
    water: float = Field(ge=0, le=1, allow_inf_nan=False)
    architecture: float = Field(ge=0, le=1, allow_inf_nan=False)
    greenery: float = Field(ge=0, le=1, allow_inf_nan=False)


class SegmentProperties(Scores):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    routing_anchors: list[tuple[float, float]] = Field(min_length=2, max_length=10)
    direction: Literal["forward", "both"]
    description: str = Field(min_length=1)
    source_url: str | None = None
    verification_status: Literal["draft", "reviewed"]
    verified_at: date | None

    @model_validator(mode="after")
    def consistent_review(self):
        if (self.verification_status == "reviewed") != (self.verified_at is not None):
            raise ValueError("Only reviewed segments must have verified_at")
        return self


class ScenicSegment(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: Geometry
    properties: SegmentProperties

    @model_validator(mode="after")
    def valid_road(self):
        coords = self.geometry.coordinates
        for lon, lat in [*coords, *self.properties.routing_anchors]:
            Point(lat=lat, lon=lon)
            bounds = CONFIG["bounds"]
            if not (bounds["west"] <= lon <= bounds["east"] and bounds["south"] <= lat <= bounds["north"]):
                raise ValueError("Catalog coordinates must be in city coverage")
        line = metric_line(coords)
        if not line.is_simple or line.length < 50:
            raise ValueError("Segment must be a simple road line at least 50 m long")
        positions = []
        for anchor in self.properties.routing_anchors:
            point = ShapePoint(PROJECT(*anchor))
            if line.distance(point) > 5:
                raise ValueError("Anchor must lie on the road line")
            positions.append(line.project(point))
        if any(a >= b for a, b in zip(positions, positions[1:])):
            raise ValueError("Anchors must follow geometry order")
        if positions[-1] - positions[0] < line.length * 0.8:
            raise ValueError("Anchors must span at least 80% of the road segment")
        return self


def load_catalog(path=ROOT / "data/moscow/scenic_segments.geojson") -> list[ScenicSegment]:
    collection = json.loads(path.read_text())
    if collection.get("type") != "FeatureCollection":
        raise ValueError("Expected FeatureCollection")
    segments = [ScenicSegment.model_validate(feature) for feature in collection["features"]]
    ids = [segment.properties.id for segment in segments]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate scenic segment ids")
    return segments


def segment_coverage(trace, segment: ScenicSegment):
    road = metric_line(segment.geometry.coordinates)
    return trace.coverage(road, CONFIG["loop"]["segment_tolerance_meters"], segment.properties.direction == "both")


def passes_segment(route_coordinates, segment: ScenicSegment) -> bool:
    """Проверяем фактическую длину и направление, включая повторные обходы."""
    from .geometry import RoadTrace
    road = metric_line(segment.geometry.coordinates)
    coverage = segment_coverage(RoadTrace(metric_line(route_coordinates)), segment)
    return coverage.length / road.length >= CONFIG["loop"]["min_segment_coverage_ratio"]
