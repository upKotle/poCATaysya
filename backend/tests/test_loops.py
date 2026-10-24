import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.catalog import ScenicSegment, load_catalog, passes_segment
from app.loops import build_loop, candidates
from app.main import app
from app.models import LoopRequest, Point, Route
from app.routing import RoutingClient
from app.settings import CONFIG

START = Point(lat=55.751, lon=37.618)


@pytest.fixture
def segment():
    # Синтетическая геометрия только для тестов, не данные каталога.
    return ScenicSegment.model_validate({'type':'Feature', 'geometry':{
        'type':'LineString','coordinates':[[37.60,55.75],[37.605,55.75],[37.61,55.75]]},
        'properties':{'id':'test-road','name':'Тестовая дорога',
        'routing_anchors':[[37.60,55.75],[37.605,55.75],[37.61,55.75]],
        'direction':'forward','water':0.5,'architecture':0.5,'greenery':0.5,
        'description':'Тестовая фикстура','source_url':None,
        'verification_status':'draft','verified_at':None}})


class FakeRouting:
    def __init__(self, segment, duration=1800, error=None, closed=True, follow=True):
        self.segment, self.duration, self.error = segment, duration, error
        self.closed, self.follow = closed, follow
        self.calls = []

    async def route_via(self, points):
        self.calls.append(points)
        if self.error:
            raise self.error
        coords = [(points[0].lon,points[0].lat)]
        if self.follow:
            coords.extend(self.segment.geometry.coordinates)
        coords.append((points[-1].lon,points[-1].lat) if self.closed else (37.70,55.80))
        return Route(geometry={'type':'LineString','coordinates':coords},distance_meters=5000,duration_seconds=self.duration)


@pytest.mark.asyncio
async def test_loop_via_anchors_closes_and_names(segment):
    routing = FakeRouting(segment)
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),routing,[segment])
    route = response.routes[0]
    assert routing.calls[0][0] == routing.calls[0][-1] == START
    assert len(routing.calls[0]) == 5
    assert route.geometry.coordinates[0] == route.geometry.coordinates[-1] == (START.lon,START.lat)
    assert route.scenic_segment_ids == ['test-road']
    assert 'Тестовая дорога' in route.explanation
    assert any('draft' in warning for warning in response.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize('seconds,accepted',[(1439,False),(1440,True),(1800,True),(1980,True),(1981,False)])
async def test_duration_window(segment,seconds,accepted):
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),FakeRouting(segment,seconds),[segment])
    assert bool(response.routes) is accepted
    if not accepted:
        assert any('80–110%' in warning for warning in response.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize('closed,follow',[(False,True),(True,False)])
async def test_invalid_geometry_not_presented_as_trip(segment,closed,follow):
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),FakeRouting(segment,closed=closed,follow=follow),[segment])
    assert response.routes == []


