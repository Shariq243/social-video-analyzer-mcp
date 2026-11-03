"""Regression tests for backend persistence and MCP transport authentication."""
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'mcp-server'))


def test_analysis_survives_background_session_and_can_be_polled(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-no-network-key')
    monkeypatch.setenv('BACKEND_API_KEY', 'test-backend-credential-at-least-32-characters')
    from app.main import app
    from app.core.database import Base, get_db
    from app.api.routes import video
    from app.services.file_manager import FileManager
    from app.core.config import settings
    monkeypatch.setattr(settings, 'backend_api_key', 'test-backend-credential-at-least-32-characters')

    engine = create_engine('sqlite:///' + (tmp_path / 'jobs.db').as_posix(), connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    def isolated_db():
        with sessions() as db:
            yield db
    monkeypatch.setattr(video, 'SessionLocal', sessions)
    for attr in ['upload_dir', 'results_dir', 'temp_dir']:
        monkeypatch.setattr(settings, attr, str(tmp_path / attr))
    monkeypatch.setattr(video, 'file_manager', FileManager())
    result = {'raw_response': 'A person explains a video editing technique.', 'model_used': 'fixture-model'}
    def download(url, output_dir, progress_callback=None):
        path = Path(output_dir) / 'clip.mp4'
        path.write_bytes(b'fixture video content')
        progress_callback(1.0)
        return True, str(path), None
    monkeypatch.setattr(video.instagram_downloader, 'download_video', download)
    monkeypatch.setattr(video.video_analyzer, 'analyze_video', lambda *a, **k: result)
    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app, base_url='http://127.0.0.1', headers={'X-Insta-Backend-Key': 'test-backend-credential-at-least-32-characters'}) as client:
            response = client.post('/api/video/analyze', json={'instagram_url': 'https://www.instagram.com/reel/fixture/', 'analysis_type': 'summary'})
            assert response.status_code == 200
            job_id = response.json()['job_id']
            status = client.get('/api/video/status/' + job_id)
            assert status.status_code == 200
            assert status.json()['status'] == 'completed'
            assert status.json()['analysis_result']['analysis']['raw_response'] == result['raw_response']
            listing = client.get('/api/jobs/').json()
            assert listing['jobs'][0]['video_filename'] == 'clip.mp4'
            assert client.get('/api/jobs/stats').json()['completed_jobs'] == 1
            assert client.post('/api/video/analyze', json={'instagram_url': 'https://evil.example/instagram.com/reel/x/'}).status_code == 400
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_streamable_http_wire_protocol_and_authentication(monkeypatch):
    import mcp_sse_server as server
    monkeypatch.setattr(server, 'API_KEYS', ['test-only-credential'])
    headers = {'Authorization': 'Bearer test-only-credential', 'Accept': 'application/json, text/event-stream'}
    with TestClient(server.app, base_url='http://127.0.0.1:8100') as client:
        for path, method in [('/sse', 'GET'), ('/messages', 'POST'), ('/mcp', 'POST')]:
            assert client.request(method, path).status_code == 401
            assert client.request(method, path, headers={'Authorization': 'Bearer incorrect'}).status_code == 401
        response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'regression-test', 'version': '1.0'}}})
        assert response.status_code == 200
        assert response.json()['result']['capabilities']['tools'] is not None
        response = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
        assert len(response.json()['result']['tools']) == 5
    monkeypatch.setattr(server, 'API_KEYS', [])
    with pytest.raises(RuntimeError, match='MCP_API_KEYS'):
        with TestClient(server.app):
            pass
