"""Client adapter tests never modify real client settings or use provider keys."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import tomllib

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import clients

ROOT = Path(__file__).resolve().parents[1]
LOCAL = [k for k in clients.CLIENTS if k != 'chatgpt']


@pytest.mark.parametrize('client', LOCAL)
def test_merge_backup_preserves_unrelated_and_repeated_install(tmp_path, client):
    target = tmp_path / ('config.toml' if client == 'codex' else 'config.json')
    if client == 'codex':
        original = '# retained comment\nmodel = "existing"\n[mcp_servers.other]\ncommand = "other.exe"\n'
    else:
        section = clients.CLIENTS[client][1]
        original = '// comment\n' + json.dumps({'unrelated': {'url': 'https://example.com/a,b}'}, section: {'other': {'command': 'other.exe'}}})
        original = original[:-1] + ',}'
    target.write_text(original, encoding='utf-8')
    backup = clients.install(client, target, ROOT, 18002)
    assert backup.read_text(encoding='utf-8') == original
    data = tomllib.loads(target.read_text()) if client == 'codex' else json.loads(target.read_text())
    section = clients.CLIENTS[client][1]
    assert data[section]['other']['command'] == 'other.exe'
    assert data[section][clients.NAME]['env'] == {'API_BASE_URL': 'http://127.0.0.1:18002'}
    first = target.read_bytes()
    clients.install(client, target, ROOT, 18002)
    assert target.read_bytes() == first


@pytest.mark.parametrize('client', LOCAL)
def test_conflicting_or_invalid_config_is_never_changed(tmp_path, client):
    target = tmp_path / 'settings'
    if client == 'codex':
        content = '[mcp_servers.insta-analyzer]\ncommand = "custom.exe"\n'
    else:
        content = json.dumps({clients.CLIENTS[client][1]: {clients.NAME: {'command': 'custom.exe'}}})
    for text in [content, 'invalid settings']:
        target.write_text(text)
        with pytest.raises((ValueError, tomllib.TOMLDecodeError)):
            clients.install(client, target, ROOT, 18002)
        assert target.read_text() == text
        assert not list(tmp_path.glob('*.insta-backup-*'))


def test_paths_require_explicit_project_and_use_appdata(tmp_path):
    assert clients.default_target('vscode') is None
    assert clients.default_target('chatgpt') is None
    assert clients.default_target('vscode', project=tmp_path) == tmp_path / '.vscode/mcp.json'
    assert clients.default_target('zed', appdata=tmp_path) == tmp_path / 'Zed/settings.json'


def test_jsonc_strings_are_not_modified():
    text = r'{/* comment */ "value": "//x,}/*y*/", "escaped": "\"//", "array": [1,],}'
    assert clients.parse_jsonc(text) == {'value': '//x,}/*y*/', 'escaped': '"//', 'array': [1]}


def test_all_nine_exported_commands_initialize_list_tools_and_call_backend(tmp_path):
    paths = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"total_jobs":7}')
        def log_message(self, *args):
            pass
    backend = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    clients.export_all(ROOT, backend.server_port, tmp_path)
    try:
        assert len(list(tmp_path.iterdir())) == 10
        for client in LOCAL:
            suffix = '.toml' if client == 'codex' else '.json'
            text = (tmp_path / (client + suffix)).read_text()
            data = tomllib.loads(text) if client == 'codex' else json.loads(text)
            config = data[clients.CLIENTS[client][1]][clients.NAME]
            assert set(config['env']) == {'API_BASE_URL'}
            result = asyncio.run(clients.check_connection(config))
            assert result['protocol'] == result['backend_tool'] == 'passed'
            assert len(result['tools']) == 5
            assert result['inside_application'] == 'not tested'
        assert paths == ['/api/jobs/stats'] * 9
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
