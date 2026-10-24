import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app, RoutingClient

START = {"lat":55.751, "lon":37.618}
END = {"lat":55.765, "lon":37.64}

def osrm_data():
    return {"code":"Ok", "waypoints":[{"distance":3}, {"distance":5}], "routes":[{
        "distance":2600, "duration":420,
        "geometry":{"type":"LineString", "coordinates":[[37.618,55.751],[37.625,55.758],[37.64,55.765]]}}]}

@pytest.fixture
def client():
    with TestClient(app) as client:
        app.state.segments = []  # Эти тесты проверяют только контракт адаптера OSRM.
        yield client


def mock_router(payload=None, status=200, error=None):
    def handler(request):
        assert request.url.path == '/route/v1/driving/37.618,55.751;37.64,55.765'
        assert request.url.params['geometries'] == 'geojson'
        assert request.url.params['radiuses'] == '150;150'
        if error:
            raise error
        return httpx.Response(status, json=payload if payload is not None else osrm_data())
    return httpx.AsyncClient(base_url='http://osrm', transport=httpx.MockTransport(handler))


def test_real_adapter_contract(client):
    app.state.routing = RoutingClient(mock_router())
    response = client.post('/api/routes/point-to-point', json={"start":START,"end":END})
    assert response.status_code == 200
    data = response.json()
    assert data['routes'][0]['geometry']['coordinates'][0] == [37.618,55.751]
    assert data['baseline_duration_seconds'] == 420
    assert data['routes'][0]['distance_meters'] == 2600
    assert data['warnings']

@pytest.mark.parametrize('start,end', [
    ({'lat':91,'lon':37.6},END), ({'lat':55.75,'lon':181},END),
    ({'lat':56,'lon':37.6},END), (START,START),
    ({'lat':55.75101,'lon':37.61801},START), ({'lat':'NaN','lon':37.6},END)])
def test_invalid_points_do_not_call_router(client, start, end):
    class NeverCall:
        async def route(self, *args):
            pytest.fail('Invalid request reached routing')
    app.state.routing = NeverCall()
    assert client.post('/api/routes/point-to-point', json={'start':start,'end':end}).status_code == 422

@pytest.mark.parametrize('payload,status,error,expected', [
    ({'code':'NoRoute'},200,None,422), ({'code':'NoSegment'},400,None,422),
    ({},500,None,502), ({'code':'Ok','routes':[]},200,None,502),
    (None,200,httpx.ReadTimeout('timeout'),504),
    (None,200,httpx.ConnectError('offline'),502),
])
def test_routing_errors(client,payload,status,error,expected):
    app.state.routing = RoutingClient(mock_router(payload,status,error))
    response = client.post('/api/routes/point-to-point',json={'start':START,'end':END})
    assert response.status_code == expected
    assert 'routes' not in response.json()


def test_distant_snap(client):
    data = osrm_data()
    data['waypoints'][0]['distance'] = 151
    app.state.routing = RoutingClient(mock_router(data))
    assert client.post('/api/routes/point-to-point',json={'start':START,'end':END}).status_code == 422


def test_health_and_config(client):
    assert client.get('/api/health').json() == {'status':'ok'}
    assert client.get('/api/config').json()['bounds']['west'] == 37.52
