"""Bounded public social video downloads in a separately terminable process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from ..core.config import settings


def download_social_video(url, output_dir, progress_callback=None):
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    child = None
    try:
        with tempfile.TemporaryDirectory(prefix='social-', dir=destination) as temporary:
            scratch = Path(temporary)
            env = {k: v for k, v in os.environ.items() if not any(
                token in k.upper() for token in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'PROXY'))}
            child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('social_worker.py')),
                url, str(scratch), str(settings.max_file_size)], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + settings.download_timeout_seconds
            try:
                while child.poll() is None:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Video extraction/download exceeded its time limit')
                    if sum(p.stat().st_size for p in scratch.rglob('*') if p.is_file()) > settings.max_file_size:
                        raise ValueError('Video exceeds the configured size limit')
                    if progress_callback:
                        progress_callback(0.5)
                    time.sleep(0.05)
                if child.returncode:
                    raise ValueError('Site could not provide a public downloadable video. Login, regional restrictions, or site changes may prevent access.')
                videos = [p for p in scratch.glob('video.*') if p.suffix.lower() in {'.mp4', '.webm', '.mov', '.mkv'}]
                if len(videos) != 1 or not 0 < videos[0].stat().st_size <= settings.max_file_size:
                    raise ValueError('No complete video within the configured size limit was downloaded')
                result = destination / (uuid.uuid4().hex + videos[0].suffix)
                videos[0].replace(result)
                return True, str(result), None
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
    except Exception as exc:
        from ..security import redact
        return False, None, redact(exc)
