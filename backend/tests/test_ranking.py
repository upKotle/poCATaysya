"""Геометрические фикстуры заданы в метрах, не получены из внешней сети."""
import math

import pytest
from pyproj import Transformer

from app.catalog import ScenicSegment, metric_line, passes_segment
from app.geometry import RoadTrace, repeated_distance, route_similarity
from app.models import Preferences, Route
from app.ranking import describe, evaluate, select_routes
from app.settings import CONFIG

TO_GEO = Transformer.from_crs(32637, 4326, always_xy=True).transform
FROM_GEO = Transformer.from_crs(4326, 32637, always_xy=True).transform
ORIGIN = FROM_GEO(37.61,55.75)


def geo(points):
    return [TO_GEO(ORIGIN[0]+x,ORIGIN[1]+y) for x,y in points]


def road(points, id='road', water=1, architecture=1, greenery=1, direction='both'):
    coords = geo(points)
    return ScenicSegment.model_validate({'type':'Feature','geometry':{'type':'LineString','coordinates':coords},'properties':{
        'id':id,'name':id,'routing_anchors':[coords[0],coords[-1]],'direction':direction,
        'water':water,'architecture':architecture,'greenery':greenery,
        'description':'Synthetic test road','source_url':None,'verification_status':'draft','verified_at':None}})


def route(points, id='route', duration=1800):
    return Route(id=id,geometry={'type':'LineString','coordinates':geo(points)},
                 distance_meters=sum(math.dist(a,b) for a,b in zip(points,points[1:])),duration_seconds=duration)


def assessed(points,segments,preferences=None,id='route',duration=1800):
    return evaluate(route(points,id,duration),segments,preferences or Preferences(),1800)


def test_repeated_road_penalized_and_no_repeated_beauty():
    segment = road([(0,0),(1000,0)])
    once = assessed([(0,0),(1000,0)],[segment])
    twice = assessed([(0,0),(1000,0),(0,0)],[segment])
    assert twice.scenic_meters == pytest.approx(once.scenic_meters,abs=0.1)
    assert twice.weighted_scenic_meters == pytest.approx(once.weighted_scenic_meters,abs=0.1)
    assert twice.repeated_meters > 900
    assert twice.score < once.score
    assert twice.route.geometry.coordinates == geo([(0,0),(1000,0),(0,0)])


def test_duplicate_catalog_geometry_not_double_counted():
    points = [(0,0),(1000,0)]
    a,b = road(points,'a'),road(points,'b')
    once, twice = assessed(points,[a]),assessed(points,[a,b])
    assert twice.weighted_scenic_meters == pytest.approx(once.weighted_scenic_meters)
    assert twice.score == pytest.approx(once.score)
    assert len(twice.segments) == 1
    assert twice.passed_segment_ids == {'a','b'}


def test_overlapping_catalog_keeps_strongest_score_and_is_order_independent():
    points = [(0,0),(1000,0)]
    low,high = road(points,'low',water=0.1),road(points,'high',water=1)
    preference = Preferences(water=1,architecture=0,greenery=0)
    first = assessed(points,[low,high],preference)
    second = assessed(points,[high,low],preference)
    assert first.weighted_scenic_meters == pytest.approx(1000,abs=0.1)
    assert first.score == second.score
    assert [s.properties.id for s in first.segments] == ['high']


def test_actual_partial_length_not_full_road_length():
    segment = road([(0,0),(1000,0)])
    item = assessed([(0,0),(850,0)],[segment])
    assert 849 < item.scenic_meters < 851
    assert item.scenic_meters < 1000


def test_one_anchor_or_crossing_does_not_receive_beauty():
    segment = road([(0,0),(1000,0)])
    assert assessed([(500,-500),(500,500)],[segment]).scenic_meters == 0
    short = road([(0,0),(60,0)])
    assert assessed([(30,-100),(30,100)],[short]).scenic_meters == 0


def test_direction_and_later_valid_passage():
    segment = road([(0,0),(1000,0)],direction='forward')
    assert not passes_segment(geo([(1000,0),(0,0)]),segment)
    assert passes_segment(geo([(1000,0),(0,0),(1000,0)]),segment)
    assert passes_segment(geo([(0,0),(1000,0),(0,0)]),segment)


def test_preferences_change_order():
    water = road([(0,0),(1000,0)],'water',water=1,architecture=0,greenery=0)
    buildings = road([(0,1000),(1000,1000)],'buildings',water=0,architecture=1,greenery=0)
    def choose(preferences):
        first = assessed([(0,0),(1000,0)],[water,buildings],preferences,id='water')
        second = assessed([(0,1000),(1000,1000)],[water,buildings],preferences,id='buildings')
        return select_routes([first,second])[0].route.id
    assert choose(Preferences(water=1,architecture=0,greenery=0)) == 'water'
    assert choose(Preferences(water=0,architecture=1,greenery=0)) == 'buildings'
    assert Preferences(water=0,architecture=0,greenery=0).normalized() == Preferences().normalized()


