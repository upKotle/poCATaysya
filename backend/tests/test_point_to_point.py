import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.catalog import ScenicSegment
from app.models import Point, Preferences, Route, RouteRequest
from app.point_to_point import build_point_to_point, point_candidates
from app.settings import CONFIG


@pytest.fixture
def road():
    return ScenicSegment.model_validate({'type':'Feature','geometry':{'type':'LineString','coordinates':[[37.60,55.75],[37.605,55.75],[37.61,55.75]]},'properties':{
        'id':'road','name':'Тестовая дорога','routing_anchors':[[37.60,55.75],[37.605,55.75],[37.61,55.75]],
        'direction':'forward','water':1,'architecture':0,'greenery':0,'description':'Фикстура',
        'source_url':None,'verification_status':'draft','verified_at':None}})


BODY = RouteRequest(start=Point(lat=55.74,lon=37.59),end=Point(lat=55.74,lon=37.62),max_extra_minutes=5)


class Router:
    def __init__(self, seconds=900, error=None, follow=True):
        self.seconds, self.error, self.follow = seconds, error, follow
        self.calls = []

    async def route(self, start, end):
        return Route(geometry={'type':'LineString','coordinates':[[start.lon,start.lat],[end.lon,end.lat]]},distance_meters=2000,duration_seconds=600)

    async def durations(self, points):
        return [[0 if a == b else 10 for b in points] for a in points]

    async def route_via(self, points):
        self.calls.append(points)
        if self.error:
            raise self.error
        coords = [[p.lon,p.lat] for p in points] if self.follow else [[BODY.start.lon,BODY.start.lat],[BODY.end.lon,BODY.end.lat]]
        return Route(geometry={'type':'LineString','coordinates':coords},distance_meters=4000,duration_seconds=self.seconds)


@pytest.mark.asyncio
@pytest.mark.parametrize('seconds,count',[(899,2),(900,2),(900.01,1)])
async def test_hard_time_limit_and_baseline(road,seconds,count):
    router = Router(seconds)
    response = await build_point_to_point(BODY,router,[road])
    assert len(response.routes) == count
    assert response.baseline_duration_seconds == 600
    assert response.routes[0].id == 'baseline'
    assert all(route.duration_seconds <= 900 for route in response.routes)
    if count == 2:
        assert response.routes[1].scenic_segment_ids == ['road']
        assert 'Возвращение' not in response.routes[1].explanation
        assert router.calls[0][0] == BODY.start and router.calls[0][-1] == BODY.end


@pytest.mark.asyncio
async def test_anchor_without_following_road_is_not_scenic(road):
    response = await build_point_to_point(BODY,Router(follow=False),[road])
    assert len(response.routes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[422,502,504])
async def test_candidate_error_keeps_baseline(road,status):
    response = await build_point_to_point(BODY,Router(error=HTTPException(status,'failure')),[road])
    assert [r.id for r in response.routes] == ['baseline']
    assert response.warnings


@pytest.mark.asyncio
async def test_table_failure_keeps_baseline(road):
    class Broken(Router):
        async def durations(self, points):
            raise HTTPException(504,'timeout')
    response = await build_point_to_point(BODY,Broken(),[road])
    assert len(response.routes) == 1
    assert any('не полностью' in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_budget_keeps_baseline(road,monkeypatch):
    class Slow(Router):
        async def durations(self, points):
            await asyncio.sleep(1)
    monkeypatch.setitem(CONFIG['point_to_point'],'request_budget_seconds',.02)
    response = await build_point_to_point(BODY,Slow(),[road])
    assert response.routes[0].id == 'baseline'


@pytest.mark.asyncio
async def test_baseline_failure_propagates(road):
    class Broken(Router):
        async def route(self, *args):
            raise HTTPException(502,'offline')
    with pytest.raises(HTTPException) as error:
        await build_point_to_point(BODY,Broken(),[road])
    assert error.value.status_code == 502


def test_unreachable_and_over_budget_plans_not_queried(road):
    assert list(point_candidates(BODY,[road],[[None]*5 for _ in range(5)],900)) == []
    assert list(point_candidates(BODY,[road],[[1000]*5 for _ in range(5)],900)) == []


@pytest.mark.parametrize('minutes',[0,6,21,-1])
def test_invalid_extra_minutes(minutes):
    with pytest.raises(ValidationError):
        RouteRequest(start=BODY.start,end=BODY.end,max_extra_minutes=minutes)


@pytest.mark.asyncio
async def test_duplicate_candidates_not_returned(road):
    duplicate = road.model_copy(deep=True)
    duplicate.properties.id = 'copy'
    response = await build_point_to_point(BODY,Router(),[road,duplicate])
    assert len(response.routes) == 2


@pytest.mark.asyncio
async def test_no_catalog_returns_baseline():
    response = await build_point_to_point(BODY,Router(),[])
    assert len(response.routes) == 1
    assert any('не найдено' in warning for warning in response.warnings)


def test_candidates_respect_direction_preferences_and_cap(road):
    architecture = road.model_copy(deep=True)
    architecture.properties.id = 'architecture'
    architecture.properties.water = 0
    architecture.properties.architecture = 1
    body = BODY.model_copy(update={'preferences': Preferences(water=0,architecture=1,greenery=0)})
    plans = list(point_candidates(body,[road,architecture],[[10]*8 for _ in range(8)],900))
    assert len(plans) <= CONFIG['point_to_point']['max_candidates']
    assert plans[0][0][0].properties.id == 'architecture'
    for selected, points in plans:
        assert len(selected) <= 2
        assert points[0] == BODY.start and points[-1] == BODY.end
        for offset in range(1,len(points)-1,3):
            assert points[offset].lon < points[offset+2].lon  # forward не разворачивается
