"""Regression tests for findings from the public-source audit; no provider calls."""
import json
import logging
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'windows'))
sys.path.insert(0, str(ROOT / 'mcp-server'))


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-gemini-secret-not-real')
    monkeypatch.setenv('BACKEND_API_KEY', 'test-backend-internal-secret-at-least-32-characters')
    from app.main import app
    from app.core.config import settings
    monkeypatch.setattr(settings, 'backend_api_key', 'test-backend-internal-secret-at-least-32-characters')
    return app, settings


def test_backend_rejects_missing_wrong_auth_and_untrusted_host_origin(runtime):
    app, settings = runtime
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/jobs/stats').status_code == 401
        assert client.get('/api/jobs/stats', headers={'X-Insta-Backend-Key': 'wrong'}).status_code == 401
        headers = {'X-Insta-Backend-Key': settings.backend_api_key}
        assert client.get('/api/jobs/stats', headers={**headers, 'Host': 'attacker.invalid:18002'}).status_code == 403
        assert client.get('/health', headers={'Origin': 'https://attacker.invalid'}).status_code == 403
        # Valid auth reaches routing without touching a database.
        assert client.get('/not-a-route', headers=headers).status_code == 404
    settings.backend_api_key = ''
    with pytest.raises(RuntimeError, match='BACKEND_API_KEY'):
        with TestClient(app):
            pass


def test_file_handler_redacts_credentials_in_message_and_traceback(runtime, tmp_path):
    from app.security import SecretFilter
    _, settings = runtime
    path = tmp_path / 'test.log'
    handler = logging.FileHandler(path, encoding='utf-8')
    handler.addFilter(SecretFilter())
    logger = logging.getLogger('isolated-redaction-test')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        try:
            raise ValueError(settings.gemini_api_key + settings.backend_api_key)
        except ValueError:
            logger.exception('Provider message: %s', settings.gemini_api_key)
    finally:
        logger.removeHandler(handler)
        handler.close()
    text = path.read_text(encoding='utf-8')
    assert settings.gemini_api_key not in text
    assert settings.backend_api_key not in text
    assert '[REDACTED]' in text


@pytest.mark.parametrize('length,chunks', [('1000', [b'x']), (None, [b'12345', b'67890', b'x'])])
def test_stream_rejects_oversize_even_without_content_length(runtime, tmp_path, monkeypatch, length, chunks):
    from app.services.instagram_downloader import InstagramDownloader, Post
    _, settings = runtime
    monkeypatch.setattr(settings, 'max_file_size', 10)
    downloader = InstagramDownloader()
    monkeypatch.setattr(Post, 'from_shortcode', lambda *args: SimpleNamespace(is_video=True, video_url='https://example.invalid/fixture.mp4'))
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {'Content-Length': length} if length else {}
    response.iter_content.return_value = iter(chunks)
    monkeypatch.setattr(downloader.loader.context, 'get_raw', lambda *args: response)
    success, _, error = downloader.download_video('https://www.instagram.com/reel/fixture/', str(tmp_path))
    assert not success and 'size limit' in error
    assert not list(tmp_path.glob('*.part'))
    assert not list(tmp_path.glob('*.mp4'))


def test_valid_stream_and_upload_size_guard(runtime, tmp_path, monkeypatch):
    from app.services.instagram_downloader import InstagramDownloader, Post
    from app.services.video_analyzer import VideoAnalyzer
    _, settings = runtime
    monkeypatch.setattr(settings, 'max_file_size', 10)
    downloader = InstagramDownloader()
    monkeypatch.setattr(Post, 'from_shortcode', lambda *args: SimpleNamespace(is_video=True, video_url='https://example.invalid/fixture.mp4'))
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {}
    response.iter_content.return_value = iter([b'12345', b'67890'])
    monkeypatch.setattr(downloader.loader.context, 'get_raw', lambda *args: response)
    success, path, _ = downloader.download_video('https://www.instagram.com/reel/fixture/', str(tmp_path))
    assert success and Path(path).read_bytes() == b'1234567890'
    Path(path).write_bytes(b'x' * 11)
    analyzer = VideoAnalyzer()
    analyzer.client = Mock()
    with pytest.raises(Exception, match='size limit'):
        analyzer.analyze_video(path)
    analyzer.client.files.upload.assert_not_called()