@pytest.mark.asyncio
async def test_no_catalog_no_routing():
    class NeverRouting:
        async def route_via(self,*args):
            pytest.fail('No candidates must not request a route')
    response = await build_loop(LoopRequest(start=START),NeverRouting(),[])
    assert not response.routes
    assert any('нет участков' in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_no_car_path_is_empty_result(segment):
    response = await build_loop(LoopRequest(start=START),FakeRouting(segment,error=HTTPException(422,'NoRoute')),[segment])
    assert response.routes == []
    assert any('автомобильный путь' in warning for warning in response.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[502,504])
async def test_router_unavailable_propagates(segment,status):
    with pytest.raises(HTTPException) as error:
        await build_loop(LoopRequest(start=START),FakeRouting(segment,error=HTTPException(status,'router error')),[segment])
    assert error.value.status_code == status


@pytest.mark.asyncio
async def test_total_budget_cancels_request(segment,monkeypatch):
    monkeypatch.setitem(CONFIG['loop'],'request_budget_seconds',0.01)
    cancelled = False
    class SlowRouting:
        async def route_via(self,points):
            nonlocal cancelled
            try:
                await asyncio.sleep(5)
            finally:
                cancelled = True
    with pytest.raises(HTTPException) as error:
        await build_loop(LoopRequest(start=START),SlowRouting(),[segment])
    assert error.value.status_code == 504
    assert cancelled


def test_catalog_schema_and_endpoint():
    catalog = load_catalog()
    assert 20 <= len(catalog) <= 30
    assert all(s.properties.source_url.startswith('https://www.openstreetmap.org/way/') for s in catalog)
    assert all(s.properties.verification_status == 'draft' and s.properties.verified_at is None for s in catalog)
    with TestClient(app) as client:
        response = client.get('/api/scenic-segments')
        assert response.status_code == 200
        assert response.json()['type'] == 'FeatureCollection'
        assert len(response.json()['features']) == len(catalog)


def test_candidate_limit_seed_and_waypoints():
    catalog = load_catalog()
    first = list(candidates(START,catalog,42))
    again = list(candidates(START,catalog,42))
    assert first == again
    assert len(first) <= 20
    assert all(1 <= len(selected) <= 3 for selected,_ in first)
    assert len({tuple((p.lon,p.lat) for p in points) for _,points in first}) == len(first)
    for selected,points in first:
        assert 1 <= len(selected) <= 3
        assert points[0] == points[-1] == START
        assert len(points) >= 4
        assert len(points) == 2 + sum(len(s.properties.routing_anchors) for s in selected)


def test_anchor_nearby_does_not_mean_full_passage(segment):
    assert not passes_segment([[37.6049,55.749],[37.605,55.75],[37.6051,55.749]],segment)
    assert passes_segment(segment.geometry.coordinates,segment)
    assert not passes_segment(list(reversed(segment.geometry.coordinates)),segment)
    both = segment.model_copy(deep=True)
    both.properties.direction = 'both'
    assert passes_segment(list(reversed(both.geometry.coordinates)),both)


@pytest.mark.parametrize('mutation', ['anchor','order','coordinates','review'])
def test_invalid_catalog_rejected(segment,mutation):
    raw = segment.model_dump(mode='json')
    if mutation == 'anchor': raw['properties']['routing_anchors'][1] = [37.62,55.77]
    if mutation == 'order': raw['properties']['routing_anchors'].reverse()
    if mutation == 'coordinates': raw['geometry']['coordinates'][0] = [55.75,37.60]
    if mutation == 'review': raw['properties']['verification_status'] = 'reviewed'
    with pytest.raises(ValidationError):
        ScenicSegment.model_validate(raw)


@pytest.mark.parametrize('body', [
    {'start':{'lat':91,'lon':37.6},'target_duration_minutes':30},
    {'start':{'lat':56,'lon':37.6},'target_duration_minutes':30},
    {'start':START.model_dump(),'target_duration_minutes':31},
])
def test_loop_validation(body):
    with TestClient(app) as client:
        class NeverRouting:
            async def route_via(self,*args):pytest.fail('Invalid request reached routing')
        app.state.routing = NeverRouting()
        assert client.post('/api/routes/loop',json=body).status_code == 422


def test_loop_endpoint(segment):
    with TestClient(app) as client:
        app.state.segments = [segment]
        app.state.routing = FakeRouting(segment)
        response = client.post('/api/routes/loop',json={'start':START.model_dump(),'target_duration_minutes':30})
        assert response.status_code == 200
        assert response.json()['routes'][0]['duration_seconds'] == 1800
        assert 'baseline_duration_seconds' not in response.json()


@pytest.mark.asyncio
async def test_osrm_multi_waypoint_contract(segment):
    points = [START,*[Point(lon=lon,lat=lat) for lon,lat in segment.properties.routing_anchors],START]
    def handler(request):
        coords = request.url.path.rsplit('/',1)[1].split(';')
        assert len(coords) == 5
        assert coords[0] == coords[-1] == '37.618,55.751'
        assert request.url.params['radiuses'] == '150;150;150;150;150'
        return httpx.Response(200,json={'code':'Ok','waypoints':[{'distance':0} for _ in points], 'routes':[{
            'distance':5000,'duration':1800,'geometry':{'type':'LineString','coordinates':[
                [START.lon,START.lat],*segment.geometry.coordinates,[START.lon,START.lat]]}}]})
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(handler)) as client:
        route = await RoutingClient(client).route_via(points)
    assert len(route.geometry.coordinates) == 5


