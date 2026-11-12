"""Isolated yt-dlp worker. stdout/stderr are suppressed by the parent."""
import ipaddress
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit


def main():
    # Enforce the network destination at connection time, including redirects.
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def checked_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            if not ipaddress.ip_address(address[0].split('%')[0]).is_global:
                raise OSError('Non-public network destination blocked')
        return original_connect(sock, address)
    def checked_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            if not ipaddress.ip_address(address[0].split('%')[0]).is_global:
                raise OSError('Non-public network destination blocked')
        return original_connect_ex(sock, address)
    socket.socket.connect = checked_connect
    socket.socket.connect_ex = checked_connect_ex
    url, destination, limit = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
    if sys.argv[4:] == ['preview']:
        from social_preview import download_preview
        download_preview(url, destination, limit)
        return
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, MaxDownloadsReached
    def progress(data):
        if max(data.get('downloaded_bytes', 0), data.get('total_bytes') or 0) > limit:
            raise ValueError('Video size limit exceeded')
    def reject_live(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in {'is_live', 'is_upcoming'}:
            return 'Live streams are not supported'
    options = {
        'outtmpl': str(destination / 'video.%(ext)s'),
        'format': 'hd/sd/best[ext=mp4]/best',
        'noplaylist': True, 'playlist_items': '1', 'max_downloads': 1,
        'max_filesize': limit, 'socket_timeout': 15, 'retries': 0,
        'fragment_retries': 0, 'concurrent_fragment_downloads': 1,
        'progress_hooks': [progress], 'match_filter': reject_live,
        'quiet': True, 'no_warnings': True, 'cachedir': False,
        'enable_file_urls': False, 'overwrites': False,
        'hls_prefer_native': True, 'external_downloader': {'default': 'native'},
    }
    # TikTok currently rejects yt-dlp's default UA with an unexpected webpage.
    # A stable browser UA works with the existing Python request handlers; no
    # browser cookies, native networking handler, or account login is needed.
    if urlsplit(url).hostname in {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com',
                                 'vt.tiktok.com', 'vm.tiktok.com'}:
        options['http_headers'] = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/143.0.0.0 Safari/537.36'),
        }
    attempts = 2 if 'http_headers' in options else 1
    for attempt in range(attempts):
        try:
            with YoutubeDL(options) as downloader:
                downloader.download([url])
            break
        except MaxDownloadsReached:
            break
        except DownloadError as exc:
            if attempt + 1 == attempts or 'Unexpected response from webpage request' not in str(exc):
                raise
            # Retry only this extraction error, once, with a fresh cookie jar.
            # The parent still enforces one deadline across both attempts.
            options['http_headers']['User-Agent'] = (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) '
                'Gecko/20100101 Firefox/140.0')


if __name__ == '__main__':
    main()