def test_submission_limit_blocks_repeated_work(runtime, monkeypatch):
    app, settings = runtime
    monkeypatch.setattr(settings, 'max_submissions_per_minute', 1)
    # Independent middleware instance so the test has a fresh rate-limit window.
    from app.security import BackendBoundary
    from fastapi import FastAPI
    isolated = FastAPI()
    isolated.add_middleware(BackendBoundary)
    with TestClient(isolated, base_url='http://127.0.0.1', headers={'X-Insta-Backend-Key': settings.backend_api_key}) as client:
        assert client.post('/api/video/analyze').status_code == 404
        assert client.post('/api/video/analyze').status_code == 429


def test_job_slot_rejected_without_database_or_provider_work(runtime, monkeypatch):
    from app.api.routes import video
    from fastapi import HTTPException, BackgroundTasks
    monkeypatch.setattr(video, 'job_slots', threading.BoundedSemaphore(0))
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        video.analyze_video(video.VideoAnalysisRequest(instagram_url='https://www.instagram.com/reel/fixture/'), BackgroundTasks(), db)
    assert exc.value.status_code == 429
    db.add.assert_not_called()


def test_backend_key_is_persisted_encrypted_and_not_exported(tmp_path):
    import launcher
    settings = launcher.Settings('', '', 'test-gemini-own-key', mode='local')
    launcher.save_settings(settings, tmp_path)
    assert launcher.load_settings(tmp_path).backend_key == settings.backend_key
    assert settings.backend_key.encode() not in (tmp_path / 'credentials.dpapi').read_bytes()
    directory = launcher.export_client_configs(settings, tmp_path / 'exports')
    for path in directory.iterdir():
        assert settings.backend_key not in path.read_text(encoding='utf-8')


def test_stdio_recovers_encrypted_backend_key(tmp_path, monkeypatch):
    import launcher
    import mcp_sse_server as server
    settings = launcher.Settings('', '', 'test-gemini-own-key', mode='local')
    launcher.save_settings(settings, tmp_path / '.insta-analyzer')
    monkeypatch.delenv('BACKEND_API_KEY', raising=False)
    monkeypatch.setattr(server, '__file__', str(tmp_path / 'mcp-server/mcp_sse_server.py'))
    assert server.backend_headers() == {'X-Insta-Backend-Key': settings.backend_key}


def test_storage_budget_releases_job_slot(runtime, tmp_path, monkeypatch):
    from app.api.routes import video
    from fastapi import HTTPException, BackgroundTasks
    _, settings = runtime
    monkeypatch.setattr(settings, 'max_storage_bytes', 1)
    monkeypatch.setattr(settings, 'upload_dir', str(tmp_path))
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(video, 'job_slots', slots)
    db = Mock()
    with pytest.raises(HTTPException) as exc:
        video.analyze_video(video.VideoAnalysisRequest(instagram_url='https://www.instagram.com/reel/fixture/'), BackgroundTasks(), db)
    assert exc.value.status_code == 507
    db.add.assert_not_called()
    assert slots.acquire(blocking=False)


