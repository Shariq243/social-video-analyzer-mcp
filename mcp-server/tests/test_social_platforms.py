import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
from video_platforms import platform_for_url


@pytest.mark.parametrize('url,platform', [
    ('https://www.instagram.com/reel/fixture/', 'instagram'),
    ('https://www.facebook.com/share/r/fixture/', 'facebook'),
    ('https://fb.watch/fixture/', 'facebook'),
    ('https://vm.tiktok.com/fixture/', 'tiktok'),
    ('https://www.linkedin.com/posts/fixture', 'linkedin'),
    ('https://x.com/example/status/123', 'x'),
    ('https://twitter.com/example/status/123', 'x'),
])
def test_platform_urls(url, platform):
    assert platform_for_url(url) == platform


@pytest.mark.parametrize('url', ['https://instagram.com.evil.test/reel/x',
    'http://facebook.com/video/x', 'https://localhost/video',
    'https://127.0.0.1/video', 'https://user:pass@x.com/a/status/1',
    'https://x.com:8080/a/status/1', 'file:///tmp/video', 'https://x.com/'])
def test_reject_unsafe_urls(url):
    with pytest.raises(ValueError):
        platform_for_url(url)


def test_deadline_kills_worker_and_removes_partial(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-unused-key')
    from app.services import social_downloader as module
    child = Mock()
    child.poll.return_value = None
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: child)
    ticks = iter([0, 999])
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(ticks))
    ok, path, error = module.download_social_video('https://x.com/a/status/1', str(tmp_path))
    assert not ok and path is None and 'time limit' in error
    child.kill.assert_called_once()
    assert not list(tmp_path.iterdir())


def test_dispatch_keeps_instagram_and_routes_other_platforms(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-unused-key')
    from app.services import instagram_downloader as module
    from app.services import social_downloader
    called = Mock(return_value=(True, 'fixture.mp4', None))
    monkeypatch.setattr(social_downloader, 'download_social_video', called)
    downloader = module.InstagramDownloader()
    assert downloader.download_video('https://www.facebook.com/share/r/fixture/', 'unused')[0]
    called.assert_called_once()
    assert not downloader.download_video('https://evil.test/video', 'unused')[0]


@pytest.mark.parametrize('oversized', [False, True])
def test_worker_result_and_oversize_cleanup(tmp_path, monkeypatch, oversized):
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-unused-key')
    from app.services import social_downloader as module
    monkeypatch.setattr(module.settings, 'max_file_size', 8)
    child = Mock(returncode=0)
    child.poll.return_value = None if oversized else 0
    def spawn(command, **kwargs):
        (Path(command[3]) / 'video.mp4').write_bytes(b'x' * (9 if oversized else 4))
        assert not any('KEY' in k.upper() for k in kwargs['env'])
        return child
    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    result = module.download_social_video('https://x.com/a/status/1', str(tmp_path))
    assert result[0] is not oversized
    if oversized:
        child.kill.assert_called_once()
        assert not list(tmp_path.iterdir())
    else:
        assert Path(result[1]).read_bytes() == b'xxxx'
