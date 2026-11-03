"""Loopback backend boundary and secret-safe logging."""
from collections import deque
import logging
import secrets
import time
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from .core.config import settings


def redact(value):
    text = str(value)
    for secret in [settings.gemini_api_key, settings.backend_api_key, settings.instagram_password]:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


class SecretFilter(logging.Filter):
    def filter(self, record):
        record.msg, record.args = redact(record.getMessage()), ()
        if record.exc_info:
            record.msg += '\n' + redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        record.exc_text = None
        return True


class BackendBoundary:
    def __init__(self, app):
        self.app = app
        self.submissions = deque()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        host = headers.get(b'host', b'').decode('latin-1')
        try:
            parsed = urlsplit('http://' + host)
            valid_host = parsed.hostname in {'localhost', '127.0.0.1', '::1'} and not parsed.username and not parsed.password and not parsed.path
            parsed.port  # reject malformed ports
        except ValueError:
            valid_host = False
        origin = headers.get(b'origin')
        valid_origin = True
        if origin:
            try:
                source = urlsplit(origin.decode('latin-1'))
                valid_origin = source.scheme in {'http', 'https'} and source.hostname in {'localhost', '127.0.0.1', '::1'} and not source.username
            except ValueError:
                valid_origin = False
        status, detail = None, None
        if not valid_host or not valid_origin:
            status, detail = 403, 'Untrusted host or origin'
        elif scope['path'] != '/health':
            key = settings.backend_api_key
            supplied = headers.get(b'x-insta-backend-key', b'')
            if not key:
                status, detail = 503, 'Backend authentication is not configured'
            elif not secrets.compare_digest(supplied, key.encode('utf-8')):
                status, detail = 401, 'Unauthorized'
            elif scope['path'] == '/api/video/analyze' and scope['method'] == 'POST':
                now = time.monotonic()
                while self.submissions and self.submissions[0] <= now - 60:
                    self.submissions.popleft()
                if len(self.submissions) >= settings.max_submissions_per_minute:
                    status, detail = 429, 'Submission limit reached; try again later'
                else:
                    self.submissions.append(now)
        if status:
            return await JSONResponse({'detail': detail}, status_code=status)(scope, receive, send)
        await self.app(scope, receive, send)