@pytest.fixture
def pending_job(runtime, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.models import JobStatus, VideoJob

    engine = create_engine('sqlite:///' + (tmp_path / 'jobs.db').as_posix())
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            job = VideoJob(job_id='fixture-job', status=JobStatus.PENDING,
                           instagram_url='https://www.instagram.com/reel/fixture/')
            db.add(job)
            db.commit()
            yield db, job
    finally:
        engine.dispose()


def test_cancelled_pending_job_never_starts(pending_job, monkeypatch):
    import asyncio
    from app.api.routes import jobs, video
    from app.models import JobStatus

    db, job = pending_job
    download = Mock()
    monkeypatch.setattr(video.instagram_downloader, 'download_video', download)
    asyncio.run(jobs.cancel_job(job.job_id, db))
    video._process_video_job(job.job_id, job.instagram_url, 'summary', db)
    assert job.status == JobStatus.CANCELLED
    download.assert_not_called()


def test_failed_file_cleanup_keeps_job_available_for_retry(pending_job, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from app.api.routes import jobs
    from app.models import VideoJob

    db, job = pending_job
    monkeypatch.setattr(jobs.file_manager, 'cleanup_job_files', Mock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(jobs.delete_job(job.job_id, cleanup_files=True, db=db))
    assert exc.value.status_code == 500
    assert db.get(VideoJob, job.id) is not None


def test_real_stdio_tool_reaches_authenticated_backend(tmp_path):
    import asyncio
    import os
    import socket
    import subprocess
    import time
    import httpx
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, GEMINI_API_KEY='test-provider-key-not-real',
               BACKEND_API_KEY='test-internal-credential-at-least-32-characters',
               DATABASE_URL='sqlite:///' + (tmp_path / 'test.db').as_posix(),
               UPLOAD_DIR=str(tmp_path / 'uploads'), RESULTS_DIR=str(tmp_path / 'results'),
               TEMP_DIR=str(tmp_path / 'temp'), LOG_FILE=str(tmp_path / 'backend.log'),
                API_BASE_URL=f'http://127.0.0.1:{port}',
                HTTP_PROXY='http://127.0.0.1:1', NO_PROXY='')
    child = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--app-dir', str(ROOT / 'backend'),
                              '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    async def check():
        async with stdio_client(StdioServerParameters(command=sys.executable,
                args=[str(ROOT / 'mcp-server/mcp_sse_server.py'), '--stdio'], env=env)) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == 5
                result = await session.call_tool('get_system_stats', {})
                assert not result.isError
                assert json.loads(result.content[0].text)['total_jobs'] == 0
    try:
        with httpx.Client(trust_env=False) as client:
            deadline = time.monotonic() + 20
            while True:
                assert child.poll() is None
                try:
                    if client.get(env['API_BASE_URL'] + '/health', timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.1)
            assert client.get(env['API_BASE_URL'] + '/api/jobs/stats').status_code == 401
        asyncio.run(check())
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_old_encrypted_settings_migrate_once(tmp_path):
    import launcher
    legacy = {'tunnel_id': '', 'runtime_key': '', 'gemini_key': 'test-preserved-gemini', 'mode': 'local'}
    (tmp_path / 'credentials.dpapi').write_bytes(launcher.crypt(json.dumps(legacy).encode()))
    first = launcher.load_settings(tmp_path)
    second = launcher.load_settings(tmp_path)
    assert first.backend_key == second.backend_key
    assert first.gemini_key == legacy['gemini_key']
    assert first.backend_key.encode() not in (tmp_path / 'credentials.dpapi').read_bytes()


def test_stream_deadline_removes_partial_video(runtime, tmp_path, monkeypatch):
    from app.services import instagram_downloader as module
    downloader = module.InstagramDownloader()
    monkeypatch.setattr(module.Post, 'from_shortcode', lambda *args: SimpleNamespace(is_video=True, video_url='https://example.invalid/fixture.mp4'))
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {}
    response.iter_content.return_value = iter([b'x'])
    monkeypatch.setattr(downloader.loader.context, 'get_raw', lambda *args: response)
    times = iter([0, 999])
    # Replace this module's time namespace, leaving test runners/HTTP time intact.
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: next(times)))
    success, _, error = downloader.download_video('https://www.instagram.com/reel/fixture/', str(tmp_path))
    assert not success and 'time limit' in error
    assert not list(tmp_path.glob('*.part'))