def test_crossing_short_road_is_not_passage(segment):
    short = segment.model_copy(deep=True)
    short.geometry.coordinates = [(37.60,55.75),(37.60045,55.75),(37.6009,55.75)]
    assert not passes_segment([(37.60045,55.749),(37.60045,55.751)],short)
    assert passes_segment(short.geometry.coordinates,short)


@pytest.mark.parametrize('preferences', [
    {'water':-1}, {'architecture':1.1}, {'greenery':'NaN'}, {'water':'Infinity'}
])
def test_invalid_preferences(preferences):
    with TestClient(app) as client:
        assert client.post('/api/routes/loop',json={'start':START.model_dump(),'preferences':preferences}).status_code == 422


@pytest.mark.asyncio
async def test_search_continues_after_first_success(segment,monkeypatch):
    import app.loops as loops
    points = [START,Point(lat=55.75,lon=37.60),Point(lat=55.75,lon=37.61),START]
    monkeypatch.setattr(loops,'candidates',lambda *args: iter([([segment],points)] * 4))
    routing = FakeRouting(segment)
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),routing,[segment])
    assert len(routing.calls) == 4
    assert len(response.routes) == 1  # Одинаковая дорога не становится четырьмя вариантами.


@pytest.mark.asyncio
async def test_partial_results_survive_budget_end(segment,monkeypatch):
    import app.loops as loops
    points = [START,Point(lat=55.75,lon=37.60),Point(lat=55.75,lon=37.61),START]
    monkeypatch.setattr(loops,'candidates',lambda *args: iter([([segment],points)] * 2))
    monkeypatch.setitem(CONFIG['loop'],'request_budget_seconds',0.1)
    class OnceThenSlow(FakeRouting):
        async def route_via(self,points):
            if self.calls:
                await asyncio.sleep(5)
            return await super().route_via(points)
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),OnceThenSlow(segment),[segment])
    assert len(response.routes) == 1
    assert any('Время поиска закончилось' in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_best_later_candidate_wins_before_deduplication(segment,monkeypatch):
    import app.loops as loops
    points = [START,Point(lat=55.75,lon=37.60),Point(lat=55.75,lon=37.61),START]
    monkeypatch.setattr(loops,'candidates',lambda *args: iter([([segment],points)] * 2))
    class Improving(FakeRouting):
        async def route_via(self,points):
            self.duration = 1440 if not self.calls else 1800
            return await super().route_via(points)
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),Improving(segment),[segment])
    assert len(response.routes) == 1
    assert response.routes[0].duration_seconds == 1800


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[502,504])
async def test_partial_result_survives_router_failure(segment,monkeypatch,status):
    import app.loops as loops
    points = [START,Point(lat=55.75,lon=37.60),Point(lat=55.75,lon=37.61),START]
    monkeypatch.setattr(loops,'candidates',lambda *args: iter([([segment],points)] * 2))
    class OnceThenFail(FakeRouting):
        async def route_via(self,points):
            if self.calls:
                raise HTTPException(status,'router failure')
            return await super().route_via(points)
    response = await build_loop(LoopRequest(start=START,target_duration_minutes=30),OnceThenFail(segment),[segment])
    assert len(response.routes) == 1
    assert any('часть запросов' in warning for warning in response.warnings)
