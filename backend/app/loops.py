"""Ограниченный поиск круговых поездок с ранжированием и разнообразием."""
import asyncio

from fastapi import HTTPException

from .catalog import ScenicSegment
from .geo import distance
from .models import LoopRequest, LoopResponse, Point
from .ranking import evaluate, select_routes, describe
from .planning import candidates, available_segments, table_points
from .settings import CONFIG, WARNING


async def build_loop(body: LoopRequest, routing, segments: list[ScenicSegment]) -> LoopResponse:
    settings = CONFIG["loop"]
    target = body.target_duration_minutes * 60
    warnings = [WARNING]
    attempted = inaccessible = 0
    evaluations = []
    try:
        async with asyncio.timeout(settings["request_budget_seconds"]):
            nearby = available_segments(body.start, segments)
            matrix = await routing.durations(table_points(body.start, nearby)) if nearby and hasattr(routing, 'durations') else None
            for selected, points in candidates(body.start, nearby, body.seed, body.target_duration_minutes, body.preferences, matrix):
                attempted += 1
                try:
                    route = await routing.route_via(points)
                except HTTPException as error:
                    if error.status_code == 422:
                        inaccessible += 1
                        continue
                    if not evaluations:
                        raise
                    warnings.append("Маршрутизатор не ответил на часть запросов. Показаны уже проверенные поездки.")
                    break
                if not settings["min_duration_ratio"] * target <= route.duration_seconds <= settings["max_duration_ratio"] * target:
                    continue
                coords = route.geometry.coordinates
                if any(distance(body.start, Point(lon=lon, lat=lat)) > CONFIG["max_snap_meters"] for lon, lat in (coords[0], coords[-1])):
                    continue
                item = evaluate(route, segments, body.preferences, target)
                if not {s.properties.id for s in selected} <= item.passed_segment_ids:
                    continue
                # Стабильный ключ для равных оценок; публичный ID вычисляется из геометрии.
                item.route.id = f"candidate-{attempted:02d}"
                evaluations.append(item)
    except TimeoutError as error:
        if not evaluations:
            raise HTTPException(504, "Не успели подобрать поездку за отведённое время. Попробуйте другой старт или повторите запрос.") from error
        warnings.append("Время поиска закончилось. Показаны уже проверенные поездки; другие варианты могли не попасть в подборку.")
    chosen = select_routes(evaluations)
    if chosen:
        if any(s.properties.verification_status == "draft" for item in chosen for s in item.segments):
            warnings.append("В поездки включены черновые участки (draft). Оценки красоты и видимость из автомобиля ещё не проверены.")
        if len(chosen) < CONFIG['ranking']['max_routes']:
            warnings.append(f"Найдено разных поездок: {len(chosen)}. Остальные кандидаты не подошли по времени, прохождению дорог, повторам или слишком похожи.")
        return LoopResponse(routes=[describe(item) for item in chosen], warnings=warnings)
    if not attempted and not nearby:
        warnings.append("Рядом со стартом пока нет участков из каталога.")
    elif not attempted:
        warnings.append("OSRM не нашёл связного автомобильного пути через доступные участки каталога.")
    elif inaccessible == attempted:
        warnings.append("Не удалось построить автомобильный путь через участки каталога. Попробуйте другой старт.")
    else:
        warnings.append("В небольшом каталоге не нашлось поездки в пределах 80–110% выбранного времени с подтверждённым прохождением участков и допустимым количеством повторов. Попробуйте другое время или старт.")
    return LoopResponse(routes=[], warnings=warnings)
