"""Подбираем промежуточные участки; дорожную маршрутизацию выполняет OSRM."""
import heapq
import itertools
import math
import random
from dataclasses import dataclass

from shapely.geometry import Point as ShapePoint

from .catalog import PROJECT, metric_line
from .models import Point, Preferences
from .settings import CONFIG


def available_segments(start, segments):
    settings = CONFIG['loop']
    origin = ShapePoint(PROJECT(start.lon, start.lat))
    nearby = sorted((s for s in segments if metric_line(s.geometry.coordinates).distance(origin) <= settings['nearby_radius_meters']), key=lambda s:s.properties.id)
    # Граница таблицы — число координат, а не только число записей каталога.
    selected, size = [], 1
    for segment in nearby:
        anchors = len(segment.properties.routing_anchors)
        if len(selected) < settings['max_catalog_segments'] and size + anchors <= settings['max_table_coordinates']:
            selected.append(segment)
            size += anchors
    return selected


def table_points(start, segments):
    return [start, *[Point(lon=lon,lat=lat) for s in segments for lon,lat in s.properties.routing_anchors]]


@dataclass
class Plan:
    selected: tuple
    indices: tuple[int, ...]
    seconds: float
    affinity: float
    priority: float
    in_window: bool


def candidates(start, segments, seed, target_duration_minutes=30, preferences=None, matrix=None):
    settings = CONFIG['loop']
    segments = available_segments(start, segments)
    points = table_points(start, segments)
    weights = (preferences or Preferences()).normalized()
    target = target_duration_minutes * 60
    lengths = {s.properties.id:metric_line(s.geometry.coordinates).length for s in segments}
    indices, offset = {}, 1
    for segment in segments:
        indices[segment.properties.id] = tuple(range(offset,offset+len(segment.properties.routing_anchors)))
        offset += len(segment.properties.routing_anchors)
    coordinates = [PROJECT(p.lon,p.lat) for p in points]
    rng = random.Random(seed if seed is not None else 0)
    shuffled = list(segments)
    rng.shuffle(shuffled)

    def plans():
        for size in range(1, min(settings['max_segments_per_candidate'],len(segments)) + 1):
            for selected in itertools.permutations(shuffled,size):
                # Обратный порядок anchors используем только для двусторонних дорог.
                for reverse in (False, True) if any(s.properties.direction == 'both' for s in selected) else (False,):
                    path = (0, *[i for s in selected for i in (tuple(reversed(indices[s.properties.id])) if reverse and s.properties.direction == 'both' else indices[s.properties.id])], 0)
                    if matrix is not None:
                        legs = [matrix[a][b] for a,b in zip(path,path[1:])]
                        if any(value is None for value in legs):
                            continue
                        seconds = sum(legs)
                    else:
                        meters = sum(math.dist(coordinates[a],coordinates[b]) for a,b in zip(path,path[1:]))
                        seconds = meters * settings['road_distance_factor'] / (settings['estimated_speed_kmh'] / 3.6)
                    scenic = sum(lengths[s.properties.id] for s in selected)
                    affinity = sum(lengths[s.properties.id] * sum(weights[key]*getattr(s.properties,key) for key in weights) for s in selected) / scenic
                    bearings = [math.atan2(coordinates[indices[s.properties.id][0]][1]-coordinates[0][1],coordinates[indices[s.properties.id][0]][0]-coordinates[0][0]) for s in selected]
                    spread = 1-math.hypot(sum(math.cos(a) for a in bearings),sum(math.sin(a) for a in bearings))/size
                    deviation = abs(seconds-target)/target
                    priority = 4*affinity + 0.2*spread + 0.1*min(scenic/2000,1) - deviation
                    inside = settings['min_duration_ratio']*target <= seconds <= settings['max_duration_ratio']*target
                    yield Plan(selected,path,seconds,affinity,priority,inside)
    # Выбираем по времени и предпочтениям ДО полных запросов маршрутов.
    pool = heapq.nsmallest(300,plans(),key=lambda p:(not p.in_window,-p.priority))
    used = []
    for _ in range(settings['max_candidates']):
        if not pool:
            return
        def key(plan):
            ids = {s.properties.id for s in plan.selected}
            overlap = max((len(ids & other)/len(ids | other) for other in used),default=0)
            return (not plan.in_window, -(plan.priority - 0.8*overlap))
        plan = min(pool,key=key)
        pool.remove(plan)
        used.append({s.properties.id for s in plan.selected})
        yield list(plan.selected), [points[i] for i in plan.indices]
