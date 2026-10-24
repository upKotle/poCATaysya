"""Отдельные проверки настоящего OSRM: RUN_OSRM_INTEGRATION=1 uv run pytest tests/test_osrm_integration.py."""
import os
import pytest
from fastapi.testclient import TestClient

from app.catalog import load_catalog, passes_segment
from app.geo import distance
from app.main import app
from app.models import Point

pytestmark = pytest.mark.skipif(os.getenv('RUN_OSRM_INTEGRATION') != '1', reason='Нужен запущенный OSRM и явное включение')
START = {'lat':55.751,'lon':37.618}


@pytest.fixture(scope='module')
def real_client():
    # Общий адаптер сохраняет ограничение частоты между тестами.
    with TestClient(app) as client:
        yield client


def test_real_osrm_point_to_point(real_client):
    response = real_client.post('/api/routes/point-to-point', json={
        'start':START, 'end':{'lat':55.765,'lon':37.64}})
    assert response.status_code == 200, response.text
    route = response.json()['routes'][0]
    assert route['distance_meters'] > 100
    assert route['duration_seconds'] > 0
    assert len(route['geometry']['coordinates']) > 2


def test_real_osrm_loop(real_client):
    response = real_client.post('/api/routes/loop', json={
        'start':START, 'target_duration_minutes':30, 'seed':0})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['routes'], data['warnings']
    from app.geometry import RoadTrace, route_similarity
    from app.catalog import metric_line
    from app.settings import CONFIG
    assert 1 <= len(data['routes']) <= 3
    catalog = {s.properties.id:s for s in load_catalog()}
    traces = []
    for route in data['routes']:
        assert 1440 <= route['duration_seconds'] <= 1980
        coords = route['geometry']['coordinates']
        assert len(coords) > 2
        for lon, lat in (coords[0],coords[-1]):
            assert distance(Point(**START),Point(lon=lon,lat=lat)) <= 150
        assert route['scenic_segment_ids']
        assert all(passes_segment(coords,catalog[id]) for id in route['scenic_segment_ids'])
        trace = RoadTrace(metric_line(coords))
        assert all(route_similarity(trace,other,CONFIG['ranking']['similarity_tolerance_meters']) < CONFIG['ranking']['max_similarity_ratio'] for other in traces)
        traces.append(trace)


def test_real_osrm_scenic_point_to_point(real_client):
    from app.catalog import metric_line
    from app.geometry import RoadTrace, route_similarity
    response = real_client.post('/api/routes/point-to-point', json={
        'start':{'lat':55.74,'lon':37.59}, 'end':{'lat':55.765,'lon':37.64},
        'max_extra_minutes':15, 'preferences':{'water':1,'architecture':0,'greenery':0}})
    assert response.status_code == 200, response.text
    data = response.json()
    assert 2 <= len(data['routes']) <= 3, data['warnings']
    assert data['routes'][0]['id'] == 'baseline'
    catalog = {s.properties.id:s for s in load_catalog()}
    traces = []
    for route in data['routes']:
        assert route['duration_seconds'] <= data['baseline_duration_seconds'] + 900
        coords = route['geometry']['coordinates']
        assert len(coords) > 10
        assert all(passes_segment(coords,catalog[id]) for id in route['scenic_segment_ids'])
        trace = RoadTrace(metric_line(coords))
        assert all(route_similarity(trace,other,25) < .8 for other in traces)
        traces.append(trace)
