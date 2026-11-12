"""Public post analysis with fixture media and a dummy model."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'mcp-server'))


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-key')
    from app.services import post_analysis
    return post_analysis


@pytest.mark.parametrize('url,kinds,carousel,expected', [
    ('https://www.instagram.com/p/DfGihRwlvYG/?utm_source=fixture', ['image'], False, 'image'),
    ('https://www.instagram.com/reel/Fixture/?igsh=fixture', ['video'], False, 'video'),
    ('https://www.instagram.com/p/Fixture/', ['image', 'image'], True, 'carousel'),
    ('https://www.instagram.com/p/Fixture/', ['image', 'video', 'image'], True, 'mixed_carousel'),
])
def test_instagram_post_detects_and_analyzes_ordered_media(service, monkeypatch, tmp_path, url, kinds, carousel, expected):
    nodes = [SimpleNamespace(is_video=kind == 'video', url=f'https://a.cdninstagram.com/{i}.jpg',
                            display_url=f'https://a.cdninstagram.com/{i}.jpg',
                            video_url=f'https://a.cdninstagram.com/{i}.mp4') for i, kind in enumerate(kinds)]
    post = SimpleNamespace(typename='GraphSidecar' if carousel else 'GraphVideo' if kinds[0] == 'video' else 'GraphImage',
                           caption='Fixture caption', is_video=nodes[0].is_video, url=nodes[0].url,
                           video_url=nodes[0].video_url, get_sidecar_nodes=lambda: iter(nodes))
    lookup = Mock(return_value=post)
    monkeypatch.setattr(service.instaloader.Post, 'from_shortcode', lookup)

    @contextmanager
    def media(media_url):
        mime = 'video/mp4' if media_url.endswith('.mp4') else 'image/jpeg'
        yield httpx.Response(200, headers={'Content-Type': mime}, content=b'fixture media')

    monkeypatch.setattr(service, '_instagram_media', media)
    vision = Mock(side_effect=lambda prompt, image=None: image.name if image else 'Ordered fixture summary')
    monkeypatch.setattr(service, '_vision', vision)
    video = Mock()
    video.analyze_video.return_value = {'raw_response': 'Fixture video'}
    detected = Mock()
    result = service.analyze_public_post(url, tmp_path, 'summary', video, Mock(), Mock(), detected)
    detected.assert_called_once_with(expected)
    assert lookup.call_args.args[1] == url.split('/')[4]
    assert result['post_caption'] == 'Fixture caption'
    assert result['content_type'] == expected
    assert result['media_count'] == len(kinds)
    assert [slide['index'] for slide in result['slides']] == list(range(1, len(kinds) + 1))
    assert [slide['media_type'] for slide in result['slides']] == kinds
    assert video.analyze_video.call_count == kinds.count('video')
    assert all('path' not in slide for slide in result['slides'])


def test_instagram_access_error_is_explicit(service, monkeypatch, tmp_path):
    lookup = Mock(side_effect=service.instaloader.exceptions.LoginRequiredException('fixture restriction'))
    monkeypatch.setattr(service.instaloader.Post, 'from_shortcode', lookup)
    with pytest.raises(ValueError, match='Instagram did not provide access'):
        service.analyze_public_post('https://www.instagram.com/p/DfGihRwlvYG/', tmp_path,
                                    'summary', Mock(), Mock(), Mock(), Mock())


def test_image_only_transcription_is_rejected_before_download(service, monkeypatch, tmp_path):
    monkeypatch.setattr(service.instaloader.Post, 'from_shortcode', Mock(return_value=SimpleNamespace(
        typename='GraphImage', caption=None, is_video=False)))
    media = Mock()
    monkeypatch.setattr(service, '_instagram_media', media)
    with pytest.raises(ValueError, match='Transcription requires a video'):
        service.analyze_public_post('https://www.instagram.com/p/Fixture/', tmp_path,
                                    'transcription', Mock(), Mock(), Mock(), Mock())
    media.assert_not_called()


@pytest.mark.parametrize('url', ['https://www.facebook.com/share/r/fixture/', 'https://vt.tiktok.com/fixture/',
                                 'https://lnkd.in/p/fixture', 'https://x.com/example/status/123'])
@pytest.mark.parametrize('preview', [False, True])
def test_universal_other_platform_routes_video_or_labeled_preview(service, monkeypatch, tmp_path, url, preview):
    path = tmp_path / ('fixture.jpg' if preview else 'fixture.mp4')
    path.write_bytes(b'fixture media')
    success = (True, str(path), None)
    download = Mock(side_effect=[(False, None, 'No video'), success] if preview else [success])
    monkeypatch.setattr(service, 'download_social_video', download)
    vision = Mock(return_value='Fixture image')
    monkeypatch.setattr(service, '_vision', vision)
    video = Mock()
    video.analyze_video.return_value = {'raw_response': 'Fixture video'}
    result = service.analyze_public_post(url, tmp_path, 'summary', video, Mock(), Mock(), Mock())
    assert result['content_type'] == ('image_preview' if preview else 'video')
    assert result['media_count'] == 1
    assert video.analyze_video.call_count == (0 if preview else 1)
    if preview:
        assert download.call_args.kwargs['preview'] is True
        vision.assert_called_once()
    else:
        vision.assert_not_called()


def test_old_database_adds_media_type_without_removing_job(service, monkeypatch, tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.core import database
    engine = create_engine('sqlite:///' + (tmp_path / 'existing.db').as_posix())
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE video_jobs (id INTEGER PRIMARY KEY, job_id VARCHAR(36))'))
        conn.execute(text("INSERT INTO video_jobs (job_id) VALUES ('old-job')"))
    monkeypatch.setattr(database, 'engine', engine)
    database.create_tables()
    database.create_tables()
    assert 'media_type' in {column['name'] for column in inspect(engine).get_columns('video_jobs')}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT job_id, media_type FROM video_jobs')).one() == ('old-job', None)
    engine.dispose()


def test_post_mcp_call_uses_existing_job_endpoint(monkeypatch):
    import mcp_sse_server as server
    client = AsyncMock()
    client.post.return_value = httpx.Response(200, json={'job_id': 'fixture-job', 'status': 'pending'})
    monkeypatch.setattr(server, 'http_client', client)
    url = 'https://www.facebook.com/share/r/fixture/'
    result = asyncio.run(server.analyze_video_tool(url, 'summary', analyze_post=True))
    assert result['job_id'] == 'fixture-job'
    client.post.assert_awaited_once_with('/api/video/analyze', json={
        'instagram_url': url, 'analysis_type': 'summary', 'analyze_post': True,
    })


def test_local_video_frames_keep_original_timestamps(service, monkeypatch, tmp_path):
    path = tmp_path / 'fixture.mp4'
    path.write_bytes(b'fixture video')
    monkeypatch.setattr(service.settings, 'ollama_video_frames', 3)
    monkeypatch.setattr(service.shutil, 'which', lambda name: name)
    def run(command, **options):
        if command[0] == 'ffprobe':
            return SimpleNamespace(stdout=b'12.0')
        Path(command[-1]).write_bytes(b'fixture frame')
    monkeypatch.setattr(service.subprocess, 'run', run)
    monkeypatch.setattr(service, '_vision', Mock(return_value='Fixture description'))
    result = service._describe_frames(path, Mock())
    assert [item['timestamp_seconds'] for item in result] == [0, 4, 8]
    assert not list(tmp_path.glob('frames-*'))
