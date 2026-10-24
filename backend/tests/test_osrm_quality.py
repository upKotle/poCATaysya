"""Явный сетевой регрессионный сценарий: RUN_OSRM_QUALITY=1 uv run pytest tests/test_osrm_quality.py -q."""
import os

import pytest
from fastapi.testclient import TestClient

from app.catalog import metric_line
from app.geometry import RoadTrace, route_similarity
from app.main import app

pytestmark=pytest.mark.skipif(os.getenv('RUN_OSRM_QUALITY')!='1',reason='Отдельный сетевой сценарий качества, до 55 запросов OSRM')


def test_hour_and_preference_difference_on_real_roads():
    responses={}
    with TestClient(app) as client:
        for label,minutes,prefs in [
            ('hour',60,{'water':1,'architecture':1,'greenery':1}),
            ('water',30,{'water':1,'architecture':0,'greenery':0}),
            ('architecture',30,{'water':0,'architecture':1,'greenery':0}),
        ]:
            response=client.post('/api/routes/loop',json={'start':{'lat':55.751,'lon':37.618},'target_duration_minutes':minutes,'preferences':prefs})
            assert response.status_code==200,response.text
            data=response.json()
            assert data['routes'],(label,data['warnings'])
            assert 1<=len(data['routes'])<=3
            assert all(minutes*60*.8<=r['duration_seconds']<=minutes*60*1.1 for r in data['routes'])
            responses[label]=data['routes'][0]
    water,architecture=responses['water'],responses['architecture']
    similarity=route_similarity(RoadTrace(metric_line(water['geometry']['coordinates'])),RoadTrace(metric_line(architecture['geometry']['coordinates'])),25)
    assert similarity<.8,similarity
    assert water['scenic_category_meters']['water']>architecture['scenic_category_meters']['water']
    assert architecture['scenic_category_meters']['architecture']>water['scenic_category_meters']['architecture']
