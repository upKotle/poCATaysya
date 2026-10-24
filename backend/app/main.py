from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .settings import CONFIG, ROOT
from .models import RouteRequest, RouteResponse, LoopRequest, LoopResponse
from .routing import RoutingClient, create_osrm_client
from .geo import distance, validate_coverage
from .catalog import load_catalog
from .loops import build_loop
from .point_to_point import build_point_to_point
from .frontend import mount_frontend


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_osrm_client() as client:
        app.state.routing = RoutingClient(client)
        app.state.segments = load_catalog()
        yield


app = FastAPI(title="Scenic Drive", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}  # Жив ли backend; не проверяет внешнюю маршрутизацию.


@app.get("/api/config")
def config():
    return CONFIG


@app.post("/api/routes/point-to-point", response_model=RouteResponse)
async def point_to_point(body: RouteRequest):
    for point in (body.start, body.end):
        validate_coverage(point)
    if distance(body.start, body.end) < CONFIG["min_distance_meters"]:
        raise HTTPException(422, "Точки A и B должны находиться минимум в 50 метрах друг от друга.")
    return await build_point_to_point(body, app.state.routing, app.state.segments)


@app.get("/api/scenic-segments")
def scenic_segments():
    return {"type": "FeatureCollection", "features": [s.model_dump(mode="json") for s in app.state.segments]}


@app.post("/api/routes/loop", response_model=LoopResponse)
async def loop(body: LoopRequest):
    validate_coverage(body.start)
    return await build_loop(body, app.state.routing, app.state.segments)


mount_frontend(app, ROOT / "frontend" / "dist")
