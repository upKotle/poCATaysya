import asyncio
import logging
import math
from collections import OrderedDict
import os
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from .models import Point, Route
from .settings import CONFIG

logger = logging.getLogger(__name__)


def create_osrm_client() -> httpx.AsyncClient:
    base_url = os.getenv("OSRM_BASE_URL", "http://localhost:5000").rstrip("/")
    local = urlsplit(base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    # Локальный OSRM доступен напрямую даже при глобальном HTTP(S)_PROXY.
    # Для внешнего сервера явная настройка не зависит от VPN браузера.
    proxy = None if local else os.getenv("OSRM_PROXY_URL", "").strip() or None
    return httpx.AsyncClient(
        base_url=base_url, proxy=proxy, trust_env=not local,
        timeout=httpx.Timeout(15),
        headers={"User-Agent": "ScenicDrive/0.1 (local personal route planner)"},
    )


class RoutingClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache = OrderedDict()

    async def _get(self, path: str, params: dict) -> httpx.Response:
        key = (path, tuple(sorted(params.items())))
        async with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < CONFIG['routing']['cache_ttl_seconds']:
                self._cache.move_to_end(key)
                return cached[1]
            await asyncio.sleep(max(0, 1 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            response = await self.client.get(path, params=params)
            return response

    def _remember(self, path, params, response):
        key = (path, tuple(sorted(params.items())))
        self._cache[key] = (time.monotonic(), response)
        self._cache.move_to_end(key)
        while len(self._cache) > CONFIG['routing']['cache_max_entries']:
            self._cache.popitem(last=False)

    async def route(self, start: Point, end: Point) -> Route:
        return await self.route_via([start, end])

    async def route_via(self, points: list[Point]) -> Route:
        if len(points) < 2:
            raise ValueError("At least two waypoints are required")
        coords = ";".join(f"{point.lon},{point.lat}" for point in points)
        try:
            path = f"/route/v1/driving/{coords}"
            params = {
                "overview": "full", "geometries": "geojson", "steps": "false",
                "alternatives": "false", "radiuses": ";".join(str(CONFIG["max_snap_meters"]) for _ in points)}
            response = await self._get(path, params)
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid OSRM response")
            if data.get("code") in {"NoRoute", "NoSegment"}:
                raise HTTPException(422, "Автомобильный путь не найден. Выберите точки ближе к доступной дороге.")
            response.raise_for_status()
            if data.get("code") != "Ok":
                raise ValueError("Unexpected OSRM code")
            waypoints = data["waypoints"]
            if len(waypoints) != len(points):
                raise ValueError("Invalid waypoints")
            if any(w["distance"] > CONFIG["max_snap_meters"] for w in waypoints):
                raise HTTPException(422, "Точка слишком далеко от автомобильной дороги.")
            raw = data["routes"][0]
            route = Route(geometry=raw["geometry"], distance_meters=raw["distance"], duration_seconds=raw["duration"])
            for lon, lat in route.geometry.coordinates:
                Point(lat=lat, lon=lon)
            self._remember(path, params, response)
            return route
        except httpx.TimeoutException as exc:
            logger.warning("OSRM timeout (%s)", type(exc).__name__)
            raise HTTPException(504, "Сервер маршрутов не ответил за 15 секунд. Проверьте подключение backend к интернету и настройку OSRM_PROXY_URL. VPN только в браузере не влияет на backend.") from exc
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ValidationError) as exc:
            logger.warning("OSRM request failed (%s)", type(exc).__name__)
            raise HTTPException(502, "Сервер маршрутов недоступен или вернул некорректный ответ. Проверьте OSRM_BASE_URL, запуск локального OSRM или OSRM_PROXY_URL для внешнего сервера.") from exc


    async def durations(self, points: list[Point]) -> list[list[float | None]]:
        # Один повтор только при временном сетевом сбое. Общий бюджет поиска
        # включает обе попытки; максимум 2 table + 18 Route = 20 запросов.
        for attempt in range(CONFIG['routing']['table_attempts']):
            try:
                return await self._durations_once(points)
            except HTTPException as error:
                if error.status_code != 504 or attempt + 1 == CONFIG['routing']['table_attempts']:
                    raise
                await asyncio.sleep(0.25)

    async def _durations_once(self, points: list[Point]) -> list[list[float | None]]:
        """Автомобильные времена между anchors; не заменяют проверку полного маршрута."""
        coords = ";".join(f"{round(p.lon, 6)},{round(p.lat, 6)}" for p in points)
        try:
            path = f"/table/v1/driving/{coords}"
            params = {
                "annotations": "duration",
                "radiuses": ";".join(str(CONFIG['max_snap_meters']) for _ in points),
            }
            response = await self._get(path, params)
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid table response")
            if data.get('code') == 'NoSegment':
                raise HTTPException(422, 'Не удалось привязать старт или участок каталога к автомобильной дороге.')
            response.raise_for_status()
            if data.get('code') != 'Ok':
                raise ValueError('Invalid table code')
            rows = data['durations']
            if len(rows) != len(points) or any(len(row) != len(points) for row in rows):
                raise ValueError('Invalid matrix shape')
            if any(value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0) for row in rows for value in row):
                raise ValueError('Invalid duration')
            self._remember(path, params, response)
            return rows
        except httpx.TimeoutException as exc:
            raise HTTPException(504, 'Не удалось получить автомобильные времена OSRM. Проверьте подключение backend и OSRM_PROXY_URL.') from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning('OSRM table failed (%s)', type(exc).__name__)
            raise HTTPException(502, 'Не удалось получить автомобильные времена OSRM. Проверьте сервер маршрутов и настройки подключения.') from exc
