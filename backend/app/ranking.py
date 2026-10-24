"""Ранжирование и удаление похожих маршрутов; не зависит от OSRM/HTTP."""
import hashlib
from dataclasses import dataclass, field

from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from .catalog import ScenicSegment, metric_line, segment_coverage
from .geometry import RoadTrace, repeated_distance, route_similarity
from .models import Preferences, Route
from .settings import CONFIG


@dataclass
class Evaluation:
    route: Route
    trace: RoadTrace
    score: float
    scenic_meters: float
    weighted_scenic_meters: float
    repeated_meters: float
    repeat_ratio: float
    duration_deviation: float
    segments: list[ScenicSegment]
    accents: list[str]
    passed_segment_ids: set[str]
    category_meters: dict[str, float] = field(default_factory=dict)


def evaluate(route: Route, segments: list[ScenicSegment], preferences: Preferences, target_seconds: float) -> Evaluation:
    settings = CONFIG['ranking']
    weights = settings['weights']
    preferences = preferences.normalized()
    trace = RoadTrace(metric_line(route.geometry.coordinates))
    matched = []
    # Произвольный порядок записей каталога не должен влиять на результат.
    for segment in sorted(segments, key=lambda s: s.properties.id):
        coverage = segment_coverage(trace, segment)
        length = metric_line(segment.geometry.coordinates).length
        if coverage.length / length >= CONFIG['loop']['min_segment_coverage_ratio']:
            attraction = sum(preferences[key] * getattr(segment.properties, key) for key in preferences)
            matched.append((segment, coverage, attraction))
    # На совпадающей дороге берём сильнейшую оценку, а не складываем копии.
    matched.sort(key=lambda item: (-item[2], item[0].properties.id))
    credited = GeometryCollection()
    scenic = beauty = 0.0
    included = []
    contributions = {key: 0.0 for key in preferences}
    categories = {key: 0.0 for key in preferences}
    for segment, coverage, attraction in matched:
        unique = coverage.difference(credited.buffer(settings['repeat_tolerance_meters'], cap_style=2)) if not credited.is_empty else coverage
        length = unique.length
        if length < settings['min_credited_length_meters']:
            continue
        scenic += length
        beauty += length * attraction
        included.append(segment)
        for key in preferences:
            contributions[key] += length * preferences[key] * getattr(segment.properties, key)
            if getattr(segment.properties, key) >= settings['category_threshold']:
                categories[key] += length
        credited = unary_union([credited, coverage])
    repeated = repeated_distance(trace.line, settings['repeat_tolerance_meters'], settings['repeat_sample_meters'])
    total_length = max(trace.line.length, 1.0)
    repeat_ratio = max(0, repeated - settings['repeat_allowance_meters']) / total_length
    deviation = abs(route.duration_seconds - target_seconds) / target_seconds
    score = (weights['scenic_length'] * min(1, beauty / settings['scenic_length_scale_meters'])
             + weights['scenic_fraction'] * min(1, beauty / total_length)
             + weights['diversity'] * min(len(included), 3) / 3
             + weights['preference_match'] * (beauty / scenic if scenic else 0)
             - weights['repeats'] * repeat_ratio
             - weights['duration_deviation'] * deviation)
    accents = [key for key in sorted(contributions, key=lambda key: (-contributions[key], key)) if contributions[key] > 0][:2]
    return Evaluation(route, trace, score, scenic, beauty, repeated, repeat_ratio, deviation, included, accents, {s.properties.id for s, _, _ in matched}, categories)


def select_routes(evaluations: list[Evaluation]) -> list[Evaluation]:
    settings = CONFIG['ranking']
    chosen = []
    eligible = [item for item in evaluations if item.segments and item.repeat_ratio <= settings['max_repeat_ratio']]
    for item in sorted(eligible, key=lambda item: (-round(item.score, 9), item.duration_deviation, item.route.id)):
        if all(route_similarity(item.trace, other.trace, settings['similarity_tolerance_meters']) < settings['max_similarity_ratio'] for other in chosen):
            chosen.append(item)
            if len(chosen) >= settings['max_routes']:
                break
    return chosen


def describe(item: Evaluation, *, loop: bool = True) -> Route:
    route = item.route.model_copy(deep=True)
    digest = hashlib.sha256(route.geometry.model_dump_json().encode()).hexdigest()[:12]
    route.id = ('loop-' if loop else 'scenic-') + digest
    route.scenic_segment_ids = [s.properties.id for s in item.segments]
    route.scenic_category_meters = {key: round(value) for key,value in item.category_meters.items()}
    labels = {'water': 'вода', 'architecture': 'архитектура', 'greenery': 'зелень'}
    route.explanation = 'Через: ' + '; '.join(s.properties.name for s in item.segments) + ('. Возвращение к старту.' if loop else '.')
    if item.accents:
        route.explanation += ' По оценкам каталога акцент: ' + ', '.join(labels[key] for key in item.accents) + '.'
    if item.repeated_meters > CONFIG['ranking']['repeat_allowance_meters']:
        percent = max(1, round(100 * item.repeated_meters / max(item.trace.line.length, 1)))
        route.explanation += f' Около {percent}% пути проходит по уже пройденной дороге.'
    return route
