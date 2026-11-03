"""Isolated yt-dlp worker. stdout/stderr are suppressed by the parent."""
import ipaddress
import socket
import sys
from pathlib import Path


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
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import MaxDownloadsReached
    url, destination, limit = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
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
    with YoutubeDL(options) as downloader:
        try:
            downloader.download([url])
        except MaxDownloadsReached:
            pass


if __name__ == '__main__':
    main()
