from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend


def test_combined_app_serves_ui_assets_and_api(tmp_path):
    directory = tmp_path / 'dist'
    (directory / 'assets').mkdir(parents=True)
    (directory / 'index.html').write_text('<!doctype html><title>Scenic Drive</title>')
    (directory / 'assets' / 'app.js').write_text('console.log("ready");')
    app = FastAPI()

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    mount_frontend(app, directory)
    with TestClient(app) as client:
        assert 'Scenic Drive' in client.get('/').text
        assert client.get('/assets/app.js').status_code == 200
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/api/missing').status_code == 404
        assert client.get('/missing.js').status_code == 404
        assert client.get('/.env').status_code == 404
        assert client.get('/docs').status_code == 200


def test_missing_frontend_does_not_break_backend_development(tmp_path):
    app = FastAPI()
    mount_frontend(app, tmp_path / 'not-built')
    with TestClient(app) as client:
        assert client.get('/').status_code == 404
