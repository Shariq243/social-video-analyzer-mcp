"""Windows-specific regression tests; never register actual autostart or use real keys."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import launcher

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows integration")


def dummy_settings(**extra):
    return launcher.Settings(tunnel_id="tunnel_" + "0" * 32, runtime_key="test-runtime-not-real",
                             gemini_key="test-gemini-not-real", **extra)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_credentials_are_encrypted_and_round_trip(tmp_path):
    settings = dummy_settings()
    launcher.save_settings(settings, tmp_path)
    encrypted = (tmp_path / "credentials.dpapi").read_bytes()
    assert settings.runtime_key.encode() not in encrypted
    assert settings.gemini_key.encode() not in encrypted
    assert launcher.load_settings(tmp_path) == settings
    (tmp_path / "credentials.dpapi").write_bytes(b"invalid encrypted data")
    with pytest.raises(OSError):
        launcher.load_settings(tmp_path)


def test_validation_rejects_invalid_configuration():
    settings = dummy_settings()
    settings.tunnel_id = "not-a-tunnel"
    with pytest.raises(ValueError):
        settings.validate()
    settings.tunnel_id = "tunnel_" + "0" * 32
    settings.backend_port = settings.health_port
    with pytest.raises(ValueError):
        settings.validate()


def test_login_registration_is_per_user_and_contains_no_key(monkeypatch):
    writes = {}
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    fake = SimpleNamespace(HKEY_CURRENT_USER="current-user", REG_SZ=1,
                           CreateKey=lambda hive, path: Key(),
                           SetValueEx=lambda key, name, reserved, kind, value: writes.update({name: value}),
                           DeleteValue=lambda key, name: writes.pop(name))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    launcher.configure_autostart(True)
    command = writes[launcher.RUN_NAME]
    assert "pythonw.exe" in command and "supervise" in command
    assert "test-runtime" not in command and "test-gemini" not in command
    launcher.configure_autostart(False)
    assert not writes


def test_log_redaction(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "STATE", tmp_path)
    settings = dummy_settings()
    logger = launcher.safe_logger(settings)
    try:
        logger.info("remote error key=%s other=%s", settings.runtime_key, settings.gemini_key)
        for handler in logger.handlers: handler.flush()
        text = (tmp_path / "runtime.log").read_text(encoding="utf-8")
        assert settings.runtime_key not in text and settings.gemini_key not in text
        assert "[REDACTED]" in text
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


@pytest.mark.parametrize("mode", ["chatgpt", "local"])
def test_supervisor_starts_recovers_and_stops_owned_services(tmp_path, monkeypatch, mode):
    """Use real child processes and loopback listeners, with fake provider services."""
    monkeypatch.setattr(launcher, "STATE", tmp_path)
    settings = dummy_settings(backend_port=free_port(), health_port=free_port(), mode=mode)
    if mode == "local":
        settings.runtime_key = settings.tunnel_id = ""
        settings.validate()
        monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: pytest.fail("Local mode invoked tunnel setup"))
    monkeypatch.setattr(launcher, "load_settings", lambda: settings)
    original_running = launcher.is_running
    monkeypatch.setattr(launcher, "is_running", lambda: original_running(tmp_path))
    children = []
    original_spawn = launcher.spawn
    stub = """import http.server,sys
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
 def log_message(self,*args): pass
http.server.HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()
"""
    def spawn_stub(command, env, logger, label):
        port = settings.backend_port if label == "backend" else settings.health_port
        proc = original_spawn([sys.executable, "-u", "-c", stub, str(port)], env, logger, label)
        children.append(proc)
        return proc
    monkeypatch.setattr(launcher, "spawn", spawn_stub)
    thread = threading.Thread(target=launcher.supervise, daemon=True)
    def wait_for(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(0.2)
        status_text = (tmp_path / "status.json").read_text(encoding="utf-8") if (tmp_path / "status.json").exists() else "no status"
        log_text = (tmp_path / "runtime.log").read_text(encoding="utf-8") if (tmp_path / "runtime.log").exists() else "no log"
        raise AssertionError("Supervisor did not reach the expected state: " + status_text + "\n" + log_text)
    def ready():
        try:
            return json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["message"].startswith("Ready")
        except (OSError, ValueError): return False
    thread.start()
    try:
        wait_for(ready)
        assert launcher.is_running()
        # A second supervisor must exit without creating duplicate services.
        second = threading.Thread(target=launcher.supervise)
        second.start(); second.join(timeout=3)
        assert not second.is_alive()
        assert len(children) == (1 if mode == "local" else 2)
        children[0].terminate()
        children[0].wait(timeout=5)
        wait_for(lambda: len(children) >= (2 if mode == "local" else 4))
        wait_for(ready)
        launcher.stop_supervisor()
        thread.join(timeout=15)
        assert not thread.is_alive()
        assert all(child.poll() is not None for child in children)
        assert not launcher.is_running()
    finally:
        (tmp_path / "stop").touch()
        thread.join(timeout=15)
        for child in children:
            launcher.terminate_owned(child)
        logger = launcher.logging.getLogger("insta-launcher")
        for handler in list(logger.handlers):
            handler.close(); logger.removeHandler(handler)


def test_local_configs_have_no_credentials(tmp_path):
    settings = launcher.Settings("", "", "test-own-gemini-key", mode="local")
    settings.validate()
    launcher.export_client_configs(settings, tmp_path)
    for name, wrapper in [("cursor", "mcpServers"), ("claude", "mcpServers"), ("zed", "context_servers")]:
        text = (tmp_path / (name + ".json")).read_text()
        assert settings.gemini_key not in text
        server = json.loads(text)[wrapper]["insta-analyzer"]
        assert server["args"][-1] == "--stdio"
        assert Path(server["command"]).exists()
        assert Path(server["args"][0]).exists()
        assert server["env"] == {"API_BASE_URL": "http://127.0.0.1:18002"}

def test_generated_clients_initialize_and_call_backend(tmp_path):
    """Exercise the exact exported commands with an SDK client and HTTP backend."""
    import asyncio
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"total_jobs":7}')
        def log_message(self, *args): pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    settings = launcher.Settings("", "", "test-own-gemini-key", mode="local", backend_port=backend.server_port)
    launcher.export_client_configs(settings, tmp_path)
    async def check(config):
        async with stdio_client(StdioServerParameters(**config)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 5
                result = await session.call_tool("get_system_stats", {})
                assert not result.isError
                assert '7' in result.content[0].text
    try:
        for name, wrapper in [("cursor", "mcpServers"), ("claude", "mcpServers"), ("zed", "context_servers")]:
            config = json.loads((tmp_path / (name + ".json")).read_text())[wrapper]["insta-analyzer"]
            asyncio.run(check(config))
        assert requests == ["/api/jobs/stats"] * 3
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
