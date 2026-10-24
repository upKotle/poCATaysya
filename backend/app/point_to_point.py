"""Живописные A → B: обычный путь всегда первый, время — жёсткое ограничение."""
import asyncio
import itertools

from fastapi import HTTPException

from .catalog import metric_line
from .geo import distance
from .geometry import route_similarity
from .models import Point, RouteResponse
from .ranking import evaluate, describe
from .settings import CONFIG, WARNING


def corridor_segments(baseline, segments):
    corridor = metric_line(baseline.geometry.coordinates).buffer(CONFIG['point_to_point']['corridor_meters'])
    # Все anchors должны помещаться в одну таблицу вместе с A и B.
    selected, size = [], 2
    for segment in sorted(segments, key=lambda s: s.properties.id):
        count = len(segment.properties.routing_anchors)
        if corridor.intersects(metric_line(segment.geometry.coordinates)) and size + count <= CONFIG['loop']['max_table_coordinates']:
            selected.append(segment)
            size += count
    return selected


def point_candidates(body, segments, matrix, limit):
    points = [body.start, body.end]
    options = []
    for segment in segments:
        indices = tuple(range(len(points), len(points) + len(segment.properties.routing_anchors)))
        points.extend(Point(lon=lon, lat=lat) for lon, lat in segment.properties.routing_anchors)
        directions = [indices, indices[::-1]] if segment.properties.direction == 'both' else [indices]
        options.append((segment, directions))
    weights = body.preferences.normalized()
    plans = []
    for size in (1, 2):
        for selected in itertools.permutations(options, size):
            for directions in itertools.product(*(item[1] for item in selected)):
                path = (0, *[i for indices in directions for i in indices], 1)
                legs = [matrix[a][b] for a, b in zip(path, path[1:])]
                if any(value is None for value in legs) or sum(legs) > limit:
                    continue
                chosen = [item[0] for item in selected]
                beauty = sum(metric_line(s.geometry.coordinates).length * sum(weights[k] * getattr(s.properties, k) for k in weights) for s in chosen)
                affinity = sum(sum(weights[k] * getattr(s.properties, k) for k in weights) for s in chosen) / size
                priority = 3 * affinity + min(beauty / 2000, 1) - sum(legs) / max(limit, 1)
                plans.append((priority, chosen, path))
    used = []
    for _ in range(CONFIG['point_to_point']['max_candidates']):
        if not plans:
            break
        def priority(plan):
            ids = {s.properties.id for s in plan[1]}
            overlap = max((len(ids & other) / len(ids | other) for other in used), default=0)
            return plan[0] - 0.8 * overlap
        plan = max(plans, key=priority)
        plans.remove(plan)
        used.append({s.properties.id for s in plan[1]})
        yield plan[1], [points[i] for i in plan[2]]


async def build_point_to_point(body, routing, segments):
    settings = CONFIG['point_to_point']
    warnings = [WARNING]
    baseline = None
    evaluations = []
    try:
        async with asyncio.timeout(settings['request_budget_seconds']):
            baseline = await routing.route(body.start, body.end)
            base = evaluate(baseline, segments, body.preferences, max(baseline.duration_seconds, 1))
            baseline = describe(base, loop=False)
            baseline.id = 'baseline'
            baseline.explanation = 'Обычный автомобильный маршрут OSRM.'
            nearby = corridor_segments(baseline, segments)
            if nearby:
                points = [body.start, body.end, *[Point(lon=lon, lat=lat) for s in nearby for lon, lat in s.properties.routing_anchors]]
                matrix = await routing.durations(points)
                limit = baseline.duration_seconds + body.max_extra_minutes * 60
                for selected, points in point_candidates(body, nearby, matrix, limit):
                    try:
                        route = await routing.route_via(points)
                    except HTTPException as error:
                        if error.status_code == 422:
                            continue
                        raise
                    if route.duration_seconds > limit:
                        continue
                    if any(distance(point, Point(lon=coord[0], lat=coord[1])) > CONFIG['max_snap_meters'] for point, coord in ((body.start, route.geometry.coordinates[0]), (body.end, route.geometry.coordinates[-1]))):
                        continue
                    item = evaluate(route, segments, body.preferences, max(route.duration_seconds, 1))
                    if not {s.properties.id for s in selected} <= item.passed_segment_ids:
                        continue
                    if item.weighted_scenic_meters <= base.weighted_scenic_meters + settings['min_beauty_gain_meters']:
                        continue
                    if item.repeat_ratio > CONFIG['ranking']['max_repeat_ratio']:
                        continue
                    if route_similarity(item.trace, base.trace, CONFIG['ranking']['similarity_tolerance_meters']) >= CONFIG['ranking']['max_similarity_ratio']:
                        continue
                    evaluations.append(item)
    except (HTTPException, TimeoutError) as error:
        if baseline is None:
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(504, 'Не удалось построить обычный маршрут за отведённое время.') from error
        warnings.append('Поиск альтернатив завершён не полностью: маршрутизатор недоступен или истекло время. Обычный маршрут сохранён.')
    chosen = []
    for item in sorted(evaluations, key=lambda e: (-e.score, e.route.duration_seconds)):
        if all(route_similarity(item.trace, other.trace, CONFIG['ranking']['similarity_tolerance_meters']) < CONFIG['ranking']['max_similarity_ratio'] for other in chosen):
            chosen.append(item)
            if len(chosen) == settings['max_alternatives']:
                break
    routes = [baseline, *[describe(item, loop=False) for item in chosen]]
    if not chosen:
        warnings.append('Красивых улучшений в пределах дополнительного времени не найдено. Показан обычный маршрут.')
    if any(s.properties.verification_status == 'draft' for item in [base, *chosen] for s in item.segments):
        warnings.append('Оценки участков — черновые (draft); видимость из автомобиля ещё не проверена.')
    return RouteResponse(routes=routes, warnings=warnings, baseline_duration_seconds=baseline.duration_seconds)
