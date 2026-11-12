"""Bounded public social video downloads in a separately terminable process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from ..core.config import settings


def download_social_video(url, output_dir, progress_callback=None, *, preview=False, deadline=None):
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    child = None
    try:
        if deadline is None:
            deadline = time.monotonic() + settings.download_timeout_seconds
        elif time.monotonic() >= deadline:
            raise TimeoutError('Media download exceeded its time limit')
        with tempfile.TemporaryDirectory(prefix='social-', dir=destination) as temporary:
            scratch = Path(temporary)
            env = {k: v for k, v in os.environ.items() if not any(
                token in k.upper() for token in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'PROXY'))}
            limit = min(settings.max_file_size, 10 * 1024 * 1024) if preview else settings.max_file_size
            command = [sys.executable, str(Path(__file__).with_name('social_worker.py')),
                       url, str(scratch), str(limit)]
            if preview:
                command.append('preview')
            child = subprocess.Popen(command, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                while child.poll() is None:
                    if time.monotonic() > deadline:
                        raise TimeoutError('Video extraction/download exceeded its time limit')
                    if sum(p.stat().st_size for p in scratch.rglob('*') if p.is_file()) > limit:
                        raise ValueError('Video exceeds the configured size limit')
                    if progress_callback:
                        progress_callback(0.5)
                    time.sleep(0.05)
                if child.returncode:
                    if preview:
                        raise ValueError('The site did not expose an accessible public preview image.')
                    raise ValueError('Site could not provide a public downloadable video. Login, regional restrictions, or site changes may prevent access.')
                extensions = {'.jpg', '.png', '.webp'} if preview else {'.mp4', '.webm', '.mov', '.mkv'}
                files = [p for p in scratch.glob('preview.*' if preview else 'video.*') if p.suffix.lower() in extensions]
                if len(files) != 1 or not 0 < files[0].stat().st_size <= limit:
                    raise ValueError('No complete media within the configured size limit was downloaded')
                result = destination / (uuid.uuid4().hex + files[0].suffix)
                files[0].replace(result)
                return True, str(result), None
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
    except Exception as exc:
        from ..security import redact
        return False, None, redact(exc)
