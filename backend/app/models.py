from typing import Literal
from pydantic import BaseModel, Field


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Geometry(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = Field(min_length=2)


class Route(BaseModel):
    id: str = "baseline"
    geometry: Geometry
    distance_meters: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    scenic_segment_ids: list[str] = Field(default_factory=list)
    scenic_category_meters: dict[str, float] = Field(default_factory=dict)
    explanation: str = "Обычный автомобильный маршрут OSRM."


class RouteResponse(BaseModel):
    routes: list[Route]
    warnings: list[str]
    baseline_duration_seconds: float



class Preferences(BaseModel):
    water: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    architecture: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    greenery: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)

    def normalized(self) -> dict[str, float]:
        values = self.model_dump()
        total = sum(values.values())
        return {key: value / total for key, value in values.items()} if total else {key: 1 / 3 for key in values}


class RouteRequest(BaseModel):
    start: Point
    end: Point
    max_extra_minutes: Literal[5, 10, 15, 20] = 10
    preferences: Preferences = Field(default_factory=Preferences)


class LoopRequest(BaseModel):
    start: Point
    target_duration_minutes: Literal[30, 45, 60, 90] = 60
    seed: int | None = None
    preferences: Preferences = Field(default_factory=Preferences)


class LoopResponse(BaseModel):
    routes: list[Route]
    warnings: list[str]
