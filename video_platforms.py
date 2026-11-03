"""Public video URL validation shared by the backend and MCP transport."""
from urllib.parse import urlsplit

HOSTS = {
    'instagram': {'instagram.com', 'www.instagram.com', 'm.instagram.com', 'instagr.am'},
    'facebook': {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com', 'fb.watch'},
    'tiktok': {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'},
    'linkedin': {'linkedin.com', 'www.linkedin.com', 'lnkd.in'},
    'x': {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com'},
}


def platform_for_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port not in (None, 443) or not parsed.path.strip('/')
                or any(ord(c) < 32 for c in url)):
            raise ValueError
        for platform, hosts in HOSTS.items():
            if parsed.hostname in hosts:
                return platform
    except (ValueError, TypeError):
        pass
    raise ValueError('Use a public HTTPS video URL from Instagram, Facebook, TikTok, LinkedIn, or X (Twitter).')
