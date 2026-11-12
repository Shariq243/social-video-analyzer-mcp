"""Read a public page's Open Graph preview inside the guarded worker."""
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import urljoin, urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from video_platforms import platform_for_url


class PreviewMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        field = attributes.get('property') or attributes.get('name')
        if tag == 'meta' and field in {'og:image', 'og:image:secure_url', 'twitter:image'}:
            self.image = self.image or attributes.get('content')


@contextmanager
def _open(session, url, platform=None):
    for _ in range(6):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.port not in (None, 443)):
            raise ValueError('Preview URL must use public HTTPS')
        if platform is not None and platform_for_url(url) != platform:
            raise ValueError('Preview page redirected outside its platform')
        with session.get(url, stream=True, allow_redirects=False, timeout=(5, 10)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            response.raise_for_status()
            yield response
            return
    raise ValueError('Too many preview redirects')


def _bounded_chunks(response, limit):
    total = 0
    for chunk in response.iter_content(65536):
        total += len(chunk)
        if total > limit:
            raise ValueError('Preview exceeded its size limit')
        yield chunk


def download_preview(url, destination, limit):
    with requests.Session() as session:
        session.trust_env = False
        with _open(session, url, platform_for_url(url)) as page:
            if 'text/html' not in page.headers.get('Content-Type', '').lower():
                raise ValueError('The public post page did not return HTML')
            metadata = PreviewMetadata()
            metadata.feed(b''.join(_bounded_chunks(page, 2 * 1024 * 1024)).decode('utf-8', errors='replace'))
            if not metadata.image:
                raise ValueError('No public preview metadata was available')
            image = urljoin(page.url, metadata.image)
        with _open(session, image) as response:
            mime = response.headers.get('Content-Type', '').partition(';')[0].lower()
            suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}.get(mime)
            if not suffix:
                raise ValueError('Unsupported preview image format')
            with (destination / ('preview' + suffix)).open('wb') as output:
                for chunk in _bounded_chunks(response, limit):
                    output.write(chunk)