def test_similar_routes_reverse_and_different_sampling_are_duplicates():
    points = [(0,0),(1000,0),(1000,1000),(0,1000),(0,0)]
    segment = road([(0,0),(1000,0)])
    first = assessed(points,[segment],id='first')
    reverse = assessed(list(reversed(points)),[segment],id='reverse')
    dense = assessed([(0,0),(500,0),(1000,0),(1000,500),(1000,1000),(0,1000),(0,0)],[segment],id='dense')
    assert route_similarity(first.trace,reverse.trace,25) == pytest.approx(1)
    assert len(select_routes([first,reverse,dense])) == 1


def test_small_offset_and_tiny_detour_do_not_create_another_variant():
    first = RoadTrace(metric_line(geo([(0,0),(1000,0)])))
    offset = RoadTrace(metric_line(geo([(0,10),(1000,10)])))
    detour = RoadTrace(metric_line(geo([(0,0),(500,0),(500,10),(510,10),(510,0),(1000,0)])))
    assert route_similarity(first,offset,25) >= 0.99
    assert route_similarity(first,detour,25) >= 0.95


def test_distinct_routes_not_removed_because_names_are_equal():
    evaluations = []
    for index in range(4):
        y = index * 1000
        segment = road([(0,y),(1000,y)],f'segment-{index}')
        segment.properties.name = 'Same name'
        evaluations.append(assessed([(0,y),(1000,y)],[segment],id=f'route-{index}'))
    chosen = select_routes(evaluations)
    assert len(chosen) == 3
    assert {item.route.id for item in chosen} == {'route-0','route-1','route-2'}


def test_heavily_repeated_trip_rejected_but_common_exit_allowed():
    segment = road([(0,0),(1000,0)])
    bad = assessed([(0,0),(1000,0),(0,0),(1000,0),(0,0)],[segment])
    assert bad.repeat_ratio > CONFIG['ranking']['max_repeat_ratio']
    assert select_routes([bad]) == []
    good_points = [(0,0),(100,0),(100,1000),(1000,1000),(1000,0),(100,0),(0,0)]
    good = assessed(good_points,[road([(100,1000),(1000,1000)])])
    assert good.repeat_ratio == 0
    assert len(select_routes([good])) == 1


def test_repeated_geometry_does_not_make_same_route_distinct():
    a = RoadTrace(metric_line(geo([(0,0),(1000,0)])))
    b = RoadTrace(metric_line(geo([(0,0),(1000,0),(0,0),(1000,0)])))
    assert route_similarity(a,b,25) == pytest.approx(1)


def test_duration_and_scenic_fraction_affect_ranking():
    segment = road([(0,0),(1000,0)])
    near = assessed([(0,0),(1000,0)],[segment],duration=1800)
    far = assessed([(0,0),(1000,0)],[segment],duration=1440)
    assert near.score > far.score
    detour = assessed([(0,0),(1000,0),(1000,1000),(0,1000)],[segment])
    assert near.score > detour.score


def test_explanation_and_id_are_public_facts_not_internal_score():
    item = assessed([(0,0),(1000,0)],[road([(0,0),(1000,0)])])
    result = describe(item)
    assert result.id.startswith('loop-')
    assert result.id == describe(item).id
    assert 'вода' in result.explanation or 'архитектура' in result.explanation
    assert 'score' not in result.model_dump()
    assert item.route.id == 'route'


def test_non_repeating_curve_is_not_penalized():
    line = metric_line(geo([(i*20,30*math.sin(i/10)) for i in range(50)]))
    assert repeated_distance(line,12,25) < 1


def test_preference_affinity_not_only_longest_catalog_segment():
    # Короткий архитектурный участок должен конкурировать с длинной набережной,
    # когда выбрана только архитектура; исходные оценки не меняются под запрос.
    buildings=road([(0,0),(1000,0)],'buildings',water=0,architecture=.9,greenery=0)
    bank=road([(0,1000),(2000,1000)],'bank',water=.9,architecture=.4,greenery=0)
    preference=Preferences(water=0,architecture=1,greenery=0)
    a=assessed([(0,0),(1000,0)],[buildings,bank],preference)
    b=assessed([(0,1000),(2000,1000)],[buildings,bank],preference)
    assert a.score>b.score
    assert describe(a).scenic_category_meters['architecture']>900
    assert describe(a).scenic_category_meters['water']==0
