import pytest

from app.models import Point, Preferences
from app.planning import available_segments, candidates, table_points
from app.catalog import load_catalog
from app.settings import CONFIG
from test_ranking import road

START=Point(lat=55.75,lon=37.61)


def examples():
    return [road([(0,0),(1000,0)],'water',water=1,architecture=0,greenery=0),
            road([(0,1000),(1000,1000)],'architecture',water=0,architecture=1,greenery=0),
            road([(0,2000),(1000,2000)],'green',water=0,architecture=0,greenery=1)]


def constant_matrix(segments):
    points=table_points(START,available_segments(START,segments))
    # Не геометрическая заглушка маршрута: фикстура автомобильных времён table.
    return [[0 if i==j else 600 for j in range(len(points))] for i in range(len(points))]


def test_target_duration_changes_itinerary_before_route_calls():
    segments=examples();matrix=constant_matrix(segments)
    short=next(candidates(START,segments,0,30,Preferences(),matrix))
    hour=next(candidates(START,segments,0,60,Preferences(),matrix))
    assert len(short[0])==1  # 3 автомобильных перехода × 600 с = 30 мин.
    assert len(hour[0])==2   # 5 переходов × 600 с = 50 мин, внутри 48–66.
    assert short[1]!=hour[1]


def test_preferences_change_itinerary_before_route_calls():
    segments=examples();matrix=constant_matrix(segments)
    water=next(candidates(START,segments,0,30,Preferences(water=1,architecture=0,greenery=0),matrix))
    architecture=next(candidates(START,segments,0,30,Preferences(water=0,architecture=1,greenery=0),matrix))
    assert water[0][0].properties.id=='water'
    assert architecture[0][0].properties.id=='architecture'


def test_unreachable_table_transitions_not_used():
    segments=examples();points=table_points(START,available_segments(START,segments))
    matrix=[[0 if i==j else None for j in range(len(points))] for i in range(len(points))]
    assert list(candidates(START,segments,0,60,Preferences(),matrix))==[]


def test_table_and_route_query_limits_and_no_empty_loop():
    selected=available_segments(START,load_catalog())
    assert len(table_points(START,selected))<=CONFIG['loop']['max_table_coordinates']<=100
    plans=list(candidates(START,selected,0,60))
    assert len(plans)<=18
    for roads,points in plans:
        assert 1<=len(roads)<=3
        assert points[0]==points[-1]==START
        assert len(points)>2


def test_orientation_respects_oneway():
    segments=examples()
    for s in segments:s.properties.direction='forward'
    for selected,points in candidates(START,segments,42,60,Preferences(),constant_matrix(segments)):
        position=1
        for segment in selected:
            anchors=segment.properties.routing_anchors
            actual=points[position:position+len(anchors)]
            assert [(point.lon,point.lat) for point in actual]==anchors
            position+=len(anchors)
