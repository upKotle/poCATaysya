import httpx
import pytest
from fastapi import HTTPException

from app.models import Point
from app.routing import RoutingClient
from app.settings import CONFIG

POINTS=[Point(lat=55.751,lon=37.618),Point(lat=55.765,lon=37.64)]


@pytest.mark.asyncio
async def test_table_contract_and_cache_without_repeated_network_calls():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.path=='/table/v1/driving/37.618,55.751;37.64,55.765'
        assert request.url.params['annotations']=='duration'
        assert request.url.params['radiuses']=='150;150'
        return httpx.Response(200,json={'code':'Ok','durations':[[0,100],[200,0]]})
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(handler)) as client:
        router=RoutingClient(client)
        first=await router.durations(POINTS)
        first[0][1]=9999
        second=await router.durations(POINTS)
    assert second==[[0,100],[200,0]]
    assert len(calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,status',[
    ({'code':'Ok','durations':[[0]]},502),
    ({'code':'Ok','durations':[[0,-1],[2,0]]},502),
    ({'code':'Ok','durations':[[0,'100'],[2,0]]},502),
    ({'code':'NoSegment'},422),
])
async def test_invalid_table(payload,status):
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))) as client:
        with pytest.raises(HTTPException) as error:
            await RoutingClient(client).durations(POINTS)
        assert error.value.status_code==status


@pytest.mark.asyncio
async def test_null_duration_is_unreachable_not_zero():
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'code':'Ok','durations':[[0,None],[50,0]]}))) as client:
        assert (await RoutingClient(client).durations(POINTS))[0][1] is None


@pytest.mark.asyncio
async def test_errors_not_cached_and_cache_expires(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'code':'Ok','durations':[[0]]} if len(calls)==1 else {'code':'Ok','durations':[[0,10],[10,0]]})
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(handler)) as client:
        router=RoutingClient(client)
        with pytest.raises(HTTPException):await router.durations(POINTS)
        router._last_request=0
        await router.durations(POINTS)
        monkeypatch.setitem(CONFIG['routing'],'cache_ttl_seconds',0)
        router._last_request=0
        await router.durations(POINTS)
    assert len(calls)==3


@pytest.mark.asyncio
async def test_table_timeout():
    def handler(request):raise httpx.ReadTimeout('timeout')
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HTTPException) as error:await RoutingClient(client).durations(POINTS)
    assert error.value.status_code==504


@pytest.mark.asyncio
async def test_table_retries_one_transient_timeout():
    count=0
    def handler(request):
        nonlocal count
        count+=1
        if count==1:raise httpx.ReadTimeout('temporary')
        return httpx.Response(200,json={'code':'Ok','durations':[[0,10],[10,0]]})
    async with httpx.AsyncClient(base_url='http://osrm',transport=httpx.MockTransport(handler)) as client:
        result=await RoutingClient(client).durations(POINTS)
    assert count==2
    assert result==[[0,10],[10,0]]
