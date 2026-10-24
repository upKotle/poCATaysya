import os
from unittest.mock import patch

import pytest
from dotenv import load_dotenv

from app.routing import create_osrm_client


def client_options(monkeypatch, url, proxy):
    monkeypatch.setenv('OSRM_BASE_URL',url)
    if proxy is None:
        monkeypatch.delenv('OSRM_PROXY_URL',raising=False)
    else:
        monkeypatch.setenv('OSRM_PROXY_URL',proxy)
    with patch('app.routing.httpx.AsyncClient') as factory:
        create_osrm_client()
        return factory.call_args.kwargs


def test_explicit_routing_proxy_does_not_require_shell_proxy(monkeypatch):
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.delenv(key,raising=False)
    options=client_options(monkeypatch,'https://router.project-osrm.org','http://127.0.0.1:10809')
    assert options['proxy'] == 'http://127.0.0.1:10809'
    assert options['trust_env'] is True
    assert options['base_url'] == 'https://router.project-osrm.org'


@pytest.mark.parametrize('url',['http://localhost:5000','http://127.0.0.1:5000','http://[::1]:5000'])
def test_local_router_bypasses_proxy(monkeypatch,url):
    monkeypatch.setenv('HTTPS_PROXY','http://not-running.invalid:9999')
    options=client_options(monkeypatch,url,'http://not-running.invalid:9999')
    assert options['proxy'] is None
    assert options['trust_env'] is False


@pytest.mark.parametrize('proxy',[None,'','  '])
def test_no_explicit_proxy_preserves_standard_environment_support(monkeypatch,proxy):
    options=client_options(monkeypatch,'https://router.project-osrm.org/',proxy)
    assert options['proxy'] is None
    assert options['trust_env'] is True
    assert options['base_url'] == 'https://router.project-osrm.org'


def test_env_file_does_not_override_explicit_shell_configuration(tmp_path,monkeypatch):
    env=tmp_path/'.env'
    env.write_text('OSRM_BASE_URL=https://example.invalid\nOSRM_PROXY_URL=http://127.0.0.1:10809\n')
    monkeypatch.setenv('OSRM_BASE_URL','http://localhost:5000')
    monkeypatch.delenv('OSRM_PROXY_URL',raising=False)
    load_dotenv(env,override=False)
    assert os.environ['OSRM_BASE_URL'] == 'http://localhost:5000'
    assert os.environ['OSRM_PROXY_URL'] == 'http://127.0.0.1:10809'
